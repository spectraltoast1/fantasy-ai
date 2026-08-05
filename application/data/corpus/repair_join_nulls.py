"""
repair_join_nulls.py — one-off, league-scoped repair of two null columns on a persisted join.

Two independent defects left nulls on `season_<year>.parquet`. Neither is fixable by re-joining, and
re-joining would be actively worse (see "Why not a re-join"), so this repairs the two COLUMNS in
place and touches nothing else.

  1. `matchup_result` null on `audit_join` repair rows. `_build_zero_stat_row` zero-fills only NUMERIC
     dtypes, so every post-join String/Boolean column fell through. Fixed at source in `audit_join`;
     this closes the rows already on disk.
  2. `is_two_way` null on weeks appended AFTER the corpus harvest. `join_nfl_sleeper_weekly` never
     emits that column, and the per-week append concats `how="diagonal"`, so a scoped week-advance
     null-fills it. `harvest._apply_two_way` is its only writer and was never re-run. Fixed at source
     in `weekly_refresh`; this closes the weeks already on disk.

WHY NOT A RE-JOIN. The repair rows exist *because* the join excludes those players (no `nfl_stats`
row -> null position -> the SKILL_POSITIONS filter drops them to remainders), so a re-join reproduces
the exclusion rather than fixing it — it would DELETE the rows. And the leagues carrying these nulls
are in the frozen corpus that the immutable L2 ledger grades against, so re-emitting `matchup_result`
for every row under the post-P2 rule would break ledger reproducibility for no benefit.

WHAT MAKES THIS SAFE. Both operations are single-column and null-only:
  * `matchup_result` is filled ONLY where null (`audit_join.fill_null_matchup_result`), so an existing
    verdict can never move — verdict-neutrality holds by construction, and is asserted anyway.
  * `is_two_way` is recomputed by `harvest._apply_two_way`, which preserves every other column and
    rewrites only when the flag actually changes.
Row count is invariant, and every other column is asserted value-identical before anything is written.

Usage:
    python3 -m application.data.corpus.repair_join_nulls --league-id <id> --season <yr>   # dry-run
    python3 -m application.data.corpus.repair_join_nulls --league-id <id> --season <yr> --write
"""
import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import harvest
from application.data.transforms import audit_join

_UNTOUCHED_EXEMPT = ("matchup_result", "is_two_way")


def _fill_results(df: pl.DataFrame) -> pl.DataFrame:
    """Apply the null-only verdict fill per WEEK — `result_expr` groups on `matchup_id` alone, which is
    only correct within a single week (two weeks' matchup 1 would otherwise merge into one group)."""
    if "matchup_result" not in df.columns:
        return df
    parts = [audit_join.fill_null_matchup_result(g)
             for _k, g in sorted(df.group_by("week"), key=lambda kv: int(kv[0][0]))]
    return pl.concat(parts, how="vertical").select(df.columns)


def _assert_untouched(before: pl.DataFrame, after: pl.DataFrame, label: str) -> None:
    """Every column except the two being repaired must be value-identical, and the row count invariant.

    Value-identical, not byte-identical: polars' parquet writer is physically non-deterministic, so a
    byte hash flakes (~8%) — the property that matters is the VALUES. Sorting on a stable key makes the
    comparison order-insensitive, since the per-week regroup above may permute rows.
    """
    if before.height != after.height:
        raise SystemExit(f"✖ {label}: row count moved {before.height} -> {after.height}")
    if before.columns != after.columns:
        raise SystemExit(f"✖ {label}: column set/order moved")
    key = ["season", "week", "roster_id", "sleeper_player_id"]
    cols = [c for c in before.columns if c not in _UNTOUCHED_EXEMPT]
    b = before.select(cols).sort(key)
    a = after.select(cols).sort(key)
    if not b.equals(a):
        raise SystemExit(f"✖ {label}: a column outside {_UNTOUCHED_EXEMPT} changed — refusing to write")

    # The verdict half is stronger than "untouched": an EXISTING verdict must not move either.
    graded = before.filter(pl.col("matchup_result").is_not_null()).select(key + ["matchup_result"]).sort(key)
    after_same = (after.join(graded.drop("matchup_result"), on=key, how="inner")
                  .select(key + ["matchup_result"]).sort(key))
    if not graded.equals(after_same):
        raise SystemExit(f"✖ {label}: an ALREADY-GRADED matchup_result changed — that is a finding, stop")


def run(league_id: str, season: int, write: bool = False) -> dict:
    tag = "REPAIRING" if write else "DRY-RUN (no writes)"
    print(f"=== {tag}: {league_id} / {season} ===")
    if not data_layer.join_season_exists(season, league_id=league_id):
        raise SystemExit(f"✖ no join_season for {league_id} / {season}")

    before = data_layer.read_join_season(season, league_id=league_id)
    mr_null = before["matchup_result"].is_null().sum() if "matchup_result" in before.columns else 0
    tw_null = before["is_two_way"].is_null().sum() if "is_two_way" in before.columns else 0
    print(f"  before: {before.height} rows · matchup_result null={mr_null} · is_two_way null={tw_null}")

    if mr_null:
        print("  rows to fill:")
        for r in before.filter(pl.col("matchup_result").is_null()).iter_rows(named=True):
            print(f"    wk{r['week']} roster={r['roster_id']} matchup={r['matchup_id']} "
                  f"{r['player_display_name']} (sleeper_id={r['sleeper_player_id']})")

    after = _fill_results(before)
    _assert_untouched(before, after, f"{league_id} {season}")
    filled = mr_null - (after["matchup_result"].is_null().sum() if "matchup_result" in after.columns else 0)
    if mr_null:
        for r in after.filter(pl.col("sleeper_player_id").is_in(
                before.filter(pl.col("matchup_result").is_null())["sleeper_player_id"].unique().to_list())
        ).iter_rows(named=True):
            if r["matchup_result"] is not None and r["roster_total_points"] is not None:
                print(f"    -> wk{r['week']} roster={r['roster_id']} verdict={r['matchup_result']}")
    print(f"  matchup_result: {filled} null(s) filled, {mr_null - filled} left null "
          f"(ungradeable — no matchup_id, a bye, or an unplayed week)")

    if write:
        data_layer.write_join_season(after, season, league_id=league_id)
        flag_ids = audit_join._two_way_ids(season)
        hit = harvest._apply_two_way(league_id, season, flag_ids)
        final = data_layer.read_join_season(season, league_id=league_id)
        print(f"  is_two_way: re-applied from the corpus reference — {hit} row(s) flagged, "
              f"{final['is_two_way'].is_null().sum() if 'is_two_way' in final.columns else 0} null(s) left")
        print(f"  done — {final.height} rows, every other column value-identical")
    else:
        print(f"  is_two_way: would re-apply harvest._apply_two_way (expect {tw_null} null(s) cleared)")
        print("  (dry-run — nothing written)")
    return {"rows": before.height, "matchup_result_filled": filled, "is_two_way_null_before": tw_null}


def main():
    ap = argparse.ArgumentParser(description="Repair null matchup_result / is_two_way on one league-season.")
    ap.add_argument("--league-id", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--write", action="store_true", help="actually write (default is a dry run)")
    a = ap.parse_args()
    run(a.league_id, a.season, write=a.write)
    sys.exit(0)


if __name__ == "__main__":
    main()
