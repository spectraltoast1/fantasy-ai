"""
Compute the weekly projection consensus + spread band (DECISION_READS.md §3).

Phase 2's forward prior: a percentile band around a *borrowed* weekly projection — e.g.
projected 10 → 6 (25th) / 10 (50th) / 17 (75th). Per design law 3 we borrow the center
and build only the band; per law 2 the band width *is* the confidence signal (tight =
act, wide = coin-flip).

Per (week, player) over the whole skill pool it derives:
  - center_ppr: the consensus center = median proj_pts_ppr across sources (today one
    source, Sleeper/RotoWire ⇒ its value). n_sources carried as evidence.
  - band_ppr: the spread width = the player's residual std (actual − projection) over his
    weeks *strictly before* this one, shrunk toward the position's residual std (computed
    over the full NFL pool — the borrowed substrate) by SHRINK_K games of prior. Thin
    early-season samples lean on the positional prior; the estimate sharpens as his own
    history accrues. `stdev(actual − proj)`, not raw score variance: the center already
    absorbs the mean, so residual spread is what makes the ~50%-in-IQR calibration mean
    something (a sharper reading of §3's "historical weekly variance").
  - p25_ppr / p50_ppr / p75_ppr: the percentile band. p50 = the borrowed center (law 3).
    p25/p75 = center + band·(∓BAND_Z + shift), floored at 0, where `shift` is a
    skewness-driven Cornish-Fisher quantile adjustment (§3 component 3, the skew term).
    The shift = SKEW_GAIN·(g/6)·(BAND_Z²−1) with `g` the player's **residual skewness**
    shrunk toward a full-pool positional prior (same shrink idiom as the width, one moment
    up). Because BAND_Z < 1, a right-skewed residual (g > 0 — the universal case: boom weeks
    are the long tail) drives `shift` **negative**, moving both breakpoints down: the
    borrowed center sits *above* the realized median (projections lean mildly optimistic),
    so honest 25/25 tails need the band shifted under the center, giving a slightly longer
    lower gap. Tuned + validated per-tail on the 2025 answer key — see the note below and
    backtest_projection_consensus.py.
  - skew_ppr: the shrunk residual skewness `g` used for the shift (evidence; null when the
    positional prior itself is null, which won't happen for skill positions).
  - Empirical footnote (worth recording): the *archetype-from-opportunity* driver §3
    literally names (TD-dependence: share of projected points from TDs) was measured against
    the 2025 answer key and **did not track** residual skew (high-TD players skew 0.64, low-TD
    0.89 — backwards and negligible), while the per-player residual third moment shrunk to the
    positional prior does. So the skew is driven by measured residual skewness (the realized
    boom/bust), not the projection's component mix — honest to the calibration (law 2), and the
    exact parallel to how the width uses the residual second moment.
  - disagreement_ppr: cross-source spread (std across sources) — NULL until a 2nd source
    lands (ffanalytics in-season). Present now so the additive source is a value change,
    not a schema change (the entity is source-agnostic by design).

Not tall over as_of_week (unlike the other derived analytics): a projection for week W is
a fixed forward statement, and its band uses only weeks < W, so the as-of information is
baked into the projected week. Keyed on `week`, like the projections entity it reads.

Scoring is **league-driven** via the scoring dispatcher (_scoring.py): the league's
scoring_settings pick both the projection column (center + disagreement) and the nfl_stats
actual column (residuals). Standard PPR/half/std leagues select the matching canned columns;
custom scoring routes to the recompute engine (not built — its selectors raise). For this full-PPR
league profile=ppr → proj_pts_ppr + fantasy_points_ppr (unchanged output). Output columns keep the
*_ppr suffix (they now hold league points — a documented naming wart, rename deferred to the
any-league project).

Output: snapshots/derived/projection_consensus_{season}.parquet, one row per (week, player).

Usage:
    python compute_projection_consensus.py --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))  # application/data → data_layer
sys.path.insert(0, str(_TRANSFORMS_DIR))          # transforms → _analytics
import data_layer
from _analytics import round1, skewness, stdev
from _scoring import scoring_profile, projection_points_expr, actual_points_expr

# Variance-shrink weight, in "games of prior": the player's residual variance is pooled
# with the positional prior as (n·player_var + K·pos_var)/(n + K). Mirrors
# compute_player_signal.py's SHRINK_K idiom (there for a rate, here for a variance). At
# the week-4 freeze a player has ≤ 3 residuals, so K = 4 gives the prior a shade over
# half the weight — honest for thin samples, tilting to his own history as it accrues.
SHRINK_K = 4
# Band half-width multiplier on the residual std: p25/p75 = center + band·(∓BAND_Z + shift).
# The normal-theory value for the 25th/75th percentiles is 0.6745·σ; residuals are non-normal
# (peaked in the middle with fat boom/bust tails that inflate σ), so the empirical
# multiplier that lands IQR coverage at ~50% is tuned on the 2025 answer key
# (backtest_projection_consensus.py --sweep) and baked here — tested, not guessed. The
# 2025 sweep chose 0.55 once the skew term (below) shares the calibration load. Re-tune
# in-season — width and skew are swept jointly.
BAND_Z = 0.55
# Skew-shrink weight, in "games of prior": the player's residual *skewness* (third moment)
# is pooled with the positional-skew prior as (n·g_player + K·g_pos)/(n + K). Larger than
# SHRINK_K because a third moment is noisier than a variance, so it leans on the prior
# longer — early season the skew is essentially the position's.
SKEW_SHRINK_K = 8
# Multiplier on the Cornish-Fisher skewness term: shift = SKEW_GAIN·(g/6)·(BAND_Z²−1). Pure
# Cornish-Fisher is gain 1.0; the 2025 answer-key sweep chose 1.5 (both tails within ~0.006
# of the 0.25 target). Tuned, not assumed — same discipline as BAND_Z.
SKEW_GAIN = 1.5


def _consensus(proj_ppr) -> dict:
    """Consensus center + source count from one player-week's per-source projections.

    `proj_ppr`: the list of proj_pts_ppr values, one per source. Center = median (robust
    to an outlier source); n_sources = how many projected him. Pure — no I/O, no globals.
    """
    vals = [v for v in proj_ppr if v is not None]
    n = len(vals)
    center = sorted(vals)[n // 2] if n % 2 else (sorted(vals)[n // 2 - 1] + sorted(vals)[n // 2]) / 2 if n else None
    return {"center_ppr": center, "n_sources": n}


def _projection_band(center, resid_history, pos_resid_std, pos_resid_skew, *,
                     shrink_k, band_z, skew_shrink_k, skew_gain) -> dict:
    """Percentile band around a borrowed projection center for one player-week.

    `center`: the consensus projection (becomes p50). `resid_history`: the player's
    realized (actual − projection) residuals over weeks strictly before this one
    (out-of-sample). `pos_resid_std` / `pos_resid_skew`: the position's residual std and
    skewness over the full pool — the priors the thin per-player estimates shrink toward.
    Constants injected (not module globals) so the backtest exercises this exact function.

    Band width = residual std shrunk toward the positional prior by `shrink_k` games:
    shrunk_var = (n·player_var + K·pos_var)/(n + K); band = √shrunk_var. With < 2
    residuals the player estimate is undefined → the band is the positional prior (a wide,
    honest default).

    Skew = residual skewness (one moment up) shrunk toward the positional-skew prior by
    `skew_shrink_k` games; < 3 residuals → the positional prior. It feeds a Cornish-Fisher
    quantile shift = skew_gain·(g/6)·(band_z²−1), the same additive term on both breakpoints:
      p25/p75 = center + band·(∓band_z + shift), p50 = center (borrowed, unshifted).
    Because band_z < 1, a right-skewed residual (g > 0) makes shift < 0 → both breakpoints
    move down under the center (the borrowed center sits above the realized median), giving
    honest 25/25 tails with a slightly longer lower gap. Floored at 0 (points can't go
    negative).
    """
    n = len(resid_history)
    player_std = stdev(resid_history)  # None when < 2 residuals
    band = pos_resid_std if player_std is None else (
        (n * player_std ** 2 + shrink_k * pos_resid_std ** 2) / (n + shrink_k)
    ) ** 0.5

    player_skew = skewness(resid_history)  # None when < 3 residuals
    skew = pos_resid_skew if player_skew is None else (
        (n * player_skew + skew_shrink_k * pos_resid_skew) / (n + skew_shrink_k)
    )
    shift = skew_gain * (skew / 6.0) * (band_z ** 2 - 1) if skew is not None else 0.0

    return {
        "center_ppr": round1(center),
        "p25_ppr": round1(max(0.0, center + band * (-band_z + shift))),
        "p50_ppr": round1(center),
        "p75_ppr": round1(center + band * (band_z + shift)),
        "band_ppr": round(band, 3),
        "skew_ppr": round(skew, 3) if skew is not None else None,
        "resid_std_raw": round(player_std, 3) if player_std is not None else None,
        "resid_std_pos": round(pos_resid_std, 3),
        "resid_skew_raw": round(player_skew, 3) if player_skew is not None else None,
        "resid_skew_pos": round(pos_resid_skew, 3) if pos_resid_skew is not None else None,
        "n_resid": n,
    }


def _consensus_frame(proj: pl.DataFrame, proj_col: str = "proj_pts_ppr") -> pl.DataFrame:
    """Collapse the multi-source projections to one consensus row per (week, player):
    median center, source count, and the cross-source disagreement std (null < 2 sources).
    Rows with no usable center (all-null proj) are dropped — no band without a center.
    `proj_col` is the league-scored projection column the scoring dispatcher selected."""
    return (
        proj.group_by("week", "sleeper_player_id")
        .agg(
            pl.col("position").first().alias("position"),
            pl.col(proj_col).median().alias("center_ppr"),
            pl.col("source").n_unique().alias("n_sources"),
            # Cross-source disagreement std — NULL (not 0.0) with a single source, so
            # "can't measure disagreement" stays distinct from "sources agreed exactly"
            # (law 2). Fills in-season when ffanalytics adds a 2nd source.
            pl.when(pl.col("source").n_unique() >= 2)
            .then(pl.col(proj_col).std(ddof=0))
            .otherwise(None)
            .alias("disagreement_ppr"),
        )
        .drop_nulls("center_ppr")
    )


def _residuals(consensus: pl.DataFrame, actual: pl.DataFrame) -> pl.DataFrame:
    """Per (player, week) residual = actual − consensus center, on matched pairs only."""
    return consensus.join(actual, on=["sleeper_player_id", "week"], how="inner").with_columns(
        (pl.col("actual_ppr") - pl.col("center_ppr")).alias("resid")
    )


def compute(season: int, scoring: dict | None = None) -> pl.DataFrame:
    # Scoring dispatcher: the league's scoring_settings pick the projection + actual points, so
    # center/residuals are league-scored. Standard (ppr/half/std) selects the canned columns; custom
    # is recomputed by the delta engine in _scoring. `scoring` is injectable (defaults to the persisted
    # league settings) so the backtest can exercise custom profiles without touching the parquet. The
    # output column names keep the *_ppr suffix (a documented wart — they now hold league points).
    if scoring is None:
        scoring = data_layer.read_scoring_settings(season)
    profile = scoring_profile(scoring)

    # League-scored projected points, per source row, before the cross-source consensus median.
    proj = data_layer.read_projections(season).with_columns(
        projection_points_expr(profile, scoring).alias("proj_pts_league")
    )
    actual = (
        data_layer.read_nfl_stats(season)
        .select(
            "sleeper_player_id", pl.col("week").cast(pl.Int64),
            actual_points_expr(profile, scoring).alias("actual_ppr"),
        )
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("actual_ppr").first())
    )

    consensus = _consensus_frame(proj, "proj_pts_league")
    matched = _residuals(consensus, actual)

    # Positional residual-std + residual-skew priors over the full pool (borrowed
    # substrate), + global fallbacks for any position that never matched (defensive; won't
    # happen for skill). skewness() is the shared pure helper, applied to each position's
    # residual list so the prior matches the per-player estimate it shrinks toward.
    pos_resid_std = {
        r["position"]: float(r["s"])
        for r in matched.group_by("position").agg(pl.col("resid").std(ddof=0).alias("s")).iter_rows(named=True)
        if r["s"] is not None
    }
    global_resid_std = float(matched["resid"].std(ddof=0))
    resid_by_pos: dict = {}
    for r in matched.select("position", "resid").iter_rows(named=True):
        resid_by_pos.setdefault(r["position"], []).append(float(r["resid"]))
    pos_resid_skew = {p: skewness(v) for p, v in resid_by_pos.items()}
    global_resid_skew = skewness([r for v in resid_by_pos.values() for r in v])

    # Per-player residual history, sorted by week, for the weeks-< W lookup.
    resid_by_player: dict = {}
    for r in matched.select("sleeper_player_id", "week", "resid").sort("sleeper_player_id", "week").iter_rows(named=True):
        resid_by_player.setdefault(r["sleeper_player_id"], []).append((int(r["week"]), float(r["resid"])))

    rows = []
    for r in consensus.iter_rows(named=True):
        pid, wk, pos = r["sleeper_player_id"], int(r["week"]), r["position"]
        hist = [resid for (w, resid) in resid_by_player.get(pid, []) if w < wk]
        pos_std = pos_resid_std.get(pos, global_resid_std)
        pos_skew = pos_resid_skew.get(pos, global_resid_skew)
        band = _projection_band(r["center_ppr"], hist, pos_std, pos_skew,
                                shrink_k=SHRINK_K, band_z=BAND_Z,
                                skew_shrink_k=SKEW_SHRINK_K, skew_gain=SKEW_GAIN)
        rows.append({
            "season": season,
            "week": wk,
            "sleeper_player_id": pid,
            "position": pos,
            "n_sources": r["n_sources"],
            "disagreement_ppr": round(r["disagreement_ppr"], 3) if r["disagreement_ppr"] is not None else None,
            **band,
        })

    df = pl.DataFrame(rows, infer_schema_length=None).sort("week", "center_ppr", descending=[False, True])
    max_week = int(df["week"].max())
    print(f"=== Projection consensus + spread: season={season}  weeks 1..{max_week}  "
          f"(rows={df.height}, sources={sorted(proj['source'].unique().to_list())}) ===")
    print("  positional residual std (band prior):  "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_resid_std.items())))
    print("  positional residual skew (skew prior): "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_resid_skew.items()) if s is not None))
    print(f"  week {max_week} top projections (center | p25–p75 band | skew | n_resid):")
    print(df.filter(pl.col("week") == max_week).head(8).select(
        "sleeper_player_id", "position", "center_ppr", "p25_ppr", "p75_ppr", "band_ppr", "skew_ppr", "n_resid"
    ))
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_projection_consensus(df, season)
    print(f"  → snapshots/derived/projection_consensus_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the weekly projection consensus + spread band.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
