"""
Manager Dossiers — the AI dossier writer (DECISION_READS.md §7 Phase B).

Reads the deterministic `manager_features` (Phase A) and writes one qualitative dossier per manager
to `derived/manager_dossiers_{season}`. Opt-in and API-key-gated; synchronous sequential Haiku calls
(`client.generate_dossier` is the swap point for a Batch path later). A zero-comparable-league
manager skips the AI (a hardcoded "no intel" dossier); the whole read is skipped cleanly when no key
is configured; a re-run is a no-op unless `--force` (run once per season).

Usage:
    python3 -m application.ai.write_manager_dossiers --season 2025 [--force] [--model claude-haiku-4-5]
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
from application.data import data_layer
from application.ai import client
from application.ai import dossier_prompt as dp

# Haiku 4.5 pricing ($ per 1M tokens) — for the cost summary line only.
_IN_RATE, _OUT_RATE = 1.0, 5.0


def build_dossier_row(feat: dict, season: int, generated_at: str, *, model: str):
    """Return (row_dict, usage_or_None) for one manager. Zero-signal managers skip the API.

    Pure orchestration of the seam: the ONLY side effect is `client.generate_dossier` (one Haiku
    call), and only for managers with signal. Validates the returned dict against the fixed schema.
    """
    zero_signal = (feat.get("n_transactions") in (0, None)) or feat.get("depth_tier") == "none"
    base = {
        "season": season,
        "owner_id": feat.get("owner_id"),
        "owner_name": feat.get("owner_name"),
        "team_name": feat.get("team_name"),
        "roster_id": feat.get("roster_id"),
        "is_primary": bool(feat.get("is_primary")),
        "n_leagues": feat.get("n_leagues"),
        "n_seasons": feat.get("n_seasons"),
        "n_transactions": feat.get("n_transactions"),
        "depth_tier": feat.get("depth_tier"),
        "model": None,
        "generated_at": generated_at,
        "is_zero_signal": zero_signal,
    }
    if zero_signal:
        return {**base, **dp.zero_signal_dossier()}, None

    dossier, usage = client.generate_dossier(
        dp.system_prompt(), dp.user_prompt(feat), model=model,
    )
    missing = [k for k in dp.DOSSIER_KEYS if not str(dossier.get(k, "")).strip()]
    if missing:
        raise ValueError(f"dossier for {feat.get('owner_name')} missing/empty keys: {missing}")
    return {**base, "model": model, **{k: dossier[k] for k in dp.DOSSIER_KEYS}}, usage


def compute(season: int, *, model: str = client.DEFAULT_MODEL) -> pl.DataFrame:
    feats = data_layer.read_manager_features(season).sort("owner_name")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"=== Manager dossiers: season={season}  model={model}  managers={feats.height} ===")

    rows, tot_in, tot_out, n_api = [], 0, 0, 0
    for feat in feats.iter_rows(named=True):
        row, usage = build_dossier_row(feat, season, generated_at, model=model)
        rows.append(row)
        tag = "zero-signal (no API)" if row["is_zero_signal"] else f"{row['n_transactions']} txns"
        print(f"  {(row['owner_name'] or ''):<16} {'[you]' if row['is_primary'] else '     '}  {tag}")
        if usage:
            tot_in += usage["input_tokens"]
            tot_out += usage["output_tokens"]
            n_api += 1

    cost = tot_in / 1e6 * _IN_RATE + tot_out / 1e6 * _OUT_RATE
    print(f"  {n_api} API call(s); {tot_in} in / {tot_out} out tokens  ~= ${cost:.3f}")
    return pl.DataFrame(rows)


def run(season: int, *, force: bool = False, model: str = client.DEFAULT_MODEL) -> None:
    if not client.api_available():
        print("Manager dossiers: LOCKED — set a real config.ANTHROPIC_API_KEY to enable this opt-in "
              "AI read. Nothing written.")
        return
    if data_layer.manager_dossiers_exist(season) and not force:
        print(f"Manager dossiers for {season} already exist — run once per season. "
              f"Use --force to regenerate.")
        return
    df = compute(season, model=model)
    data_layer.write_manager_dossiers(df, season)
    print(f"  -> snapshots/derived/manager_dossiers_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write per-manager cross-league AI dossiers (Phase B).")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--force", action="store_true", help="regenerate even if dossiers exist")
    parser.add_argument("--model", default=client.DEFAULT_MODEL)
    args = parser.parse_args()
    run(args.season, force=args.force, model=args.model)
