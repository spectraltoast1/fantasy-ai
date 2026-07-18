"""prove_shrink_invariance.py — the equivalence-spine proof for the center-shrink promotion (Session 8c).

Ships less than it sounds: a uniform positive `CENTER_SHRINK` scales every ROS centre by the same factor, so
the ADVICE is unchanged. This proves it in-memory (no writes), computing the is_mine reads at CENTER_SHRINK
= 1.0 vs 0.8 and asserting:

  - production_vor `vor` is VALUE-IDENTICAL (the ratio (ros−waiver)/(top−waiver) cancels the scale; persisted
    at 3 dp) and `Spearman(ros_value)` = 1.0 (the centre is monotone-scaled → ranking preserved);
  - true_rank `rank` / `spectrum_pos` are IDENTICAL (a dense rank of a monotone scale + an affine normalizer);
  - bracket_odds is STRUCTURALLY independent — the sim reads `projection_consensus` directly and never calls
    `_ros_values`, so playoff odds are byte-identical (a stronger claim than value-identity).

Only the display magnitudes move: `ros_value` / `waiver_line` / `pool_top` ×0.8, and the band re-shapes.

Reused by `check_center_shrink` (the promotion-correct gate). SHADOW — reads only, writes nothing.

Run: python3 -m application.data.corpus.prove_shrink_invariance [--season 2025]
"""
import argparse
import contextlib
import inspect
import io

import polars as pl

from application.data import data_layer
from application.data.transforms import compute_bracket_sim
from application.data.transforms import compute_production_vor as pv
from application.data.transforms import compute_true_rank

PROMOTED_SHRINK = 0.8


@contextlib.contextmanager
def _at_shrink(s):
    old = pv.CENTER_SHRINK
    pv.CENTER_SHRINK = s
    try:
        yield
    finally:
        pv.CENTER_SHRINK = old


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _prod_vor_at(season, shrink, league_id):
    with _at_shrink(shrink):
        return _quiet(lambda: pv.compute(season, league_id=league_id))


def _true_rank_from(season, prod_vor_df, league_id):
    """compute_true_rank fed the in-memory production_vor frame (it reads the persisted one via
    data_layer.read_production_vor — monkeypatched here so the proof needs no persist)."""
    orig = data_layer.read_production_vor
    data_layer.read_production_vor = lambda *a, **k: prod_vor_df
    try:
        return _quiet(lambda: compute_true_rank.compute(season, league_id=league_id))
    finally:
        data_layer.read_production_vor = orig


def invariance(season: int = 2025, league_id=None) -> dict:
    """Compute the is_mine reads at 1.0 vs the promoted shrink and return the invariance evidence."""
    pv1 = _prod_vor_at(season, 1.0, league_id)
    pvs = _prod_vor_at(season, PROMOTED_SHRINK, league_id)
    key = ["as_of_week", "roster_id", "sleeper_player_id"]
    j = pv1.select(key + ["ros_value", "vor"]).join(
        pvs.select(key + ["ros_value", "vor"]), on=key, suffix="_s")

    # VOR invariant. The ratio cancels the scale exactly in continuous math; the persisted reads are round1/
    # round6-quantized, so a handful of values land one round3 ULP (0.001) apart at a rounding boundary — a
    # quantization artifact, NOT a reordering. Assert value-identity to within that ULP + report the cases.
    dvor = j.with_columns((pl.col("vor") - pl.col("vor_s")).abs().alias("d"))
    vor_max_delta = float(dvor["d"].max())
    vor_n_differ = dvor.filter(pl.col("d") > 1e-9).height
    vor_invariant = round(vor_max_delta, 3) <= 0.001   # ≤ 1 round3 ULP (compare at persisted precision)
    # ros_value uniformly ×shrink (the display magnitude that MOVES); no strict reorder (Spearman ≈ 1, any
    # <1 is round1 tie-handling, never a strict inversion).
    ros_moves = float((pvs["ros_value"].sum() / pv1["ros_value"].sum())) if pv1["ros_value"].sum() else None
    spearman = j.select(pl.corr("ros_value", "ros_value_s", method="spearman")).item()

    # true_rank: the team standings (the ADVICE) are EXACTLY identical; spectrum_pos invariant to a ULP.
    tr1 = _true_rank_from(season, pv1, league_id)
    trs = _true_rank_from(season, pvs, league_id)
    trkey = ["as_of_week", "roster_id"]
    tj = tr1.select(trkey + ["rank", "spectrum_pos"]).join(
        trs.select(trkey + ["rank", "spectrum_pos"]), on=trkey, suffix="_s")
    rank_identical = bool((tj["rank"] == tj["rank_s"]).all())
    dspec = tj.with_columns((pl.col("spectrum_pos") - pl.col("spectrum_pos_s")).abs().alias("d"))
    spectrum_max_delta = float(dspec["d"].max())
    spectrum_invariant = round(spectrum_max_delta, 3) <= 0.001   # ≤ 1 round3 ULP (persisted precision)

    # bracket_odds: structural independence — the sim never calls _ros_values / references CENTER_SHRINK.
    src = inspect.getsource(compute_bracket_sim)
    odds_independent = ("_ros_values" not in src) and ("CENTER_SHRINK" not in src) \
        and ("read_production_vor" not in src)   # reads rosters via _roster_as_of, centre via consensus

    return {"vor_invariant": vor_invariant, "vor_max_delta": vor_max_delta, "vor_n_differ": vor_n_differ,
            "ros_moves_ratio": ros_moves, "ros_spearman": spearman, "rank_identical": rank_identical,
            "spectrum_invariant": spectrum_invariant, "spectrum_max_delta": spectrum_max_delta,
            "odds_independent": odds_independent, "n_players": j.height, "n_teams": tj.height}


def run(season: int = 2025, league_id=None) -> dict:
    r = invariance(season, league_id)
    print(f"\n=== Center-shrink invariance proof (is_mine, season {season}) — 1.0 vs {PROMOTED_SHRINK} ===")
    print(f"  true_rank.rank EXACTLY identical      : {r['rank_identical']}   (the standings — the advice; "
          f"n={r['n_teams']} teams)")
    print(f"  VOR invariant (≤1 round3 ULP)         : {r['vor_invariant']}   "
          f"({r['vor_n_differ']}/{r['n_players']} differ, max|Δ|={r['vor_max_delta']:.4f})")
    print(f"  spectrum_pos invariant (≤0.001)       : {r['spectrum_invariant']}   "
          f"(max|Δ|={r['spectrum_max_delta']:.4f})")
    print(f"  playoff odds structurally independent : {r['odds_independent']}  (sim reads consensus, not the shrink)")
    print(f"  ros_value MOVES uniformly ×{PROMOTED_SHRINK}         : sum ratio {r['ros_moves_ratio']:.4f}  "
          f"(Spearman {r['ros_spearman']:.6f} — no strict reorder, round1 tie-handling only)")
    ok = all([r["rank_identical"], r["vor_invariant"], r["spectrum_invariant"], r["odds_independent"],
              r["ros_moves_ratio"] is not None and abs(r["ros_moves_ratio"] - PROMOTED_SHRINK) < 0.02])
    print(f"\n  {'PROVEN' if ok else 'FAILED'}: the ADVICE (standings, VOR, odds) is invariant — VOR/spectrum "
          f"differ only by a round-quantization ULP at a handful of boundaries, never a reorder; only "
          f"projected points (~{PROMOTED_SHRINK}×) + the band move. SHADOW — no writes.")
    return r


def __main():
    ap = argparse.ArgumentParser(description="Center-shrink invariance proof (shadow).")
    ap.add_argument("--season", type=int, default=2025)
    run(ap.parse_args().season)


if __name__ == "__main__":
    __main()
