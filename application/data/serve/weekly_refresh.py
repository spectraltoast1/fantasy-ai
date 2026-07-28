"""
Weekly refresh orchestrator (P2/S2) — advance ONE league to a target week.

The live cadence that un-freezes the app: fetch the league's current state (Sleeper rosters/matchups/
transactions) + weekly NFL stats + Sleeper projections → join → recompute the spine → **scoped** Postgres
load (``build_db.load_league`` — one league, one transaction, others untouched). The serve seam
(``reads._as_of_slice`` defaults to ``max(as_of_week)`` per league) then surfaces the new week with no app
change. Every sub-step already exists and is individually idempotent; this is the single-league driver that
sequences them, modeled on ``corpus/compute_demo_slices`` (per-step on-disk gates + a report).

Two modes:
  --live       current week from Sleeper /state/nfl — the 2026 in-season path.
  --week N      replay a season that already has weeks (e.g. is_mine 2025) to BUILD + PROVE the machinery
               now, in preseason. Advancing weeks [1..4] → [1..5] is exactly the un-freeze mechanic.

Preseason / no-actuals weeks are graceful (consistent with S1's forward path): a week with rosters +
projections but no realized stats advances on projections-only (the join zero-fills actuals — nothing is
fabricated); a week with no matchups snapshot at all advances nothing.

Usage:
    # replay the is_mine 2025 league from week 4 to week 5 (build/prove)
    application/venv/bin/python -m application.data.serve.weekly_refresh --season 2025 --week 5
    # live in-season (2026, once games start)
    application/venv/bin/python -m application.data.serve.weekly_refresh --live
"""

import argparse
import sys
from collections import defaultdict

import polars as pl

from application.api import db
from application.data import data_layer
from application.data.fetchers import nfl_stats, sleeper
from application.data.serve import build_db
from application.data.transforms import join_nfl_sleeper_weekly
from application.data.corpus import compute_spine
from application.shared import league_resolver


def _resolve_scoring_key(lid: str, season: int) -> str:
    """The league's scoring_key from the demo_manifest slice (falls back to the is_mine default)."""
    for l, s, sk in build_db._slices():
        if l == lid and s == season:
            return sk
    return data_layer._active_league(season)[1]


def _joined_max_week(lid: str, season: int) -> int:
    """Deepest week currently in the league's join season file (0 if none) — where the advance starts."""
    p = data_layer._join_season_path(season, lid)
    if not p.exists():
        return 0
    weeks = pl.read_parquet(p, columns=["week"])["week"]
    return int(weeks.max()) if weeks.len() else 0


def _spine_covers(lid: str, season: int, week: int) -> bool:
    """The persisted spine already reaches `week` (max as_of_week ≥ week) — recompute is then a no-op."""
    p = data_layer._production_vor_path(season, lid)
    if not p.exists():
        return False
    a = pl.read_parquet(p, columns=["as_of_week"])["as_of_week"]
    return a.len() > 0 and int(a.max()) >= week


def _db_max_as_of(lid: str) -> int | None:
    """The league's deepest as_of_week already in Postgres (None if absent) — to no-op an up-to-date load."""
    r = db.fetch_all('SELECT max(as_of_week) AS mx FROM "production_vor" WHERE league_id = %(l)s', {"l": lid})
    return r[0]["mx"] if r and r[0]["mx"] is not None else None


def _has_actuals(season: int, week: int) -> bool:
    if not data_layer._nfl_stats_path(season).exists():
        return False
    return week in set(data_layer.read_nfl_stats(season)["week"].to_list())


def refresh_league(lid: str | None = None, season: int | None = None, *,
                   target_week: int | None = None, live: bool = False, do_load: bool = True) -> dict:
    """Advance one league to `target_week` (or the live current week). Returns a report of actions taken."""
    if live:
        state = sleeper._get_nfl_state()
        season = int(state["season"])
        target_week = int(state.get("leg", 0) or 0)
    if season is None:
        raise SystemExit("--season is required (or --live)")
    lid = lid or league_resolver.resolve_league_id(season)
    scoring_key = _resolve_scoring_key(lid, season)

    report: dict = {"league_id": lid, "season": season, "target_week": target_week,
                    "scoring_key": scoring_key, "actions": []}

    def act(msg: str) -> None:
        report["actions"].append(msg)
        print(f"  {msg}")

    print(f"=== weekly_refresh: league {lid}  season {season}  → week {target_week}  ({scoring_key}) ===")

    # Preseason: no game week yet. Refresh the season's projection input (the forward prior) and stop —
    # nothing realized to advance to (the "too early" render is S4). Never fabricate a week.
    if not target_week or target_week < 1:
        act(f"no current game week (leg={target_week}) — preseason; refreshing projections only, nothing to advance")
        if live and not data_layer.projections_exist(season):
            sleeper.fetch_projections_season(season)
            act(f"banked {season} projections (forward prior)")
        return report

    # 1. FETCH (idempotent, skip-if-present) --------------------------------------------------------------
    if not data_layer._sleeper_matchups_path(season, target_week, lid).exists():
        if live:
            sleeper.refresh(lid); act("fetched current Sleeper state (refresh)")
        else:
            sleeper.backfill(lid, season); act(f"backfilled Sleeper matchups/transactions for {season}")
    else:
        act(f"matchups wk{target_week} already banked — Sleeper fetch skipped")

    if data_layer.read_projections(season, week=target_week).is_empty():
        act(f"fetched projections wk{target_week}" if sleeper.fetch_projections(season, target_week)
            else f"no projections available for wk{target_week} (source empty)")
    else:
        act(f"projections wk{target_week} present — skipped")

    if not _has_actuals(season, target_week):
        if live:
            nfl_stats.refresh()
        if not _has_actuals(season, target_week):
            act(f"no realized nfl_stats for wk{target_week} yet — advancing on projections-only "
                "(join zero-fills actuals; nothing fabricated)")

    # 2. JOIN (the advance) -------------------------------------------------------------------------------
    if not data_layer._sleeper_matchups_path(season, target_week, lid).exists():
        act(f"no matchups snapshot for wk{target_week} — cannot advance the join; stopping (nothing realized)")
        return report
    cur = _joined_max_week(lid, season)
    if cur >= target_week:
        act(f"join already covers wk{target_week} (max joined = {cur})")
    else:
        for wk in range(cur + 1, target_week + 1):
            if data_layer._sleeper_matchups_path(season, wk, lid).exists():
                join_nfl_sleeper_weekly.run(season, wk, league_id=lid)
                act(f"joined week {wk} → season_{season}.parquet")

    # 3. SPINE (recompute — the join is mutable, so on-disk spine reads are stale) -------------------------
    if _spine_covers(lid, season, target_week):
        act(f"spine already covers as_of {target_week} — recompute skipped")
    else:
        timing: dict = defaultdict(float)
        compute_spine._compute_league(lid, season, scoring_key, timing)
        act(f"recomputed spine (production_vor/true_rank/positional_depth/bracket_odds/player_signal) → as_of 1..{target_week}")

    # 4. LOAD (per-league scoped reload → Postgres) -------------------------------------------------------
    if do_load:
        db_max = _db_max_as_of(lid)
        if db_max is not None and db_max >= target_week:
            act(f"Postgres already at as_of {db_max} (≥ {target_week}) — scoped reload skipped (no-op)")
        else:
            build_db.reload_league(lid)
            act(f"scoped-reloaded league to Postgres → as_of advanced to {target_week} (others untouched)")
    else:
        act("--no-load: derived store advanced; Postgres not written")

    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Advance one league to the current/target week (weekly refresh).")
    ap.add_argument("--league", default=None, help="league_id (default: the is_mine league for the season)")
    ap.add_argument("--season", type=int, default=None, help="season (required unless --live)")
    ap.add_argument("--week", type=int, default=None, help="target week (replay); omit with --live")
    ap.add_argument("--live", action="store_true", help="derive season+week from Sleeper /state/nfl (in-season)")
    ap.add_argument("--no-load", action="store_true", help="advance the derived store but do NOT write Postgres")
    args = ap.parse_args()
    if not args.live and args.season is None:
        ap.error("pass --season (+ --week) for a replay, or --live for the in-season current week")
    report = refresh_league(lid=args.league, season=args.season, target_week=args.week,
                            live=args.live, do_load=not args.no_load)
    print(f"\n=== done: {len(report['actions'])} step(s); league {report['league_id']} "
          f"season {report['season']} → week {report['target_week']} ===")


if __name__ == "__main__":
    main()
