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
  - p25_ppr / p50_ppr / p75_ppr: center ± BAND_Z·band, floored at 0 (points can't go
    negative — a mild practical right-skew; archetype skew, §3 component 3, is a follow-on).
  - disagreement_ppr: cross-source spread (std across sources) — NULL until a 2nd source
    lands (ffanalytics in-season). Present now so the additive source is a value change,
    not a schema change (the entity is source-agnostic by design).

Not tall over as_of_week (unlike the other derived analytics): a projection for week W is
a fixed forward statement, and its band uses only weeks < W, so the as-of information is
baked into the projected week. Keyed on `week`, like the projections entity it reads.

Scoring: center uses proj_pts_ppr, residuals use nfl_stats fantasy_points_ppr — correct
because the league is full PPR (generic PPR = league-exact today). The scoring_settings
selection/recompute for half-PPR / custom leagues stays the documented latent item in
TECHNICAL_ARCHITECTURE.md §Projections — not built here.

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
from _analytics import round1, stdev

# Variance-shrink weight, in "games of prior": the player's residual variance is pooled
# with the positional prior as (n·player_var + K·pos_var)/(n + K). Mirrors
# compute_player_signal.py's SHRINK_K idiom (there for a rate, here for a variance). At
# the week-4 freeze a player has ≤ 3 residuals, so K = 4 gives the prior a shade over
# half the weight — honest for thin samples, tilting to his own history as it accrues.
SHRINK_K = 4
# Band half-width multiplier on the residual std: p25/p75 = center ± BAND_Z·band. The
# normal-theory value for the 25th/75th percentiles is 0.6745·σ; residuals are non-normal
# (peaked in the middle with fat boom/bust tails that inflate σ), so the empirical
# multiplier that lands IQR coverage at ~50% is tuned on the 2025 answer key
# (backtest_projection_consensus.py --sweep) and baked here — tested, not guessed. The
# 2025 sweep chose 0.6 (coverage 0.514), below the normal 0.6745. Re-tune in-season.
BAND_Z = 0.6


def _consensus(proj_ppr) -> dict:
    """Consensus center + source count from one player-week's per-source projections.

    `proj_ppr`: the list of proj_pts_ppr values, one per source. Center = median (robust
    to an outlier source); n_sources = how many projected him. Pure — no I/O, no globals.
    """
    vals = [v for v in proj_ppr if v is not None]
    n = len(vals)
    center = sorted(vals)[n // 2] if n % 2 else (sorted(vals)[n // 2 - 1] + sorted(vals)[n // 2]) / 2 if n else None
    return {"center_ppr": center, "n_sources": n}


def _projection_band(center, resid_history, pos_resid_std, *, shrink_k, band_z) -> dict:
    """Percentile band around a borrowed projection center for one player-week.

    `center`: the consensus projection (becomes p50). `resid_history`: the player's
    realized (actual − projection) residuals over weeks strictly before this one
    (out-of-sample). `pos_resid_std`: the position's residual std over the full pool — the
    prior the thin per-player estimate shrinks toward. Constants injected (not module
    globals) so the backtest exercises this exact function.

    Band width = residual std shrunk toward the positional prior by `shrink_k` games:
    shrunk_var = (n·player_var + K·pos_var)/(n + K); band = √shrunk_var. With < 2
    residuals the player estimate is undefined → the band is the positional prior (a wide,
    honest default). p25/p75 = center ± band_z·band, floored at 0 (points can't go
    negative — mild practical right-skew).
    """
    player_std = stdev(resid_history)  # None when < 2 residuals
    n = len(resid_history)
    if player_std is None:
        band = pos_resid_std
    else:
        band = ((n * player_std ** 2 + shrink_k * pos_resid_std ** 2) / (n + shrink_k)) ** 0.5
    half = band_z * band
    return {
        "center_ppr": round1(center),
        "p25_ppr": round1(max(0.0, center - half)),
        "p50_ppr": round1(center),
        "p75_ppr": round1(center + half),
        "band_ppr": round(band, 3),
        "resid_std_raw": round(player_std, 3) if player_std is not None else None,
        "resid_std_pos": round(pos_resid_std, 3),
        "n_resid": n,
    }


def _consensus_frame(proj: pl.DataFrame) -> pl.DataFrame:
    """Collapse the multi-source projections to one consensus row per (week, player):
    median center, source count, and the cross-source disagreement std (null < 2 sources).
    Rows with no usable center (all-null proj) are dropped — no band without a center."""
    return (
        proj.group_by("week", "sleeper_player_id")
        .agg(
            pl.col("position").first().alias("position"),
            pl.col("proj_pts_ppr").median().alias("center_ppr"),
            pl.col("source").n_unique().alias("n_sources"),
            # Cross-source disagreement std — NULL (not 0.0) with a single source, so
            # "can't measure disagreement" stays distinct from "sources agreed exactly"
            # (law 2). Fills in-season when ffanalytics adds a 2nd source.
            pl.when(pl.col("source").n_unique() >= 2)
            .then(pl.col("proj_pts_ppr").std(ddof=0))
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


def compute(season: int) -> pl.DataFrame:
    proj = data_layer.read_projections(season)
    actual = (
        data_layer.read_nfl_stats(season)
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual_ppr"))
    )

    consensus = _consensus_frame(proj)
    matched = _residuals(consensus, actual)

    # Positional residual-std prior over the full pool (borrowed substrate), + a global
    # fallback for any position that never matched (defensive; won't happen for skill).
    pos_resid_std = {
        r["position"]: float(r["s"])
        for r in matched.group_by("position").agg(pl.col("resid").std(ddof=0).alias("s")).iter_rows(named=True)
        if r["s"] is not None
    }
    global_resid_std = float(matched["resid"].std(ddof=0))

    # Per-player residual history, sorted by week, for the weeks-< W lookup.
    resid_by_player: dict = {}
    for r in matched.select("sleeper_player_id", "week", "resid").sort("sleeper_player_id", "week").iter_rows(named=True):
        resid_by_player.setdefault(r["sleeper_player_id"], []).append((int(r["week"]), float(r["resid"])))

    rows = []
    for r in consensus.iter_rows(named=True):
        pid, wk, pos = r["sleeper_player_id"], int(r["week"]), r["position"]
        hist = [resid for (w, resid) in resid_by_player.get(pid, []) if w < wk]
        pos_std = pos_resid_std.get(pos, global_resid_std)
        band = _projection_band(r["center_ppr"], hist, pos_std, shrink_k=SHRINK_K, band_z=BAND_Z)
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
    print("  positional residual std (band prior): "
          + ", ".join(f"{p} {s:.2f}" for p, s in sorted(pos_resid_std.items())))
    print(f"  week {max_week} top projections (center | p25–p75 band | n_resid):")
    print(df.filter(pl.col("week") == max_week).head(8).select(
        "sleeper_player_id", "position", "center_ppr", "p25_ppr", "p75_ppr", "band_ppr", "n_resid"
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
