"""scorecard_registry.py — the declared naive-baseline + confidence-signal registry for the L3 scorer.

The scorer (`compute_engine_scorecard.py`) is the first thing that judges. Two things must be DECLARED
(checked-in + gated), not improvised at score time, so the verdicts are reproducible and inspectable:

  1. **The naive baseline per claim family** — so `skill = 1 − metric_engine / metric_naive` computes the
     same way everywhere. Only two reads shipped a real baseline to *promote* (`player_signal`→`naive_ppg`,
     `bracket_odds` prob→the 0.25 coin-flip Brier — verified in the backtests); the rest are *declared*
     canonical naives, tagged so the Trust Report can say which skill numbers rest on a promoted vs a
     newly-declared reference. Where skill is the wrong lens (the interval band — its native lens is
     calibration), `skill_kind="na"`, NOT a fabricated number (Will's ruling; supersedes the brief's
     band baseline).

  2. **The confidence signal + its polarity per family** — so the confidence-honesty (law-2) test knows how
     to turn each raw signal into a monotone "more-confident-is-larger" strength. Two signals are
     monotone-but-inverted (`ros_cv`, `regression_risk` — ↑ means LESS confident); three are *extremeness*
     signals (`spectrum_pos`, `playoff_odds` — confident at the extremes, uncertain at 0.5). Using the raw
     value would be wrong — the transforms live here once.

This module DECLARES; it does not tune. It is the sibling of the 4a `constants_snapshot.py` (which
fingerprints the MODEL's constants). This registry is the SCORER's config — it rides the scorer's
`code_version` (it is checked-in code), while each scorecard row also carries the LEDGER's `constants_hash`
(which model made the claims it scored). `check_registry()` is the cross-check the gate proves bites.
"""
from application.data.corpus.predictions_map import FAMILIES, NO_CONFIDENCE_FAMILIES

SCORECARD_CONFIG_VERSION = "v2026-07-16"

# The coin-flip Brier baseline for a probability claim (a fair coin → Brier = 0.5² = 0.25). Promoted from
# backtest_bracket_sim (a literal there); named here so the gate can cross-check it against the live backtest.
COIN_FLIP_BRIER = 0.25

# Confidence-honesty tier scheme: tertiles of the per-claim confidence STRENGTH (edge-free Spearman is the
# primary verdict; the tertiles drive the reliability display + the top−bottom gap). Quantiles, not fixed
# absolute edges, because the five signals live on different scales; deterministic on the frozen corpus.
TIER_QUANTILES = (1.0 / 3.0, 2.0 / 3.0)
TIER_LABELS = ("low_conf", "mid_conf", "high_conf")

# --- The naive-baseline registry: (read, claim_type) -> {skill_kind, baseline, provenance, desc} ---
# skill_kind ∈ {mae, brier, accuracy, na}. `na` = skill is not the honest lens (the band → calibration).
NAIVE_BASELINES: dict[tuple, dict] = {
    ("production_vor", "point"): {
        "skill_kind": "mae", "baseline": "recent_ppg_forward", "provenance": "declared",
        "desc": "carry recent form forward: mean(pts | wk ≤ as_of) × #realized forward weeks (≥ as_of)"},
    ("ros_player_band", "interval"): {
        "skill_kind": "na", "baseline": None, "provenance": "na",
        "desc": "skill n/a by design — the band's native lens is CALIBRATION (PIT/coverage), not center-MAE; "
                "grading its center as a point read is the anti-law-2 move"},
    ("player_signal", "point"): {
        "skill_kind": "mae", "baseline": "naive_ppg", "provenance": "promoted",
        "desc": "equal-weight cumulative recent ppg carried forward (backtest_player_signal's naive_ppg)"},
    ("player_signal", "direction"): {
        "skill_kind": "accuracy", "baseline": "base_rate", "provenance": "declared",
        "desc": "majority realized-direction class; skill = (accuracy − base_rate) / (1 − base_rate)"},
    ("true_rank", "ordinal"): {
        "skill_kind": "mae", "baseline": "random_permutation", "provenance": "declared",
        "desc": "closed-form E|rank_error| under a uniform permutation of n seats = (n²−1)/(3n) — no RNG"},
    ("positional_depth", "point"): {
        "skill_kind": "mae", "baseline": "pool_mean", "provenance": "declared",
        "desc": "pool-mean realized roster×position pts over the clean subset; ★ APPROXIMATE answer key — "
                "coverage-flagged, skill on the clean subset only"},
    ("bracket_odds", "probability"): {
        "skill_kind": "brier", "baseline": "coin_flip_0.25", "provenance": "promoted",
        "desc": "0.25 coin-flip Brier baseline (backtest_bracket_sim); skill = 1 − Brier_engine / 0.25"},
    ("bracket_odds", "point"): {
        "skill_kind": "mae", "baseline": "pool_mean_wins", "provenance": "declared",
        "desc": "pool-mean realized wins per league — the 0.5-winrate coin-flip season on a balanced schedule"},
    ("bracket_odds", "ordinal"): {
        "skill_kind": "mae", "baseline": "random_permutation", "provenance": "declared",
        "desc": "closed-form E|seed_error| under a uniform permutation of n seats = (n²−1)/(3n) — no RNG"},
}

# --- The confidence-signal registry: (read, claim_type) -> {signal, strength, primitive, label} ---
# strength: how to turn the raw signal into a monotone "more-confident-is-larger" conf_strength.
#   "neg"        → conf_strength = −signal          (signal ↑ means LESS confident)
#   "extremeness"→ conf_strength = |signal − 0.5|   (confident at the extremes, uncertain at 0.5)
# primitive: the realized error the honesty test stratifies (the band uses abs_error, NOT pit — pit is the
#   calibration verdict; ros_cv claims to rank FRAGILITY, so honesty = "fragile bands miss by more").
CONF_SIGNALS: dict[tuple, dict] = {
    ("ros_player_band", "interval"): {
        "signal": "ros_cv", "strength": "neg", "primitive": "abs_error", "label": "ros_cv"},
    ("player_signal", "point"): {
        "signal": "regression_risk", "strength": "neg", "primitive": "abs_error", "label": "regression_risk"},
    ("true_rank", "ordinal"): {
        "signal": "spectrum_pos", "strength": "extremeness", "primitive": "rank_abs_error", "label": "spectrum_pos"},
    ("positional_depth", "point"): {
        "signal": "spectrum_pos", "strength": "extremeness", "primitive": "abs_error", "label": "spectrum_pos"},
    ("bracket_odds", "probability"): {
        "signal": "playoff_odds", "strength": "extremeness", "primitive": "brier", "label": "playoff_odds"},
}


def random_perm_mae(n: int) -> float | None:
    """E|X − Y| for X, Y i.i.d. uniform on {1..n} — the expected absolute rank error of a uniformly random
    permutation, in CLOSED FORM `(n²−1)/(3n)`. The no-skill baseline for an ordinal claim; a function of the
    seat count only (no RNG, no seeded shuffle) so it is exactly reproducible and cannot drift."""
    if n is None or n < 2:
        return None
    return (n * n - 1) / (3.0 * n)


def families() -> list[tuple]:
    """The 9 (read, claim_type) families, from the 4a predictions registry (the single source of truth)."""
    return [(f["read"], f["claim_type"]) for f in FAMILIES]


def check_registry() -> dict:
    """Cross-check the declared registry against the 4a claim registry — the gate's baseline-registry guard.

    Returns `{ok, problems}`. `ok=False` (⇒ gate red) when: a family is missing / extra vs the 9 claim
    families; a `skill_kind` is invalid; the promoted baselines disagree with the live backtest constants;
    the `na` family is not exactly the interval band; or the confidence-signal set does not match the 4a
    5-measurable / 4-flagged split. Prove-bite: mutate any entry (drop a family, flip a skill_kind, change
    COIN_FLIP_BRIER) and this reddens."""
    problems = []
    fam = set(families())

    # 1 — the naive registry covers exactly the 9 families
    if set(NAIVE_BASELINES) != fam:
        problems.append(f"NAIVE_BASELINES family set != claim families: "
                        f"missing={fam - set(NAIVE_BASELINES)} extra={set(NAIVE_BASELINES) - fam}")
    # 2 — valid skill_kind everywhere
    for k, spec in NAIVE_BASELINES.items():
        if spec["skill_kind"] not in {"mae", "brier", "accuracy", "na"}:
            problems.append(f"{k}: invalid skill_kind {spec['skill_kind']!r}")
    # 3 — na is exactly the interval band
    na_fams = {k for k, s in NAIVE_BASELINES.items() if s["skill_kind"] == "na"}
    if na_fams != {("ros_player_band", "interval")}:
        problems.append(f"skill_kind='na' families {na_fams} != {{('ros_player_band','interval')}}")
    # 4 — promoted baselines match the live backtests (the checked-in-and-gated discipline)
    try:
        from application.data.transforms import backtest_bracket_sim as _bbs
        # the sim gate beats 0.25 − BRIER_MARGIN, so the coin-flip baseline it references is 0.25
        if COIN_FLIP_BRIER != 0.25 or (0.25 - _bbs.BRIER_MARGIN) >= 0.25:
            problems.append(f"COIN_FLIP_BRIER {COIN_FLIP_BRIER} disagrees with backtest_bracket_sim baseline 0.25")
    except Exception as e:                                          # noqa: BLE001
        problems.append(f"could not cross-check backtest_bracket_sim baseline: {e}")
    if NAIVE_BASELINES[("player_signal", "point")]["baseline"] != "naive_ppg":
        problems.append("player_signal/point promoted baseline must be 'naive_ppg'")
    # 5 — the confidence registry matches the 4a 5-measurable / 4-flagged split
    conf_fam = set(CONF_SIGNALS)
    flagged = {(r, c) for (r, c) in NO_CONFIDENCE_FAMILIES}
    if conf_fam & flagged:
        problems.append(f"CONF_SIGNALS overlaps the no-confidence flag set: {conf_fam & flagged}")
    if conf_fam | flagged != fam:
        problems.append(f"confidence-measurable ∪ flagged ({len(conf_fam)}+{len(flagged)}) != 9 families")
    for k, spec in CONF_SIGNALS.items():
        if spec["strength"] not in {"neg", "extremeness"}:
            problems.append(f"{k}: invalid strength transform {spec['strength']!r}")

    return {"ok": not problems, "problems": problems}
