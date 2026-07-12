"""
Compute per-team trajectory (form) analytics from the weekly join.

Promotes the front-end `computeForm` shaping (formerly in queries.js) into a polars
transform. "Form" reframes weekly scoring from variance to *direction*: is the team
trending up or fading? Rather than a last-half-vs-first-half split (which discards
the middle week and jumps discontinuously as weeks append), it fits an
exponentially-weighted linear trend — every week's weight halves every
HALF_LIFE_WK weeks back from the most recent — so the read is smooth, uses every
game, and works from two weeks on.

Per team it derives:
  - slope: recency-weighted points/week trend (positive = heating up)
  - direction: rising / fading / steady, thresholded against the team's own average
    scoring (±DIRECTION_BAND/wk) so a small wobble stays "steady"
  - recent: the last two weeks' W/L — a results counterpoint to the scoring trend
  - spectrum_pos: league-relative 0–1 marker (min→max slope across all teams) for
    the Fading↔Surging spectrum
  - weeks: the per-week series (pts, result, beat-median flag, recency weight) the
    chart draws

Output: snapshots/derived/team_form_{season}.parquet, one row per roster_id.

Usage:
    python3 -m application.data.transforms.compute_team_form --season 2025
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, median, round1, spectrum_positions

# Recency weighting: each week's weight halves every HALF_LIFE_WK weeks back from the
# most recent, so the trend leans on recent form without cutting older games off.
HALF_LIFE_WK = 2
# Direction band: a slope within ±DIRECTION_BAND of the team's own avg scoring (per
# week) reads "steady". Tuned to the per-week slope scale (≈ a 12% swing over a
# 4-week window) — catches a monotonic climb/slide, leaves week-to-week noise steady.
DIRECTION_BAND = 0.04


def _team_form(weeks, median_by_week, *, half_life, direction_band):
    """Port of queries.js computeForm for one team.

    `weeks`: list of {"week", "pts", "result"} sorted by week. `half_life` and
    `direction_band` are injected (not read from module globals) so the analytic is
    parameterisable and testable in isolation. Returns a dict with slope, direction,
    recent W/L, and the per-week series carrying beat-median + weight. `slope` is
    rounded to one decimal to match the front-end value the spectrum normalises over.
    """
    weeks = [
        {
            "week": w["week"],
            "pts": w["pts"],
            "result": w["result"],
            "beatMedian": w["pts"] > median_by_week.get(w["week"], 0.0),
            "weight": 1.0,
        }
        for w in sorted(weeks, key=lambda w: w["week"])
    ]
    n = len(weeks)
    pts = [w["pts"] for w in weeks]

    if n < 2:
        return {"slope": 0.0, "direction": "steady", "recent_w": 0, "recent_l": 0, "weeks": weeks}

    # Exponential weights: most recent week = 1, halving every `half_life` weeks.
    decay = 0.5 ** (1 / half_life)
    wts = [decay ** (n - 1 - i) for i in range(n)]
    for w, wt in zip(weeks, wts):
        w["weight"] = wt

    # Weighted least-squares slope of points vs. week index (x = 0..n-1) — pts/week.
    W = sum(wts)
    mx = sum(wt * i for i, wt in enumerate(wts)) / W
    my = sum(wt * pts[i] for i, wt in enumerate(wts)) / W
    num = sum(wts[i] * (i - mx) * (pts[i] - my) for i in range(n))
    den = sum(wts[i] * (i - mx) ** 2 for i in range(n))
    slope = num / den if den else 0.0

    # Direction: slope as a fraction of the team's own average scoring, so the
    # "steady" band scales to how much this team puts up.
    avg = mean(pts)
    rel = slope / avg if avg else 0.0
    direction = "rising" if rel > direction_band else "fading" if rel < -direction_band else "steady"

    # Recent record: the last two weeks — a results counterpoint to the scoring trend.
    recent = weeks[n - min(2, n):]
    recent_w = sum(1 for w in recent if w["result"] == "W")
    recent_l = sum(1 for w in recent if w["result"] == "L")

    return {
        "slope": round1(slope),
        "direction": direction,
        "recent_w": recent_w,
        "recent_l": recent_l,
        "weeks": weeks,
    }


def _compute_as_of(season_df: pl.DataFrame, as_of_week: int) -> list:
    """Per-team form rows as of one cutoff week N — `season_df` is the join filtered to
    weeks ≤ N. Returns a list of row dicts tagged `as_of_week = N`. The EWMA trend, the
    per-week beat-median line, and the league-relative Fading↔Surging spectrum are all
    recomputed within weeks ≤ N, so the read is the team exactly as it would have looked
    through week N (Part 2: the cutoff bounds *what data exists*; the EWMA half-life is
    how data inside the cutoff is weighted — form is a trend read, so it stays decayed)."""
    # Collapse per-player rows to one row per (team, week): the team's total points
    # and W/L that week (both repeat across a team's players, so first() is exact).
    team_week = (
        season_df.group_by("roster_id", "week")
        .agg(
            pl.col("roster_total_points").first().alias("pts"),
            pl.col("matchup_result").first().alias("result"),
        )
        .sort("roster_id", "week")
    )

    # Per-week league median (across all teams that week) — the beat/below line.
    median_by_week = {
        int(wk): median(grp["pts"].to_list())
        for (wk,), grp in team_week.group_by("week")
    }

    weeks_by_team = {}
    for row in team_week.iter_rows(named=True):
        weeks_by_team.setdefault(int(row["roster_id"]), []).append(
            {"week": int(row["week"]), "pts": float(row["pts"]), "result": row["result"]}
        )

    records = []
    for rid, weeks in weeks_by_team.items():
        f = _team_form(weeks, median_by_week, half_life=HALF_LIFE_WK, direction_band=DIRECTION_BAND)
        records.append({"roster_id": rid, **f})

    # League-relative spectrum position (0–1, min→max slope across all teams), via the
    # shared normaliser so the rule has one home across the two transforms.
    positions = spectrum_positions([r["slope"] for r in records])

    rows = []
    for r, pos in zip(records, positions):
        rows.append(
            {
                "as_of_week": as_of_week,
                "roster_id": r["roster_id"],
                "slope": r["slope"],
                "direction": r["direction"],
                "recent_w": r["recent_w"],
                "recent_l": r["recent_l"],
                "spectrum_pos": pos,
                # View-ready camelCase so the front-end seam can JSON.parse and pass
                # straight to the chart with no per-item remapping.
                "weeks_json": json.dumps(r["weeks"]),
            }
        )
    return rows


def compute(season: int) -> pl.DataFrame:
    season_df = data_layer.read_join_season(season)

    # Materialize one tall snapshot per as-of week N = 1..maxweek: the team's form
    # exactly as it would have read through week N. Current (latest) behavior is the
    # N = maxweek slice. Cheap to materialize all weeks.
    max_week = int(season_df["week"].max())
    all_rows = []
    for n in range(1, max_week + 1):
        all_rows.extend(_compute_as_of(season_df.filter(pl.col("week") <= n), n))

    df = pl.DataFrame(all_rows).sort("as_of_week", "roster_id")
    print(f"=== Team form: season={season}  as_of_week 1..{max_week} ===")
    print(df.filter(pl.col("as_of_week") == max_week).select(
        "roster_id", "slope", "direction", "recent_w", "recent_l", "spectrum_pos"
    ))
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_team_form(df, season)
    print(f"  → snapshots/derived/team_form_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute per-team trajectory (form) analytics.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
