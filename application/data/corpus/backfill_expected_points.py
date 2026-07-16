"""
backfill_expected_points.py — Session 3c commit 2: light up §1 Quality across the matched corpus.
Session 3d reuses it verbatim (`--stratum generalization`) to light Quality on the 48 generalization joins.

Two ADDITIVE steps over the stratum's 2020–2024 leagues (2025 already carries *_exp from its post-join build —
left entirely untouched here; verified: gen 2025 joins carry 14/14 *_exp, 2020–24 carry 0/14). Runs on the
C1-augmented `nfl_stats` (which now carries the 14 *_exp components for every season):

  1. APPEND *_exp onto each league's `join_season` — read the existing join, left-join the augmented
     `nfl_stats` *_exp on **(player_id/gsis_id, week)** + fill_null(0.0), write back. Keying on the gsis
     (not sleeper_player_id) is both faithful and safe: each existing join row already carries the gsis of
     the nfl row that supplied its stats (the 3a star-join), and (gsis, week) is unique — so every row gets
     exactly its own source row's *_exp with no cartesian expansion. Mirrors `harvest._apply_two_way`:
     additive, row-count + pre-existing-column preserving, idempotent (rewrite only when it actually adds).
     Does **not** re-run the join logic (that would needlessly re-touch the 1.7 pinned-registry path).

  2. RE-RUN `player_signal` for each non-degenerate league — `compute_player_signal` is already
     `has_exp`-aware, so with *_exp now in the join the §1 Quality axis (quality_rate / luck /
     point_correlation) populates; every other column is byte-identical (the core is *_exp-independent). The
     degenerate matched league (`1124876463083261952`, 2024 — playoff_week_start unset, the 3b flag) has no
     spine and is skipped (stays flagged, mirroring compute_spine).

The 4 other spine reads (production_vor / true_rank / positional_depth / bracket_odds) read neither *_exp
nor player_signal, so their persisted 3b files are left untouched — blast radius contained
(check_expected_points proves recompute-from-the-augmented-join == persisted).

Idempotent + per-league failure isolated (the compute_spine/harvest precedent). Budget reported.

Usage:
    python3 -m application.data.corpus.backfill_expected_points --pilot 3   # small sample + budget
    python3 -m application.data.corpus.backfill_expected_points             # all matched 2020–2024
    python3 -m application.data.corpus.backfill_expected_points --stratum generalization   # 3d: gen joins
"""
import argparse
import contextlib
import io
import sys
import time
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.transforms import compute_player_signal
from application.data.transforms._scoring import EXP_COMPONENT_COLS

# 2025 already carries *_exp (built after the fetcher join was added) — verify-untouched, never re-touched.
BACKFILL_SEASONS = (2020, 2021, 2022, 2023, 2024)


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def targets(stratum="matched", limit=None) -> list[dict]:
    """A stratum's manifest rows for the backfill seasons (2020–24), deterministic order (season, league_id).
    Defaults to `matched` (3c's behavior); `generalization` lights §1 Quality on the gen joins (3d)."""
    man = data_layer.read_corpus_manifest()
    rows = [r for r in man.iter_rows(named=True)
            if r["stratum"] == stratum and int(r["season"]) in BACKFILL_SEASONS]
    rows.sort(key=lambda r: (int(r["season"]), str(r["league_id"])))
    return rows[:limit] if limit else rows


def _append_exp_to_join(lid: str, season: int) -> str:
    """Additively append the 14 *_exp columns onto the league's whole-season join, sourced from the augmented
    nfl_stats via a left join on (player_id/gsis_id, week) + fill_null(0.0). Returns a short status:
    'added' / 'refreshed' / 'unchanged' / 'absent'. Row count + every pre-existing column are preserved
    (asserted); the file is rewritten ONLY when the *_exp actually change (idempotent resume)."""
    if not data_layer.join_season_exists(season, league_id=lid):
        return "absent"
    j = data_layer.read_join_season(season, league_id=lid)
    base = j.drop([c for c in EXP_COMPONENT_COLS if c in j.columns])   # clean slate → idempotent re-run
    exp_src = data_layer.read_nfl_stats(season).select(
        "player_id", pl.col("week").cast(base.schema["week"]), *EXP_COMPONENT_COLS
    )
    aug = base.join(
        exp_src, on=["player_id", "week"], how="left", maintain_order="left"
    ).with_columns([pl.col(c).fill_null(0.0) for c in EXP_COMPONENT_COLS])

    # Additive-only guarantees: no row added/removed, every pre-existing column byte-identical to disk.
    if aug.height != base.height:
        raise RuntimeError(f"append_exp {lid} {season}: row count {base.height}→{aug.height} — not additive")
    moved = [c for c in base.columns if not aug[c].equals(base[c])]
    if moved:
        raise RuntimeError(f"append_exp {lid} {season}: pre-existing columns moved {moved[:5]} — not additive")

    had = all(c in j.columns for c in EXP_COMPONENT_COLS)
    same = had and all(aug[c].equals(j[c]) for c in EXP_COMPONENT_COLS)
    if same:
        return "unchanged"
    data_layer.write_join_season(aug, season, league_id=lid)
    return "refreshed" if had else "added"


def run(stratum="matched", limit=None, pilot=None) -> dict:
    tgts = targets(stratum, pilot) if pilot else targets(stratum, limit)
    t0 = time.time()
    join_status = defaultdict(int)          # added/refreshed/unchanged/absent
    signal_recomputed = flagged = 0
    flagged_leagues, errored_leagues = [], []
    timing = defaultdict(float)

    for i, r in enumerate(tgts, 1):
        lid, season = str(r["league_id"]), int(r["season"])
        tag = f"[{i}/{len(tgts)}] {lid} {season}"
        try:
            t = time.time()
            st = _append_exp_to_join(lid, season)
            timing["append_join"] += time.time() - t
            join_status[st] += 1

            reason = compute_spine._degenerate_reason(lid, season)
            if reason:
                flagged += 1
                flagged_leagues.append((lid, season, reason))
                print(f"  {tag}  join:{st:9}  ⚠ FLAGGED (degenerate, player_signal skipped): {reason}")
                continue

            t = time.time()
            with _quiet():
                compute_player_signal.run(season, league_id=lid)
            timing["player_signal"] += time.time() - t
            signal_recomputed += 1
            print(f"  {tag}  join:{st:9}  player_signal recomputed")
        except Exception as exc:   # noqa: BLE001 — isolate one league; a re-run retries it
            errored_leagues.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:160]}")

    report = {
        "stratum": stratum,
        "targets": len(tgts), "join_status": dict(join_status),
        "signal_recomputed": signal_recomputed, "flagged": flagged,
        "elapsed_s": round(time.time() - t0, 1),
        "timing": {k: round(v, 1) for k, v in timing.items()},
        "flagged_leagues": flagged_leagues, "errored_leagues": errored_leagues,
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print(f"\n=== expected-points backfill report ({rep.get('stratum', 'matched')} 2020–2024) ===")
    print(f"  targets={rep['targets']}  join={rep['join_status']}  "
          f"player_signal recomputed={rep['signal_recomputed']}  flagged={rep['flagged']}")
    print(f"  wall-clock={rep['elapsed_s']}s  timing={rep['timing']}")
    for lid, season, reason in rep["flagged_leagues"]:
        print(f"    flagged: {lid} {season} — {reason}")
    er = rep["errored_leagues"]
    print(f"  errored leagues (isolated; retried on re-run): {len(er)}")
    for lid, season, err in er:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Append *_exp to a stratum's joins + re-run player_signal (3c/3d).")
    ap.add_argument("--stratum", default="matched", choices=["matched", "generalization", "mine"],
                    help="which stratum to backfill (default matched — 3c; generalization — 3d)")
    ap.add_argument("--limit", type=int, default=None, help="first N targets (deterministic order)")
    ap.add_argument("--pilot", type=int, default=None, help="first N targets + budget (validate plumbing)")
    a = ap.parse_args()
    run(stratum=a.stratum, limit=a.limit, pilot=a.pilot)


if __name__ == "__main__":
    main()
    sys.exit(0)
