"""Cold-league onboarding benchmark — what "connect your league" actually costs (P5/S0).

`weekly_refresh` ADVANCES a league that is already in the store. This measures the other half: the
first time the store ever sees a league — fetch the raw layer, join every week, compute the spine,
export the schedule, load it. That chain is what P5's connect flow will run on demand, and until now
nobody had timed it.

**It is a measuring instrument, not a pipeline.** It composes the existing steps (the same calls the
corpus harvest and the weekly refresh make) and times each one; it computes nothing of its own and
changes no constant. Two deliberate properties:

- **It never commits the load.** The COPY runs for real against Postgres inside a transaction that is
  then ROLLED BACK, so the timing is honest while the database is untouched. That also sidesteps
  `build_db.load_league`'s demo_manifest gate — cataloging a brand-new league is onboarding (P5/S4),
  not something a measurement should do. The only cost not captured is the COMMIT itself.
- **It refuses a warm league.** The pipeline's per-step on-disk gates are what make `weekly_refresh`
  idempotent, so re-timing a processed league measures the *gates* and looks impossibly fast. A
  league that is already present raises unless `--allow-warm` says that is the point (which is how
  the cold-vs-warm claim gets its evidence).

Deliberately NOT measured as per-league cost: `nfl_stats.refresh()` and the scoring-keyed substrate
(`projection_consensus` / `ros_player_band`). Those are shared across every league on a profile — the
first league pays for them, the rest inherit. Counting them per user is how you buy a machine you
don't need. `--substrate` times them separately, on their own terms.

S3 re-runs this UNCHANGED on the Fly worker so the two environments compare directly, so it stays
env-first (no `application/config.py`) and emits machine-readable JSON alongside the table.

    python -m application.data.serve.bench_cold_league --league <id> --season 2025
    python -m application.data.serve.bench_cold_league --league <id> --season 2025 --to-week 1
    python -m application.data.serve.bench_cold_league --substrate --season 2026 --scoring-keys ppr half
"""
import argparse
import json
import resource
import sys
import time
from collections import defaultdict
from pathlib import Path

import polars as pl
import psycopg

from application.api.db import database_url
from application.data import data_layer as dl
from application.data.corpus import compute_spine, harvest
from application.data.fetchers import _http, sleeper
from application.data.serve import build_db
from application.data.transforms import (build_substrate, compute_manager_features,
                                         compute_ros_player_band, export_schedule,
                                         join_nfl_sleeper_weekly)
from application.data.transforms._keys import scoring_key_from_settings

# ru_maxrss is bytes on macOS and kibibytes on Linux — normalise so a laptop run and a Fly run
# (the whole point of keeping this script re-runnable) are directly comparable.
_RSS_SCALE = 1 if sys.platform == "darwin" else 1024


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * _RSS_SCALE / 1e6


def _cpu_s() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


# --- instrumentation ----------------------------------------------------------------------------

class _CallLog:
    """Wrap the ONE HTTP chokepoint every fetcher routes through, so the API-call count and the
    network time are measured rather than estimated — and attributable per URL, which is what lets a
    week-1 connect be costed without re-fetching a whole season."""

    def __init__(self):
        self.calls: list[dict] = []
        self._orig = None

    def __enter__(self):
        self._orig = _http.get

        def counted(url, **kw):
            t = time.perf_counter()
            try:
                return self._orig(url, **kw)
            finally:
                self.calls.append({"url": url, "s": round(time.perf_counter() - t, 3),
                                   "phase": _CallLog.phase})
        _http.get = counted
        return self

    def __exit__(self, *exc):
        _http.get = self._orig

    phase = "-"   # set by the stage timer so each call is attributed to the step that made it

    def summary(self) -> dict:
        by_phase: dict[str, int] = defaultdict(int)
        for c in self.calls:
            by_phase[c["phase"]] += 1
        return {"n": len(self.calls), "network_s": round(sum(c["s"] for c in self.calls), 2),
                "by_phase": dict(by_phase)}


class _Stage:
    """Time one step: wall-clock, CPU (user+sys) and the peak RSS reached by its end.

    wall vs CPU is the CPU-bound / I/O-bound verdict, and that verdict decides whether a bigger
    machine buys anything at all — so it is measured per stage, not guessed for the total."""

    def __init__(self, report: dict, name: str):
        self.report, self.name = report, name

    def __enter__(self):
        _CallLog.phase = self.name
        self.t0, self.c0 = time.perf_counter(), _cpu_s()
        print(f"\n--- {self.name} ---")
        return self

    def __exit__(self, *exc):
        wall = time.perf_counter() - self.t0
        cpu = _cpu_s() - self.c0
        self.report["stages"][self.name] = {
            "wall_s": round(wall, 2), "cpu_s": round(cpu, 2),
            "cpu_frac": round(cpu / wall, 2) if wall > 0.01 else None,
            "peak_rss_mb": round(_peak_rss_mb(), 1),
        }
        _CallLog.phase = "-"
        print(f"--- {self.name}: {wall:.1f}s wall, {cpu:.1f}s cpu ---")


def _dir_bytes(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _league_dirs(lid: str, season: int) -> dict[str, Path]:
    """Every directory a league-scoped run writes — the growth measurement and the teardown both
    read this, so they can't drift apart."""
    return {"raw_sleeper": dl._sleeper_league_dir(season, lid),
            "joined": dl._join_league_dir(lid),
            "derived": dl._league_dir(lid)}


# --- cold-ness ----------------------------------------------------------------------------------

def assert_cold(lid: str, season: int) -> None:
    """A league is cold when the store has never seen it: absent from the registry, absent from
    EVERY catalog (all three served ones plus the frozen corpus manifest), and absent from all three
    on-disk league directories. Standing rule 1 in executable form — a fast total is a bug until
    this has passed, and P5/S4a's onboarder uses it as a precondition rather than a benchmark aid.

    It is also the "catalogued after" half of S4a's DoD: once `write_connected_league` has run, this
    function must REFUSE the same league. A coldness check that misses a catalog is a coldness check
    that lies, and until S4a it missed two."""
    warm = []
    # A synthetic league is generated, not harvested (P5/S2d), so "cold" is not even the right
    # question — there is nothing on Sleeper to time. Its on-disk directories would already trip the
    # check below, but incidentally rather than for a stated reason; this says the reason.
    if dl.is_synthetic(lid):
        raise SystemExit(
            f"league {lid} is SYNTHETIC — generated by build_demo_clone, not harvested from Sleeper. "
            "There is no cold-load to benchmark.")
    if dl.leagues_exists():
        known = dl.read_leagues().filter(pl.col("league_id").cast(str) == lid)
        if known.height:
            warm.append("leagues.parquet")
    # EVERY catalog, not just the demo manifest. `_catalog()` is the union of three parquets, so a
    # coldness check that reads one of them is a coldness check that lies — and it lied by two.
    # `synthetic_catalog` was never checked: the `is_synthetic` short-circuit above only covers the
    # hardcoded SYNTHETIC_LEAGUE_IDS literal, so a second clone would have slipped straight through.
    # `connected_catalog` is new in S4a and is the one that will actually fill up.
    for label, exists, read in (("demo_manifest.parquet", dl.demo_manifest_exists, dl.read_demo_manifest),
                                ("synthetic_catalog.parquet", dl.synthetic_catalog_exists, dl.read_synthetic_catalog),
                                ("connected_catalog.parquet", dl.connected_catalog_exists, dl.read_connected_catalog)):
        if exists() and read().filter(pl.col("league_id").cast(str) == lid).height:
            warm.append(label)
    # The frozen corpus manifest is not a served catalog, but a corpus league is emphatically not
    # cold — the spine ran on 269 of them — and its artifacts may have been swept while its manifest
    # row survived. Checking it here is what stops a "cold" run from being aimed at the corpus.
    if dl.corpus_manifest_exists():
        if dl.read_corpus_manifest().filter(pl.col("league_id").cast(str) == lid).height:
            warm.append("corpus_manifest.parquet (the frozen 271-league corpus)")
    warm += [f"{k} ({p})" for k, p in _league_dirs(lid, season).items() if p.exists()]
    if warm:
        raise SystemExit(
            f"league {lid} is NOT cold — present in: {', '.join(warm)}.\n"
            "Timing a warm league measures the pipeline's per-step gates, not the work. Pick a league "
            "the store has never seen (do NOT delete an existing one's artifacts — that risks the "
            "frozen corpus and the demo slate). Use --allow-warm only to demonstrate the gate skip.")


# --- the cold chain -----------------------------------------------------------------------------

def bench_league(lid: str, season: int, *, to_week: int | None, do_load: bool,
                 allow_warm: bool, dossiers: bool = False) -> dict:
    """Run the cold-onboarding chain for one league, timing every step.

    NOTE the chain itself is a finding: there is no single "onboard a cold league" entry point today.
    `weekly_refresh.refresh_league` assumes the raw layer already exists (its fetch stage only calls
    `sleeper.refresh`/`backfill`), so the cold half lives in `corpus/harvest`. P5/S4 needs a real one;
    this composes the same steps in the same order meanwhile.
    """
    report: dict = {"league_id": lid, "season": season, "to_week": to_week,
                    "platform": sys.platform, "stages": {}}
    if allow_warm:
        report["cold"] = False
        print(f"!! --allow-warm: {lid} may already be present; this measures the GATES, not the work")
    else:
        assert_cold(lid, season)
        report["cold"] = True

    before_bytes = _dir_bytes(dl._SNAPSHOT_DIR)

    with _CallLog() as calls:
        # 1 · FETCH — the raw layer, exactly as the harvest pulls it (config → roster_positions →
        # lineup_slots → teams → every completed week's matchups + transactions). Gated on
        # `_raw_present` for the same reason harvest gates it: a re-run must not re-pull.
        with _Stage(report, "fetch"):
            if harvest._raw_present(lid, season):
                print("  raw already present — skipped (this is the GATE, not the work)")
                report["fetch"] = "skipped (raw present)"
            else:
                harvest._pull_raw(lid, season)

        # The scoring key comes from THIS league's own settings. weekly_refresh._resolve_scoring_key
        # falls back to the is_mine league's key for anything absent from demo_manifest, which would
        # silently score a stranger's league on the owner's profile — never let a cold league take
        # that path.
        scoring_key = scoring_key_from_settings(dl.read_scoring_settings(season, league_id=lid))
        report["scoring_key"] = scoring_key
        substrate = dl._projection_consensus_path(season, scoring_key)
        report["substrate_present"] = substrate.exists()
        print(f"\nscoring_key = {scoring_key}   substrate present: {report['substrate_present']}")
        if not report["substrate_present"]:
            raise SystemExit(
                f"no {season} projection_consensus for scoring_key {scoring_key} ({substrate}).\n"
                "This league is the first on its key — build the substrate first (--substrate). That "
                "gap is itself the S5 preflight question.")

        reg_end = harvest._reg_end(lid, season)
        target = min(reg_end, to_week) if to_week else reg_end
        report["reg_end"], report["target_week"] = reg_end, target
        print(f"regular season ends wk{reg_end}; joining + computing through wk{target}")

        # 2 · JOIN — one week at a time, the authoritative player×week table. Starts after the
        # deepest week already joined, exactly like weekly_refresh, so a re-run is a no-op.
        with _Stage(report, "join"):
            jp = dl._join_season_path(season, lid)
            done = int(pl.read_parquet(jp, columns=["week"])["week"].max()) if jp.exists() else 0
            joined = 0
            for wk in range(done + 1, target + 1):
                if dl._sleeper_matchups_path(season, wk, lid).exists():
                    join_nfl_sleeper_weekly.run(season, wk, league_id=lid)
                    joined += 1
            report["weeks_joined"] = joined
            report["weeks_already_joined"] = done

        # 3 · BAND — scoring-keyed and shared, and bounded by the honest-band season exactly as the
        # weekly refresh bounds it. Below 2026 it is a deliberate no-op, not a missing step.
        with _Stage(report, "band"):
            if season >= build_db.FIRST_HONEST_BAND_SEASON:
                compute_ros_player_band.run(season, scoring_key=scoring_key)
                report["band"] = "rebuilt (shared substrate — NOT per-league cost)"
            else:
                report["band"] = f"skipped: season < FIRST_HONEST_BAND_SEASON ({build_db.FIRST_HONEST_BAND_SEASON})"
                print(f"  {report['band']}")

        # 4 · SPINE — the five decision reads. _compute_league accumulates its own per-read timing,
        # which is where the bracket_sim (10k sims PER as-of week) cost becomes visible.
        with _Stage(report, "spine"):
            spine_timing: dict = defaultdict(float)
            compute_spine._compute_league(lid, season, scoring_key, spine_timing)
            report["spine_reads"] = {k: round(v, 2) for k, v in sorted(spine_timing.items(),
                                                                       key=lambda kv: -kv[1])}
            print("  " + "  ".join(f"{k}={v:.1f}s" for k, v in report["spine_reads"].items()))

        # 5 · SCHEDULE — the league-scoped schedule export the served store needs.
        with _Stage(report, "schedule"):
            export_schedule.run(season, league_id=lid)

        # 6 · DOSSIERS (--dossiers) — the Manager Dossier surface, which `_compute_league` does NOT
        # cover. It is a CROSS-LEAGUE fan-out: every manager's comparable other leagues, throttled,
        # hundreds of calls. Measuring the base chain alone would report the cost of four of the five
        # surfaces and call it "connect your league".
        # The AI leg (write_manager_dossiers → one Haiku call per manager) is deliberately NOT run:
        # the manager count IS the call count, so it can be priced without spending, and the
        # measurement stays free of a live model call.
        if dossiers:
            with _Stage(report, "manager_activity"):
                if dl.manager_activity_exists(season, league_id=lid):
                    print("  manager_activity already present — skipped (gate, not work)")
                else:
                    sleeper.fetch_manager_activity(lid, season)
            with _Stage(report, "manager_features"):
                compute_manager_features.run(season, league_id=lid)
            feats = dl.read_manager_features(season, league_id=lid)
            report["dossier_ai_calls"] = feats.height
            print(f"  {feats.height} managers → {feats.height} Haiku calls a dossier write would make "
                  f"(NOT made here — counted so it can be priced)")

    report["sleeper_calls"] = calls.summary()
    report["sleeper_call_log"] = calls.calls

    # 6 · LOAD — the real DELETE+COPY against Postgres, then ROLLBACK. See the module docstring.
    if do_load:
        with _Stage(report, "load"):
            report["load"] = _time_load_rolled_back(lid, season, scoring_key)

    growth = {k: _dir_bytes(p) for k, p in _league_dirs(lid, season).items()}
    report["store_growth_bytes"] = {**growth, "total": sum(growth.values()),
                                    "whole_tree_delta": _dir_bytes(dl._SNAPSHOT_DIR) - before_bytes}
    report["peak_rss_mb"] = round(_peak_rss_mb(), 1)
    report["total_wall_s"] = round(sum(s["wall_s"] for s in report["stages"].values()), 2)
    report["total_cpu_s"] = round(sum(s["cpu_s"] for s in report["stages"].values()), 2)
    return report


def _time_load_rolled_back(lid: str, season: int, scoring_key: str) -> dict:
    """`load_league`'s work — DELETE the league's rows across the 14 tables, COPY its present slices —
    on a real connection, then ROLLBACK instead of commit.

    Uses build_db's own `DATASETS` / `_copy_slice_tx` / `_tables_present`, so this is the real COPY
    path rather than a second implementation of it; only the slice lookup (demo_manifest, which a
    brand-new league is deliberately not in) and the final commit differ.
    """
    counts: dict[str, int] = {}
    with psycopg.connect(database_url()) as conn:
        build_db._tables_present(conn)
        with conn.cursor() as cur:
            for ds in build_db.DATASETS:
                cur.execute(f'DELETE FROM "{ds.table}" WHERE league_id = %s', (lid,))
        for ds in build_db.DATASETS:
            p = ds.path(season, lid, scoring_key)
            if not p.exists():
                continue
            counts[ds.table] = build_db._copy_slice_tx(conn, ds.table, pl.read_parquet(p), lid, season)
        conn.rollback()      # never commit — the measurement leaves Postgres exactly as it found it
    total = sum(counts.values())
    print(f"  COPY'd {total} rows across {len(counts)} tables, then ROLLED BACK (database untouched)")
    return {"rows": total, "tables": counts, "committed": False}


def teardown(lid: str, season: int) -> None:
    """Remove every artifact a benchmarked league wrote, so the store is left as it was found.

    A measurement that leaves a scratch league behind has quietly become a load. Reads the SAME
    `_league_dirs` map the growth measurement uses, so the two can never disagree about what a run
    creates. It touches nothing shared: the registry, the catalog and the scoring-keyed substrate are
    not league directories and are never removed here.
    """
    import shutil
    for name, p in _league_dirs(lid, season).items():
        if p.exists():
            n = sum(1 for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p)
            print(f"  removed {name}: {p} ({n} files)")
        else:
            print(f"  {name}: already absent")
    assert_cold(lid, season)
    print(f"✓ {lid} is cold again")


# --- shared substrate ---------------------------------------------------------------------------

def bench_substrate(season: int, keys: list[str]) -> dict:
    """Time a substrate build — what the FIRST league on a new scoring key costs, once, for everyone.

    Guarded, because these are shared artifacts: the pre-build sha256 is recorded and re-checked
    after. The transforms are deterministic, so an identical hash is the expected result and a moved
    one is a finding (and a restore), not a shrug. Never pass a season below
    FIRST_HONEST_BAND_SEASON — those files are the frozen corpus.
    """
    if season < build_db.FIRST_HONEST_BAND_SEASON:
        raise SystemExit(
            f"refusing to rebuild substrate for {season}: below FIRST_HONEST_BAND_SEASON "
            f"({build_db.FIRST_HONEST_BAND_SEASON}) is the FROZEN CORPUS — the immutable out-of-sample "
            "certification baseline the L2 ledger was derived from. A re-backfill is the annual "
            "pipeline's job, not a benchmark's.")
    import hashlib

    def _sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"

    report: dict = {"season": season, "scoring_keys": keys, "stages": {}}
    for key in keys:
        watched = {"projection_consensus": dl._projection_consensus_path(season, key),
                   "ros_player_band": dl._ros_player_band_path(season, key)}
        before = {n: _sha(p) for n, p in watched.items()}
        with _Stage(report, f"substrate:{key}"):
            build_substrate.run([season], [key])
        after = {n: _sha(p) for n, p in watched.items()}
        moved = [n for n in before if before[n] != after[n]]
        report[f"{key}_deterministic"] = not moved
        if moved:
            print(f"  !! {key}: {moved} CHANGED on rebuild — not byte-deterministic; report it")
    report["total_wall_s"] = round(sum(s["wall_s"] for s in report["stages"].values()), 2)
    report["peak_rss_mb"] = round(_peak_rss_mb(), 1)
    return report


# --- output -------------------------------------------------------------------------------------

def print_table(report: dict) -> None:
    print("\n" + "=" * 74)
    title = (f"COLD-LEAGUE BENCHMARK — {report.get('league_id')} {report.get('season')} "
             f"({report.get('scoring_key', '?')}), wk1..{report.get('target_week', '?')}"
             if "league_id" in report else
             f"SUBSTRATE BENCHMARK — {report['season']} {report['scoring_keys']}")
    print(title)
    print("=" * 74)
    print(f"{'stage':<12}{'wall s':>9}{'cpu s':>9}{'cpu/wall':>10}{'peak RSS MB':>13}")
    for name, s in report["stages"].items():
        frac = f"{s['cpu_frac']:.2f}" if s["cpu_frac"] is not None else "-"
        print(f"{name:<12}{s['wall_s']:>9.2f}{s['cpu_s']:>9.2f}{frac:>10}{s['peak_rss_mb']:>13.1f}")
    print("-" * 74)
    print(f"{'TOTAL':<12}{report['total_wall_s']:>9.2f}{report.get('total_cpu_s', 0):>9.2f}")
    if "spine_reads" in report:
        print(f"\nspine split: " + ", ".join(f"{k} {v}s" for k, v in report["spine_reads"].items()))
    if "sleeper_calls" in report:
        c = report["sleeper_calls"]
        print(f"sleeper: {c['n']} calls, {c['network_s']}s network  {c['by_phase']}")
    if "dossier_ai_calls" in report:
        print(f"dossier AI calls a write would make: {report['dossier_ai_calls']} (not made)")
    if "store_growth_bytes" in report:
        g = report["store_growth_bytes"]
        print(f"store growth: {g['total'] / 1e6:.2f} MB for this league "
              f"(whole tree +{g['whole_tree_delta'] / 1e6:.2f} MB)")
    print(f"peak RSS: {report['peak_rss_mb']} MB")
    print("=" * 74)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--league", help="a league_id the store has NEVER seen")
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--to-week", type=int, default=None,
                    help="cap join+spine at this week (models an early-season connect)")
    ap.add_argument("--no-load", action="store_true", help="skip the (rolled-back) Postgres load timing")
    ap.add_argument("--allow-warm", action="store_true",
                    help="permit an already-present league — measures the gate skip, not the work")
    ap.add_argument("--teardown", action="store_true",
                    help="remove the league's artifacts and prove it is cold again")
    ap.add_argument("--dossiers", action="store_true",
                    help="also time the Manager Dossier chain (cross-league fan-out + features)")
    ap.add_argument("--substrate", action="store_true",
                    help="time a shared substrate build instead of a league")
    ap.add_argument("--scoring-keys", nargs="+", default=["ppr", "half"])
    ap.add_argument("--json", default=None, help="write the full report here")
    a = ap.parse_args()

    if a.teardown:
        if not a.league:
            ap.error("--teardown needs --league")
        teardown(a.league, a.season)
        return
    if a.substrate:
        report = bench_substrate(a.season, a.scoring_keys)
    else:
        if not a.league:
            ap.error("--league is required (or use --substrate)")
        report = bench_league(a.league, a.season, to_week=a.to_week, do_load=not a.no_load,
                              allow_warm=a.allow_warm, dossiers=a.dossiers)
    print_table(report)
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))
        print(f"\nreport → {a.json}")


if __name__ == "__main__":
    main()
