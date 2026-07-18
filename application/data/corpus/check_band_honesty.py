"""check_band_honesty.py — the Session 8 band-honesty gate (Improvement-Loop, the asymmetric band re-tune).

Asserts the band-honesty work is honest: the asymmetric band's SYMMETRIC default is value-identical to the
frozen spine, the vectorised sweep math mirrors the shipped band exactly, the joint re-tune's coverage
recovery holds on UNSEEN seasons + the league-wise holdout, the confidence re-score DEMONSTRATES the
ros_cv→ros_sigma flip (not ships it), both re-scores are shadows, and it's all propose-only + deterministic.
Mirrors check_tuner / check_debias: exit 0 iff every check passes, and a gate that can't fail is not a gate.

  1. SYMMETRIC DEFAULT IS IDENTITY (std instr 2) — with BEAR_Z==BULL_Z==1.44 the band recomputes
     value-identical to the frozen spine; a skewed BEAR_Z MOVES it. Bite: the moved band ≠ frozen.
  2. THE SWEEP MATH MIRRORS THE SHIPPED BAND — `_apply_dials` (the vectorised objective path) == the shipped
     `_blended_band` row-for-row, symmetric AND skewed. Bite: a bull/bear swap ≠ `_blended_band`.
  3. COVERAGE RECOVERS ON THE HOLDOUT (the win, std instr 6) — at the proposed dials, DEV 2024 + TEST 2025 +
     the generalization holdout climb from <0.65 toward ~0.80 with the below-bear tail collapsing.
  4. BEAR_Z IS A DISCIPLINED NEW DIAL — ships at symmetric identity (==BULL_Z==1.44), has NO
     constants_snapshot pin and NO check_tuner._MODULES drift entry (this gate covers it, the FORM_ANCHOR_W
     precedent). Bite: a non-identity default fails.
  5. THE CONFIDENCE RE-SCORE DEMONSTRATES THE FLIP (law-2) — ros_cv is inverted (Spearman>0, not honest) and
     reproduces the frozen scorecard (method check); ros_sigma is honest (Spearman ≤ −margin). Bite: the
     honest criterion applied to ros_cv is False.
  6. THE RE-SCORES ARE SHADOWS — the confidence + coverage re-scores write NOTHING to the frozen corpus.
     Bite: a spy on the writers catches any mutation.
  7. PROPOSE-ONLY — the live dials are unchanged (symmetric identity) and DIFFER from the proposed combo;
     nothing is shipped. Bite: a live dial that already moved fails.
  8. DETERMINISTIC — the re-scores recompute value-identical run-to-run.

Run: python3 -m application.data.corpus.check_band_honesty
"""
import argparse
import contextlib
import io
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import check_tuner
from application.data.corpus import compute_spine
from application.data.corpus import constants_snapshot as snap
from application.data.corpus import rescore_band_confidence as rc
from application.data.corpus import rescore_band_coverage as rcov
from application.data.corpus import scorecard_registry as reg
from application.data.transforms import _constants
from application.data.transforms import backtest_ros_player_band as bt
from application.data.transforms import compute_ros_player_band as band
from application.data.transforms.compute_ros_player_band import _blended_band


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:70} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


@contextlib.contextmanager
def _at_dials(*, bull_z=None, bear_z=None, anchor_w=None):
    """Temporarily set the band's live dial globals (always restored)."""
    ob, obr, oa = band.BULL_Z, band.BEAR_Z, band.ANCHOR_W
    if bull_z is not None:
        band.BULL_Z = bull_z
    if bear_z is not None:
        band.BEAR_Z = bear_z
    if anchor_w is not None:
        band.ANCHOR_W = anchor_w
    try:
        yield
    finally:
        band.BULL_Z, band.BEAR_Z, band.ANCHOR_W = ob, obr, oa


def _sample():
    for t in compute_spine.targets(("matched",)):
        lid, season, sk = str(t["league_id"]), int(t["season"]), str(t["scoring_key"])
        if compute_spine._spine_present(lid, season):
            return lid, season, sk
    raise RuntimeError("no present matched league to check against")


def _rowwise_band(df: pl.DataFrame, bull_z, bear_z, anchor_w):
    """The shipped `_blended_band` applied per row — the reference `_apply_dials` must match."""
    out = []
    for r in df.iter_rows(named=True):
        anchor = None if r["anchor_ceiling"] is None else \
            {"anchor_ceiling": r["anchor_ceiling"], "anchor_floor": r["anchor_floor"]}
        b = _blended_band(r["center"], r["sigma"], anchor, anchor_w * r["remaining_frac"],
                          bull_z=bull_z, bear_z=bear_z)
        out.append((b["ros_bull"], b["ros_bear"]))
    return out


def check() -> bool:
    results: list = []
    lid, season, sk = _sample()
    print(f"\n  gate over the Session-8 band honesty (identity · sweep math · win · confidence flip · shadow)")
    print(f"  sample: league {lid}  season {season}  scoring_key {sk}")

    # 1 — the symmetric default is identity (and a skew MOVES it) -------------------------------------
    print("  1 — symmetric default (BEAR_Z==BULL_Z==1.44) recomputes the frozen spine value-identical:")
    bd_frozen = pl.read_parquet(data_layer._ros_player_band_path(season, sk))
    bd_id = _quiet(lambda: band.compute(season, scoring_key=sk))
    _ok("symmetric default == frozen spine (value-identical)", _frame_eq(bd_id, bd_frozen), results)
    with _at_dials(bear_z=3.0):
        bd_skew = _quiet(lambda: band.compute(season, scoring_key=sk))
    _ok("a skewed BEAR_Z (3.0) MOVES the band (≠ frozen — the dial bites)",
        not _frame_eq(bd_skew, bd_frozen), results)

    # 2 — the vectorised sweep math mirrors the shipped band -----------------------------------------
    print("  2 — the sweep's _apply_dials == the shipped _blended_band (symmetric AND skewed):")
    ing = pl.DataFrame(bt._materialize(season, league_id=lid, scoring_key=sk), infer_schema_length=None)

    def _matches(bz, brz, aw):
        g = bt._apply_dials(ing, bz, brz, aw)
        exp = _rowwise_band(ing, bz, brz, aw)
        return all(abs(a - e[0]) < 1e-9 and abs(b - e[1]) < 1e-9
                   for a, b, e in zip(g["bull"].to_list(), g["bear"].to_list(), exp))
    _ok("_apply_dials == _blended_band at symmetric (1.44, 1.44, 0.25)", _matches(1.44, 1.44, 0.25), results)
    _ok("_apply_dials == _blended_band at skewed (0.0, 3.5, 0.0)", _matches(0.0, 3.5, 0.0), results)

    # --- the re-scores, run ONCE under a write-spy (checks 3/5/6/7 reuse them) -----------------------
    frozen_writers = ["write_predictions", "write_outcomes", "write_resolutions", "write_engine_scorecard",
                      "write_tune_proposals"]
    spy: list = []
    saved = {}
    for w in frozen_writers:
        if hasattr(data_layer, w):
            saved[w] = getattr(data_layer, w)
            setattr(data_layer, w, (lambda name: (lambda *a, **k: spy.append(name)))(w))
    try:
        conf = _quiet(lambda: rc.run(seasons=[2024, 2025]))
        cov = _quiet(lambda: rcov.run(seasons=[2024, 2025]))
    finally:
        for w, fn in saved.items():
            setattr(data_layer, w, fn)

    # 3 — the coverage win holds on unseen seasons + the league-wise holdout -------------------------
    print("  3 — coverage recovers at the proposed dials (DEV + sealed TEST + generalization):")
    bss = cov["by_season_stratum"]

    def _recovered(key):
        r = bss.get(key)
        if not r:
            return False, "no data"
        (c0, b0, _), (c1, b1, _) = r["current"], r["proposed"]
        good = c0 < 0.65 and 0.75 <= c1 <= 0.92 and b1 < b0 - 0.2
        return good, f"cov {c0:.3f}→{c1:.3f} below-bear {b0:.3f}→{b1:.3f}"
    for key, label in (((2024, "matched"), "DEV 2024"), ((2025, "matched"), "TEST 2025 (sealed)"),
                       ((2025, "generalization"), "generalization 2025 (league holdout)")):
        good, extra = _recovered(key)
        _ok(f"{label} coverage recovers (proposed ~0.80, below-bear collapses)", good, results, extra)

    # 4 — BEAR_Z is a disciplined new dial ----------------------------------------------------------
    print("  4 — BEAR_Z is a disciplined new dial (symmetric identity · no snapshot pin · gated here):")
    _ok("BEAR_Z ships at symmetric identity (== BULL_Z == 1.44)",
        _constants.BEAR_Z == _constants.BULL_Z == 1.44, results)
    _ok("BEAR_Z has NO constants_snapshot pin (symmetric default keeps constants_hash reproducible)",
        not any("BEAR_Z" in k for k in snap.SNAPSHOT), results)
    _ok("BEAR_Z has NO check_tuner._MODULES drift entry (this gate covers it — FORM_ANCHOR_W precedent)",
        "BEAR_Z" not in check_tuner._MODULES, results)

    # 5 — the confidence re-score demonstrates the ros_cv → ros_sigma flip ---------------------------
    print("  5 — the confidence re-score demonstrates the flip (ros_cv inverted → ros_sigma honest):")
    cv, sg = conf["pooled"][rc.CURRENT_SIGNAL], conf["pooled"][rc.PROPOSED_SIGNAL]
    _ok("ros_cv is INVERTED (Spearman > 0, not honest)",
        cv["spearman"] is not None and cv["spearman"] > 0 and not cv["honest"], results,
        f"ρ={cv['spearman']:+.3f}")
    _ok("ros_sigma is HONEST (Spearman ≤ −margin AND honest)",
        sg["spearman"] is not None and sg["spearman"] <= -reg.CONF_MONO_MARGIN and sg["honest"], results,
        f"ρ={sg['spearman']:+.3f}")
    fz = data_layer.read_engine_scorecard(2024).filter(
        (pl.col("read") == "ros_player_band") & (pl.col("slice_dim") == "overall"))
    fz_mono = fz["conf_monotonicity"][0] if fz.height else None
    reproduced = (fz_mono is not None
                  and abs(conf["per_season"][2024][rc.CURRENT_SIGNAL]["spearman"] - fz_mono) < 1e-6)
    _ok("the re-score reproduces the frozen scorecard's ros_cv conf_monotonicity (method check)",
        reproduced, results)

    # 6 — the re-scores are shadows -----------------------------------------------------------------
    print("  6 — both re-scores are shadows (write NOTHING to the frozen corpus):")
    _ok("confidence + coverage re-scores wrote none of predictions/outcomes/resolutions/scorecard/proposals",
        not spy, results, "" if not spy else f"mutated: {spy}")

    # 7 — propose-only: the live dials are unchanged and DIFFER from the proposal --------------------
    print("  7 — propose-only (the shipped dials are the symmetric identity; the fit is a proposal):")
    prop = cov["proposed"]
    live = {"BULL_Z": _constants.BULL_Z, "BEAR_Z": _constants.BEAR_Z, "ANCHOR_W": _constants.ANCHOR_W}
    _ok("the live dials are the symmetric identity (BEAR_Z==BULL_Z==1.44, ANCHOR_W==0.25) — nothing shipped",
        live["BEAR_Z"] == live["BULL_Z"] == 1.44 and live["ANCHOR_W"] == 0.25, results)
    _ok("the proposed combo DIFFERS from the live dials (a real proposal, human promotes)",
        any(prop[n] != live[n] for n in prop), results)

    # 8 — determinism -------------------------------------------------------------------------------
    print("  8 — determinism (the re-scores recompute value-identical run-to-run):")
    c1 = _quiet(lambda: rc.run(seasons=[2024]))
    c2 = _quiet(lambda: rc.run(seasons=[2024]))
    _ok("confidence re-score deterministic (Spearman stable)",
        c1["pooled"][rc.PROPOSED_SIGNAL]["spearman"] == c2["pooled"][rc.PROPOSED_SIGNAL]["spearman"]
        and c1["pooled"][rc.CURRENT_SIGNAL]["spearman"] == c2["pooled"][rc.CURRENT_SIGNAL]["spearman"], results)
    ingd = bt._corpus_ingredients(2024)
    ga = bt._score_per_key(bt._apply_dials(ingd, prop["BULL_Z"], prop["BEAR_Z"], prop["ANCHOR_W"]))
    gb = bt._score_per_key(bt._apply_dials(ingd, prop["BULL_Z"], prop["BEAR_Z"], prop["ANCHOR_W"]))
    _ok("band coverage recompute value-identical", _frame_eq(ga, gb), results)

    # --- PROVE-BITES ------------------------------------------------------------------------------
    print("  PROVE-BITES:")
    swapped = ing.with_columns(bt._apply_dials(ing, 1.44, 3.0, 0.25)["bear"].alias("bull"))  # wrong bull
    exp = _rowwise_band(ing, 1.44, 3.0, 0.25)
    bite2 = not all(abs(a - e[0]) < 1e-9 for a, e in zip(swapped["bull"].to_list(), exp))
    _ok("check-2 bites (a bull/bear swap ≠ _blended_band)", bite2, results)
    _ok("check-5 bites (the honest criterion applied to ros_cv is False — it is not honest)",
        not cv["honest"], results)
    _ok("value-equality bites (differing ≠; a row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the asymmetric band's symmetric default is identity, the "
          f"sweep math mirrors the shipped band, the joint re-tune's coverage recovery holds on unseen "
          f"seasons + the league holdout, the confidence re-score demonstrates the ros_cv→ros_sigma flip, "
          f"both re-scores are shadows, and it is propose-only + deterministic. Human promotes.")
    return ok


def main():
    argparse.ArgumentParser(description="Gate for Session 8 band honesty.").parse_args()
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
