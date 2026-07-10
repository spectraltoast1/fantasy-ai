"""Scoring dispatcher — route the league's scoring to the right points source.

The `projections` entity is league-agnostic: it stores the generic canned columns Sleeper/RotoWire
computes (`proj_pts_ppr`/`proj_pts_half`/`proj_pts_std`) plus the component stats. This module is the
seam that turns "the league's `scoring_settings`" into "which points to use" — applied at the
consumption layer (compute_projection_consensus) so the same projections can serve any league.

Two paths (open/closed):
  - **Standard** (PPR / half-PPR / standard) — the scoring the canned columns already express. Selected
    by `rec` ∈ {1.0, 0.5, 0.0} with the other shape-defining offensive keys at their standard values.
    We just pick the matching canned projection column and the matching nfl_stats actual column. Built.
  - **Custom** — anything the canned columns can't express (6-pt pass TD, TE-premium / other reception
    bonuses, non-{0,.5,1} PPR, yardage/first-down bonuses). Routes to `recompute_custom_points`, a
    defined interface that is **not built yet** and raises. When the custom scoring engine lands, only
    that function's body fills in — this dispatcher and every call site stay unchanged.

Scope: skill-position offense only (V1). DST/K/IDP scoring keys are ignored — they don't affect
QB/RB/WR/TE points. Turnover penalties (`pass_int`, `fum_lost`) are treated as within the canned
column's tolerance (they vary league-to-league by a point and move skill scoring only marginally), so
they don't by themselves force the custom path — only the *shape-defining* keys below do.
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


def _nonzero(v) -> bool:
    return v is not None and abs(float(v)) > _TOL


def scoring_profile(scoring: dict) -> str:
    """Classify the league's scoring as "ppr" | "half" | "std" | "custom".

    Standard iff `rec` ∈ {1, .5, 0}, every shape-defining offensive key matches `_STANDARD`, and no
    skill-scoring bonus / first-down key is active. Anything else → "custom" (the canned columns can't
    express it, so the points must be recomputed from components)."""
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


def projection_column(profile: str) -> str:
    """The `projections` column carrying the league's projected points for a standard profile."""
    if profile == "custom":
        recompute_custom_points(None, None)  # raises — custom points aren't a canned column
    return {"ppr": "proj_pts_ppr", "half": "proj_pts_half", "std": "proj_pts_std"}[profile]


def actual_points_expr(profile: str) -> pl.Expr:
    """The nfl_stats expression for a player's actual points under a standard profile. nfl_stats
    carries `fantasy_points_ppr` (PPR) and `fantasy_points` (standard); half-PPR is their mean
    (half-PPR = std + 0.5·receptions = the midpoint of std and full PPR)."""
    if profile == "custom":
        recompute_custom_points(None, None)  # raises
    if profile == "ppr":
        return pl.col("fantasy_points_ppr")
    if profile == "std":
        return pl.col("fantasy_points")
    return (pl.col("fantasy_points_ppr") + pl.col("fantasy_points")) / 2.0  # half


def recompute_custom_points(components, scoring: dict):
    """Recompute points from component stats under an arbitrary `scoring_settings` — the custom
    scoring engine. **Not built yet** (deliberately stubbed): standard leagues never reach here, and
    custom-scoring support is the first piece of the 'any league' project. When built, this takes a
    per-player component frame (proj_* for projections, the nfl_stats stat columns for actuals) plus
    `scoring`, and returns league-scored points; the dispatcher and its call sites don't change.
    """
    raise NotImplementedError(
        "Custom scoring detected — the recompute-from-components engine is not built yet. "
        "This league's scoring_settings can't be expressed by the canned PPR/half/std columns "
        "(non-standard reception/TD values, a positional bonus, or first-down scoring). "
        "Standard PPR/half/std leagues are supported today; custom scoring is the next project."
    )
