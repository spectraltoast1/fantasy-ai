"""League registry builder (Improvement-Loop L0 keying).

Writes `leagues.parquet` — the single source of truth for "which leagues exist and how each is keyed"
(replacing the implicit `config.SLEEPER_LEAGUE_ID` single-league assumption, audit S1.3). The registry is
a **projection of the corpus manifest** (the authoritative, already-classified set from Sessions 0.5/0.6)
**unioned with the live config league**, so the classification lives in exactly one place and never drifts.

One row per (league_id, season):
    league_id · season · scoring_key · shape_key · is_mine · onboarded_at · pilot_cohort

`pilot_cohort` is derived from the manifest stratum (mine → "mine", matched → "corpus",
generalization → "corpus_gen"). The is_mine league is the one every derived read/write defaults to
(`data_layer._active_league`); corpus (backfill) leagues carry is_mine=false.

Run: python3 -m application.shared.league_registry build [--season 2025 ...]
"""
import argparse
import sys
from datetime import datetime, timezone

import polars as pl

from application import config
from application.data import data_layer
from application.data.transforms import _keys

_REG_SCHEMA = {
    "league_id": pl.Utf8, "season": pl.Int64, "scoring_key": pl.Utf8, "shape_key": pl.Utf8,
    "is_mine": pl.Boolean, "onboarded_at": pl.Utf8, "pilot_cohort": pl.Utf8,
}
_COHORT = {"mine": "mine", "matched": "corpus", "generalization": "corpus_gen"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reg_row_from_manifest(r: dict) -> dict:
    """Project one non-excluded corpus-manifest row onto the registry schema (reuses its classification)."""
    return {
        "league_id": str(r["league_id"]),
        "season": int(r["season"]),
        "scoring_key": r["scoring_key"],
        "shape_key": r["shape_key"],
        "is_mine": bool(r["is_mine"]),
        "onboarded_at": r.get("selected_at") or _now(),
        "pilot_cohort": _COHORT.get(r["stratum"]),
    }


def _mine_shape_key(season: int, league_id: str) -> str:
    """Best-effort shape_key for the live league from persisted settings, reusing the corpus classifier.

    Only reached in the bootstrap case (no corpus manifest yet). shape_key is registry metadata, not a
    partition key, and the manifest is authoritative when present — so this degrades gracefully. Reads the
    raw config with an EXPLICIT league_id (the config league it is building for): the raw layer is now
    league-keyed and its default resolution goes through `_active_league`, which reads the very
    leagues.parquet this builder writes — an explicit key breaks that bootstrap cycle (Session 3a)."""
    try:
        from application.data.transforms import _manager
        slots = data_layer.read_roster_positions(season, league_id=league_id)["slot"].to_list()
        league = data_layer.read_playoff_settings(season, league_id=league_id)
        num_teams = league.get("num_teams") or league.get("total_rosters")
        return _keys.shape_key(num_teams, _manager.qb_structure(slots),
                               _manager.league_format(league.get("type")))
    except Exception:   # noqa: BLE001 — bootstrap best-effort; the manifest supplies the real shape_key
        return _keys.shape_key(None, "1qb", "redraft")


def _ensure_mine(rows: list, seen: set, season: int) -> None:
    """Guarantee an is_mine row for the live config league in `season`, even without a corpus manifest.

    The functional keys (league_id, scoring_key) are seeded from config + the persisted scoring settings;
    shape_key is best-effort (see `_mine_shape_key`). No-op if the manifest already carried this league."""
    lid = str(config.SLEEPER_LEAGUE_ID)
    if (lid, season) in seen:
        return
    scoring = data_layer.read_scoring_settings(season, league_id=lid)
    rows.append({
        "league_id": lid, "season": season,
        "scoring_key": _keys.scoring_key_from_settings(scoring),
        "shape_key": _mine_shape_key(season, lid),
        "is_mine": True, "onboarded_at": _now(), "pilot_cohort": "mine",
    })
    seen.add((lid, season))


def build(seasons=(2025,)) -> pl.DataFrame:
    """Build leagues.parquet from the corpus manifest (∖ excluded) ∪ the live config league; overwrite."""
    rows, seen = [], set()
    if data_layer.corpus_manifest_exists():
        m = data_layer.read_corpus_manifest().filter(pl.col("stratum") != "excluded")
        for r in m.iter_rows(named=True):
            rows.append(_reg_row_from_manifest(r))
            seen.add((str(r["league_id"]), int(r["season"])))
    for season in seasons:
        _ensure_mine(rows, seen, season)
    df = pl.DataFrame(rows, schema=_REG_SCHEMA)
    data_layer.write_leagues(df)
    return df


def main():
    ap = argparse.ArgumentParser(description="Build the league registry (leagues.parquet).")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="build/overwrite leagues.parquet")
    b.add_argument("--season", type=int, action="append", dest="seasons",
                   help="season(s) to guarantee a live is_mine row for (default: 2025). Repeatable.")
    a = ap.parse_args()
    if a.cmd != "build":
        ap.error("expected the 'build' subcommand")
    seasons = tuple(a.seasons) if a.seasons else (2025,)
    df = build(seasons)
    mine = df.filter(pl.col("is_mine"))
    print(f"leagues.parquet: {df.height} rows | is_mine={mine.height} | "
          f"cohorts={dict(df['pilot_cohort'].value_counts().iter_rows())}")
    for r in mine.iter_rows(named=True):
        print(f"  mine: season={r['season']} league_id={r['league_id']} "
              f"scoring_key={r['scoring_key']} shape_key={r['shape_key']}")


if __name__ == "__main__":
    main()
    sys.exit(0)
