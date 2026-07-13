"""
Corpus gate (Session 0.5, commit 3) — internal-consistency, no answer key.

The check_market_vor / check_ros_synthesis regime: the corpus has no future truth to grade against,
so this asserts the manifest is self-consistent and honest, exit 0/1.

  Stratum integrity  every `matched` row satisfies the matched predicate, passes the filter, and is
                     scoreable (ZERO unscoreable matched rows); every `generalization` row is never_tune.
  Season balance     matched supply per season reported; FAIL if any DECLARED-train season is below the
                     explicit floor (don't paper over a thin 2020 — declare which seasons you train on).
  Filter honesty     every manifest row has a filter_result; every fail carries a reason; pass-rate
                     reported and compared to Session 0's 87%.
  No leakage         no `matched` row is never_tune; no `generalization` row is tunable.

Run: python3 -m application.data.corpus.check_corpus
"""
import sys
from collections import Counter

from application.data import data_layer
from application.data.corpus import _corpus

# Declared train window + floors (Deliverable 2). Session 0.6 corrected the float32 bug that had zeroed
# 2020-21, so the split is now the full six seasons:
#   Split: TRAIN 2020-2023 · DEV 2024 · TEST 2025 (2026 analogue). 2020-21 are THIN (~8, ~16 selected),
#   used via league-wise k-fold WITHIN the train seasons, not leaned on as a standalone season-wise dev.
# Two floors — operationalising the standing instruction "a suspiciously clean zero is a bug":
#   HARD floor  → a train season below it is unusable even pooled ⇒ the gate FAILS (this is exactly what
#                 would have caught the 0.5 "0 matched in 2020 AND 2021" had it existed).
#   SOLID floor → below it a season is flagged THIN (reported, k-folded), not failed.
TRAIN_WINDOW = (2020, 2021, 2022, 2023)
MATCHED_SEASON_HARD_FLOOR = 5
MATCHED_SEASON_SOLID_FLOOR = 20
SESSION0_PASS_RATE = 87.0

_ok_count = {"n": 0}


def _ok(msg):
    print(f"  ✓ {msg}")


def _fail(msg):
    print(f"  ✗ {msg}")
    _ok_count["n"] += 1


def check() -> bool:
    if not data_layer.corpus_manifest_exists():
        _fail("corpus_manifest.parquet missing — run select.py first")
        return False
    m = data_layer.read_corpus_manifest().to_dicts()
    matched = [r for r in m if r["stratum"] == "matched"]
    gen = [r for r in m if r["stratum"] == "generalization"]

    # 1. stratum integrity — for matched rows scoring_key is the canned profile (ppr/half), so it
    # doubles as the scoring signal for the predicate (a cust- hash would fail MATCHED_SCORINGS).
    bad_pred = [r for r in matched if not _corpus.is_matched_eligible(
        r["scoring_key"], r["qb_structure"], r["league_format"], r["num_teams"])]
    if bad_pred:
        _fail(f"{len(bad_pred)} matched rows violate the matched predicate")
    else:
        _ok(f"all {len(matched)} matched rows satisfy the matched predicate")

    unscoreable_matched = [r for r in matched if not r["scoreable"]]
    if unscoreable_matched:
        _fail(f"{len(unscoreable_matched)} matched rows are UNSCOREABLE (must be zero)")
    else:
        _ok("zero matched rows are unscoreable")

    unfiltered_matched = [r for r in matched if r["filter_result"] != "pass"]
    if unfiltered_matched:
        _fail(f"{len(unfiltered_matched)} matched rows did not pass the filter")
    else:
        _ok("all matched rows passed the inclusion filter")

    gen_tunable = [r for r in gen if not r["never_tune"]]
    if gen_tunable:
        _fail(f"{len(gen_tunable)} generalization rows are tunable (never_tune must be true)")
    else:
        _ok(f"all {len(gen)} generalization rows are never_tune")

    # 2. season balance
    by_season = Counter(r["season"] for r in matched)
    print(f"  matched supply per season: {dict(sorted(by_season.items()))}")
    empty = [s for s in TRAIN_WINDOW if by_season.get(s, 0) < MATCHED_SEASON_HARD_FLOOR]
    if empty:
        _fail(f"declared-train seasons below HARD floor {MATCHED_SEASON_HARD_FLOOR} (unusable even "
              f"pooled — a suspiciously clean low count, cf. the 0.5 float32 bug): "
              f"{ {s: by_season.get(s,0) for s in empty} }")
    else:
        _ok(f"every declared-train season {TRAIN_WINDOW} ≥ hard floor {MATCHED_SEASON_HARD_FLOOR}")
    thin = [s for s in TRAIN_WINDOW
            if MATCHED_SEASON_HARD_FLOOR <= by_season.get(s, 0) < MATCHED_SEASON_SOLID_FLOOR]
    if thin:
        print(f"  ⓘ thin train seasons (< {MATCHED_SEASON_SOLID_FLOOR}, k-folded within train, not "
              f"standalone): { {s: by_season.get(s, 0) for s in thin} }")

    # 3. filter honesty
    no_result = [r for r in m if not r["filter_result"]]
    if no_result:
        _fail(f"{len(no_result)} manifest rows have no filter_result")
    else:
        _ok("every manifest row has a filter_result")
    fails = [r for r in m if r["filter_result"] == "fail"]
    fails_no_reason = [r for r in fails if not r["filter_reason"]]
    if fails_no_reason:
        _fail(f"{len(fails_no_reason)} failed rows carry no reason")
    else:
        _ok("every failed row carries a reason")
    graded = [r for r in m if r["filter_result"] in ("pass", "fail") and r["stratum"] != "mine"]
    if graded:
        rate = round(100 * sum(1 for r in graded if r["filter_result"] == "pass") / len(graded), 1)
        _ok(f"filter pass-rate {rate}% over {len(graded)} filtered (Session 0: {SESSION0_PASS_RATE}%)")

    # 4. no leakage of intent
    matched_never_tune = [r for r in matched if r["never_tune"]]
    if matched_never_tune:
        _fail(f"{len(matched_never_tune)} matched rows are never_tune (would drop from tuning)")
    else:
        _ok("no matched row is mis-flagged never_tune")

    print(f"  strata: {dict(Counter(r['stratum'] for r in m))}")
    return _ok_count["n"] == 0


def main():
    print("=== check_corpus ===")
    ok = check()
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
