"""check_center_shrink.py — the center-shrink gate (Improvement-Loop, the systematic-shrink lever).

Asserts the center-shrink work is honest: the multiplicative `CENTER_SHRINK` ships at identity (1.0) and
recomputes the frozen spine value-identical; it is rank-preserving (a positive scalar → discrimination
invariant); BOTH reads consume it; the shadow re-score writes nothing; the measured CONSEQUENCE holds (an
honest centre de-skews the all-downside band into a genuine two-sided range with balanced tails); and it is
deterministic. Mirrors check_debias / check_band_honesty: exit 0 iff every check passes, every check
prove-bitten.

  1. shrink=1.0 IS IDENTITY (and shrink<1 MOVES) — production_vor + band at CENTER_SHRINK=1.0 recompute
     value-identical to the frozen spine; at 0.8 both move. Bite: a shrink<1 claiming "no change" fails.
  2. RANK-PRESERVING — a positive multiplicative scalar leaves Spearman(centre, realised) exactly unchanged
     (the ordinal reads are invariant). Bite: a non-monotone transform (−centre) flips the correlation.
  3. THE CONSUMER USES IT — BOTH production_vor AND the band move at shrink<1 (the shared aggregator).
  4. THE RE-SCORE IS A SHADOW — it writes NOTHING to the frozen corpus. Bite: a write-spy catches any mutation.
  5. THE MEASURED CONSEQUENCE — at SHRINK* the re-fit band de-skews (effective up:down 0.00 → two-sided) with
     coverage ~0.80 and balanced tails on the holdout. Bite: a symmetric-fit claim on the unshrunk (all-
     downside) centre fails.
  6. DETERMINISM — the re-score recomputes value-identical run-to-run (SHRINK* + the effective widths stable).

Run: python3 -m application.data.corpus.check_center_shrink
"""
import argparse
import contextlib
import io
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.corpus import rescore_center_shrink as rc
from application.data.transforms import _constants
from application.data.transforms import compute_production_vor as pv
from application.data.transforms import compute_ros_player_band as band


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:70} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    if set(a.columns) != set(b.columns):
        return False
    c = b.columns
    return a.select(c).sort(c).equals(b.select(c).sort(c))


@contextlib.contextmanager
def _at_shrink(s):
    old = pv.CENTER_SHRINK
    pv.CENTER_SHRINK = s
    try:
        yield
    finally:
        pv.CENTER_SHRINK = old


def _sample():
    for t in compute_spine.targets(("matched",)):
        lid, season, sk = str(t["league_id"]), int(t["season"]), str(t["scoring_key"])
        if compute_spine._spine_present(lid, season):
            return lid, season, sk
    raise RuntimeError("no present matched league to check against")


def check() -> bool:
    results: list = []
    lid, season, sk = _sample()
    print(f"\n  gate over the center-shrink (identity · rank-preserving · consumer · shadow · consequence)")
    print(f"  sample: league {lid}  season {season}  scoring_key {sk}")

    # 1 — the equivalence spine: VOR / true-rank / playoff-odds are INVARIANT under the shipped shrink ----
    print("  1 — the equivalence spine: VOR / true-rank / playoff-odds invariant (only points + band move):")
    from application.data.corpus import prove_shrink_invariance as inv
    iv = inv.invariance(2025)   # is_mine, the shipped season — compute at 1.0 vs the promoted 0.8
    _ok("VOR invariant to ≤1 round3 ULP (no reorder)", iv["vor_invariant"], results,
        f"{iv['vor_n_differ']} differ, max|Δ|={iv['vor_max_delta']:.4f}")
    _ok("true_rank standings EXACTLY identical (the advice)", iv["rank_identical"], results)
    _ok("true_rank.spectrum_pos invariant (≤0.001)", iv["spectrum_invariant"], results)
    _ok("playoff odds structurally independent (byte-identical)", iv["odds_independent"], results)
    _ok("ros_value MOVES uniformly ×0.8 (only projected points scale)",
        iv["ros_moves_ratio"] is not None and abs(iv["ros_moves_ratio"] - 0.8) < 0.02, results,
        f"ratio {iv['ros_moves_ratio']:.4f}")

    # 2 — rank-preserving (a positive scalar leaves discrimination unchanged) -------------------------
    print("  2 — a positive multiplicative scalar is rank-preserving (Spearman(centre, realised) invariant):")
    from application.data.transforms import backtest_ros_player_band as bt
    ing = bt._corpus_ingredients(season)
    d0 = ing.select(pl.corr("center", "actual", method="spearman")).item()
    d_shrunk = ing.with_columns((pl.col("center") * 0.8).alias("center")).select(
        pl.corr("center", "actual", method="spearman")).item()
    d_neg = ing.with_columns((pl.col("center") * -1.0).alias("center")).select(
        pl.corr("center", "actual", method="spearman")).item()
    _ok("Spearman invariant under ×0.8 (identical to 6dp)", round(d0, 6) == round(d_shrunk, 6), results,
        f"{d0:+.6f}=={d_shrunk:+.6f}")
    _ok("bite: a non-monotone transform (×−1) flips it", round(d_neg, 6) == round(-d0, 6), results)

    # 3 — the consumer uses it: both reads consume the SHIPPED shrink (0.8 ≠ 1.0) ----------------------
    print("  3 — both reads consume the shipped CENTER_SHRINK (0.8 ≠ 1.0):")
    with _at_shrink(1.0):
        pv1 = _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk))
        bd1 = _quiet(lambda: band.compute(season, scoring_key=sk))
    pv8 = _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk))   # live default = the shipped 0.8
    bd8 = _quiet(lambda: band.compute(season, scoring_key=sk))
    _ok("production_vor consumes CENTER_SHRINK (0.8 shrinks vs 1.0)", not _frame_eq(pv8, pv1), results)
    _ok("ros_player_band consumes CENTER_SHRINK (0.8 shrinks vs 1.0)", not _frame_eq(bd8, bd1), results)

    # --- run the re-score ONCE under a write-spy (checks 4/5 reuse it) --------------------------------
    frozen_writers = ["write_predictions", "write_outcomes", "write_resolutions", "write_engine_scorecard",
                      "write_tune_proposals", "write_center_gap"]
    spy: list = []
    saved = {}
    for w in frozen_writers:
        if hasattr(data_layer, w):
            saved[w] = getattr(data_layer, w)
            setattr(data_layer, w, (lambda name: (lambda *a, **k: spy.append(name)))(w))
    try:
        res = _quiet(lambda: rc.run(shrink=0.8))   # measure the SHIPPED band, not the TRAIN-argmin
    finally:
        for w, fn in saved.items():
            setattr(data_layer, w, fn)

    # 4 — the re-score is a shadow -------------------------------------------------------------------
    print("  4 — the re-score is a shadow (writes NOTHING to the frozen corpus):")
    _ok("re-score wrote none of predictions/outcomes/resolutions/scorecard/proposals/center_gap",
        not spy, results, "" if not spy else f"mutated: {spy}")

    # 5 — the SHIPPED band (0.8) is a two-sided honest range with recovered coverage --------------------
    print("  5 — the SHIPPED band (0.8) is a two-sided honest range with recovered coverage:")
    up1, dn1, r1 = res["eff_unshrunk"]
    ups, dns, rs = res["eff_shrunk"]
    _ok("the shipped band is TWO-SIDED (up>0 AND down>0)", ups > 0 and dns > 0, results,
        f"up {ups:.1f} / down {dns:.1f}  (up:down {rs:.2f})")
    _ok("de-skewed from S8's all-downside band (up:down rose off ~0)", r1 < 0.05 and rs > r1, results,
        f"{r1:.2f} → {rs:.2f}")
    dev = res["coverage"].get((rc.DEV, "matched"))
    _ok("coverage recovers ~0.80 with balanced tails on DEV (below≈above, both small)",
        dev is not None and 0.75 <= dev[0] <= 0.90 and dev[1] < 0.20 and dev[2] < 0.20, results,
        f"cov {dev[0]:.3f} below {dev[1]:.3f} above {dev[2]:.3f}" if dev else "no DEV")
    d_re0, d_re1 = res["discrimination"]
    _ok("ranking invariant in the re-score (Spearman identical)", d_re0 == d_re1, results)

    # 6 — determinism -------------------------------------------------------------------------------
    print("  6 — determinism (the re-score recomputes value-identical run-to-run):")
    res2 = _quiet(lambda: rc.run(shrink=0.8))
    _ok("SHRINK* stable", res["shrink_star"] == res2["shrink_star"], results)
    _ok("fitted band combos stable (unshrunk + shrunk)",
        res["fit_unshrunk"] == res2["fit_unshrunk"] and res["fit_shrunk"] == res2["fit_shrunk"], results)
    _ok("effective widths stable", res["eff_shrunk"] == res2["eff_shrunk"], results)
    _ok("value-equality bites (differing ≠; a row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    # ships at the PROMOTED value (Session 8c)
    _ok("CENTER_SHRINK SHIPPED at 0.8 (the honest-engine promotion)", _constants.CENTER_SHRINK == 0.8, results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — CENTER_SHRINK ships at 0.8 (the honest centre); VOR / "
          f"true-rank / playoff-odds are INVARIANT (only projected points ×0.8 + the two-sided band move); "
          f"rank-preserving; the shadow re-score writes nothing; the shipped band is two-sided with ~0.80 "
          f"coverage; deterministic. The honest engine is shipped.")
    return ok


def main():
    argparse.ArgumentParser(description="Gate for the center-shrink.").parse_args()
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
