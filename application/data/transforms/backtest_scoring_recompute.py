"""
Reconciliation gate for the custom-scoring recompute engine (`_scoring.recompute_custom_points`).

Unlike the predictive engine backtests, the custom-scoring engine is a *deterministic* recompute — its
"answer key" is the canned scoring columns themselves. The engine scores league points as a delta on the
standard canned baseline (`proj_pts_std` / `fantasy_points`), so the discipline is reconciliation, not
prediction. Four checks (exit 0 iff all pass):

  A — **Equivalence.** Run the custom path with a *standard* scoring_settings (rec ∈ {1, .5, 0}) and assert
      it reproduces the matching canned column, on real 2025 data, both sides (projections + nfl_stats
      actuals). This proves the custom code path *is* the canned path on standard inputs — the delta
      baseline design's core guarantee. (Projections round their components to 2 dp, so the projection
      side reconciles to ~0.01; the actual side is exact.)
  B — **Custom deltas.** Synthetic custom settings (6-pt pass TD, TE premium, 0.75-PPR) shift points by
      *exactly* the expected term vs. the PPR baseline (+2·pass_td, +bonus·rec for TEs only, −0.25·rec).
  C — **Rejection.** Settings the projections can't score a center for (first-down / threshold-yardage
      bonuses) raise `NotImplementedError` naming the offending key — never a silent wrong number (law 2).
  D — **End-to-end.** `compute_projection_consensus.compute(season, scoring=<custom>)` runs without
      raising and returns a sane, non-empty consensus frame — proving the whole read spine (which consumes
      this consensus) now runs for a custom-scoring league.
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms import compute_projection_consensus
from application.data.transforms._scoring import recompute_custom_points, scoring_profile

PROJ_TOL = 0.02    # projections store components at 2 dp → ~0.01 rounding on the reconstruction
ACTUAL_TOL = 1e-6  # nfl_stats components are exact
DELTA_TOL = 1e-6


def _max_abs(df: pl.DataFrame, expr: pl.Expr, ref: str) -> float:
    return float(df.select((expr - pl.col(ref)).abs().alias("d"))["d"].max())


def _check(label: str, err: float, tol: float, results: list) -> None:
    ok = err <= tol
    results.append(ok)
    print(f"    {label:52} max_err={err:.4f}  (tol {tol:g})  {'PASS' if ok else 'FAIL'}")


def run(season: int) -> bool:
    proj = data_layer.read_projections(season).filter(pl.col("proj_pts_ppr").is_not_null())
    act = data_layer.read_nfl_stats(season).drop_nulls("sleeper_player_id")
    print(f"=== Custom-scoring recompute gate: season={season}  "
          f"(proj rows={proj.height}, actual rows={act.height}) ===")

    results: list[bool] = []
    ppr, half, std = {"rec": 1.0}, {"rec": 0.5}, {"rec": 0.0}

    # --- A: equivalence — custom path reproduces the canned columns on standard inputs ---
    print("  A — equivalence (custom path == canned on standard scoring):")
    _check("proj  custom(ppr)  vs proj_pts_ppr", _max_abs(proj, recompute_custom_points(ppr, "proj"), "proj_pts_ppr"), PROJ_TOL, results)
    _check("proj  custom(half) vs proj_pts_half", _max_abs(proj, recompute_custom_points(half, "proj"), "proj_pts_half"), PROJ_TOL, results)
    _check("proj  custom(std)  vs proj_pts_std", _max_abs(proj, recompute_custom_points(std, "proj"), "proj_pts_std"), PROJ_TOL, results)
    _check("actual custom(ppr) vs fantasy_points_ppr", _max_abs(act, recompute_custom_points(ppr, "actual"), "fantasy_points_ppr"), ACTUAL_TOL, results)
    _check("actual custom(std) vs fantasy_points", _max_abs(act, recompute_custom_points(std, "actual"), "fantasy_points"), ACTUAL_TOL, results)
    act_half = act.with_columns(((pl.col("fantasy_points_ppr") + pl.col("fantasy_points")) / 2.0).alias("hp"))
    _check("actual custom(half) vs (ppr+std)/2", _max_abs(act_half, recompute_custom_points(half, "actual"), "hp"), ACTUAL_TOL, results)

    # --- B: custom deltas land exactly (vs the PPR baseline) ---
    print("  B — custom deltas (exact vs PPR baseline):")
    base_p = recompute_custom_points(ppr, "proj")
    base_a = recompute_custom_points(ppr, "actual")
    # 6-pt pass TD: +2·pass_td (both sides)
    six = {"rec": 1.0, "pass_td": 6.0}
    _check("6pt-passTD proj  Δ == 2·proj_pass_td",
           float(proj.select((recompute_custom_points(six, "proj") - base_p - 2.0 * pl.col("proj_pass_td").fill_null(0)).abs().max().alias("d"))["d"][0]), DELTA_TOL, results)
    _check("6pt-passTD actual Δ == 2·passing_tds",
           float(act.select((recompute_custom_points(six, "actual") - base_a - 2.0 * pl.col("passing_tds").fill_null(0)).abs().max().alias("d"))["d"][0]), DELTA_TOL, results)
    # TE premium 0.5: +0.5·rec for TE only, 0 elsewhere
    te = {"rec": 1.0, "bonus_rec_te": 0.5}
    d_te = act.with_columns((recompute_custom_points(te, "actual") - base_a).alias("delta"))
    _check("TE-prem actual: TE Δ == 0.5·receptions",
           float(d_te.filter(pl.col("position") == "TE").select((pl.col("delta") - 0.5 * pl.col("receptions").fill_null(0)).abs().max().alias("d"))["d"][0]), DELTA_TOL, results)
    _check("TE-prem actual: non-TE Δ == 0",
           float(d_te.filter(pl.col("position") != "TE").select(pl.col("delta").abs().max().alias("d"))["d"][0]), DELTA_TOL, results)
    # 0.75-PPR: −0.25·rec vs full PPR
    p75 = {"rec": 0.75}
    _check("0.75-PPR proj  Δ == −0.25·proj_rec",
           float(proj.select((recompute_custom_points(p75, "proj") - base_p + 0.25 * pl.col("proj_rec").fill_null(0)).abs().max().alias("d"))["d"][0]), DELTA_TOL, results)

    # --- C: rejection — unsupported skill-scoring keys raise, naming the key ---
    print("  C — rejection (unsupported keys raise, not silently mis-score):")
    for bad in ({"rec": 1.0, "rec_fd": 1.0}, {"rec": 1.0, "bonus_rush_yd_100": 3.0}, {"rec": 1.0, "pass_fd": 0.5}):
        key = next(k for k in bad if k != "rec")
        try:
            recompute_custom_points(bad, "proj")
            print(f"    {key:52} did NOT raise                 FAIL")
            results.append(False)
        except NotImplementedError as e:
            named = key in str(e)
            print(f"    {key:52} raises, names key={named}       {'PASS' if named else 'FAIL'}")
            results.append(named)

    # --- D: end-to-end — the consensus transform runs under a real custom profile ---
    print("  D — end-to-end (compute_projection_consensus under custom scoring):")
    custom = {"rec": 0.75, "pass_td": 6.0, "bonus_rec_te": 0.5}  # 0.75-PPR, 6-pt pass TD, TE premium
    assert scoring_profile(custom) == "custom", "test scoring must classify as custom"
    ppr_frame = compute_projection_consensus.compute(season, scoring={"rec": 1.0})
    cus_frame = compute_projection_consensus.compute(season, scoring=custom)
    same_schema = cus_frame.columns == ppr_frame.columns
    nonempty = cus_frame.height > 0 and cus_frame["center_ppr"].null_count() == 0
    # QBs must gain from the 6-pt pass TD; a paired-week join isolates the scoring change.
    j = cus_frame.join(ppr_frame.select("week", "sleeper_player_id", "position", pl.col("center_ppr").alias("center_ppr_ppr")),
                       on=["week", "sleeper_player_id", "position"], how="inner")
    qb_gain = j.filter(pl.col("position") == "QB").select((pl.col("center_ppr") > pl.col("center_ppr_ppr")).mean())["center_ppr"][0]
    qb_ok = qb_gain is not None and qb_gain > 0.9  # >90% of QBs gain from 6-pt pass TDs
    print(f"    runs, {cus_frame.height} rows, schema match={same_schema}, centers non-null={nonempty}   "
          f"{'PASS' if (same_schema and nonempty) else 'FAIL'}")
    print(f"    QB centers rise under 6-pt pass TD: {qb_gain:.1%} of QBs           {'PASS' if qb_ok else 'FAIL'}")
    results.extend([same_schema, nonempty, qb_ok])

    # --- E: classifier float32-drift guards (Session 0.6 — network-free) ---
    # Sleeper serves weights at float32, so a standard PPR league arrives drifted ~1.5e-9. The classifier
    # must see through the drift (the fix) WITHOUT loosening enough to swallow a genuinely custom league
    # (the guard — a real custom weight deviates by 0.01, seven orders of magnitude above the drift).
    print("  E — classifier float32-drift guards:")
    _f32 = {"rec": 1.0, "rush_yd": 0.10000000149011612, "rec_yd": 0.10000000149011612,
            "pass_yd": 0.03999999910593033, "pass_td": 4.0, "rush_td": 6.0, "rec_td": 6.0}
    guards = [
        ("float32-drifted PPR  => ppr   (the fix)", scoring_profile(_f32), "ppr"),
        ("float32-drifted half => half  (the fix)", scoring_profile({**_f32, "rec": 0.5}), "half"),
        ("genuine custom rush_yd=0.11 => custom (guard)", scoring_profile({**_f32, "rush_yd": 0.11}), "custom"),
        ("TE-premium bonus_rec_te=0.5 => custom (guard)", scoring_profile({**_f32, "bonus_rec_te": 0.5}), "custom"),
    ]
    for label, got, want in guards:
        g_ok = got == want
        results.append(g_ok)
        print(f"    {label:54} got={got:7} {'PASS' if g_ok else 'FAIL'}")

    ok = all(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — custom-scoring recompute reconciles to the canned "
          f"columns on standard inputs, deltas exactly on custom inputs, rejects the unscoreable, and "
          f"runs the spine end to end.")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reconciliation gate for the custom-scoring recompute engine.")
    parser.add_argument("--season", type=int, default=2025)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)
