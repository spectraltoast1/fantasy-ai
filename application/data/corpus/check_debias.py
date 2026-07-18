"""check_debias.py — the Session 7 de-bias gate (Improvement-Loop L4, the second anchor).

Asserts the de-bias is honest: it ships at identity, it is a decision-layer convex blend (not a projection
engine), BOTH reads actually consume the de-biased centre, the re-score is a shadow measurement that never
mutates the frozen corpus, the seasonal delta-tracking persists idempotently, and the whole thing is
deterministic. Mirrors check_tuner / check_spine: exit 0 iff every check passes, and a gate that can't fail
is not a gate — every check has a prove-bite.

  1. λ=0 IS IDENTITY (and λ>0 is NOT) — production_vor + the band at FORM_ANCHOR_W=0 recompute value-
     identical to the frozen spine; at λ>0 the number MOVES. Bite: a λ>0 that claimed "no change" fails.
  2. DECISION-LAYER, NOT A PROJECTION ENGINE (design law 3) — _ros_values is a convex blend of two EXISTING
     series: λ=0 → borrowed centre, λ=1 → recent_ppg × n_weeks, λ=0.5 → their exact midpoint. Bite: a
     non-convex / model-like output fails the algebra.
  3. THE CONSUMER USES IT (std instr 7) — BOTH production_vor AND the band inherit the de-biased centre
     (the shared _ros_values), so both frames move at λ>0. Bite: a read that ignored the dial would not move.
  4. THE RE-SCORE IS A SHADOW — it writes NOTHING to the frozen corpus (predictions / outcomes /
     resolutions / engine_scorecard). Bite: a spy on those writers catches any mutation.
  5. DELTA-TRACKING PERSISTS + IS IDEMPOTENT — center_gap exists, is provenanced, gap == predicted −
     realized, and re-writing the same rows appends nothing. Bite: a broken gap identity fails.
  6. DETERMINISTIC — recomputing at a fixed λ (0 and >0) is value-identical run-to-run. Bite: value-equality
     bites (differing values ≠; a row permutation ==).

Run: python3 -m application.data.corpus.check_debias
"""
import argparse
import contextlib
import io
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.transforms import compute_production_vor as pv
from application.data.transforms import compute_ros_player_band as band
from application.data.transforms.compute_production_vor import _ros_values
from application.data.transforms.backtest_ros_player_band import GRADE_WEEK, _canonical_actual


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:64} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


def _sample():
    """A present matched (league_id, season, scoring_key) to recompute against the frozen spine."""
    for t in compute_spine.targets(("matched",)):
        lid, season, sk = str(t["league_id"]), int(t["season"]), str(t["scoring_key"])
        if compute_spine._spine_present(lid, season):
            return lid, season, sk
    raise RuntimeError("no present matched league to check against")


def _at_lambda(lam, fn):
    """Run `fn` with the live FORM_ANCHOR_W dial temporarily set to `lam`, always restored."""
    old = pv.FORM_ANCHOR_W
    pv.FORM_ANCHOR_W = lam
    try:
        return fn()
    finally:
        pv.FORM_ANCHOR_W = old


def check() -> bool:
    results: list = []
    lid, season, sk = _sample()
    print(f"\n  gate over the S7 de-bias (identity · decision-layer · consumer · shadow · delta · determinism)")
    print(f"  sample: league {lid}  season {season}  scoring_key {sk}")

    pv_frozen = pl.read_parquet(data_layer._production_vor_path(season, lid))
    bd_frozen = pl.read_parquet(data_layer._ros_player_band_path(season, sk))

    # 1 — λ=0 identity, λ>0 moves --------------------------------------------------------------------
    print("  1 — λ=0 is identity (and λ>0 moves the number):")
    pv0 = _at_lambda(0.0, lambda: _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk)))
    bd0 = _at_lambda(0.0, lambda: _quiet(lambda: band.compute(season, scoring_key=sk)))
    _ok("production_vor λ=0 == frozen spine", _frame_eq(pv0, pv_frozen), results)
    _ok("ros_player_band λ=0 == frozen spine", _frame_eq(bd0, bd_frozen), results)
    pv5 = _at_lambda(0.5, lambda: _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk)))
    bd5 = _at_lambda(0.5, lambda: _quiet(lambda: band.compute(season, scoring_key=sk)))
    _ok("production_vor λ=0.5 ≠ frozen spine (the dial bites)", not _frame_eq(pv5, pv_frozen), results)
    _ok("ros_player_band λ=0.5 ≠ frozen spine (the dial bites)", not _frame_eq(bd5, bd_frozen), results)

    # 2 — decision-layer convex blend, not a projection engine (design law 3) ------------------------
    print("  2 — decision-layer: _ros_values is a convex blend of two existing series (design law 3):")
    cons = pl.DataFrame({
        "week": [1, 2, 3, 1, 2, 3], "sleeper_player_id": ["A", "A", "A", "B", "B", "B"],
        "position": ["RB"] * 6, "center_ppr": [10.0, 10.0, 10.0, 4.0, 4.0, 4.0],
    })
    rf = pl.DataFrame({"sleeper_player_id": ["A", "B"], "recent_ppg": [6.0, 9.0]})
    rem = [1, 2, 3]  # borrowed = 30 (A), 12 (B); form_ros = 6·3=18 (A), 9·3=27 (B)
    def val(df, pid):
        return float(df.filter(pl.col("sleeper_player_id") == pid)["ros_value"][0])
    r0 = _ros_values(cons, rem, recent_form=rf, form_anchor_w=0.0)
    r1 = _ros_values(cons, rem, recent_form=rf, form_anchor_w=1.0)
    rh = _ros_values(cons, rem, recent_form=rf, form_anchor_w=0.5)
    _ok("λ=0 → borrowed centre (A=30, B=12)", val(r0, "A") == 30.0 and val(r0, "B") == 12.0, results)
    _ok("λ=1 → recent_ppg × n_weeks (A=18, B=27)", val(r1, "A") == 18.0 and val(r1, "B") == 27.0, results)
    _ok("λ=0.5 → exact convex midpoint (A=24, B=19.5)",
        val(rh, "A") == 24.0 and val(rh, "B") == 19.5, results)
    rf_miss = pl.DataFrame({"sleeper_player_id": ["A"], "recent_ppg": [6.0]})  # B has no form
    rm = _ros_values(cons, rem, recent_form=rf_miss, form_anchor_w=1.0)
    _ok("no-form player keeps the borrowed centre (B=12 at λ=1)", val(rm, "B") == 12.0, results)

    # 3 — the consumer uses it: BOTH reads inherit the de-biased centre ------------------------------
    print("  3 — the consumer uses it (std instr 7): BOTH production_vor AND the band move at λ>0:")
    _ok("production_vor consumes the de-biased centre", not _frame_eq(pv5, pv0), results)
    _ok("ros_player_band consumes the de-biased centre", not _frame_eq(bd5, bd0), results)

    # 4 — the re-score is a SHADOW: it mutates no frozen-corpus entity -------------------------------
    print("  4 — the re-score is a shadow (writes NOTHING to the frozen corpus):")
    from application.data.corpus import rescore_debias
    frozen_writers = ["write_predictions", "write_outcomes", "write_resolutions", "write_engine_scorecard"]
    calls = []
    saved = {}
    for w in frozen_writers:
        if hasattr(data_layer, w):
            saved[w] = getattr(data_layer, w)
            setattr(data_layer, w, (lambda name: (lambda *a, **k: calls.append(name)))(w))
    try:
        truth = _canonical_actual(season, sk)
        cons2 = data_layer.read_projection_consensus(season, scoring_key=sk)
        _quiet(lambda: rescore_debias._coverage_at(season, sk, 0.5, truth, int(cons2["week"].max())))
    finally:
        for w, fn in saved.items():
            setattr(data_layer, w, fn)
    _ok("re-score wrote none of predictions/outcomes/resolutions/scorecard", not calls, results,
        "" if not calls else f"mutated: {calls}")

    # 5 — delta-tracking persists + is idempotent ---------------------------------------------------
    print("  5 — center-gap delta-tracking (persisted · provenanced · idempotent · gap == pred−real):")
    _ok("center_gap exists", data_layer.center_gap_exists(), results)
    cg = data_layer.read_center_gap()
    need = {"season", "scoring_key", "predicted_center", "realized", "gap", "code_version", "constants_hash"}
    _ok("rows carry (season, scoring_key, predicted, realized, gap, provenance)",
        cg.height > 0 and need.issubset(set(cg.columns)), results)
    gap_ok = all(abs((r["predicted_center"] - r["realized"]) - r["gap"]) < 1e-6 for r in cg.iter_rows(named=True))
    _ok("gap == predicted − realized (every row)", gap_ok, results)
    h0 = data_layer.read_center_gap().height
    data_layer.write_center_gap(data_layer.read_center_gap())  # re-write the SAME rows
    h1 = data_layer.read_center_gap().height
    _ok("re-writing the same rows appends nothing (idempotent by gap_id)", h0 == h1, results, f"h={h0}")

    # 6 — determinism -------------------------------------------------------------------------------
    print("  6 — determinism (recompute value-identical run-to-run at a fixed λ):")
    pv0b = _at_lambda(0.0, lambda: _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk)))
    pv5b = _at_lambda(0.5, lambda: _quiet(lambda: pv.compute(season, league_id=lid, scoring_key=sk)))
    _ok("λ=0 recompute is value-identical", _frame_eq(pv0, pv0b), results)
    _ok("λ=0.5 recompute is value-identical", _frame_eq(pv5, pv5b), results)
    _ok("value-equality bites (differing values ≠; a row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the S7 de-bias ships at identity, is a decision-layer "
          f"convex blend consumed by both reads, the re-score is a shadow, delta-tracking is idempotent, "
          f"and it is deterministic. Auto-tune, human promotes — nothing merged.")
    return ok


def main():
    argparse.ArgumentParser(description="Gate for the Session 7 de-bias.").parse_args()
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
