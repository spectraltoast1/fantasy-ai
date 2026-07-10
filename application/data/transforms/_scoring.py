"""Scoring dispatcher — route the league's scoring to the right points source.

The `projections` entity is league-agnostic: it stores the generic canned columns Sleeper/RotoWire
computes (`proj_pts_ppr`/`proj_pts_half`/`proj_pts_std`) plus the component stats. This module is the
seam that turns "the league's `scoring_settings`" into "which points to use" — applied at the
consumption layer (compute_projection_consensus) so the same projections serve any league.

Two paths (open/closed):
  - **Standard** (PPR / half-PPR / standard) — the scoring the canned columns already express. Selected
    by `rec` ∈ {1.0, 0.5, 0.0} with the other shape-defining offensive keys at their standard values.
    We just pick the matching canned projection column and the matching nfl_stats actual column.
  - **Custom** — anything the canned columns can't express (6-pt pass TD, TE-premium / other reception
    bonuses, non-{0,.5,1} PPR, non-standard yardage/TD rates). Recomputed by the **delta engine** below.

The custom scoring engine (the "any-league" project's first piece): it does **not** rebuild points from
scratch — RotoWire's `proj_pts_ppr` bakes in contributions the exposed components don't carry (projected
turnovers, minor bonuses), so a from-scratch sum misses them by up to ~2 pts. Instead it takes the
**standard canned baseline** (`proj_pts_std` / `fantasy_points`) and adds, per component, only the
*delta* between the league's weight and the standard weight:

    points_league = std_baseline + Σ_k (w_custom[k] − w_std[k]) · component_k

This is **exact for a standard league by construction** (all deltas 0 ⇒ points = the std column), robust
to whatever the vendor baked into the baseline, and only touches the components that actually changed.

**What the engine supports vs. rejects (law 2 — speak only when confident).** A term is supported iff its
component is present in the *projections* (so the projection center and the actual can be scored the same
way, keeping residuals matched):
  - **Supported:** any `rec` value (PPR variants), any `pass_td`/`rush_td`/`rec_td` (incl. 6-pt pass TD),
    any `pass_yd`/`rush_yd`/`rec_yd` rate, and position-conditional reception bonuses
    (`bonus_rec_te`/`_rb`/`_wr`/`_qb` = TE premium etc.), applied as `bonus · receptions` gated on position.
  - **Rejected (raises, never silently mis-scores):** first-down bonuses (`pass_fd`/`rush_fd`/`rec_fd`) and
    threshold/milestone yardage or other reception/rush/pass bonuses (`bonus_rush_yd_100`, …) — the
    projections carry no component for them, so we can't score the projection center faithfully. These
    unlock when a projection source that carries the component lands (ffanalytics/FantasyPros, in-season).

Scope: skill-position offense only (V1). DST/K/IDP scoring keys are ignored — they don't affect
QB/RB/WR/TE points. Turnover penalties (`pass_int`, `fum_lost`) and 2-pt conversions are treated as
within the std baseline's tolerance (they sit in the baseline at the standard rate on both sides; the
projections carry no component to adjust them, and they move skill scoring only marginally), so they
don't force the custom path and are carried, unadjusted, through the baseline.
"""

import polars as pl

# The standard offensive scoring the canned pts_ppr/half/std columns represent (rec handled separately).
_STANDARD = {
    "pass_yd": 0.04, "pass_td": 4.0,
    "rush_yd": 0.1, "rush_td": 6.0,
    "rec_yd": 0.1, "rec_td": 6.0,
}
_REC_TO_PROFILE = {1.0: "ppr", 0.5: "half", 0.0: "std"}
_TOL = 1e-9

# --- Custom-scoring recompute engine ---------------------------------------------------------------

# Delta baseline weights: the std canned column embeds these, so a custom weight contributes only its
# difference from here. `rec` is 0.0 in the std baseline (std = no PPR), so a PPR value adds as a full
# delta — reconstructing the ppr/half columns exactly (ppr − std == 1·receptions; half == +0.5·rec).
_STD_WEIGHTS = {**_STANDARD, "rec": 0.0}

# Each supported linear component → (projections column, nfl_stats column). Same weight applied to both
# sides so the projection center and the realized actual are scored identically (residuals stay matched).
_COMPONENT_COLS = {
    "pass_yd": ("proj_pass_yd", "passing_yards"),
    "pass_td": ("proj_pass_td", "passing_tds"),
    "rush_yd": ("proj_rush_yd", "rushing_yards"),
    "rush_td": ("proj_rush_td", "rushing_tds"),
    "rec_yd": ("proj_rec_yd", "receiving_yards"),
    "rec_td": ("proj_rec_td", "receiving_tds"),
    "rec": ("proj_rec", "receptions"),
}
_BASELINE_COL = {"proj": "proj_pts_std", "actual": "fantasy_points"}

# Position-conditional per-reception bonuses (Sleeper keys). Score as `bonus · receptions` for the mapped
# position only — the TE-premium family. Multiplies the same `rec` component as PPR.
_REC_BONUS_POS = {
    "bonus_rec_qb": "QB",
    "bonus_rec_rb": "RB",
    "bonus_rec_wr": "WR",
    "bonus_rec_te": "TE",
}

# Skill-offense keys with no projection component → the custom path can't score the projection center for
# them, so it raises rather than silently dropping their value from the read.
_FIRST_DOWN_KEYS = {"pass_fd", "rush_fd", "rec_fd"}


def _nonzero(v) -> bool:
    return v is not None and abs(float(v)) > _TOL


def scoring_profile(scoring: dict) -> str:
    """Classify the league's scoring as "ppr" | "half" | "std" | "custom".

    Standard iff `rec` ∈ {1, .5, 0}, every shape-defining offensive key matches `_STANDARD`, and no
    skill-scoring bonus / first-down key is active. Anything else → "custom" (the canned columns can't
    express it, so the points are recomputed from components by the delta engine)."""
    rec = scoring.get("rec", 0.0)
    if rec not in _REC_TO_PROFILE:
        return "custom"
    for key, std in _STANDARD.items():
        if abs(float(scoring.get(key, std)) - std) > _TOL:
            return "custom"
    for key, value in scoring.items():
        # Offensive reception/rush/pass bonuses (incl. TE premium = bonus_rec_te) and first-down
        # points reshape skill value in ways the canned columns don't carry.
        if key.startswith(("bonus_rec", "bonus_rush", "bonus_pass")) and _nonzero(value):
            return "custom"
        if key.endswith("_fd") and _nonzero(value):  # pass_fd / rush_fd / rec_fd
            return "custom"
    return _REC_TO_PROFILE[rec]


def _reject_unsupported(scoring: dict) -> None:
    """Raise if the league has an active skill-scoring key the projections can't score a center for."""
    bad = []
    for key, value in scoring.items():
        if not _nonzero(value):
            continue
        if key in _FIRST_DOWN_KEYS:
            bad.append(key)
        elif key.startswith(("bonus_pass", "bonus_rush", "bonus_rec")) and key not in _REC_BONUS_POS:
            bad.append(key)
    if bad:
        raise NotImplementedError(
            "Custom scoring uses key(s) the projection substrate can't score: "
            f"{sorted(bad)}. First-down bonuses and threshold/yardage bonuses have no component in the "
            "Sleeper/RotoWire projections, so the projected center can't be computed faithfully — the "
            "read would be silently wrong. Supported custom scoring today: non-{0,.5,1} PPR, non-standard "
            "TD/yardage values, and position-conditional reception bonuses (TE premium). These keys unlock "
            "when an in-season projection source carrying the component lands (ffanalytics/FantasyPros)."
        )


def recompute_custom_points(scoring: dict, side: str) -> pl.Expr:
    """The custom scoring engine: a polars Expr for a player's league-scored points, as a delta on the
    standard canned baseline (see the module docstring). `side` ∈ {"proj", "actual"} selects the
    projections vs. nfl_stats component columns. Raises on unsupported keys (`_reject_unsupported`).

    points_league = <std baseline column> + Σ_k (w_custom[k] − w_std[k]) · component_k[side]
                    + Σ_pos bonus_rec_<pos> · receptions[side]  (gated on position == <pos>)
    """
    if side not in ("proj", "actual"):
        raise ValueError(f"side must be 'proj' or 'actual', got {side!r}")
    _reject_unsupported(scoring)

    idx = 0 if side == "proj" else 1
    terms: list[pl.Expr] = []
    for key, cols in _COMPONENT_COLS.items():
        delta = float(scoring.get(key, _STD_WEIGHTS[key])) - _STD_WEIGHTS[key]
        if abs(delta) > _TOL:
            terms.append(delta * pl.col(cols[idx]).fill_null(0.0))
    rec_col = _COMPONENT_COLS["rec"][idx]
    for key, pos in _REC_BONUS_POS.items():
        bonus = float(scoring.get(key, 0.0))
        if _nonzero(bonus):
            terms.append(
                pl.when(pl.col("position") == pos)
                .then(bonus * pl.col(rec_col).fill_null(0.0))
                .otherwise(0.0)
            )

    baseline = pl.col(_BASELINE_COL[side])
    if not terms:
        return baseline
    delta_sum = terms[0]
    for t in terms[1:]:
        delta_sum = delta_sum + t
    return baseline + delta_sum


def projection_points_expr(profile: str, scoring: dict) -> pl.Expr:
    """The projections Expr carrying the league's projected points. Standard → the canned column;
    custom → the delta engine on the `proj_pts_std` baseline."""
    if profile == "custom":
        return recompute_custom_points(scoring, "proj")
    return pl.col({"ppr": "proj_pts_ppr", "half": "proj_pts_half", "std": "proj_pts_std"}[profile])


def actual_points_expr(profile: str, scoring: dict) -> pl.Expr:
    """The nfl_stats Expr for a player's actual points under the league scoring. nfl_stats carries
    `fantasy_points_ppr` (PPR) and `fantasy_points` (standard); half-PPR is their mean (half-PPR = std +
    0.5·receptions = the midpoint of std and full PPR). Custom → the delta engine on `fantasy_points`."""
    if profile == "custom":
        return recompute_custom_points(scoring, "actual")
    if profile == "ppr":
        return pl.col("fantasy_points_ppr")
    if profile == "std":
        return pl.col("fantasy_points")
    return (pl.col("fantasy_points_ppr") + pl.col("fantasy_points")) / 2.0  # half
