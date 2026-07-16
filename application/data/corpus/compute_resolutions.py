"""
compute_resolutions.py — join the claims to realized truth + attach the grading PRIMITIVES (Session 4b, C2).

Joins `predictions_{season} ⋈ outcomes_{season}` per the claim→outcome→primitive mapping, HORIZON-CORRECT
(each family joins the right realized window), and writes `resolutions_{season}` — one row per claim,
carrying `truth` + the primitives (`error`/`abs_error`, `in_band`, `pit`, `brier`, `rank_error`,
`direction_hit`) + the claim's full provenance. It computes primitives; it does NOT grade. **No verdict,
no aggregate score, no `claim_correct`, no `suppress`** — a per-row `pit=0.97` is a primitive, not a
judgement; the scorer (Session 5) is the first thing that judges, and only over DISTRIBUTIONS (standing
instr 4). Law 1 is structural.

Design (the ★ forks, per the brief + the C1 scoping finding):
  • **PIT only where a distribution is stated** — interval (band: center + sigma) and probability
    (playoff_odds → the deterministic mid-PIT for a Bernoulli). Point / ordinal / direction get `pit=null`
    and their native primitive. No fabricated sigma for a point claim (the anti-law-2 move).
  • **Horizon-correct windows**: production_vor / band (ros) → Σ realized points weeks ≥ as_of;
    player_signal point/direction (weekly) → the forward weeks > as_of; true_rank / bracket_odds (season)
    → the season-end roster facts. positional_depth (season) → Σ realized roster×position points weeks ≥
    as_of (the ★ fuzzy answer key — graded on its clean subset, coverage FLAGGED).
  • **Scope-correct truth (C1 finding)**: league-scoped point claims (production_vor, player_signal,
    positional_depth) resolve against their LEAGUE's realized points; the scoring-scoped band resolves
    against the canonical scoring-scoped series it was projected under.
  • **Unresolved is named, not dropped, not a fake zero** — a claim whose subject has no realized window
    (dropped / injured / no forward games) resolves with a `unresolved_reason`, counted per family.

Each claim resolves to EXACTLY ONE outcome (1:1 on `prediction_id`); asserted. Report per-family primitive
distributions as a FIRST LOOK, explicitly "not a grade".

Usage:
    python3 -m application.data.corpus.compute_resolutions --season 2023   # one season
    python3 -m application.data.corpus.compute_resolutions                  # all spined seasons
"""
import argparse
import hashlib
import math
import sys
import time

import numpy as np
import polars as pl

from application.data import data_layer

SPINED_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)

# Realized momentum-band for the `direction` primitive: forward-vs-recent ppg change beyond this →
# rising/fading, else steady. A relative band with an absolute floor (documented modelling choice; the
# scorer aggregates the hit-rate, it is not a verdict).
_DIR_REL = 0.15
_DIR_ABS = 1.5

RESOLUTION_COLS = [
    "resolution_id", "prediction_id", "league_id", "scoring_key", "season", "as_of_week",
    "read", "claim_type", "subject_id", "horizon", "resolves_at",
    "code_version", "constants_hash", "inputs_ok", "served",
    "truth", "error", "abs_error", "in_band", "pit", "brier", "rank_error", "direction_hit",
    "resolved", "unresolved_reason", "coverage_flag", "recorded_at",
]
# The primitive columns each resolver fills (others null); carried onto every claim of the family.
_PRIM_COLS = ["prediction_id", "truth", "error", "abs_error", "in_band", "pit", "brier",
             "rank_error", "direction_hit", "resolved", "unresolved_reason", "coverage_flag"]

try:                                            # a vectorised Gaussian CDF for PIT
    from scipy.special import erf as _erf       # noqa: F401
    def _erf_vec(a):
        return _erf(a)
except Exception:                               # noqa: BLE001 — scipy optional; math.erf is always there
    _erf_e = np.vectorize(math.erf)
    def _erf_vec(a):
        return _erf_e(a)


def _norm_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + _erf_vec(z / math.sqrt(2.0)))


def _det_uniform(pid: str) -> float:
    """A DETERMINISTIC uniform in [0,1) from a claim's `prediction_id` — a pure sha of the id, never
    wall-clock, so a twice-compute is value-identical. Used to seed the randomized PIT of a Bernoulli
    (playoff_odds), which is Uniform(0,1) under calibration — the continuous-PIT analog that makes the
    scorer's ONE PIT-uniformity test valid for the probability family too."""
    return int.from_bytes(hashlib.blake2b(pid.encode(), digest_size=8).digest(), "big") / 2.0 ** 64


def _empty_prim() -> pl.DataFrame:
    return pl.DataFrame(schema={
        "prediction_id": pl.Utf8, "truth": pl.Float64, "error": pl.Float64, "abs_error": pl.Float64,
        "in_band": pl.Float64, "pit": pl.Float64, "brier": pl.Float64, "rank_error": pl.Float64,
        "direction_hit": pl.Float64, "resolved": pl.Boolean,
        "unresolved_reason": pl.Utf8, "coverage_flag": pl.Utf8,
    })


def _prim(df: pl.DataFrame) -> pl.DataFrame:
    """Coerce a resolver's frame to the full primitive schema (missing primitives → typed null)."""
    out = df
    defaults = {"truth": None, "error": None, "abs_error": None, "in_band": None, "pit": None,
                "brier": None, "rank_error": None, "direction_hit": None,
                "unresolved_reason": None, "coverage_flag": None}
    for c, d in defaults.items():
        if c not in out.columns:
            dt = pl.Utf8 if c in ("unresolved_reason", "coverage_flag") else pl.Float64
            out = out.with_columns(pl.lit(d, dtype=dt).alias(c))
    if "resolved" not in out.columns:
        out = out.with_columns(pl.col("truth").is_not_null().alias("resolved"))
    return out.select(_PRIM_COLS)


# ---------------------------------------------------------------------------------------------------
# Per-family resolvers — each returns the _PRIM schema, one row per claim in the family
# ---------------------------------------------------------------------------------------------------

def _sum_forward_points(claims: pl.DataFrame, pts: pl.DataFrame, join_on: list, *,
                        strict: bool) -> pl.DataFrame:
    """truth = Σ realized points over the forward window, per claim. `claims` carries `prediction_id`,
    `as_of_week`, and the join keys; `pts` carries the join keys + `week` + `pts`. `strict` → weeks >
    as_of (weekly forward); else weeks ≥ as_of (ROS). Claims with no qualifying week → truth null."""
    j = claims.join(pts, on=join_on, how="left")
    cond = (pl.col("week") > pl.col("as_of_week")) if strict else (pl.col("week") >= pl.col("as_of_week"))
    truth = (j.filter(pl.col("week").is_not_null() & cond)
              .group_by("prediction_id").agg(pl.col("pts").sum().alias("truth")))
    return claims.select("prediction_id").join(truth, on="prediction_id", how="left")


def resolve_production_vor(preds: pl.DataFrame, pwp_l: pl.DataFrame) -> pl.DataFrame:
    c = (preds.filter(pl.col("read") == "production_vor")
              .with_columns(pl.col("subject_id").str.split(":").list.get(1).alias("pid"))
              .select("prediction_id", "league_id", "pid", "as_of_week", "value"))
    if not c.height:
        return _empty_prim()
    pts = pwp_l.select("league_id", pl.col("subject_id").alias("pid"), "week", pl.col("value").alias("pts"))
    truth = _sum_forward_points(c, pts, ["league_id", "pid"], strict=False)
    out = c.join(truth, on="prediction_id", how="left").with_columns(
        (pl.col("value") - pl.col("truth")).alias("error"),
        (pl.col("value") - pl.col("truth")).abs().alias("abs_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null())
          .then(pl.lit("no realized ROS points in league (weeks ≥ as_of; dropped/injured/season over)"))
          .otherwise(None).alias("unresolved_reason"),
    )
    return _prim(out)


def resolve_band(preds: pl.DataFrame, pwp_c: pl.DataFrame) -> pl.DataFrame:
    c = (preds.filter(pl.col("read") == "ros_player_band")
              .select("prediction_id", "scoring_key", pl.col("subject_id").alias("pid"),
                      "as_of_week", "value", "lo", "hi", "sigma"))
    if not c.height:
        return _empty_prim()
    pts = pwp_c.select("scoring_key", pl.col("subject_id").alias("pid"), "week", pl.col("value").alias("pts"))
    truth = _sum_forward_points(c, pts, ["scoring_key", "pid"], strict=False)
    out = c.join(truth, on="prediction_id", how="left")
    # PIT via the stated Gaussian (center + sigma); in_band via [lo, hi]. Only for resolved rows.
    r = out.filter(pl.col("truth").is_not_null())
    pit_vals = {}
    if r.height:
        z = ((r["truth"] - r["value"]) / r["sigma"].fill_null(0.0).replace(0.0, float("nan"))).to_numpy()
        pit = _norm_cdf(z)
        pit_vals = dict(zip(r["prediction_id"].to_list(), [None if (x != x) else float(x) for x in pit]))
    out = out.with_columns(
        pl.when((pl.col("truth") >= pl.col("lo")) & (pl.col("truth") <= pl.col("hi"))).then(1.0)
          .when(pl.col("truth").is_not_null()).then(0.0).otherwise(None).alias("in_band"),
        pl.col("prediction_id").replace_strict(pit_vals, default=None, return_dtype=pl.Float64).alias("pit"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null())
          .then(pl.lit("no realized ROS points for player under scoring_key (weeks ≥ as_of)"))
          .otherwise(None).alias("unresolved_reason"),
    )
    return _prim(out)


def resolve_player_signal_point(preds: pl.DataFrame, pwp_l: pl.DataFrame) -> pl.DataFrame:
    c = (preds.filter((pl.col("read") == "player_signal") & (pl.col("claim_type") == "point"))
              .with_columns(pl.col("subject_id").str.split(":").list.get(1).alias("pid"))
              .select("prediction_id", "league_id", "pid", "as_of_week", "value"))
    if not c.height:
        return _empty_prim()
    pts = pwp_l.select("league_id", pl.col("subject_id").alias("pid"), "week", pl.col("value").alias("pts"))
    j = c.join(pts, on=["league_id", "pid"], how="left")
    fwd = (j.filter(pl.col("week").is_not_null() & (pl.col("week") > pl.col("as_of_week")))
            .group_by("prediction_id").agg(pl.col("pts").mean().alias("truth")))   # forward PPG = mean
    out = c.join(fwd, on="prediction_id", how="left").with_columns(
        (pl.col("value") - pl.col("truth")).alias("error"),
        (pl.col("value") - pl.col("truth")).abs().alias("abs_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null())
          .then(pl.lit("no realized forward games (weeks > as_of) in league")).otherwise(None)
          .alias("unresolved_reason"),
    )
    return _prim(out)


def resolve_player_signal_direction(preds: pl.DataFrame, pwp_l: pl.DataFrame) -> pl.DataFrame:
    c = (preds.filter((pl.col("read") == "player_signal") & (pl.col("claim_type") == "direction"))
              .with_columns(pl.col("subject_id").str.split(":").list.get(1).alias("pid"))
              .select("prediction_id", "league_id", "pid", "as_of_week", "value_str"))
    if not c.height:
        return _empty_prim()
    pts = pwp_l.select("league_id", pl.col("subject_id").alias("pid"), "week", pl.col("value").alias("pts"))
    j = c.join(pts, on=["league_id", "pid"], how="left")
    recent = (j.filter(pl.col("week").is_not_null() & (pl.col("week") <= pl.col("as_of_week")))
               .group_by("prediction_id").agg(pl.col("pts").mean().alias("recent")))
    forward = (j.filter(pl.col("week").is_not_null() & (pl.col("week") > pl.col("as_of_week")))
                .group_by("prediction_id").agg(pl.col("pts").mean().alias("forward")))
    m = c.join(recent, on="prediction_id", how="left").join(forward, on="prediction_id", how="left")
    thr = pl.max_horizontal(pl.lit(_DIR_ABS), (_DIR_REL * pl.col("recent").abs()))
    delta = pl.col("forward") - pl.col("recent")
    realized_dir = (pl.when(delta > thr).then(pl.lit("rising"))
                      .when(delta < -thr).then(pl.lit("fading"))
                      .otherwise(pl.lit("steady")))
    resolvable = pl.col("recent").is_not_null() & pl.col("forward").is_not_null()
    out = m.with_columns(
        pl.when(resolvable & (realized_dir == pl.col("value_str"))).then(1.0)
          .when(resolvable).then(0.0).otherwise(None).alias("direction_hit"),
        resolvable.alias("resolved"),
        pl.when(~resolvable).then(pl.lit("no recent and/or forward games to sign the trend"))
          .otherwise(None).alias("unresolved_reason"),
    )
    return _prim(out)


def _roster_fact(preds: pl.DataFrame, fact: pl.DataFrame, read: str, claim_type: str) -> pl.DataFrame:
    """The season-level roster join: truth = the single roster fact for (league_id, roster_id=subject_id)."""
    c = (preds.filter((pl.col("read") == read) & (pl.col("claim_type") == claim_type))
              .select("prediction_id", "league_id", pl.col("subject_id"), "value"))
    f = fact.select("league_id", "subject_id", pl.col("value").alias("truth"))
    return c.join(f, on=["league_id", "subject_id"], how="left")


def resolve_true_rank(preds: pl.DataFrame, fstd: pl.DataFrame) -> pl.DataFrame:
    out = _roster_fact(preds, fstd, "true_rank", "ordinal")
    if not out.height:
        return _empty_prim()
    out = out.with_columns(
        (pl.col("value") - pl.col("truth")).alias("rank_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null()).then(pl.lit("no realized final standing for roster"))
          .otherwise(None).alias("unresolved_reason"))
    return _prim(out)


def resolve_positional_depth(preds: pl.DataFrame, rpp: pl.DataFrame) -> pl.DataFrame:
    c = (preds.filter(pl.col("read") == "positional_depth")
              .select("prediction_id", "league_id", "subject_id", "as_of_week", "value"))
    if not c.height:
        return _empty_prim()
    pts = rpp.select("league_id", "subject_id", "week", pl.col("value").alias("pts"))
    truth = _sum_forward_points(c, pts, ["league_id", "subject_id"], strict=False)   # weeks ≥ as_of
    out = c.join(truth, on="prediction_id", how="left").with_columns(
        (pl.col("value") - pl.col("truth")).alias("error"),
        (pl.col("value") - pl.col("truth")).abs().alias("abs_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.lit("positional_depth ★: surplus_value vs realized roster×position pts is an approximate "
               "answer key (§6) — graded on the clean subset").alias("coverage_flag"),
        pl.when(pl.col("truth").is_null())
          .then(pl.lit("no realized points at that roster×position (weeks ≥ as_of) — clean-subset gap"))
          .otherwise(None).alias("unresolved_reason"))
    return _prim(out)


def resolve_bracket_prob(preds: pl.DataFrame, mp: pl.DataFrame) -> pl.DataFrame:
    out = _roster_fact(preds, mp, "bracket_odds", "probability")
    if not out.height:
        return _empty_prim()
    # brier = (p − y)². PIT = the randomized PIT of a Bernoulli(p), Uniform(0,1) under calibration:
    #   y=1 → (1−p) + U·p ;  y=0 → U·(1−p),  with U a DETERMINISTIC uniform seeded by prediction_id.
    u = np.array([_det_uniform(pid) for pid in out["prediction_id"].to_list()])
    out = out.with_columns(pl.Series("u", u))
    out = out.with_columns(
        ((pl.col("value") - pl.col("truth")) ** 2).alias("brier"),
        pl.when(pl.col("truth") == 1.0).then((1.0 - pl.col("value")) + pl.col("u") * pl.col("value"))
          .when(pl.col("truth") == 0.0).then(pl.col("u") * (1.0 - pl.col("value")))
          .otherwise(None).alias("pit"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null()).then(pl.lit("no realized made-playoffs fact for roster"))
          .otherwise(None).alias("unresolved_reason"))
    return _prim(out)


def resolve_bracket_wins(preds: pl.DataFrame, wins: pl.DataFrame) -> pl.DataFrame:
    out = _roster_fact(preds, wins, "bracket_odds", "point")
    if not out.height:
        return _empty_prim()
    out = out.with_columns(
        (pl.col("value") - pl.col("truth")).alias("error"),
        (pl.col("value") - pl.col("truth")).abs().alias("abs_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null()).then(pl.lit("no realized wins for roster"))
          .otherwise(None).alias("unresolved_reason"))
    return _prim(out)


def resolve_bracket_seed(preds: pl.DataFrame, fstd: pl.DataFrame) -> pl.DataFrame:
    out = _roster_fact(preds, fstd, "bracket_odds", "ordinal")
    if not out.height:
        return _empty_prim()
    out = out.with_columns(
        (pl.col("value") - pl.col("truth")).alias("rank_error"),
        pl.col("truth").is_not_null().alias("resolved"),
        pl.when(pl.col("truth").is_null()).then(pl.lit("no realized final seed for roster"))
          .otherwise(None).alias("unresolved_reason"))
    return _prim(out)


# ---------------------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------------------

def resolve_season(season: int) -> pl.DataFrame:
    """Build the full `resolutions_{season}` frame (one row per claim), horizon-correct, with provenance."""
    preds = data_layer.read_predictions(season)
    pwp_l = data_layer.read_outcomes(season, outcome_type="player_weekly_pts")
    pwp_c = data_layer.read_outcomes(season, outcome_type="player_weekly_pts_canonical")
    rpp = data_layer.read_outcomes(season, outcome_type="roster_position_pts")
    wins = data_layer.read_outcomes(season, outcome_type="roster_wins")
    fstd = data_layer.read_outcomes(season, outcome_type="roster_final_standing")
    mp = data_layer.read_outcomes(season, outcome_type="roster_made_playoffs")

    prim = pl.concat([
        resolve_production_vor(preds, pwp_l),
        resolve_band(preds, pwp_c),
        resolve_player_signal_point(preds, pwp_l),
        resolve_player_signal_direction(preds, pwp_l),
        resolve_true_rank(preds, fstd),
        resolve_positional_depth(preds, rpp),
        resolve_bracket_prob(preds, mp),
        resolve_bracket_wins(preds, wins),
        resolve_bracket_seed(preds, fstd),
    ], how="vertical")

    # Join integrity: exactly one primitive row per claim (no cartesian blow-up, no silent drop).
    assert prim.height == preds.height, f"resolutions {prim.height} != claims {preds.height} (season {season})"
    assert prim["prediction_id"].n_unique() == prim.height, "duplicate prediction_id in resolutions"

    res = preds.select(
        "prediction_id", "league_id", "scoring_key", "season", "as_of_week", "read", "claim_type",
        "subject_id", "horizon", "resolves_at", "code_version", "constants_hash", "inputs_ok", "served",
    ).join(prim, on="prediction_id", how="left").with_columns(
        pl.col("prediction_id").alias("resolution_id"),
        pl.lit(None, dtype=pl.Utf8).alias("recorded_at"),
    )
    return res.select(RESOLUTION_COLS)


def run(seasons=SPINED_SEASONS) -> dict:
    t0 = time.time()
    seasons = [s for s in seasons if data_layer.predictions_exists(s) and data_layer.outcomes_exists(s)]
    rows_written = 0
    per_family = {}   # (read, claim_type) -> accumulated frame for the report
    for season in seasons:
        before = data_layer.read_resolutions(season).height if data_layer.resolutions_exists(season) else 0
        res = resolve_season(season)
        data_layer.write_resolutions(res, season)
        after = data_layer.read_resolutions(season).height
        rows_written += after - before
        for (read, ct), g in res.group_by("read", "claim_type"):
            key = (read, ct)
            per_family[key] = pl.concat([per_family[key], g]) if key in per_family else g
        print(f"  season {season}: {res.height:,} resolutions computed ({after - before:,} newly appended; "
              f"append-only-of-new)")

    report = {"seasons": seasons, "rows_written": rows_written,
              "elapsed_s": round(time.time() - t0, 1), "per_family": per_family,
              "file_sizes": {s: round(__import__("os").path.getsize(data_layer._resolutions_path(s)) / 1e6, 2)
                             for s in seasons if data_layer.resolutions_exists(s)}}
    _print_report(report)
    return report


def _pit_hist(vals: pl.Series) -> str:
    v = vals.drop_nulls().to_numpy()
    if not len(v):
        return "n/a"
    h, _ = np.histogram(v, bins=10, range=(0.0, 1.0))
    return " ".join(str(int(x)) for x in h) + f"  (n={len(v)})"


def _print_report(rep: dict) -> None:
    print("\n=== resolutions report — FIRST LOOK, NOT A GRADE (the scorer, Session 5, judges) ===")
    print(f"  seasons={rep['seasons']}  rows={rep['rows_written']:,}  wall-clock={rep['elapsed_s']}s")
    print("  per-family primitive distributions (report, not verdict):")
    for (read, ct), g in sorted(rep["per_family"].items()):
        n = g.height
        rsv = int(g["resolved"].sum())
        unr = n - rsv
        line = f"    {read:16}/{ct:12} n={n:>7} resolved={rsv:>7} unresolved={unr:>6}"
        r = g.filter(pl.col("resolved"))
        bits = []
        if r["abs_error"].drop_nulls().len():
            bits.append(f"MAE={round(r['abs_error'].mean(),2)} medErr={round(r['error'].median(),2)}")
        if r["in_band"].drop_nulls().len():
            bits.append(f"in_band={round(r['in_band'].mean(),3)}")
        if r["pit"].drop_nulls().len():
            bits.append(f"PIT[{_pit_hist(r['pit'])}]")
        if r["brier"].drop_nulls().len():
            bits.append(f"Brier={round(r['brier'].mean(),3)}")
        if r["rank_error"].drop_nulls().len():
            bits.append(f"rankErr med={round(r['rank_error'].median(),1)} MAE={round(r['rank_error'].abs().mean(),2)}")
        if r["direction_hit"].drop_nulls().len():
            bits.append(f"dir_hit={round(r['direction_hit'].mean(),3)}")
        print(line)
        if bits:
            print(f"        {' · '.join(bits)}")
    # surface anything alarming as a FINDING (no verdict, no constant change)
    print("  findings (surfaced, not graded):")
    for (read, ct), g in sorted(rep["per_family"].items()):
        r = g.filter(pl.col("resolved"))
        if r["error"].drop_nulls().len() and abs(r["error"].median()) > 5:
            print(f"    · {read}/{ct}: median error {round(r['error'].median(),1)} — projection bias (report only)")
        if r["pit"].drop_nulls().len():
            v = r["pit"].drop_nulls().to_numpy()
            edge = float(((v < 0.1) | (v > 0.9)).mean())
            if edge > 0.35:
                print(f"    · {read}/{ct}: {round(edge*100)}% of PIT at the [0,0.1]∪[0.9,1] edges — calibration signal")


def main():
    ap = argparse.ArgumentParser(description="Compute the L2 resolutions ledger (Session 4b).")
    ap.add_argument("--season", type=int, default=None, help="one season (default: all spined)")
    a = ap.parse_args()
    run((a.season,) if a.season else SPINED_SEASONS)


if __name__ == "__main__":
    main()
    sys.exit(0)
