"""
Compute Positional Depth — the Value read re-sliced by position vs. league (DECISION_READS.md §6).

The last of the four Phase-3 reads, and the third re-aggregation of the Production VOR that shipped
in §4 (after True Rank §5). It answers the trade/waiver question behind roster shape: **by position,
where do I have startable-quality surplus (trade capital) and where is a starting slot filled at
~replacement level (a gap)?** Per design law 3 it borrows nothing new — it re-slices the borrowed
`ros_value`/`vor` per position, net of that position's starting requirement, and benchmarks each team
against the league distribution at that position.

Per (as_of_week, roster_id, position ∈ QB/RB/WR/TE) — fine position, not VOR's QB/FLEX pool, because
the whole value is per-position ("deep at WR, thin at TE"):

  - starter_need: the position's **dedicated** starting-slot count from lineup_slots (QB=1, RB=2,
    WR=2, TE=1). The FLEX×2 is shared across RB/WR/TE, so it is *not* attributed to one position — a
    team's flex-worthy depth shows up as surplus below, which is exactly what makes it trade capital.
  - starter_value: sum of the top-starter_need players' ros_value (what fills the dedicated need);
    surplus_value: ros_value beyond the need (depth); surplus_startable: how many of that depth clear
    the waiver line (vor > 0) — genuinely startable, i.e. real trade capital vs. roster filler.
  - marginal_vor: the VOR of the starter_need-th best player (the last dedicated starter) — the **gap
    indicator**: ≤ 0 means you're starting replacement level at that slot. None when the roster can't
    even fill the dedicated slots (a body-count gap).
  - spectrum_pos: league-relative 0–1 of the team's starter_value **within that position's cohort**
    (min→0, max→1, the shared normaliser) — the spec's "compare each position to the league
    distribution" benchmark.
  - shape: a light, advisory {surplus / adequate / gap} label off marginal_vor + spectrum_pos —
    carried as a convenience over the numbers, not an imperative (the manager adjudicates the move).

Tall over as_of_week like Production VOR / True Rank: VOR is already resolved per (as_of_week,
roster_id) with the roster taken as-of-N, so this inherits roster-as-of-N for free. One row per
(team, position) even when the roster is empty at a position (n_rostered = 0 → a body-count gap that
would otherwise be invisible in a rostered-players-only frame).

Output: snapshots/derived/positional_depth_{season}.parquet, one row per (as_of_week, roster_id, position).

Usage:
    python3 -m application.data.transforms.compute_positional_depth --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1, spectrum_positions

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Advisory shape thresholds (named, league-agnostic magic numbers — future config seed).
# A dedicated starter at/below the waiver line reads as a gap; startable depth atop the league
# reads as a surplus. Evidence-first: the numbers lead, these only bucket them for legibility.
GAP_VOR = 0.0           # marginal starter VOR ≤ this ⇒ you're starting replacement level
SURPLUS_SPECTRUM = 0.66  # top-third of the league at the position (with real startable depth) ⇒ surplus


def _starter_needs(lineup_slots: pl.DataFrame) -> dict:
    """position → dedicated starting-slot count, from the league's declared lineup slots (not
    hard-coded). Only rows whose `slot` is a position name count as dedicated need; the shared FLEX
    slot is excluded (its depth surfaces as per-position surplus). Standard 1QB league → QB1/RB2/WR2/TE1."""
    needs: dict = {}
    for r in lineup_slots.iter_rows(named=True):
        if r["slot"] in SKILL_POSITIONS:
            needs[r["slot"]] = needs.get(r["slot"], 0) + int(r["count"])
    return {p: needs.get(p, 0) for p in SKILL_POSITIONS}


def _position_depth(players: list, need: int) -> dict:
    """Per (team, position) re-aggregation of the VOR rows. `players` are that position's rostered
    entries as {ros_value, vor}; `need` the dedicated starting requirement. Pure."""
    ranked = sorted(players, key=lambda p: p["ros_value"], reverse=True)
    n = len(ranked)
    starter_value = sum(p["ros_value"] for p in ranked[:need])
    rostered_value = sum(p["ros_value"] for p in ranked)
    surplus_startable = sum(1 for p in ranked[need:] if p["vor"] > 0)
    # marginal starter = the last dedicated starter; None when the roster can't fill the slots.
    marginal_vor = ranked[need - 1]["vor"] if need > 0 and n >= need else None
    return {
        "n_rostered": n,
        "starter_need": need,
        "rostered_value": rostered_value,
        "starter_value": starter_value,
        "surplus_value": rostered_value - starter_value,
        "surplus_startable": surplus_startable,
        "marginal_vor": marginal_vor,
    }


def _shape(d: dict, spectrum_pos: float) -> str:
    """Advisory surplus/adequate/gap label from the marginal starter's VOR + league spectrum.
    Gap wins first (a hole to fill regardless of the league); then a startable surplus atop the
    league; else adequate."""
    need = d["starter_need"]
    if need > 0 and (d["n_rostered"] < need or d["marginal_vor"] is None or d["marginal_vor"] <= GAP_VOR):
        return "gap"
    if d["surplus_startable"] >= 1 and spectrum_pos >= SURPLUS_SPECTRUM:
        return "surplus"
    return "adequate"


def _compute_as_of(vor_slice: pl.DataFrame, needs: dict, season: int, n: int) -> list:
    """Positional Depth rows for one as-of cutoff N: re-aggregate the VOR slice per (team, position),
    attach a within-position league spectrum, then the advisory shape. One row per (team, position)
    even at zero roster count. Returns row dicts tagged as_of_week = N."""
    by_tp: dict = {}
    rosters = set()
    for row in vor_slice.iter_rows(named=True):
        rid = int(row["roster_id"])
        rosters.add(rid)
        by_tp.setdefault((rid, row["position"]), []).append(
            {"ros_value": row["ros_value"], "vor": row["vor"]}
        )

    records = []
    for rid in sorted(rosters):
        for pos in SKILL_POSITIONS:
            d = _position_depth(by_tp.get((rid, pos), []), needs[pos])
            records.append({"roster_id": rid, "position": pos, **d})

    # League-relative spectrum position within each position's cohort (min→0, max→1 across teams).
    spectrum = [0.5] * len(records)
    by_pos: dict = {}
    for i, r in enumerate(records):
        by_pos.setdefault(r["position"], []).append(i)
    for idxs in by_pos.values():
        for i, p in zip(idxs, spectrum_positions([records[i]["starter_value"] for i in idxs])):
            spectrum[i] = p

    rows = []
    for r, sp in zip(records, spectrum):
        rows.append({
            "season": season,
            "as_of_week": n,
            "roster_id": r["roster_id"],
            "position": r["position"],
            "starter_need": r["starter_need"],
            "n_rostered": r["n_rostered"],
            "rostered_value": round1(r["rostered_value"]),
            "starter_value": round1(r["starter_value"]),
            "surplus_value": round1(r["surplus_value"]),
            "surplus_startable": r["surplus_startable"],
            "marginal_vor": round(r["marginal_vor"], 3) if r["marginal_vor"] is not None else None,
            "spectrum_pos": sp,
            "shape": _shape(r, sp),
        })
    return rows


def compute(season: int, *, league_id=None) -> pl.DataFrame:
    vor = data_layer.read_production_vor(season, league_id=league_id, as_of_week="all").select(
        "as_of_week", "roster_id", "position", "ros_value", "vor"
    )
    needs = _starter_needs(data_layer.read_lineup_slots(season, league_id=league_id))

    all_rows = []
    for n in sorted(vor["as_of_week"].unique().to_list()):
        all_rows.extend(_compute_as_of(vor.filter(pl.col("as_of_week") == n), needs, season, n))

    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "roster_id", "position"
    )
    max_week = int(df["as_of_week"].max())
    print(f"=== Positional Depth: season={season}  as_of_week 1..{max_week}  "
          f"(needs {needs}; rows={df.height}) ===")
    print(f"  week {max_week} sample (2 teams, all positions):")
    sample_teams = df.filter(pl.col("as_of_week") == max_week)["roster_id"].unique().sort().head(2).to_list()
    print(df.filter((pl.col("as_of_week") == max_week) & pl.col("roster_id").is_in(sample_teams)).select(
        "roster_id", "position", "starter_need", "n_rostered", "starter_value",
        "surplus_value", "surplus_startable", "marginal_vor", "spectrum_pos", "shape"
    ))
    counts = df.filter(pl.col("as_of_week") == max_week).group_by("shape").len().sort("shape")
    print(f"  week {max_week} shape distribution: {dict(counts.iter_rows())}")
    return df


def run(season: int, *, league_id=None) -> None:
    df = compute(season, league_id=league_id)
    data_layer.write_positional_depth(df, season, league_id=league_id)
    lid = league_id or data_layer._active_league(season)[0]
    print(f"  → snapshots/derived/league/{lid}/positional_depth_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Positional Depth from the borrowed VOR (§6).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
