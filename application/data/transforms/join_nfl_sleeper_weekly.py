"""
Join NFL player stats (nflreadpy) with Sleeper matchup data for a given season + week.

Design:
  - Sleeper is the authoritative left table: every rostered skill-position player
    appears in the output regardless of whether nflreadpy has stats for them that week.
  - Players with no nflreadpy entry (injured, suspended, inactive) receive 0.0 for all
    numeric stat columns. Their sleeper_points is already correct from Sleeper.
  - DSTs are stripped before the join. Kickers are removed by the final SKILL_POSITIONS
    filter (position="K" from nflreadpy, or null if they never appear in nflreadpy).
  - Identity metadata (name, position, etc.) for unmatched players is sourced from an
    in-memory lookup built from the full-season nflreadpy file. As a last resort,
    player_id_map provides gsis_id for players absent from nflreadpy entirely.

Usage:
    python3 -m application.data.transforms.join_nfl_sleeper_weekly --season 2025 --week 4
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

# Identity columns sourced from nflreadpy — used to enrich unmatched Sleeper rows.
_IDENTITY_COLS = [
    "player_id",
    "player_name",
    "player_display_name",
    "position",
    "position_group",
    "headshot_url",
]

# Sleeper-derived columns that live at the end of the output schema.
_SLEEPER_TAIL_COLS = [
    "roster_id",
    "matchup_id",
    "sleeper_points",
    "is_starter",
    "roster_total_points",
    "matchup_result",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_nfl_stats(season: int, week: int) -> pl.DataFrame:
    """Load all positions for the target week.

    Filtering to SKILL_POSITIONS happens after the join so that K rows
    come through matched (position='K') and are dropped cleanly at the end.
    """
    df = data_layer.read_nfl_stats(season)
    return df.filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    )


def _build_player_metadata(season: int) -> pl.DataFrame:
    """One row per sleeper_player_id — identity columns only.

    Built from the full-season nflreadpy file so players who were inactive
    in the target week but played in other weeks are still resolvable.
    """
    df = data_layer.read_nfl_stats(season)
    return (
        df.select(_IDENTITY_COLS + ["sleeper_player_id"])
        .filter(pl.col("sleeper_player_id").is_not_null())
        .unique(subset=["sleeper_player_id"], keep="first")
    )


# ---------------------------------------------------------------------------
# Sleeper parsing
# ---------------------------------------------------------------------------

def _parse_sleeper_matchups(
    season: int, week: int
) -> tuple[pl.DataFrame, dict]:
    """Explode Sleeper matchup rows into one row per rostered player.

    DSTs (all-uppercase alphabetic team codes like 'TB', 'DEN') are stripped
    here. Kickers are left in and removed after the join via SKILL_POSITIONS.

    Points come from Sleeper's own scoring — these are the league-official
    fantasy points, not nflreadpy's recalculation.

    Returns:
        (DataFrame of non-DST players, counts dict with 'total' and 'dst_count')
    """
    matchups = data_layer.read_sleeper_matchups(season, week)

    rows = []
    total_entries = 0
    dst_count = 0

    for row in matchups.iter_rows(named=True):
        roster_id = row["roster_id"]
        matchup_id = row["matchup_id"]
        roster_total_points = float(row["points"] or 0.0)

        try:
            players_points = json.loads(row["players_points"] or "{}")
        except (json.JSONDecodeError, TypeError):
            players_points = {}

        try:
            starters = set(json.loads(row["starters"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            starters = set()

        for player_id, pts in players_points.items():
            total_entries += 1
            # Strip DSTs — Sleeper represents them as all-uppercase team abbreviations.
            if player_id.isalpha() and player_id.isupper():
                dst_count += 1
                continue
            rows.append(
                {
                    "sleeper_player_id": player_id,
                    "roster_id": roster_id,
                    "matchup_id": matchup_id,
                    "sleeper_points": float(pts),
                    "is_starter": player_id in starters,
                    "roster_total_points": roster_total_points,
                }
            )

    counts = {"total": total_entries, "dst_count": dst_count}

    if not rows:
        return pl.DataFrame(
            schema={
                "sleeper_player_id": pl.Utf8,
                "roster_id": pl.Int64,
                "matchup_id": pl.Int64,
                "sleeper_points": pl.Float64,
                "is_starter": pl.Boolean,
                "roster_total_points": pl.Float64,
            }
        ), counts

    df = pl.DataFrame(rows).with_columns(
        pl.col("sleeper_player_id").cast(pl.Utf8),
        pl.col("roster_id").cast(pl.Int64),
        pl.col("matchup_id").cast(pl.Int64),
        pl.col("sleeper_points").cast(pl.Float64),
        pl.col("is_starter").cast(pl.Boolean),
        pl.col("roster_total_points").cast(pl.Float64),
    )
    return df, counts


def _derive_matchup_result(sleeper: pl.DataFrame) -> pl.DataFrame:
    """Tag each row W/L based on which roster scored more in the matchup."""
    winners = (
        sleeper.group_by("matchup_id")
        .agg(
            pl.col("roster_id")
            .sort_by("roster_total_points", descending=True)
            .first()
            .alias("winner_roster_id")
        )
    )
    return sleeper.join(winners, on="matchup_id", how="left").with_columns(
        pl.when(pl.col("roster_id") == pl.col("winner_roster_id"))
        .then(pl.lit("W"))
        .otherwise(pl.lit("L"))
        .alias("matchup_result")
    ).drop("winner_roster_id")


# ---------------------------------------------------------------------------
# Post-join enrichment
# ---------------------------------------------------------------------------

def _enrich_unmatched(
    joined: pl.DataFrame,
    metadata: pl.DataFrame,
    season: int,
    week: int,
) -> pl.DataFrame:
    """Fill identity columns and zero-out stat columns for unmatched rows.

    Unmatched rows are players Sleeper rostered but nflreadpy has no entry for
    that week (injured, suspended, inactive). Their metadata is pulled from the
    full-season lookup; their stat columns are filled with 0.
    """
    # Join metadata with a suffix to avoid name conflicts with existing columns.
    meta_renamed = metadata.rename({c: f"{c}_meta" for c in _IDENTITY_COLS})
    enriched = joined.join(meta_renamed, on="sleeper_player_id", how="left")

    # Coalesce: prefer the value nflreadpy already populated; fall back to lookup.
    enriched = enriched.with_columns([
        pl.coalesce([pl.col(c), pl.col(f"{c}_meta")]).alias(c)
        for c in _IDENTITY_COLS
    ]).drop([f"{c}_meta" for c in _IDENTITY_COLS])

    # Fill week-context columns for rows that were unmatched.
    enriched = enriched.with_columns([
        pl.col("season").fill_null(season).cast(pl.Int32),
        pl.col("week").fill_null(week).cast(pl.Int32),
        pl.col("season_type").fill_null(pl.lit("REG")),
    ])

    # Zero-fill all numeric stat columns. Skip non-stat columns and string columns.
    _skip = {
        *_IDENTITY_COLS,
        *_SLEEPER_TAIL_COLS,
        "sleeper_player_id", "season", "week", "season_type",
        "game_id", "team", "opponent_team",
        "fetched_at",
        "fg_made_list", "fg_missed_list", "fg_blocked_list",
    }
    fill_cols = [
        c for c in enriched.columns
        if c not in _skip and enriched[c].dtype in (
            pl.Float64, pl.Float32, pl.Int64, pl.Int32, pl.Int16, pl.UInt64, pl.UInt32
        )
    ]
    return enriched.with_columns([
        pl.col(c).fill_null(0) for c in fill_cols
    ])


def _apply_player_id_map_fallback(joined: pl.DataFrame) -> pl.DataFrame:
    """Last-resort: fill player_id and pfr_id from player_id_map for players absent
    from nflreadpy entirely (e.g. cut before week 1, never recorded stats).

    pfr_id is surfaced so unknown-position players can be identified in the
    validation report (e.g. 'MixoJo00' is readable as Joe Mixon).
    Name and position remain null; these players are dropped by the SKILL_POSITIONS
    filter and flagged in the reconciliation report.
    """
    id_map = (
        data_layer.read_player_id_map()
        .select(["sleeper_player_id", "gsis_id", "pfr_id"])
        .filter(pl.col("sleeper_player_id").is_not_null())
        .with_columns(pl.col("sleeper_player_id").cast(pl.Utf8))
    )

    enriched = joined.join(id_map, on="sleeper_player_id", how="left")
    enriched = enriched.with_columns(
        pl.coalesce([pl.col("player_id"), pl.col("gsis_id")]).alias("player_id")
    ).drop("gsis_id")

    # Add pfr_id column if it doesn't already exist (it won't — nflreadpy doesn't carry it).
    if "pfr_id" not in joined.columns:
        return enriched
    # If it somehow already exists, coalesce rather than duplicate.
    return enriched.with_columns(
        pl.coalesce([pl.col("pfr_id"), pl.col("pfr_id_right")]).alias("pfr_id")
    ).drop("pfr_id_right")


# ---------------------------------------------------------------------------
# Output ordering
# ---------------------------------------------------------------------------

def _reorder_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Put Sleeper-derived columns at the end, preserving nflreadpy column order."""
    tail = [c for c in _SLEEPER_TAIL_COLS if c in df.columns]
    head = [c for c in df.columns if c not in set(_SLEEPER_TAIL_COLS)]
    return df.select(head + tail)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _print_validation(
    raw_counts: dict,
    pre_filter: pl.DataFrame,
    joined: pl.DataFrame,
    season: int,
    week: int,
) -> None:
    """Print a full reconciliation report.

    Every Sleeper roster entry must be accounted for in exactly one bucket:
      raw_total = dst_count + k_count + unknown_count + skill_count
    A mismatch here means something fell through all enrichment steps.
    """
    raw_total = raw_counts["total"]
    dst_count = raw_counts["dst_count"]
    k_count = pre_filter.filter(pl.col("position") == "K").height
    unknown = pre_filter.filter(pl.col("position").is_null())
    unknown_count = len(unknown)
    skill_count = len(joined)

    reconciled = dst_count + k_count + unknown_count + skill_count
    status = "✓" if reconciled == raw_total else f"✗  ({reconciled} ≠ {raw_total})"

    print(f"\n=== Validation Report: season={season} week={week} ===")
    print(f"Total Sleeper roster entries: {raw_total}")
    print(f"  DSTs stripped:              {dst_count}")
    print(f"  Kickers removed:            {k_count}")
    print(f"  Unknown position (dropped): {unknown_count}")
    if unknown_count > 0:
        for row in unknown.select(
            ["sleeper_player_id", "player_id", "pfr_id", "roster_id"]
        ).iter_rows(named=True):
            pfr = row.get("pfr_id") or "—"
            pid = row.get("player_id") or "—"
            print(f"    → sleeper_id={row['sleeper_player_id']}  pfr_id={pfr}  gsis={pid}  roster={row['roster_id']}")
    print(f"  Skill players in output:    {skill_count}")
    print(f"Reconciled: {dst_count}+{k_count}+{unknown_count}+{skill_count} = {reconciled}/{raw_total} {status}")

    zero_stat = joined.filter(pl.col("fantasy_points") == 0.0).height
    print(f"\nZero-stat rows (inactive this week): {zero_stat}/{skill_count}")

    key_cols = ["player_display_name", "position", "fantasy_points", "matchup_result"]
    for col in key_cols:
        if col in joined.columns:
            null_count = joined[col].is_null().sum()
            if null_count > 0:
                print(f"  ⚠ Null [{col}]: {null_count} rows")

    if "position" in joined.columns:
        pos_counts = joined["position"].value_counts().sort("position")
        print(f"Position breakdown: {dict(zip(pos_counts['position'].to_list(), pos_counts['count'].to_list()))}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _apply_registry_eligibility(joined: pl.DataFrame) -> pl.DataFrame:
    """Registry-authoritative skill-eligibility (Session 1.7 — roster reproducibility).

    For a *rostered* player, "what slot does he fill?" is a **fantasy** question answered by the Sleeper
    registry — not by nflreadpy, which answers "what did he produce?". When the two DISAGREE on
    skill-eligibility (a two-way player like Travis Hunter: nflreadpy labels him CB from his defensive
    line, Sleeper rosters him at WR), the **pinned** registry wins: the player is classified by the slot he
    actually fills and survives the SKILL_POSITIONS filter deterministically. Agreement cases (virtually
    everyone) are untouched — nothing to arbitrate. The registry is read PINNED, so this classification
    cannot drift with the 24h players cache. Players with a still-null position (no nflreadpy row) are left
    for audit_join, which resolves them against the same pinned snapshot.
    """
    reg = data_layer.read_pinned_sleeper_players().select(
        "sleeper_player_id", pl.col("position").alias("_reg_position")
    )
    joined = joined.join(reg, on="sleeper_player_id", how="left")
    conflict = (
        pl.col("_reg_position").is_in(list(SKILL_POSITIONS))
        & pl.col("position").is_not_null()
        & ~pl.col("position").is_in(list(SKILL_POSITIONS))
    )
    return joined.with_columns(
        position=pl.when(conflict).then(pl.col("_reg_position")).otherwise(pl.col("position")),
        position_group=pl.when(conflict).then(pl.col("_reg_position")).otherwise(pl.col("position_group")),
    ).drop("_reg_position")


def run(season: int, week: int) -> None:
    nfl = _load_nfl_stats(season, week)
    metadata = _build_player_metadata(season)
    sleeper, raw_counts = _parse_sleeper_matchups(season, week)
    sleeper = _derive_matchup_result(sleeper)

    # Left join: every rostered non-DST player stays in the output.
    joined = sleeper.join(nfl, on="sleeper_player_id", how="left")

    # Enrich unmatched rows with metadata + zero stats.
    joined = _enrich_unmatched(joined, metadata, season, week)

    # Final fallback: player_id and pfr_id from id map for players absent from nflreadpy.
    joined = _apply_player_id_map_fallback(joined)

    # Registry-authoritative skill-eligibility (Session 1.7): the pinned Sleeper registry decides the slot a
    # rostered player fills, overriding a conflicting nflreadpy stats-position for two-way players. Applied
    # before the pre-filter capture so remainders + the skill filter both see the corrected eligibility.
    joined = _apply_registry_eligibility(joined)

    # Capture pre-filter state for the reconciliation report.
    pre_filter = joined

    # Drop K and any player whose position is still unresolvable.
    joined = joined.filter(pl.col("position").is_in(list(SKILL_POSITIONS)))

    # Restore canonical column ordering (pfr_id is not part of the output schema).
    if "pfr_id" in joined.columns:
        joined = joined.drop("pfr_id")
    joined = _reorder_columns(joined)

    # Guarantee season/week are present and correctly typed before the append.
    # The single season file is keyed on these columns for its dedup guard.
    joined = joined.with_columns(
        pl.lit(season).cast(pl.Int32).alias("season"),
        pl.lit(week).cast(pl.Int32).alias("week"),
    )

    data_layer.write_join_nfl_sleeper_weekly(joined, season, week)

    # Write remainders — unknown-position players the join could not resolve.
    # Empty DataFrame = clean join. Auditor reads this to decide whether to act.
    unknown = pre_filter.filter(pl.col("position").is_null())
    remainders = unknown.select([
        "sleeper_player_id", "player_id", "pfr_id", "roster_id",
        "matchup_id", "sleeper_points", "is_starter", "roster_total_points",
    ]) if "pfr_id" in unknown.columns else unknown.select([
        "sleeper_player_id", "player_id", "roster_id",
        "matchup_id", "sleeper_points", "is_starter", "roster_total_points",
    ])
    data_layer.write_join_remainders(remainders, season, week)

    _print_validation(raw_counts, pre_filter, joined, season, week)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Join NFL stats with Sleeper matchups.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()
    run(args.season, args.week)
    # Audit runs automatically after every join to resolve any remainders.
    from application.data.transforms import audit_join
    audit_join.audit(args.season, args.week)
