"""
harvest.py — the corpus raw harvest (Improvement-Loop Session 3a, commit 2).

Reads the FROZEN `corpus_manifest` and, per selected (league_id, season), pulls the raw Sleeper layer and
builds a per-league `join_season` — the first data that exercises the L0 collision isolation commit 1 just
built. It does NOT re-select, re-crawl, or re-filter: the manifest is the authority.

Per league-season:
  1. RAW PULL (idempotent, throttled via `_http`): teams (+rosters), roster_positions, league config,
     lineup_slots (derived), and every regular-season week's matchups + transactions. A league already on
     disk is skipped — a re-run pulls only what's missing (the leaguelogs.snapshot() precedent; standing
     instruction 8: persist, never re-derive from a moving source).
  2. JOIN: `join_nfl_sleeper_weekly.run` per regular-season week against nfl_stats + the PINNED registry
     (Session 1.7 — the join reads the pin, not the 24h cache), written league-keyed.
  3. TWO-WAY FLAG: carry `corpus_two_way_flags` (the ~2/season cross-position players) through as a
     first-class `is_two_way` boolean on the join output — FLAG, do not exclude (the scorer slices later).
  4. INTEGRITY RE-VERIFY (flag, don't drop): a league can have drifted since discovery, so re-check the
     PULLED data — every reg week has matchups and isn't all-zero; no team ≥3 empty/zero-starters weeks
     after wk2; roster count == num_teams. A failure is FLAGGED with a named reason, never harvested into a
     silent hole (standing instruction 1 — a clean zero is a bug).

Budget: every Sleeper call is throttled + counted; the incremental re-run cost is ≈ 0 because raw is
persisted. The historical-accuracy footnote (1.7 residual): the pinned registry is current-state, so a
2020-24 league's skill-eligibility label is *today's* — the material exposure is the two-way set, reported.

Usage:
    python3 -m application.data.corpus.harvest --pilot 5      # small cross-strata pilot + budget, no full pull
    python3 -m application.data.corpus.harvest               # the full 271-league harvest
    python3 -m application.data.corpus.harvest --strata matched
    python3 -m application.data.corpus.harvest --limit N     # first N targets (deterministic order)
    python3 -m application.data.corpus.harvest --throttle 0.15
"""
import argparse
import json
import sys
import time
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.fetchers import _http, sleeper
from application.data.transforms import compute_bracket_sim, derive_lineup_slots, join_nfl_sleeper_weekly

HARVEST_STRATA = ("matched", "generalization", "mine")

# --- call counter (wraps sleeper._get_json so every Sleeper call in the pull is counted) --------------
_CALLS = 0


def _install_counter():
    global _CALLS
    _CALLS = 0
    orig = sleeper._get_json

    def counting(url, params=None, **kw):
        global _CALLS
        _CALLS += 1
        return orig(url, params=params, **kw)

    sleeper._get_json = counting
    return orig


def _restore_counter(orig):
    sleeper._get_json = orig


# --- targets ------------------------------------------------------------------------------------------

def targets(strata=HARVEST_STRATA, limit=None) -> list[dict]:
    """The manifest rows to harvest, in a deterministic order (season, then league_id)."""
    man = data_layer.read_corpus_manifest()
    rows = [r for r in man.iter_rows(named=True) if r["stratum"] in strata]
    rows.sort(key=lambda r: (int(r["season"]), str(r["league_id"])))
    return rows[:limit] if limit else rows


def pilot_targets(n: int, strata=HARVEST_STRATA) -> list[dict]:
    """A small cross-strata sample: ~n/len(strata) leagues from each stratum (deterministic), so the pilot
    exercises every stratum's raw pull + budget rather than only the earliest season."""
    per = max(1, n // len(strata))
    picked = []
    for st in strata:
        picked.extend(targets((st,))[:per])
    return picked[:n] if n else picked


# --- raw pull (idempotent) ----------------------------------------------------------------------------

def _raw_present(lid: str, season: int) -> bool:
    """A league-season is considered raw-present when its config + teams + week-1 matchups all exist."""
    return (data_layer._league_settings_path(season, lid).exists()
            and data_layer._sleeper_teams_path(season, lid).exists()
            and data_layer._sleeper_matchups_path(season, 1, lid).exists())


def _pull_raw(lid: str, season: int) -> None:
    """Fetch the raw layer for one league-season (throttled, league-keyed). Overwrites — only called when
    the league is not already raw-present, so it is not re-pulled on a resumed run."""
    sleeper.fetch_league_config(lid, season)     # league_settings (scoring + playoff config)
    sleeper.fetch_roster_positions(lid, season)  # roster_positions
    derive_lineup_slots.run(season, league_id=lid)   # lineup_slots (derived from roster_positions)
    sleeper.fetch_teams(lid, season)             # teams (+ rosters, transiently)
    sleeper.backfill(lid, season, pace=0.0)      # all completed weeks' matchups + transactions (throttled by _http)


# --- join + two-way flag ------------------------------------------------------------------------------

def _reg_end(lid: str, season: int) -> int:
    """Regular-season end week = playoff_week_start - 1 (from the pulled league config), clamped to [1, 18].
    A missing OR garbled (< 2) playoff_week_start falls back to the shared sane default
    (`compute_bracket_sim._sane_playoff_week_start`, the single source of truth so harvest and the sim can't
    drift) — so a broken config harvests a real season instead of being clamped to a week-1-only stub."""
    try:
        pw = data_layer.read_playoff_settings(season, league_id=lid).get("playoff_week_start")
    except Exception:   # noqa: BLE001 — missing/garbled config → the sane default handles None
        pw = None
    start = compute_bracket_sim._sane_playoff_week_start(pw)
    return max(1, min(start - 1, 18))


def _build_join(lid: str, season: int, reg_end: int) -> int:
    """Join every regular-season week that has a matchups snapshot; return the count of weeks joined."""
    n = 0
    for wk in range(1, reg_end + 1):
        if data_layer._sleeper_matchups_path(season, wk, lid).exists():
            join_nfl_sleeper_weekly.run(season, wk, league_id=lid)
            n += 1
    return n


def _apply_two_way(lid: str, season: int, flag_ids: set) -> int:
    """Add/refresh the `is_two_way` boolean on the league's whole season join (deterministic). Returns the
    number of rows flagged. Existing columns are preserved — only the boolean is (re)computed. Rewrites the
    file ONLY when the flag actually changes, so a resumed run doesn't re-touch unchanged joins but a
    previously-mis-flagged join (e.g. built before a flag fix) is corrected rather than frozen."""
    if not data_layer.join_season_exists(season, league_id=lid):
        return 0
    j = data_layer.read_join_season(season, league_id=lid)
    new_flag = pl.col("sleeper_player_id").is_in(list(flag_ids))
    base = j.drop("is_two_way") if "is_two_way" in j.columns else j
    j2 = base.with_columns(new_flag.alias("is_two_way"))
    if ("is_two_way" not in j.columns) or (not j2["is_two_way"].equals(j["is_two_way"])):
        data_layer.write_join_season(j2, season, league_id=lid)
    return int(j2["is_two_way"].sum())


# --- integrity re-verify (flag, don't drop) -----------------------------------------------------------

def _integrity(lid: str, season: int, num_teams, reg_end: int) -> list[str]:
    """Re-check the PULLED data for the half-dead-league signals; return a list of named reasons (empty =
    clean). Computed entirely from persisted raw — no extra API calls."""
    reasons = []
    try:
        n_rosters = data_layer.read_sleeper_teams(season, league_id=lid).height
    except Exception:   # noqa: BLE001
        return ["teams_missing"]
    if num_teams is not None and n_rosters != int(num_teams):
        reasons.append(f"roster_count={n_rosters}!={num_teams}")

    empty_by_roster = defaultdict(int)
    complete = True
    for wk in range(1, reg_end + 1):
        p = data_layer._sleeper_matchups_path(season, wk, lid)
        if not p.exists():
            complete = False
            continue
        m = pl.read_parquet(p)
        pts = m["points"].fill_null(0.0) if "points" in m.columns else pl.Series([0.0])
        if num_teams is not None and (m.height < int(num_teams) or int((pts > 0).sum()) < int(num_teams)):
            complete = False
        if wk > 2:
            for row in m.iter_rows(named=True):
                starters = row.get("starters")
                empty = (starters in (None, "", "[]")) or ((row.get("points") or 0) == 0)
                if empty:
                    empty_by_roster[row.get("roster_id")] += 1
    if not complete:
        reasons.append("season_incomplete")
    if [rid for rid, n in empty_by_roster.items() if n >= 3]:
        reasons.append("abandonment")
    return reasons


# --- driver -------------------------------------------------------------------------------------------

def run(strata=HARVEST_STRATA, limit=None, throttle: float = 0.1, pilot=None) -> dict:
    _http.set_throttle(throttle)
    tgts = pilot_targets(pilot, strata) if pilot else targets(strata, limit)
    flags = data_layer.read_corpus_two_way_flags()
    # {season:int -> {player_id:str}}. Built row-wise on purpose: `group_by` iteration yields the key as a
    # TUPLE ((2025,)), so a dict keyed on it would silently miss an int-season lookup — a clean-zero bug.
    flag_by_season = defaultdict(set)
    for row in flags.iter_rows(named=True):
        flag_by_season[int(row["season"])].add(str(row["sleeper_player_id"]))

    orig = _install_counter()
    t0 = time.time()
    pulled = skipped = joined_leagues = 0
    flagged_leagues = []          # (league_id, season, [reasons])
    errored_leagues = []          # (league_id, season, error) — a per-league failure, ISOLATED not fatal
    two_way_hits = defaultdict(set)   # season -> {player_id} actually appearing on a harvested roster
    try:
        for i, r in enumerate(tgts, 1):
            lid, season, num_teams = str(r["league_id"]), int(r["season"]), r["num_teams"]
            tag = f"[{i}/{len(tgts)}] {r['stratum']:14} {lid} {season}"
            # Per-league isolation (the _http.isolate discipline): a transient Sleeper failure (SSL/read
            # timeout on one of ~10k calls) flags THAT league and the harvest continues — one blip must not
            # abort a 271-league pull. A re-run retries the errored leagues (no join → not skipped).
            try:
                # `join_season_exists` is the terminal artifact — only written after a league's raw was
                # pulled and joined, so it is the resumability signal (a re-run skips finished leagues).
                if data_layer.join_season_exists(season, league_id=lid):
                    skipped += 1
                    _apply_two_way(lid, season, flag_by_season.get(season, set()))
                    print(f"  {tag}  SKIP (already harvested)")
                else:
                    print(f"  {tag}  pulling…")
                    if not _raw_present(lid, season):
                        _pull_raw(lid, season)
                        pulled += 1
                    reg_end = _reg_end(lid, season)
                    _build_join(lid, season, reg_end)
                    joined_leagues += 1
                    hit = _apply_two_way(lid, season, flag_by_season.get(season, set()))
                    if hit:
                        print(f"      two-way rows flagged: {hit}")

                # record which flagged players actually appear on a harvested roster (exposure)
                if data_layer.join_season_exists(season, league_id=lid):
                    j = data_layer.read_join_season(season, league_id=lid)
                    if "is_two_way" in j.columns:
                        present = j.filter(pl.col("is_two_way"))["sleeper_player_id"].unique().to_list()
                        two_way_hits[season].update(present)

                reasons = _integrity(lid, season, num_teams, _reg_end(lid, season))
                if reasons:
                    flagged_leagues.append((lid, season, reasons))
                    print(f"      ⚠ FLAGGED (drifted): {';'.join(reasons)}")
            except Exception as exc:   # noqa: BLE001 — isolate one league's failure; a re-run retries it
                errored_leagues.append((lid, season, str(exc)[:120]))
                print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:120]}")
    finally:
        _restore_counter(orig)

    elapsed = time.time() - t0
    calls = _CALLS
    report = {
        "targets": len(tgts), "pulled": pulled, "skipped": skipped, "joined": joined_leagues,
        "calls": calls, "elapsed_s": round(elapsed, 1),
        "calls_per_pulled": round(calls / pulled, 1) if pulled else 0.0,
        "flagged_leagues": flagged_leagues,
        "errored_leagues": errored_leagues,
        "two_way_exposure": {s: sorted(v) for s, v in sorted(two_way_hits.items())},
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== harvest report ===")
    print(f"  targets={rep['targets']}  pulled={rep['pulled']}  skipped={rep['skipped']}  "
          f"joined={rep['joined']}")
    print(f"  Sleeper calls={rep['calls']}  wall-clock={rep['elapsed_s']}s  "
          f"calls/pulled-league={rep['calls_per_pulled']}  (incremental re-run ≈ 0 — raw persisted)")
    tw = rep["two_way_exposure"]
    n_tw = sum(len(v) for v in tw.values())
    print(f"  two-way exposure (flagged players on a harvested roster): {n_tw} across {tw}")
    fl = rep["flagged_leagues"]
    print(f"  drifted/flagged leagues (NOT dropped): {len(fl)}")
    for lid, season, reasons in fl:
        print(f"    {lid} {season}: {';'.join(reasons)}")
    er = rep.get("errored_leagues", [])
    print(f"  errored leagues (isolated; retried on re-run): {len(er)}")
    for lid, season, err in er:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Harvest the corpus raw layer + per-league join (Session 3a).")
    ap.add_argument("--strata", nargs="+", default=list(HARVEST_STRATA), choices=list(HARVEST_STRATA))
    ap.add_argument("--limit", type=int, default=None, help="first N targets (deterministic order)")
    ap.add_argument("--pilot", type=int, default=None, help="pilot: harvest N leagues across strata + report")
    ap.add_argument("--throttle", type=float, default=0.1, help="min gap (s) between Sleeper calls")
    a = ap.parse_args()
    run(strata=tuple(a.strata), limit=a.limit, throttle=a.throttle, pilot=a.pilot)


if __name__ == "__main__":
    main()
    sys.exit(0)
