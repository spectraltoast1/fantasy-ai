"""
Manager behavioural features — the deterministic, credit-free AI input (DECISION_READS.md §7).

Phase A commit 3. Reads the cross-league `manager_activity_{season}` (acquired by
sleeper.py's `fetch-manager-activity` mode) and emits one row per league manager to
`snapshots/derived/manager_features_{season}.parquet`: FAAB aggression, waiver/free-agent
mix, waiver success rate, add/drop churn, trade frequency, positional lean of adds, and the
signal-depth counts (n_leagues / n_seasons / n_transactions) the Phase-B Haiku writer gates
confidence on. Rate/lean features are null when the sample is too thin to define them — never
a fabricated 0 (law 2). NOT a forward projection and NOT the dossier — this is the pre-filtered
feature substrate; the AI synthesis is Phase B.

Same SOLID shape as the other compute transforms: the pure per-manager math lives in
`_manager.manager_features` (injected constants, no I/O), `compute(season)` is the composition
root, `run(season)` writes. Every manager in the league gets a row — including a manager with
zero comparable-league activity (depth 0, null features), so the profile set is complete.

Usage:
    python3 -m application.data.transforms.compute_manager_features --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms import _manager

# Signal-depth tiers (transactions drawn on) — an honest, coarse confidence label; Phase B
# still reads the raw counts. Injected into the pure feature function.
DEPTH_THIN = 10          # < this many transactions = a thin read
DEPTH_MODERATE = 30      # < this = moderate; >= this = deep


def _primary_username() -> str | None:
    """config.SLEEPER_USERNAME resolves 'which manager is me' (mirrors the front-end's
    MY_USERNAME==owner_name idiom). Guarded so the transform still runs without config."""
    try:
        from application import config
        return getattr(config, "SLEEPER_USERNAME", None)
    except Exception:
        return None


def compute(season: int) -> pl.DataFrame:
    activity = data_layer.read_manager_activity(season)
    teams = data_layer.read_sleeper_teams(season)          # owner_id, roster_id, owner_name, team_name

    # sleeper_player_id -> position, skill only (for the positional lean of adds).
    players = data_layer.read_sleeper_players()
    pos_by_id = {
        str(r["sleeper_player_id"]): r["position"]
        for r in players.select("sleeper_player_id", "position").iter_rows(named=True)
        if r["position"] in _manager._SKILL
    }

    me = _primary_username()
    by_owner = {oid: g.to_dicts() for (oid,), g in activity.group_by("owner_id")}

    rows = []
    for t in teams.iter_rows(named=True):
        owner_id = t.get("owner_id")
        feats = _manager.manager_features(
            by_owner.get(owner_id, []), pos_by_id,
            depth_thin=DEPTH_THIN, depth_moderate=DEPTH_MODERATE,
        )
        rows.append({
            "season": season,
            "owner_id": owner_id,
            "owner_name": t.get("owner_name"),
            "team_name": t.get("team_name"),
            "roster_id": t.get("roster_id"),
            "is_primary": (me is not None and t.get("owner_name") == me),
            **feats,
        })

    df = pl.DataFrame(rows).sort("n_transactions", "owner_name", descending=[True, False])

    print(f"=== Manager features: season={season}  managers={df.height} ===")
    print(df.select(
        "owner_name", "is_primary", "n_leagues", "n_seasons", "n_transactions", "depth_tier",
        "waiver_success_rate", "avg_bid_frac", "trades_per_league",
    ))
    zero = df.filter(pl.col("n_transactions") == 0).height
    print(f"  signal depth — deep {df.filter(pl.col('depth_tier')=='deep').height}, "
          f"moderate {df.filter(pl.col('depth_tier')=='moderate').height}, "
          f"thin {df.filter(pl.col('depth_tier')=='thin').height}, none {zero}")
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_manager_features(df, season)
    print(f"  → snapshots/derived/manager_features_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the per-manager cross-league behavioural features.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
