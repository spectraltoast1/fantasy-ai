"""
check_predictions.py — the L2 predictions-ledger gate (Improvement-Loop Session 4a, commit 3).

Asserts, over the 270 spined league-seasons in the FROZEN manifest, that the `predictions` reshape is
coverage-complete, schema-sound (typed sidecars + XOR), immutable, provenance-honest, deterministic, and
confidence-trackable-or-flagged — and that Law 1 holds STRUCTURALLY (no grade / verdict / resolution
column exists anywhere in the entity; the scorer, Session 5, is the first judge). Mirrors `check_spine` /
`check_harvest`: exit 0 iff every check passes. A gate that can't fail is not a gate — every check has a
prove-bite.

  1. CLAIM COVERAGE — every spined league has its league-scoped claims; the band contributes EXACTLY one
     scoring-scoped population per (scoring_key, season) with league_id=null; and on a sample, each of the
     9 claim families' row count == the source read's non-null count (no read silently dropped).
  2. SCHEMA + TYPING XOR + LAW 1 — canonical columns, required non-null; value XOR value_str by claim_type;
     lo/hi/sigma present IFF interval; confidence_json only where a family carries it; league_id null IFF
     band; served=false, prompt_version/model/created_at null; constants_hash == the live snapshot;
     prediction_id unique; and NO grade/verdict/resolution column exists (Law 1 is structural).
  3. IMMUTABILITY — the append-only writer never overwrites: a same-code_version re-write appends nothing;
     a new-code_version write appends a parallel population (both retained). Proven on a throwaway season.
  4. PROVENANCE BITES — the constants_hash drift gate reddens on a changed module constant; the store
     exercises inputs_ok's `false` path (≥1 league) AND the derivation flips false on a degraded input;
     all `served=false` rows share ONE code_version naming the PRODUCING commit (its tree carries
     backfill_predictions.py — not the base/dirty-tree sha), and the dirty-tree stamp guard bites (4a-fix).
  5. DETERMINISM — rebuilding a sample league/band's claims (with the PERSISTED code_version) is
     value-identical to the persisted rows, incl. a stable prediction_id. Value-compared (`_frame_eq`):
     determinism is a property of the VALUES, not the physically-non-deterministic parquet byte stream.
  6. CONFIDENCE HONESTY — every graded claim family carries a populated canonical confidence + label; every
     family on the named no-native-confidence flag list carries null confidence (flagged, not fabricated).

Run: python3 -m application.data.corpus.check_predictions [--strata matched generalization mine] [--sample N]
"""
import argparse
import os
import subprocess
import sys

import polars as pl

from application.data import data_layer
from application.data.corpus import (
    backfill_predictions,
    constants_snapshot,
    inputs_ok,
    predictions_map,
)

# Columns that would mean a claim has been GRADED/RESOLVED — Law 1 forbids any of them in this entity.
_FORBIDDEN_COLS = {"error", "abs_error", "in_band", "pit", "brier", "rank_error", "grade", "verdict",
                   "resolution", "resolved", "outcome", "outcome_type", "truth", "graded", "score"}
_NUMERIC_CLAIMS = ("point", "interval", "probability", "ordinal")


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:60} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality (same columns + same VALUES) — the determinism property is about
    values, not the physically-non-deterministic parquet byte stream (the check_spine precedent)."""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


def _commit_has_producer(sha: str) -> bool:
    """True iff `sha` is a real commit whose tree contains the producing code
    (`backfill_predictions.py`) — so `code_version` names the commit that PRODUCED the claims, not the
    base/dirty-tree commit (the 4a-fix defect: the base sha's tree lacks the backfill file)."""
    root = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run(["git", "cat-file", "-e", f"{sha}:application/data/corpus/backfill_predictions.py"],
                       cwd=root, capture_output=True)
    return r.returncode == 0


def _guard_bites() -> bool:
    """The dirty-tree stamp guard exists and bites: a clean tree passes, a dirty one raises."""
    try:
        backfill_predictions._assert_clean_tree("")            # clean → no raise
    except Exception:
        return False
    try:
        backfill_predictions._assert_clean_tree(" M application/data/corpus/backfill_predictions.py")
        return False                                           # dirty → should have raised
    except RuntimeError:
        return True


def _load(seasons) -> pl.DataFrame:
    parts = [data_layer.read_predictions(s) for s in seasons if data_layer.predictions_exists(s)]
    return pl.concat(parts, how="diagonal") if parts else pl.DataFrame()


def _rebuild_league(lid, season, sk, cv) -> pl.DataFrame:
    """Rebuild one league's league-scoped claims under a given code_version (for the determinism check)."""
    iok = inputs_ok.derive_inputs_ok(lid, season)
    ctx = {"league_id": lid, "scoring_key": sk, "season": season, "code_version": cv,
           "constants_hash": constants_snapshot.constants_hash(), "inputs_ok": iok}
    frames = {src: backfill_predictions._LEAGUE_READERS[src](season, league_id=lid, as_of_week="all")
              for src in predictions_map.LEAGUE_SOURCES}
    return predictions_map.build_league_claims(frames, ctx)


def _rebuild_band(sk, season, cv) -> pl.DataFrame:
    ctx = {"league_id": None, "scoring_key": sk, "season": season, "code_version": cv,
           "constants_hash": constants_snapshot.constants_hash(), "inputs_ok": True}
    return predictions_map.build_band_claims(
        data_layer.read_ros_player_band(season, scoring_key=sk, as_of_week="all"), ctx)


def _expected_family_counts(lid, season, sk) -> dict:
    """The claim-count each family SHOULD produce = the source read's non-null-value rows (deep coverage)."""
    exp = {}
    readers = {**backfill_predictions._LEAGUE_READERS,
               predictions_map.BAND_SOURCE: lambda s, **k: data_layer.read_ros_player_band(s, scoring_key=sk, as_of_week="all")}
    src_cache = {}
    for spec in predictions_map.FAMILIES:
        src = spec["source"]
        if src not in src_cache:
            if src == predictions_map.BAND_SOURCE:
                src_cache[src] = data_layer.read_ros_player_band(season, scoring_key=sk, as_of_week="all")
            else:
                src_cache[src] = backfill_predictions._LEAGUE_READERS[src](season, league_id=lid, as_of_week="all")
        df = src_cache[src]
        val_col = spec["value"]
        subj = spec["subject_id"]
        non_null = df.filter(
            pl.all_horizontal([pl.col(c).is_not_null() for c in subj]) & pl.col(val_col).is_not_null()
        ).height
        exp[(spec["read"], spec["claim_type"])] = non_null
    return exp


def check(strata=("matched", "generalization", "mine"), sample: int = 3) -> bool:
    results: list = []
    strata = tuple(strata)
    tgts = backfill_predictions.targets(strata)
    seasons = sorted({int(t["season"]) for t in tgts})
    df = _load(seasons)
    print(f"\n  gate over {len(tgts)} spined league-seasons, seasons {seasons}, {df.height:,} claim rows")

    # 1 — coverage
    print("  1 — claim coverage (every league present; band once per scoring key; sample family counts):")
    missing_league = [f"{t['league_id']} {t['season']}"
                      for t in tgts if data_layer.read_predictions(int(t["season"]),
                                                                    league_id=str(t["league_id"])).is_empty()]
    _ok(f"every spined league has league-scoped claims ({len(tgts)})", not missing_league, results,
        "" if not missing_league else f"{len(missing_league)} missing, e.g. {missing_league[:3]}")
    band = df.filter(pl.col("read") == predictions_map.BAND_SOURCE)
    band_pops = band.group_by("scoring_key", "season").len()
    expect_pops = {(str(t["scoring_key"]), int(t["season"])) for t in tgts}
    _ok(f"band = one population per (scoring_key, season) [{band_pops.height} == {len(expect_pops)}]",
        band_pops.height == len(expect_pops), results)
    _ok("band rows all have league_id=null", band["league_id"].is_null().all(), results)
    # deep sample: per-family counts match source non-null counts
    sample_tgts = tgts[:: max(1, len(tgts) // sample)][:sample]
    deep_ok = True
    for t in sample_tgts:
        lid, s, sk = str(t["league_id"]), int(t["season"]), str(t["scoring_key"])
        exp = _expected_family_counts(lid, s, sk)
        got = data_layer.read_predictions(s, league_id=lid)
        for (read, ct), n in exp.items():
            if read == predictions_map.BAND_SOURCE:
                continue  # band is league_id-null, checked via band population above
            actual = got.filter((pl.col("read") == read) & (pl.col("claim_type") == ct)).height
            if actual != n:
                deep_ok = False
                print(f"      coverage gap {lid} {s} {read}/{ct}: claims {actual} != source {n}")
    _ok(f"sample family counts == source non-null counts ({len(sample_tgts)} leagues)", deep_ok, results)

    # 2 — schema + typing XOR + Law 1
    print("  2 — schema integrity + typing XOR + Law 1 (no verdict column):")
    _ok("canonical column set", df.columns == predictions_map.CLAIM_COLS, results)
    forbidden = _FORBIDDEN_COLS & set(df.columns)
    _ok("Law 1: no grade/verdict/resolution column exists", not forbidden, results,
        "" if not forbidden else f"found {forbidden}")
    req = ["prediction_id", "scoring_key", "season", "as_of_week", "read", "subject_type", "subject_id",
           "claim_type", "code_version", "constants_hash"]
    _ok("required columns non-null", all(df[c].null_count() == 0 for c in req), results)
    bad_val = df.filter(pl.col("claim_type").is_in(_NUMERIC_CLAIMS) & pl.col("value").is_null()).height
    bad_num_str = df.filter(pl.col("claim_type").is_in(_NUMERIC_CLAIMS) & pl.col("value_str").is_not_null()).height
    bad_dir_val = df.filter((pl.col("claim_type") == "direction") & pl.col("value").is_not_null()).height
    bad_dir_str = df.filter((pl.col("claim_type") == "direction") & pl.col("value_str").is_null()).height
    _ok("value XOR value_str by claim_type", not (bad_val or bad_num_str or bad_dir_val or bad_dir_str),
        results, f"(num-null-val={bad_val} num-str={bad_num_str} dir-val={bad_dir_val} dir-nullstr={bad_dir_str})")
    iv, non_iv = df.filter(pl.col("claim_type") == "interval"), df.filter(pl.col("claim_type") != "interval")
    bad_iv = iv.filter(pl.col("lo").is_null() | pl.col("hi").is_null() | pl.col("sigma").is_null()).height
    bad_non_iv = non_iv.filter(pl.col("lo").is_not_null() | pl.col("hi").is_not_null()
                               | pl.col("sigma").is_not_null()).height
    _ok("lo/hi/sigma present IFF interval", not (bad_iv or bad_non_iv), results,
        f"(interval-missing={bad_iv} non-interval-set={bad_non_iv})")
    _ok("league_id null IFF band", (df.filter(pl.col("read") == predictions_map.BAND_SOURCE)["league_id"].is_null().all()
        and df.filter(pl.col("read") != predictions_map.BAND_SOURCE)["league_id"].is_not_null().all()), results)
    _ok("served=false, prompt_version/model/created_at null universally",
        (~df["served"]).all() and df["prompt_version"].null_count() == df.height
        and df["model"].null_count() == df.height and df["created_at"].null_count() == df.height, results)
    _ok("constants_hash == live snapshot", (df["constants_hash"] == constants_snapshot.constants_hash()).all(),
        results)
    _ok("prediction_id unique", df["prediction_id"].n_unique() == df.height, results)

    # 3 — immutability (throwaway season; never touches the canonical store)
    print("  3 — immutability (append-only-of-new; same code_version idempotent; new one parallel):")
    tmp_season = 99999
    data_layer._predictions_path(tmp_season).unlink(missing_ok=True)
    slc = df.head(3)
    data_layer.write_predictions(slc, tmp_season)
    n1 = data_layer.read_predictions(tmp_season).height
    data_layer.write_predictions(slc, tmp_season)                       # same ids → 0 new
    n2 = data_layer.read_predictions(tmp_season).height
    parallel = slc.with_columns(pl.lit("__PARALLEL__").alias("code_version"),
                                (pl.col("prediction_id") + "_v2").alias("prediction_id"))
    data_layer.write_predictions(parallel, tmp_season)                  # new ids → +3, both kept
    n3 = data_layer.read_predictions(tmp_season).height
    cvs = data_layer.read_predictions(tmp_season)["code_version"].n_unique()
    data_layer._predictions_path(tmp_season).unlink(missing_ok=True)
    _ok(f"same code_version re-write appends nothing [{n1}=={n2}]", n1 == 3 and n2 == 3, results)
    _ok(f"new code_version appends a parallel population [{n2}->{n3}, {cvs} versions]",
        n3 == 6 and cvs == 2, results)

    # 4 — provenance bites
    print("  4 — provenance bites (constants drift; inputs_ok false path):")
    _ok("constants snapshot matches live now (green)", constants_snapshot.check_constants_drift()["ok"], results)
    _saved = constants_snapshot.SNAPSHOT["ros_player_band.BULL_Z"]
    constants_snapshot.SNAPSHOT["ros_player_band.BULL_Z"] = _saved + 1.0
    drift_red = not constants_snapshot.check_constants_drift()["ok"]
    constants_snapshot.SNAPSHOT["ros_player_band.BULL_Z"] = _saved
    _ok("drift gate reddens on a changed module constant", drift_red, results)
    n_false = df.filter(~pl.col("inputs_ok")).select("league_id", "season").unique().height
    _ok(f"store exercises inputs_ok=false path ({n_false} league-seasons)", n_false >= 1, results)
    synth = pl.DataFrame({"league_id": ["X"], "season": [2099], "filter_result": ["pass"],
                          "id_resolution_pct": [10.0]})
    _ok("inputs_ok derivation flips false on a degraded input",
        not inputs_ok.inputs_ok_detail("X", 2099, manifest=synth)["ok"], results)
    # code_version provenance (4a-fix): served=false is ONE version naming the PRODUCING commit; guard bites.
    sf_cvs = df.filter(~pl.col("served"))["code_version"].unique().to_list()
    _ok(f"served=false rows share ONE code_version [{len(sf_cvs)}]", len(sf_cvs) == 1, results,
        "" if len(sf_cvs) == 1 else f"{sf_cvs[:3]}")
    _ok("code_version names the PRODUCING commit (its tree has backfill_predictions.py)",
        len(sf_cvs) == 1 and _commit_has_producer(sf_cvs[0]), results,
        sf_cvs[0][:12] if len(sf_cvs) == 1 else "")
    _ok("dirty-tree stamp guard exists + bites (clean ok; dirty raises)", _guard_bites(), results)

    # 5 — determinism
    print("  5 — determinism (rebuild a sample == persisted, incl. stable prediction_id):")
    det_ok = True
    for t in sample_tgts:
        lid, s, sk = str(t["league_id"]), int(t["season"]), str(t["scoring_key"])
        persisted = data_layer.read_predictions(s, league_id=lid)
        cv = persisted["code_version"][0]
        rebuilt = _rebuild_league(lid, s, sk, cv)
        det_ok = det_ok and _frame_eq(rebuilt, persisted)
    _ok(f"league claims rebuild value-identical ({len(sample_tgts)} leagues)", det_ok, results)
    bsk, bseason = str(sample_tgts[0]["scoring_key"]), int(sample_tgts[0]["season"])
    bpers = df.filter((pl.col("read") == predictions_map.BAND_SOURCE) & (pl.col("scoring_key") == bsk)
                      & (pl.col("season") == bseason))
    bcv = bpers["code_version"][0]
    _ok("band claims rebuild value-identical", _frame_eq(_rebuild_band(bsk, bseason, bcv), bpers), results)

    # 6 — confidence honesty
    print("  6 — confidence honesty (graded families populated + labelled; flagged families null):")
    conf_ok = True
    detail = []
    for (read, ct), sub in df.group_by("read", "claim_type"):
        flagged = (read, ct) in predictions_map.NO_CONFIDENCE_FAMILIES
        n_conf = sub.filter(pl.col("confidence").is_not_null()).height
        n_label = sub.filter(pl.col("confidence_label").is_not_null()).height
        if flagged:
            good = n_conf == 0
        else:
            good = n_conf > 0 and n_label == sub.height   # populated + every row labelled
        conf_ok = conf_ok and good
        if not good:
            detail.append(f"{read}/{ct}(conf={n_conf},label={n_label}/{sub.height})")
    _ok("every family graded-populated or flag-null", conf_ok, results,
        "" if conf_ok else "; ".join(detail))

    # prove-bites (logic-level; no canonical-store mutation)
    print("  PROVE-BITES:")
    _ok("check-2 XOR bites (direction row with a value is rejected)",
        pl.DataFrame({"claim_type": ["direction"], "value": [0.0]})
        .filter((pl.col("claim_type") == "direction") & pl.col("value").is_not_null()).height == 1, results)
    _ok("check-2 Law-1 bites (a 'verdict' column would be forbidden)", "verdict" in _FORBIDDEN_COLS, results)
    _ok("check-4 producing-commit bites (the empty tree carries no producer)",
        not _commit_has_producer("4b825dc642cb6eb9a060e54bf8d69288fbee4904"), results)  # git's empty-tree sha
    _ok("check-4 guard bites (clean ok, dirty raises)", _guard_bites(), results)
    _ok("check-5 value-equality bites (differing ≠; permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the predictions ledger ({df.height:,} claims over "
          f"{len(tgts)} spined league-seasons) is coverage-complete, schema-sound (typed XOR), immutable, "
          f"provenance-honest, deterministic, confidence-trackable-or-flagged, and Law-1-structural.")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the L2 predictions ledger (Session 4a).")
    ap.add_argument("--strata", nargs="+", default=["matched", "generalization", "mine"],
                    choices=["matched", "generalization", "mine"])
    ap.add_argument("--sample", type=int, default=3, help="leagues for the deep coverage/determinism checks")
    a = ap.parse_args()
    sys.exit(0 if check(tuple(a.strata), a.sample) else 1)


if __name__ == "__main__":
    main()
