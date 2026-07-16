"""
backfill_predictions.py — reshape the frozen corpus spine into the L2 `predictions` ledger (Session 4a, C2).

Reads the FROZEN 5-read spine + the FROZEN scoring-scoped `ros_player_band`, and emits immutable CLAIM
rows (`served=false` reconstruction) for the 270 spined league-seasons (221 matched + 48 generalization
+ is_mine 2025). It reshapes; it does not fetch, recompute a read, re-select, or re-tune (standing instr
8). No grade, no verdict — Law 1 is structural.

Per league-season: read the 5 league reads (as_of_week="all") + emit the 8 league-scoped claim families.
The scoring-scoped `ros_player_band` is emitted ONCE per (scoring_key, season) with `league_id=null` —
re-emitting per league would multiply-count it in 4b's outcomes join.

Idempotent + resumable (the 3a precedent): the write is append-only-of-new by `prediction_id` (which
folds in `code_version`), so a re-run under the same code appends NOTHING; a per-season done-cache skips
already-written leagues/bands so a resumed run reads nothing it doesn't need. Per-league failure is
ISOLATED. Determinism is the load-bearing property: `prediction_id` is a pure sha1 of its key (never
wall-clock), so a twice-backfill is value-identical (verified by check_predictions).

Usage:
    python3 -m application.data.corpus.backfill_predictions --strata mine --limit 1   # is_mine 2025, proof
    python3 -m application.data.corpus.backfill_predictions --pilot 6                  # cross-stratum sample
    python3 -m application.data.corpus.backfill_predictions                            # full 270
"""
import argparse
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine, constants_snapshot, inputs_ok, predictions_map

BACKFILL_STRATA = ("matched", "generalization", "mine")

# source read -> the data_layer reader (league-scoped take league_id; the band takes scoring_key).
_LEAGUE_READERS = {
    "production_vor": data_layer.read_production_vor,
    "player_signal": data_layer.read_player_signal,
    "true_rank": data_layer.read_true_rank,
    "positional_depth": data_layer.read_positional_depth,
    "bracket_odds": data_layer.read_bracket_odds,
}


def _git_sha() -> str:
    """The git sha at write time (the `code_version` provenance). Names the commit; a dirty tree is not
    reflected — the authoritative store is regenerated at a clean commit."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(os.path.abspath(__file__))
    ).decode().strip()


def targets(strata=BACKFILL_STRATA, limit=None) -> list[dict]:
    """The spined manifest rows to reshape, deterministic order. Filters to spine-present (so is_mine
    2024 — harvested but never spined — is excluded), then applies `limit` to the spined set."""
    rows = [r for r in compute_spine.targets(strata)
            if compute_spine._spine_present(str(r["league_id"]), int(r["season"]))]
    return rows[:limit] if limit else rows


def pilot_targets(n: int, strata=BACKFILL_STRATA) -> list[dict]:
    per = max(1, n // len(strata))
    picked = []
    for st in strata:
        picked.extend(targets((st,))[:per])
    return picked[:n] if n else picked


def _done_cache(season: int, code_version: str) -> dict:
    """What's already on disk for a season UNDER THIS code_version — {leagues: set(league_id),
    bands: set(scoring_key)} — read once per season so the skip costs one read, not one-per-league.
    Keyed on `code_version`: a re-run under a NEW code_version is deliberately NOT skipped, so it writes
    its parallel population (the write is idempotent by prediction_id, so a same-version re-run appends
    nothing anyway — this just avoids re-reading the reads)."""
    if not data_layer.predictions_exists(season):
        return {"leagues": set(), "bands": set()}
    df = data_layer.read_predictions(season).filter(pl.col("code_version") == code_version)
    leagues = set(df.filter(pl.col("league_id").is_not_null())["league_id"].unique().to_list())
    bands = set(df.filter(pl.col("read") == predictions_map.BAND_SOURCE)["scoring_key"].unique().to_list())
    return {"leagues": leagues, "bands": bands}


def run(strata=BACKFILL_STRATA, limit=None, pilot=None, code_version=None) -> dict:
    cv = code_version or _git_sha()
    chash = constants_snapshot.constants_hash()
    man = data_layer.read_corpus_manifest()
    tgts = pilot_targets(pilot, strata) if pilot else targets(strata, limit)

    t0 = time.time()
    league_written = league_skipped = band_written = band_skipped = 0
    rows_written = 0
    by_family = Counter()                       # (read, claim_type) -> rows
    inputs_false = []                           # (league_id, season, fail_reasons)
    errored = []                                # (league_id, season, error)
    seasons_touched = set()
    done = {}                                    # season -> _done_cache (lazy)
    emitted_bands = defaultdict(set)             # season -> {scoring_key} emitted THIS run

    for i, r in enumerate(tgts, 1):
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        tag = f"[{i}/{len(tgts)}] {r['stratum']:14} {lid} {season} {sk}"
        if season not in done:
            done[season] = _done_cache(season, cv)
        try:
            # --- league-scoped claims (8 families) ---
            if lid in done[season]["leagues"]:
                league_skipped += 1
            else:
                iok = inputs_ok.inputs_ok_detail(lid, season, manifest=man)
                if not iok["ok"]:
                    inputs_false.append((lid, season, iok["fail_reasons"]))
                ctx = {"league_id": lid, "scoring_key": sk, "season": season,
                       "code_version": cv, "constants_hash": chash, "inputs_ok": iok["ok"]}
                frames = {src: _LEAGUE_READERS[src](season, league_id=lid, as_of_week="all")
                          for src in predictions_map.LEAGUE_SOURCES}
                claims = predictions_map.build_league_claims(frames, ctx)
                data_layer.write_predictions(claims, season)
                league_written += 1
                rows_written += claims.height
                seasons_touched.add(season)
                for read, ct, cnt in claims.group_by("read", "claim_type").len().iter_rows():
                    by_family[(read, ct)] += cnt

            # --- scoring-scoped band claims (once per (scoring_key, season), league_id=null) ---
            if sk in done[season]["bands"] or sk in emitted_bands[season]:
                band_skipped += 1
            else:
                band_df = data_layer.read_ros_player_band(season, scoring_key=sk, as_of_week="all")
                # The band's four league integrity signals are N/A (roster-free scoring substrate, gated at
                # Session 2/2.5 build) → inputs_ok=True by construction; documented, not a blanket league flag.
                bctx = {"league_id": None, "scoring_key": sk, "season": season,
                        "code_version": cv, "constants_hash": chash, "inputs_ok": True}
                bclaims = predictions_map.build_band_claims(band_df, bctx)
                data_layer.write_predictions(bclaims, season)
                band_written += 1
                rows_written += bclaims.height
                seasons_touched.add(season)
                emitted_bands[season].add(sk)
                for read, ct, cnt in bclaims.group_by("read", "claim_type").len().iter_rows():
                    by_family[(read, ct)] += cnt
            if lid not in done[season]["leagues"] or sk not in done[season]["bands"]:
                print(f"  {tag}  written")
            else:
                print(f"  {tag}  SKIP (present)")
        except Exception as exc:   # noqa: BLE001 — isolate one league; a re-run retries it
            errored.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:160]}")

    report = {
        "targets": len(tgts), "code_version": cv, "constants_hash": chash,
        "league_written": league_written, "league_skipped": league_skipped,
        "band_written": band_written, "band_skipped": band_skipped,
        "rows_written": rows_written, "elapsed_s": round(time.time() - t0, 1),
        "by_family": dict(by_family),
        "file_sizes": {s: round(os.path.getsize(data_layer._predictions_path(s)) / 1e6, 2)
                       for s in sorted(seasons_touched) if data_layer.predictions_exists(s)},
        "inputs_false": inputs_false, "errored": errored,
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== predictions backfill report ===")
    print(f"  targets={rep['targets']}  code_version={rep['code_version'][:12]}  "
          f"constants_hash={rep['constants_hash']}")
    print(f"  leagues written={rep['league_written']} skipped={rep['league_skipped']}  |  "
          f"bands written={rep['band_written']} skipped={rep['band_skipped']}")
    print(f"  rows written this run={rep['rows_written']:,}  wall-clock={rep['elapsed_s']}s  "
          f"(incremental re-run ≈ 0 — append-only-of-new)")
    print("  by claim family (read, claim_type):")
    for (read, ct), cnt in sorted(rep["by_family"].items()):
        print(f"    {read:18} {ct:12} {cnt:>10,}")
    if rep["file_sizes"]:
        print("  per-season file size (MB):")
        for s, mb in rep["file_sizes"].items():
            print(f"    predictions_{s}.parquet  {mb}")
    print(f"  inputs_ok=false league-seasons: {len(rep['inputs_false'])}")
    for lid, season, reasons in rep["inputs_false"]:
        print(f"    {lid} {season}: {reasons}")
    print(f"  errored (isolated; retried on re-run): {len(rep['errored'])}")
    for lid, season, err in rep["errored"]:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Backfill the L2 predictions ledger (Session 4a).")
    ap.add_argument("--strata", nargs="+", default=list(BACKFILL_STRATA),
                    choices=["matched", "generalization", "mine"])
    ap.add_argument("--limit", type=int, default=None, help="first N spined targets (deterministic order)")
    ap.add_argument("--pilot", type=int, default=None, help="N leagues across strata + budget report")
    ap.add_argument("--code-version", default=None, help="override the git-sha code_version (for tests)")
    a = ap.parse_args()
    run(strata=tuple(a.strata), limit=a.limit, pilot=a.pilot, code_version=a.code_version)


if __name__ == "__main__":
    main()
    sys.exit(0)
