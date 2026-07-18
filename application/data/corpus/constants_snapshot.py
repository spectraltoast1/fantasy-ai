"""Pinned constants snapshot — the `constants_hash` provenance for the L2 predictions ledger (Session 4a).

A read-only *fingerprint* of the tuning-constant vector that produced the frozen 5-read spine + band +
consensus. Its job is NOT to tune (that is L4's future `_constants.py`, deliberately UNBUILT here — no
Tunable dataclass, no grids, no objectives, no sweep harness) — it is to answer "which model made this
claim?" so that a spine recomputed under different constants writes a *distinguishable parallel
population* in `predictions` instead of silently collapsing two regimes into one provenance string (the
exact provenance-lie the ledger exists to prevent). The hash CHANGES when any constant changes;
`check_constants_drift()` reddens when a live module global drifts from this snapshot (the drift guard).

Keys are namespaced `<module>.<CONST>` because two modules legitimately share a constant name
(`projection_consensus.SHRINK_K=4` vs `player_signal.SHRINK_K=6`).

TWO EPOCHS (Session 8c — the honest-engine promotion). `SNAPSHOT` tracks the LIVE shipped engine, so it was
RE-PINNED in 8c: `ros_player_band.BULL_Z` 1.44→0.524, `ANCHOR_W` 0.25→0.0 (the joint re-fit at the promoted
`CENTER_SHRINK=0.8`). `constants_hash()` therefore now fingerprints the shipped honest engine, and
`check_constants_drift()` is green against it. The FROZEN corpus (the immutable 2.9M served=false rows) was
made at the OLD vector — `FROZEN_CORPUS_HASH` records that baseline, and the frozen-corpus gates validate
against IT, not the moving live hash. `CENTER_SHRINK`/`BEAR_Z` are post-corpus dials, deliberately OUT of the
snapshot (they never fingerprinted the frozen rows; keeping them out preserves the frozen rows' reproducibility).
"""
import hashlib
import importlib
import json

# The full constant vector consumed by the 6 reads + the consensus substrate (verified in-code
# 2026-07-16). This is a LITERAL fingerprint — it is NOT read back from the modules at hash time, so it
# can disagree with the code and turn the drift gate red (that disagreement is the whole point).
SNAPSHOT: dict[str, object] = {
    # compute_projection_consensus (§3 substrate the other reads borrow)
    "projection_consensus.BAND_Z": 0.55,
    "projection_consensus.SKEW_GAIN": 1.5,
    "projection_consensus.SHRINK_K": 4,
    "projection_consensus.SKEW_SHRINK_K": 8,
    # compute_ros_player_band (§2/§3 interval substrate) — RE-PINNED in Session 8c (the honest-engine
    # promotion): BULL_Z 1.44→0.524, ANCHOR_W 0.25→0.0, the joint re-fit at the promoted CENTER_SHRINK=0.8.
    # This moves the LIVE constants_hash to the shipped engine; the frozen corpus keeps FROZEN_CORPUS_HASH
    # (below) — the two epochs are the "distinguishable population" without persisting a second copy.
    "ros_player_band.BULL_Z": 0.524,
    "ros_player_band.ANCHOR_W": 0.0,
    "ros_player_band.POOL_SIZE": 300,
    "ros_player_band.POSITION_FLOORS": {"QB": 32, "RB": 80, "WR": 90, "TE": 32},
    # compute_player_signal (§1 repeatability / trust)
    "player_signal.SHRINK_K": 6,
    "player_signal.MIN_GAMES": 3,
    "player_signal.POS_MEAN_MIN_OPP": 3.0,
    "player_signal.SPIKE_BAND": 0.15,
    "player_signal.STICKY_BAND": 0.05,
    "player_signal.OPP_HALF_LIFE_WK": None,
    "player_signal.DIRECTION_HALF_LIFE_WK": 2,
    "player_signal.DIRECTION_BAND": 0.04,
    # compute_positional_depth (§6 roster shape)
    "positional_depth.GAP_VOR": 0.0,
    "positional_depth.SURPLUS_SPECTRUM": 0.66,
    # compute_bracket_sim (§5 playoff odds)
    "bracket_sim.SIMS": 10000,
    "bracket_sim.SEED": 20260709,
    "bracket_sim.MAGIC_ODDS": 0.90,
    "bracket_sim._DEFAULT_PLAYOFF_WEEK_START": 15,
}

# IMPROVEMENT_LOOP names these five as L4's initial tunables. Tagged for the future Tuner; the hash still
# covers the FULL vector (a fingerprint must be complete, not just the tunable subset).
TUNABLES: tuple[str, ...] = (
    "projection_consensus.BAND_Z",
    "projection_consensus.SKEW_GAIN",
    "ros_player_band.BULL_Z",
    "ros_player_band.ANCHOR_W",
    "player_signal.OPP_HALF_LIFE_WK",
)


def constants_hash() -> str:
    """Stable 16-char fingerprint of the full snapshot vector (the `constants_hash` provenance column) —
    tracks the LIVE shipped engine (moves on a promotion re-pin).

    Canonicalised exactly like `_keys.scoring_key`: `json.dumps(sort_keys, compact)` → `sha1[:16]`.
    Deterministic + machine-independent (hashlib, never Python's salted `hash()`)."""
    norm = json.dumps(SNAPSHOT, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


# The constants_hash that produced the FROZEN corpus (the immutable L2/L3 baseline: the 2.9M served=false
# predictions + their resolutions + scorecard). Recorded in Session 8c when the live snapshot was re-pinned to
# the promoted honest engine — so `constants_hash()` (live) now differs from the frozen rows' stamp. The
# frozen-corpus gates validate against THIS baseline, not the moving live hash; a future re-backfill under a
# new engine appends a new-hash population beside the frozen one (append-only) — the annual pipeline's job.
FROZEN_CORPUS_HASH = "a3d01b8e5f4d5131"


def _live_value(key: str):
    """The live module global a snapshot key mirrors (lazy import — keeps this module import-cheap and
    dodges a corpus→transforms import at load). Used ONLY by the drift check, never by the hash."""
    module_name, const = key.split(".", 1)
    mod = importlib.import_module(f"application.data.transforms.compute_{module_name}")
    return getattr(mod, const)


def check_constants_drift() -> dict:
    """Cross-check the snapshot against the live module globals — the drift guard.

    Returns `{ok, drifts, missing}`: `drifts` = `[(key, snapshot_value, live_value)]` where a live
    constant differs from its pin; `missing` = snapshot keys that no longer resolve to a module global.
    `ok=False` (⇒ gate red) when either is non-empty. Change a module constant without updating this
    snapshot and the gate reddens."""
    drifts, missing = [], []
    for key, snap_val in SNAPSHOT.items():
        try:
            live = _live_value(key)
        except (ImportError, AttributeError):
            missing.append(key)
            continue
        if live != snap_val:
            drifts.append((key, snap_val, live))
    return {"ok": not drifts and not missing, "drifts": drifts, "missing": missing}
