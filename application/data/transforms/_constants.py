"""transforms/_constants.py — the engine's *dials* registry (Improvement-Loop Session 6, L4).

The single home for the constants the Tuner (L4) sweeps: the dials that drift across seasons and get
re-fit out-of-sample. It is NOT a home for every constant that happens to be a number — an operational
pin (a random `SEED`, a sim count) or a not-yet-tuned dial is part of its own script's logic and lives
there, not here. Two constants that never get swept in the registry would just recreate the
two-places-hold-a-number problem this file exists to kill.

THE RULE — one home per constant:
  * A constant lives in EXACTLY ONE place; nothing is defined here AND in a module.
  * A *dial* migrates into this registry the FIRST TIME it is actually tuned; a *pin* never migrates.
  * The owning module RE-EXPORTS a migrated dial (`from application.data.transforms._constants import
    BAND_Z`), so the dial's canonical dotted path (`projection_consensus.BAND_Z`) is preserved — the
    backtests that `from compute_… import BAND_Z`, `constants_snapshot._live_value`, and the drift gate
    all still resolve.
  * Borderline dial/pin calls (e.g. `MAGIC_ODDS`, `POOL_SIZE`) are deferred to the session that first
    tunes the constant.

Over seasons the dials converge here instead of scattering, while pins and untouched dials stay home.

This file is a LEAF: it imports nothing from `transforms` / `corpus` / `data_layer` (a dial re-export is
`transforms → _constants`; the reverse would be an import cycle). `gate`/`objective` are STRINGS the
tuner resolves lazily via `importlib` — never live callables — for the same reason.

Session 6 migrates the 5 dials named in `constants_snapshot.TUNABLES`. `constants_snapshot.py` stays the
FROZEN provenance fingerprint of the FULL constant vector (its `constants_hash` is baked into 2.9M
`predictions` rows) and is UNCHANGED: this registry is the live HOME for these 5, the snapshot remains
their historical pin, and the drift gate cross-checks that the two agree (registry.current ==
SNAPSHOT[key] == live module global).

`scope` records the DATA scope the dial's fit objective reads (nfl / scoring / league), which tells the
tuner's `SplitReader` which reads to guard. It is NOT a per-league value: all five are single global
scalars. For every Session-6 dial the OPERATIVE holdout is season-wise (TRAIN 2020–23 · DEV 2024 · TEST
2025); the league-wise (generalization-cohort) seal is built and prove-bitten but N/A-by-construction
this session (these objectives don't fit a per-league value) — it becomes load-bearing from Session 7's
genuinely league-scoped reads.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Tunable:
    """One swept dial. `current` is the single source of truth for its live value (re-exported below)."""
    name: str                    # the module-global name, e.g. "BAND_Z"
    module: str                  # short module key: compute_<module>, e.g. "projection_consensus"
    current: object              # the live value — equals the exact prior in-code literal (no number moved)
    grid: tuple                  # candidate values the sweep searches (moved from the backtest)
    gate: str                    # backtest module the fit objective + coupled gate live in
    objective: str               # human label of the fit objective the gate computes
    scope: str                   # data scope the objective reads: "nfl" | "scoring" | "league"
    coupled_gates: tuple = ()    # sibling gates re-run for the coupled-regression guardrail
    fitted_on: str = ""          # the data the CURRENT value was last fit on
    last_tuned: str = ""         # yyyy-mm-dd of the last promotion ("" = pre-registry / never)
    note: str = ""


# The 5 dials Session 6 migrates. `current` == the exact prior in-code literal, so the re-export moves no
# live number (equivalence-gated in check_tuner). Grids are copied verbatim from the backtests' *_GRID /
# SWEEP_HALF_LIVES — this registry is now their one home.
_DIALS = (
    Tunable(
        name="OPP_HALF_LIFE_WK", module="player_signal", current=None,
        grid=(None, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0),
        gate="backtest_player_signal", objective="MAE(expected_ppg, rest_of_season_ppg)",
        scope="nfl", coupled_gates=("backtest_player_signal",),
        fitted_on="2025",
        note="Opportunity-rate recency half-life in weeks; None = cumulative (max sample). The one "
             "center-INDEPENDENT dial — the honest first thing to re-fit OOS on the corpus split.",
    ),
    Tunable(
        name="BAND_Z", module="projection_consensus", current=0.55,
        grid=(0.5, 0.55, 0.6, 0.6745, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0, 1.1, 1.25, 1.4),
        gate="backtest_projection_consensus", objective="|coverage-0.50| + |below-0.25| + |above-0.25|",
        scope="scoring", coupled_gates=("backtest_production_vor", "backtest_true_rank"),
        fitted_on="2025",
        note="Weekly p25/p75 half-width in residual-sigma units (normal-theory 0.6745; residuals are "
             "fatter-tailed, so 0.55 once the skew term shares the load). HELD in S6: entangled with the "
             "optimistic center (L3) — a change now compensates for a bias S7 removes; revisit post-de-bias.",
    ),
    Tunable(
        name="SKEW_GAIN", module="projection_consensus", current=1.5,
        grid=(0.0, 0.5, 1.0, 1.5, 2.0),
        gate="backtest_projection_consensus", objective="|coverage-0.50| + |below-0.25| + |above-0.25|",
        scope="scoring", coupled_gates=("backtest_production_vor", "backtest_true_rank"),
        fitted_on="2025",
        note="Cornish-Fisher skew-shift multiplier on the weekly band (pure CF = 1.0). HELD in S6 "
             "(suspected overfit, expected toward 0 once the center is de-biased) — entangled with the center.",
    ),
    Tunable(
        name="BULL_Z", module="ros_player_band", current=1.44,
        grid=(0.674, 0.842, 1.036, 1.150, 1.282, 1.440, 1.645, 1.960),
        gate="backtest_ros_player_band", objective="|coverage-target| + |below-above| (freeze week)",
        scope="league", coupled_gates=("backtest_ros_player_band",),
        fitted_on="2025",
        note="ROS bull/bear half-width in sigma units, tuned jointly with ANCHOR_W to (1.44, 0.25) "
             "(freeze-week coverage 0.817). RESOLVES the recorded drift: STATUS narrated 1.645; live + "
             "snapshot are 1.44 — 1.44 is the truth, DECLARED here (not re-tuned). HELD in S6 (entangled).",
    ),
    Tunable(
        name="ANCHOR_W", module="ros_player_band", current=0.25,
        grid=(0.0, 0.25, 0.5, 0.75, 1.0),
        gate="backtest_ros_player_band", objective="|coverage-target| + |below-above| (freeze week)",
        scope="league", coupled_gates=("backtest_ros_player_band",),
        fitted_on="2025",
        note="Max preseason-anchor weight (early-season blend toward the ADP-curve prior). HELD in S6 "
             "(open OOS worry, but downstream of the center — revisit post-de-bias).",
    ),
)

REGISTRY: dict = {t.name: t for t in _DIALS}

# --- Re-exported module globals: the dials' live values. -------------------------------------------
# A module owning a dial does `from application.data.transforms._constants import BAND_Z`; THIS is the
# binding it receives. Keeping the value here (not in the module) is what makes the registry the single
# home. Each equals its exact prior in-code literal — no live number moves.
OPP_HALF_LIFE_WK = REGISTRY["OPP_HALF_LIFE_WK"].current
BAND_Z = REGISTRY["BAND_Z"].current
SKEW_GAIN = REGISTRY["SKEW_GAIN"].current
BULL_Z = REGISTRY["BULL_Z"].current
ANCHOR_W = REGISTRY["ANCHOR_W"].current


def tunable(name: str) -> Tunable:
    """The registered dial by module-global name."""
    return REGISTRY[name]


def tunables() -> tuple:
    """All registered dials, in declaration order."""
    return _DIALS
