"""The read → claim reshape: the 9 claim families of the L2 `predictions` ledger (Session 4a).

Pure reshape of the FROZEN reads into immutable claim rows — no fetch, no recompute, no re-tune, no
grade. Each of the 6 reads is already computed per `as_of_week`; we record a claim at EVERY as-of the
read carries (that as-of *is* "the week the claim was made"). One read can emit MULTIPLE claim families
(bracket_odds → 3, player_signal → 2), and the scoring-scoped band recurs every season, so the
`prediction_id` hash adds `season` and `claim_type` to the IMPROVEMENT_LOOP §L2 key
`(scope, read, subject_id, as_of_week, horizon, code_version)` — without `claim_type` the three
bracket_odds claims for one roster-week collide; without `season` the same (scoring_key, player, week)
band claim collides across years. (Documented refinement; the §L2 key assumed one claim per
(read, subject, week) within a season-partitioned file.)

Schema shape (typed sidecars over the flat §L2 columns, per the confirmed design + 3 refinements):
  • `value` (Float64) XOR `value_str` (Utf8) by claim_type — numeric claims vs the categorical `direction`.
  • `lo`/`hi`/`sigma` (Float64) present IFF `interval` — `sigma` is the band's `ros_sigma`, a typed scale
    param so 4b's `pit = Φ((truth−center)/sigma)` never backs sigma out of lo/hi via BULL_Z.
  • `confidence` (Float64) is the read's designated CANONICAL numeric confidence — the scorer's Law-2
    input; `confidence_label` (Utf8) names WHICH signal it is; `confidence_json` (Utf8) is
    supplementary/audit ONLY (never the scorer's primary read), populated only where a read carries extra
    signals (player_signal, positional_depth's `shape`), null everywhere else.

Law 1 is structural: these are CLAIMS ONLY. No grade / verdict / resolution column exists here.
"""
import hashlib

import polars as pl

# Canonical column order for `predictions_{season}` (the live 2026 path reuses this verbatim).
CLAIM_COLS = [
    "prediction_id", "league_id", "scoring_key", "season", "as_of_week",
    "read", "subject_type", "subject_id", "claim_type",
    "value", "value_str", "lo", "hi", "sigma",
    "horizon", "resolves_at",
    "confidence", "confidence_label", "confidence_json",
    "code_version", "constants_hash", "prompt_version", "model",
    "inputs_ok", "served", "created_at",
]

# Reads with NO native confidence field — FLAGGED (not fabricated). Law-2 confidence-honesty is
# unmeasurable for these until a confidence signal is defined; the gate accepts null confidence here.
NO_CONFIDENCE_FAMILIES: set = {
    ("production_vor", "point"),
    ("player_signal", "direction"),   # brief lists none; `reliability` is a candidate, surfaced not wired
    ("bracket_odds", "point"),        # proj_wins
    ("bracket_odds", "ordinal"),      # avg_seed
}

# The 9 families. `source` = the read whose persisted frame feeds this family; `subject_id` = source
# column(s) namespaced with ":"; `confidence`/`confidence_label`/`confidence_json` per the mapping table.
# `lo`/`hi`/`sigma` set only for the interval family.
FAMILIES: list[dict] = [
    {"source": "production_vor", "read": "production_vor", "subject_type": "player",
     "subject_id": ("roster_id", "sleeper_player_id"), "claim_type": "point", "value": "ros_value",
     "horizon": "ros", "resolves_at": "season_end",
     "confidence": None, "confidence_label": None, "confidence_json": None},

    {"source": "ros_player_band", "read": "ros_player_band", "subject_type": "player",
     "subject_id": ("sleeper_player_id",), "claim_type": "interval", "value": "ros_center",
     "lo": "ros_bear", "hi": "ros_bull", "sigma": "ros_sigma",
     "horizon": "ros", "resolves_at": "season_end",
     # Session 8c: the shipped confidence signal is the raw-points spread ros_sigma (the proven-honest signal);
     # the percentage ros_cv (proven INVERTED, S5) retires to the confidence_json audit column, not dropped.
     "confidence": "ros_sigma", "confidence_label": "ros_sigma", "confidence_json": ["ros_cv"]},

    {"source": "player_signal", "read": "player_signal", "subject_type": "player",
     "subject_id": ("roster_id", "sleeper_player_id"), "claim_type": "point", "value": "expected_ppg",
     "horizon": "week", "resolves_at": "weekly",
     "confidence": "regression_risk", "confidence_label": "regression_risk",
     "confidence_json": ["reliability", "read", "security", "point_correlation"]},

    {"source": "player_signal", "read": "player_signal", "subject_type": "player",
     "subject_id": ("roster_id", "sleeper_player_id"), "claim_type": "direction", "value": "direction",
     "horizon": "week", "resolves_at": "weekly",
     "confidence": None, "confidence_label": None, "confidence_json": None},

    {"source": "true_rank", "read": "true_rank", "subject_type": "roster",
     "subject_id": ("roster_id",), "claim_type": "ordinal", "value": "rank",
     "horizon": "season", "resolves_at": "season_end",
     "confidence": "spectrum_pos", "confidence_label": "spectrum_pos", "confidence_json": None},

    {"source": "positional_depth", "read": "positional_depth", "subject_type": "roster",
     "subject_id": ("roster_id", "position"), "claim_type": "point", "value": "surplus_value",
     "horizon": "season", "resolves_at": "season_end",
     "confidence": "spectrum_pos", "confidence_label": "spectrum_pos", "confidence_json": ["shape"]},

    {"source": "bracket_odds", "read": "bracket_odds", "subject_type": "roster",
     "subject_id": ("roster_id",), "claim_type": "probability", "value": "playoff_odds",
     "horizon": "season", "resolves_at": "season_end",
     "confidence": "playoff_odds", "confidence_label": "playoff_odds", "confidence_json": None},

    {"source": "bracket_odds", "read": "bracket_odds", "subject_type": "roster",
     "subject_id": ("roster_id",), "claim_type": "point", "value": "proj_wins",
     "horizon": "season", "resolves_at": "season_end",
     "confidence": None, "confidence_label": None, "confidence_json": None},

    {"source": "bracket_odds", "read": "bracket_odds", "subject_type": "roster",
     "subject_id": ("roster_id",), "claim_type": "ordinal", "value": "avg_seed",
     "horizon": "season", "resolves_at": "season_end",
     "confidence": None, "confidence_label": None, "confidence_json": None},
]

# Which reads each stratum of the driver reads once per league / per scoring-key.
LEAGUE_SOURCES = ["production_vor", "player_signal", "true_rank", "positional_depth", "bracket_odds"]
BAND_SOURCE = "ros_player_band"


def _subject_id_expr(cols: tuple) -> pl.Expr:
    return pl.concat_str([pl.col(c).cast(pl.Utf8) for c in cols], separator=":")


def build_family(src: pl.DataFrame, spec: dict, ctx: dict) -> pl.DataFrame:
    """Reshape one source read frame into one claim family's rows (the canonical CLAIM_COLS)."""
    ct = spec["claim_type"]
    scope_key = ctx["league_id"] if ctx["league_id"] is not None else ctx["scoring_key"]

    # value / value_str — XOR by claim_type
    if ct == "direction":
        value_expr = pl.lit(None, dtype=pl.Float64).alias("value")
        value_str_expr = pl.col(spec["value"]).cast(pl.Utf8).alias("value_str")
    else:
        value_expr = pl.col(spec["value"]).cast(pl.Float64).alias("value")
        value_str_expr = pl.lit(None, dtype=pl.Utf8).alias("value_str")

    def _f64(field):
        return (pl.col(spec[field]).cast(pl.Float64) if spec.get(field)
                else pl.lit(None, dtype=pl.Float64)).alias(field)

    conf = (pl.col(spec["confidence"]).cast(pl.Float64) if spec.get("confidence")
            else pl.lit(None, dtype=pl.Float64)).alias("confidence")
    conf_label = pl.lit(spec.get("confidence_label"), dtype=pl.Utf8).alias("confidence_label")
    conf_json = (pl.struct(spec["confidence_json"]).struct.json_encode() if spec.get("confidence_json")
                 else pl.lit(None, dtype=pl.Utf8)).alias("confidence_json")

    frame = src.select(
        pl.col("as_of_week").cast(pl.Int64).alias("as_of_week"),
        _subject_id_expr(spec["subject_id"]).alias("subject_id"),
        value_expr, value_str_expr,
        _f64("lo"), _f64("hi"), _f64("sigma"),
        conf, conf_label, conf_json,
    )
    # A claim needs a subject and a value — drop rows the source left null (report at the driver).
    claim_val = "value_str" if ct == "direction" else "value"
    frame = frame.filter(pl.col("subject_id").is_not_null() & pl.col(claim_val).is_not_null())

    frame = frame.with_columns(
        pl.lit(ctx["league_id"], dtype=pl.Utf8).alias("league_id"),
        pl.lit(ctx["scoring_key"], dtype=pl.Utf8).alias("scoring_key"),
        pl.lit(ctx["season"], dtype=pl.Int64).alias("season"),
        pl.lit(spec["read"], dtype=pl.Utf8).alias("read"),
        pl.lit(spec["subject_type"], dtype=pl.Utf8).alias("subject_type"),
        pl.lit(ct, dtype=pl.Utf8).alias("claim_type"),
        pl.lit(spec["horizon"], dtype=pl.Utf8).alias("horizon"),
        pl.lit(spec["resolves_at"], dtype=pl.Utf8).alias("resolves_at"),
        pl.lit(ctx["code_version"], dtype=pl.Utf8).alias("code_version"),
        pl.lit(ctx["constants_hash"], dtype=pl.Utf8).alias("constants_hash"),
        pl.lit(None, dtype=pl.Utf8).alias("prompt_version"),
        pl.lit(None, dtype=pl.Utf8).alias("model"),
        pl.lit(ctx["inputs_ok"], dtype=pl.Boolean).alias("inputs_ok"),
        pl.lit(False, dtype=pl.Boolean).alias("served"),
        pl.lit(None, dtype=pl.Utf8).alias("created_at"),
    )
    # prediction_id — stable sha1[:16] over the key; machine-independent, never wall-clock. Adds `season`
    # and `claim_type` to the §L2 key: `season` because the scoring-scoped band spans every season (the
    # same (scoring_key, player, week) claim recurs each year and must NOT collapse to one id — §L2 leaned
    # on season-partitioning, but a claim id must be globally unique); `claim_type` because one read emits
    # several claim families per subject-week (bracket_odds → 3) that would otherwise collide.
    keys = frame.select(pl.concat_str([
        pl.lit(str(scope_key)), pl.col("season").cast(pl.Utf8), pl.col("read"), pl.col("subject_id"),
        pl.col("as_of_week").cast(pl.Utf8), pl.col("horizon"), pl.col("claim_type"),
        pl.lit(str(ctx["code_version"])),
    ], separator="|")).to_series()
    ids = [hashlib.sha1(k.encode()).hexdigest()[:16] for k in keys]
    frame = frame.with_columns(pl.Series("prediction_id", ids, dtype=pl.Utf8))
    return frame.select(CLAIM_COLS)


def build_league_claims(frames: dict, ctx: dict) -> pl.DataFrame:
    """The 8 league-scoped claim families (production_vor · player_signal ×2 · true_rank ·
    positional_depth · bracket_odds ×3) for one league-season. `frames` maps source read → its frame."""
    parts = [build_family(frames[spec["source"]], spec, ctx)
             for spec in FAMILIES if spec["source"] in LEAGUE_SOURCES]
    return pl.concat(parts, how="vertical")


def build_band_claims(band_df: pl.DataFrame, ctx: dict) -> pl.DataFrame:
    """The single scoring-scoped interval family (ros_player_band), emitted once per (scoring_key,
    season) with `league_id=null`. `ctx["league_id"]` MUST be None."""
    assert ctx["league_id"] is None, "band claims carry league_id=null"
    spec = next(s for s in FAMILIES if s["source"] == BAND_SOURCE)
    return build_family(band_df, spec, ctx)
