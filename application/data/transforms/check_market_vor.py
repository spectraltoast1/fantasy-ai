"""
Check Market VOR — internal-consistency gate (DECISION_READS.md §4).

Market VOR is priced on the **current** LeagueLogs market. Against a past league season there is NO
future truth to grade the market with, so this is an **internal-consistency** gate (like
backtest_manager_features / check_ros_synthesis), not an answer-key backtest: it proves the read is
algebraically sound, the pools are right, and the time-world is stated honestly — not that the market
predicts anything (it can't be tested here).

**Cross-time is a state, not an error.** A slice whose market season ≠ league season is a POC and the
panel gates off (``api/reads._market_panel``); a same-season slice (2026 production × 2026 prices) is a
live read and the panel turns on. This gate therefore checks that the flag *tells the truth about the
data* rather than demanding one particular time-world — otherwise it would go red the day the read went
live. Use ``--expect`` to pin the mode when you know which one you're gating.

Verdicts (exit 0 iff all pass):

  1. **Recompute match** — independently re-run the shipped compute (`compute_market_vor.compute`) and
     demand the persisted parquet matches frame-for-frame. What's validated is exactly what serves the
     read (the backtest_production_vor idiom), so the stored market_vor / waiver / top / trade_gap are
     the real ones, not a re-derivation.
  2. **VOR algebra** — per (snapshot_date, pool): waiver_line ≤ pool_top; market_vor is monotonic
     non-decreasing in market_value (rank-preserving — immune to rounding); the pool_top-valued row
     maps to ≈1.0; negatives are strictly below the waiver line.
  3. **Pool integrity** — every row's pool == the shared `position_pools` mapping for its position, and
     those pools match what Production VOR uses for the same league (one shared engine).
  4. **Profile / coverage** — exactly one MARKET_PROFILE, no picks, rostered players only; the frozen
     roster's market coverage ≥ COVERAGE_MIN (missing players reported, not fatal).
  5. **Gap honesty (the crux)** — every row's is_cross_time == (market_season ≠ league season), and the
     slice is homogeneous (one time-world, never half-fused); has_production_vor == (production_vor is
     not null); trade_gap is null iff no production row and equals market_vor − production_vor
     otherwise. The market number is never silently fused across time.

Usage:
    python3 -m application.data.transforms.check_market_vor --season 2025
    python3 -m application.data.transforms.check_market_vor --season 2026 --expect contemporaneous
    python3 -m application.data.transforms.check_market_vor --season 2025 --prove-bites
"""

import argparse
import sys

import polars as pl
from polars.testing import assert_frame_equal

from application.data import data_layer
from application.data.transforms import compute_market_vor
from application.data.transforms._analytics import position_pools
from application.data.transforms.compute_production_vor import _pool_of

COVERAGE_MIN = 0.95
_KEY = ["season", "snapshot_date", "roster_id", "sleeper_player_id"]
EXPECT_MODES = ("auto", "cross-time", "contemporaneous")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _diagnose_staleness(df: pl.DataFrame, expected: pl.DataFrame) -> None:
    """Name the usual cause of a recompute mismatch, because it is almost never an algebra bug.

    Market VOR has **no cadence** — the weekly refresh rebuilds the spine (`compute_spine`), not this
    read, and the collectors only bank the raw series. So the persisted parquet drifts from `compute()`
    on two independent axes: the market series grows daily, and the league's `production_vor` advances a
    week at a time. Print both so the next reader doesn't have to re-derive "height mismatch".
    """
    p_last, e_last = df["snapshot_date"].max(), expected["snapshot_date"].max()
    if p_last != e_last:
        print(f"     ↳ the market series moved on: persisted through {p_last}, raw now runs to {e_last}")
    p_as_of = df["production_as_of"].unique().to_list()
    e_as_of = expected["production_as_of"].unique().to_list()
    if p_as_of != e_as_of:
        print(f"     ↳ production advanced: persisted priced against as_of_week {p_as_of}, now {e_as_of}")
    print("     ↳ nothing recomputes market_vor — re-run compute_market_vor to refresh the read.")


def _time_world(df: pl.DataFrame, expect: str = "auto") -> bool:
    """Verdict 5's time-world half — the flag must state what the data IS.

    Deliberately NOT "every row is cross-time". Cross-time (market season ≠ league season) is the POC
    state and gates the panel off; same-season is the live read and turns it on. Pinning the gate to one
    of those would turn it red the day the read went live, so what's asserted is the invariant that
    holds in both worlds: the flag matches the seasons on every row, and the slice states ONE time-world
    (a half-fused frame is exactly the silent cross-time fusion the column exists to prevent).
    """
    ok = True
    if df["is_cross_time"].null_count():
        ok = False; _fail(f"time-world: {df['is_cross_time'].null_count()} rows state no time-world (null)")
    lying = df.filter(pl.col("is_cross_time") != (pl.col("market_season") != pl.col("season")))
    if lying.height:
        ok = False; _fail(f"time-world: {lying.height} rows where is_cross_time ≠ (market_season ≠ season)")
    modes = set(df["is_cross_time"].drop_nulls().unique().to_list())
    if len(modes) > 1:
        ok = False; _fail("time-world: slice is part cross-time, part contemporaneous — a fused frame")
    actual = {frozenset({True}): "cross-time", frozenset({False}): "contemporaneous"}.get(
        frozenset(modes), "mixed/empty"
    )
    if expect != "auto" and actual != expect:
        ok = False; _fail(f"time-world: expected {expect}, the read is {actual}")
    if ok:
        panel = "panel gates OFF (POC, not a live call)" if actual == "cross-time" else "panel may render"
        _ok(f"time-world: {actual} on every row — the flag states the truth; {panel}")
    return ok


def check(season: int, expect: str = "auto") -> bool:
    # Resolve the is_mine league the same way every read/write wrapper does (via `_active_league`), then
    # read the FULL tall parquet — the recompute-match compares every banked snapshot against compute(),
    # so we deliberately bypass `read_market_vor`'s latest-snapshot-only default. This fixes the L0-keying
    # fallout (the bare `_market_vor_path(season)` call that crashed) while preserving the original
    # full-frame semantics; mirrors backtest_l0_keying's explicit-key path read.
    if not data_layer.market_vor_exists(season):
        _fail(f"no market_vor parquet for {season} — run compute_market_vor first")
        return False
    df = pl.read_parquet(data_layer._market_vor_path(season, data_layer._active_league(season)[0]))
    passed = True

    # 1. Recompute match — the persisted read IS the shipped compute, frame-for-frame.
    expected = compute_market_vor.compute(season)
    try:
        assert_frame_equal(
            df.sort(_KEY), expected.sort(_KEY), check_row_order=True, check_column_order=False
        )
        _ok(f"recompute match: persisted parquet == compute() output ({df.height} rows)")
    except AssertionError as e:
        passed = False
        _fail(f"recompute mismatch: persisted parquet != compute() output\n     {str(e).splitlines()[0]}")
        _diagnose_staleness(df, expected)

    # 2. VOR algebra, per (snapshot_date, pool). Reproduce market_vor from the stored waiver/top/value
    #    within a spread-aware tolerance — the stored columns are each rounded independently (value/
    #    waiver/top to 1dp, vor to 3dp), so exact reproduction is impossible; the bound scales as the
    #    rounding ÷ spread. A positive-slope affine reproduction implies monotonicity in value and that
    #    below-waiver values are negative, so those need no separate (rounding-fragile) checks.
    algebra_ok = True
    for (d, pool), g in df.group_by(["snapshot_date", "pool"]):
        wl, top = g["waiver_line"][0], g["pool_top"][0]
        if (g["waiver_line"] != wl).any() or (g["pool_top"] != top).any():
            algebra_ok = False; _fail(f"{d} {pool}: waiver/top not constant within the group")
        if wl > top:
            algebra_ok = False; _fail(f"{d} {pool}: waiver_line {wl} > pool_top {top}"); continue
        spread = top - wl
        if spread <= 0:
            continue  # degenerate pool → _vor floors at 0 by design; nothing to reproduce
        tol = 0.2 / spread + 0.005
        recomp = g.with_columns(((pl.col("market_value") - wl) / spread).alias("_r"))
        bad = recomp.filter((pl.col("market_vor") - pl.col("_r")).abs() > tol)
        if bad.height:
            algebra_ok = False; _fail(f"{d} {pool}: {bad.height} rows where market_vor ≠ (value−waiver)/spread (tol {tol:.3f})")
        at_top = g.filter(pl.col("market_value") == top)
        if at_top.height and abs(at_top["market_vor"].max() - 1.0) > 0.01:
            algebra_ok = False; _fail(f"{d} {pool}: pool_top row market_vor {at_top['market_vor'].max()} ≉ 1.0")
    if algebra_ok:
        _ok("VOR algebra: waiver≤top, market_vor reproduces (value−waiver)/spread (⇒ monotonic; negatives below waiver), top≈1.0")
    passed = passed and algebra_ok

    # 3. Pool integrity — pools match the shared engine and Production VOR.
    pool_of = _pool_of(data_layer.read_lineup_slots(season))
    mismatched = df.filter(
        pl.col("pool") != pl.col("position").replace_strict(pool_of, default=None)
    )
    if mismatched.height:
        passed = False; _fail(f"pool integrity: {mismatched.height} rows whose pool ≠ position_pools({{position}})")
    elif pool_of != position_pools(data_layer.read_lineup_slots(season).to_dicts()):
        passed = False; _fail("pool integrity: _pool_of diverged from position_pools")
    else:
        _ok(f"pool integrity: every row's pool matches the shared engine ({sorted(set(pool_of.values()))})")

    # 4. Profile / coverage.
    profs = df["market_profile"].unique().to_list()
    if profs != [compute_market_vor.MARKET_PROFILE]:
        passed = False; _fail(f"profile: expected only {compute_market_vor.MARKET_PROFILE}, got {profs}")
    else:
        _ok(f"profile: single format-matched profile {profs[0]}")
    season_df = data_layer.read_join_season(season).filter(
        pl.col("position").is_in(compute_market_vor.SKILL_POSITIONS)
    )
    from application.data.transforms.compute_production_vor import _roster_as_of
    roster = _roster_as_of(season_df, int(season_df["week"].max()))
    latest = df.filter(pl.col("snapshot_date") == df["snapshot_date"].max())
    covered = latest["sleeper_player_id"].n_unique()
    cov = covered / len(roster) if roster else 0.0
    if cov < COVERAGE_MIN:
        passed = False; _fail(f"coverage: {covered}/{len(roster)} frozen-roster players priced ({cov:.1%}) < {COVERAGE_MIN:.0%}")
    else:
        _ok(f"coverage: {covered}/{len(roster)} frozen-roster players priced ({cov:.1%})")

    # 5. Gap honesty — the time-world is stated truthfully, gap never fused, nulls where no production row.
    gap_ok = _time_world(df, expect)
    if df.filter(pl.col("has_production_vor") != pl.col("production_vor").is_not_null()).height:
        gap_ok = False; _fail("gap honesty: has_production_vor disagrees with production_vor nullity")
    if df.filter((~pl.col("has_production_vor")) & pl.col("trade_gap").is_not_null()).height:
        gap_ok = False; _fail("gap honesty: a no-production row has a non-null trade_gap (fabricated number)")
    fused = df.filter(
        pl.col("has_production_vor")
        & ((pl.col("market_vor") - pl.col("production_vor")).round(3) != pl.col("trade_gap"))
    )
    if fused.height:
        gap_ok = False; _fail(f"gap honesty: {fused.height} rows where trade_gap ≠ market_vor − production_vor")
    if gap_ok:
        n_gap = df.filter(pl.col("has_production_vor")).height
        _ok(f"gap honesty: {n_gap} gap rows = market_vor − production_vor; "
            f"{df.height - n_gap} no-production rows null (law 2)")
    passed = passed and gap_ok

    return passed


def prove_bites(season: int) -> bool:
    """Show the time-world predicate has teeth: three corruptions that MUST be caught.

    Also the contemporaneous proof. There is no 2026 league to compute against yet (`_active_league`
    raises), so the same-season case is exercised by re-labelling the banked frame's market_season to
    the league season — the exact shape a live 2026×2026 read produces — and demanding the gate call it
    `contemporaneous` and pass. That's the claim S3 makes: the read is ready, not that it's live.
    """
    df = pl.read_parquet(data_layer._market_vor_path(season, data_layer._active_league(season)[0]))
    all_ok = True

    print("\n--- prove-bites: each of these MUST be caught (a ✓ below would be the bug) ---")
    cases = [
        ("a flipped flag (says contemporaneous, seasons disagree)",
         df.with_columns(pl.when(pl.int_range(pl.len()) == 0).then(False)
                           .otherwise(pl.col("is_cross_time")).alias("is_cross_time")), "auto"),
        ("a half-fused frame (one row genuinely same-season, the rest cross-time)",
         df.with_columns(
             pl.when(pl.int_range(pl.len()) == 0).then(pl.col("season"))
               .otherwise(pl.col("market_season")).alias("market_season"),
             pl.when(pl.int_range(pl.len()) == 0).then(False)
               .otherwise(pl.col("is_cross_time")).alias("is_cross_time")), "auto"),
        ("a cross-time read gated as if it were live", df, "contemporaneous"),
    ]
    for label, frame, expect in cases:
        print(f"  [{label}]")
        if _time_world(frame, expect):
            all_ok = False; print("     !! NOT CAUGHT — the predicate is toothless here")

    print("\n--- prove-bites: the contemporaneous path (a same-season read must PASS) ---")
    same_season = df.with_columns(
        pl.col("season").alias("market_season"),
        pl.lit(False).alias("is_cross_time"),
    )
    if not _time_world(same_season, "contemporaneous"):
        all_ok = False; print("     !! a same-season read did NOT pass as contemporaneous")
    return all_ok


def main(season: int, expect: str = "auto", bites: bool = False) -> None:
    print(f"=== check_market_vor: season={season} expect={expect} ===")
    ok = check(season, expect)
    if bites:
        ok = prove_bites(season) and ok
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internal-consistency gate for Market VOR.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--expect", choices=EXPECT_MODES, default="auto",
                        help="pin the time-world: cross-time (POC, panel off) or contemporaneous (live)")
    parser.add_argument("--prove-bites", action="store_true",
                        help="show the time-world predicate catches corruptions + passes a same-season read")
    args = parser.parse_args()
    main(args.season, args.expect, args.prove_bites)
