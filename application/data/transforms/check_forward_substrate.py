"""
Check the forward-season substrate — the STRUCTURAL / sanity gate for a preseason build (P2/S1).

The two `backtest_*` substrate gates (projection_consensus, ros_player_band) grade the band's
coverage against realized points — the answer key. A forward season (2026 preseason) has **no
actuals yet**, so those gates cannot produce a verdict. This gate certifies what CAN be certified
without actuals: the 2026 consensus + band are well-formed, honestly prior-shaped, and reproduce the
shipped code — i.e. the forward-season path (compute_projection_consensus's pooled-residual prior)
did what it claims and nothing is silently broken or fabricated.

Verdicts (exit 0 iff all pass), for scoring_key ∈ {ppr, half}, season = 2026:

  1. Present + schema     — both derived parquet exist; columns == the 2025 reference frame's.
  2. Coverage            — all four skill positions present (QB/RB/WR/TE).
  3. Non-null core       — consensus center/p25/p50/p75/band and band ros_center/bull/bear/sigma.
  4. Ordering            — p25 ≤ p50 ≤ p75; ros_bear ≤ ros_center ≤ ros_bull (every row).
  5. Floors              — p25 ≥ 0, band ≥ 0, ros_bear ≥ 0, ros_sigma ≥ 0.
  6. Finite              — no NaN / inf in any numeric column.
  7. Forward invariant   — every consensus row n_resid == 0 and resid_std_raw null, and
                           band_ppr == resid_std_pos (one constant per position). This is the PROOF
                           that every player took the <2-residual fallback → band = positional prior.
  8. Prior tracks history — the 2026 positional prior equals _pooled_residuals(2020..2025) per
                           position (value-exact) and sits in a plausible fantasy-points range.
  9. Anchor honesty      — anchor_applied == (ANCHOR_W > 0 AND holdout_2026 curve present). Under the
                           shipped ANCHOR_W = 0.0 the ADP curve is evidence-only, so all False.
 10. Determinism         — recompute(2026) == the persisted parquet (value-equal, order-insensitive).
 11. Historical parity   — recompute(2024, 2025) consensus == persisted (the forward-season change
                           did NOT perturb the frozen corpus inputs). Consensus only: the persisted
                           2020-2025 *band* store is stale at the pre-8c CENTER_SHRINK=1.0 (it was
                           never rebuilt after the honest 0.8 shipped), so band-vs-persisted would
                           false-fail; the band's history no-op is proven separately by code-diff
                           isolation (git-stash) in the S1 audit, not against the stale store.

Plus inline "bites" checks so the gate provably has teeth.

Usage:
    python3 -m application.data.transforms.check_forward_substrate
"""

import argparse
import sys

import polars as pl
from polars.testing import assert_frame_equal

from application.data import data_layer
from application.data.transforms import compute_projection_consensus as C
from application.data.transforms import compute_ros_player_band as B
from application.data.transforms import _constants
from application.data.transforms._scoring import standard_scoring, scoring_profile

SEASON = 2026
KEYS = ["ppr", "half"]
SKILL = {"QB", "RB", "WR", "TE"}
_TOL = 2e-3  # resid_std_pos is round(.,3); pooled recompute is unrounded

CONS_SORT = ["week", "sleeper_player_id"]
BAND_SORT = ["as_of_week", "position", "sleeper_player_id"]
CONS_CORE = ["center_ppr", "p25_ppr", "p50_ppr", "p75_ppr", "band_ppr"]
BAND_CORE = ["ros_center", "ros_bull", "ros_bear", "ros_sigma"]


def _ok(label: str, cond: bool, results: list) -> None:
    print(f"  {'✓' if cond else '✗'} {label}")
    results.append(bool(cond))


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame, sort: list) -> bool:
    try:
        assert_frame_equal(a.sort(sort), b.sort(sort), check_row_order=False, check_column_order=False)
        return True
    except AssertionError:
        return False


def _no_nulls(df: pl.DataFrame, cols: list) -> bool:
    return all(df[c].null_count() == 0 for c in cols)


def _finite(df: pl.DataFrame) -> bool:
    for c, dt in zip(df.columns, df.dtypes):
        if dt in (pl.Float32, pl.Float64):
            bad = (df[c].is_nan() | df[c].is_infinite()).fill_null(False)
            if bad.any():
                return False
    return True


def _ordered(df: pl.DataFrame, lo: str, mid: str, hi: str) -> bool:
    """Every row satisfies lo ≤ mid ≤ hi (nulls fail — core cols are asserted non-null upstream)."""
    return df.filter((pl.col(lo) > pl.col(mid)) | (pl.col(mid) > pl.col(hi))).height == 0


def _pooled_pos_std(profile, scoring) -> dict:
    pooled = C._pooled_residuals(profile, scoring, exclude_season=SEASON)
    return {
        r["position"]: float(r["s"])
        for r in pooled.group_by("position").agg(pl.col("resid").std(ddof=0).alias("s")).iter_rows(named=True)
    }


def check() -> bool:
    r: list = []
    for key in KEYS:
        scoring = standard_scoring(key)
        profile = scoring_profile(scoring)
        print(f"\n--- scoring_key={key}  season={SEASON} ---")

        if not (data_layer._projection_consensus_path(SEASON, key).exists() and
                data_layer._ros_player_band_path(SEASON, key).exists()):
            _ok(f"{key}: both 2026 derived files present", False, r)
            continue
        cons = data_layer.read_projection_consensus(SEASON, scoring_key=key)
        band = pl.read_parquet(data_layer._ros_player_band_path(SEASON, key))
        cons_ref = data_layer.read_projection_consensus(2025, scoring_key=key)
        band_ref = pl.read_parquet(data_layer._ros_player_band_path(2025, key))

        # 1. Present + schema
        _ok("consensus columns == 2025 reference", set(cons.columns) == set(cons_ref.columns), r)
        _ok("band columns == 2025 reference", set(band.columns) == set(band_ref.columns), r)

        # 2. Coverage
        _ok("consensus covers all 4 skill positions", set(cons["position"].unique()) == SKILL, r)
        _ok("band covers all 4 skill positions", set(band["position"].unique()) == SKILL, r)

        # 3. Non-null core
        _ok("consensus core columns non-null", _no_nulls(cons, CONS_CORE), r)
        _ok("band core columns non-null", _no_nulls(band, BAND_CORE), r)

        # 4. Ordering
        _ok("consensus p25 ≤ p50 ≤ p75", _ordered(cons, "p25_ppr", "p50_ppr", "p75_ppr"), r)
        _ok("band ros_bear ≤ ros_center ≤ ros_bull", _ordered(band, "ros_bear", "ros_center", "ros_bull"), r)

        # 5. Floors
        _ok("consensus p25 ≥ 0 and band ≥ 0",
            cons.filter((pl.col("p25_ppr") < 0) | (pl.col("band_ppr") < 0)).height == 0, r)
        _ok("band ros_bear ≥ 0 and ros_sigma ≥ 0",
            band.filter((pl.col("ros_bear") < 0) | (pl.col("ros_sigma") < 0)).height == 0, r)

        # 6. Finite
        _ok("consensus has no NaN/inf", _finite(cons), r)
        _ok("band has no NaN/inf", _finite(band), r)

        # 7. Forward invariant — every player took the <2-residual fallback → band = positional prior
        _ok("consensus n_resid == 0 every row", cons["n_resid"].max() == 0 and cons["n_resid"].min() == 0, r)
        _ok("consensus resid_std_raw all null (no per-player residual)", cons["resid_std_raw"].null_count() == cons.height, r)
        _ok("consensus band_ppr == resid_std_pos every row (band IS the positional prior)",
            cons.filter((pl.col("band_ppr") - pl.col("resid_std_pos")).abs() > 1e-9).height == 0, r)
        _ok("consensus band_ppr is one constant per position",
            cons.group_by("position").agg(pl.col("band_ppr").n_unique().alias("n")).filter(pl.col("n") > 1).height == 0, r)

        # 8. Prior tracks history
        pooled = _pooled_pos_std(profile, scoring)
        got = {row["position"]: float(row["resid_std_pos"])
               for row in cons.group_by("position").agg(pl.col("resid_std_pos").first()).iter_rows(named=True)}
        _ok(f"positional prior == pooled 2020-2025 residual std (per position)  {[(p, round(pooled[p], 2)) for p in sorted(pooled)]}",
            all(abs(got[p] - pooled[p]) <= _TOL for p in SKILL), r)
        _ok("each positional prior in a plausible fantasy-points range (1..25)",
            all(1.0 <= got[p] <= 25.0 for p in SKILL), r)

        # 9. Anchor honesty
        expect_anchor = _constants.ANCHOR_W > 0 and data_layer.adp_points_curve_exists(holdout=SEASON)
        _ok(f"anchor_applied == (ANCHOR_W>0 and holdout_2026 present) = {expect_anchor} "
            f"(ANCHOR_W={_constants.ANCHOR_W})",
            bool(band["anchor_applied"].any()) == expect_anchor, r)

        # 10. Determinism — persisted IS the shipped compute
        _ok("consensus recompute(2026) == persisted", _frame_eq(C.compute(SEASON, scoring=scoring), cons, CONS_SORT), r)
        _ok("band recompute(2026) == persisted", _frame_eq(B.compute(SEASON, scoring_key=key), band, BAND_SORT), r)

    # 11. Historical parity — the corpus consensus inputs are not perturbed by the forward-season change.
    print("\n--- historical parity (consensus; band store is stale at pre-8c CENTER_SHRINK) ---")
    for s in (2024, 2025):
        sc = standard_scoring("ppr")
        _ok(f"consensus recompute(ppr {s}) == persisted",
            _frame_eq(C.compute(s, scoring=sc), data_layer.read_projection_consensus(s, scoring_key="ppr"), CONS_SORT), r)

    return all(r)


def _bites() -> bool:
    """Prove the structural predicates have teeth: a perturbed frame must fail them."""
    print("\n--- prove-it-bites ---")
    r: list = []
    cons = data_layer.read_projection_consensus(SEASON, scoring_key="ppr")

    # ordering bites: swap p25/p75 on one row → _ordered False
    bad = cons.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("p75_ppr")).otherwise(pl.col("p25_ppr")).alias("p25_ppr"),
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("p25_ppr")).otherwise(pl.col("p75_ppr")).alias("p75_ppr"),
    )
    _ok("ordering check bites (a p25/p75 swap fails _ordered)", not _ordered(bad, "p25_ppr", "p50_ppr", "p75_ppr"), r)

    # forward-invariant bites: a nonzero n_resid must be caught
    bad2 = cons.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(1).otherwise(pl.col("n_resid")).alias("n_resid"))
    _ok("forward-invariant bites (a nonzero n_resid fails)", bad2["n_resid"].max() != 0, r)

    # band=prior bites: perturb resid_std_pos on one row → band_ppr != resid_std_pos
    bad3 = cons.with_columns(
        pl.when(pl.int_range(pl.len()) == 0).then(pl.col("resid_std_pos") + 5.0).otherwise(pl.col("resid_std_pos")).alias("resid_std_pos"))
    _ok("band==prior check bites (a perturbed resid_std_pos fails)",
        bad3.filter((pl.col("band_ppr") - pl.col("resid_std_pos")).abs() > 1e-9).height > 0, r)

    # value-equality bites: a differing frame is not equal
    _ok("value-equality bites (a shifted center ≠ persisted)",
        not _frame_eq(cons.with_columns((pl.col("center_ppr") + 1).alias("center_ppr")), cons, CONS_SORT), r)

    return all(r)


def main() -> None:
    parser = argparse.ArgumentParser(description="Structural gate for the forward-season (2026 preseason) substrate.")
    parser.add_argument("--prove-bites", action="store_true", help="also run the teeth demonstration")
    args = parser.parse_args()
    print("=== check_forward_substrate ===")
    ok = check()
    if args.prove_bites:
        ok = _bites() and ok
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
