"""
retire_xtd.py — Corpus cleanup C2: drop the dead `xtd` column from the 2020-24 substrate.

`xtd` is the retired hand-rolled TD-proxy (Σ td_prob) that the ff_opportunity `*_exp` expected-points model
superseded. It survives only on the 2020-24 `nfl_stats` + `join_season` parquets (built before the proxy was
retired); 2025 lacks it, so the six-season corpus schema is inconsistent. Its ONLY code reference anywhere is
a comment in `nfl_stats.py` — nothing reads it. Dropping it unifies the schema.

This is an additive-INVERSE (a column drop) and must move NO live number (standing instruction 5 — deleting
dead code moves no live number): every OTHER column stays byte-identical and the row count is unchanged
(asserted per file); and because the derived reads select their inputs by name (never `xtd`), the 5-read
spine recomputes value-identical (proven by check_spine after the drop). Idempotent — a re-run over a
schema that no longer carries `xtd` is a no-op.

Usage:
    python3 -m application.data.corpus.retire_xtd            # nfl_stats 2020-24 + every join carrying xtd
    python3 -m application.data.corpus.retire_xtd --dry-run  # report what carries xtd; write nothing
"""
import argparse
import glob
import re
import sys

import polars as pl

from application.data import data_layer

_COL = "xtd"
_NFL_SEASONS = (2020, 2021, 2022, 2023, 2024)


def _assert_additive_inverse(before: pl.DataFrame, after: pl.DataFrame, tag: str) -> None:
    """The only change may be the dropped `xtd` column: same rows, every remaining column byte-identical."""
    if after.height != before.height:
        raise RuntimeError(f"{tag}: row count {before.height}→{after.height} on xtd drop — not additive-inverse")
    moved = [c for c in after.columns if not after[c].equals(before[c])]
    if moved:
        raise RuntimeError(f"{tag}: pre-existing columns moved {moved[:5]} on xtd drop — not additive-inverse")


def _drop_from_nfl_stats(dry_run: bool) -> list:
    """Drop `xtd` from each 2020-24 nfl_stats season file (full overwrite). Returns [(year, before_w, after_w)]."""
    changed = []
    for yr in _NFL_SEASONS:
        df = data_layer.read_nfl_stats(yr)
        if _COL not in df.columns:
            continue
        out = df.drop(_COL)
        _assert_additive_inverse(df, out, f"nfl_stats {yr}")
        if not dry_run:
            data_layer.write_nfl_stats(out, yr)
        changed.append((yr, df.width, out.width))
    return changed


def _join_targets() -> list:
    """(league_id, season) for every persisted join_season carrying `xtd` (schema scan, no full read)."""
    base = data_layer._SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / "league"
    out = []
    for p in glob.glob(str(base / "*" / "season_*.parquet")):
        m = re.search(r"league/(\d+)/season_(\d+)\.parquet$", p)
        if not m:
            continue
        lid, season = m.group(1), int(m.group(2))
        if _COL in pl.scan_parquet(p).collect_schema().names():
            out.append((lid, season))
    return sorted(out, key=lambda t: (t[1], t[0]))


def _drop_from_joins(dry_run: bool) -> int:
    """Drop `xtd` from every join_season carrying it (mirrors harvest._apply_two_way, inverted). Count dropped."""
    n = 0
    for lid, season in _join_targets():
        df = data_layer.read_join_season(season, league_id=lid)
        if _COL not in df.columns:
            continue
        out = df.drop(_COL)
        _assert_additive_inverse(df, out, f"join {lid} {season}")
        if not dry_run:
            data_layer.write_join_season(out, season, league_id=lid)
        n += 1
    return n


def run(dry_run: bool = False) -> dict:
    tag = "DRY-RUN (no writes)" if dry_run else "retiring xtd"
    print(f"=== {tag}: drop dead `xtd` from the 2020-24 substrate ===")
    nfl = _drop_from_nfl_stats(dry_run)
    print(f"  nfl_stats: {len(nfl)} season(s) carry xtd → dropped "
          f"({', '.join(f'{yr} {b}→{a} cols' for yr, b, a in nfl) or 'none'})")
    n_join = _drop_from_joins(dry_run)
    print(f"  join_season: {n_join} file(s) carried xtd → dropped")
    print(f"  {'(dry-run — nothing written)' if dry_run else 'done — every other column byte-identical, rows unchanged'}")
    return {"nfl_stats": nfl, "joins": n_join, "dry_run": dry_run}


def main():
    ap = argparse.ArgumentParser(description="Retire the dead xtd column from the 2020-24 corpus substrate.")
    ap.add_argument("--dry-run", action="store_true", help="report what carries xtd; write nothing")
    a = ap.parse_args()
    run(dry_run=a.dry_run)


if __name__ == "__main__":
    main()
    sys.exit(0)
