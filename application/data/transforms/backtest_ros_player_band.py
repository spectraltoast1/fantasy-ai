"""
Backtest the ROS Player Band bull/bear band against the full-2025 answer key.

(Renamed from backtest_ros_outcome_shape.py in the L0 keying split — the band it validates is now the
scoring-scoped ros_player_band; the calibration is computed on the is_mine league's rostered players
[band ⋈ production_vor], reproducing the pre-split numbers since it rebuilds the band through the same
pure functions from production_vor.ros_value.)

The gate §2's quantitative skeleton (DECISION_READS.md §2) must clear: is the rest-of-season
bull/bear range **calibrated** — does a player's realised ROS production actually land inside
[ros_bear, ros_bull] about as often as the interval claims? Bull/bear is the ROS-horizon analog
of the §3 weekly spread, so it earns its width the same way §3 does: against reality, not by
assumption. Two verdicts (exit 0 iff both pass):

  - **Calibration (predictive)** — at the freeze week, the fraction of players whose actual ROS
    lands in [ros_bear, ros_bull] must sit within COVERAGE_TOL of the TARGET (0.80 — an ~80% "good
    season / bad season" range, §2's realistic high/low). The two tail rates (below-bear /
    above-bull) are reported as evidence: the skeleton's band is symmetric-by-design (no ROS-level
    skew term — a documented deferral; the §3 per-week band already carries the skew this sums
    over), so we gate combined coverage and *report* tail balance. `objective(season, {BULL_Z, ANCHOR_W})`
    returns the freeze-week score the split-aware harness (corpus/tuner.py) sweeps BULL_Z against — the
    ROS analog of the §3 gate's BAND_Z sweep. This is the real test: summing independent weekly bands
    assumes zero residual autocorrelation, and BULL_Z absorbs whatever that assumption gets wrong.
  - **Decision-relevant** — sort players by ros_bull (the ceiling) into terciles and confirm actual
    realised ROS rises monotonically (dead < mid < stud), the way backtest_production_vor tests VOR
    tiers. Confirms the bull ceiling carries ranking signal, not just width.

It imports the SAME pure functions the transform ships (`_ros_sigma`, `_preseason_anchor`,
`_blended_band`, `_load_anchor_inputs`) — what's validated is exactly what serves the read, no
re-derivation. Per-player realised ROS is a simple
Σ actual PPR over the remaining weeks (a player read, not a team read — no optimal_lineup). The
band's forward inputs (each week's band_ppr, built from weeks < that week) never see the actuals
they're tested against — no leakage.

**Small-sample honesty (documented):** the primary gate is the **freeze-week** snapshot (each
player once, longest real ROS). Coverage across ~160 players is a fair calibration sample, but a
league-wide over/under-projection correlates their misses, so pooling the nested per-week windows
(same player at N=1..4) would inflate n without independent signal — reported as evidence only.

**Preseason-anchor honesty (documented):** the roster is frozen at weeks 1–4, so every tested cutoff
(N=1..4) sits in the **early / prior-heavy** regime — the anchor weight w_N = ANCHOR_W · (remaining/
total) is near its max here (≈0.19 at the freeze). The late-season, evidence-heavy tail of the decay
(w_N → 0 as the horizon closes) is asserted by construction, not exercised by this answer key; it
cannot be until an as-of week past the freeze exists. The tuner therefore sweeps ANCHOR_W where the
anchor matters most, which is the honest place to tune it. The gate reports the pre-anchor vs
anchored freeze-week tails so the anchor's calibration contribution is visible, not assumed.

Usage:
    python3 -m application.data.transforms.backtest_ros_player_band --season 2025   # verdict
    python3 -m application.data.corpus.tuner                                         # the split-aware sweep
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean
from application.data.transforms.compute_ros_player_band import (
    ANCHOR_W, BEAR_Z, BULL_Z, SKILL_POSITIONS, _blended_band, _load_anchor_inputs, _preseason_anchor,
    _ros_sigma,
)

# Target bull/bear coverage — the fraction of players whose actual ROS should land in the band.
# 0.80 = an ~80% (10th/90th) "good season / bad season" interval, §2's realistic high/low.
TARGET_COVERAGE = 0.80
# The freeze-week combined coverage must land within this of TARGET_COVERAGE.
COVERAGE_TOL = 0.05
# The BULL_Z / ANCHOR_W candidate grids are homed in the L4 registry (_constants.py) — the one home for a
# swept dial. The joint sweep is retired into the split-aware harness (corpus/tuner.py).
#
# The `run()` VERDICT below stays is_mine-scoped (the shipped gate, freeze-week coverage 0.817). The TUNER
# `objective` is CORPUS-scoped (Session 6b): it pools rostered-freeze players across the 221 matched leagues
# grouped by scoring_key, so BULL_Z/ANCHOR_W get a real out-of-sample TRAIN 2020–23 window (the is_mine
# objective had none pre-2024). The dials still HOLD — entangled with the optimistic center; this is
# testability, not promotion (the band re-tune is Session 8, post-de-bias).
#
# GRADE_WEEK — the single week-4 as-of cutoff the 6b INTERIM corpus objective graded at. Session 8 RETIRED
# it from `objective` (which now grades ACROSS the season's as-of weeks via `_corpus_ingredients`); it is
# KEPT here only because the S7 shadow substrate still pins to it — `backfill_center_gap` /
# `rescore_debias` / `check_debias` import GRADE_WEEK for the seasonal centre-gap grade. Do not re-add it to
# the band objective.
GRADE_WEEK = 4


def _actual_weekly(season: int, *, reader=data_layer) -> dict:
    """(sleeper_player_id, week) → actual PPR points, the answer key for realised ROS."""
    df = (
        reader.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS))
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual"))
    )
    return {(r["sleeper_player_id"], r["week"]): float(r["actual"]) for r in df.iter_rows(named=True)}


def _test_points(season: int, bull_z: float, anchor_w: float, *, bear_z: float | None = None,
                 reader=data_layer, league_id=None, scoring_key=None, cutoffs=None, actual=None,
                 anchor_inputs=None):
    """One row per (as_of_week N, player): the shipped bull/bear band + the actual ROS over the same
    remaining weeks. Rebuilds the band through the transform's own `_preseason_anchor` / `_blended_band`
    (and `_load_anchor_inputs`), so what's validated is exactly what serves the read — no re-derivation.
    Returns (rows, freeze_week). Security is carried for the situation-axis evidence line. `reader` is the
    data seam (default `data_layer`); the tuner passes a `SplitReader` that raises on a sealed season —
    the first read below (production_vor) bites, so a peeking fit cannot reach the answer key.

    Defaults reproduce the shipped is_mine grade (used by `run()`): `league_id`/`scoring_key` None →
    is_mine league + its scoring profile; `cutoffs` None → grade every as-of week; `actual` None →
    nfl_stats PPR; `anchor_inputs` None → load per season. The corpus objective (Session 6b) passes an
    explicit `league_id`+`scoring_key`, `cutoffs=[GRADE_WEEK]`, the scoring-scoped canonical `actual`, and a
    once-per-season `anchor_inputs` — so it grades the same math on the matched cohort."""
    vor = reader.read_production_vor(season, league_id=league_id, as_of_week="all").select(
        "as_of_week", "roster_id", "sleeper_player_id", "position", "ros_value", "n_weeks"
    )
    consensus = reader.read_projection_consensus(season, scoring_key=scoring_key).select(
        "week", "sleeper_player_id", "band_ppr"
    )
    signal = reader.read_player_signal(season, league_id=league_id, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "security"
    )
    if actual is None:
        actual = _actual_weekly(season, reader=reader)
    adp_map, curve_lookup, curve_max_rank = anchor_inputs if anchor_inputs is not None \
        else _load_anchor_inputs(season)
    bz = bull_z if bear_z is None else bear_z   # bear_z defaults to bull_z → historically-symmetric band

    weeks = sorted(vor["as_of_week"].unique().to_list())
    freeze = max(weeks)
    if cutoffs is not None:
        weeks = [w for w in weeks if w in cutoffs]
    max_proj_week = int(consensus["week"].max())

    rows = []
    for n in weeks:
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        sigma_map = {
            r["sleeper_player_id"]: r["ros_sigma"]
            for r in _ros_sigma(consensus, remaining).iter_rows(named=True)
        }
        sec_map = {
            r["sleeper_player_id"]: r["security"]
            for r in signal.filter(pl.col("as_of_week") == n).iter_rows(named=True)
        }
        for r in vor.filter(pl.col("as_of_week") == n).iter_rows(named=True):
            pid = r["sleeper_player_id"]
            remaining_frac = r["n_weeks"] / max_proj_week if max_proj_week else 0.0
            anchor = _preseason_anchor(adp_map.get(pid), curve_lookup, curve_max_rank, remaining_frac)
            band = _blended_band(
                r["ros_value"], sigma_map.get(pid, 0.0), anchor, anchor_w * remaining_frac,
                bull_z=bull_z, bear_z=bz
            )
            act = sum(actual.get((pid, wk), 0.0) for wk in remaining)
            rows.append({
                "as_of_week": n, "roster_id": int(r["roster_id"]), "sleeper_player_id": pid,
                "position": r["position"], "bear": band["ros_bear"],
                "bull": band["ros_bull"], "actual": act,
                "security": sec_map.get(pid, "unknown"),
            })
    return rows, freeze


def _coverage(df: pl.DataFrame) -> tuple[float, float, float]:
    """(inside-band rate, below-bear rate, above-bull rate)."""
    n = df.height
    inside = df.filter((pl.col("actual") >= pl.col("bear")) & (pl.col("actual") <= pl.col("bull"))).height
    below = df.filter(pl.col("actual") < pl.col("bear")).height
    above = df.filter(pl.col("actual") > pl.col("bull")).height
    return inside / n, below / n, above / n


def _pool_coverage_evidence(season: int, freeze: int) -> None:
    """Report the PERSISTED band's coverage on its whole projected pool vs the `in_calibrated_pool` subset
    (S1.6). The gated verdict above grades the is_mine league's rostered-freeze players (the population
    BULL_Z was fit on); this evidence grades the entity's ACTUAL population — the whole scoring-scoped pool
    the band is emitted over. It exposes what the gated number cannot: the band, under the UNCHANGED
    BULL_Z=1.44, is well-calibrated on the decision-relevant pool but polluted on the whole pool (deep-bench
    / waiver fodder swing far wider than their projections). This is evidence for the pool restriction, NOT
    a re-tune — BULL_Z stays; re-fitting belongs to the Tuner on the corpus with holdouts."""
    try:
        band = data_layer.read_ros_player_band(season, as_of_week="all")
    except FileNotFoundError:
        print("  [evidence] no persisted ros_player_band — run compute_ros_player_band first")
        return
    if "in_calibrated_pool" not in band.columns:
        print("  [evidence] persisted band predates in_calibrated_pool — recompute to see pool coverage")
        return
    actual = _actual_weekly(season)
    max_proj_week = int(data_layer.read_projection_consensus(season)["week"].max())
    # Grade at the DECISION week (the roster freeze the gated verdict uses), NOT the band's max as-of.
    # Session 2 widened the persisted band to the full projected season, so band.max() is now deep in the
    # year (a ~1-week ROS horizon); grading there would make this evidence incomparable to the verdict.
    # Pinning to `freeze` keeps it a like-for-like companion and byte-stable across the range change.
    fz = band.filter(pl.col("as_of_week") == freeze)
    if not fz.height:
        print(f"  [evidence] persisted band has no as-of week {freeze} slice — skipping pool evidence")
        return
    rows = []
    for r in fz.iter_rows(named=True):
        act = sum(actual.get((r["sleeper_player_id"], wk), 0.0)
                  for wk in range(freeze + 1, max_proj_week + 1))
        rows.append({"bear": r["ros_bear"], "bull": r["ros_bull"], "actual": act,
                     "in_calibrated_pool": r["in_calibrated_pool"]})
    graded = pl.DataFrame(rows)
    whole = _coverage(graded)
    pool_df = graded.filter(pl.col("in_calibrated_pool"))
    pool = _coverage(pool_df)
    comp = dict(fz.filter(pl.col("in_calibrated_pool")).group_by("position").len().sort("position").iter_rows())
    print()
    print(f"  [evidence] persisted-band coverage at freeze week {freeze} (BULL_Z={BULL_Z}, target "
          f"{TARGET_COVERAGE:.2f}):")
    print(f"    whole pool          (n={graded.height}): coverage {whole[0]:.3f}  "
          f"below-bear {whole[1]:.3f}  above-bull {whole[2]:.3f}")
    print(f"    in_calibrated_pool  (n={pool_df.height}): coverage {pool[0]:.3f}  "
          f"below-bear {pool[1]:.3f}  above-bull {pool[2]:.3f}   composition {comp}")
    print(f"    → restricting to the calibrated pool moves coverage {whole[0]:.3f} → {pool[0]:.3f} "
          f"(no BULL_Z change); the whole-pool number is the honest cost of pricing waiver fodder.")


def _canonical_actual(season: int, scoring_key: str, *, reader=data_layer) -> dict:
    """(sleeper_player_id, week) → realised points under `scoring_key`'s CANONICAL profile — the stored
    scoring-scoped answer key (`player_weekly_pts_canonical`), which matches the basis the band was
    projected under (nfl_stats PPR mis-scores half by up to ~7 pts/wk). league_id is null on this series,
    so we filter by scoring_key. Read through `reader` — season-guarded, so a peeking fit raises here too."""
    out = (
        reader.read_outcomes(season, outcome_type="player_weekly_pts_canonical")
        .filter(pl.col("scoring_key") == scoring_key)
        .select("subject_id", pl.col("week").cast(pl.Int64), "value")
    )
    return {(r["subject_id"], r["week"]): float(r["value"]) for r in out.iter_rows(named=True)}


def _materialize(season: int, *, reader=data_layer, league_id=None, scoring_key=None,
                 actual=None, anchor_inputs=None) -> list:
    """The DIAL-INDEPENDENT band ingredients per (as_of_week, player) for one league — everything the band
    needs EXCEPT the swept dials (bull_z/bear_z/anchor_w): the borrowed centre (ros_value), the accumulated
    sigma, the horizon fraction, the preseason anchor floor/ceiling (None if the player has no anchor), and
    the realised ROS over the remaining weeks. Mirrors `_test_points` up to — but not including — the
    dial-dependent `_blended_band`; a joint sweep materializes this ONCE per season then applies each dial
    combo as vectorized arithmetic (`_apply_dials`). Reuses the shipped `_ros_sigma`/`_preseason_anchor`
    (standing instr 5). `scoring_key` is stamped on every row."""
    vor = reader.read_production_vor(season, league_id=league_id, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "position", "ros_value", "n_weeks")
    consensus = reader.read_projection_consensus(season, scoring_key=scoring_key).select(
        "week", "sleeper_player_id", "band_ppr")
    if actual is None:
        actual = _canonical_actual(season, scoring_key, reader=reader)
    adp_map, curve_lookup, curve_max_rank = anchor_inputs if anchor_inputs is not None \
        else _load_anchor_inputs(season)
    max_proj_week = int(consensus["week"].max())
    rows = []
    for n in sorted(vor["as_of_week"].unique().to_list()):
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        sigma_map = {r["sleeper_player_id"]: r["ros_sigma"]
                     for r in _ros_sigma(consensus, remaining).iter_rows(named=True)}
        for r in vor.filter(pl.col("as_of_week") == n).iter_rows(named=True):
            pid = r["sleeper_player_id"]
            remaining_frac = r["n_weeks"] / max_proj_week if max_proj_week else 0.0
            anchor = _preseason_anchor(adp_map.get(pid), curve_lookup, curve_max_rank, remaining_frac)
            rows.append({
                "scoring_key": scoring_key, "as_of_week": n, "sleeper_player_id": pid,
                "position": r["position"], "center": float(r["ros_value"]),
                "sigma": float(sigma_map.get(pid, 0.0)), "remaining_frac": float(remaining_frac),
                "anchor_floor": float(anchor["anchor_floor"]) if anchor else None,
                "anchor_ceiling": float(anchor["anchor_ceiling"]) if anchor else None,
                "actual": float(sum(actual.get((pid, wk), 0.0) for wk in remaining)),
            })
    return rows


def _corpus_ingredients(season: int, *, reader=data_layer) -> pl.DataFrame:
    """Materialize the dial-independent band ingredients pooled across the MATCHED cohort, ALL as-of weeks,
    grouped by scoring_key — the across-as-of-weeks upgrade of the interim GRADE_WEEK grade (Session 8; the
    band already computes every as-of week, so the objective grades them all, not just week 4). Loaded ONCE
    per season; the joint sweep applies each dial combo as vectorized arithmetic. The scoring-scoped
    canonical answer key is read through `reader` FIRST (season-guarded ⇒ a sealed season raises before the
    unguarded anchor read), so the structural split-seal bites for the corpus objective too. DEDUP one row
    per (scoring_key, sleeper_player_id, as_of_week): same-key leagues share the band AND the canonical
    realised, so duplicate rows are pure roster-popularity weight. Raises ValueError if the season has no
    matched leagues / gradeable rows."""
    manifest = data_layer.read_corpus_manifest()  # metadata (no season arg → not a sealed read)
    matched = (
        manifest.filter((pl.col("stratum") == "matched") & (pl.col("season") == season))
        .select("league_id", "scoring_key").unique()
    )
    if matched.height == 0:
        raise ValueError(f"no matched leagues for season {season}")
    actual_by_key = {sk: _canonical_actual(season, sk, reader=reader)
                     for sk in matched["scoring_key"].unique().to_list()}
    anchor_inputs = _load_anchor_inputs(season)  # NFL-global, leave-one-out leak-free; season already cleared
    rows = []
    for lid, sk in matched.iter_rows():
        rows.extend(_materialize(season, reader=reader, league_id=lid, scoring_key=sk,
                                 actual=actual_by_key[sk], anchor_inputs=anchor_inputs))
    if not rows:
        raise ValueError(f"no gradeable corpus rows for season {season}")
    return (pl.DataFrame(rows, infer_schema_length=None)
            .unique(subset=["scoring_key", "sleeper_player_id", "as_of_week"], keep="first"))


def _apply_dials(df: pl.DataFrame, bull_z: float, bear_z: float, anchor_w: float) -> pl.DataFrame:
    """Vectorized bull/bear from the materialized ingredients at the given dials — the polars mirror of the
    shipped `_blended_band` (proven value-equal in check_band_honesty, standing instr 2). w =
    anchor_w·remaining_frac; with an anchor and w>0 the un-floored projection extreme blends toward the
    anchor extreme, else the pure-projection extreme is used; each floored at 0. bull uses bull_z, bear
    uses bear_z (Session 8's down-side half-width)."""
    w = anchor_w * pl.col("remaining_frac")
    proj_bull = pl.col("center") + bull_z * pl.col("sigma")
    proj_bear = pl.col("center") - bear_z * pl.col("sigma")
    has_anchor = pl.col("anchor_ceiling").is_not_null() & (w > 0.0)
    bull = pl.when(has_anchor).then((1.0 - w) * proj_bull + w * pl.col("anchor_ceiling")).otherwise(proj_bull)
    bear = pl.when(has_anchor).then((1.0 - w) * proj_bear + w * pl.col("anchor_floor")).otherwise(proj_bear)
    return df.with_columns(
        pl.max_horizontal(pl.lit(0.0), bull).alias("bull"),
        pl.max_horizontal(pl.lit(0.0), bear).alias("bear"),
    )


def _score_per_key(graded: pl.DataFrame) -> pl.DataFrame:
    """Per scoring_key: coverage / below-bear / above-bull, pooled across ALL as-of weeks. Vectorized (one
    group_by) so a large joint sweep is tractable — the across-season analog of the per-group `_coverage`."""
    return graded.group_by("scoring_key").agg(
        (((pl.col("actual") >= pl.col("bear")) & (pl.col("actual") <= pl.col("bull"))).mean()).alias("cov"),
        ((pl.col("actual") < pl.col("bear")).mean()).alias("below"),
        ((pl.col("actual") > pl.col("bull")).mean()).alias("above"),
    )


def objective(season: int, consts: dict, *, reader=data_layer, ingredients=None) -> float:
    """The tuner's scalar fit objective for BULL_Z / BEAR_Z / ANCHOR_W, at the values in `consts`, on
    `reader`'s allowed partition — LOWER is better. CORPUS-scoped, ACROSS the season's as-of weeks (Session
    8 retired the interim single GRADE_WEEK): pools the matched cohort per scoring_key and returns the mean
    of |coverage−TARGET| + |below-bear − above-bull| (each regime's band should hit 0.80 with balanced
    tails). Pass `ingredients` (from `_corpus_ingredients`) to reuse a once-per-season materialization
    across a joint sweep; else it materializes here. Reuses the shipped band math via `_apply_dials`
    (standing instr 5). Matched leagues exist every season → a real TRAIN 2020–23 window."""
    bull_z = consts.get("BULL_Z", BULL_Z)
    bear_z = consts.get("BEAR_Z", BEAR_Z)
    w = consts.get("ANCHOR_W", ANCHOR_W)
    df = ingredients if ingredients is not None else _corpus_ingredients(season, reader=reader)
    per_key = _score_per_key(_apply_dials(df, bull_z, bear_z, w))
    obj = (pl.col("cov") - TARGET_COVERAGE).abs() + (pl.col("below") - pl.col("above")).abs()
    return float(per_key.select(obj.mean()).item())


def _is_calibrated(df: pl.DataFrame, consts: dict) -> bool:
    """The band's own read-gate PASS criterion on the corpus, matching the shipped `run()` standard: mean
    |coverage − TARGET| across scoring keys within COVERAGE_TOL."""
    per_key = _score_per_key(_apply_dials(
        df, consts.get("BULL_Z", BULL_Z), consts.get("BEAR_Z", BEAR_Z), consts.get("ANCHOR_W", ANCHOR_W)))
    return bool(per_key.select((pl.col("cov") - TARGET_COVERAGE).abs().mean()).item() <= COVERAGE_TOL)


def coupled_ok(season: int, proposed: dict, current: dict, *, reader=data_layer, ingredients=None) -> bool:
    """The band's OWN read-gate coupled guardrail, made REAL on the held-out corpus (Session 8) — a
    NO-REGRESSION check (6b returned None because the shipped is_mine `run()` has no DEV spine). Band width
    is decoupled from the centre reads by construction (production_vor / true_rank / bracket_odds consume the
    centre, not the band bounds), so the band's OWN calibration is the only gate that could move; a
    regression is current-PASSES → proposed-FAILS. Returns False ONLY in that case. The current
    under-covering band already FAILS the calibration bar on the holdout corpus, so a proposed combo that
    (much) better-covers is not a regression — the honest, evaluable answer 6b left as None."""
    df = ingredients if ingredients is not None else _corpus_ingredients(season, reader=reader)
    if _is_calibrated(df, proposed):
        return True
    return not _is_calibrated(df, current)   # no regression unless we broke a currently-passing gate


def run(season: int, bull_z: float = BULL_Z, anchor_w: float = ANCHOR_W, bear_z: float = BEAR_Z) -> bool:
    rows, freeze = _test_points(season, bull_z, anchor_w, bear_z=bear_z)
    tp = pl.DataFrame(rows)
    fz = tp.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS Player Band backtest: season={season}  test points={tp.height} "
          f"(player × as-of week; freeze week={freeze}, n={fz.height})  "
          f"BULL_Z={bull_z}  BEAR_Z={bear_z}  ANCHOR_W={anchor_w} ===")

    # 1. Calibration — freeze-week coverage near TARGET, tails reported (symmetric band, no ROS skew term).
    cov, below, above = _coverage(fz)
    cov_pool, _, _ = _coverage(tp)
    calibrated = abs(cov - TARGET_COVERAGE) <= COVERAGE_TOL
    print()
    print(f"  calibration (freeze week {freeze}; target {TARGET_COVERAGE:.2f} ± {COVERAGE_TOL:.2f}):")
    print(f"    actual ROS in [bear, bull] = {cov:.3f}  {'PASS' if calibrated else 'FAIL'}")
    print(f"    tails: below-bear {below:.3f} / above-bull {above:.3f}  (symmetric band — evidence, not gated)")
    print(f"    [evidence] pooled coverage over weeks 1..{freeze} (n={tp.height}, nested/non-indep) = {cov_pool:.3f}")

    # Anchor effect (evidence): the §2 preseason anchor's mark on the freeze-week band vs the
    # pre-anchor pure-projection band at the SAME bull_z (isolates what the anchor changed, not the width).
    pre_rows, _ = _test_points(season, bull_z, 0.0, bear_z=bear_z)
    pre = pl.DataFrame(pre_rows).filter(pl.col("as_of_week") == freeze)
    pcov, pbelow, pabove = _coverage(pre)
    print()
    print(f"  [evidence] preseason-anchor effect at freeze (bull_z={bull_z}):")
    print(f"    pre-anchor  (ANCHOR_W=0.00): coverage {pcov:.3f}  below-bear {pbelow:.3f}  above-bull {pabove:.3f}")
    print(f"    anchored    (ANCHOR_W={anchor_w:.2f}): coverage {cov:.3f}  below-bear {below:.3f}  above-bull {above:.3f}")

    # 1b. Anchor-consumption gate (Session 1.7 fold-in — the missing tooth). The §2 preseason anchor must be
    #     CONSUMED, not silently disabled. A dropped / mis-pathed per-holdout curve makes `_load_anchor_inputs`
    #     return empty maps → every band degrades to the pure-projection read → anchored coverage collapses
    #     onto the pre-anchor number, and NOTHING here noticed (Session 2's gate only proved the curve FILES
    #     exist, never that the band consumes them). Assert the anchor (a) has present inputs reaching N>0
    #     freeze players AND (b) actually MOVES freeze coverage (anchored ≠ pre-anchor). A silent-disable —
    #     which historically read as a clean PASS at the disabled 0.744 — now FAILS.
    adp_map, curve_lookup, _ = _load_anchor_inputs(season)
    anchored_n = fz.filter(pl.col("sleeper_player_id").is_in(list(adp_map))).height if adp_map else 0
    anchor_moves = abs(cov - pcov) > 1e-9
    anchor_live = bool(curve_lookup) and anchored_n > 0 and anchor_moves
    print()
    print(f"  anchor-consumption (§2 anchor must be live, not silently disabled):")
    print(f"    curve present={bool(curve_lookup)}  anchored freeze players={anchored_n} (N>0 required)  "
          f"anchored≠pre-anchor={anchor_moves} (Δcov={cov - pcov:+.3f})   {'PASS' if anchor_live else 'FAIL'}")

    # 2. Decision-relevant — terciles by ros_bull, actual ROS rises monotonically (dead < mid < stud).
    g = fz.sort("bull", descending=False)
    third = g.height // 3
    dead = mean(g.head(third)["actual"].to_list())
    stud = mean(g.tail(third)["actual"].to_list())
    mid = mean(g.slice(third, g.height - 2 * third)["actual"].to_list())
    monotonic = dead < mid < stud
    print()
    print(f"  decision-relevant: mean ACTUAL ROS by ros_bull tercile (expect dead < mid < stud)")
    print(f"    dead {dead:.1f}  <  mid {mid:.1f}  <  stud {stud:.1f}   {'PASS' if monotonic else 'FAIL'}")

    # Evidence (not gated): does the situation axis carry signal — do non-stable players miss LOW more?
    def _miss_low(df):
        return df.filter(pl.col("actual") < pl.col("bear")).height / df.height if df.height else float("nan")
    stable = fz.filter(pl.col("security") == "stable")
    shaky = fz.filter(pl.col("security") != "stable")
    print()
    print(f"  [evidence] below-bear (bear-case broke) rate by security tier:")
    print(f"    stable {_miss_low(stable):.3f} (n={stable.height})   non-stable {_miss_low(shaky):.3f} (n={shaky.height})")

    # Whole-pool vs calibrated-pool coverage on the PERSISTED band (S1.6) — evidence, not gated.
    # Graded at the same decision (freeze) week as the verdict, not the band's full-season max as-of.
    _pool_coverage_evidence(season, freeze)

    ok = calibrated and monotonic and anchor_live
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — bull/bear band {'is' if calibrated else 'is NOT'} "
          f"calibrated at the freeze (coverage {cov:.3f} vs target {TARGET_COVERAGE:.2f}); "
          f"ros_bull {'ranks' if monotonic else 'does NOT rank'} realised ROS (dead<mid<stud); "
          f"§2 anchor {'LIVE' if anchor_live else 'SILENTLY DISABLED'}.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest ROS Outcome Shape against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    # The BULL_Z × ANCHOR_W sweep is retired into the split-aware harness:
    #   python3 -m application.data.corpus.tuner
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
