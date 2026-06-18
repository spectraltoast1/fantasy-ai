"""
Compute the per-player spike signal-quality read from the weekly join.

The first decision-critique engine slice (Product Roadmap Phase 1). It answers the
recurring manager question behind waivers, start/sit, and streaming: **"is this
production real, or is it noise?"** — without any forward projection. It is a
*characterization of past production*, not a points forecast (design law 3: borrow
the substrate, don't build a projection engine).

The read rests on a well-established asymmetry: a player's **opportunity** (targets,
carries, snaps — volume) is sticky week to week, while his **efficiency** (points per
opportunity: yards-per-touch and especially TD rate) regresses hard toward the
positional norm. So recent production is decomposed:

  - opportunity per game (`opp_g`) — the repeatable, volume-driven part, carried
    forward as the anchor.
  - points per opportunity (`ppo`) — the fragile part, shrunk toward the league-wide
    positional mean by sample size (a player with few games gets pulled harder toward
    the norm; SHRINK_K games of "prior" weight).

`expected_ppg = opp_g * shrunk_ppo` is the volume-anchored, efficiency-regressed
estimate. The headline is **regression_risk = 1 - expected_ppg / recent_ppg**: the
fraction of recent scoring that the sustainable-usage picture does NOT support
(positive = spike-prone; ~0 = usage-backed; negative = usage suggests room to rise).
A categorical `read` (too_early / spike / mixed / sticky) gates the language on
sample size (design law 2: speak only when confident), and `td_share` is carried as
the most legible evidence ("a third of these points were touchdowns").

The decomposition was validated against the full-2025 answer key — see
backtest_player_signal.py. It beats a naive "recent points carry forward" baseline on
rest-of-season error AND, among hot players (which the naive read cannot tell apart),
correctly separates the group that held from the group that regressed ~3 pts/g.

Output: snapshots/derived/player_signal_{season}.parquet, one row per rostered skill
player.

Usage:
    python compute_player_signal.py --season 2025
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))  # application/data → data_layer
sys.path.insert(0, str(_TRANSFORMS_DIR))          # transforms → _analytics
import data_layer
from _analytics import round1, spectrum_positions

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Shrinkage weight (in "games of prior") pulling a player's points-per-opportunity
# toward the league positional mean: shrunk = (g·ppo + K·mean) / (g + K). Tuned on the
# 2025 backtest — rest-of-season error is flat-bottomed across K≈4–12, so the choice is
# robust, not knife-edge. At the 4-game freeze a player's own efficiency and the league
# norm get roughly equal weight.
SHRINK_K = 6
# Below this many games a per-game read is too thin to characterise; the player is
# flagged low-sample and the read is held at "too_early" (law 2: speak only when sure).
MIN_GAMES = 3
# A player needs at least this much opportunity per game to anchor the league
# positional efficiency mean — pure zero-volume rows would bias the norm downward.
POS_MEAN_MIN_OPP = 3.0
# Read bands on regression_risk. Above SPIKE_BAND the production is meaningfully
# unsupported by usage (cool-off likely); below STICKY_BAND it is usage-backed; the
# middle is genuinely mixed and should be framed as such, not as a confident call.
SPIKE_BAND = 0.15
STICKY_BAND = 0.05


def opportunity_expr() -> pl.Expr:
    """Position-specific opportunity (per row): the volume a player commands, which is
    the sticky half of fantasy production. WR/TE → targets; RB → carries + targets
    (dual-threat backs earn through the air too); QB → pass attempts + carries. Shared
    by the production transform and the backtest so both score on the same definition.
    """
    return (
        pl.when(pl.col("position").is_in(["WR", "TE"]))
        .then(pl.col("targets"))
        .when(pl.col("position") == "RB")
        .then(pl.col("carries") + pl.col("targets"))
        .otherwise(pl.col("attempts") + pl.col("carries"))  # QB
    )


def _player_signal(agg, pos_mean_ppo, *, shrink_k, min_games, spike_band, sticky_band):
    """The pure signal read for one player from his recent-window aggregate.

    `agg`: {position, games, ppg, opp_g, td_ppg}. `pos_mean_ppo`: the league-wide mean
    points-per-opportunity for this player's position. The tuning constants are injected
    (not read from module globals) so the analytic is parameterisable and testable in
    isolation — the backtest sweeps `shrink_k` through this same function.

    Returns the decomposition: expected (efficiency-regressed) ppg, regression_risk, the
    TD share of scoring, and a sample-gated categorical read.
    """
    games = agg["games"]
    ppg = agg["ppg"]
    opp_g = agg["opp_g"]
    td_ppg = agg["td_ppg"]

    low_sample = games < min_games or opp_g <= 0.0
    ppo = ppg / opp_g if opp_g > 0 else 0.0
    # Shrink efficiency toward the positional norm by sample size; opportunity is the
    # anchor and is carried forward as-is (the sticky half).
    shrunk_ppo = (games * ppo + shrink_k * pos_mean_ppo) / (games + shrink_k)
    expected_ppg = opp_g * shrunk_ppo
    regression_risk = 1.0 - expected_ppg / ppg if ppg > 0 else 0.0
    td_share = td_ppg / ppg if ppg > 0 else 0.0

    if low_sample:
        read = "too_early"
    elif regression_risk >= spike_band:
        read = "spike"
    elif regression_risk <= sticky_band:
        read = "sticky"
    else:
        read = "mixed"

    return {
        "games": games,
        "low_sample": low_sample,
        "recent_ppg": round1(ppg),
        "opp_g": round1(opp_g),
        "td_ppg": round1(td_ppg),
        "td_share": round(td_share, 3),
        "ppo": round(ppo, 3),
        "pos_mean_ppo": round(pos_mean_ppo, 3),
        "eff_ratio": round(ppo / pos_mean_ppo, 3) if pos_mean_ppo > 0 else 0.0,
        "expected_ppg": round1(expected_ppg),
        "regression_risk": round(regression_risk, 3),
        "read": read,
    }


def _recent_aggregate(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse per-week skill rows to one recent-window aggregate per player: games,
    per-game fantasy points (PPR — the league's scoring), per-game opportunity, and
    per-game TD points. Plus the per-week (pts, opp) series for an evidence sparkline."""
    return (
        df.with_columns(opportunity_expr().alias("opp"))
        .group_by("sleeper_player_id", "player_display_name", "position")
        .agg(
            pl.len().alias("games"),
            pl.col("fantasy_points_ppr").sum().alias("pts_tot"),
            pl.col("opp").sum().alias("opp_tot"),
            (
                (pl.col("rushing_tds") + pl.col("receiving_tds")) * 6
                + pl.col("passing_tds") * 4
            ).sum().alias("td_pts_tot"),
            pl.struct("week", pl.col("fantasy_points_ppr").alias("pts"), "opp")
            .sort_by("week")
            .alias("weeks"),
        )
        .with_columns(
            (pl.col("pts_tot") / pl.col("games")).alias("ppg"),
            (pl.col("opp_tot") / pl.col("games")).alias("opp_g"),
            (pl.col("td_pts_tot") / pl.col("games")).alias("td_ppg"),
        )
    )


def positional_mean_ppo(season: int, weeks) -> dict:
    """League-wide mean points-per-opportunity per position, from the full NFL stat pool
    (not just this league's rostered players) so the efficiency norm is stable — this is
    the borrowed substrate the per-player read regresses toward. Volume-weighted (total
    points / total opportunity) over players clearing POS_MEAN_MIN_OPP per game, across
    the given `weeks` (the weeks ≤ the as-of cutoff). The norm is a structural baseline,
    so it is cumulative within the cutoff (max sample available as of week N) — never
    peeking past N.
    """
    pool = (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS) & pl.col("week").is_in(weeks))
        .with_columns(
            opportunity_expr().alias("opp"),
            pl.col("fantasy_points_ppr").fill_null(0.0),
        )
    )
    per_player = pool.group_by("player_display_name", "position").agg(
        pl.len().alias("g"),
        pl.col("fantasy_points_ppr").sum().alias("pts"),
        pl.col("opp").sum().alias("opp"),
    )
    qualified = per_player.filter(pl.col("opp") / pl.col("g") >= POS_MEAN_MIN_OPP)
    means = qualified.group_by("position").agg(
        (pl.col("pts").sum() / pl.col("opp").sum()).alias("mean_ppo")
    )
    return {row["position"]: float(row["mean_ppo"]) for row in means.iter_rows(named=True)}


def _compute_as_of(season_df: pl.DataFrame, pos_mean: dict, as_of_week: int) -> list:
    """The per-player signal rows as of one cutoff week N — `season_df` is the join
    already filtered to weeks ≤ N (skill positions, nulls filled). Returns a list of
    row dicts tagged `as_of_week = N`.

    Both the cutoff (Part 1) and roster-as-of-N (Part 3) fall out of the filtered slice:
    `roster_id` per player resolves to the team they belonged to in their latest week
    **≤ N** (arg_max over the slice), so a mid-season trade/add changes *who is on the
    team* at week N, not just their numbers. The opportunity-percentile spectrum is
    recomputed within this cohort, so it reads "where this player sits in the league as
    of week N".
    """
    # roster_id per player = the team they belong to in their latest week ≤ N (a
    # mid-season acquisition is credited to their as-of-N roster), mirroring the leakage
    # transform's current-team rule. One row per rostered skill player.
    current_roster = {
        row["sleeper_player_id"]: int(row["roster_id"])
        for row in season_df.group_by("sleeper_player_id")
        .agg(pl.col("roster_id").sort_by("week").last().alias("roster_id"))
        .iter_rows(named=True)
    }

    agg = _recent_aggregate(season_df)

    records = []
    for row in agg.iter_rows(named=True):
        pos = row["position"]
        sig = _player_signal(
            {
                "position": pos,
                "games": int(row["games"]),
                "ppg": float(row["ppg"]),
                "opp_g": float(row["opp_g"]),
                "td_ppg": float(row["td_ppg"]),
            },
            pos_mean.get(pos, 0.0),
            shrink_k=SHRINK_K,
            min_games=MIN_GAMES,
            spike_band=SPIKE_BAND,
            sticky_band=STICKY_BAND,
        )
        records.append(
            {
                "as_of_week": as_of_week,
                "roster_id": current_roster.get(row["sleeper_player_id"]),
                "sleeper_player_id": row["sleeper_player_id"],
                "player_display_name": row["player_display_name"],
                "position": pos,
                **sig,
                "weeks": [
                    {"week": int(w["week"]), "pts": round1(float(w["pts"])), "opp": round1(float(w["opp"]))}
                    for w in row["weeks"]
                ],
            }
        )

    # Opportunity percentile within position (0–1, min→max opp_g) — the league-relative
    # "how much volume does he command" evidence, via the shared spectrum normaliser.
    by_pos = {}
    for i, r in enumerate(records):
        by_pos.setdefault(r["position"], []).append(i)
    opp_pct = [0.5] * len(records)
    for pos, idxs in by_pos.items():
        positions = spectrum_positions([records[i]["opp_g"] for i in idxs])
        for i, p in zip(idxs, positions):
            opp_pct[i] = p

    rows = []
    for r, op in zip(records, opp_pct):
        weeks = r.pop("weeks")
        rows.append(
            {
                **r,
                "opp_pct": round(op, 3),
                # View-ready series so the front-end seam can JSON.parse and draw a
                # points/opportunity sparkline with no per-item remapping.
                "weeks_json": json.dumps(weeks),
            }
        )
    return rows


def compute(season: int) -> pl.DataFrame:
    # Full (frozen) join; usage/score columns can be null for a player who didn't record
    # that stat type, so treat as zero so opportunity and TD points are well-defined.
    full = data_layer.read_join_season(season).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    ).with_columns(
        [
            pl.col(c).fill_null(0.0)
            for c in [
                "carries", "targets", "attempts", "fantasy_points_ppr",
                "rushing_tds", "receiving_tds", "passing_tds",
            ]
        ]
    )

    # Materialize one tall snapshot per as-of week N = 1..maxweek: the dashboard exactly
    # as it would have read through week N, every player recomputed on weeks ≤ N. Current
    # (latest) behavior is the N = maxweek slice. Cheap to materialize all weeks.
    max_week = int(full["week"].max())
    all_rows = []
    for n in range(1, max_week + 1):
        sub = full.filter(pl.col("week") <= n)
        # Structural efficiency baseline: cumulative over weeks ≤ N (max sample within
        # the cutoff), never peeking past N.
        pos_mean = positional_mean_ppo(season, list(range(1, n + 1)))
        all_rows.extend(_compute_as_of(sub, pos_mean, n))

    df = pl.DataFrame(all_rows).sort(
        "as_of_week", "roster_id", "regression_risk", descending=[False, False, True]
    )
    print(f"=== Player signal: season={season}  as_of_week 1..{max_week} ===")
    latest = df.filter(pl.col("as_of_week") == max_week)
    print(f"  latest (week {max_week}) — {latest.height} players:")
    print(latest.select(
        "player_display_name", "position", "recent_ppg", "opp_g",
        "td_share", "regression_risk", "read",
    ))
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_player_signal(df, season)
    print(f"  → snapshots/derived/player_signal_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the per-player spike signal-quality read.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
