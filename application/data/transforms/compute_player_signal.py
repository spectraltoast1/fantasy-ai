"""
Compute the per-player spike signal-quality read from the weekly join.

The first decision-critique engine slice (Product Roadmap Phase 1). It answers the
recurring manager question behind waivers, start/sit, and streaming: **"is this
production real, or is it noise?"** — without any forward projection. It is a
*characterization of past production*, not a points forecast (design law 3: borrow
the substrate, don't build a projection engine).

The read rests on a well-established asymmetry: a player's **opportunity** (targets,
carries, snaps — volume) is sticky week to week, while his **efficiency** (points per
opportunity: yards-per-touch and especially TD rate) regresses hard toward the
positional norm. So recent production is decomposed:

  - opportunity per game (`opp_g`) — the repeatable, volume-driven part, carried
    forward as the anchor.
  - points per opportunity (`ppo`) — the fragile part, shrunk toward the league-wide
    positional mean by sample size (a player with few games gets pulled harder toward
    the norm; SHRINK_K games of "prior" weight). (Shrinking toward the player's own
    model-expected efficiency was tested and lost to the positional mean on the answer
    key — see `_player_signal`; the model feeds the §1 Quality axis, not this forecast.)

`expected_ppg = opp_g * shrunk_ppo` is the volume-anchored, efficiency-regressed
estimate. The headline is **regression_risk = 1 - expected_ppg / recent_ppg**: the
fraction of recent scoring that the sustainable-usage picture does NOT support
(positive = spike-prone; ~0 = usage-backed; negative = usage suggests room to rise).
A categorical `read` (too_early / spike / mixed / sticky) gates the language on
sample size (design law 2: speak only when confident), and `td_share` is carried as
the most legible evidence ("a third of these points were touchdowns").

The decomposition was validated against the full-2025 answer key — see
backtest_player_signal.py. It beats a naive "recent points carry forward" baseline on
rest-of-season error AND, among hot players (which the naive read cannot tell apart),
correctly separates the group that held from the group that regressed ~3 pts/g.

**Phase 1 refinement (DECISION_READS.md §1):** these fields close the gap between this
shipped engine and the full Opportunity spec — kept separate, not fused into the
core read above, per "don't collapse the axes; divergence is the signal":
  - `quality_rate` — the Quality axis: **expected fantasy points per opportunity**, from
    ffverse's empirical expected-points model (`ff_opportunity`), re-scored under the
    league's settings (`_scoring.expected_points_expr`). It weights each chance by the
    value its context (target depth, field position, down & distance) empirically
    produces — the full multi-component EV read §1 specifies, not the old TD-only
    `td_prob` proxy. Independent of Volume (`opp_g`): a 3rd-down back can be
    high-quality/low-volume, and that divergence is the signal.
  - `direction` / `reliability` — the Trust axis's trend + consistency, from the
    player's own weekly opportunity series (a weighted-least-squares slope fit).
  - `security` — the Trust axis's context flag, from Sleeper injury/depth-chart status.
  - `point_correlation` — the companion: how tightly a player's weekly **actual** points
    track his weekly **expected** points. Read against `quality_rate`: low correlation +
    high quality = unlucky (bounce-back); low correlation + low quality = correctly cheap.
  - `luck` — the legible residual: recent PPG minus expected PPG (points/game above or
    below what the chances were worth). Positive = running hot; negative = bounce-back.

Output: snapshots/derived/player_signal_{season}.parquet, one row per rostered skill
player.

Usage:
    python3 -m application.data.transforms.compute_player_signal --season 2025
"""

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, pearson, round1, spectrum_positions
from application.data.transforms._scoring import (
    EXP_COMPONENT_COLS, actual_points_expr, expected_points_expr, scoring_profile,
)
# OPP_HALF_LIFE_WK (opportunity-rate recency half-life; None = cumulative) is a swept dial, homed in the
# L4 dials registry and re-exported here so `player_signal.OPP_HALF_LIFE_WK` and every importer resolve.
# Every OTHER constant below (SHRINK_K, MIN_GAMES, POS_MEAN_MIN_OPP, SPIKE/STICKY_BAND, DIRECTION_*) is a
# pin, not a dial — it stays defined in this module.
from application.data.transforms._constants import OPP_HALF_LIFE_WK  # noqa: F401  (re-exported dial)

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Shrinkage weight (in "games of prior") pulling a player's points-per-opportunity
# toward the league positional mean: shrunk = (g·ppo + K·mean) / (g + K). Tuned on the
# 2025 backtest — rest-of-season error is flat-bottomed across K≈4–12, so the choice is
# robust, not knife-edge. At the 4-game freeze a player's own efficiency and the league
# norm get roughly equal weight.
SHRINK_K = 6
# Below this many games a per-game read is too thin to characterise; the player is
# flagged low-sample and the read is held at "too_early" (law 2: speak only when sure).
MIN_GAMES = 3
# A player needs at least this much opportunity per game to anchor the league
# positional efficiency mean — pure zero-volume rows would bias the norm downward.
POS_MEAN_MIN_OPP = 3.0
# Read bands on regression_risk. Above SPIKE_BAND the production is meaningfully
# unsupported by usage (cool-off likely); below STICKY_BAND it is usage-backed; the
# middle is genuinely mixed and should be framed as such, not as a confident call.
SPIKE_BAND = 0.15
STICKY_BAND = 0.05
# Opportunity windowing (Season-replay Part 2): the per-game rates (opportunity, ppg, TD ppg) are read
# off a player's recent weeks through an injected EWMA half-life (each week's weight halves every
# OPP_HALF_LIFE_WK weeks back; None = cumulative). It ships cumulative — the 2025 sweep found short
# half-lives hurt rest-of-season MAE monotonically. OPP_HALF_LIFE_WK is a swept dial, homed in
# _constants.py and re-exported at the top of this module; the tuner re-fits it OOS on the corpus split.

# --- Trust axis (DECISION_READS.md §1 refinement) ---
# Direction's own recency weighting for the slope fit itself — separate from
# OPP_HALF_LIFE_WK (which weights the opp_g *rate*, validated cumulative). Recent
# weeks matter more when fitting "is this trending," independent of how the
# point-estimate rate is windowed.
DIRECTION_HALF_LIFE_WK = 2
# A slope within ±DIRECTION_BAND of the player's own average opportunity reads
# "steady" — a small wobble stays flat rather than reading as a trend.
DIRECTION_BAND = 0.04
# Sleeper injury_status values that flag real risk to the opportunity continuing.
# "Questionable" is treated as its own softer tier, not lumped in here.
SECURITY_FLAGGED_STATUSES = {"Out", "Doubtful", "IR", "PUP", "Sus", "NA"}


def opportunity_expr() -> pl.Expr:
    """Position-specific opportunity (per row): the volume a player commands, which is
    the sticky half of fantasy production. WR/TE → targets; RB → carries + targets
    (dual-threat backs earn through the air too); QB → pass attempts + carries. Shared
    by the production transform and the backtest so both score on the same definition.
    """
    return (
        pl.when(pl.col("position").is_in(["WR", "TE"]))
        .then(pl.col("targets"))
        .when(pl.col("position") == "RB")
        .then(pl.col("carries") + pl.col("targets"))
        .otherwise(pl.col("attempts") + pl.col("carries"))  # QB
    )


def _weighted_rates(weeks, *, half_life):
    """EWMA-weighted per-game rates from a player's per-week series.

    `weeks`: list of {week, pts, opp, td_pts, exp_pts} (any order; `exp_pts` optional,
    defaults to 0.0 — keeps this function callable on older-shaped week dicts). Each week's
    weight halves every `half_life` weeks back from the player's most recent game, so a
    drifting role is read off recent usage without discarding older games — a
    half-life, not a hard window. `half_life=None` → equal weight (cumulative). The
    half-life is injected (not a module global) so the analytic is parameterisable and
    testable in isolation: the backtest sweeps it through this same function.

    Returns {games, ppg, opp_g, td_ppg, exp_pts_g}. `games` is the raw count — sample size
    for the low-sample gate, which is about confidence, not recency, so it is never
    weighted. The weights are normalised, so only their *relative* size within the
    player's own games matters (a player whose games are all old is not down-levelled —
    a per-game rate is a per-game rate; staleness is the sample gate's job, not the
    rate's).
    """
    ws = sorted(weeks, key=lambda w: w["week"])
    n = len(ws)
    if half_life is None or n <= 1:
        wts = [1.0] * n
    else:
        last = ws[-1]["week"]
        decay = 0.5 ** (1.0 / half_life)
        wts = [decay ** (last - w["week"]) for w in ws]
    tw = sum(wts) or 1.0
    return {
        "games": n,
        "ppg": sum(wt * w["pts"] for wt, w in zip(wts, ws)) / tw,
        "opp_g": sum(wt * w["opp"] for wt, w in zip(wts, ws)) / tw,
        "td_ppg": sum(wt * w["td_pts"] for wt, w in zip(wts, ws)) / tw,
        "exp_pts_g": sum(wt * w.get("exp_pts", 0.0) for wt, w in zip(wts, ws)) / tw,
    }


def _player_signal(agg, pos_mean_ppo, *, shrink_k, min_games, spike_band, sticky_band):
    """The pure signal read for one player from his recent-window aggregate.

    `agg`: {position, games, ppg, opp_g, td_ppg, exp_pts_g}. `pos_mean_ppo`: the league-wide
    mean points-per-opportunity for this player's position. The tuning constants are
    injected (not read from module globals) so the analytic is parameterisable and
    testable in isolation — the backtest sweeps `shrink_k` through this same function.

    Returns the decomposition: expected (efficiency-regressed) ppg, regression_risk, the
    TD share of scoring, a sample-gated categorical read, `quality_rate` — the Quality axis
    (DECISION_READS.md §1): **expected fantasy points per opportunity** from ffverse's
    empirical model, re-scored under league settings (`exp_pts_g` is the per-game expected
    points; dividing by `opp_g` gives the value per chance), independent of how many touches
    he gets — a 3rd-down back can be high-quality_rate, low-opp_g, and that divergence is the
    signal — and `luck` = recent ppg minus expected ppg (the legible over/under-performance
    residual).
    """
    games = agg["games"]
    ppg = agg["ppg"]
    opp_g = agg["opp_g"]
    td_ppg = agg["td_ppg"]
    exp_pts_g = agg.get("exp_pts_g", 0.0)

    low_sample = games < min_games or opp_g <= 0.0
    quality_rate = exp_pts_g / opp_g if opp_g > 0 else 0.0  # exp_ppo: the model's expected efficiency
    luck = ppg - exp_pts_g  # observed minus expected points per game (variance/luck residual)
    ppo = ppg / opp_g if opp_g > 0 else 0.0
    # Shrink realized efficiency toward the league positional mean by sample size; opportunity is the
    # anchor and is carried forward as-is (the sticky half). **The 710 #3 upgrade to shrink toward the
    # player's own model-expected efficiency (exp_ppo) was tested and REJECTED by the answer key** —
    # it lost to the positional mean at every SHRINK_K (K=6: MAE 2.699 vs 2.599). Forecasting efficiency
    # is regression toward the *population*; exp_ppo (built on the same recent weeks) is too correlated
    # with realized ppo to supply that pull. So the model serves the §1 Quality axis (quality_rate /
    # luck / point_correlation), not the core forecast — validate the bet, don't assume it.
    shrunk_ppo = (games * ppo + shrink_k * pos_mean_ppo) / (games + shrink_k)
    expected_ppg = opp_g * shrunk_ppo
    regression_risk = 1.0 - expected_ppg / ppg if ppg > 0 else 0.0
    td_share = td_ppg / ppg if ppg > 0 else 0.0

    if low_sample:
        read = "too_early"
    elif regression_risk >= spike_band:
        read = "spike"
    elif regression_risk <= sticky_band:
        read = "sticky"
    else:
        read = "mixed"

    return {
        "games": games,
        "low_sample": low_sample,
        "recent_ppg": round1(ppg),
        "opp_g": round1(opp_g),
        "td_ppg": round1(td_ppg),
        "td_share": round(td_share, 3),
        "ppo": round(ppo, 3),
        "pos_mean_ppo": round(pos_mean_ppo, 3),
        "eff_ratio": round(ppo / pos_mean_ppo, 3) if pos_mean_ppo > 0 else 0.0,
        "expected_ppg": round1(expected_ppg),
        "regression_risk": round(regression_risk, 3),
        "read": read,
        "quality_rate": round(quality_rate, 3),
        "luck": round1(luck),
    }


def td_points_expr() -> pl.Expr:
    """Fantasy points from touchdowns (per row): rushing + receiving at 6, passing at 4.
    The most legible evidence in the read, carried per week so it can be recency-weighted
    on the same EWMA path as opportunity."""
    return (pl.col("rushing_tds") + pl.col("receiving_tds")) * 6 + pl.col("passing_tds") * 4


def _direction(series, *, half_life, band) -> str:
    """Trend of a player's own opportunity across his recent weeks — the Trust axis's
    "direction" (DECISION_READS.md §1): is his role growing, shrinking, or steady?
    A weighted-least-squares slope + band-thresholding at player grain, fit on `opp`
    instead of points. `series`: list of {week, opp, ...},
    any order. Fewer than 2 games reads "steady" — nothing to fit a trend to.
    """
    ws = sorted(series, key=lambda w: w["week"])
    n = len(ws)
    if n < 2:
        return "steady"
    opp = [w["opp"] for w in ws]
    decay = 0.5 ** (1.0 / half_life)
    wts = [decay ** (n - 1 - i) for i in range(n)]
    W = sum(wts)
    mx = sum(wt * i for i, wt in enumerate(wts)) / W
    my = sum(wt * opp[i] for i, wt in enumerate(wts)) / W
    num = sum(wts[i] * (i - mx) * (opp[i] - my) for i in range(n))
    den = sum(wts[i] * (i - mx) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    avg = mean(opp)
    rel = slope / avg if avg else 0.0
    return "rising" if rel > band else "fading" if rel < -band else "steady"


def _reliability(series, *, min_games):
    """0–1 read on how consistent a player's opportunity has been week to week — the
    Trust axis's "reliability" (DECISION_READS.md §1). From the coefficient of variation
    (std/mean) of his weekly opportunity: `reliability = 1 / (1 + cv)`, so a perfectly
    steady role reads 1.0 and a wildly swinging one approaches 0. None below
    `min_games` — a CV from one or two games measures noise, not consistency.
    """
    if len(series) < min_games:
        return None
    opp = [w["opp"] for w in series]
    m = mean(opp)
    if m <= 0:
        return None
    var = sum((o - m) ** 2 for o in opp) / len(opp)
    cv = (var ** 0.5) / m
    return round(1.0 / (1.0 + cv), 3)


def _point_correlation(series, *, min_games):
    """Correlation between a player's weekly **actual** fantasy points and his weekly
    **expected** points (`exp_pts`, the Quality signal re-scored under league settings) —
    the point-correlation companion (DECISION_READS.md §1): do his valuable chances
    actually convert? Read against `quality_rate`: low correlation + high quality_rate =
    unlucky, a bounce-back candidate (the valuable chances are there, they just haven't
    hit yet); low correlation + low quality_rate = correctly cheap (no hidden upside
    either way). None below `min_games`, or when either series has no variance to
    correlate against.
    """
    if len(series) < min_games:
        return None
    pts = [w["pts"] for w in series]
    exp = [w["exp_pts"] for w in series]
    r = pearson(exp, pts)
    return round(r, 3) if r is not None else None


def _security(injury_status, depth_chart_order) -> str:
    """Categorical read off Sleeper roster context — the Trust axis's "security"
    (DECISION_READS.md §1): is the ground under this opportunity solid? A context flag,
    not a trend, so it stays a separate field rather than blending into
    direction/reliability. Approximation, not the full spec: real security also wants
    coaching/scheme-change and the competition's draft capital, which aren't in the
    data layer yet — this is the slice buildable from what Sleeper's /players/nfl
    endpoint already returns. `depth_chart_order > 1` is a soft signal only (WR/TE rooms
    routinely start more than one), so it reads as the milder "depth_chart_risk" tier,
    not "flagged".
    """
    if injury_status in SECURITY_FLAGGED_STATUSES:
        return "flagged"
    if injury_status == "Questionable":
        return "questionable"
    if depth_chart_order is not None and depth_chart_order > 1:
        return "depth_chart_risk"
    return "stable"


def _recent_aggregate(df: pl.DataFrame) -> pl.DataFrame:
    """Collapse per-week skill rows to one per-player record: the raw game count and the
    per-week (pts, opp, td_pts, exp_pts) series. The per-game rates (ppg, opp_g, td_ppg,
    exp_pts_g) are derived from this series by `_weighted_rates` (EWMA half-life), so the
    windowing choice lives in one injected-parameter place rather than baked into the
    aggregation — and the same series drives the evidence sparkline and the Quality/Trust/
    point-correlation reads. `exp_pts` is the league-scored expected points (computed on the
    frame before this call), so the series carries expected alongside actual per week."""
    return (
        df.with_columns(opportunity_expr().alias("opp"), td_points_expr().alias("td_pts"))
        .group_by("sleeper_player_id", "player_display_name", "position")
        .agg(
            pl.len().alias("games"),
            pl.struct(
                "week", pl.col("fantasy_points_ppr").alias("pts"), "opp", "td_pts", "exp_pts"
            )
            .sort_by("week")
            .alias("weeks"),
        )
    )


def positional_mean_ppo(season: int, weeks, *, scoring=None) -> dict:
    """League-wide mean points-per-opportunity per position, from the full NFL stat pool
    (not just this league's rostered players) so the efficiency norm is stable — this is
    the borrowed substrate the per-player read regresses toward. Volume-weighted (total
    points / total opportunity) over players clearing POS_MEAN_MIN_OPP per game, across
    the given `weeks` (the weeks ≤ the as-of cutoff). The norm is a structural baseline,
    so it is cumulative within the cutoff (max sample available as of week N) — never
    peeking past N. Session 9: the points basis is the league's CANONICAL scoring
    (`actual_points_expr`; == fantasy_points_ppr for a PPR league → is_mine byte-identical).
    """
    pts = actual_points_expr(scoring_profile(scoring), scoring) if scoring else pl.col("fantasy_points_ppr")
    pool = (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS) & pl.col("week").is_in(weeks))
        .with_columns(
            opportunity_expr().alias("opp"),
            pts.fill_null(0.0).alias("fantasy_points_ppr"),
        )
    )
    per_player = pool.group_by("player_display_name", "position").agg(
        pl.len().alias("g"),
        pl.col("fantasy_points_ppr").sum().alias("pts"),
        pl.col("opp").sum().alias("opp"),
    )
    qualified = per_player.filter(pl.col("opp") / pl.col("g") >= POS_MEAN_MIN_OPP)
    means = qualified.group_by("position").agg(
        (pl.col("pts").sum() / pl.col("opp").sum()).alias("mean_ppo")
    )
    return {row["position"]: float(row["mean_ppo"]) for row in means.iter_rows(named=True)}


def _compute_as_of(
    season_df: pl.DataFrame, pos_mean: dict, as_of_week: int, *, opp_half_life, security_map: dict,
    has_exp: bool = True,
) -> list:
    """The per-player signal rows as of one cutoff week N — `season_df` is the join
    already filtered to weeks ≤ N (skill positions, nulls filled). Returns a list of
    row dicts tagged `as_of_week = N`.

    Both the cutoff (Part 1) and roster-as-of-N (Part 3) fall out of the filtered slice:
    `roster_id` per player resolves to the team they belonged to in their latest week
    **≤ N** (arg_max over the slice), so a mid-season trade/add changes *who is on the
    team* at week N, not just their numbers. The opportunity-percentile spectrum is
    recomputed within this cohort, so it reads "where this player sits in the league as
    of week N".
    """
    # roster_id per player = the team they belong to in their latest week ≤ N (a
    # mid-season acquisition is credited to their as-of-N roster), mirroring the leakage
    # transform's current-team rule. One row per rostered skill player.
    current_roster = {
        row["sleeper_player_id"]: int(row["roster_id"])
        for row in season_df.group_by("sleeper_player_id")
        .agg(pl.col("roster_id").sort_by("week").last().alias("roster_id"))
        .iter_rows(named=True)
    }

    agg = _recent_aggregate(season_df)

    records = []
    for row in agg.iter_rows(named=True):
        pos = row["position"]
        series = [
            {
                "week": int(w["week"]), "pts": float(w["pts"]), "opp": float(w["opp"]),
                "td_pts": float(w["td_pts"]), "exp_pts": float(w["exp_pts"]),
            }
            for w in row["weeks"]
        ]
        # EWMA-weighted per-game rates (opportunity is the drifting half — recency-tilted);
        # the read then splits these into sticky opportunity vs efficiency-regressed ppo.
        rates = _weighted_rates(series, half_life=opp_half_life)
        sig = _player_signal(
            {"position": pos, **rates},
            pos_mean.get(pos, 0.0),
            shrink_k=SHRINK_K,
            min_games=MIN_GAMES,
            spike_band=SPIKE_BAND,
            sticky_band=STICKY_BAND,
        )
        # The §1 Quality axis rests on the ff_opportunity substrate; hold it null where that substrate
        # is absent (pre-2025 corpus), rather than reporting a placeholder-zero quality_rate/luck.
        if not has_exp:
            sig["quality_rate"] = None
            sig["luck"] = None
        # Trust axis (direction/reliability) + the point-correlation companion are
        # computed from the raw series, not inside `_player_signal` — they need the
        # per-week list, not just the aggregate rates, and (for security) external
        # roster context `_player_signal` has no business depending on.
        records.append(
            {
                "as_of_week": as_of_week,
                "roster_id": current_roster.get(row["sleeper_player_id"]),
                "sleeper_player_id": row["sleeper_player_id"],
                "player_display_name": row["player_display_name"],
                "position": pos,
                **sig,
                "direction": _direction(series, half_life=DIRECTION_HALF_LIFE_WK, band=DIRECTION_BAND),
                "reliability": _reliability(series, min_games=MIN_GAMES),
                "point_correlation": _point_correlation(series, min_games=MIN_GAMES) if has_exp else None,
                "security": security_map.get(row["sleeper_player_id"], "unknown"),
                "weeks": [
                    {"week": w["week"], "pts": round1(w["pts"]), "opp": round1(w["opp"])}
                    for w in series
                ],
            }
        )

    # Opportunity percentile within position (0–1, min→max opp_g) — the league-relative
    # "how much volume does he command" evidence, via the shared spectrum normaliser.
    by_pos = {}
    for i, r in enumerate(records):
        by_pos.setdefault(r["position"], []).append(i)
    opp_pct = [0.5] * len(records)
    for pos, idxs in by_pos.items():
        positions = spectrum_positions([records[i]["opp_g"] for i in idxs])
        for i, p in zip(idxs, positions):
            opp_pct[i] = p

    rows = []
    for r, op in zip(records, opp_pct):
        weeks = r.pop("weeks")
        rows.append(
            {
                **r,
                "opp_pct": round(op, 3),
                # View-ready series so the front-end seam can JSON.parse and draw a
                # points/opportunity sparkline with no per-item remapping.
                "weeks_json": json.dumps(weeks),
            }
        )
    return rows


def _security_map() -> dict:
    """sleeper_player_id → security category, from the PINNED Sleeper registry snapshot
    (injury_status, depth_chart_order). This is "now" data, not historical — Sleeper
    doesn't snapshot injury/depth-chart state by week — so the same value applies to
    every as_of_week slice for a given player. A documented simplification, not a bug:
    the source data has no history to be more precise with. Session 1.7: reads the pinned
    snapshot, not the live 24h cache, so the security axis is reproducible too (the same
    registry-drift class the eligibility fix closes; 0 movement at capture since the pin is
    a copy of the live cache)."""
    players = data_layer.read_pinned_sleeper_players()
    return {
        row["sleeper_player_id"]: _security(row["injury_status"], row["depth_chart_order"])
        for row in players.iter_rows(named=True)
    }


def compute(season: int, *, league_id=None) -> pl.DataFrame:
    # Full (frozen) join; usage/score columns can be null for a player who didn't record
    # that stat type, so treat as zero so opportunity and points are well-defined.
    scoring = data_layer.read_scoring_settings(season, league_id=league_id)
    join = data_layer.read_join_season(season, league_id=league_id).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    ).with_columns(
        [
            pl.col(c).fill_null(0.0)
            for c in [
                "carries", "targets", "attempts", "fantasy_points_ppr",
                "rushing_tds", "receiving_tds", "passing_tds",
            ]
        ]
    )
    # exp_pts = the league-scored expected points from the ff_opportunity components (the Quality basis).
    # The ff_opportunity substrate (EXP_COMPONENT_COLS) is only backfilled for 2025; historical corpus
    # seasons lack it. When present it drives the §1 Quality axis; when ABSENT exp_pts is a placeholder
    # and the Quality-axis fields (quality_rate / luck / point_correlation) are held null (law 2 — null
    # when the substrate can't support the read). The core repeatability read (regression_risk /
    # expected_ppg / the categorical read) needs none of it, so it is unaffected — is_mine (2025, has the
    # columns) is byte-identical, corpus 2020-24 gets the core read with a null Quality axis.
    has_exp = all(c in join.columns for c in EXP_COMPONENT_COLS)
    if has_exp:
        full = join.with_columns(
            [pl.col(c).fill_null(0.0) for c in EXP_COMPONENT_COLS]
        ).with_columns(expected_points_expr(scoring).alias("exp_pts"))
    else:
        full = join.with_columns(pl.lit(0.0).alias("exp_pts"))

    # Session 9: score realized weekly points on the league's CANONICAL scoring (was raw fantasy_points_ppr —
    # a fixed-PPR yardstick that mis-scored non-PPR keys by up to ~7 pts/wk). actual_points_expr("ppr") ==
    # fantasy_points_ppr, so is_mine (a PPR league) is byte-identical; overwrite in place so _recent_aggregate
    # + point_correlation pick it up as `pts`. (For non-PPR corpus keys the CODE now diverges from the frozen
    # spine predictions — realized only on a future re-backfill; the frozen parquet stays immutable.)
    full = full.with_columns(
        actual_points_expr(scoring_profile(scoring), scoring).fill_null(0.0).alias("fantasy_points_ppr"))

    security_map = _security_map()

    # Materialize one tall snapshot per as-of week N = 1..maxweek: the dashboard exactly
    # as it would have read through week N, every player recomputed on weeks ≤ N. Current
    # (latest) behavior is the N = maxweek slice. Cheap to materialize all weeks.
    max_week = int(full["week"].max())
    all_rows = []
    for n in range(1, max_week + 1):
        sub = full.filter(pl.col("week") <= n)
        # Structural efficiency baseline: cumulative over weeks ≤ N (max sample within
        # the cutoff), never peeking past N.
        pos_mean = positional_mean_ppo(season, list(range(1, n + 1)), scoring=scoring)
        all_rows.extend(
            _compute_as_of(sub, pos_mean, n, opp_half_life=OPP_HALF_LIFE_WK,
                           security_map=security_map, has_exp=has_exp)
        )

    # infer_schema_length=None: reliability/point_correlation are None for many
    # low-sample rows (early as_of_week slices especially) — a partial-row schema scan
    # can pin the wrong dtype for a column that's all-null in the sampled prefix but
    # numeric further down, so scan every row instead.
    # sleeper_player_id is the unique tie-break: within a (as_of_week, roster_id) many players share a
    # rounded regression_risk, so a sort on it alone is parallelism-dependent (the 1.7 lesson). One row
    # per (as_of_week, sleeper_player_id) ⇒ it fully orders the frame → byte-stable output.
    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "roster_id", "regression_risk", "sleeper_player_id", descending=[False, False, True, False]
    )
    # Keep the Quality-axis columns Float64 even when held all-null (no ff_opportunity substrate), so the
    # corpus schema is consistent with 2025 for the scorer's cross-league scans.
    df = df.with_columns([
        pl.col(c).cast(pl.Float64) for c in ("quality_rate", "luck", "point_correlation")
        if c in df.columns and df[c].dtype == pl.Null
    ])
    print(f"=== Player signal: season={season}  as_of_week 1..{max_week} ===")
    latest = df.filter(pl.col("as_of_week") == max_week)
    print(f"  latest (week {max_week}) — {latest.height} players:")
    print(latest.select(
        "player_display_name", "position", "recent_ppg", "opp_g",
        "td_share", "regression_risk", "read",
    ))
    return df


def run(season: int, *, league_id=None) -> None:
    df = compute(season, league_id=league_id)
    data_layer.write_player_signal(df, season, league_id=league_id)
    lid = league_id or data_layer._active_league(season)[0]
    print(f"  → snapshots/derived/league/{lid}/player_signal_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the per-player spike signal-quality read.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
