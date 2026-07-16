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
sim does *not* assume them and raises if they haven't been fetched
(`python3 -m application.data.fetchers.sleeper fetch-league-config`).
For this league that's a **4-team** championship playoff, playoffs starting wk16 (⇒ regular season ends
wk15) — correcting an earlier schedule-inferred "6-team" guess. The gate (backtest_bracket_sim.py) is
still deliberately config-light (win-prob calibration + expected-wins correlation on actual results),
independent of the playoff cut.

Tall over as_of_week N=1..maxweek (roster-as-of-N, frozen wks 1–4), each simulating N+1..reg_season_end.

Output: snapshots/derived/bracket_odds_{season}.parquet, one row per (as_of_week, roster_id).

Usage:
    python3 -m application.data.transforms.compute_bracket_sim --season 2025
"""

import argparse
import hashlib
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1, expand_slots, optimal_lineup
from application.data.transforms.compute_production_vor import _roster_as_of

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# --- Simulation config ---
SIMS = 10_000
SEED = 20260709
MAGIC_ODDS = 0.90          # "clinch" threshold for the magic-number proxy


def _sim_seed(season: int, league_id=None) -> int:
    """League-stable Monte-Carlo seed. The is_mine/primary league keeps the base SEED, so its
    bracket_odds stay byte-identical to the pre-corpus output; every other league gets a seed derived
    from a stable hash of its league_id. Same league ⇒ same odds on re-run (reproducible); different
    leagues ⇒ independent Monte-Carlo draws (the ledger's calibration can't average correlated noise
    away — one global SEED would share one stream across all 221). Machine-independent (hashlib, not
    the salted Python `hash()`); never wall-clock.

    A corpus season without an is_mine league (2020–2023) has no primary — those leagues are
    definitionally non-primary, so resolving the primary is best-effort and absence just routes to the
    derived seed."""
    try:
        primary = str(data_layer._active_league(season)[0])
    except Exception:   # noqa: BLE001 — no is_mine league for this season → no primary to match
        primary = None
    lid = str(league_id) if league_id is not None else primary
    if lid is not None and lid == primary:
        return SEED
    h = int.from_bytes(hashlib.blake2b(str(lid).encode(), digest_size=7).digest(), "big")
    return SEED ^ h


# A playoff_week_start below this is not a real postseason boundary (0/1/negative — garbled or unset in the
# league's Sleeper config); fall back to the standard 15 (a 14-week regular season) rather than yield a
# reg_season_end < 1 that disables the whole season. The single source of truth for the sanity floor, shared
# by _playoff_config (the sim) and harvest._reg_end (the harvest) so the two can never drift.
_DEFAULT_PLAYOFF_WEEK_START = 15


def _sane_playoff_week_start(pw) -> int:
    """A league's playoff_week_start, floored to a sane value. `pw` < 2 or non-numeric/None (missing/garbled)
    → `_DEFAULT_PLAYOFF_WEEK_START`; otherwise the real value. A playoff starting week 0 or 1 is impossible,
    so it means the config was never set — clamping to 1/−1 (the old behaviour) silently disabled the season
    instead of harvesting it."""
    try:
        start = int(pw)
    except (TypeError, ValueError):
        return _DEFAULT_PLAYOFF_WEEK_START
    return start if start >= 2 else _DEFAULT_PLAYOFF_WEEK_START


def _playoff_config(season: int, *, league_id=None) -> tuple:
    """(reg_season_end_week, playoff_teams) from the league's real Sleeper settings — NOT hardcoded.
    `playoff_week_start` is the first postseason week, so the regular season ends the week before;
    `playoff_teams` is the championship-bracket size (the top-K that make the playoffs). Raises with a
    clear message if league_settings hasn't been fetched — never silently fall back to a guess. A
    present-but-garbled `playoff_week_start` (< 2) is floored to the sane default (`_sane_playoff_week_start`)
    so a broken config yields a real season, not reg_season_end = −1."""
    s = data_layer.read_playoff_settings(season, league_id=league_id)
    if "playoff_week_start" not in s or "playoff_teams" not in s:
        raise RuntimeError(
            "league_settings missing playoff config — run "
            "`python3 -m application.data.fetchers.sleeper fetch-league-config <year>` "
            "first. The bracket sim reads the league's real playoff_week_start / playoff_teams; it "
            "does not assume them."
        )
    return _sane_playoff_week_start(s["playoff_week_start"]) - 1, int(s["playoff_teams"])


def _division_map(season: int, *, league_id=None):
    """roster_id → division label, when the league runs divisions AND the per-roster assignment is
    persisted. Today the teams entity carries no `division` column (Sleeper keeps that assignment on
    the rosters endpoint; persisting it is a documented follow-up), so this returns None and the
    seeding falls back to the flat (wins, points-for) table — i.e. the standard league is unchanged.
    When a division league is onboarded and its map is persisted, division-aware seeding activates
    with no further code change. Returns None unless ≥ 2 divisions are actually present.

    NB — division seeding is **synthetic-gated only** (no real division league in the answer key); see
    backtest_bracket_sim.py. Revisit against real division standings when such a league is added."""
    teams = data_layer.read_sleeper_teams(season, league_id=league_id)
    if "division" not in teams.columns:
        return None
    m = {int(r["roster_id"]): r["division"] for r in teams.iter_rows(named=True) if r["division"] is not None}
    return m if len(set(m.values())) >= 2 else None


def _seed_table(total_wins, total_pts, playoff_teams: int, divisions=None):
    """Per-sim playoff seeding from the final table → (seed, made) arrays, shape (SIMS, T). Rank key =
    wins·1e5 + points-for (points-for stays within the multiplier's headroom). **Division-aware:** when
    `divisions` (a per-team-index label list with ≥ 2 distinct values) is given, each division's leader
    is seeded ahead of every non-winner — Sleeper's default: division winners take the top seeds ordered
    among themselves by record, the rest are wildcards by record — via a large additive bonus on the
    winners' key that preserves order within winners and within wildcards. No divisions → the flat seed
    (exactly the prior behavior, so the standard league is byte-identical)."""
    key = total_wins * 1e5 + total_pts
    seed_key = key
    if divisions is not None:
        div = np.asarray(divisions)
        if np.unique(div).size >= 2:
            sims = key.shape[0]
            is_winner = np.zeros(key.shape, dtype=bool)
            for d in np.unique(div):
                cols = np.where(div == d)[0]
                win_local = np.argmax(key[:, cols], axis=1)  # per sim, first max (ties → lowest index)
                is_winner[np.arange(sims), cols[win_local]] = True
            seed_key = key + is_winner * 1e12  # dominates any wins·1e5 + points-for spread
    order = np.argsort(-seed_key, axis=1)
    seed = np.empty(key.shape, dtype=int)
    np.put_along_axis(seed, order, np.broadcast_to(np.arange(1, key.shape[1] + 1), key.shape), axis=1)
    return seed, seed <= playoff_teams


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
    # Iterate the groups in a FIXED (week, matchup_id) order. A roster's cumulative points is a float sum,
    # and float addition is non-associative, so the non-deterministic order polars' group_by yields groups in
    # flips the accumulated sum by a rounding ULP run-to-run for a roster whose total lands on a round1
    # boundary — a latent non-determinism the fixed-SEED sim otherwise inherits (current_points was the only
    # column it reached; graded outputs stayed stable). Sorting pins it; proven a no-op for the whole
    # persisted corpus (matched + is_mine), only making the value reproducible.
    for _, g in sorted(sub.group_by("week", "matchup_id"), key=lambda kv: (int(kv[0][0]), int(kv[0][1]))):
        rows = g.sort("roster_id").to_dicts()
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
    """week → list of (i, j) team-index pairs from the real matchup_id pairings. `rids` are **sorted**
    so the pair order is deterministic: polars group_by doesn't guarantee intra-group row order, and on
    a zero-score tie (e.g. two all-OUT bye rosters, μ=σ=0) the winner otherwise flips with row order,
    making the fixed-SEED sim non-reproducible run-to-run. Sorting makes the fixed seed actually
    deterministic (a latent fixed here alongside the division-seeding work)."""
    sched: dict = {}
    sub = matchups.filter(pl.col("week").is_in(list(weeks)) & pl.col("matchup_id").is_not_null())
    for (wk, _mid), g in sub.group_by("week", "matchup_id"):
        rids = sorted(int(r) for r in g["roster_id"].to_list())
        if len(rids) == 2 and rids[0] in idx and rids[1] in idx:
            sched.setdefault(int(wk), []).append((idx[rids[0]], idx[rids[1]]))
    return sched


def _simulate(team_ids: list, base: dict, dists: dict, sched: dict, weeks: range, playoff_teams: int,
              divisions=None, *, seed: int = SEED) -> dict:
    """Monte Carlo the remaining regular season. `dists[w]` = (mu[T], sig[T]) arrays; `sched[w]` =
    index pairs; `base` = as-of-N standings; `playoff_teams` = the league's championship-bracket size;
    `divisions` = per-team-index division labels (None ⇒ flat seeding); `seed` = the league-stable RNG
    seed (`_sim_seed`). Returns per-team aggregates over SIMS runs."""
    T = len(team_ids)
    rng = np.random.default_rng(seed)
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

    # Final seeding per sim (division-aware when a division map is present; flat otherwise).
    seed, made = _seed_table(total_wins, total_pts, playoff_teams, divisions)

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
                   reg_season_end: int, playoff_teams: int, div_map=None, *, seed: int = SEED) -> list:
    """Bracket-odds rows for one as-of cutoff N (playoff config injected from league settings)."""
    weeks = range(n + 1, reg_season_end + 1)
    team_ids = sorted(roster_pids.keys())
    if not list(weeks) or not team_ids:
        return []
    idx = {rid: i for i, rid in enumerate(team_ids)}
    divisions = [div_map.get(rid) for rid in team_ids] if div_map else None

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
    agg = _simulate(team_ids, base, dists, sched, weeks, playoff_teams, divisions, seed=seed)

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


def compute(season: int, *, league_id=None, scoring_key=None) -> pl.DataFrame:
    reg_season_end, playoff_teams = _playoff_config(season, league_id=league_id)

    cons = data_layer.read_projection_consensus(season, scoring_key=scoring_key).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    ).select("week", "sleeper_player_id", "position", "center_ppr", "band_ppr")
    cons_by_week: dict = {}
    for r in cons.iter_rows(named=True):
        cons_by_week.setdefault(int(r["week"]), {})[r["sleeper_player_id"]] = (
            float(r["center_ppr"]), float(r["band_ppr"] or 0.0), r["position"]
        )

    season_df = data_layer.read_join_season(season, league_id=league_id).filter(pl.col("position").is_in(SKILL_POSITIONS))
    slots = expand_slots(data_layer.read_lineup_slots(season, league_id=league_id).to_dicts())
    matchups = data_layer.read_season_matchups(season, through_week=reg_season_end, league_id=league_id)
    div_map = _division_map(season, league_id=league_id)  # None for a no-division league → flat seeding (unchanged)
    seed = _sim_seed(season, league_id)  # league-stable: base SEED for is_mine, hashed per corpus league
    max_roster_week = int(season_df["week"].max())

    # A named diagnosis (standing instruction 6), not a cryptic empty-frame crash. reg_season_end<2 or a
    # single-week join means the raw harvest is degenerate — e.g. playoff_week_start unset=0 ⇒ reg_end=-1,
    # or only week-1 matchups were pulled. There is no regular season to simulate, so flag the league
    # rather than ship a clean-zero bracket (standing instruction 1). The driver isolates + reports it.
    if reg_season_end < 2 or max_roster_week < 1:
        raise RuntimeError(
            f"no simulable regular season (reg_season_end={reg_season_end}, max_roster_week="
            f"{max_roster_week}) — degenerate/incomplete raw harvest (playoff_week_start unset or "
            f"only week-1 matchups joined)")

    all_rows = []
    for n in range(1, max_roster_week + 1):
        roster = _roster_as_of(season_df, n)  # pid → roster_id
        roster_pids: dict = {}
        for pid, rid in roster.items():
            roster_pids.setdefault(int(rid), []).append(pid)
        # Sort each roster's player list so the optimal-lineup tie-break (max first-occurrence over
        # rounded center_ppr, which collides often) sees a stable order → the fixed-SEED sim is
        # reproducible. `_roster_as_of` returns a dict whose order isn't guaranteed run-to-run.
        for rid in roster_pids:
            roster_pids[rid].sort()
        all_rows.extend(_compute_as_of(n, roster_pids, cons_by_week, slots, matchups, season,
                                       reg_season_end, playoff_teams, div_map, seed=seed))

    # roster_id is the unique tie-break: within an as-of week, playoff_odds ties across teams, so a
    # sort on (as_of_week, playoff_odds) alone is parallelism-dependent (the 1.7 lesson). One row per
    # (as_of_week, roster_id) ⇒ roster_id fully orders it → the fixed-seed output is byte-stable.
    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "playoff_odds", "roster_id", descending=[False, True, False]
    )
    latest = df.filter(pl.col("as_of_week") == max_roster_week)
    print(f"=== Bracket Odds: season={season}  as_of_week 1..{max_roster_week}  "
          f"(sim wks N+1..{reg_season_end}, {playoff_teams} playoff teams, {SIMS} sims; rows={df.height}) ===")
    print(f"  week {max_roster_week} playoff odds (favorites first):")
    print(latest.select("roster_id", "current_wins", "current_points", "proj_wins",
                        "playoff_odds", "avg_seed", "magic_wins"))
    print(f"  Σ playoff_odds = {latest['playoff_odds'].sum():.2f}  (invariant ≈ {playoff_teams})")
    return df


def run(season: int, *, league_id=None, scoring_key=None) -> None:
    df = compute(season, league_id=league_id, scoring_key=scoring_key)
    data_layer.write_bracket_odds(df, season, league_id=league_id)
    lid = league_id or data_layer._active_league(season)[0]
    print(f"  → snapshots/derived/league/{lid}/bracket_odds_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Bracket Odds (§5 bracket-math Monte Carlo).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
