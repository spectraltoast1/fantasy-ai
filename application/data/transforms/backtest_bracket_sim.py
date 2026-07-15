"""
Backtest Bracket Odds against the full-2025 answer key.

The gate the §5 bracket-math sim must clear before it drives any posture surface. The sim rests on
one modelled object — each team's weekly score distribution (mean from the borrowed optimal-lineup
projection, spread from the §3 band) — so the honest tests hit that object directly, using **only
actual matchup results we already have** (so they're independent of the playoff-config constants).
Two verdicts (exit 0 iff both):

  - **Win-probability calibration.** Over every *actual* matchup in weeks N+1..REG_SEASON_END (across
    as-of N), score the analytic P(win) against the realized result with the **Brier score**; require
    it to beat the 0.25 coin-flip baseline by a margin, and print a calibration table (predicted band
    vs realized win rate). This validates the score-distribution engine — the core of the sim.
  - **Standings prediction.** Per as-of N, correlate each team's **expected wins** (analytic: as-of-N
    wins + Σ remaining P(win) — the deterministic backbone the Monte Carlo approximates) with its
    **actual** wins over the same weeks (Spearman; freeze-week primary, n=10 teams, pooled as evidence).

Imports the SAME pure functions the transform ships (`_team_week_dist`, `_win_prob`,
`_standings_as_of`) — no re-derivation. Also reports (not gated) whether the high-playoff-odds teams
actually finished top-PLAYOFF_TEAMS.

Usage:
    python3 -m application.data.transforms.backtest_bracket_sim --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, pearson, expand_slots
from application.data.transforms.compute_production_vor import _roster_as_of
import numpy as np

from application.data.transforms.compute_bracket_sim import (
    SKILL_POSITIONS,
    _playoff_config,
    _seed_table,
    _standings_as_of,
    _team_week_dist,
    _win_prob,
    compute as _bracket_compute,
)

# Brier must beat the 0.25 coin-flip baseline by at least this margin.
BRIER_MARGIN = 0.02
# Minimum freeze-week Spearman between expected and actual wins.
CORR_MIN = 0.50


def _rankdata(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs, ys):
    return pearson(_rankdata(xs), _rankdata(ys))


def _week_matchups(matchups: pl.DataFrame, w: int) -> list:
    """Actual (rid_a, rid_b, pts_a, pts_b) pairs for week w."""
    out = []
    sub = matchups.filter((pl.col("week") == w) & pl.col("matchup_id").is_not_null())
    for _, g in sub.group_by("matchup_id"):
        rows = g.to_dicts()
        if len(rows) == 2:
            a, b = rows[0], rows[1]
            out.append((int(a["roster_id"]), int(b["roster_id"]), float(a["points"]), float(b["points"])))
    return out


def _test_points(season: int, *, league_id=None, scoring_key=None):
    """Collect per-matchup (p_win, outcome) calibration points and per-(N, team) expected vs actual
    wins, all from the shipped pure functions on the actual answer key."""
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
    reg_season_end, _ = _playoff_config(season, league_id=league_id)
    matchups = data_layer.read_season_matchups(season, through_week=reg_season_end, league_id=league_id)
    freeze = int(season_df["week"].max())

    calib = []        # (p_win, outcome) per actual matchup
    winrows = []      # (as_of_week, roster_id, expected_wins, actual_wins)
    for n in range(1, freeze + 1):
        weeks = range(n + 1, reg_season_end + 1)
        if not list(weeks):
            continue
        roster = _roster_as_of(season_df, n)
        roster_pids: dict = {}
        for pid, rid in roster.items():
            roster_pids.setdefault(int(rid), []).append(pid)

        base = _standings_as_of(matchups, n)
        exp = {rid: base.get(rid, {}).get("wins", 0.0) for rid in roster_pids}
        act = {rid: base.get(rid, {}).get("wins", 0.0) for rid in roster_pids}

        # Per-week team distributions (roster-as-of-N projecting week w).
        for w in weeks:
            cw = cons_by_week.get(w, {})
            dist = {rid: _team_week_dist(pids, cw, slots) for rid, pids in roster_pids.items()}
            for a, b, pa, pb in _week_matchups(matchups, w):
                if a not in dist or b not in dist:
                    continue
                mua, siga = dist[a]
                mub, sigb = dist[b]
                p = _win_prob(mua, siga, mub, sigb)
                outcome = 1.0 if pa > pb else (0.0 if pb > pa else 0.5)
                calib.append((p, outcome))
                exp[a] += p
                exp[b] += 1.0 - p
                act[a] += outcome
                act[b] += 1.0 - outcome

        for rid in roster_pids:
            winrows.append({"as_of_week": n, "roster_id": rid,
                            "expected_wins": exp[rid], "actual_wins": act[rid]})

    return calib, pl.DataFrame(winrows), freeze


def run(season: int, *, league_id=None, scoring_key=None) -> bool:
    calib, wins, freeze = _test_points(season, league_id=league_id, scoring_key=scoring_key)
    print(f"=== Bracket Odds backtest: season={season}  calibration matchups={len(calib)}  "
          f"win rows={wins.height}  (freeze week={freeze}) ===")

    # 1. Win-probability calibration — Brier vs the 0.25 coin-flip baseline.
    brier = mean([(p - o) ** 2 for p, o in calib])
    brier_ok = brier <= 0.25 - BRIER_MARGIN
    print()
    print(f"  win-prob calibration (Brier, lower better; baseline 0.25):")
    print(f"    Brier = {brier:.4f}   (need ≤ {0.25 - BRIER_MARGIN:.3f})   {'PASS' if brier_ok else 'FAIL'}")
    print(f"    predicted band → realized win rate:")
    for lo, hi in [(0.0, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.01)]:
        b = [(p, o) for p, o in calib if lo <= p < hi]
        if b:
            print(f"      p∈[{lo:.1f},{hi:.1f})  n={len(b):<4} pred={mean([p for p, _ in b]):.2f}  "
                  f"actual={mean([o for _, o in b]):.2f}")

    # 2. Standings prediction — freeze-week Spearman(expected wins, actual wins).
    fz = wins.filter(pl.col("as_of_week") == freeze)
    r_s = _spearman(fz["expected_wins"].to_list(), fz["actual_wins"].to_list())
    corr_ok = r_s is not None and r_s >= CORR_MIN
    print()
    print(f"  standings prediction (freeze week {freeze}, n={fz.height} teams):")
    print(f"    Spearman(expected wins, actual wins) = {r_s:.3f}  (min {CORR_MIN:.2f})  {'PASS' if corr_ok else 'FAIL'}")
    r_pool = _spearman(wins["expected_wins"].to_list(), wins["actual_wins"].to_list())
    print(f"    [evidence] pooled Spearman over all as-of weeks (n={wins.height}) = {r_pool:.3f}")

    # Evidence (not gated): do the shipped high-odds teams actually make the top-K playoffs?
    try:
        reg_end, playoff_teams = _playoff_config(season, league_id=league_id)
        odds = data_layer.read_bracket_odds(season, league_id=league_id, as_of_week=freeze)
        actual_final = _standings_as_of(
            data_layer.read_season_matchups(season, through_week=reg_end, league_id=league_id), reg_end
        )
        ranked = sorted(actual_final.items(), key=lambda kv: (kv[1]["wins"], kv[1]["points"]), reverse=True)
        actual_playoff = {rid for rid, _ in ranked[:playoff_teams]}
        pred_playoff = set(odds.sort("playoff_odds", descending=True).head(playoff_teams)["roster_id"].to_list())
        hit = len(pred_playoff & actual_playoff)
        print()
        print(f"  evidence: top-{playoff_teams} by playoff_odds vs actual playoff teams "
              f"→ {hit}/{playoff_teams} correct")
    except Exception as e:  # bracket_odds not built yet — evidence only, never gates
        print(f"  evidence: (bracket_odds parquet not available: {e})")

    # --- Determinism + invariant (the fixed SEED must reproduce; Σ odds = playoff_teams) ---
    _reg, playoff_teams = _playoff_config(season, league_id=league_id)
    a = _bracket_compute(season, league_id=league_id, scoring_key=scoring_key).sort(["as_of_week", "roster_id"])
    b = _bracket_compute(season, league_id=league_id, scoring_key=scoring_key).sort(["as_of_week", "roster_id"])
    det_ok = a.equals(b)
    sums = a.group_by("as_of_week").agg(pl.col("playoff_odds").sum().alias("s"))["s"].to_list()
    inv_ok = all(abs(s - playoff_teams) < 0.02 for s in sums)
    print()
    print(f"  determinism: two runs frame-equal = {det_ok}  {'PASS' if det_ok else 'FAIL'}")
    print(f"  invariant:   Σ playoff_odds ≈ {playoff_teams} every as-of week = {inv_ok}  {'PASS' if inv_ok else 'FAIL'}")

    # --- Synthetic division-seeding correctness (no real division league in the answer key) ---
    # 10 teams, 2 divisions; div-1's winner (idx 5, 5 wins) has a worse record than several div-0
    # non-winners. Division-aware seeding must still seat the division winner in the top slots
    # (Sleeper default), so it makes the bracket where flat seeding drops it for a higher-record team.
    wins = np.array([[10., 9., 8., 7., 6., 5., 1., 1., 1., 1.]])
    pts = np.array([[500., 490., 480., 470., 460., 450., 400., 400., 400., 400.]])
    divs = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
    seed_flat, made_flat = _seed_table(wins, pts, 4, None)
    seed_div, made_div = _seed_table(wins, pts, 4, divs)
    div_ok = (
        bool(made_div[0, 5]) and not bool(made_flat[0, 5])   # div winner makes it only w/ divisions
        and int(seed_div[0, 5]) <= 2                          # division winners take the top seeds
        and not bool(made_div[0, 3]) and bool(made_flat[0, 3])  # a higher-record non-winner is bumped
    )
    print(f"  synthetic divisions: low-record division winner seeded ahead of wildcards = {div_ok}  "
          f"{'PASS' if div_ok else 'FAIL'}  (div-winner seed={int(seed_div[0,5])}, flat made={bool(made_flat[0,5])})")

    ok = brier_ok and corr_ok and det_ok and inv_ok and div_ok
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — win probabilities "
          f"{'beat' if brier_ok else 'do NOT beat'} coin-flip (Brier {brier:.3f}); expected wins "
          f"{'track' if corr_ok else 'do NOT track'} actual (Spearman {r_s:.2f}); sim deterministic; "
          f"division seeding correct on the synthetic league.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest Bracket Odds against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
