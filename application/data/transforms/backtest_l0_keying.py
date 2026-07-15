"""
Gate for the L0 keying migration (Improvement-Loop Session 1).

L0 moved every league/scoring-scoped derived entity out of the flat `derived/{entity}_{season}.parquet`
into scope-partitioned paths (`derived/league/<league_id>/…`, `derived/scoring/<scoring_key>/…`) so a
second league can never overwrite the first (audit S1.3). This gate proves the move changed **nothing**
about the numbers and that the isolation actually holds. Exit 0 iff every applicable check passes.

  A — **Migration identity (needs the real snapshots).** For each re-keyed entity, frame-compare the
      OLD flat parquet against the NEW keyed parquet for the is_mine league. Skipped per-entity when the
      flat file is absent (already migrated / never built); FAILS if the flat exists but the keyed file
      does not (migration not run yet). This is the "reproduce mine frame-for-frame" guarantee.
  B — **Collision isolation (synthetic; runs anywhere).** Write two different frames under two league_ids
      and confirm each reads back its own rows — league #2 provably cannot overwrite league #1.
  B2 — **Raw-layer collision isolation (synthetic; Session 3a).** The same guarantee on the now-league-keyed
      raw layer (`sleeper/<season>/league/<league_id>/…`), with a prove-bites control showing an
      unpartitioned (season-only) write DOES collide — the hazard the raw re-key removes.
  C — **Registry / resolver smoke.** leagues.parquet resolves the is_mine (league_id, scoring_key), and
      the resolver returns it registry-first (no network).

Run: python3 -m application.data.transforms.backtest_l0_keying --season 2025
Migrate first (re-run the deterministic transforms to the keyed paths) so A has both sides to compare.
"""

import argparse
import shutil
import sys

import polars as pl

from application.data import data_layer
from application.shared import league_resolver

_SNAP = data_layer._SNAPSHOT_DIR

# entity -> (old flat parquet path, new keyed parquet path builder taking (lid, sk))
_LEAGUE_ENTITIES = ["player_signal", "production_vor", "market_vor",
                    "true_rank", "positional_depth", "bracket_odds", "manager_features", "manager_dossiers"]


def _check(label, ok, results, extra=""):
    results.append(ok)
    print(f"    {label:58} {'PASS' if ok else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-independent frame equality: same columns, and same rows sorted by all columns."""
    if set(a.columns) != set(b.columns):
        return False
    cols = a.columns
    return a.sort(cols).equals(b.select(cols).sort(cols))


def _migration_pairs(season: int, lid: str, sk: str):
    """(name, old_flat_path, new_keyed_path) for every re-keyed entity."""
    d = _SNAP / "derived"
    pairs = [(n, d / f"{n}_{season}.parquet", d / "league" / lid / f"{n}_{season}.parquet")
             for n in _LEAGUE_ENTITIES]
    pairs.append(("projection_consensus", d / f"projection_consensus_{season}.parquet",
                  d / "scoring" / sk / f"projection_consensus_{season}.parquet"))
    pairs.append(("manager_activity",
                  _SNAP / "sleeper" / str(season) / f"manager_activity_{season}.parquet",
                  _SNAP / "sleeper" / str(season) / "league" / lid / f"manager_activity_{season}.parquet"))
    return pairs


def _check_migration(season: int, lid: str, sk: str, results: list) -> None:
    print("  A — migration identity (old flat parquet == new keyed parquet, is_mine league):")
    any_compared = False
    for name, old, new in _migration_pairs(season, lid, sk):
        if not old.exists():
            print(f"    {name:58} SKIP  (flat absent — migrated or never built)")
            continue
        if not new.exists():
            _check(f"{name} keyed file present", False, results, "migration not run — keyed file missing")
            continue
        any_compared = True
        a, b = pl.read_parquet(old), pl.read_parquet(new)
        _check(f"{name} frame-equal (rows {a.height})", _frame_eq(a, b), results)
    if not any_compared:
        print("    (no flat files present — migration-identity check had nothing to compare)")


def _check_ros_split(season: int, lid: str, sk: str, results: list) -> None:
    """The old ros_outcome_shape must equal ros_player_band ⋈ ros_league_view — the split loses nothing."""
    print("  A2 — ROS split reconstruction (old ros_outcome_shape == band ⋈ league_view):")
    old = _SNAP / "derived" / f"ros_outcome_shape_{season}.parquet"
    band_p = _SNAP / "derived" / "scoring" / sk / f"ros_player_band_{season}.parquet"
    view_p = _SNAP / "derived" / "league" / lid / f"ros_league_view_{season}.parquet"
    if not old.exists():
        print("    ros_outcome_shape flat absent — reconstruction had nothing to compare")
        return
    if not (band_p.exists() and view_p.exists()):
        _check("ros band + league_view present", False, results,
               "run compute_ros_player_band + compute_ros_league_view")
        return
    recon = pl.read_parquet(view_p).join(
        pl.read_parquet(band_p), on=["season", "as_of_week", "sleeper_player_id", "position"], how="left")
    _check(f"ros_outcome_shape reconstructed (rows {recon.height})",
           _frame_eq(pl.read_parquet(old), recon), results)


def _check_collision(season: int, results: list) -> None:
    print("  B — collision isolation (two leagues cannot overwrite each other):")
    a_id, b_id = "__L0TEST_A__", "__L0TEST_B__"
    fa = pl.DataFrame({"as_of_week": [4], "roster_id": [1], "sleeper_player_id": ["A"], "vor": [1.0]})
    fb = pl.DataFrame({"as_of_week": [4], "roster_id": [1], "sleeper_player_id": ["B"], "vor": [2.0]})
    try:
        data_layer.write_production_vor(fa, season, league_id=a_id)
        data_layer.write_production_vor(fb, season, league_id=b_id)  # must NOT touch A
        ra = data_layer.read_production_vor(season, league_id=a_id, as_of_week="all")
        rb = data_layer.read_production_vor(season, league_id=b_id, as_of_week="all")
        pa = data_layer._production_vor_path(season, a_id)
        pb = data_layer._production_vor_path(season, b_id)
        _check("distinct paths per league_id", pa != pb, results)
        _check("league A reads back its own rows (unclobbered)", ra.equals(fa), results,
               f"got {ra['sleeper_player_id'].to_list()}")
        _check("league B reads back its own rows", rb.equals(fb), results)
    finally:
        for lid in (a_id, b_id):
            shutil.rmtree(data_layer._league_dir(lid), ignore_errors=True)


def _check_collision_raw(season: int, results: list) -> None:
    """Raw-layer twin of B (Session 3a): two leagues' matchups in one season cannot overwrite each other,
    now that the raw/join layer is league-keyed. Includes a prove-bites negative control — a season-only
    (unpartitioned) write DOES collide, which is exactly the hazard league_id keying removes."""
    print("  B2 — raw-layer collision isolation (two leagues' matchups cannot overwrite each other):")
    a_id, b_id = "__L0RAWTEST_A__", "__L0RAWTEST_B__"
    wk = 1
    fa = pl.DataFrame({"roster_id": [1], "matchup_id": [1], "points": [10.0],
                       "players_points": ["{}"], "starters": ["[]"]})
    fb = pl.DataFrame({"roster_id": [1], "matchup_id": [1], "points": [20.0],
                       "players_points": ["{}"], "starters": ["[]"]})
    try:
        data_layer.write_sleeper_matchups(fa, season, wk, league_id=a_id)
        data_layer.write_sleeper_matchups(fb, season, wk, league_id=b_id)  # must NOT touch A
        ra = data_layer.read_sleeper_matchups(season, wk, league_id=a_id)
        rb = data_layer.read_sleeper_matchups(season, wk, league_id=b_id)
        pa = data_layer._sleeper_matchups_path(season, wk, a_id)
        pb = data_layer._sleeper_matchups_path(season, wk, b_id)
        _check("distinct paths per league_id (raw matchups)", pa != pb, results)
        _check("league A matchups read back unclobbered", ra.equals(fa), results,
               f"got points={ra['points'].to_list()}")
        _check("league B matchups read back its own rows", rb.equals(fb), results)
        # prove-bites: writing BOTH leagues to one shared (season-only) path collides — B clobbers A.
        shared = _SNAP / "sleeper" / str(season) / "__l0rawtest_shared__.parquet"
        shared.parent.mkdir(parents=True, exist_ok=True)
        fa.write_parquet(shared)
        fb.write_parquet(shared)
        collided = not pl.read_parquet(shared).equals(fa)
        _check("PROVE-BITES: an unpartitioned (season-keyed) write collides", collided, results,
               "league B clobbered A at a shared path — the collision league_id keying prevents")
        shared.unlink(missing_ok=True)
    finally:
        for lid in (a_id, b_id):
            shutil.rmtree(data_layer._sleeper_league_dir(season, lid), ignore_errors=True)


def _check_registry(season: int, results: list) -> None:
    print("  C — registry / resolver smoke:")
    if not data_layer.leagues_exists():
        _check("leagues.parquet exists", False, results,
               "run `python3 -m application.shared.league_registry build`")
        return
    lid, sk = data_layer._active_league(season)
    _check("_active_league returns (league_id, scoring_key)", bool(lid) and bool(sk), results, f"({lid}, {sk})")
    _check("resolver.resolve_active == _active_league", league_resolver.resolve_active(season) == (lid, sk), results)
    _check("resolver.resolve_league_id is registry-first (no network)",
           league_resolver.resolve_league_id(season) == lid, results)


def run(season: int) -> bool:
    results: list = []
    print(f"=== L0 keying gate: season={season} ===")
    if data_layer.leagues_exists():
        lid, sk = data_layer._active_league(season)
        _check_migration(season, lid, sk, results)
        _check_ros_split(season, lid, sk, results)
    else:
        print("  A — migration identity: SKIP (no registry; build it, then re-run after migration)")
    _check_collision(season, results)
    _check_collision_raw(season, results)
    _check_registry(season, results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the keyed layout reproduces mine frame-for-frame "
          f"and isolates leagues.")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gate for the L0 keying migration.")
    parser.add_argument("--season", type=int, default=2025)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)
