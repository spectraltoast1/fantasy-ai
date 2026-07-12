"""
Manager-dossiers gate — an INTERNAL-CONSISTENCY check on the AI output (no answer key).

AI-written dossiers can't be scored against ground truth, so this verifies they are self-consistent
and honest, reading only the PERSISTED dossiers (+ manager_features) — no API calls, so it's free
and repeatable. Four hard checks (exit 0 iff all pass) plus soft grounding evidence:

  1. Coverage — every league manager has exactly one dossier row (no missing, no extras).
  2. Schema — every dossier carries all fixed keys, non-empty.
  3. Depth echo — each dossier's signal-depth columns match manager_features exactly, and
     is_zero_signal is set iff the manager truly had no signal (grounding the confidence gate).
  4. Zero-signal honesty — a zero-signal dossier carries the hardcoded "no intel" content with the
     model unset (AI skipped); a signal dossier names the model. No fabricated tendencies.

Soft evidence (reported, not gated): how many confidence_notes cite the transaction count, and that
the primary user's dossier is self-framed (blindspot) rather than opponent-framed.

Usage:
    python3 -m application.ai.check_manager_dossiers --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
from application.data import data_layer
from application.ai import dossier_prompt as dp


def _check_coverage(dossiers: pl.DataFrame, feats: pl.DataFrame) -> bool:
    d_ids = set(dossiers["owner_id"].to_list())
    f_ids = set(feats["owner_id"].to_list())
    ok = d_ids == f_ids and dossiers.height == feats.height and dossiers["owner_id"].n_unique() == dossiers.height
    print(f"  1. coverage: {dossiers.height} dossiers for {feats.height} managers, "
          f"missing={len(f_ids - d_ids)} extra={len(d_ids - f_ids)}  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_schema(dossiers: pl.DataFrame) -> bool:
    empty = 0
    for r in dossiers.iter_rows(named=True):
        empty += sum(1 for k in dp.DOSSIER_KEYS if not str(r.get(k) or "").strip())
    ok = empty == 0
    print(f"  2. schema: {len(dp.DOSSIER_KEYS)} required fields, {empty} empty across all rows  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def _check_depth_echo(dossiers: pl.DataFrame, feats: pl.DataFrame) -> bool:
    cols = ["n_leagues", "n_seasons", "n_transactions", "depth_tier"]
    j = dossiers.select(["owner_id", *cols, "is_zero_signal"]).join(
        feats.select(["owner_id", *cols]), on="owner_id", suffix="_feat")
    mismatch = j.filter(
        (pl.col("n_leagues") != pl.col("n_leagues_feat"))
        | (pl.col("n_seasons") != pl.col("n_seasons_feat"))
        | (pl.col("n_transactions") != pl.col("n_transactions_feat"))
        | (pl.col("depth_tier") != pl.col("depth_tier_feat"))
    ).height
    # is_zero_signal must be set iff the manager had no signal
    zs_bad = j.filter(
        pl.col("is_zero_signal") != ((pl.col("n_transactions_feat") == 0) | (pl.col("depth_tier_feat") == "none"))
    ).height
    ok = mismatch == 0 and zs_bad == 0
    print(f"  3. depth echo: {mismatch} depth mismatch vs features, {zs_bad} wrong is_zero_signal  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def _check_zero_signal_honesty(dossiers: pl.DataFrame) -> bool:
    hardcoded = dp.zero_signal_dossier()
    zero = dossiers.filter(pl.col("is_zero_signal"))
    signal = dossiers.filter(~pl.col("is_zero_signal"))
    bad_zero = sum(
        1 for r in zero.iter_rows(named=True)
        if r.get("model") is not None or any(r.get(k) != hardcoded[k] for k in dp.DOSSIER_KEYS)
    )
    bad_signal = signal.filter(pl.col("model").is_null()).height
    ok = bad_zero == 0 and bad_signal == 0
    print(f"  4. zero-signal honesty: {zero.height} zero-signal (hardcoded, model unset), "
          f"{bad_zero} malformed, {bad_signal} signal rows missing a model  {'PASS' if ok else 'FAIL'}")
    return ok


def _evidence(dossiers: pl.DataFrame) -> None:
    signal = dossiers.filter(~pl.col("is_zero_signal"))
    grounded = sum(
        1 for r in signal.iter_rows(named=True)
        if str(r["n_transactions"]) in (r["confidence_note"] or "")
    )
    print(f"  evidence: {grounded}/{signal.height} confidence_notes cite the transaction count")
    prim = dossiers.filter(pl.col("is_primary"))
    if prim.height == 1:
        text = (prim["edge_or_blindspot"][0] or "").lower()
        self_framed = any(w in text for w in (" you", "your", " you'"))
        print(f"  evidence: primary user's blindspot is self-framed (mentions you/your): {self_framed}")


def run(season: int) -> bool:
    dossiers = data_layer.read_manager_dossiers(season)
    feats = data_layer.read_manager_features(season)
    print(f"=== Manager dossiers gate: season={season}  dossiers={dossiers.height} ===")

    c1 = _check_coverage(dossiers, feats)
    c2 = _check_schema(dossiers)
    c3 = _check_depth_echo(dossiers, feats)
    c4 = _check_zero_signal_honesty(dossiers)
    _evidence(dossiers)

    ok = c1 and c2 and c3 and c4
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — dossiers are "
          f"{'complete, schema-valid, depth-grounded, and honest about zero signal' if ok else 'INCONSISTENT'}.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Internal-consistency gate for manager dossiers.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
