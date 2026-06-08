"""
Compute per-team lineup-leakage analytics from the weekly join.

Promotes the front-end `computeLeakage` / `optimalLineup` / `expandSlots` shaping
(formerly in queries.js) into a polars transform. Leakage is framed for improvement,
not regret: it leads with lineup efficiency (process soundness) and splits the points
a manager left on the bench into two buckets that mean very different things:

  - coachable: an ONGOING misallocation — a player habitually benched
    (startShare < HABITUAL_STARTER_THRESHOLD) out-rates one habitually started, on the
    season, by a clear margin (COACHABLE_RATE_MARGIN), both reliable samples, the
    benched gem still rostered, and the realized weekly gain positive. A repeatable
    "start X over Y" fix whose cost is recoverable.
  - variance: everything else — a bench player who spiked a single week, or a one-off
    wrong call on a normally-correct starter. Not a repeatable mistake. The
    reassurance bucket, and usually most of the total.

The two buckets sum to the season points left (every weekly swap routes to exactly
one), so the raw total is preserved as supporting evidence rather than the headline.

Per team it derives: efficiency % (actual vs optimal lineup), season points left, the
coachable/variance split, the top repeatable named fixes, the per-week leak series,
and a league-relative 0–1 Leaky↔Optimal spectrum marker (min→max efficiency).

Output: snapshots/derived/team_leakage_{season}.parquet, one row per roster_id.

Usage:
    python compute_team_leakage.py --season 2025
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import data_layer

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Below this many games a per-game rate is too noisy to trust (one big week distorts
# it), so such players are kept out of the coachable hierarchy test.
MIN_GAMES = 2
# A benched player must out-rate the started player by more than this factor (>10%)
# over the season for the swap to count as a repeatable hierarchy error, not noise.
COACHABLE_RATE_MARGIN = 1.1
# Start share at/above this marks a "habitual starter"; below it, a "habitual bench"
# player. The coachable signal is a habitual-bench gem out-rating a habitual starter.
HABITUAL_STARTER_THRESHOLD = 0.5


def _round1(n: float) -> float:
    return round(n, 1)


def _expand_slots(slot_rows):
    """Port of queries.js expandSlots: one entry per physical slot (FLEX count 2 → two),
    most-constrained first so dedicated slots claim their position's stars before flex
    slots."""
    slots = []
    for s in slot_rows:
        eligible = str(s["eligible"]).split(",")
        for _ in range(int(s["count"])):
            slots.append({"slot": s["slot"], "eligible": eligible})
    slots.sort(key=lambda s: len(s["eligible"]))
    return slots


def _optimal_lineup(players, slots):
    """Port of queries.js optimalLineup: greedy by ascending eligibility, filling the
    most-constrained slots first with the top scorer available. Each player carries a
    stable `_i` to track usage. Returns the total and the chosen picks (each tagged
    with its filled slot), so callers can both score and diff against who was started."""
    used = set()
    picks = []
    total = 0.0
    for slot in slots:
        candidates = [
            p for p in players if p["_i"] not in used and p["position"] in slot["eligible"]
        ]
        if not candidates:
            continue
        pick = max(candidates, key=lambda p: p["pts"])
        total += pick["pts"]
        used.add(pick["_i"])
        picks.append({**pick, "slot": slot["slot"]})
    return {"total": total, "picks": picks}


def _cls(pos):
    return "QB" if pos == "QB" else "FLEX"


def _team_leakage(week_nums, pool_by_week, slots, season_by_name):
    """Port of queries.js computeLeakage for one team.

    `pool_by_week`: week -> list of {name, position, pts, started} for this team.
    `season_by_name`: name -> {rate, startShare, lowSample, current} for this team.
    """
    by_week = []
    actual_tot = 0.0
    optimal_tot = 0.0
    leak_max = 0.0
    coachable_pts = 0.0
    variance_pts = 0.0
    fix_agg = {}  # "gem|dud" -> aggregated repeatable fix across weeks

    for wk in week_nums:
        pool = [{**p, "_i": i} for i, p in enumerate(pool_by_week.get(wk, []))]
        if not pool:
            continue

        started = [p for p in pool if p["started"]]
        actual_pts = sum(p["pts"] for p in started)
        opt = _optimal_lineup(pool, slots)
        left = opt["total"] - actual_pts

        actual_tot += actual_pts
        optimal_tot += opt["total"]
        leak_max = max(leak_max, left)
        by_week.append({"week": wk, "left": _round1(left)})

        if left <= 0.05:
            continue

        # gems = optimal picks not actually started; duds = starters the optimal lineup
        # drops. Pair within swap-eligibility classes (QB only displaces QB; RB/WR/TE
        # interchange via FLEX) so every swap is legal; counts balance within each
        # class, so zipping best gem ↔ worst dud is sum-exact.
        opt_idx = {p["_i"] for p in opt["picks"]}
        gems_by_cls = {}
        duds_by_cls = {}
        for p in opt["picks"]:
            if not p["started"]:
                gems_by_cls.setdefault(_cls(p["position"]), []).append(p)
        for p in started:
            if p["_i"] not in opt_idx:
                duds_by_cls.setdefault(_cls(p["position"]), []).append(p)

        for c, gems in gems_by_cls.items():
            gems = sorted(gems, key=lambda p: p["pts"], reverse=True)
            duds = sorted(duds_by_cls.get(c, []), key=lambda p: p["pts"])
            for j in range(min(len(gems), len(duds))):
                g = gems[j]
                d = duds[j]
                gain = g["pts"] - d["pts"]
                gs = season_by_name.get(g["name"])
                ds = season_by_name.get(d["name"])

                # Coachable only if this is a repeatable hierarchy error AND the swap
                # actually helped that week: a habitual-bench gem that clearly out-rates
                # a habitual-starter dud over the season, both reliable samples, gem
                # still rostered, realized weekly gain positive. Everything else is
                # variance. Routing gain>0 only keeps the coachable bucket non-negative
                # while staying sum-exact with the total.
                coachable = (
                    gs is not None
                    and ds is not None
                    and not gs["lowSample"]
                    and not ds["lowSample"]
                    and gs["current"]
                    and gs["startShare"] < HABITUAL_STARTER_THRESHOLD
                    and ds["startShare"] >= HABITUAL_STARTER_THRESHOLD
                    and gs["rate"] > ds["rate"] * COACHABLE_RATE_MARGIN
                    and gain > 0
                )

                if coachable:
                    coachable_pts += gain
                    key = f"{g['name']}|{d['name']}"
                    f = fix_agg.get(key)
                    if f is None:
                        f = {
                            "position": g["position"] if g["position"] == d["position"] else "FLEX",
                            "benchName": g["name"],
                            "benchRate": _round1(gs["rate"]),
                            "starterName": d["name"],
                            "starterRate": _round1(ds["rate"]),
                            "edge": _round1(gs["rate"] - ds["rate"]),  # repeatable season rate gap
                            "pts": 0.0,  # realized points recovered, for ranking the fixes
                        }
                        fix_agg[key] = f
                    f["pts"] += gain
                else:
                    variance_pts += gain

    fixes = sorted(fix_agg.values(), key=lambda f: f["pts"], reverse=True)
    fixes = [{**f, "pts": _round1(f["pts"])} for f in fixes][:2]

    return {
        "pct": actual_tot / optimal_tot if optimal_tot else 1.0,
        "points_left": _round1(optimal_tot - actual_tot),
        "coachable_pts": _round1(coachable_pts),
        "variance_pts": _round1(variance_pts),
        "leak_max": _round1(leak_max),
        "by_week": by_week,
        "fixes": fixes,
    }


def compute(season: int) -> pl.DataFrame:
    season_df = data_layer.read_join_season(season).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    )
    slot_rows = data_layer.read_lineup_slots(season).to_dicts()
    slots = _expand_slots(slot_rows)

    # Per (team, week) player pool for the optimal-lineup / leakage calc, tagging each
    # player with whether they were actually started.
    pool_by_team_week = {}
    for row in season_df.iter_rows(named=True):
        rid = int(row["roster_id"])
        wk = int(row["week"])
        pool_by_team_week.setdefault(rid, {}).setdefault(wk, []).append(
            {
                "name": row["player_display_name"],
                "position": row["position"],
                "pts": float(row["sleeper_points"]),
                "started": bool(row["is_starter"]),
            }
        )

    # Per (team, player) season totals → role + rate, replicating SQL_ROSTER. rate is
    # per-game output (quality, not availability); startShare distinguishes habitual
    # starters from bench. A player traded mid-season aggregates separately per roster.
    roster_agg = (
        season_df.group_by("roster_id", "player_display_name")
        .agg(
            pl.len().alias("games"),
            pl.col("is_starter").cast(pl.Int64).sum().alias("starts"),
            pl.col("sleeper_points").sum().alias("total"),
        )
    )

    # Each player's CURRENT team = the roster they belong to in their latest week
    # (arg_max over week), replicating SQL_CURRENT_TEAM — so a former team's view can
    # mark a player departed while still crediting the weeks he played there.
    current_team = {
        row["player_display_name"]: int(row["cur_roster"])
        for row in season_df.group_by("player_display_name")
        .agg(pl.col("roster_id").sort_by("week").last().alias("cur_roster"))
        .iter_rows(named=True)
    }

    season_by_name_by_team = {}
    for row in roster_agg.iter_rows(named=True):
        rid = int(row["roster_id"])
        name = row["player_display_name"]
        games = int(row["games"])
        season_by_name_by_team.setdefault(rid, {})[name] = {
            "rate": float(row["total"]) / games if games else 0.0,
            "startShare": int(row["starts"]) / games if games else 0.0,
            "lowSample": games < MIN_GAMES,
            "current": current_team.get(name) == rid,
        }

    records = []
    for rid, pool_by_week in pool_by_team_week.items():
        week_nums = sorted(pool_by_week.keys())
        lk = _team_leakage(
            week_nums, pool_by_week, slots, season_by_name_by_team.get(rid, {})
        )
        records.append({"roster_id": rid, **lk})

    # League-relative spectrum position (0–1, min→max efficiency across all teams).
    # Matches attachSpectrumPos: a flat field collapses everyone to the 0.5 midpoint.
    pcts = [r["pct"] for r in records]
    lo, hi = min(pcts), max(pcts)
    span = hi - lo

    rows = []
    for r in records:
        rows.append(
            {
                "roster_id": r["roster_id"],
                "pct": r["pct"],
                "points_left": r["points_left"],
                "coachable_pts": r["coachable_pts"],
                "variance_pts": r["variance_pts"],
                "leak_max": r["leak_max"],
                "spectrum_pos": (r["pct"] - lo) / span if span else 0.5,
                # View-ready camelCase so the front-end seam can JSON.parse and pass
                # straight to the chart/fix-list with no per-item remapping.
                "by_week_json": json.dumps(r["by_week"]),
                "fixes_json": json.dumps(r["fixes"]),
            }
        )

    df = pl.DataFrame(rows).sort("roster_id")
    print(f"=== Team leakage: season={season} ===")
    print(
        df.select(
            "roster_id", "pct", "points_left", "coachable_pts", "variance_pts", "spectrum_pos"
        )
    )
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_team_leakage(df, season)
    print(f"  → snapshots/derived/team_leakage_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute per-team lineup-leakage analytics.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
