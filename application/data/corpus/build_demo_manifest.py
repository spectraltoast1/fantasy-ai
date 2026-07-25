"""Build the demo manifest — the authoritative Stage-B demo slate (session B0).

Records the locked 12-lineage / 31-slice demo set (``demo_slate.csv``, delivered with the B0 brief)
into the data layer: per slice its resolved ``league_id``, a root-keyed ``lineage_id``, a pinned
``viewer_roster_id`` ("you" for that slice), and the panel-gating policy. **No analytics are computed
here (that is B2) and no frontend changes (B5).** This is data-modelling + recording only.

Inputs (read-only):
  - ``demo_slate.csv`` (this directory) — the locked slate: (lineage, name, season, league_id,
    scoring_key, num_teams, is_mine). The lineage slug groups a redraft chain's seasons.
  - ``corpus_discovery`` — display ``name`` + ``previous_league_id`` (chain validation).
  - Sleeper ``teams`` per (season, league_id) — viewer resolution.
  - The raw harvest (join ``season_<yr>`` + sleeper league dir) — presence check.

Output: ``snapshots/demo_manifest.parquet`` via ``data_layer.write_demo_manifest`` — one row per demo
slice with ``_DEMO_MANIFEST_COLS``. It is the source B2 (compute) and B3 (loader + ``/api/leagues``)
read the slate from. Like ``leagues.parquet`` the parquet is generated runtime; this script + the CSV
are the version-controlled deliverables.

Policies (locked with Will in the B0 brief):
  - ``lineage_id`` = the chain **root**: the earliest-season league_id of the lineage (globally unique
    Sleeper id — never collides). The human slug is a label only, not persisted.
  - viewer: the **is_mine** lineage pins ``config.SLEEPER_USERNAME``'s roster per season; each **corpus**
    lineage pins the owner present in the most of its seasons (tie → lowest owner_id), resolved to that
    owner's roster_id per season. Provisional-but-valid (the mid-table refinement is a post-B2 polish).
  - panels: ``manager`` ON for all 31 (dossiers come from transaction/roster history every slice has);
    ``market`` + ``ros`` ON **only** for the is_mine 2025 slice (the one live slice with a current market
    / news world — historical seasons can't reconstruct them honestly).

Usage:
    python3 -m application.data.corpus.build_demo_manifest            # build + write
    python3 -m application.data.corpus.build_demo_manifest --report   # resolve + print, do NOT write
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

import application.config as config
from application.data import data_layer

_SLATE_CSV = Path(__file__).resolve().parent / "demo_slate.csv"


def _load_slate() -> pl.DataFrame:
    return pl.read_csv(_SLATE_CSV, schema_overrides={"league_id": pl.Utf8, "season": pl.Int64})


def _prev_map() -> dict[str, str | None]:
    """league_id -> previous_league_id from corpus_discovery (a league's chain link, season-invariant)."""
    disc = data_layer.read_corpus_discovery().select("league_id", "previous_league_id").unique()
    return {r["league_id"]: r["previous_league_id"] for r in disc.iter_rows(named=True)}


def _walk_root(league_id: str, prev: dict[str, str | None]) -> str:
    """Follow previous_league_id back to the deepest ancestor known to discovery — the chain ROOT.

    Terminates at a null previous_league_id (the true origin) or when the link exits discovery (an
    earlier league never crawled); either way the deepest league_id we can establish. Root-keying (vs.
    the earliest *demo* season) keeps lineage_id stable if an earlier season is later added, and globally
    unique since it's a Sleeper id — the B0 brief's duplicate-proof requirement. Cycle-guarded."""
    seen: set[str] = set()
    cur = league_id
    while True:
        p = prev.get(cur)
        if not p or p not in prev or p in seen:
            return cur
        seen.add(cur)
        cur = p


def _lineage_roots(slate: pl.DataFrame, prev: dict[str, str | None]) -> dict[str, str]:
    """lineage slug -> root league_id (deepest discovered ancestor of the earliest slate season)."""
    roots: dict[str, str] = {}
    for lineage, grp in slate.group_by("lineage"):
        name = lineage[0] if isinstance(lineage, tuple) else lineage
        earliest = grp.sort("season").row(0, named=True)
        roots[name] = _walk_root(earliest["league_id"], prev)
    return roots


def _raw_harvest_ok(season: int, league_id: str) -> bool:
    """The raw a B2 compute needs: the NFL×Sleeper join for the season + the sleeper league dir."""
    join = data_layer._join_league_dir(league_id) / f"season_{season}.parquet"
    sleeper = data_layer._sleeper_league_dir(season, league_id)
    return join.exists() and sleeper.exists()


def _teams(season: int, league_id: str) -> pl.DataFrame | None:
    try:
        return data_layer.read_sleeper_teams(season, league_id=league_id)
    except Exception:
        return None


def _viewer_owner_for_lineage(slate_rows: list[dict], is_mine: bool) -> str | None:
    """Pick the viewer OWNER for a lineage.

    is_mine -> config.SLEEPER_USERNAME's owner_id (stable across the chain's seasons).
    corpus  -> the owner present in the most of the lineage's seasons; tie -> lowest owner_id.
    """
    if is_mine:
        for r in slate_rows:
            t = _teams(r["season"], r["league_id"])
            if t is not None:
                m = t.filter(pl.col("owner_name") == config.SLEEPER_USERNAME)
                if m.height:
                    return str(m["owner_id"][0])
        return None
    tenure: dict[str, int] = {}
    for r in slate_rows:
        t = _teams(r["season"], r["league_id"])
        if t is None:
            continue
        for oid in t["owner_id"].to_list():
            tenure[str(oid)] = tenure.get(str(oid), 0) + 1
    if not tenure:
        return None
    # max seasons present, tie-broken by lowest owner_id (deterministic).
    return sorted(tenure.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _roster_for_owner(season: int, league_id: str, owner_id: str | None):
    t = _teams(season, league_id)
    if t is None or owner_id is None:
        return None
    m = t.filter(pl.col("owner_id") == owner_id)
    return int(m["roster_id"][0]) if m.height else None


def build(report: bool = False) -> pl.DataFrame:
    slate = _load_slate()
    disc = data_layer.read_corpus_discovery().select(
        "league_id", "season", "name", "previous_league_id"
    )
    disc_by_id = {(r["league_id"], r["season"]): r for r in disc.iter_rows(named=True)}
    prev = _prev_map()
    roots = _lineage_roots(slate, prev)

    rows: list[dict] = []
    flags: list[str] = []

    for lineage, grp in slate.group_by("lineage", maintain_order=True):
        name = lineage[0] if isinstance(lineage, tuple) else lineage
        grp = grp.sort("season")
        slate_rows = grp.to_dicts()
        is_mine_lineage = bool(grp["is_mine"][0])
        viewer_owner = _viewer_owner_for_lineage(slate_rows, is_mine_lineage)
        if viewer_owner is None:
            flags.append(f"{name}: could not resolve a viewer owner")

        for r in slate_rows:
            lid, season = r["league_id"], int(r["season"])
            is_mine = bool(r["is_mine"])
            disc_row = disc_by_id.get((lid, season))
            display_name = (disc_row or {}).get("name") or r["name"]
            prev_lid = (disc_row or {}).get("previous_league_id")
            raw_ok = _raw_harvest_ok(season, lid)
            if not raw_ok:
                flags.append(f"{name} {season} ({lid}): raw harvest MISSING")
            viewer_roster = _roster_for_owner(season, lid, viewer_owner)
            if viewer_roster is None:
                flags.append(f"{name} {season} ({lid}): viewer owner absent this season — no roster")
            live_mine_2025 = is_mine and season == 2025
            rows.append({
                "lineage_id": roots[name],
                "league_id": lid,
                "season": season,
                "name": display_name,
                "scoring_key": r["scoring_key"],
                "num_teams": int(r["num_teams"]),
                "is_mine": is_mine,
                "previous_league_id": prev_lid,
                "viewer_roster_id": viewer_roster,
                "panels_market": live_mine_2025,
                "panels_ros": live_mine_2025,
                "panels_manager": True,
            })

    manifest = pl.DataFrame(rows).select(data_layer._DEMO_MANIFEST_COLS).sort("lineage_id", "season")
    _validate_chains(manifest, prev, flags)

    _print_summary(manifest, flags)
    if not report:
        data_layer.write_demo_manifest(manifest)
        print(f"\n  → wrote snapshots/demo_manifest.parquet ({manifest.height} rows)")
    else:
        print("\n  [--report] not written.")
    return manifest


def _validate_chains(manifest: pl.DataFrame, prev: dict[str, str | None], flags: list[str]) -> None:
    """Every slice of a lineage must trace back (via previous_league_id) to the same root, so /api/leagues
    (B3) can group per lineage. Walk-based, so seasons the demo deliberately skips (e.g. dysf omits 2023)
    don't false-flag — a gap only matters if the intervening link is absent from discovery."""
    for lineage_id, grp in manifest.group_by("lineage_id", maintain_order=True):
        root = lineage_id[0] if isinstance(lineage_id, tuple) else lineage_id
        for r in grp.iter_rows(named=True):
            reached = _walk_root(r["league_id"], prev)
            if reached != root:
                flags.append(
                    f"chain {root}: {r['season']} league {r['league_id']} walks to {reached}, not the "
                    f"lineage root (a chain link is missing from discovery)"
                )


def _print_summary(manifest: pl.DataFrame, flags: list[str]) -> None:
    n_lineages = manifest["lineage_id"].n_unique()
    print(f"demo_manifest: {manifest.height} slices / {n_lineages} lineages")
    print(manifest.select("lineage_id", "season", "league_id", "name",
                          "viewer_roster_id", "panels_market", "panels_ros", "panels_manager"))
    mkt = manifest.filter(pl.col("panels_market"))
    print(f"\npanels_market/ros ON for {mkt.height} slice(s): "
          f"{[(r['name'], r['season']) for r in mkt.iter_rows(named=True)]}")
    print(f"panels_manager ON for all {manifest.height}: {manifest['panels_manager'].all()}")
    print(f"every slice has a viewer_roster_id: {manifest['viewer_roster_id'].null_count() == 0}")
    if flags:
        print(f"\n⚠ {len(flags)} flag(s):")
        for f in flags:
            print(f"    - {f}")
    else:
        print("\n✓ no flags — every slice resolves, raw present, chains clean.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Stage-B demo manifest from demo_slate.csv.")
    parser.add_argument("--report", action="store_true", help="Resolve + print, do NOT write.")
    args = parser.parse_args()
    build(report=args.report)
