"""
Derive the starting skill-slot requirements from a league's raw roster_positions.

The league object's roster_positions
(fetched by `python3 -m application.data.fetchers.sleeper fetch-roster-positions`)
lists every slot including bench, IR, kicker, and defense, e.g.
    ['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN',...].

This transform keeps only the STARTING slots a skill player (QB/RB/WR/TE) can fill,
maps each to its eligible positions, and collapses to one row per distinct slot type:

    slot   count  eligible
    QB     1      QB
    RB     2      RB
    WR     2      WR
    TE     1      TE
    FLEX   2      RB,WR,TE

This declared config replaces the earlier inference (min observed starters → slots) so
the front-end "perfect lineup" / lineup-efficiency calc is exact rather than guessed.
V1 is skill-only, so K and DEF starting slots are intentionally dropped — they do not
affect optimal selection among QB/RB/WR/TE.

Usage:
    python3 -m application.data.transforms.derive_lineup_slots --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Sleeper slot code → the set of positions eligible to fill it. Only slots that a
# skill player can occupy are listed; anything absent here (K, DEF, DST, BN, IR,
# TAXI, …) is treated as non-skill / reserve and dropped.
_SLOT_ELIGIBILITY = {
    "QB": ["QB"],
    "RB": ["RB"],
    "WR": ["WR"],
    "TE": ["TE"],
    "FLEX": ["RB", "WR", "TE"],
    "WRRB_FLEX": ["RB", "WR"],
    "REC_FLEX": ["WR", "TE"],
    "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
    "SUPERFLEX": ["QB", "RB", "WR", "TE"],
}


def derive(season: int) -> pl.DataFrame:
    raw = data_layer.read_roster_positions(season)
    slots = raw.sort("slot_index")["slot"].to_list()

    rows = []
    skipped = []
    for slot in slots:
        eligible = _SLOT_ELIGIBILITY.get(slot)
        if eligible is None:
            skipped.append(slot)
            continue
        rows.append({"slot": slot, "eligible": ",".join(eligible)})

    if not rows:
        raise ValueError(
            f"No startable skill slots found in roster_positions for {season}: {slots}"
        )

    df = (
        pl.DataFrame(rows)
        .group_by("slot", "eligible")
        .agg(pl.len().alias("count"))
        .select("slot", "count", "eligible")
        .sort("slot")
    )

    print(f"=== Lineup slots: season={season} ===")
    print(f"  raw roster_positions ({len(slots)}): {slots}")
    print(f"  dropped (non-skill / reserve): {skipped}")
    skill_starters = int(df["count"].sum())
    print(f"  starting skill slots: {skill_starters}")
    print(df)
    return df


def run(season: int) -> None:
    df = derive(season)
    data_layer.write_lineup_slots(df, season)
    print(f"  → snapshots/sleeper/{season}/lineup_slots_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Derive starting skill-slot requirements from roster_positions."
    )
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
