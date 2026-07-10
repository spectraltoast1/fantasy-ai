"""
Compute Bracket Odds — the bracket-math half of the Posture read (DECISION_READS.md §5).

Posture Evidence is two proxies shown *adjacent*: **True Rank** (roster strength — already shipped)
and the **bracket math** (standings + playoff odds + magic number). This builds the second half — the
Monte Carlo season simulation, "the deepest computation in the spec" — turning the forward reads into
per-team playoff odds. Per design law 3 it borrows the forward prior (the §3 weekly band + the §4/§5
lineup value) and builds only the simulation layer.

The engine, per as-of cutoff N:

  - **Team weekly score distribution.** For every team and every remaining week w (> N), the roster
    as-of-N is set into its optimal lineup by that week's borrowed projection centre
    (projection_consensus.center_ppr, the §3 band's p50), giving a weekly **mean** μ = Σ starter
    centres and **std** σ = sqrt(Σ starter band_ppr²) — band_ppr is the shrunk residual std the §3
    band already builds. Starters are independent (a documented simplification — no covariance).
  - **Per-matchup win probability** (analytic): P(A beats B) = Φ((μ_A − μ_B)/sqrt(σ_A² + σ_B²)) via
    math.erf — the honest core of the read, and what the gate calibrates directly.
  - **Standings as-of-N** from the *actual* matchup results for weeks ≤ N (wins, then points-for — the
    standard Sleeper tiebreaker). The sim starts here.
  - **Monte Carlo season sim** (numpy, fixed seed): SIMS runs; each draws every team's weekly score
    ~ N(μ, σ²), pairs by the **real remaining schedule** (matchup_id from the matchup snapshots),
    accumulates wins + points-for onto the as-of-N standings, ranks the final table (wins, points-for),
    and seeds the top PLAYOFF_TEAMS into the playoffs. Aggregated across runs → playoff_odds, projected
    wins/points/seed, and a magic-number proxy (fewest more wins that clinch ≥ MAGIC_ODDS).

**Playoff config (from the league's real settings).** reg_season_end + playoff_teams come from
`_playoff_config` reading the persisted `league_settings` (playoff_week_start − 1, playoff_teams) — the
sim does *not* assume them and raises if they haven't been fetched (`sleeper.py fetch-league-config`).
For this league that's a **4-team** championship playoff, playoffs starting wk16 (⇒ regular season ends
wk15) — correcting an earlier schedule-inferred "6-team" guess. The gate (backtest_bracket_sim.py) is
still deliberately config-light (win-prob calibration + expected-wins correlation on actual results),
independent of the playoff cut.

Tall over as_of_week N=1..maxweek (roster-as-of-N, frozen wks 1–4), each simulating N+1..reg_season_end.

Output: snapshots/derived/bracket_odds_{season}.parquet, one row per (as_of_week, roster_id).

Usage:
    python compute_bracket_sim.py --season 2025
"""

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))  # application/data → data_layer
sys.path.insert(0, str(_TRANSFORMS_DIR))          # transforms → _analytics
import data_layer
from _analytics import round1, expand_slots, optimal_lineup
from compute_production_vor import _roster_as_of

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# --- Simulation config ---
SIMS = 10_000
SEED = 20260709
MAGIC_ODDS = 0.90          # "clinch" threshold for the magic-number proxy


def _playoff_config(season: int) -> tuple:
    """(reg_season_end_week, playoff_teams) from the league's real Sleeper settings — NOT hardcoded.
    `playoff_week_start` is the first postseason week, so the regular season ends the week before;
    `playoff_teams` is the championship-bracket size (the top-K that make the playoffs). Raises with a
    clear message if league_settings hasn't been fetched — never silently fall back to a guess."""
    s = data_layer.read_playoff_settings(season)
    if "playoff_week_start" not in s or "playoff_teams" not in s:
        raise RuntimeError(
            "league_settings missing playoff config — run `sleeper.py fetch-league-config <year>` "
            "first. The bracket sim reads the league's real playoff_week_start / playoff_teams; it "
            "does not assume them."
        )
    return int(s["playoff_week_start"]) - 1, int(s["playoff_teams"])


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _win_prob(mu_a: float, sig_a: float, mu_b: float, sig_b: float) -> float:
    """Analytic P(team A outscores team B) for two independent Normal weekly scores."""
    denom = math.sqrt(sig_a * sig_a + sig_b * sig_b)
    if denom <= 0.0:
        return 0.5 if mu_a == mu_b else (1.0 if mu_a > mu_b else 0.0)
    return _norm_cdf((mu_a - mu_b) / denom)


def _team_week_dist(pids: list, cons_week: dict, slots: list) -> tuple:
    """(μ, σ) for one team's optimal lineup in one week. `pids` are the team's rostered player ids;
    `cons_week` maps player id → (center, band, position) for that week (players absent from it — OUT/
    inactive — aren't lineup-eligible). μ = Σ optimal-starter centres; σ = sqrt(Σ starter band²)
    (independence across starters, documented). Pure."""
    pool = []
    for i, pid in enumerate(pids):
        rec = cons_week.get(pid)
        if rec is None:
            continue
        center, band, pos = rec
        pool.append({"_i": i, "position": pos, "pts": center, "band": band})
    opt = optimal_lineup(pool, slots)
    var = sum(p["band"] * p["band"] for p in opt["picks"])
    return opt["total"], math.sqrt(var)


def _standings_as_of(matchups: pl.DataFrame, n: int) -> dict:
    """roster_id → {"wins", "points"} from the *actual* results for weeks ≤ N. A matchup is the two
    rows sharing a (week, matchup_id); higher points wins (a tie splits 0.5). Points-for is the
    tiebreaker carried alongside wins."""
    standings: dict = {}
    sub = matchups.filter((pl.col("week") <= n) & pl.col("matchup_id").is_not_null())
    for _, g in sub.group_by("week", "matchup_id"):
        rows = g.to_dicts()
        for r in rows:
            standings.setdefault(int(r["roster_id"]), {"wins": 0.0, "points": 0.0})
            standings[int(r["roster_id"])]["points"] += float(r["points"])
        if len(rows) == 2:
            a, b = rows[0], rows[1]
            ra, rb = int(a["roster_id"]), int(b["roster_id"])
            if a["points"] > b["points"]:
                standings[ra]["wins"] += 1.0
            elif b["points"] > a["points"]:
                standings[rb]["wins"] += 1.0
            else:
                standings[ra]["wins"] += 0.5
                standings[rb]["wins"] += 0.5
    return standings


def _schedule(matchups: pl.DataFrame, weeks: range, idx: dict) -> dict:
    """week → list of (i, j) team-index pairs from the real matchup_id pairings."""
    sched: dict = {}
    sub = matchups.filter(pl.col("week").is_in(list(weeks)) & pl.col("matchup_id").is_not_null())
    for (wk, _mid), g in sub.group_by("week", "matchup_id"):
        rids = [int(r) for r in g["roster_id"].to_list()]
        if len(rids) == 2 and rids[0] in idx and rids[1] in idx:
            sched.setdefault(int(wk), []).append((idx[rids[0]], idx[rids[1]]))
    return sched


def _simulate(team_ids: list, base: dict, dists: dict, sched: dict, weeks: range, playoff_teams: int) -> dict:
    """Monte Carlo the remaining regular season. `dists[w]` = (mu[T], sig[T]) arrays; `sched[w]` =
    index pairs; `base` = as-of-N standings; `playoff_teams` = the league's championship-bracket size.
    Returns per-team aggregates over SIMS runs."""
    T = len(team_ids)
    rng = np.random.default_rng(SEED)
    base_wins = np.array([base.get(r, {}).get("wins", 0.0) for r in team_ids])
    base_pts = np.array([base.get(r, {}).get("points", 0.0) for r in team_ids])

    total_wins = np.tile(base_wins, (SIMS, 1)).astype(float)
    total_pts = np.tile(base_pts, (SIMS, 1)).astype(float)
    rem_wins = np.zeros((SIMS, T))

    for w in weeks:
        mu, sig = dists[w]
        scores = rng.normal(mu, sig, size=(SIMS, T))
        total_pts += scores
        for i, j in sched.get(w, []):
            a = scores[:, i] > scores[:, j]
            total_wins[:, i] += a
            total_wins[:, j] += ~a
            rem_wins[:, i] += a
            rem_wins[:, j] += ~a

    # Final seeding per sim: rank by (wins, points-for) descending. Fold into one scalar key
    # (points-for can't exceed the 1e5 multiplier's headroom) and read off the seed by argsort.
    key = total_wins * 1e5 + total_pts
    order = np.argsort(-key, axis=1)
    seed = np.empty_like(key, dtype=int)
    np.put_along_axis(seed, order, np.broadcast_to(np.arange(1, T + 1), key.shape), axis=1)
    made = seed <= playoff_teams

    playoff_odds = made.mean(axis=0)
    proj_wins = total_wins.mean(axis=0)
    proj_points = total_pts.mean(axis=0)
    avg_seed = seed.mean(axis=0)

    # Magic-number proxy: fewest additional wins k after which the team clinches in ≥ MAGIC_ODDS of
    # the sims that hit exactly k remaining wins. None if even winning out doesn't clinch that often.
    magic = []
    R = len(list(weeks))
    for t in range(T):
        m = None
        for k in range(R + 1):
            mask = rem_wins[:, t] == k
            if mask.sum() > 0 and made[mask, t].mean() >= MAGIC_ODDS:
                m = k
                break
        magic.append(m)

    return {
        "playoff_odds": playoff_odds, "proj_wins": proj_wins, "proj_points": proj_points,
        "avg_seed": avg_seed, "magic_wins": magic, "remaining_games": R,
    }


def _compute_as_of(n, roster_pids, cons_by_week, slots, matchups, season,
                   reg_season_end: int, playoff_teams: int) -> list:
    """Bracket-odds rows for one as-of cutoff N (playoff config injected from league settings)."""
    weeks = range(n + 1, reg_season_end + 1)
    team_ids = sorted(roster_pids.keys())
    if not list(weeks) or not team_ids:
        return []
    idx = {rid: i for i, rid in enumerate(team_ids)}

    dists = {}
    for w in weeks:
        cw = cons_by_week.get(w, {})
        mu = np.zeros(len(team_ids))
        sig = np.zeros(len(team_ids))
        for rid, i in idx.items():
            mu[i], sig[i] = _team_week_dist(roster_pids[rid], cw, slots)
        dists[w] = (mu, sig)

    base = _standings_as_of(matchups, n)
    sched = _schedule(matchups, weeks, idx)
    agg = _simulate(team_ids, base, dists, sched, weeks, playoff_teams)

    rows = []
    for rid, i in idx.items():
        b = base.get(rid, {"wins": 0.0, "points": 0.0})
        rows.append({
            "season": season,
            "as_of_week": n,
            "roster_id": rid,
            "playoff_odds": round(float(agg["playoff_odds"][i]), 3),
            "proj_wins": round1(float(agg["proj_wins"][i])),
            "proj_points": round1(float(agg["proj_points"][i])),
            "avg_seed": round1(float(agg["avg_seed"][i])),
            "magic_wins": agg["magic_wins"][i],
            "remaining_games": agg["remaining_games"],
            "current_wins": round1(b["wins"]),
            "current_points": round1(b["points"]),
        })
    return rows


def compute(season: int) -> pl.DataFrame:
    reg_season_end, playoff_teams = _playoff_config(season)

    cons = data_layer.read_projection_consensus(season).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    ).select("week", "sleeper_player_id", "position", "center_ppr", "band_ppr")
    cons_by_week: dict = {}
    for r in cons.iter_rows(named=True):
        cons_by_week.setdefault(int(r["week"]), {})[r["sleeper_player_id"]] = (
            float(r["center_ppr"]), float(r["band_ppr"] or 0.0), r["position"]
        )

    season_df = data_layer.read_join_season(season).filter(pl.col("position").is_in(SKILL_POSITIONS))
    slots = expand_slots(data_layer.read_lineup_slots(season).to_dicts())
    matchups = data_layer.read_season_matchups(season, through_week=reg_season_end)
    max_roster_week = int(season_df["week"].max())

    all_rows = []
    for n in range(1, max_roster_week + 1):
        roster = _roster_as_of(season_df, n)  # pid → roster_id
        roster_pids: dict = {}
        for pid, rid in roster.items():
            roster_pids.setdefault(int(rid), []).append(pid)
        all_rows.extend(_compute_as_of(n, roster_pids, cons_by_week, slots, matchups, season,
                                       reg_season_end, playoff_teams))

    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "playoff_odds", descending=[False, True]
    )
    latest = df.filter(pl.col("as_of_week") == max_roster_week)
    print(f"=== Bracket Odds: season={season}  as_of_week 1..{max_roster_week}  "
          f"(sim wks N+1..{reg_season_end}, {playoff_teams} playoff teams, {SIMS} sims; rows={df.height}) ===")
    print(f"  week {max_roster_week} playoff odds (favorites first):")
    print(latest.select("roster_id", "current_wins", "current_points", "proj_wins",
                        "playoff_odds", "avg_seed", "magic_wins"))
    print(f"  Σ playoff_odds = {latest['playoff_odds'].sum():.2f}  (invariant ≈ {playoff_teams})")
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_bracket_odds(df, season)
    print(f"  → snapshots/derived/bracket_odds_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Bracket Odds (§5 bracket-math Monte Carlo).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
