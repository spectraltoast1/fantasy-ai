"""
build_substrate.py — the NFL-substrate driver (Session 2).

Builds the scoring-scoped forward-prior spine the corpus harvest (Session 3) runs on:
`projection_consensus` then `ros_player_band`, for each standard scoring key × each backfilled season.
Consensus must precede the band (the band reads the consensus centres/spread). Idempotent — re-running
overwrites each scoring/season slice deterministically.

Prerequisites (NFL-global, already banked): `projections` 2020–2025, `nfl_stats`, `adp_preseason`, and
the per-held-out `adp_points_curve/holdout_{S}` (compute_adp_points_curve --all). The band's anchor read
requires holdout_S to exist for each season S it builds.

Scope: Session 2 built the MATCHED keys — {ppr, half}. Session 2.5's `--generalization` mode adds the
generalization stratum's remaining keys (std + the capped custom `cust-<hash>` keys), read from the final
corpus_manifest, EXCLUDING {ppr,half} (already built). Custom keys resolve a representative scoring dict
from corpus_discovery so consensus recomputes the custom points.

Usage:
    python3 -m application.data.transforms.build_substrate                       # {ppr,half} × 2020..2025
    python3 -m application.data.transforms.build_substrate --seasons 2020 2021   # subset of seasons
    python3 -m application.data.transforms.build_substrate --scoring-keys ppr    # subset of keys
    python3 -m application.data.transforms.build_substrate --generalization      # gen keys × 2020..2025
"""

import argparse
import json
import sys

from application.data import data_layer
from application.data.transforms import compute_projection_consensus, compute_ros_player_band
from application.data.transforms._keys import scoring_key_from_settings

DEFAULT_SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
DEFAULT_KEYS = ["ppr", "half"]


def run(seasons: list[int], scoring_keys: list[str]) -> None:
    for key in scoring_keys:
        for season in seasons:
            print(f"\n########## substrate: scoring={key}  season={season} ##########")
            compute_projection_consensus.run(season, scoring_key=key)
            compute_ros_player_band.run(season, scoring_key=key)


def _gen_substrate_keys():
    """(std_keys, {custom_key: representative_scoring_settings}) for the generalization stratum, EXCLUDING
    {ppr,half} (already built for matched). Gen keys come from the final manifest; each custom cust-<hash>
    is resolved to a representative scoring_settings dict from discovery (any league carrying that key)."""
    man = data_layer.read_corpus_manifest().to_dicts()
    gen_keys = {r["scoring_key"] for r in man if r["stratum"] == "generalization"} - {"ppr", "half"}
    std_keys = sorted(k for k in gen_keys if not str(k).startswith("cust"))
    custom_keys = sorted(k for k in gen_keys if str(k).startswith("cust"))
    key_to_scoring = {}
    for r in data_layer.read_corpus_discovery().to_dicts():
        settings = json.loads(r["scoring_settings_json"])
        k = scoring_key_from_settings(settings)
        if k in custom_keys and k not in key_to_scoring:
            key_to_scoring[k] = settings
    missing = [k for k in custom_keys if k not in key_to_scoring]
    if missing:
        raise RuntimeError(f"no discovery league resolves custom keys {missing}")
    return std_keys, key_to_scoring


def run_generalization(seasons: list[int]) -> None:
    std_keys, custom = _gen_substrate_keys()
    n_keys = len(std_keys) + len(custom)
    print(f"=== generalization substrate: {len(std_keys)} std key(s) {std_keys} + {len(custom)} custom "
          f"key(s) × {len(seasons)} seasons = {n_keys * len(seasons)} (consensus, band) pairs ===")
    for key in std_keys:                               # std → standard_scoring handles it
        for season in seasons:
            print(f"\n########## substrate: scoring={key}  season={season} ##########")
            compute_projection_consensus.run(season, scoring_key=key)
            compute_ros_player_band.run(season, scoring_key=key)
    for key, scoring in custom.items():                # custom → pass the representative scoring dict
        for season in seasons:
            print(f"\n########## substrate: scoring={key}  season={season} ##########")
            compute_projection_consensus.run(season, scoring_key=key, scoring=scoring)
            compute_ros_player_band.run(season, scoring_key=key)
    print(f"\n=== generalization substrate complete: {n_keys} keys × {len(seasons)} seasons ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build the NFL substrate (projection_consensus + ros_player_band) per scoring_key × season.")
    parser.add_argument("--seasons", type=int, nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--scoring-keys", nargs="+", choices=["ppr", "half", "std"], default=DEFAULT_KEYS)
    parser.add_argument("--generalization", action="store_true",
                        help="build the generalization stratum's keys (std + capped custom) from the manifest")
    args = parser.parse_args()
    if args.generalization:
        run_generalization(args.seasons)
    else:
        run(args.seasons, args.scoring_keys)
    sys.exit(0)
