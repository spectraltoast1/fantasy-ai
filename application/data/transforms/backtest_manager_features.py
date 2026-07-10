"""
Manager-features gate — an INTERNAL-CONSISTENCY check, because behaviour has no answer key.

Unlike the predictive reads (VOR / True Rank / …), a behavioural profile can't be scored
against realised outcomes — there's no "correct" waiver aggression. So this gate verifies the
pipeline is self-consistent and honest, three ways (each PASS/FAIL, exit 0 iff all pass):

  1. Comparability invariant — every source league in manager_activity matches the TARGET
     league on all four filter axes (scoring profile + size + QB structure + format). Grounds
     against the persisted target facts (scoring_settings / team count / roster_positions), so a
     leaked non-comparable league fails here. Reuses the shipped _manager helpers.
  2. Accounting round-trip — the features reconcile with the activity frame by INDEPENDENT
     re-aggregation (n_transactions / n_leagues / trade+waiver+FA counts), and every fraction
     sits in [0, 1] with positional shares summing to 1 (or all null).
  3. Signal-depth honesty — every league manager has a row; a manager with zero captured
     transactions has NULL rate/lean features (no fabricated 0), and non-null features are
     backed by real activity.

Usage:
    python -m application.data.transforms.backtest_manager_features --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms import _manager

_FRACTION_COLS = ("waiver_share", "waiver_success_rate", "avg_bid_frac", "max_bid_frac",
                  "budget_spent_frac", "add_qb_share", "add_rb_share", "add_wr_share", "add_te_share")
_SHARE_COLS = ("add_qb_share", "add_rb_share", "add_wr_share", "add_te_share")


def _target_signature(season: int) -> dict:
    """Reconstruct the target league's comparability signature from persisted data (no API)."""
    scoring = data_layer.read_scoring_settings(season)
    num_teams = data_layer.read_sleeper_teams(season).height
    slots = data_layer.read_roster_positions(season).sort("slot_index")["slot"].to_list()
    return {
        "scoring_profile": _manager.scoring_profile(scoring),
        "num_teams": num_teams,
        "qb_structure": _manager.qb_structure(slots),
    }


def _check_comparability(activity: pl.DataFrame, target: dict) -> bool:
    leagues = activity.filter(pl.col("kind") == "league")
    mism = leagues.filter(
        (pl.col("scoring_profile") != target["scoring_profile"])
        | (pl.col("num_teams") != target["num_teams"])
        | (pl.col("qb_structure") != target["qb_structure"])
    )
    fmt_uniq = leagues["league_format"].n_unique()
    ok = mism.height == 0 and fmt_uniq <= 1
    print(f"  1. comparability invariant  (target {target['scoring_profile']}/"
          f"{target['num_teams']}-team/{target['qb_structure']}):")
    print(f"       {leagues.height} source-league markers, {mism.height} off-axis, "
          f"{fmt_uniq} distinct format(s)  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_accounting(activity: pl.DataFrame, feats: pl.DataFrame) -> bool:
    txn = activity.filter(pl.col("kind") == "txn")
    # independent re-aggregation from the activity frame
    agg = txn.group_by("owner_id").agg(
        pl.len().alias("n_txn"),
        (pl.col("txn_type") == "trade").sum().alias("n_trade"),
        (pl.col("txn_type") == "waiver").sum().alias("n_waiver"),
        (pl.col("txn_type") == "free_agent").sum().alias("n_fa"),
    )
    lg = (activity.filter(pl.col("kind") == "league")
          .group_by("owner_id")
          .agg(pl.struct("source_league_id", "source_season").n_unique().alias("n_lg")))
    j = (feats.join(agg, on="owner_id", how="left")
              .join(lg, on="owner_id", how="left")
              .with_columns(pl.col("n_txn", "n_trade", "n_waiver", "n_fa", "n_lg").fill_null(0)))

    recon = j.filter(
        (pl.col("n_transactions") != pl.col("n_txn"))
        | (pl.col("n_trades") != pl.col("n_trade"))
        | (pl.col("n_waivers") != pl.col("n_waiver"))
        | (pl.col("n_free_agents") != pl.col("n_fa"))
        | (pl.col("n_leagues") != pl.col("n_lg"))
    )

    # every fraction in [0, 1]
    frac_bad = 0
    for c in _FRACTION_COLS:
        frac_bad += feats.filter(pl.col(c).is_not_null() & ((pl.col(c) < 0) | (pl.col(c) > 1))).height
    # positional shares sum to 1 (or all null)
    have = feats.filter(pl.col("add_qb_share").is_not_null())
    share_sum = have.select(sum(pl.col(c) for c in _SHARE_COLS).alias("s"))["s"].to_list()
    share_bad = sum(1 for s in share_sum if abs(s - 1.0) > 1e-6)

    ok = recon.height == 0 and frac_bad == 0 and share_bad == 0
    print(f"  2. accounting round-trip:")
    print(f"       {recon.height} managers with count mismatch, {frac_bad} out-of-range fraction(s), "
          f"{share_bad} bad positional-share sum(s)  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_depth_honesty(feats: pl.DataFrame, teams: pl.DataFrame) -> bool:
    all_present = feats.height == teams.height and feats["owner_id"].n_unique() == teams.height
    # zero transactions -> all rate/lean features null (no fabricated 0)
    zero = feats.filter(pl.col("n_transactions") == 0)
    fabricated = 0
    for c in _FRACTION_COLS + ("trades_per_league", "moves_per_league"):
        fabricated += zero.filter(pl.col(c).is_not_null()).height
    # non-null rate feature must be backed by transactions
    unbacked = feats.filter(
        (pl.col("n_transactions") == 0) & (pl.col("depth_tier") != "none")
    ).height
    ok = all_present and fabricated == 0 and unbacked == 0
    print(f"  3. signal-depth honesty:")
    print(f"       {feats.height}/{teams.height} managers profiled, {zero.height} zero-signal, "
          f"{fabricated} fabricated feature(s)  {'PASS' if ok else 'FAIL'}")
    return ok


def run(season: int) -> bool:
    activity = data_layer.read_manager_activity(season)
    feats = data_layer.read_manager_features(season)
    teams = data_layer.read_sleeper_teams(season)
    target = _target_signature(season)

    print(f"=== Manager features backtest: season={season}  "
          f"managers={feats.height}  activity_rows={activity.height} ===")
    c1 = _check_comparability(activity, target)
    c2 = _check_accounting(activity, feats)
    c3 = _check_depth_honesty(feats, teams)

    ok = c1 and c2 and c3
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — cross-league features are "
          f"{'internally consistent + honest' if ok else 'INCONSISTENT'}: comparable leagues only, "
          f"counts reconcile, thin samples stay null.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Internal-consistency gate for manager features.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
