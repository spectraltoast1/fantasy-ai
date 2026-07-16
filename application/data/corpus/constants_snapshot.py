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

⚠️ BULL_Z DRIFT (recorded, NOT fixed — changing a constant is the Tuner's job, standing instr 4):
STATUS.md narration records `BULL_Z = 1.645`; the live code (`compute_ros_player_band.py`) is `1.44`
(the joint (BULL_Z, ANCHOR_W) = (1.44, 0.25) freeze-week tune, coverage 0.817). This snapshot pins the
ACTUAL live value **1.44** — so the fingerprint documents what the code really did, and the drift gate
would fire only if the code changed without updating this snapshot. The STATUS↔code discrepancy is a
narration-vs-code documentation drift, surfaced here; it is not a code change to make in this session.
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
    # compute_ros_player_band (§2/§3 interval substrate)
    "ros_player_band.BULL_Z": 1.44,
    "ros_player_band.ANCHOR_W": 0.25,
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
    """Stable 16-char fingerprint of the full snapshot vector (the `constants_hash` provenance column).

    Canonicalised exactly like `_keys.scoring_key`: `json.dumps(sort_keys, compact)` → `sha1[:16]`.
    Deterministic + machine-independent (hashlib, never Python's salted `hash()`)."""
    norm = json.dumps(SNAPSHOT, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


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
