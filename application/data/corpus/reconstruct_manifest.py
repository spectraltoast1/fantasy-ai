"""
Corpus manifest RECONSTRUCTION — the 2026-08-13 recovery.

On 2026-08-12 22:25 a `check_store_boundary --prove-bites` run drove every laptop-owned writer for
real. `write_corpus_manifest` / `write_corpus_discovery` / `write_corpus_two_way_flags` take only a
dataframe, so they had no throwaway target and overwrote the real and only copy with empty frames
(0 rows AND 0 columns — even the schema went). See `sessions/engine/SESSION_CORPUS_RECOVERY.md` and
the rule it bought, CODING_BIBLE §5.

**This module RECONSTRUCTS; it does not REGENERATE. The difference is the whole point.**

`select.py` reads `corpus_discovery` (also destroyed) and would need `discover.py` first — a fresh
BFS crawl against an August-2026 Sleeper that now contains 2026 leagues which did not exist in July.
That would emit a NEW corpus wearing the old one's name: silently no longer the population the
immutable L2 ledger was derived from, which is the one failure mode with no alarm attached. (Worse,
`discover._persist` rewrites `corpus_crawl_state.json` in full at every 25-manager checkpoint, so a
single run also destroys the last surviving record of the July crawl.)

So the population is taken from the **persisted raw harvest** — harvesting only ever happened for
leagues that were actually selected, making it the tightest available bound — and every column is
recomputed from artifacts that survived, with ZERO network calls.

Provenance, column by column:

  league_id · season          the raw harvest dirs (272 on disk − DEMO-2025 synthetic = 271)
  scoring_key                 `_scoring.scoring_profile` + `_keys.scoring_key` over the persisted
                              `league_settings` §scoring block — the same classifier `select.py`
                              re-runs, so the Session-0.6 float32 fix is applied, not re-imported
  num_teams                   `league_settings` §league `num_teams` (present 272/272)
  qb_structure                `_manager.qb_structure` over persisted `roster_positions`
  has_divisions               `league_settings` §league `divisions` >= 2 — yields exactly the 25
                              documented real corpus division leagues (11 matched + 14 gen)
  scoreable · scoreable_reject `select.scoreability` — deterministic, no API
  filter_* · id_resolution_pct · has_transactions
                              `corpus_filter_cache.json` (survived; 271/271 hit, all "pass")
  is_mine                     `demo_manifest` (survived)
  stratum · never_tune        `_corpus.is_matched_eligible`; corroborated three ways (see below)
  league_format · shape_key   see NOT FULLY RECOVERED

NOT FULLY RECOVERED — `league_format` (and hence the format suffix of `shape_key`) for 36 rows.
Sleeper's `settings.type` was never persisted: `fetchers/sleeper.fetch_league_config` keeps an
explicit playoff-key allowlist that excludes it. Absence on disk is therefore NOT evidence of
"redraft" — `_manager.league_format(None)` returns "redraft" because *Sleeper* omits the key on a
classic redraft league, but our harvester drops it unconditionally. Measured proof: 7 leagues known
from `leagues.parquet` to be keeper/dynasty also have no `type` key on disk, so mapping absent ->
redraft would provably misclassify them.

The stale `leagues.parquet` (Jul 14, pre-2.5) carries `shape_key`, whose suffix IS the format, and
covers 235 of the 271. For the remaining 36 the format is left NULL rather than guessed — absence is
reported, never fabricated. This costs nothing structural: all 36 are generalization-eligible on
shape alone (superflex / divisions / custom / exotic size — none of which consults format), no
matched row is affected, `check_corpus` only applies the matched predicate to matched rows, and
`shape_key` is registry metadata that nothing partitions on (`league_registry.py:54`; the derived
layers key on `scoring_key`).

`selected_at` is a wall-clock column and is lost for every row — the restore stamp is written
instead, which is why the manifest verdict is CONSISTENT, never EXACT.

The stratum assignment is corroborated three independent ways, and `run()` REFUSES TO WRITE unless
it lands exactly on the documented 221 matched / 48 generalization / 2 mine:
  1. the 235 format-known leagues classify to exactly 221 matched + 12 generalization + 2 mine;
  2. the 36 format-unknown are independently generalization-eligible on shape alone;
  3. 12 + 36 = 48, the documented generalization count.

Run: python3 -m application.data.corpus.reconstruct_manifest [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polars as pl

from application.data import data_layer
from application.data.corpus import _corpus
from application.data.corpus.select import _MANIFEST_COLS, scoreability
from application.data.transforms import _keys, _manager, _scoring

# The corpus population is the persisted raw harvest, minus the generated demo clone. `DEMO-2025` is
# in `data_layer.SYNTHETIC_LEAGUE_IDS`: it was generated, never crawled and never judged (it is the
# one harvest dir absent from the filter cache), so it was never a manifest row.
SEASONS = range(2020, 2026)

# The documented frozen strata. A reconstruction that misses these has not recovered the corpus, so
# this is a hard stop rather than a warning (SESSION_CORPUS_RECOVERY §2 — a difference is escalated,
# never quietly accepted).
EXPECTED_STRATA = {"matched": 221, "generalization": 48, "mine": 2}


def _raw_population() -> list[tuple[int, str]]:
    """Every (season, league_id) with a persisted raw harvest — the tightest bound on the corpus."""
    out = []
    for season in SEASONS:
        base = data_layer._SNAPSHOT_DIR / "sleeper" / str(season) / "league"
        if not base.is_dir():
            continue
        for lid in sorted(os.listdir(base)):
            if lid.startswith(".") or data_layer.is_synthetic(lid):
                continue
            out.append((season, lid))
    return out


def _settings(season: int, league_id: str) -> tuple[dict, dict]:
    """(scoring_settings, league_settings) from the persisted tall section/key/value frame."""
    df = data_layer.read_league_settings(season, league_id=league_id)
    scoring, league = {}, {}
    for section, key, value in df.iter_rows():
        (scoring if section == "scoring" else league)[key] = value
    return scoring, league


def _filter_verdicts() -> dict:
    """The recorded July selection verdicts, keyed by league_id. Located exactly as `select.py` does.

    This is the surviving *record* of the inclusion filter, not an inference from it: 427 judged,
    359 pass / 68 fail, each failure carrying its reason. JSON, so it is read directly — the same
    thing `select.py:280` does; there is no data_layer entity for it.
    """
    path = data_layer._corpus_manifest_path().parent / "corpus_filter_cache.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _format_witness() -> dict[tuple[int, str], str]:
    """(season, league_id) -> league_format, read off `leagues.parquet`'s `shape_key` suffix.

    `leagues.parquet` is a Jul-14 pre-2.5 projection of the manifest written by
    `league_registry.build()`, so it is STALE as a population (it holds 43 rows the harvest does not)
    and is used ONLY as a per-league witness for this one column, never as a row source.
    """
    lg = data_layer.read_leagues()
    return {(int(s), str(lid)): shape.rsplit("-", 1)[-1]
            for lid, s, shape in zip(lg["league_id"], lg["season"], lg["shape_key"])}


def build() -> pl.DataFrame:
    """The reconstructed manifest, deterministically ordered. Pure: reads only persisted artifacts."""
    fmt_by_league = _format_witness()
    verdicts = _filter_verdicts()
    mine = set(data_layer.read_demo_manifest().filter(pl.col("is_mine"))["league_id"].to_list())
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for season, lid in _raw_population():
        scoring, league = _settings(season, lid)
        profile = _scoring.scoring_profile(scoring)
        num_teams = int(league["num_teams"]) if league.get("num_teams") is not None else None
        qb = _manager.qb_structure(data_layer.read_roster_positions(season, league_id=lid)["slot"].to_list())
        has_divisions = int(league.get("divisions") or 0) >= 2
        league_format = fmt_by_league.get((season, lid))   # None for the 36 — see the module docstring
        sc_ok, sc_rej = scoreability(profile, scoring)

        if lid in mine:
            stratum = "mine"
        elif league_format is not None and _corpus.is_matched_eligible(
                _keys.scoring_key(profile, scoring), qb, league_format, num_teams):
            stratum = "matched"
        else:
            # Format-unknown rows can never be matched (the predicate requires redraft), and every
            # one of them is independently generalization-eligible on shape alone — asserted below.
            stratum = "generalization"
            if league_format is None and not _corpus.is_generalization_eligible(
                    profile, qb, has_divisions, num_teams):
                raise AssertionError(
                    f"{season}/{lid}: format unknown AND not generalization-eligible on shape — its "
                    f"stratum genuinely depends on the unrecovered league_format. STOP AND ESCALATE.")

        v = verdicts.get(lid, {})
        rows.append({
            "league_id": lid,
            "season": season,
            "scoring_key": _keys.scoring_key(profile, scoring),
            # Null format -> null shape_key. A synthesised "…-unknown" would assert a recovered value.
            "shape_key": _keys.shape_key(num_teams, qb, league_format) if league_format else None,
            "num_teams": num_teams,
            "qb_structure": qb,
            "league_format": league_format,
            "has_divisions": has_divisions,
            "stratum": stratum,
            "never_tune": stratum != "matched",       # mirrors select.add_manifest
            "scoreable": sc_ok,
            "scoreable_reject": sc_rej,
            "filter_result": v.get("filter_result"),
            "filter_reason": v.get("filter_reason"),
            "id_resolution_pct": v.get("id_resolution_pct"),
            "has_transactions": v.get("has_transactions"),
            "is_mine": lid in mine,
            "selected_at": stamp,                     # original wall-clock value is unrecoverable
        })

    # Neither discover nor select sorts before writing, so row order was never evidence of anything.
    # Sort explicitly so the reconstruction is reproducible rather than dict-insertion-ordered.
    return pl.DataFrame(rows, infer_schema_length=None).select(_MANIFEST_COLS).sort("season", "league_id")


def run(dry_run: bool = False) -> None:
    df = build()
    strata = {k: v for k, v in zip(*df.group_by("stratum").len().sort("stratum").to_dict(as_series=False).values())}
    print(f"reconstructed {df.height} rows | strata: {strata}")

    unknown = df.filter(pl.col("league_format").is_null())
    print(f"  league_format recovered {df.height - unknown.height}/{df.height} "
          f"({unknown.height} left NULL — all stratum={set(unknown['stratum'].to_list())})")

    if strata != EXPECTED_STRATA:
        print(f"  ✗ strata {strata} != documented {EXPECTED_STRATA} — NOT WRITING. Escalate: the "
              f"reconstruction disagrees with the population the frozen L2 ledger was derived from.")
        sys.exit(1)
    print(f"  ✓ strata match the documented frozen corpus {EXPECTED_STRATA}")

    if dry_run:
        print("  (--dry-run: nothing written)")
        return
    data_layer.write_corpus_manifest(df)
    print("  → snapshots/corpus/corpus_manifest.parquet")


def main():
    ap = argparse.ArgumentParser(description="Reconstruct the frozen corpus manifest (offline).")
    ap.add_argument("--dry-run", action="store_true", help="classify and report; write nothing")
    a = ap.parse_args()
    run(a.dry_run)


if __name__ == "__main__":
    main()
    sys.exit(0)
