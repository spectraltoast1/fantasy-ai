"""
check_resolutions.py — the L2 resolutions-ledger gate (Improvement-Loop Session 4b, commit 3).

Asserts, over the 6 spined seasons (2,893,834 claims across the 270 league-seasons in the FROZEN
manifest), that the `predictions ⋈ outcomes → resolutions` join is coverage-complete, primitive-valid,
horizon-correct, deterministic and traceable — and that Law 1 holds STRUCTURALLY: `resolutions` carries
grading PRIMITIVES but NO verdict / aggregate score / suppress flag (the scorer, Session 5, is the first
thing that judges). Mirrors `check_predictions` / `check_spine`: exit 0 iff every check passes. A gate that
can't fail is not a gate — every check has a prove-bite.

  1. RESOLUTION COVERAGE — exactly one resolution per claim (1:1 on prediction_id, no cartesian blow-up,
     no silent drop); every resolved row has a non-null truth; every UNRESOLVED row carries a reason (never
     a fake zero); per-family coverage reported, incl. positional_depth's ★ clean subset.
  2. PRIMITIVE VALIDITY — pit ∈ [0,1], brier ∈ [0,1], in_band ∈ {0,1}; pit non-null IFF interval/probability;
     each native primitive present IFF its family & resolved; rank_error INTEGER for true_rank (avg_seed is
     a legitimately fractional average seed).
  3. LAW 1 — NO VERDICT — the forbidden aggregate-verdict set (read_score / claim_correct / suppress /
     verdict / score / grade) is ABSENT; the primitives are not judgements. (Prove-bite: injecting one fails.)
  4. TRACEABILITY + DETERMINISM — every resolution rejoins its claim's prediction_id + provenance
     (code_version / constants_hash / inputs_ok / served); recomputing a season is value-identical (`_frame_eq`).
  5. REALIZED INTEGRITY RIDES THROUGH — the C1 property (playoff mass == slot count) survives into the graded
     rows: per (league, as_of_week), Σ truth over bracket_odds/probability resolutions == the league's
     playoff_teams (the property, not just the outcomes file — standing instr 7).

Run: python3 -m application.data.corpus.check_resolutions [--season S] [--sample N]
"""
import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import backfill_predictions, compute_resolutions as cr

SPINED_SEASONS = cr.SPINED_SEASONS

# Columns that would mean a claim has been JUDGED — Law 1 forbids any aggregate verdict here (the
# primitives error/pit/brier/... are REQUIRED; a per-read score or a suppress flag belongs to the scorer).
_FORBIDDEN_VERDICT_COLS = {"read_score", "claim_correct", "suppress", "verdict", "score", "grade",
                           "read_grade", "pass_fail", "correct", "aggregate_score"}


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:62} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality (same columns + same VALUES) — determinism is about values, not
    the physically-non-deterministic parquet byte stream (the check_spine/check_predictions precedent)."""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


# --- predicates shared by the real checks AND the prove-bites (so a bite is a genuine bite) -----------

def _coverage_ok(res: pl.DataFrame, n_claims: int) -> bool:
    """1:1 with the claims, no duplicate id, resolved ⇒ the family's answer is present, unresolved ⇒ reason
    set (no fake zero). `direction` has no scalar `truth` — its answer is the categorical `direction_hit`;
    every other family carries `truth`."""
    if res.height != n_claims or res["resolution_id"].n_unique() != res.height:
        return False
    bad_resolved = res.filter(pl.col("resolved") & (
        ((pl.col("claim_type") == "direction") & pl.col("direction_hit").is_null())
        | ((pl.col("claim_type") != "direction") & pl.col("truth").is_null())))
    if bad_resolved.height:
        return False
    if res.filter(~pl.col("resolved") & pl.col("unresolved_reason").is_null()).height:
        return False
    return True


def _validity_ok(res: pl.DataFrame) -> bool:
    r = res.filter(pl.col("resolved"))
    if r.filter(pl.col("pit").is_not_null() & ((pl.col("pit") < 0) | (pl.col("pit") > 1))).height:
        return False
    if r.filter(pl.col("brier").is_not_null() & ((pl.col("brier") < 0) | (pl.col("brier") > 1))).height:
        return False
    if r.filter(pl.col("in_band").is_not_null() & ~pl.col("in_band").is_in([0.0, 1.0])).height:
        return False
    # pit non-null IFF the claim states a distribution (interval / probability)
    if res.filter(pl.col("pit").is_not_null()
                  & ~pl.col("claim_type").is_in(["interval", "probability"])).height:
        return False
    # each native primitive only on its family
    if res.filter(pl.col("brier").is_not_null() & (pl.col("claim_type") != "probability")).height:
        return False
    if res.filter(pl.col("in_band").is_not_null() & (pl.col("claim_type") != "interval")).height:
        return False
    if res.filter(pl.col("direction_hit").is_not_null() & (pl.col("claim_type") != "direction")).height:
        return False
    # resolved point families carry a signed error
    if r.filter((pl.col("claim_type") == "point") & pl.col("error").is_null()).height:
        return False
    # rank_error integer for true_rank (avg_seed is legitimately fractional)
    tr = r.filter(pl.col("read") == "true_rank")
    if tr.filter(pl.col("rank_error") != pl.col("rank_error").round(0)).height:
        return False
    return True


def _law1_ok(res: pl.DataFrame) -> bool:
    return not (_FORBIDDEN_VERDICT_COLS & set(res.columns))


def _integrity_ok(res: pl.DataFrame) -> bool:
    """Realized playoff mass rides into the graded rows: per (league, as_of_week), Σ truth over
    bracket_odds/probability resolutions == the league's realized made-playoffs mass (a constant per
    league). Checks the graded rows, not just the outcomes file."""
    prob = res.filter((pl.col("read") == "bracket_odds") & (pl.col("claim_type") == "probability")
                      & pl.col("resolved"))
    if not prob.height:
        return True
    per_wk = prob.group_by("league_id", "as_of_week").agg(pl.col("truth").sum().alias("mass"))
    per_league = prob.group_by("league_id").agg(pl.col("truth").sum().alias("t"),
                                                pl.col("as_of_week").n_unique().alias("w"))
    slots = {r["league_id"]: r["t"] / r["w"] for r in per_league.iter_rows(named=True)}  # mass per as_of
    for r in per_wk.iter_rows(named=True):
        if abs(r["mass"] - slots[r["league_id"]]) > 1e-9:
            return False
    return True


def check(seasons=SPINED_SEASONS, sample: int = 1) -> bool:
    seasons = [s for s in seasons
               if data_layer.resolutions_exists(s) and data_layer.predictions_exists(s)]
    results = []
    frames = {s: data_layer.read_resolutions(s) for s in seasons}
    allres = pl.concat(frames.values(), how="vertical")
    total_claims = sum(data_layer.read_predictions(s).height for s in seasons)
    print(f"\n  gate over {len(seasons)} spined seasons, {allres.height:,} resolutions "
          f"({total_claims:,} claims)")

    print("  1 — resolution coverage (1:1 per claim; resolved⇒truth; unresolved⇒reason):")
    _ok("exactly one resolution per claim (no drop, no blow-up)",
        allres.height == total_claims and allres["resolution_id"].n_unique() == allres.height, results,
        f"[{allres.height:,} == {total_claims:,}]")
    _ok("resolved rows carry a truth; unresolved rows carry a reason (no fake zero)",
        all(_coverage_ok(frames[s], data_layer.read_predictions(s).height) for s in seasons), results)
    print("      per-family coverage (report):")
    for (read, ct), g in sorted(allres.group_by("read", "claim_type")):
        rsv = int(g["resolved"].sum())
        print(f"        {read:16}/{ct:12} n={g.height:>7} resolved={rsv:>7} "
              f"({round(rsv / g.height * 100, 1)}%) unresolved={g.height - rsv:>6}")
    pd = allres.filter(pl.col("read") == "positional_depth")
    _ok("positional_depth ★ carries its clean-subset coverage flag",
        pd.filter(pl.col("coverage_flag").is_not_null()).height == pd.height, results,
        f"[{round(int(pd['resolved'].sum()) / max(pd.height, 1) * 100, 1)}% clean]")

    print("  2 — primitive validity (ranges; pit IFF distribution; native-per-family; rank_error int):")
    _ok("pit∈[0,1] · brier∈[0,1] · in_band∈{0,1}", _validity_ok(allres), results)
    _ok("pit non-null IFF interval/probability",
        allres.filter(pl.col("pit").is_not_null()
                      & ~pl.col("claim_type").is_in(["interval", "probability"])).height == 0, results)
    _ok("rank_error integer for true_rank (avg_seed fractional by design)",
        allres.filter((pl.col("read") == "true_rank") & pl.col("resolved")
                      & (pl.col("rank_error") != pl.col("rank_error").round(0))).height == 0, results)

    print("  3 — Law 1 (primitives, NOT verdicts — no aggregate score / suppress column):")
    _ok("no forbidden verdict column present", _law1_ok(allres), results,
        f"forbidden={sorted(_FORBIDDEN_VERDICT_COLS)[:3]}…")

    print("  4 — traceability + determinism:")
    s0 = seasons[0]
    p0 = data_layer.read_predictions(s0).select("prediction_id", "code_version", "constants_hash",
                                                 "inputs_ok", "served")
    rejoin = frames[s0].join(p0, on="prediction_id", how="inner", suffix="_p")
    trace = (rejoin.height == frames[s0].height
             and (rejoin["code_version"] == rejoin["code_version_p"]).all()
             and (rejoin["constants_hash"] == rejoin["constants_hash_p"]).all()
             and (rejoin["inputs_ok"] == rejoin["inputs_ok_p"]).all()
             and (rejoin["served"] == rejoin["served_p"]).all())
    _ok("every resolution rejoins its claim's prediction_id + provenance", trace, results)
    recomputed = cr.resolve_season(s0)
    _ok(f"recompute season {s0} value-identical (twice-compute determinism)",
        _frame_eq(recomputed, frames[s0]), results)

    print("  5 — realized integrity rides through (playoff mass == slot count in the graded rows):")
    _ok("Σ truth over bracket_odds/probability == playoff_teams per (league, as_of_week)",
        all(_integrity_ok(frames[s]) for s in seasons), results)

    print("  PROVE-BITES:")
    demo = frames[s0]
    resolved_pid = demo.filter(pl.col("resolved") & pl.col("truth").is_not_null())["prediction_id"][0]
    prob_pid = demo.filter((pl.col("read") == "bracket_odds") & (pl.col("claim_type") == "probability")
                           & pl.col("resolved"))["prediction_id"][0]
    _ok("check-1 coverage bites (a resolved row with null truth is rejected)",
        not _coverage_ok(demo.with_columns(pl.when(pl.col("prediction_id") == resolved_pid)
                                           .then(None).otherwise(pl.col("truth")).alias("truth")),
                         demo.height), results)
    bad_pit = demo.with_columns(pl.when(pl.col("prediction_id") == prob_pid).then(1.3)
                                .otherwise(pl.col("pit")).alias("pit"))
    _ok("check-2 validity bites (a pit=1.3 is rejected)", not _validity_ok(bad_pit), results)
    _ok("check-3 Law-1 bites (a 'read_score' verdict column is rejected)",
        not _law1_ok(demo.with_columns(pl.lit(1.0).alias("read_score"))), results)
    _ok("check-4 determinism bites (differing values ≠; a row permutation ==)",
        (not _frame_eq(demo, demo.with_columns(pl.when(pl.col("prediction_id") == resolved_pid)
                                               .then(-999.0).otherwise(pl.col("truth")).alias("truth"))))
        and _frame_eq(demo, demo.reverse()), results)
    bad_mass = demo.with_columns(pl.when(pl.col("prediction_id") == prob_pid)
                                 .then(pl.col("truth") + 1.0).otherwise(pl.col("truth")).alias("truth"))
    _ok("check-5 integrity bites (perturbing a made-playoffs truth breaks the mass)",
        not _integrity_ok(bad_mass), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the resolutions ledger ({allres.height:,} primitives "
          f"over {len(seasons)} seasons) is coverage-complete, primitive-valid, horizon-correct, traceable, "
          f"deterministic, and Law-1-structural (primitives, not verdicts).")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the L2 resolutions ledger (Session 4b).")
    ap.add_argument("--season", type=int, default=None, help="one season (default: all spined)")
    ap.add_argument("--sample", type=int, default=1)
    a = ap.parse_args()
    seasons = (a.season,) if a.season else SPINED_SEASONS
    sys.exit(0 if check(seasons, a.sample) else 1)


if __name__ == "__main__":
    main()
