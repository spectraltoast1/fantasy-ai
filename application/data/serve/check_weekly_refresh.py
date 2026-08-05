"""
check_weekly_refresh.py — the weekly advance must not silently rot the join's columns.

The defect this exists for: `join_nfl_sleeper_weekly` does not emit `is_two_way` (it is a corpus-era
column `harvest._apply_two_way` owns), and the per-week append concats `how="diagonal"`. So a week
joined by the weekly advance arrives WITHOUT the column and gets NULL-filled. That is exactly how the
is_mine 2025 league ended up with 147 null flags in week 5 after P2/S2's scoped extension, and
`check_harvest` check 5 red — and it would have recurred on EVERY weekly advance of the 2026 season,
because nothing in `weekly_refresh` re-applied the flag.

  1. ADVANCE KEEPS THE FLAG — stage a league under a scratch id, truncate its join to week N-1, then
     advance it with the real `weekly_refresh` step and assert the joined artifact has ZERO null
     `is_two_way` and the flag matches the corpus reference.
  2. NO-OP IS A NO-OP — re-applying when nothing moved rewrites nothing (`_apply_two_way`'s own guard),
     so a quiet week stays quiet.

Prove-it-bites (a gate that can't fail is not a gate): the SAME staged advance with the re-apply step
omitted — i.e. exactly the code as it shipped — must produce nulls and fail check 1.

Everything is staged under a scratch league id and torn down in a `finally`; canonical data is never
read-modify-written. (The worktree's `snapshots` is a symlink into main's single store, so an unstaged
write would hit real corpus data — same hazard `check_harvest._check_determinism` guards against.)

Run: application/venv/bin/python -m application.data.serve.check_weekly_refresh
"""
import contextlib
import io
import shutil
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import harvest
from application.data.transforms import audit_join, join_nfl_sleeper_weekly

_TMP_LEAGUE = "__WEEKLYREFRESH__"
# The is_mine league: the one that actually carries a two-way flagged player (Travis Hunter, 2025),
# so the check exercises a real True rather than an all-False frame that would pass vacuously.
_SRC_LEAGUE, _SRC_SEASON = "1182101676608823296", 2025


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:58} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _stage(season: int, weeks: list) -> None:
    for w in weeks:
        dst = data_layer._sleeper_matchups_path(season, w, _TMP_LEAGUE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data_layer._sleeper_matchups_path(season, w, _SRC_LEAGUE), dst)


def _teardown(season: int) -> None:
    shutil.rmtree(data_layer._sleeper_league_dir(season, _TMP_LEAGUE), ignore_errors=True)
    shutil.rmtree(data_layer._join_league_dir(_TMP_LEAGUE), ignore_errors=True)


def _advance(season: int, weeks: list, target: int, *, reapply: bool) -> pl.DataFrame:
    """Join weeks 1..target-1, apply the flag (as the harvest would), then advance ONE week — with or
    without the re-apply step. `reapply=False` reproduces the code exactly as it shipped."""
    flag_ids = audit_join._two_way_ids(season)
    with contextlib.redirect_stdout(io.StringIO()):
        for w in weeks:
            if w < target:
                join_nfl_sleeper_weekly.run(season, w, league_id=_TMP_LEAGUE)
        # the harvest's own pass — this is the state a league is in before a weekly advance
        harvest._apply_two_way(_TMP_LEAGUE, season, flag_ids)
        # ...the advance itself
        join_nfl_sleeper_weekly.run(season, target, league_id=_TMP_LEAGUE)
        if reapply:
            harvest._apply_two_way(_TMP_LEAGUE, season, flag_ids)
    return data_layer.read_join_season(season, league_id=_TMP_LEAGUE)


def check() -> bool:
    results: list = []
    print("=== check_weekly_refresh — a weekly advance must not rot is_two_way ===\n")

    season = _SRC_SEASON
    src = data_layer.read_join_season(season, league_id=_SRC_LEAGUE)
    weeks = [w for w in sorted(int(w) for w in src["week"].unique().to_list())
             if data_layer._sleeper_matchups_path(season, w, _SRC_LEAGUE).exists()]
    target = weeks[-1]
    flag_ids = audit_join._two_way_ids(season)
    print(f"  staged from {_SRC_LEAGUE} {season}: weeks {weeks}, advancing to wk{target}")
    print(f"  corpus two-way reference for {season}: {sorted(flag_ids)}\n")

    try:
        _teardown(season)
        _stage(season, weeks)

        print("  1 — the advance keeps the flag:")
        j = _advance(season, weeks, target, reapply=True)
        n_null = int(j["is_two_way"].null_count()) if "is_two_way" in j.columns else -1
        _ok("is_two_way present after the advance", "is_two_way" in j.columns, results)
        _ok("zero null is_two_way after the advance", n_null == 0, results, f"{n_null} nulls")
        expect = j["sleeper_player_id"].is_in(sorted(flag_ids))
        _ok("flag matches the corpus reference", j["is_two_way"].equals(expect), results,
            f"{int(j['is_two_way'].sum() or 0)} flagged")
        # the advanced week specifically — the one the diagonal concat null-fills
        adv = j.filter(pl.col("week") == target)
        _ok(f"the advanced week (wk{target}) carries a real flag",
            adv.height > 0 and int(adv["is_two_way"].null_count()) == 0, results,
            f"{adv.height} rows, {int(adv['is_two_way'].sum() or 0)} flagged")

        print("  2 — re-applying when nothing moved is a no-op:")
        before = data_layer.read_join_season(season, league_id=_TMP_LEAGUE)
        with contextlib.redirect_stdout(io.StringIO()):
            harvest._apply_two_way(_TMP_LEAGUE, season, flag_ids)
        after = data_layer.read_join_season(season, league_id=_TMP_LEAGUE)
        cols = before.columns
        _ok("second re-apply changes nothing",
            before.select(cols).sort(cols).equals(after.select(cols).sort(cols)), results)

        print("  PROVE-BITES (the same advance, with the re-apply omitted — the shipped code):")
        _teardown(season)
        _stage(season, weeks)
        bad = _advance(season, weeks, target, reapply=False)
        bad_null = int(bad["is_two_way"].null_count()) if "is_two_way" in bad.columns else -1
        _ok("omitting the re-apply DOES null the flag (check-1 bites)", bad_null > 0, results,
            f"{bad_null} nulls in wk{target}")
        _ok("...and the reference comparison fails too",
            not bad["is_two_way"].equals(bad["sleeper_player_id"].is_in(sorted(flag_ids))), results)
    finally:
        _teardown(season)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — a weekly advance keeps is_two_way applied.")
    return ok


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
