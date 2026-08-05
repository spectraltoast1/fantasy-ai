"""
Audit and repair the nfl_sleeper_weekly_joined output for a given season + week.

After the join runs, any Sleeper-rostered players whose position could not be
resolved from nflreadpy or player_id_map are written to a remainders file.
This script reads that file and attempts to resolve each player using the cached
Sleeper /players/nfl registry. Resolved skill-position players are appended to
the joined file with 0.0 stats. Kickers and DEF are confirmed and discarded.
Any player still unresolvable is left in the remainders file for manual review.

The joined file is considered "closed" when the remainders file is empty.

Usage:
    python3 -m application.data.transforms.audit_join --season 2025 --week 1

Idempotent: safe to re-run. If remainders are already empty the script exits
immediately without touching the joined file.
"""

import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.transforms import _matchup

# Positions in the Sleeper players registry that map to skill positions.
_SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
# Positions to confirm and discard — they should never appear in the join output.
_EXCLUDE_POSITIONS = {"K", "DEF", "FB", "OL", "DL", "LB", "DB", "CB", "S",
                      "SAF", "DE", "DT", "NT", "OT", "G", "C", "ILB", "OLB",
                      "MLB", "FS", "LS", "P"}


def _load_sleeper_players() -> pl.DataFrame:
    """Load the PINNED Sleeper players snapshot (Session 1.7 — roster reproducibility).

    Remainder resolution used to read the live 24h `players.parquet` cache, so a rostered player's
    keep/discard flipped with whatever the registry said on rebuild day — the reproducibility hole. It now
    reads the immutable pinned snapshot, so the resolution is deterministic across rebuilds and re-harvests.
    This path is dormant today (the real 2025 league produces no remainders) but it is the SAME drift class
    the join corrects, and it wakes the moment a 276-league corpus yields non-empty remainders (Session 3).
    Raises with capture instructions if the pin has not been created.
    """
    return data_layer.read_pinned_sleeper_players()


def _gsis_by_sleeper() -> dict:
    """sleeper_player_id -> gsis `player_id`, from the same map the join's own fallback uses
    (`join_nfl_sleeper_weekly._apply_player_id_map_fallback`)."""
    idm = data_layer.read_player_id_map()
    return {r["sleeper_player_id"]: r["gsis_id"] for r in idm.iter_rows(named=True)
            if r.get("sleeper_player_id") and r.get("gsis_id")}


def _two_way_ids(season: int) -> set:
    """The season's two-way `sleeper_player_id`s — the same reference `harvest._apply_two_way` writes
    the flag from, so a repair row and a real row agree. Absent reference -> empty set (the flag then
    derives to False, which is what `_apply_two_way` would also produce)."""
    if not data_layer.corpus_two_way_flags_exists():
        return set()
    flags = data_layer.read_corpus_two_way_flags()
    return {str(r["sleeper_player_id"]) for r in flags.iter_rows(named=True)
            if int(r["season"]) == season}


def _week_fetched_at(joined: pl.DataFrame):
    """The week's own snapshot timestamp, so a repair row dates with the cohort it joins rather than
    carrying a null. One distinct non-null value per weekly file."""
    if "fetched_at" not in joined.columns:
        return None
    vals = joined["fetched_at"].drop_nulls()
    return vals[0] if len(vals) else None


def fill_null_matchup_result(week_frame: pl.DataFrame) -> pl.DataFrame:
    """Fill `matchup_result` ONLY where it is null, from the week's own matchup groups.

    A second CALL SITE of `transforms/_matchup`'s single rule — not a second implementation. This
    frame is ONE week (every caller reads a single (season, week) slice), which is exactly the
    invariant `result_expr`'s default `over="matchup_id"` relies on.

    Null-only is what makes this safe to run over an existing artifact: an already-graded verdict is
    never overwritten, so verdict-neutrality holds BY CONSTRUCTION rather than by inspection.
    """
    if "matchup_result" not in week_frame.columns:
        return week_frame
    return week_frame.with_columns(
        pl.when(pl.col("matchup_result").is_null())
        .then(_matchup.result_expr())
        .otherwise(pl.col("matchup_result"))
        .alias("matchup_result")
    )


def _build_zero_stat_row(
    remainder_row: dict,
    player: dict,
    joined_schema: dict,
    season: int,
    week: int,
    *,
    gsis_by_sleeper: dict | None = None,
    two_way_ids: set | None = None,
    fetched_at=None,
) -> dict:
    """Build a zero-stat output row for a resolved skill-position remainder.

    A repair row has to look like a row the JOIN would have written, because everything downstream
    reads it as one. The zero-fill below covers the numeric stat columns (155 of 173), but every
    column derived *after* the join is a String / Boolean / Datetime and so falls straight through
    it — which is how these rows came to carry a null `matchup_result` and, latently, a null
    `is_two_way` (Boolean is deliberately absent from the numeric tuple; zero-filling a flag to
    `false` would be a fabrication, so it is DERIVED below instead).

    What is filled here, and what is deliberately left null — the distinction is the point:

      FILLED, because a real source exists
        player_id       the same `player_id_map` the join's own fallback uses
        position_group  identity from `position`; for QB/RB/WR/TE nflreadpy's group == the position
        is_two_way      the corpus two-way reference (`read_corpus_two_way_flags`), NOT a zero-fill
        fetched_at      the week frame's own snapshot timestamp, so the row dates with its cohort
        matchup_result  NOT here — it needs the whole week's frame; filled in `audit()` (see there)

      LEFT NULL, because there is nothing honest to put there (§3 Law 2: a missing signal is null,
      never fabricated)
        game_id, opponent_team    the player did not play a game. There is no game to name.
        team                      from the pinned registry, which is already tried above; a free
                                  agent at pin time has none, and null is the honest answer.
        headshot_url              absent from the pinned registry and from this season's stats. It
                                  IS recoverable from a prior season, but that is a cross-season
                                  identity read nothing else in the join performs, for a cosmetic
                                  field — declined on purpose, not overlooked.
        fg_*_list                 kicker-only columns; a skill player has no value for them.
    """
    row = {col: None for col in joined_schema}

    # Identity from Sleeper players registry
    row["player_display_name"] = player.get("full_name")
    row["player_name"] = player.get("full_name")
    row["position"] = player.get("position")
    row["team"] = player.get("team")
    row["season"] = season
    row["week"] = week
    row["season_type"] = "REG"

    # Sleeper matchup fields
    row["sleeper_player_id"] = remainder_row["sleeper_player_id"]
    row["roster_id"] = remainder_row["roster_id"]
    row["matchup_id"] = remainder_row["matchup_id"]
    row["sleeper_points"] = remainder_row["sleeper_points"]
    row["is_starter"] = remainder_row["is_starter"]
    row["roster_total_points"] = remainder_row["roster_total_points"]

    # Post-join derived columns the numeric zero-fill cannot reach (see the docstring).
    sid = remainder_row["sleeper_player_id"]
    if "player_id" in row:
        row["player_id"] = (gsis_by_sleeper or {}).get(sid)
    if "position_group" in row and row["position"] in _SKILL_POSITIONS:
        row["position_group"] = row["position"]
    if "is_two_way" in row:
        row["is_two_way"] = sid in (two_way_ids or set())
    if "fetched_at" in row and fetched_at is not None:
        row["fetched_at"] = fetched_at

    # Zero-fill all numeric stat columns
    for col, dtype in joined_schema.items():
        if row[col] is None and dtype in (
            pl.Float64, pl.Float32, pl.Int64, pl.Int32, pl.Int16, pl.UInt64, pl.UInt32
        ):
            row[col] = 0

    return row


def audit(season: int, week: int) -> None:
    """Audit and repair the joined file for the given season/week."""
    print(f"\n=== Audit: season={season} week={week} ===")

    # --- Fast path: no remainders ---
    if not data_layer.remainders_exist(season, week):
        print("  No remainders file found — run the join first.")
        return

    remainders = data_layer.read_join_remainders(season, week)
    if len(remainders) == 0:
        print("  ✓ Remainders file is empty — join is already complete.")
        return

    print(f"  {len(remainders)} remainder(s) to resolve.")

    # --- Resolve against the PINNED registry snapshot (deterministic, not the moving 24h cache) ---
    players_df = _load_sleeper_players()

    # Build a lookup: sleeper_player_id → player dict
    players_lookup = {
        row["sleeper_player_id"]: row
        for row in players_df.iter_rows(named=True)
    }

    # --- Load joined file for schema reference and appending ---
    joined = data_layer.read_join_nfl_sleeper_weekly(season, week)
    joined_schema = {col: joined[col].dtype for col in joined.columns}

    # Sources for the post-join derived columns (see `_build_zero_stat_row`). Read once, not per row.
    gsis_by_sleeper = _gsis_by_sleeper()
    two_way_ids = _two_way_ids(season)
    fetched_at = _week_fetched_at(joined)

    skill_rows = []
    discarded = []
    still_unknown = []

    for row in remainders.iter_rows(named=True):
        sid = row["sleeper_player_id"]
        player = players_lookup.get(sid)

        if player is None:
            still_unknown.append(row)
            continue

        pos = player.get("position")
        if pos in _SKILL_POSITIONS:
            skill_rows.append(_build_zero_stat_row(
                row, player, joined_schema, season, week,
                gsis_by_sleeper=gsis_by_sleeper, two_way_ids=two_way_ids, fetched_at=fetched_at))
        elif pos in _EXCLUDE_POSITIONS or pos is None:
            discarded.append({"sleeper_player_id": sid, "position": pos,
                               "full_name": player.get("full_name")})
        else:
            # Unknown position string — treat as unresolvable
            still_unknown.append(row)

    # --- Report ---
    if discarded:
        print(f"  Confirmed and discarded ({len(discarded)} K/DEF/other):")
        for d in discarded:
            print(f"    → {d['full_name']} (pos={d['position']}, sleeper_id={d['sleeper_player_id']})")

    if skill_rows:
        print(f"  Adding {len(skill_rows)} skill-position player(s) with 0 stats:")
        for r in skill_rows:
            print(f"    + {r['player_display_name']} (pos={r['position']}, "
                  f"roster={r['roster_id']}, sleeper_id={r['sleeper_player_id']})")

        new_rows_df = pl.DataFrame(skill_rows, schema=joined_schema)
        joined = pl.concat([joined, new_rows_df])
        joined = fill_null_matchup_result(joined)
        data_layer.write_join_nfl_sleeper_weekly(joined, season, week)
        print(f"  Joined file updated: {len(joined)} total rows.")

    if still_unknown:
        print(f"  ⚠ Still unresolvable after Sleeper lookup ({len(still_unknown)}):")
        for r in still_unknown:
            pid = r.get("player_id") or "—"
            pfr = r.get("pfr_id") or "—"
            print(f"    ? sleeper_id={r['sleeper_player_id']}  gsis={pid}  pfr={pfr}  roster={r['roster_id']}")

    # --- Write updated remainders (only unresolvable rows remain) ---
    if still_unknown:
        remaining_df = pl.DataFrame(still_unknown, schema=remainders.schema)
    else:
        remaining_df = pl.DataFrame(schema=remainders.schema)

    data_layer.write_join_remainders(remaining_df, season, week)

    if not still_unknown:
        print(f"  ✓ All remainders resolved — join is now complete.")
    else:
        print(f"  {len(still_unknown)} player(s) left in remainders for manual review.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit and repair the weekly join output.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()
    audit(args.season, args.week)
