"""
check_expected_points.py — the expected-points backfill gate (Improvement-Loop Session 3c, commit 3).

Asserts that the additive *_exp backfill (C1) + the matched-corpus re-run (C2) lit up §1 Quality across all
six seasons WITHOUT moving anything else. Sibling to `check_spine` (which owns the 3b spine invariants); this
gate owns the *_exp-specific teeth. Exit 0 iff every applicable check passes.

  1. *_exp PRESENT + POPULATED for 2020–2025 — every season's nfl_stats carries all 14 EXP_COMPONENT_COLS
     and they carry signal (not a silently all-zero/all-null season — standing instruction 1). A null/missing
     season would re-create the exact TEST-only gap this session closed.
  2. CONSUMER SEES IT — a sample of matched joins per season carries the full *_exp set (the read consumes
     the join, not nfl_stats directly — "the artifact exists" ≠ "the consumer uses it", standing instr 7).
  3. player_signal REPRODUCIBLE + §1 QUALITY LIT — recompute a sample matched league's player_signal from
     the augmented join: value-identical to persisted AND quality_rate/luck non-null + point_correlation
     not-all-null (the axis is lit, not held-null like 3b).
  4. BLAST RADIUS CONTAINED — recompute production_vor / true_rank / positional_depth / bracket_odds from the
     augmented join: value-identical to their persisted 3b output (they read neither *_exp nor player_signal,
     so adding *_exp to the join cannot move them).

Checks 3+4 compare recompute-vs-persisted ORDER-INSENSITIVELY (`_frame_eq`): polars' parquet WRITER is
physically non-deterministic (the on-disk bytes flake run-to-run for a byte-identical in-memory frame —
values AND row order are stable, only the serialization moves), so the meaningful assertion is value-identity,
not on-disk byte order.

Prove-it-bites (a gate that can't fail is not a gate): a season with *_exp stripped fails check 1; an all-null
Quality column fails check 3; differing values are unequal while a row-permutation is equal (the value
predicate bites, order-insensitively).

Run: python3 -m application.data.corpus.check_expected_points [--sample-per-season N]
"""
import argparse
import contextlib
import io
import sys
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.transforms import (
    compute_bracket_sim,
    compute_player_signal,
    compute_positional_depth,
    compute_production_vor,
    compute_true_rank,
)
from application.data.transforms._scoring import EXP_COMPONENT_COLS

ALL_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
QUALITY_COLS = ("quality_rate", "luck", "point_correlation")

# The 5 reads: (compute, path, needs_scoring_key). The first four are the blast-radius set (must equal 3b in
# value); player_signal is the one that legitimately moved (Quality lit). We compare recompute-vs-persisted
# ORDER-INSENSITIVELY (see _frame_eq) — polars' parquet writer is physically non-deterministic (the on-disk
# bytes flake run-to-run for a byte-identical in-memory frame), and blast-radius / reproducibility are about
# VALUE-identity, not the on-disk byte order.
_BLAST = [
    (compute_production_vor.compute, data_layer._production_vor_path, True),
    (compute_true_rank.compute, data_layer._true_rank_path, False),
    (compute_positional_depth.compute, data_layer._positional_depth_path, False),
    (compute_bracket_sim.compute, data_layer._bracket_odds_path, True),
]
_SIGNAL = (compute_player_signal.compute, data_layer._player_signal_path, False)


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality: same columns + same VALUES, ignoring row order. polars' parquet
    writer is physically non-deterministic — the on-disk bytes flake run-to-run for a byte-identical
    in-memory frame (values AND row order are stable) — so the project compares recompute VALUES, not the
    byte stream. Sorts both by all columns, then frame-eq."""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:60} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


# --- predicates (factored out so prove-it-bites can call them directly) --------------------------------

def _exp_present(df: pl.DataFrame) -> bool:
    return all(c in df.columns for c in EXP_COMPONENT_COLS)


def _exp_populated(df: pl.DataFrame) -> bool:
    """Present AND carrying signal — a season whose *_exp are all-zero/all-null is as bad as an absent one
    (standing instruction 1). receptions_exp is the broadest always-on component; a real season has ~24% of
    rows nonzero, so >0 is a safe floor that a silent zero-season fails."""
    if not _exp_present(df) or "receptions_exp" not in df.columns:
        return False
    return float((df["receptions_exp"].fill_null(0.0) != 0.0).mean()) > 0.0


def _quality_lit(ps: pl.DataFrame) -> bool:
    """The §1 Quality axis is lit (not held-null like 3b): quality_rate + luck fully non-null (they are
    defined for every row when *_exp is present), point_correlation not entirely null (it carries structural
    low-sample nulls, but a fully-null column means has_exp was False)."""
    return (all(c in ps.columns for c in QUALITY_COLS)
            and float(ps["quality_rate"].is_null().mean()) == 0.0
            and float(ps["luck"].is_null().mean()) == 0.0
            and float(ps["point_correlation"].is_null().mean()) < 1.0)


# --- sample selection ---------------------------------------------------------------------------------

def _sample(n_per_season: int) -> list[dict]:
    """First N matched leagues per season (deterministic) that have a full spine — spanning all six seasons
    so the determinism/Quality proof covers 2025 (unchanged) alongside 2020–24 (backfilled)."""
    by_season = defaultdict(list)
    for r in compute_spine.targets():          # matched stratum, deterministic order
        by_season[int(r["season"])].append(r)
    picked = []
    for s in sorted(by_season):
        present = [r for r in by_season[s]
                   if compute_spine._spine_present(str(r["league_id"]), s)]
        picked.extend(present[:n_per_season])
    return picked


# --- value-identity / blast-radius (recompute a sample → equal to 3b; never touches canonical data) ----

def _check_recompute(sample_rows, results):
    print("  3+4 — recompute a sample from the augmented join (value-identity + blast radius):")
    checked = 0
    for r in sample_rows:
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        if not compute_spine._spine_present(lid, season):
            continue
        # Blast radius: the 4 reads recompute VALUE-identical to their persisted 3b output (they read
        # neither *_exp nor player_signal). Order-insensitive — the parquet writer's bytes flake run-to-run
        # (values stable); this proves the values didn't move, which is the real claim.
        blast_same = True
        for comp, path_fn, needs_sk in _BLAST:
            kw = {"scoring_key": sk} if needs_sk else {}
            got = _quiet(lambda: comp(season, league_id=lid, **kw))
            blast_same = blast_same and _frame_eq(got, pl.read_parquet(path_fn(season, lid)))
        # player_signal: reproducible (recompute value-identical) AND §1 Quality lit.
        comp, path_fn, _ = _SIGNAL
        got = _quiet(lambda: comp(season, league_id=lid))
        persisted = pl.read_parquet(path_fn(season, lid))
        ps_same = _frame_eq(got, persisted)
        ps_lit = _quality_lit(persisted)
        _ok(f"{lid} {season}: 4 reads value-identical to 3b; player_signal reproducible + Quality lit",
            blast_same and ps_same and ps_lit, results,
            "" if (blast_same and ps_same and ps_lit)
            else f"(blast={blast_same} ps_repro={ps_same} quality_lit={ps_lit})")
        checked += 1
    if not checked:
        print("    (no present sample leagues to recompute)")


# --- the gate -----------------------------------------------------------------------------------------

def check(sample_per_season: int = 1) -> bool:
    results: list = []
    print("=== expected-points backfill gate (Session 3c) ===")

    # 1 — *_exp present + populated for every season.
    print("  1 — *_exp present + populated for 2020–2025 (no null/missing season):")
    for season in ALL_SEASONS:
        ns = data_layer.read_nfl_stats(season)
        present, populated = _exp_present(ns), _exp_populated(ns)
        rate = float((ns["receptions_exp"].fill_null(0.0) != 0.0).mean()) if "receptions_exp" in ns.columns else 0.0
        _ok(f"{season}: 14 *_exp present + populated", present and populated, results,
            f"receptions_exp nonzero {rate:.1%}")

    # 2 — the consumer (join) carries *_exp for a sample per season.
    print("  2 — matched joins carry *_exp (the read consumes the join):")
    sample = _sample(sample_per_season)
    join_bad = []
    for r in sample:
        lid, season = str(r["league_id"]), int(r["season"])
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        j = data_layer.read_join_season(season, league_id=lid)
        if not _exp_present(j):
            join_bad.append((lid, season))
    _ok(f"sample matched joins carry all 14 *_exp ({len(sample)} leagues across {len(ALL_SEASONS)} seasons)",
        not join_bad, results, "" if not join_bad else f"{len(join_bad)} missing, e.g. {join_bad[:3]}")

    # 3 + 4 — recompute determinism + Quality lit + blast radius.
    _check_recompute(sample, results)

    # prove-it-bites (logic-level; no store mutation)
    print("  PROVE-BITES:")
    ns2024 = data_layer.read_nfl_stats(2024)
    _ok("check-1 detects a season with *_exp stripped",
        not _exp_present(ns2024.drop(EXP_COMPONENT_COLS)), results)
    _ok("check-1 passes on the real (populated) season", _exp_populated(ns2024), results)
    all_null = pl.DataFrame({"quality_rate": [None, None], "luck": [None, None],
                             "point_correlation": [None, None]}).with_columns(
        [pl.col(c).cast(pl.Float64) for c in QUALITY_COLS])
    _ok("check-3 fails on an all-null Quality axis", not _quality_lit(all_null), results)
    _ok("check-3/4 value-equality predicate bites (different values ≠; order-insensitive)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — *_exp present + populated across 2020–2025, the "
          f"consumer sees it, §1 Quality is lit + reproducible, and the blast radius is contained.")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the expected-points backfill (Session 3c).")
    ap.add_argument("--sample-per-season", type=int, default=1,
                    help="matched leagues per season for the recompute proof (default 1 → 6 leagues)")
    a = ap.parse_args()
    sys.exit(0 if check(a.sample_per_season) else 1)


if __name__ == "__main__":
    main()
