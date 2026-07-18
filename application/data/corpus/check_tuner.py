"""check_tuner.py — the L4 Tuner gate (Improvement-Loop Session 6, commit 3).

Asserts that the Tuner is honest: the dials registry is the single source of truth (and the modules
actually import it), the split is STRUCTURAL (a peeking fit cannot silently succeed), one driver re-fits
any dial, every proposal carries its full evidence, the four guardrails BITE, the first run is disciplined
(the band dials HELD with the entanglement reason, de-bias the top lead), and the proposals are
value-identical on a re-run. Mirrors `check_scorecard` / `check_resolutions`: exit 0 iff every check
passes, and a gate that can't fail is not a gate — every check has a prove-bite.

  1. REGISTRY IS THE SOURCE OF TRUTH — for each of the 5 dials, registry.current == the live module global
     == the frozen constants snapshot; the 3 owning modules IMPORT (re-export) the registry (consumer-uses-
     it, standing instr 7). BULL_Z resolved by declaration (1.44). Bite: drift a live global.
  2. THE SPLIT IS STRUCTURAL — a fit reaching for TEST 2025, a generalization league, or certifying on
     TRAIN each RAISE ForbiddenPartition (the bites ARE the checks — peeking is unrepresentable).
  3. THE HARNESS IS GENERAL — one objective(season, consts, *, reader) resolves from Tunable.gate for every
     dial and returns the read's own verdict-path number (no bespoke per-constant path). Bite: a fabricated
     gate name does not resolve.
  4. GUARDRAILS BITE — the pure verdict HOLDs a train-only win, a coupled regression, and a sub-floor
     effect, and RECOMMENDs only a clean un-entangled pass; entanglement overrides even a clean pass.
  5. RUN DISCIPLINED — de-bias is the rank-1 LEAD; the WEEKLY-band dials (BAND_Z, SKEW_GAIN) stay HELD with
     the entanglement reason (nothing entangled is RECOMMENDED); the ROS-band dials (BULL_Z, BEAR_Z,
     ANCHOR_W) are UN-entangled and re-fit JOINTLY on the corpus objective (Session 8) → they RECOMMEND, with
     a REAL (bool, not None) coupled guardrail; OPP_HALF_LIFE_WK is swept on the holdout. Every proposal row
     carries its evidence + a RECOMMEND/HOLD/LEAD verdict.
  6. DETERMINISM — rebuilding the proposals is value-identical (the pinned as-of + rounded metrics). Bite:
     a perturbed metric ≠; a row permutation ==.

Run: python3 -m application.data.corpus.check_tuner
"""
import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import constants_snapshot as snap
from application.data.corpus import tuner
from application.data.transforms import _constants

_MODULES = {
    "BAND_Z": "compute_projection_consensus", "SKEW_GAIN": "compute_projection_consensus",
    "BULL_Z": "compute_ros_player_band", "ANCHOR_W": "compute_ros_player_band",
    "OPP_HALF_LIFE_WK": "compute_player_signal",
}
# Session 8 split the band dials by read: the WEEKLY-band dials (projection_consensus) stay HELD as
# entangled with the optimistic centre; the ROS-band dials (ros_player_band) are un-entangled and re-fit
# JOINTLY (S7's null: the ROS band under-covers on its own — a width problem, not centre height).
_WEEKLY_BAND_DIALS = {"BAND_Z", "SKEW_GAIN"}
_ROS_BAND_DIALS = ("BULL_Z", "BEAR_Z", "ANCHOR_W")


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:70} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort("proposal_id").equals(b.select(cols).sort("proposal_id"))


def _live_global(dial):
    import importlib
    mod = importlib.import_module(f"application.data.transforms.{_MODULES[dial]}")
    return getattr(mod, dial)


# --- predicates shared by checks AND bites ----------------------------------------------------------

def _registry_is_truth() -> bool:
    """Every dial's registry current == the live re-exported module global == the frozen snapshot pin."""
    for name in _MODULES:
        reg = _constants.REGISTRY[name].current
        live = _live_global(name)
        pin = snap.SNAPSHOT[f"{_MODULES[name].replace('compute_', '')}.{name}"]
        if not (reg == live == pin):
            return False
    return True


def check(seasons=None) -> bool:
    results = []
    print("\n  gate over the L4 tuner (dials registry · split · guardrails · first run · determinism)")

    # 1 — registry is the source of truth --------------------------------------------------------------
    print("  1 — registry is the single source of truth (current == live global == frozen pin):")
    _ok("all 5 dials: registry.current == module global == constants_snapshot", _registry_is_truth(), results)
    _ok("BULL_Z resolved by declaration to 1.44 (drift killed)",
        _constants.REGISTRY["BULL_Z"].current == 1.44 and _live_global("BULL_Z") == 1.44, results)
    _ok("constants_snapshot drift gate green (live globals match the frozen fingerprint)",
        snap.check_constants_drift()["ok"], results)

    # 2 — the split is structural ----------------------------------------------------------------------
    print("  2 — the split is structural (a peeking fit RAISES — the bite is the check):")
    _ok("a fit reaching for TEST 2025 raises ForbiddenPartition", tuner.prove_test_sealed(), results)
    _ok("a fit reaching for a never_tune generalization league raises", tuner.prove_generalization_sealed(),
        results)
    _ok("certifying on a TRAIN season (peeking) raises", tuner.prove_certify_not_train(), results)

    # 3 — the harness is general -----------------------------------------------------------------------
    print("  3 — one driver re-fits any dial (objective resolves from Tunable.gate; no per-constant path):")
    resolves = True
    for t in _constants.tunables():
        try:
            fn = tuner.objective_fn(t)
            resolves &= callable(fn)
        except Exception:
            resolves = False
    _ok("objective(season, consts, *, reader) resolves for every registered dial", resolves, results)

    # 4 — the four guardrails bite ---------------------------------------------------------------------
    print("  4 — the four guardrails bite (pure verdict on synthetic guardrail states):")
    dv = tuner.decide_verdict
    clean = dict(entangled=False, changed=True, g_holdout=True, g_effect=True, g_inputs=True, g_coupled=True)
    _ok("a clean un-entangled pass RECOMMENDs (the harness CAN recommend)",
        dv(**clean)[0] == "RECOMMEND", results)
    _ok("a train-only win (holdout does not improve) is HELD",
        dv(**{**clean, "g_holdout": False})[0] == "HOLD", results)
    _ok("a coupled regression is HELD", dv(**{**clean, "g_coupled": False})[0] == "HOLD", results)
    _ok("a sub-floor effect is HELD", dv(**{**clean, "g_effect": False})[0] == "HOLD", results)
    _ok("a degraded fit window (inputs_ok) is HELD", dv(**{**clean, "g_inputs": False})[0] == "HOLD", results)
    _ok("entanglement OVERRIDES even a clean pass (band dials HELD however good the sweep)",
        dv(**{**clean, "entangled": True})[0] == "HOLD", results)

    # 5 — the run is disciplined ------------------------------------------------------------------------
    print("  5 — the run is disciplined (de-bias lead · weekly-band HELD · ros-band joint RECOMMEND · evidence):")
    ordered, rows = tuner.build_proposals()
    by = {p.constant: p for p in ordered}
    _ok("de-bias-the-center is the rank-1 LEAD",
        ordered[0].constant == "center_debias" and ordered[0].verdict == "LEAD", results)
    # The WEEKLY-band dials (projection_consensus) stay entangled/HELD; the entangled set is EXACTLY them.
    weekly_held = all(by[d].verdict == "HOLD" and tuner.ENTANGLE_REASON in by[d].hold_reason
                      for d in _WEEKLY_BAND_DIALS)
    _ok("the weekly-band dials (BAND_Z, SKEW_GAIN) HELD with the entanglement reason", weekly_held, results)
    _ok("nothing entangled is RECOMMENDED (ENTANGLED == exactly the weekly-band dials)",
        tuner.ENTANGLED == frozenset(_WEEKLY_BAND_DIALS)
        and not any(by[d].verdict == "RECOMMEND" for d in _WEEKLY_BAND_DIALS), results)
    _ok("SKEW_GAIN confirms the entanglement (OOS fit moves toward 0 — 1.5→1.0)",
        by["SKEW_GAIN"].proposed == 1.0 and "CONFIRMED" in by["SKEW_GAIN"].hold_reason, results)
    opp = by["OPP_HALF_LIFE_WK"]
    _ok("OPP_HALF_LIFE_WK swept on the holdout (a TRAIN + DEV metric exists)",
        opp.n_train_seasons == len(tuner.TRAIN_SEASONS) and opp.dev_metric_current is not None, results)
    ev_cols = ["verdict", "hold_reason", "baseline_constants_hash", "asof_date", "rank"]
    _ok("every proposal row carries its evidence (verdict + reason + baseline + asof + rank)",
        all(rows[c].null_count() == 0 for c in ev_cols), results)
    # Session 8: the ros-band dials are UN-entangled + fit JOINTLY on the across-as-of-weeks corpus objective,
    # on a full n=4 TRAIN window; the joint fit clears the guardrails → all three RECOMMEND, and the coupled
    # guardrail is REAL (a bool, not the 6b None). All three share one joint holdout effect.
    _ok("BULL_Z/BEAR_Z/ANCHOR_W fit jointly on a full TRAIN window (n=4, corpus objective)",
        all(by[d].n_train_seasons == len(tuner.TRAIN_SEASONS) for d in _ROS_BAND_DIALS), results)
    _ok("the ros-band dials un-entangled + RECOMMEND (the S8 joint band re-tune clears the guardrails)",
        all(by[d].verdict == "RECOMMEND" for d in _ROS_BAND_DIALS), results)
    _ok("the coupled guardrail is REAL for the joint fit (a bool, not the 6b None)",
        all(isinstance(by[d].g_coupled, bool) for d in _ROS_BAND_DIALS), results)
    # S7: the 6th dial (the de-bias) is swept on the split and ships at IDENTITY (0.0) — HELD, a proposal
    # only (its own λ=0 identity + shadow re-score are gated by check_debias, not here).
    fa = by.get("FORM_ANCHOR_W")
    _ok("FORM_ANCHOR_W (S7 de-bias) swept on the split, ships at 0.0, HELD (proposal only)",
        fa is not None and fa.current == 0.0 and fa.verdict == "HOLD"
        and fa.n_train_seasons == len(tuner.TRAIN_SEASONS), results)

    # 6 — determinism ----------------------------------------------------------------------------------
    print("  6 — determinism (rebuild value-identical; the pinned as-of + rounded metrics):")
    _, rows2 = tuner.build_proposals()
    _ok("rebuilding the proposals is value-identical", _frame_eq(rows, rows2), results)

    # --- PROVE-BITES (every check above can fail) -----------------------------------------------------
    print("  PROVE-BITES:")
    # 1: drift a live global away from the registry → registry-is-truth reddens (restored)
    import importlib
    mod = importlib.import_module("application.data.transforms.compute_projection_consensus")
    orig = mod.BAND_Z
    mod.BAND_Z = 0.99
    bite1 = not _registry_is_truth() and not snap.check_constants_drift()["ok"]
    mod.BAND_Z = orig
    _ok("check-1 bites (a live global drifting from the registry reddens truth + drift gate)", bite1, results)
    # 3: a fabricated gate does not resolve
    from dataclasses import replace
    bogus = replace(_constants.REGISTRY["BAND_Z"], gate="backtest_does_not_exist")
    try:
        tuner.objective_fn(bogus)
        bite3 = False
    except Exception:
        bite3 = True
    _ok("check-3 bites (a fabricated Tunable.gate does not resolve)", bite3, results)
    # 4: a NON-bite would be decide_verdict recommending a failing state — assert it does NOT
    _ok("check-4 bites (decide_verdict does NOT recommend a train-only win)",
        tuner.decide_verdict(entangled=False, changed=True, g_holdout=False, g_effect=True,
                             g_inputs=True, g_coupled=True)[0] != "RECOMMEND", results)
    # 6: a perturbed metric ≠ ; a row permutation ==
    perturbed = rows.with_columns(
        pl.when(pl.col("constant") == "SKEW_GAIN").then(-999.0).otherwise(pl.col("effect_size"))
        .alias("effect_size"))
    _ok("check-6 bites (a perturbed metric ≠; a row permutation ==)",
        (not _frame_eq(rows, perturbed)) and _frame_eq(rows, rows.reverse()), results)
    # 6b: the corpus band objective returns a real TRAIN window where the is_mine-only path does NOT — the
    # rewire's scope is exactly the fix. Positive: objective computable on a TRAIN season. Inverse bite: the
    # is_mine _test_points (no league_id) still raises on that season (no is_mine spine pre-2024).
    from application.data.transforms import backtest_ros_player_band as _brb
    _train = tuner.TRAIN_SEASONS[0]
    corpus_ok = isinstance(_brb.objective(_train, {}), float)
    try:
        _brb._test_points(_train, 1.44, 0.25)          # is_mine default (no league_id)
        ismine_empty = False
    except (FileNotFoundError, ValueError):
        ismine_empty = True
    _ok("check-6b bites (corpus band objective computes on TRAIN; the is_mine-only grade still raises)",
        corpus_ok and ismine_empty, results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the L4 tuner's registry is the source of truth, the "
          f"split is structural (peeking raises), one driver re-fits any dial, the four guardrails bite, "
          f"the run is disciplined (de-bias top lead; weekly-band HELD; ros-band un-entangled + joint "
          f"RECOMMEND, S8), and the proposals are deterministic. Auto-tune, human promotes — no transform "
          f"edited, nothing merged.")
    return ok


def main():
    argparse.ArgumentParser(description="Gate for the L4 tuner (Session 6).").parse_args()
    sys.exit(0 if check() else 1)


if __name__ == "__main__":
    main()
