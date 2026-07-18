"""compute_engine_scorecard.py — the L3 SCORER (Session 5): the first thing in the project that JUDGES.

Reads the FROZEN `resolutions` ledger and produces `engine_scorecard_{season}` — a per-read verdict,
`(read × slice × week)`, answering: does the engine beat its declared naive baseline (SKILL), is it
CALIBRATED (PIT-uniformity / coverage / Brier), does its ranking carry (DISCRIMINATION = Spearman), and —
the headline, in C2 — is its own stated confidence HONEST (law 2). It aggregates and judges; it does NOT
fetch, recompute a read, re-select, change a constant (that is the Tuner, L4), or package a suppression
(the Proposer, L6). **Measure and report; tune nothing, promote nothing.**

Law 1 is STRUCTURAL: the grain is a SLICE, never a `prediction_id`. The scorer judges DISTRIBUTIONS, never
a single claim — no per-claim pass/fail can exist, by construction. The model verdict (`slice_dim='overall'`)
is computed over `inputs_ok=true ∧ resolved=true` ONLY; `inputs_ok=false` and unresolved are their own
quarantined slices (`slice_dim ∈ {inputs_ok, resolution_status}`), never blended into a model number.

Because it fits no parameter, the scorer has NO leakage risk → it scores every season and slice; every row
carries `season` + a `cohort` slice so the out-of-sample story (does a read that looks good on 2021–2023
hold on the 48 never_tune generalization leagues / on 2025?) is visible to the human and the Tuner.

`resolutions` carries neither `confidence` nor a naive baseline, so the scorer re-joins `read_predictions`
(for `value` + `confidence`) and derives every naive from the frozen `outcomes` (`scorecard_registry.py`).

Usage:
    python3 -m application.data.corpus.compute_engine_scorecard --season 2025   # one season
    python3 -m application.data.corpus.compute_engine_scorecard                  # all spined seasons
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time

import polars as pl

from application.data import data_layer
from application.data.corpus import constants_snapshot
from application.data.corpus import scorecard_registry as reg
from application.data.corpus.compute_resolutions import _DIR_ABS, _DIR_REL

SPINED_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)

# corpus pilot_cohort → the scorer's cohort label (the honest generalization axis)
_COHORT = {"corpus": "matched", "corpus_gen": "generalization", "mine": "mine"}
# player-family reads whose subject carries a sleeper_player_id we can map to a position
_PLAYER_READS = {"production_vor", "player_signal", "ros_player_band"}

# The base model-quality slices (population = resolved ∧ inputs_ok). Each names the column it groups on
# (None → the single `overall` verdict row).
_BASE_SLICES = [
    ("overall", None),
    ("week", "as_of_week"),
    ("league", "league_id"),
    ("position", "position"),
    ("cohort", "cohort"),
    ("scoring_key", "scoring_key"),
]

SCORECARD_COLS = [
    # identity / provenance
    "scorecard_id", "read", "claim_type", "slice_dim", "slice_val", "season", "horizon",
    "code_version", "constants_hash", "config_version", "recorded_at",
    # coverage / denominators
    "n_claims", "n_resolved", "n_unresolved", "resolved_rate", "n_subjects",
    # family 1 — accuracy / error (point + ordinal)
    "mae", "med_error", "rmse",
    # family 2 — calibration (interval + probability)
    "in_band_rate", "pit_ks_stat", "pit_edge_mass", "coverage_actual", "brier",
    # family 3 — skill vs the declared naive
    "mae_naive", "skill", "skill_kind", "baseline_provenance",
    # family 3b — discrimination (Spearman of claim vs truth — does the ranking carry)
    "discrimination",
    # family 4 — confidence-honesty (law 2 — the headline)
    "conf_label", "conf_polarity", "conf_monotonicity", "conf_top_minus_bottom", "conf_tier_error",
    "conf_honest",
    # verdicts (Law-1 legal — distribution-level only)
    "measurable_law2", "verdict_note",
]

_NUMERIC_METRICS = ["mae", "med_error", "rmse", "in_band_rate", "pit_ks_stat", "pit_edge_mass",
                    "coverage_actual", "brier", "mae_naive", "skill", "conf_monotonicity",
                    "conf_top_minus_bottom", "conf_tier_error"]


# ---------------------------------------------------------------------------------------------------
# Small helpers (copied per-module, the corpus convention — not a shared import)
# ---------------------------------------------------------------------------------------------------

def _git_sha() -> str:
    """The producing commit — the scorer's `code_version`. REFUSES a dirty tree (the 4a-fix lesson):
    `code_version` folds into `scorecard_id`, so a canonical score must be stamped by a committed tree."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    if dirty.strip():
        raise RuntimeError("refusing to stamp code_version from a DIRTY tree — commit first "
                           "(scorecard_id folds in code_version; a dirty stamp is a provenance lie).")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive value-equality (determinism is about VALUES, not the physically-nondeterministic
    parquet byte stream). Same columns, then sort-by-all + `.equals` — the ledger discipline."""
    if set(a.columns) != set(b.columns):
        return False
    cols = sorted(a.columns)
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


def _ks_edge(pits: list) -> tuple:
    """KS statistic of a PIT sample vs Uniform(0,1) + the edge mass in [0,0.1]∪[0.9,1]. Deterministic
    (a sort). Returns (ks, edge) or (None, None) for an empty sample. A well-calibrated read → KS ~ 0,
    edge ~ 0.2; PIT piled at an edge → large KS + high edge mass (the band's projection-optimism tell)."""
    v = sorted(x for x in pits if x is not None)
    n = len(v)
    if n == 0:
        return (None, None)
    dpos = max((i + 1) / n - p for i, p in enumerate(v))
    dneg = max(p - i / n for i, p in enumerate(v))
    edge = sum(1 for p in v if p < 0.1 or p > 0.9) / n
    return (float(max(dpos, dneg)), float(edge))


# ---------------------------------------------------------------------------------------------------
# Enrichment — the per-claim frame the slicer aggregates
# ---------------------------------------------------------------------------------------------------

def _position_map() -> pl.DataFrame:
    """Deterministic sleeper_player_id → position, from the immutable pinned registry snapshot (Session 1.7,
    the authority for a rostered player's eligibility)."""
    pp = data_layer.read_pinned_sleeper_players()
    return pp.select(pl.col("sleeper_player_id").cast(pl.Utf8).alias("pid"),
                     pl.col("position").alias("pos_from_map")).unique(subset="pid")


def _cohort_map() -> pl.DataFrame:
    """league_id → cohort from the AUTHORITATIVE corpus manifest `stratum` (matched / generalization / mine).
    The manifest covers every spined league (312, 1 per league_id); `leagues.parquet`'s `pilot_cohort` is an
    incomplete projection (missing 34 leagues, including 8 in 2025) — so the scorer keys off the manifest."""
    m = data_layer.read_corpus_manifest()
    return (m.select(pl.col("league_id").cast(pl.Utf8), pl.col("stratum").alias("cohort"))
              .unique(subset="league_id"))


def _naive_forward_points(res: pl.DataFrame, pwp: pl.DataFrame, join_on: list) -> pl.DataFrame:
    """recent-ppg-forward naive for a ROS point read: naive = mean(pts | wk ≤ as_of) × #{SCHEDULED remaining
    weeks in the truth window (≥ as_of)}. The remaining-week count is the LEAGUE-WIDE scheduled horizon
    (`max played week − as_of + 1`), a leak-safe schedule property identical for every player at a given
    (league, as_of). NOT the player's own #realized forward weeks (Session 9: that was hindsight a leak-safe
    forecast can't use — injuries/byes shrink it and flattered the naive, making `production_vor` "lose to
    recent form every season" too harsh). Returns prediction_id → naive_pred."""
    if not res.height:
        return pl.DataFrame(schema={"prediction_id": pl.Utf8, "naive_pred": pl.Float64})
    # League-wide scheduled ROS horizon: last played week in the league − as_of + 1 (weeks ≥ as_of, matching
    # compute_resolutions' inclusive truth window). A schedule fact, not a per-player realized count.
    sched = pwp.group_by("league_id").agg(pl.col("week").max().alias("_lg_max_week"))
    j = res.select("prediction_id", "as_of_week", *join_on).join(pwp, on=join_on, how="left")
    agg = j.group_by("prediction_id", "league_id", "as_of_week").agg(
        recent=pl.col("pts").filter(pl.col("week") <= pl.col("as_of_week")).mean())
    agg = agg.join(sched, on="league_id", how="left").with_columns(
        n_fwd=pl.max_horizontal(pl.lit(0), pl.col("_lg_max_week") - pl.col("as_of_week") + 1))
    return agg.with_columns((pl.col("recent") * pl.col("n_fwd")).alias("naive_pred")).select("prediction_id", "naive_pred")


def _naive_ppg(res: pl.DataFrame, pwp: pl.DataFrame, join_on: list) -> pl.DataFrame:
    """player_signal weekly naive: equal-weight recent ppg = mean(pts | wk ≤ as_of) (the promoted `naive_ppg`,
    compared to realized forward ppg — same shape as backtest_player_signal)."""
    if not res.height:
        return pl.DataFrame(schema={"prediction_id": pl.Utf8, "naive_pred": pl.Float64})
    j = res.select("prediction_id", "as_of_week", *join_on).join(pwp, on=join_on, how="left")
    agg = j.group_by("prediction_id").agg(
        naive_pred=pl.col("pts").filter(pl.col("week") <= pl.col("as_of_week")).mean())
    return agg.select("prediction_id", "naive_pred")


def _realized_direction(res: pl.DataFrame, pwp: pl.DataFrame, join_on: list) -> pl.DataFrame:
    """The realized forward-vs-recent trend sign per direction claim (reusing compute_resolutions' band) —
    the base-rate skill needs the realized class, which resolutions doesn't carry."""
    if not res.height:
        return pl.DataFrame(schema={"prediction_id": pl.Utf8, "realized_dir": pl.Utf8})
    j = res.select("prediction_id", "as_of_week", *join_on).join(pwp, on=join_on, how="left")
    rf = j.group_by("prediction_id").agg(
        recent=pl.col("pts").filter(pl.col("week") <= pl.col("as_of_week")).mean(),
        forward=pl.col("pts").filter(pl.col("week") > pl.col("as_of_week")).mean())
    thr = pl.max_horizontal(pl.lit(_DIR_ABS), (_DIR_REL * pl.col("recent").abs()))
    delta = pl.col("forward") - pl.col("recent")
    return rf.with_columns(
        pl.when(delta > thr).then(pl.lit("rising"))
          .when(delta < -thr).then(pl.lit("fading"))
          .when(pl.col("recent").is_not_null() & pl.col("forward").is_not_null()).then(pl.lit("steady"))
          .otherwise(None).alias("realized_dir")).select("prediction_id", "realized_dir")


def enrich(season: int) -> pl.DataFrame:
    """The per-claim frame the slicer aggregates: resolutions + claim `value`/`confidence` + per-claim
    naive metric + position/cohort, with `engine_metric`/`naive_metric`/`err_signed`/`acc_abs` derived."""
    res = data_layer.read_resolutions(season)
    preds = data_layer.read_predictions(season).select(
        "prediction_id", "value", "value_str", "confidence", "confidence_label")
    res = res.join(preds, on="prediction_id", how="left")
    res = res.with_columns(pl.col("subject_id").str.split(":").list.last().alias("pid"))

    pwp_l = data_layer.read_outcomes(season, outcome_type="player_weekly_pts").select(
        "league_id", pl.col("subject_id").alias("pid"), "week", pl.col("value").alias("pts"))

    # --- per-claim naive predictions, by family ---
    naive = pl.concat([
        _naive_forward_points(res.filter(pl.col("read") == "production_vor"), pwp_l, ["league_id", "pid"]),
        _naive_ppg(res.filter((pl.col("read") == "player_signal") & (pl.col("claim_type") == "point")),
                   pwp_l, ["league_id", "pid"]),
    ], how="vertical")
    rdir = _realized_direction(
        res.filter((pl.col("read") == "player_signal") & (pl.col("claim_type") == "direction")),
        pwp_l, ["league_id", "pid"])

    # pool-mean naives (positional_depth per league×position-subject; proj_wins per league)
    pd_pool = (res.filter((pl.col("read") == "positional_depth") & pl.col("resolved"))
                  .group_by("league_id", "subject_id").agg(pl.col("truth").mean().alias("_pd_naive")))
    pw_pool = (res.filter((pl.col("read") == "bracket_odds") & (pl.col("claim_type") == "point") & pl.col("resolved"))
                  .group_by("league_id").agg(pl.col("truth").mean().alias("_pw_naive")))
    # league roster count → closed-form random-permutation naive for the ordinals
    nlg = (res.filter(pl.col("read") == "true_rank")
              .group_by("league_id").agg(pl.col("subject_id").n_unique().alias("n_lg")))

    res = (res.join(naive, on="prediction_id", how="left")
              .join(pd_pool, on=["league_id", "subject_id"], how="left")
              .join(pw_pool, on="league_id", how="left")
              .join(nlg, on="league_id", how="left")
              .join(rdir, on="prediction_id", how="left")
              .join(_position_map(), on="pid", how="left")
              .join(_cohort_map(), on="league_id", how="left"))

    is_point = pl.col("claim_type") == "point"
    is_ordinal = pl.col("claim_type") == "ordinal"
    fam = pl.concat_str(["read", "claim_type"], separator="/")
    # closed-form E|rank_error| under a uniform permutation of n seats = (n²−1)/(3n) — vectorised, no RNG
    perm_mae = (pl.when(pl.col("n_lg") >= 2)
                  .then((pl.col("n_lg") ** 2 - 1) / (3.0 * pl.col("n_lg"))).otherwise(None))

    res = res.with_columns(
        # position slice: positional_depth carries it in the subject; player reads map it; else null
        pl.when(pl.col("read") == "positional_depth").then(pl.col("subject_id").str.split(":").list.last())
          .when(pl.col("read").is_in(list(_PLAYER_READS))).then(pl.col("pos_from_map"))
          .otherwise(None).alias("position"),
        # family-1 accuracy primitive (point → error; ordinal → rank_error)
        pl.when(is_point).then(pl.col("error")).when(is_ordinal).then(pl.col("rank_error"))
          .otherwise(None).alias("err_signed"),
        pl.when(is_point).then(pl.col("abs_error")).when(is_ordinal).then(pl.col("rank_error").abs())
          .otherwise(None).alias("acc_abs"),
        # the pooled naive_pred overrides the generic one where it applies
        pl.when(pl.col("read") == "positional_depth").then(pl.col("_pd_naive"))
          .when((pl.col("read") == "bracket_odds") & is_point).then(pl.col("_pw_naive"))
          .otherwise(pl.col("naive_pred")).alias("naive_pred"),
    )
    res = res.with_columns(
        # engine_metric / naive_metric drive skill uniformly, per skill_kind
        pl.when(fam == "bracket_odds/probability").then(pl.col("brier"))
          .when(is_point).then(pl.col("abs_error"))
          .when(is_ordinal).then(pl.col("rank_error").abs())
          .when(fam == "player_signal/direction").then(pl.col("direction_hit"))
          .otherwise(None).alias("engine_metric"),
        pl.when(fam == "bracket_odds/probability").then(pl.lit(reg.COIN_FLIP_BRIER))
          .when(fam.is_in(["true_rank/ordinal", "bracket_odds/ordinal"])).then(perm_mae)
          .when(is_point).then((pl.col("naive_pred") - pl.col("truth")).abs())
          .otherwise(None).alias("naive_metric"),
    )

    # --- confidence-honesty inputs (C2): conf_strength + the honesty primitive, built from the registry ---
    # so the polarity transform + primitive can't drift from the declared spec. The band's abs_error is null
    # in resolutions (it carries in_band/pit), so its honesty primitive is computed as |center − truth|.
    strength = pl.lit(None, dtype=pl.Float64)
    conf_err = pl.lit(None, dtype=pl.Float64)
    for (rd, ct), spec in reg.CONF_SIGNALS.items():
        cond = (pl.col("read") == rd) & (pl.col("claim_type") == ct)
        s = (-pl.col("confidence")) if spec["strength"] == "neg" else (pl.col("confidence") - 0.5).abs()
        strength = pl.when(cond).then(s).otherwise(strength)
        if spec["primitive"] == "abs_error":
            e = (pl.col("value") - pl.col("truth")).abs() if rd == "ros_player_band" else pl.col("abs_error")
        elif spec["primitive"] == "rank_abs_error":
            e = pl.col("rank_error").abs()
        else:                                                       # brier
            e = pl.col("brier")
        conf_err = pl.when(cond).then(e).otherwise(conf_err)
    res = res.with_columns(strength.alias("conf_strength"), conf_err.alias("_conf_err"))
    return res


# ---------------------------------------------------------------------------------------------------
# Slicing + aggregation
# ---------------------------------------------------------------------------------------------------

_SKILL_KIND = {k: v["skill_kind"] for k, v in reg.NAIVE_BASELINES.items()}
_PROVENANCE = {k: v["provenance"] for k, v in reg.NAIVE_BASELINES.items()}
# Retained for frozen_era()'s epoch patch (constants_snapshot restores ces._CONF_LABEL[band]=ros_cv). The
# scorer itself now reads the label from reg.CONF_SIGNALS at runtime (see `lab` in _finalize) so it's correct
# under `python -m` too (where __main__ ≠ the fully-qualified module frozen_era patches).
_CONF_LABEL = {k: v["label"] for k, v in reg.CONF_SIGNALS.items()}
_CONF_POLARITY = {k: v["strength"] for k, v in reg.CONF_SIGNALS.items()}
CONF_MONO_MARGIN = reg.CONF_MONO_MARGIN   # re-exported for the report / gate


def _confidence_honesty(pop: pl.DataFrame, ctx: dict) -> tuple[dict, pl.DataFrame]:
    """The law-2 headline. For each of the 5 confidence-bearing families, over its resolved∧inputs_ok pool:
    (a) the per-read verdict — Spearman(conf_strength, realized error) [≤0 honest] + the low−high tier error
    gap [>0 honest] → `conf_honest`; (b) the per-tier reliability rows (`slice_dim='confidence_tier'`).

    DETERMINISTIC by construction: tertile edges are quantiles of the frozen pool; monotonicity + the tier
    means are computed with a SINGLE group_by over the stable frame (never a nested group_by over a
    reordered sub-frame — that path float-flakes at the ULP, the `_standings_as_of` lesson)."""
    cf = pop.filter(pl.col("conf_strength").is_not_null() & pl.col("_conf_err").is_not_null())
    if not cf.height:
        return {}, pl.DataFrame(schema={c: (pl.Utf8 if c in _STR_COLS else pl.Float64) for c in SCORECARD_COLS})
    # per-family tertile edges (quantile sorts internally → deterministic), then assign the tier
    edges = cf.group_by("read", "claim_type").agg(
        _e1=pl.col("conf_strength").quantile(reg.TIER_QUANTILES[0]),
        _e2=pl.col("conf_strength").quantile(reg.TIER_QUANTILES[1]))
    cf = cf.join(edges, on=["read", "claim_type"], how="left").with_columns(
        pl.when(pl.col("conf_strength") <= pl.col("_e1")).then(pl.lit(reg.TIER_LABELS[0]))
          .when(pl.col("conf_strength") <= pl.col("_e2")).then(pl.lit(reg.TIER_LABELS[1]))
          .otherwise(pl.lit(reg.TIER_LABELS[2])).alias("conf_tier"))
    # monotonicity + tier means via ONE group_by each (deterministic, like _agg)
    mono = {(r["read"], r["claim_type"]): (None if r["m"] is None or r["m"] != r["m"] else float(r["m"]))
            for r in cf.group_by("read", "claim_type")
                       .agg(m=pl.corr("conf_strength", "_conf_err", method="spearman")).to_dicts()}
    tier_err: dict = {}
    for r in cf.group_by("read", "claim_type", "conf_tier").agg(err=pl.col("_conf_err").mean()).to_dicts():
        tier_err.setdefault((r["read"], r["claim_type"]), {})[r["conf_tier"]] = r["err"]
    verdicts = {}
    for key, te in tier_err.items():
        lo, hi, m = te.get(reg.TIER_LABELS[0]), te.get(reg.TIER_LABELS[2]), mono.get(key)
        tmb = (lo - hi) if (lo is not None and hi is not None) else None
        honest = (m is not None and m <= -CONF_MONO_MARGIN and tmb is not None and tmb >= 0.0)
        verdicts[key] = {"conf_top_minus_bottom": tmb, "conf_honest": honest}
    tier_rows = _finalize(_agg(cf, ["conf_tier"]), "confidence_tier", "conf_tier", ctx)
    return verdicts, tier_rows


def _agg(pop: pl.DataFrame, group_cols: list) -> pl.DataFrame:
    """Aggregate the metric families over `pop`, grouped by `group_cols` (+ read, claim_type). Every mean
    is over the group's rows; skill_num/den + the PIT list are carried for the post-step."""
    keys = ["read", "claim_type", "horizon", *group_cols]
    return pop.group_by(keys).agg(
        n_claims=pl.len(),
        n_resolved=pl.col("resolved").sum(),
        n_subjects=pl.col("subject_id").n_unique(),
        mae=pl.col("acc_abs").mean(),
        med_error=pl.col("err_signed").median(),
        rmse=(pl.col("err_signed") ** 2).mean().sqrt(),
        in_band_rate=pl.col("in_band").mean(),
        brier=pl.col("brier").mean(),
        discrimination=pl.corr("value", "truth", method="spearman"),
        conf_monotonicity=pl.corr("conf_strength", "_conf_err", method="spearman"),
        conf_tier_error=pl.col("_conf_err").mean(),
        _em=pl.col("engine_metric").mean(),
        _nm=pl.col("naive_metric").mean(),
        _rise=(pl.col("realized_dir") == "rising").mean(),
        _fade=(pl.col("realized_dir") == "fading").mean(),
        _stead=(pl.col("realized_dir") == "steady").mean(),
        _pit=pl.col("pit").drop_nulls(),
    )


def _finalize(agg: pl.DataFrame, slice_dim: str, slice_val_col, ctx: dict, *,
              coverage: dict | None = None) -> pl.DataFrame:
    """Turn an aggregate frame into scorecard rows: attach identity/provenance, compute skill per
    skill_kind, KS/edge from the PIT list, and select SCORECARD_COLS. `coverage` (read,ct)->(n_claims,
    n_resolved) overrides the coverage counts for the `overall` row (full population, not just resolved)."""
    if not agg.height:
        return pl.DataFrame(schema={c: (pl.Utf8 if c in _STR_COLS else pl.Float64) for c in SCORECARD_COLS})

    # KS + edge from the PIT list (Python; the list is empty for non-distribution families)
    ks, edge = [], []
    for pits in agg["_pit"].to_list():
        k, e = _ks_edge(pits or [])
        ks.append(k)
        edge.append(e)
    agg = agg.with_columns(pl.Series("pit_ks_stat", ks, dtype=pl.Float64),
                           pl.Series("pit_edge_mass", edge, dtype=pl.Float64))

    base_rate = pl.max_horizontal("_rise", "_fade", "_stead")
    sk = pl.struct("read", "claim_type").map_elements(
        lambda s: _SKILL_KIND.get((s["read"], s["claim_type"]), "na"), return_dtype=pl.Utf8)
    prov = pl.struct("read", "claim_type").map_elements(
        lambda s: _PROVENANCE.get((s["read"], s["claim_type"]), "na"), return_dtype=pl.Utf8)
    # Read the label from reg.CONF_SIGNALS at RUNTIME (like `ml2` below), NOT the import-time _CONF_LABEL
    # cache: under `python -m …` the scorer runs as __main__ while frozen_era() patches the fully-qualified
    # module's _CONF_LABEL — a different object — so a cached read would stamp the live label (ros_sigma) on a
    # frozen-era re-score whose numbers are ros_cv. reg.CONF_SIGNALS is a single shared dict frozen_era patches.
    lab = pl.struct("read", "claim_type").map_elements(
        lambda s: reg.CONF_SIGNALS.get((s["read"], s["claim_type"]), {}).get("label"), return_dtype=pl.Utf8)
    pol = pl.struct("read", "claim_type").map_elements(
        lambda s: _CONF_POLARITY.get((s["read"], s["claim_type"])), return_dtype=pl.Utf8)
    ml2 = pl.struct("read", "claim_type").map_elements(
        lambda s: (s["read"], s["claim_type"]) in reg.CONF_SIGNALS, return_dtype=pl.Boolean)

    out = agg.with_columns(
        pl.lit(slice_dim).alias("slice_dim"),
        (pl.lit("all") if slice_val_col is None else pl.col(slice_val_col).cast(pl.Utf8)).alias("slice_val"),
        pl.lit(ctx["season"]).cast(pl.Int64).alias("season"),
        pl.lit(ctx["code_version"]).alias("code_version"),
        pl.lit(ctx["constants_hash"]).alias("constants_hash"),
        pl.lit(reg.SCORECARD_CONFIG_VERSION).alias("config_version"),
        pl.lit(None, dtype=pl.Utf8).alias("recorded_at"),
        pl.col("in_band_rate").alias("coverage_actual"),
        sk.alias("skill_kind"),
        prov.alias("baseline_provenance"),
        base_rate.alias("_base_rate"),
        lab.alias("conf_label"),
        pol.alias("conf_polarity"),
        ml2.alias("measurable_law2"),
        # conf_monotonicity + conf_tier_error come from _agg; the per-read tier verdict is a post-step
        pl.lit(None, dtype=pl.Float64).alias("conf_top_minus_bottom"),
        pl.lit(None, dtype=pl.Boolean).alias("conf_honest"),
    )
    # skill per kind; mae_naive is the denominator's realized value
    out = out.with_columns(
        pl.when(pl.col("skill_kind") == "accuracy").then(pl.col("_base_rate"))
          .when(pl.col("skill_kind").is_in(["mae", "brier"])).then(pl.col("_nm"))
          .otherwise(None).alias("mae_naive"),
    ).with_columns(
        pl.when(pl.col("skill_kind").is_in(["mae", "brier"]) & (pl.col("_nm") > 0))
          .then(1.0 - pl.col("_em") / pl.col("_nm"))
          .when((pl.col("skill_kind") == "accuracy") & (pl.col("_base_rate") < 1.0))
          .then((pl.col("_em") - pl.col("_base_rate")) / (1.0 - pl.col("_base_rate")))
          .otherwise(None).alias("skill"),
        pl.lit(None, dtype=pl.Utf8).alias("verdict_note"),
    ).with_columns(
        (pl.col("n_claims") - pl.col("n_resolved")).alias("n_unresolved"),
        (pl.col("n_resolved") / pl.col("n_claims")).alias("resolved_rate"),
    )

    # overall coverage override — the full-population n so resolved_rate reflects real coverage
    if coverage is not None:
        cov = pl.DataFrame([{"read": r, "claim_type": c, "cov_claims": n, "cov_res": nr}
                            for (r, c), (n, nr) in coverage.items()])
        out = (out.join(cov, on=["read", "claim_type"], how="left")
                  .with_columns(pl.col("cov_claims").alias("n_claims"),
                                pl.col("cov_res").alias("n_resolved"),
                                (pl.col("cov_claims") - pl.col("cov_res")).alias("n_unresolved"),
                                (pl.col("cov_res") / pl.col("cov_claims")).alias("resolved_rate")))

    scid = pl.struct("read", "claim_type", "slice_dim", "slice_val", "season").map_elements(
        lambda s: hashlib.blake2b(
            f"{s['read']}|{s['claim_type']}|{s['slice_dim']}|{s['slice_val']}|{s['season']}|{ctx['code_version']}"
            .encode(), digest_size=12).hexdigest(), return_dtype=pl.Utf8)
    out = out.with_columns(
        scid.alias("scorecard_id"),
        *[pl.col(c).cast(pl.Int64) for c in ("n_claims", "n_resolved", "n_unresolved", "n_subjects")],
        pl.col("resolved_rate").cast(pl.Float64),
        # NaN (zero-variance Spearman, 0/0 skill) is "undefined" → null, the None-not-0 convention
        *[pl.col(c).fill_nan(None) for c in (_NUMERIC_METRICS + ["discrimination"])],
    )
    return out.select(SCORECARD_COLS)


_STR_COLS = {"scorecard_id", "read", "claim_type", "slice_dim", "slice_val", "horizon", "code_version",
             "constants_hash", "config_version", "recorded_at", "skill_kind", "baseline_provenance",
             "conf_label", "conf_polarity", "verdict_note"}


# The pre-registered predictions (PM_SESSION_STARTUP §strategic frame) — the scorecard TESTS these; a
# surprise is where the learning is. Each is (label, predicate over the overall row) → HOLD ✓ / SURPRISE ✗.
PRE_REGISTERED = {
    ("player_signal", "point"): ("§1 signal HOLD (measurement)",
                                 lambda r: r["skill"] is not None and r["skill"] >= -0.02),
    ("true_rank", "ordinal"): ("§5 true-rank HOLD (measurement)",
                               lambda r: r["skill"] is not None and r["skill"] > 0.10),
    ("positional_depth", "point"): ("§6 depth HOLD (measurement)",
                                    lambda r: r["skill"] is not None and r["skill"] >= 0.0),
    ("bracket_odds", "probability"): ("§5 Brier < 0.25",
                                      lambda r: r["brier"] is not None and r["brier"] < 0.25),
    ("ros_player_band", "interval"): ("§3 band calibrated to ~0.80",
                                      lambda r: r["coverage_actual"] is not None and abs(r["coverage_actual"] - 0.80) < 0.10),
}
# production_vor is NOT pre-registered — its projection optimism is a FINDING (expected from the primitives),
# not a surprise-vs-prediction. It's surfaced in the headline + user-line, with "—" in the pre-registered column.


def _user_line(key: tuple, r: dict) -> str:
    """The 'what we'd honestly tell a user' line — copy the front end should eventually use (not wired here)."""
    read, ct = key
    sk = _fmt(r["skill"], 2) if r["skill"] is not None else "n/a"
    disc = _fmt(r["discrimination"], 2)
    lines = {
        ("production_vor", "point"): f"Ranks rest-of-season value well (Spearman {disc}) but point totals run high "
                                     f"(median +{_fmt(r['med_error'], 0)}) — trust the ORDER, not the level.",
        ("ros_player_band", "interval"): f"The range is too narrow — truth lands in-band only "
                                         f"{_fmt(r['coverage_actual'], 2)} of the time (target 0.80); widen the error bars.",
        ("player_signal", "point"): f"About even with 'recent form carries forward' (skill {sk}) — a thin edge on "
                                    f"near-random weekly scoring.",
        ("player_signal", "direction"): f"Trend calls barely beat guessing the base rate (skill {sk}).",
        ("true_rank", "ordinal"): f"Ranks final standings materially better than chance (skill {sk}).",
        ("positional_depth", "point"): f"Weak signal on an APPROXIMATE answer key (skill {sk}, coverage-flagged) — "
                                       f"directional only.",
        ("bracket_odds", "probability"): f"Playoff odds are well-calibrated (Brier {_fmt(r['brier'], 2)} < 0.25) and "
                                         f"beat a coin flip (skill {sk}).",
        ("bracket_odds", "point"): f"Win projections beat a .500 baseline (skill {sk}).",
        ("bracket_odds", "ordinal"): f"Seed projections beat random ordering (skill {sk}).",
    }
    line = lines.get(key, f"skill {sk}.")
    if r["measurable_law2"]:
        line += f" Confidence ({r['conf_label']}) {'IS honest' if r['conf_honest'] else 'does NOT sort by error — FLAG'}."
    else:
        line += " Confidence-honesty UNMEASURABLE (no native confidence signal — law-2 gap)."
    return line


def _add_verdict_notes(out: pl.DataFrame) -> pl.DataFrame:
    """Stamp the pre-registered check + the user-facing line onto each `overall` row (`verdict_note`)."""
    notes = {}
    for r in out.filter(pl.col("slice_dim") == "overall").iter_rows(named=True):
        key = (r["read"], r["claim_type"])
        tag, pred = PRE_REGISTERED.get(key, (None, None))
        prefix = ""
        if tag is not None:
            try:
                prefix = f"[{tag}: {'HOLD ✓' if pred(r) else 'SURPRISE ✗'}] "
            except Exception:                                       # noqa: BLE001
                prefix = f"[{tag}: n/a] "
        notes[key] = prefix + _user_line(key, r)
    nf = pl.DataFrame([{"read": r, "claim_type": c, "_note": n} for (r, c), n in notes.items()])
    return (out.join(nf, on=["read", "claim_type"], how="left")
               .with_columns(pl.when(pl.col("slice_dim") == "overall").then(pl.col("_note"))
                             .otherwise(pl.col("verdict_note")).alias("verdict_note"))
               .drop("_note"))


def score_season(season: int) -> pl.DataFrame:
    """Build the full `engine_scorecard_{season}` frame — all slices, provenance-stamped."""
    e = enrich(season)
    ctx = {"season": season, "code_version": _CODE_VERSION,
           "constants_hash": _one_constants_hash(e)}

    # coverage counts over the FULL family population (all inputs_ok, resolved+unresolved)
    coverage = {(r["read"], r["claim_type"]): (r["n_claims"], r["n_resolved"])
                for r in e.group_by("read", "claim_type").agg(
                    n_claims=pl.len(), n_resolved=pl.col("resolved").sum()).iter_rows(named=True)}

    # base model-quality slices — population = resolved ∧ inputs_ok
    pop = e.filter(pl.col("resolved") & pl.col("inputs_ok"))
    parts = []
    for slice_dim, col in _BASE_SLICES:
        p = pop
        if col in ("league_id", "cohort"):     # the band's league_id is null — never a league/cohort slice
            p = p.filter(pl.col("league_id").is_not_null())
        if col == "position":
            p = p.filter(pl.col("position").is_not_null())
        group_cols = [] if col is None else [col]
        parts.append(_finalize(_agg(p, group_cols), slice_dim, col, ctx,
                               coverage=coverage if slice_dim == "overall" else None))

    # quarantine slice 1 — inputs_ok (both true/false), on resolved rows: the L1 quarantine, never blended
    parts.append(_finalize(_agg(e.filter(pl.col("resolved")), ["inputs_ok"]), "inputs_ok", "inputs_ok", ctx))
    # quarantine slice 2 — resolution_status (resolved vs unresolved), on ALL claims: coverage only
    parts.append(_finalize(_agg(e, ["resolved"]), "resolution_status", "resolved", ctx))

    # confidence-honesty (law 2) — the per-tier reliability rows + the per-read verdict merged onto `overall`
    verdicts, tier_rows = _confidence_honesty(pop, ctx)
    parts.append(tier_rows)

    out = pl.concat([p for p in parts if p.height], how="vertical")
    if verdicts:
        vdf = pl.DataFrame([{"read": r, "claim_type": c, "_tmb": v["conf_top_minus_bottom"], "_hon": v["conf_honest"]}
                            for (r, c), v in verdicts.items()])
        out = out.join(vdf, on=["read", "claim_type"], how="left").with_columns(
            pl.when(pl.col("slice_dim") == "overall").then(pl.col("_tmb"))
              .otherwise(pl.col("conf_top_minus_bottom")).alias("conf_top_minus_bottom"),
            pl.when(pl.col("slice_dim") == "overall").then(pl.col("_hon"))
              .otherwise(pl.col("conf_honest")).alias("conf_honest"),
        ).drop("_tmb", "_hon")
    out = _add_verdict_notes(out)
    # Law 1 structural: no per-claim row leaked in (every row is a slice aggregate)
    assert "prediction_id" not in out.columns, "Law 1 breach: a prediction_id leaked into the scorecard"
    return out.select(SCORECARD_COLS)


def _one_constants_hash(e: pl.DataFrame) -> str:
    """The single ledger constants_hash the scored claims carry (a slice spanning two would be averaging
    across a constants change — a provenance lie). Asserts exactly one."""
    hashes = e["constants_hash"].unique().drop_nulls().to_list()
    assert len(hashes) == 1, f"scored claims span {len(hashes)} constants_hash values: {hashes}"
    return hashes[0]


_CODE_VERSION = None   # stamped once per run (a committed tree)


# ---------------------------------------------------------------------------------------------------
# Driver + report
# ---------------------------------------------------------------------------------------------------

def run(seasons=SPINED_SEASONS) -> dict:
    global _CODE_VERSION
    t0 = time.time()
    _CODE_VERSION = _git_sha()
    seasons = [s for s in seasons if data_layer.resolutions_exists(s)]
    rows_written, per_read = 0, {}
    for season in seasons:
        before = (data_layer.read_engine_scorecard(season).height
                  if data_layer.engine_scorecard_exists(season) else 0)
        sc = score_season(season)
        data_layer.write_engine_scorecard(sc, season)
        after = data_layer.read_engine_scorecard(season).height
        rows_written += after - before
        ov = sc.filter(pl.col("slice_dim") == "overall")
        for r in ov.iter_rows(named=True):
            per_read.setdefault((r["read"], r["claim_type"]), []).append((season, r))
        print(f"  season {season}: {sc.height:,} scorecard rows ({after - before:,} newly appended)")

    report = {"seasons": seasons, "rows_written": rows_written, "elapsed_s": round(time.time() - t0, 1),
              "per_read": per_read, "code_version": _CODE_VERSION,
              "file_sizes": {s: round(os.path.getsize(data_layer._engine_scorecard_path(s)) / 1e6, 2)
                             for s in seasons if data_layer.engine_scorecard_exists(s)}}
    _print_report(report)
    return report


def _fmt(x, nd=3):
    return "  n/a" if x is None else f"{x:.{nd}f}"


def _print_report(rep: dict) -> None:
    print("\n=== engine scorecard — the FIRST MEASUREMENT (report, don't tune / don't promote) ===")
    print(f"  seasons={rep['seasons']}  rows={rep['rows_written']:,}  wall-clock={rep['elapsed_s']}s")
    print("  per-read OVERALL verdict (inputs_ok ∧ resolved), across seasons:")
    for (read, ct), rows in sorted(rep["per_read"].items()):
        # pool the overall rows across seasons for the headline
        n = sum(r["n_resolved"] for _, r in rows)
        sk = rows[0][1]["skill_kind"]
        skills = [r["skill"] for _, r in rows if r["skill"] is not None]
        disc = [r["discrimination"] for _, r in rows if r["discrimination"] is not None]
        mae = [r["mae"] for _, r in rows if r["mae"] is not None]
        cov = [r["resolved_rate"] for _, r in rows if r["resolved_rate"] is not None]
        bits = [f"skill_kind={sk:8}"]
        if skills:
            bits.append(f"skill≈{_fmt(sum(skills)/len(skills))}")
        if mae:
            bits.append(f"MAE≈{_fmt(sum(mae)/len(mae), 2)}")
        if disc:
            bits.append(f"disc(Spearman)≈{_fmt(sum(disc)/len(disc))}")
        # calibration for the distribution families
        ib = [r["in_band_rate"] for _, r in rows if r["in_band_rate"] is not None]
        ks = [r["pit_ks_stat"] for _, r in rows if r["pit_ks_stat"] is not None]
        br = [r["brier"] for _, r in rows if r["brier"] is not None]
        if ib:
            bits.append(f"coverage≈{_fmt(sum(ib)/len(ib))}")
        if ks:
            bits.append(f"PIT_KS≈{_fmt(sum(ks)/len(ks))}")
        if br:
            bits.append(f"Brier≈{_fmt(sum(br)/len(br))}")
        if cov:
            bits.append(f"resolved≈{_fmt(sum(cov)/len(cov))}")
        print(f"    {read:16}/{ct:12} n={n:>7}  " + " · ".join(bits))
    _findings(rep)


def _findings(rep: dict) -> None:
    print("  findings (surfaced, not graded — the projection-optimism story the primitives already showed):")
    for (read, ct), rows in sorted(rep["per_read"].items()):
        for season, r in rows:
            if r["skill"] is not None and r["skill"] < 0 and r["skill_kind"] in ("mae", "brier"):
                print(f"    · {read}/{ct} {season}: skill {_fmt(r['skill'])} < 0 — loses to its naive baseline")
                break
        for season, r in rows:
            if r["pit_edge_mass"] is not None and r["pit_edge_mass"] > 0.35:
                print(f"    · {read}/{ct} {season}: {round(r['pit_edge_mass']*100)}% PIT edge mass — miscalibrated")
                break


def main():
    ap = argparse.ArgumentParser(description="Compute the L3 engine scorecard (Session 5).")
    ap.add_argument("--season", type=int, default=None, help="one season (default: all spined)")
    a = ap.parse_args()
    # Session 9: score the FROZEN resolutions at the epoch that made them (the band's confidence in the frozen
    # ledger is ros_cv, not the shipped ros_sigma) so a re-score reproduces every non-production_vor row and the
    # only change is the corrected production_vor naive. Mirrors check_scorecard.main(). This wrap becomes
    # epoch-conditional once the annual re-backfill lands a live-engine population (parked).
    with constants_snapshot.frozen_era():
        run((a.season,) if a.season else SPINED_SEASONS)


if __name__ == "__main__":
    main()
    sys.exit(0)
