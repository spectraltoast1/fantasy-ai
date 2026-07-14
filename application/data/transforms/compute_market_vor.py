"""
Compute Market VOR — value over replacement from the LeagueLogs market (DECISION_READS.md §4).

The market-value twin of compute_production_vor.py. Production VOR asks "what is this player worth
in rest-of-season *production*, over waiver?"; Market VOR asks the same question on **what the market
thinks he's worth** — LeagueLogs' forward-looking value. Both are anchored waiver line = 0 and divided
by the pool spread, so they land on **one comparable, unit-free scale**; the gap between them is the
§4 trade signal (market ≫ production → the market overvalues him → sell; production ≫ market → buy/hold).
Upside/hype lives in the market but not in production, so the gap isolates the speculation premium.

Per design law 3 this borrows the market value (never builds one) and adds only the decision layer —
the same anchoring + normalisation as Production VOR, reusing the shared pool engine.

**The time-world caveat (honest, not hidden).** The app is frozen at 2025 week 4, but the LeagueLogs
series only ever serves "now" and cannot be backdated — it is current (2026 offseason). So Market VOR
is computed on the **frozen-2025 league rosters** priced at the **current 2026 market**. The read itself
(market value over replacement, per roster) is clean. The Production−Market **gap** joins a 2025-season
production number to a 2026-offseason market number — cross-time — so every gap row carries
`is_cross_time` and the market season/date as first-class columns. Treat the gap as architecture / POC
validation, NOT a live trade call, until the season rolls to 2026 and production is recomputed there.
This mirrors the ros_synthesis `anchor_is_prior_season` precedent (STATUS "time-world mismatch").

  - market_value: the borrowed LeagueLogs `value` (0–100 overall-normalised) for the format-matched
    redraft profile. Borrowed, not built.
  - waiver_line: replacement level = the best **available** (unrostered as of the freeze) player's
    market value in that pool. Volatile by design (§4).
  - pool_top: the best market value in the pool (the pool ceiling).
  - market_vor = (value − waiver) / (top − waiver): waiver = 0, pool top ≈ 1, negative = below the best
    freely-available player. Normalised by the **pool spread** (not the waiver value) — §4's settled
    choice; reuses compute_production_vor._vor for byte-identical algebra.

**Pools (§4 flex reconciliation).** Identical to Production VOR: the shared `_analytics.position_pools`
derives the pools from the league's declared `lineup_slots` (standard 1QB → QB pool + one pooled flex
line for RB/WR/TE; superflex would drop QB into the flex pool). Position is NOT in the market feed
(only `position_rank`), so it is joined from the Sleeper registry (`read_sleeper_players`) for the whole
market pool — rostered and available alike, so the waiver line is computed correctly.

**Grain: tall over `snapshot_date`** — the market's own time axis (the analog of Production VOR's
`as_of_week`). Every banked market day gets its VOR rows, so the un-backdatable series is banked in
derived form; the default read is the latest snapshot. Output rows are **rostered players only**
(mirrors Production VOR). The **gap columns** join each row to the frozen Production VOR slice
(latest `as_of_week`) — `production_vor` / `trade_gap` / `has_production_vor` / `is_cross_time`.

Output: snapshots/derived/market_vor_{season}.parquet, one row per (snapshot_date, rostered player).

Usage:
    python3 -m application.data.transforms.compute_market_vor --season 2025
    python3 -m application.data.transforms.compute_market_vor --season 2025 --snapshot-date 2026-07-12
"""

import argparse

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1, position_pools
from application.data.transforms.compute_production_vor import _vor, _pool_lines, _roster_as_of

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# The format-matched market profile for this league (10-team, 1QB, full-PPR). LeagueLogs only
# publishes 12-team profiles, so the team count is the nearest match — fine, because the waiver line
# is computed from OUR league's roster/available split, not the profile's; the profile only sets the
# valuation context (redraft, not dynasty; 1QB; full PPR). Resolves the §4 open prereq flag.
MARKET_PROFILE = "redraft-1qb-12t-ppr1"


def _market_pool(season: int, profile: str) -> pl.DataFrame:
    """The market pool for one profile: every non-pick player's value, with position joined from the
    PINNED Sleeper registry (the feed carries no position label). Filtered to skill positions. One row per
    (snapshot_date, sleeper_player_id) — the value time-series for the whole profile.

    Session 1.7: the position join reads the pinned snapshot, not the live 24h cache — closing this entity's
    slice of the same registry-drift class the join corrects (a two-way player's market position was
    otherwise non-deterministic across cache refreshes)."""
    market = data_layer.read_leaguelogs_market().filter(
        (pl.col("profile") == profile) & (~pl.col("is_pick"))
    ).select("snapshot_date", "season", "sleeper_player_id", "value")
    registry = data_layer.read_pinned_sleeper_players().select(
        "sleeper_player_id", "position"
    ).filter(pl.col("position").is_in(SKILL_POSITIONS))
    return market.join(registry, on="sleeper_player_id", how="inner").rename(
        {"season": "market_season"}
    )


def _compute_snapshot(day: pl.DataFrame, roster: dict, season: int, snapshot_date,
                      *, pool_of: dict, profile: str) -> list:
    """Market VOR rows for one snapshot_date: value every market player, set each pool's waiver/top
    from who's available (unrostered in the frozen league), then score the rostered players. `day`
    carries (sleeper_player_id, position, value, market_season) for this snapshot. Reuses the shared
    _pool_lines / _vor so the algebra matches Production VOR exactly. Returns row dicts."""
    rostered_ids = set(roster)
    market_season = int(day["market_season"][0])

    # _pool_lines expects a `ros_value` column (its value axis); alias market value onto it.
    ros = day.select(
        "sleeper_player_id", "position", pl.col("value").alias("ros_value")
    )
    lines = _pool_lines(ros, rostered_ids, pool_of)
    pool_sizes = {
        p[0]: g.height for p, g in ros.with_columns(
            pl.col("position").replace_strict(pool_of, default=None).alias("pool")
        ).group_by("pool") if p[0] is not None
    }

    rows = []
    for r in ros.filter(pl.col("sleeper_player_id").is_in(list(rostered_ids))).iter_rows(named=True):
        pool = pool_of.get(r["position"])
        line = lines.get(pool)
        if line is None:
            continue
        rows.append({
            "season": season,
            "snapshot_date": snapshot_date,
            "market_season": market_season,
            "market_profile": profile,
            "roster_id": roster[r["sleeper_player_id"]],
            "sleeper_player_id": r["sleeper_player_id"],
            "position": r["position"],
            "pool": pool,
            "market_value": round1(r["ros_value"]),
            "n_pool": int(pool_sizes.get(pool, 0)),
            "waiver_line": round1(line["waiver"]),
            "pool_top": round1(line["top"]),
            "market_vor": round(_vor(r["ros_value"], line["waiver"], line["top"]), 3),
        })
    return rows


def _attach_gap(df: pl.DataFrame, season: int) -> pl.DataFrame:
    """Join the frozen Production VOR slice (latest as_of_week) onto every market row and derive the
    §4 trade gap. Cross-time by construction at the freeze (market season ≠ league season), so
    `is_cross_time` + the market season/date ride as first-class columns — the market number is never
    silently fused with the production number. Players with a market value but no production row get
    `has_production_vor = False` and a null gap (law 2 — no fabricated number)."""
    pv = data_layer.read_production_vor(season)  # default = latest as_of_week
    production_as_of = int(pv["as_of_week"][0]) if pv.height else None
    pv = pv.select(
        "roster_id", "sleeper_player_id", pl.col("vor").alias("production_vor")
    )
    out = df.join(pv, on=["roster_id", "sleeper_player_id"], how="left").with_columns(
        pl.lit(production_as_of).alias("production_as_of"),
        pl.col("production_vor").is_not_null().alias("has_production_vor"),
        (pl.col("market_season") != pl.col("season")).alias("is_cross_time"),
    ).with_columns(
        # trade_gap = market_vor − production_vor (Market ≫ Production → sell; Production ≫ Market → buy)
        (pl.col("market_vor") - pl.col("production_vor")).round(3).alias("trade_gap"),
    )
    return out


def compute(season: int, snapshot_date=None) -> pl.DataFrame:
    pool_of = position_pools(data_layer.read_lineup_slots(season).to_dicts())
    season_df = data_layer.read_join_season(season).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    )
    # Frozen-2025 roster = latest week ≤ max frozen week (the current freeze). Constant across market
    # snapshots — the league is frozen; only the market moves.
    freeze_week = int(season_df["week"].max())
    roster = _roster_as_of(season_df, freeze_week)

    pool = _market_pool(season, MARKET_PROFILE)
    if snapshot_date is not None:
        pool = pool.filter(pl.col("snapshot_date") == pl.lit(snapshot_date).str.to_date())
    dates = sorted(pool["snapshot_date"].unique().to_list())

    all_rows = []
    for d in dates:
        day = pool.filter(pl.col("snapshot_date") == d)
        all_rows.extend(_compute_snapshot(day, roster, season, d, pool_of=pool_of, profile=MARKET_PROFILE))

    df = pl.DataFrame(all_rows, infer_schema_length=None)
    df = _attach_gap(df, season).sort(
        "snapshot_date", "roster_id", "market_vor", descending=[False, False, True]
    )

    latest = df.filter(pl.col("snapshot_date") == df["snapshot_date"].max())
    print(f"=== Market VOR: season={season}  profile={MARKET_PROFILE}  "
          f"snapshots={len(dates)} ({dates[0]}..{dates[-1]}); rows={df.height} ===")
    print(f"  frozen roster as of week {freeze_week}: {len(roster)} players; "
          f"cross-time={bool(latest['is_cross_time'].all())} "
          f"(market season {latest['market_season'][0]} vs league {season})")
    for p in ("QB", "FLEX"):
        pl_slice = latest.filter(pl.col("pool") == p)
        if pl_slice.height:
            print(f"  {latest['snapshot_date'][0]} {p:<4} pool: waiver_line={pl_slice['waiver_line'][0]}  "
                  f"pool_top={pl_slice['pool_top'][0]}  (rostered={pl_slice.height})")
    print(f"  latest top market VOR (rostered):")
    print(latest.head(6).select("sleeper_player_id", "position", "market_value",
                                 "market_vor", "production_vor", "trade_gap"))
    no_prod = latest.filter(~pl.col("has_production_vor")).height
    print(f"  latest: dead weight (market_vor<0)={latest.filter(pl.col('market_vor') < 0).height}; "
          f"no production row (gap null)={no_prod}")
    return df


def run(season: int, snapshot_date=None) -> None:
    df = compute(season, snapshot_date)
    data_layer.write_market_vor(df, season)
    print(f"  → snapshots/derived/market_vor_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Market VOR from the LeagueLogs market value.")
    parser.add_argument("--season", type=int, required=True,
                        help="the LEAGUE season (roster/production side); market date carries its own season")
    parser.add_argument("--snapshot-date", type=str, default=None,
                        help="restrict to one market snapshot date (YYYY-MM-DD); default = all banked dates")
    args = parser.parse_args()
    run(args.season, args.snapshot_date)
