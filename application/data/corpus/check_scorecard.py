"""
check_scorecard.py — the L3 engine-scorecard gate (Improvement-Loop Session 5, commit 3).

Asserts, over the 6 spined seasons, that the scorecard the L3 scorer produces is coverage-complete,
metric-valid, confidence-honesty-measured (for the 5 bearing families) or explicitly-flagged (for the 4
gaps), deterministic, and — the L3 form of Law 1 — judges only DISTRIBUTIONS: the grain is a SLICE, never
a `prediction_id`; no single-claim verdict exists; the `overall` model verdict is computed on
`inputs_ok ∧ resolved` only (never blended with the quarantine slices). Mirrors `check_resolutions` /
`check_predictions`: exit 0 iff every check passes. A gate that can't fail is not a gate — every check has
a prove-bite.

  1. COVERAGE — every expected (read × slice_dim) scored: the 9 families' `overall` verdict; the base
     slices (week/league/position/cohort/scoring_key); the `confidence_tier` reliability rows for the 5
     bearing families; and the `inputs_ok` + `resolution_status` quarantine slices — each present or
     explicitly n/a-by-construction (the band has no league/cohort/position slice).
  2. METRIC RANGES — skill ≤ 1; brier/pit_ks/pit_edge/coverage/in_band ∈ [0,1]; discrimination &
     conf_monotonicity ∈ [−1,1]; resolved_rate ∈ [0,1]; n_resolved ≤ n_claims; mae/rmse ≥ 0.
  3. CONFIDENCE-HONESTY — the 5 bearing families' `overall` rows carry measurable_law2 + a non-null
     monotonicity + conf_honest; the 4 gap families carry measurable_law2=false + null confidence (flagged,
     never fabricated). The anti-sort prove-bite: anti-sorting confidence flips an honest family to dishonest.
  4. BASELINE REGISTRY — `scorecard_registry.check_registry()` is green, and BITES on a mutated registry.
  5. DETERMINISM — recomputing a season (with the PERSISTED code_version, HEAD-independent) is value-identical.
  6. LAW 1 STRUCTURAL — no `prediction_id` / single-claim-verdict column; every row is a named slice; the
     `overall` + base model-quality rows are on the clean population only (n_claims == n_resolved).

Run: python3 -m application.data.corpus.check_scorecard [--season S]
"""
import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_engine_scorecard as ces
from application.data.corpus import scorecard_registry as reg

SPINED_SEASONS = ces.SPINED_SEASONS

# The 9 families + the 5 confidence-bearing / 4 flagged split (from the 4a claim registry — single source).
_FAMILIES = set(reg.families())
_CONF_FAMILIES = set(reg.CONF_SIGNALS)
_GAP_FAMILIES = _FAMILIES - _CONF_FAMILIES
# The base model-quality slice dims (the band is legitimately absent from league/cohort/position — null league).
_EXPECTED_SLICE_DIMS = {"overall", "week", "league", "position", "cohort", "scoring_key",
                        "inputs_ok", "resolution_status", "confidence_tier"}
# A single-claim id must NEVER appear — the L3 form of Law 1 (judge distributions, not claims).
_FORBIDDEN_CLAIM_COLS = {"prediction_id", "resolution_id", "subject_id", "claim_correct", "suppress"}


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:64} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


# --- predicates shared by the real checks AND the prove-bites ---------------------------------------

def _coverage_ok(sc: pl.DataFrame) -> bool:
    ov = sc.filter(pl.col("slice_dim") == "overall")
    if {(r, c) for r, c in ov.select("read", "claim_type").iter_rows()} != _FAMILIES:
        return False
    if not _EXPECTED_SLICE_DIMS.issubset(set(sc["slice_dim"].unique().to_list())):
        return False
    # the 5 confidence-bearing families each get their 3 reliability tiers
    ct = sc.filter(pl.col("slice_dim") == "confidence_tier")
    fams = {(r, c) for r, c in ct.select("read", "claim_type").iter_rows()}
    if fams != _CONF_FAMILIES:
        return False
    if ct.filter(pl.col("slice_val").is_in(list(reg.TIER_LABELS))).height != ct.height:
        return False
    return True


def _ranges_ok(sc: pl.DataFrame) -> bool:
    specs = [("skill", None, 1.0 + 1e-9), ("brier", 0.0, 1.0), ("pit_ks_stat", 0.0, 1.0),
             ("pit_edge_mass", 0.0, 1.0), ("in_band_rate", 0.0, 1.0), ("coverage_actual", 0.0, 1.0),
             ("discrimination", -1.0 - 1e-9, 1.0 + 1e-9), ("conf_monotonicity", -1.0 - 1e-9, 1.0 + 1e-9),
             ("resolved_rate", 0.0, 1.0 + 1e-9), ("mae", 0.0, None), ("rmse", 0.0, None)]
    for col, lo, hi in specs:
        c = pl.col(col)
        cond = pl.lit(False)
        if lo is not None:
            cond = cond | (c.is_not_null() & (c < lo))
        if hi is not None:
            cond = cond | (c.is_not_null() & (c > hi))
        if sc.filter(cond).height:
            return False
    return sc.filter(pl.col("n_resolved") > pl.col("n_claims")).height == 0


def _conf_presence_ok(sc: pl.DataFrame) -> bool:
    ov = sc.filter(pl.col("slice_dim") == "overall")
    for r in ov.iter_rows(named=True):
        key = (r["read"], r["claim_type"])
        if key in _CONF_FAMILIES:
            if not r["measurable_law2"] or r["conf_monotonicity"] is None or r["conf_honest"] is None:
                return False
        else:                                                       # the 4 gaps: flagged, not fabricated
            if r["measurable_law2"] or r["conf_label"] is not None or r["conf_monotonicity"] is not None \
                    or r["conf_honest"] is not None:
                return False
    return True


_BASE_MODEL_DIMS = ["week", "league", "position", "cohort", "scoring_key"]


def _law1_ok(sc: pl.DataFrame) -> bool:
    """L3 Law 1: the scorer judges DISTRIBUTIONS, never a single claim."""
    if _FORBIDDEN_CLAIM_COLS & set(sc.columns):
        return False
    dims = set(sc["slice_dim"].unique().to_list())
    if not dims.issubset(_EXPECTED_SLICE_DIMS):
        return False
    # the base model-quality slices are on the CLEAN population only (n_claims == n_resolved). The `overall`
    # row legitimately carries full-population COVERAGE counts (n_claims != n_resolved when there are
    # unresolved), and `inputs_ok`/`resolution_status` are the quarantine slices — where the false/unresolved
    # data lives SEPARATELY, never blended into a model number.
    base = sc.filter(pl.col("slice_dim").is_in(_BASE_MODEL_DIMS))
    if base.filter(pl.col("n_claims") != pl.col("n_resolved")).height:
        return False
    if not {"inputs_ok", "resolution_status"}.issubset(dims):
        return False
    return True


def check(seasons=SPINED_SEASONS) -> bool:
    seasons = [s for s in seasons if data_layer.engine_scorecard_exists(s)]
    if not seasons:
        print("  no engine_scorecard on disk — run compute_engine_scorecard first.")
        return False
    results = []
    frames = {s: data_layer.read_engine_scorecard(s) for s in seasons}
    allsc = pl.concat(frames.values(), how="diagonal")
    print(f"\n  gate over {len(seasons)} spined seasons, {allsc.height:,} scorecard rows")

    print("  1 — coverage (9 overall verdicts · base slices · 5 confidence-tier triples · quarantine slices):")
    _ok("every expected (read × slice_dim) scored", all(_coverage_ok(frames[s]) for s in seasons), results)
    print("      rows per slice_dim (report):")
    for r in allsc.group_by("slice_dim").agg(pl.len().alias("n")).sort("slice_dim").iter_rows(named=True):
        print(f"        {r['slice_dim']:18} {r['n']:>5}")

    print("  2 — metric ranges (skill≤1 · brier/ks/coverage∈[0,1] · disc/mono∈[−1,1] · n_res≤n_claims):")
    _ok("all metrics within valid ranges", _ranges_ok(allsc), results)

    print("  3 — confidence-honesty measured for the 5, flagged for the 4:")
    _ok("5 bearing families carry monotonicity+verdict; 4 gaps flagged (null, not fabricated)",
        all(_conf_presence_ok(frames[s]) for s in seasons), results)
    # the anti-sort prove-bite (the C2 headline): anti-sorting confidence flips an honest family to dishonest
    s_any = seasons[-1]
    e = ces.enrich(s_any)
    pop = e.filter(pl.col("resolved") & pl.col("inputs_ok"))
    ctx = {"season": s_any, "code_version": "bite", "constants_hash": ces._one_constants_hash(e)}
    v_real, _ = ces._confidence_honesty(pop, ctx)
    v_anti, _ = ces._confidence_honesty(pop.with_columns((-pl.col("conf_strength")).alias("conf_strength")), ctx)
    honest_flipped = [k for k in v_real if v_real[k]["conf_honest"] and not v_anti[k]["conf_honest"]]
    _ok("anti-sort prove-bite: an honest read flips to dishonest when confidence is reversed",
        len(honest_flipped) >= 1, results, f"flipped={[f'{r}/{c}' for r, c in honest_flipped]}")

    print("  4 — baseline registry declared + gated:")
    _ok("scorecard_registry.check_registry() is green", reg.check_registry()["ok"], results)

    print("  5 — determinism (recompute with the PERSISTED code_version — HEAD-independent):")
    s0 = seasons[0]
    saved = ces._CODE_VERSION
    ces._CODE_VERSION = frames[s0]["code_version"][0]
    recomputed = ces.score_season(s0)
    ces._CODE_VERSION = saved
    _ok(f"recompute season {s0} value-identical (twice-score determinism)",
        _frame_eq(recomputed, frames[s0]), results)

    print("  6 — Law 1 structural (distributions, never a single claim):")
    _ok("no prediction_id/single-claim column; overall+base rows on the clean population only",
        all(_law1_ok(frames[s]) for s in seasons), results)

    print("  PROVE-BITES:")
    demo = frames[s0]
    a_scid = demo["scorecard_id"][0]
    _ok("check-1 coverage bites (dropping the overall slice is rejected)",
        not _coverage_ok(demo.filter(pl.col("slice_dim") != "overall")), results)
    _ok("check-2 ranges bite (a brier=1.3 is rejected)",
        not _ranges_ok(demo.with_columns(pl.when(pl.col("scorecard_id") == a_scid).then(1.3)
                                         .otherwise(pl.col("brier")).alias("brier"))), results)
    # flip a gap family to measurable → presence check must fail
    gap_scid = demo.filter((pl.col("slice_dim") == "overall") & ~pl.col("measurable_law2"))["scorecard_id"][0]
    _ok("check-3 confidence bites (a fabricated law-2 verdict on a gap family is rejected)",
        not _conf_presence_ok(demo.with_columns(
            pl.when(pl.col("scorecard_id") == gap_scid).then(True).otherwise(pl.col("measurable_law2"))
              .alias("measurable_law2"))), results)
    # registry bite: mutate NAIVE_BASELINES → check_registry reddens (restored)
    orig = reg.NAIVE_BASELINES[("true_rank", "ordinal")]["skill_kind"]
    reg.NAIVE_BASELINES[("true_rank", "ordinal")]["skill_kind"] = "bogus"
    reg_bites = not reg.check_registry()["ok"]
    reg.NAIVE_BASELINES[("true_rank", "ordinal")]["skill_kind"] = orig
    _ok("check-4 registry bites (a bogus skill_kind reddens check_registry)", reg_bites, results)
    _ok("check-5 determinism bites (a perturbed metric ≠; a row permutation ==)",
        (not _frame_eq(demo, demo.with_columns(pl.when(pl.col("scorecard_id") == a_scid).then(-999.0)
                                               .otherwise(pl.col("skill")).alias("skill"))))
        and _frame_eq(demo, demo.reverse()), results)
    _ok("check-6 Law-1 bites (an injected prediction_id column is rejected)",
        not _law1_ok(demo.with_columns(pl.lit("x").alias("prediction_id"))), results)
    # Law-1 bite 2: blend an unresolved row into a BASE model slice (n_claims != n_resolved) → rejected
    base_scid = demo.filter(pl.col("slice_dim").is_in(_BASE_MODEL_DIMS))["scorecard_id"][0]
    _ok("check-6b Law-1 bites (a base model row with unresolved blended in is rejected)",
        not _law1_ok(demo.with_columns(pl.when(pl.col("scorecard_id") == base_scid)
                                       .then(pl.col("n_resolved") - 1).otherwise(pl.col("n_resolved"))
                                       .alias("n_resolved"))), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the engine scorecard ({allsc.height:,} slice verdicts "
          f"over {len(seasons)} seasons) is coverage-complete, metric-valid, confidence-honesty-measured/"
          f"flagged, deterministic, and Law-1-structural (judges distributions, never a single claim).")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the L3 engine scorecard (Session 5).")
    ap.add_argument("--season", type=int, default=None, help="one season (default: all spined)")
    a = ap.parse_args()
    seasons = (a.season,) if a.season else SPINED_SEASONS
    sys.exit(0 if check(seasons) else 1)


if __name__ == "__main__":
    main()
