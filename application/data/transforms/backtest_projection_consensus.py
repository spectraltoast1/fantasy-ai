"""
Backtest the weekly projection spread band against the full-2025 answer key.

The gate the Phase-2 spread must clear (DECISION_READS.md §3, "Validate by calibration"):
over a season, does the actual score land inside the 25–75 band **~50%** of the time? A
band that covers ~50% is honestly sized; one that covers 80% is uselessly wide, one that
covers 20% is falsely confident. This is the law-2 confidence signal, so its width has to
be earned against reality, not assumed.

It imports the SAME pure `_projection_band` (and `_consensus_frame`/`_residuals`) the
production transform ships — what's validated here is exactly what serves the front end,
no parallel re-derivation that could drift.

Method (no peeking — each week's band uses only weeks strictly before it):
  - For every (player, week W) that was both projected (a center exists) and played (an
    actual exists), build the band from that player's residuals over weeks < W (expanding,
    out-of-sample), then test: did the actual land in [p25, p75]?
  - Coverage = fraction of those test points inside the band. Target = 0.50.
  - `--sweep` tunes BAND_Z (the p25/p75 half-width multiplier) to bring coverage to 0.50 —
    residuals are non-normal, so the empirical multiplier is tuned on the answer key, not
    assumed from the normal 0.6745. The winner sets BAND_Z in the transform.

Verdict (exit 0 iff calibrated). Also reported as evidence: the same band with NO
per-player shrink (position-only prior for everyone), and coverage split by player
volatility — the per-player width earns its keep by keeping steady and volatile players
both near 50%, where a one-size band over-covers the steady and under-covers the volatile.

Usage:
    python backtest_projection_consensus.py --season 2025
    python backtest_projection_consensus.py --season 2025 --sweep
"""

import argparse
import sys
from pathlib import Path

import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))
sys.path.insert(0, str(_TRANSFORMS_DIR))
import data_layer
from compute_projection_consensus import (
    BAND_Z,
    SHRINK_K,
    _consensus_frame,
    _projection_band,
    _residuals,
)

# Calibration tolerance: coverage of the 25–75 band must land within this of 0.50.
COVERAGE_TOL = 0.03
# BAND_Z candidates swept against the answer key. 0.6745 is the normal-theory IQR
# half-width; residuals are fatter-tailed, so the empirical best usually sits above it.
BAND_Z_GRID = [0.5, 0.55, 0.6, 0.6745, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0, 1.1, 1.25, 1.4]
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
    return matched, resid_by_player, pos_prior, global_prior


def _coverage_frame(matched, resid_by_player, pos_prior, global_prior, band_z, *, player_shrink):
    """One row per test point (player, week) with the band and whether the actual landed
    inside it. `player_shrink=False` → the naive position-only band (empty history for all),
    the same pure function with no per-player residuals."""
    rows = []
    for r in matched.iter_rows(named=True):
        pid, wk = r["sleeper_player_id"], int(r["week"])
        hist = [rd for (w, rd) in resid_by_player.get(pid, []) if w < wk] if player_shrink else []
        pos_std = pos_prior.get(r["position"], global_prior)
        b = _projection_band(r["center_ppr"], hist, pos_std, shrink_k=SHRINK_K, band_z=band_z)
        rows.append({
            "sleeper_player_id": pid, "week": wk, "position": r["position"],
            "actual": r["actual_ppr"], "band_ppr": b["band_ppr"], "n_resid": b["n_resid"],
            "hit": b["p25_ppr"] <= r["actual_ppr"] <= b["p75_ppr"],
        })
    return pl.DataFrame(rows)


def _cov(df) -> float:
    return float(df["hit"].mean())


def _best_z(matched, rbp, pos_prior, gp, *, player_shrink):
    """The BAND_Z on the grid whose coverage is closest to 0.50, for one band mode."""
    best = (None, 0.0, 1.0)  # (z, coverage, |coverage-0.5|)
    for z in BAND_Z_GRID:
        cov = _cov(_coverage_frame(matched, rbp, pos_prior, gp, z, player_shrink=player_shrink))
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
    matched, rbp, pos_prior, gp = _prep(season)
    print(f"=== BAND_Z sweep (per-player band): season={season}  test points={matched.height} ===")
    print(f"  {'band_z':<10}{'coverage':>10}   (target 0.500)")
    best = (None, 1.0)
    for z in BAND_Z_GRID:
        cov = _cov(_coverage_frame(matched, rbp, pos_prior, gp, z, player_shrink=True))
        flag = " ←best" if abs(cov - 0.5) < abs(best[1] - 0.5) else ""
        if abs(cov - 0.5) < abs(best[1] - 0.5):
            best = (z, cov)
        print(f"  {z:<10}{cov:>10.3f}{flag}")
    print(f"  → best BAND_Z at this answer key: {best[0]} (coverage {best[1]:.3f}) — bake into compute_projection_consensus.py")


def run(season: int, band_z=BAND_Z) -> bool:
    matched, rbp, pos_prior, gp = _prep(season)
    strata = _strata(matched)

    pp = _coverage_frame(matched, rbp, pos_prior, gp, band_z, player_shrink=True)
    z_naive, _ = _best_z(matched, rbp, pos_prior, gp, player_shrink=False)
    nv = _coverage_frame(matched, rbp, pos_prior, gp, z_naive, player_shrink=False)

    cov_pp, cov_nv = _cov(pp), _cov(nv)
    print(f"=== Projection-spread calibration: season={season}  test points={matched.height} "
          f"(BAND_Z={band_z}) ===")
    print(f"  positional residual std (band prior): "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_prior.items())))
    print()
    print(f"  {'band':<26}{'band_z':>8}{'25–75 coverage':>16}   (target 0.500)")
    print(f"  {'per-player (shipped)':<26}{band_z:>8}{cov_pp:>16.3f}")
    print(f"  {'naive (position-only)':<26}{z_naive:>8}{cov_nv:>16.3f}")

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

    calibrated = abs(cov_pp - 0.5) <= COVERAGE_TOL
    more_uniform = sp_pp is not None and sp_nv is not None and sp_pp <= sp_nv
    print()
    print(f"  VERDICT: calibration {'PASS' if calibrated else 'FAIL'} "
          f"(per-player 25–75 coverage {cov_pp:.3f} within {COVERAGE_TOL:.2f} of 0.50); "
          f"per-player width {'more' if more_uniform else 'NOT more'} uniform across "
          f"volatility strata than naive ({sp_pp:.3f} vs {sp_nv:.3f}).")
    return calibrated


def __main():
    parser = argparse.ArgumentParser(description="Backtest the projection spread band's calibration.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--sweep", action="store_true",
                        help="sweep BAND_Z against the answer key instead of running the verdict")
    args = parser.parse_args()
    if args.sweep:
        sweep(args.season)
        sys.exit(0)
    ok = run(args.season)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    __main()
