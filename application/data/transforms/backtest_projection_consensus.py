"""
Backtest the weekly projection spread band against the full-2025 answer key.

The gate the Phase-2 spread must clear (DECISION_READS.md §3, "Validate by calibration"):
over a season, does the actual score land inside the 25–75 band **~50%** of the time, with
each tail (below p25 / above p75) near **25%**? Combined coverage of ~50% is honestly sized;
80% is uselessly wide, 20% falsely confident. The per-tail split is what the **skew term**
(§3 component 3) is graded on — a symmetric band can hit 50% overall while systematically
missing low on one side (2025: 0.278 below vs 0.208 above), and the skew fixes that. This is
the law-2 confidence signal, so both width and skew are earned against reality, not assumed.

It imports the SAME pure `_projection_band` (and `_consensus_frame`/`_residuals`) the
production transform ships — what's validated here is exactly what serves the front end,
no parallel re-derivation that could drift.

Method (no peeking — each week's band uses only weeks strictly before it):
  - For every (player, week W) that was both projected (a center exists) and played (an
    actual exists), build the band from that player's residuals over weeks < W (expanding,
    out-of-sample), then test: did the actual land in [p25, p75]?
  - Coverage = fraction inside the band (target 0.50); the two tail rates target 0.25 each.
  - `--sweep` jointly tunes BAND_Z (p25/p75 half-width) and SKEW_GAIN (the Cornish-Fisher
    skew-shift multiplier) to land combined coverage at 0.50 AND both tails at 0.25 —
    residuals are non-normal and right-skewed, so both are tuned on the answer key, not
    assumed. The winning pair sets BAND_Z + SKEW_GAIN in the transform.

Verdict (exit 0 iff: combined coverage within COVERAGE_TOL of 0.50, both tails within
TAIL_TOL of 0.25, AND the skew term improves tail balance vs a re-tuned symmetric band).
Also reported as evidence: the position-only (no per-player shrink) band, and coverage
split by player volatility — the per-player width earns its keep by keeping steady and
volatile players both near 50%, where a one-size band over-covers the steady and
under-covers the volatile.

Usage:
    python3 -m application.data.transforms.backtest_projection_consensus --season 2025
    python3 -m application.data.transforms.backtest_projection_consensus --season 2025 --sweep
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import skewness
from application.data.transforms.compute_projection_consensus import (
    BAND_Z,
    SHRINK_K,
    SKEW_GAIN,
    SKEW_SHRINK_K,
    _consensus_frame,
    _projection_band,
    _residuals,
)

# Calibration tolerance: coverage of the 25–75 band must land within this of 0.50.
COVERAGE_TOL = 0.03
# Per-tail tolerance: the below-p25 and above-p75 rates must each land within this of 0.25.
# The skew term earns its keep by balancing the tails, not just the combined middle.
TAIL_TOL = 0.03
# BAND_Z candidates swept against the answer key. 0.6745 is the normal-theory IQR
# half-width; residuals are fatter-tailed, so the empirical best usually sits above it.
BAND_Z_GRID = [0.5, 0.55, 0.6, 0.6745, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0, 1.1, 1.25, 1.4]
# SKEW_GAIN candidates swept jointly with BAND_Z. 0.0 = the old symmetric band; 1.0 = pure
# Cornish-Fisher; > 1 sharpens the tail balance if the answer key wants it.
SKEW_GAIN_GRID = [0.0, 0.5, 1.0, 1.5, 2.0]
# A player needs this many played+projected weeks to estimate his volatility for the
# steady-vs-volatile calibration split (evidence, not the gate).
MIN_STRATA_GAMES = 4


def _prep(season: int):
    """Consensus centers ⋈ actuals → the matched (player, week, center, actual, resid)
    frame, plus the per-player residual index and the positional-prior residual std — the
    exact inputs the transform's band is built from."""
    proj = data_layer.read_projections(season)
    actual = (
        data_layer.read_nfl_stats(season)
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual_ppr"))
    )
    matched = _residuals(_consensus_frame(proj), actual)

    resid_by_player: dict = {}
    for r in matched.select("sleeper_player_id", "week", "resid").sort("sleeper_player_id", "week").iter_rows(named=True):
        resid_by_player.setdefault(r["sleeper_player_id"], []).append((int(r["week"]), float(r["resid"])))

    pos_prior = {
        r["position"]: float(r["s"])
        for r in matched.group_by("position").agg(pl.col("resid").std(ddof=0).alias("s")).iter_rows(named=True)
        if r["s"] is not None
    }
    global_prior = float(matched["resid"].std(ddof=0))

    # Positional residual-skew prior — the exact prior the transform's skew term shrinks
    # toward (skewness() is the same shared helper the transform uses).
    resid_by_pos: dict = {}
    for r in matched.select("position", "resid").iter_rows(named=True):
        resid_by_pos.setdefault(r["position"], []).append(float(r["resid"]))
    pos_skew_prior = {p: skewness(v) for p, v in resid_by_pos.items()}
    global_skew_prior = skewness([r for v in resid_by_pos.values() for r in v])
    return matched, resid_by_player, pos_prior, global_prior, pos_skew_prior, global_skew_prior


def _coverage_frame(matched, resid_by_player, pos_prior, global_prior,
                    pos_skew_prior, global_skew_prior, band_z, skew_gain, *, player_shrink):
    """One row per test point (player, week): the band, whether the actual landed inside it,
    and which tail it missed into. `player_shrink=False` → the naive position-only band
    (empty history for all), the same pure function with no per-player residuals."""
    rows = []
    for r in matched.iter_rows(named=True):
        pid, wk = r["sleeper_player_id"], int(r["week"])
        hist = [rd for (w, rd) in resid_by_player.get(pid, []) if w < wk] if player_shrink else []
        pos_std = pos_prior.get(r["position"], global_prior)
        pos_skew = pos_skew_prior.get(r["position"], global_skew_prior)
        b = _projection_band(r["center_ppr"], hist, pos_std, pos_skew,
                             shrink_k=SHRINK_K, band_z=band_z,
                             skew_shrink_k=SKEW_SHRINK_K, skew_gain=skew_gain)
        a = r["actual_ppr"]
        rows.append({
            "sleeper_player_id": pid, "week": wk, "position": r["position"],
            "actual": a, "band_ppr": b["band_ppr"], "n_resid": b["n_resid"],
            "hit": b["p25_ppr"] <= a <= b["p75_ppr"],
            "below": a < b["p25_ppr"], "above": a > b["p75_ppr"],
        })
    return pl.DataFrame(rows)


def _cov(df) -> float:
    return float(df["hit"].mean())


def _tails(df) -> tuple[float, float]:
    """(below-p25 rate, above-p75 rate) — each should sit near 0.25 for an honest band."""
    return float(df["below"].mean()), float(df["above"].mean())


def _best_z(prep, skew_gain, *, player_shrink):
    """The BAND_Z on the grid whose coverage is closest to 0.50, at a fixed skew_gain."""
    matched, rbp, pos_prior, gp, pos_skew, gsk = prep
    best = (None, 0.0, 1.0)  # (z, coverage, |coverage-0.5|)
    for z in BAND_Z_GRID:
        cov = _cov(_coverage_frame(matched, rbp, pos_prior, gp, pos_skew, gsk, z, skew_gain,
                                   player_shrink=player_shrink))
        if abs(cov - 0.5) < best[2]:
            best = (z, cov, abs(cov - 0.5))
    return best[0], best[1]


def _strata(matched):
    """Player id → 'steady' | 'volatile' by whether his actual weekly PPR std is below or
    above the median, over players with a real sample. The band's job is to be wide for the
    volatile and tight for the steady, so calibration should hold in both."""
    vol = (
        matched.group_by("sleeper_player_id")
        .agg(pl.len().alias("g"), pl.col("actual_ppr").std(ddof=0).alias("vol"))
        .filter((pl.col("g") >= MIN_STRATA_GAMES) & pl.col("vol").is_not_null())
    )
    if vol.height == 0:
        return {}
    med = float(vol["vol"].median())
    return {r["sleeper_player_id"]: ("volatile" if r["vol"] > med else "steady") for r in vol.iter_rows(named=True)}


def sweep(season: int) -> None:
    """Joint (BAND_Z × SKEW_GAIN) sweep: pick the pair that lands the combined 25–75
    coverage near 0.50 AND both tails near 0.25 — the skew term only earns its keep if it
    balances the tails, so the winner minimises combined |coverage−0.5| + the two tail errors."""
    prep = _prep(season)
    matched, rbp, pos_prior, gp, pos_skew, gsk = prep
    print(f"=== BAND_Z × SKEW_GAIN sweep (per-player band): season={season}  test points={matched.height} ===")
    print(f"  {'band_z':>8}{'skew_gain':>11}{'coverage':>10}{'below-p25':>11}{'above-p75':>11}{'score':>8}")
    best = (None, None, 9.9)  # (band_z, skew_gain, score)
    for gain in SKEW_GAIN_GRID:
        for z in BAND_Z_GRID:
            cf = _coverage_frame(matched, rbp, pos_prior, gp, pos_skew, gsk, z, gain, player_shrink=True)
            cov = _cov(cf)
            below, above = _tails(cf)
            score = abs(cov - 0.5) + abs(below - 0.25) + abs(above - 0.25)
            if score < best[2]:
                best = (z, gain, score)
            flag = " ←best" if (z, gain) == (best[0], best[1]) else ""
            print(f"  {z:>8}{gain:>11}{cov:>10.3f}{below:>11.3f}{above:>11.3f}{score:>8.3f}{flag}")
    print(f"  → best (BAND_Z, SKEW_GAIN) at this answer key: ({best[0]}, {best[1]}) "
          f"— bake into compute_projection_consensus.py")


def run(season: int, band_z=BAND_Z, skew_gain=SKEW_GAIN) -> bool:
    prep = _prep(season)
    matched, rbp, pos_prior, gp, pos_skew, gsk = prep
    strata = _strata(matched)

    pp = _coverage_frame(matched, rbp, pos_prior, gp, pos_skew, gsk, band_z, skew_gain, player_shrink=True)
    # The symmetric (no-skew) per-player band, re-tuned on BAND_Z alone, is the baseline the
    # skew term must beat on tail balance — same width machinery, skew_gain forced to 0.
    z_sym, _ = _best_z(prep, 0.0, player_shrink=True)
    sym = _coverage_frame(matched, rbp, pos_prior, gp, pos_skew, gsk, z_sym, 0.0, player_shrink=True)
    z_naive, _ = _best_z(prep, 0.0, player_shrink=False)
    nv = _coverage_frame(matched, rbp, pos_prior, gp, pos_skew, gsk, z_naive, 0.0, player_shrink=False)

    cov_pp, cov_sym, cov_nv = _cov(pp), _cov(sym), _cov(nv)
    (bl_pp, ab_pp), (bl_sym, ab_sym) = _tails(pp), _tails(sym)
    print(f"=== Projection-spread calibration: season={season}  test points={matched.height} "
          f"(BAND_Z={band_z}, SKEW_GAIN={skew_gain}) ===")
    print(f"  positional residual std (band prior):  "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_prior.items())))
    print(f"  positional residual skew (skew prior): "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_skew.items()) if s is not None))
    print()
    print(f"  {'band':<28}{'25–75 cov':>11}{'below-p25':>11}{'above-p75':>11}   (targets 0.500 / 0.250 / 0.250)")
    print(f"  {'per-player + skew (shipped)':<28}{cov_pp:>11.3f}{bl_pp:>11.3f}{ab_pp:>11.3f}")
    print(f"  {'per-player, symmetric':<28}{cov_sym:>11.3f}{bl_sym:>11.3f}{ab_sym:>11.3f}")
    print(f"  {'naive (position-only)':<28}{cov_nv:>11.3f}{'':>11}{'':>11}")

    # Calibration by volatility stratum — the per-player width should keep both near 0.50.
    def _stratum_spread(df):
        d = df.with_columns(
            pl.col("sleeper_player_id").replace_strict(strata, default=None).alias("stratum")
        ).filter(pl.col("stratum").is_not_null())
        cov = {s: _cov(g) for (s,), g in d.group_by("stratum")}
        st, vo = cov.get("steady"), cov.get("volatile")
        return st, vo, (abs(st - vo) if st is not None and vo is not None else None)

    st_pp, vo_pp, sp_pp = _stratum_spread(pp)
    st_nv, vo_nv, sp_nv = _stratum_spread(nv)
    print()
    print(f"  coverage by player volatility (steady / volatile — closer-together = better calibrated):")
    print(f"    per-player  steady {st_pp:.3f}  volatile {vo_pp:.3f}  (spread {sp_pp:.3f})")
    print(f"    naive       steady {st_nv:.3f}  volatile {vo_nv:.3f}  (spread {sp_nv:.3f})")

    # Gate: (1) combined 25–75 coverage near 0.50, (2) BOTH tails near 0.25 (the skew term's
    # job), and (3) the skew term must not worsen tail balance vs the re-tuned symmetric band.
    calibrated = abs(cov_pp - 0.5) <= COVERAGE_TOL
    tails_ok = abs(bl_pp - 0.25) <= TAIL_TOL and abs(ab_pp - 0.25) <= TAIL_TOL
    tail_err_pp = abs(bl_pp - 0.25) + abs(ab_pp - 0.25)
    tail_err_sym = abs(bl_sym - 0.25) + abs(ab_sym - 0.25)
    skew_helps = tail_err_pp <= tail_err_sym
    more_uniform = sp_pp is not None and sp_nv is not None and sp_pp <= sp_nv
    ok = calibrated and tails_ok and skew_helps
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — "
          f"combined coverage {cov_pp:.3f} {'within' if calibrated else 'OUTSIDE'} {COVERAGE_TOL:.2f} of 0.50; "
          f"tails ({bl_pp:.3f}/{ab_pp:.3f}) {'within' if tails_ok else 'OUTSIDE'} {TAIL_TOL:.2f} of 0.25; "
          f"skew {'improves' if skew_helps else 'WORSENS'} tail balance vs symmetric "
          f"({tail_err_pp:.3f} vs {tail_err_sym:.3f}).")
    print(f"  (evidence: per-player width {'more' if more_uniform else 'NOT more'} uniform across "
          f"volatility strata than naive — {sp_pp:.3f} vs {sp_nv:.3f}.)")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest the projection spread band's calibration.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--sweep", action="store_true",
                        help="sweep BAND_Z × SKEW_GAIN against the answer key instead of running the verdict")
    args = parser.parse_args()
    if args.sweep:
        sweep(args.season)
        sys.exit(0)
    ok = run(args.season)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    __main()
