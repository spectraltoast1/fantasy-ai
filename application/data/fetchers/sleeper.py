"""
Sleeper fetcher — league matchups, transactions, rosters, and bracket snapshots.

Public API:
    backfill(league_id, year)  — fetch all completed regular-season weeks, write parquet snapshots
    refresh(league_id)         — fetch current league state to cache and this week's data to snapshots
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

_HERE = Path(__file__).resolve().parent        # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                       # .../application/data/
CACHE_DIR = _DATA_DIR / "cache" / "sleeper"    # raw JSON current-state dumps (see _write_json)

# data_layer.py lives one level up in application/data/ — all parquet snapshot/cache I/O
# goes through it (the fetcher constructs no parquet paths). The raw JSON dumps written by
# _write_json stay put: they're current-state API captures, not data-layer entities.
sys.path.insert(0, str(_DATA_DIR))
import data_layer

_SLEEPER_BASE = "https://api.sleeper.app/v1"
# Projections/stats live on a separate host (no /v1), distinct from the main league API.
_SLEEPER_STATS_BASE = "https://api.sleeper.com"

_PLAYERS_CACHE_MAX_AGE_SECONDS = 86_400  # 24 hours

# Columns to keep from the /players/nfl response — the full payload has 100+ fields.
_PLAYERS_KEEP_COLS = ["sleeper_player_id", "full_name", "position", "team", "status"]

# V1 is skill positions only; the projections endpoint also returns FB/CB noise.
SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}

# Pinned schema for the projections write so the growing season file stays type-stable
# across weeks/sources (mirrors leaguelogs.py's _SCHEMA). This is the normalized,
# source-agnostic contract data_layer.write_projections persists — see its docstring.
_PROJECTIONS_SCHEMA = {
    "season": pl.Int64,
    "week": pl.Int64,
    "source": pl.Utf8,          # the provider we pull from ("sleeper")
    "company": pl.Utf8,         # the underlying projection house Sleeper serves (e.g. "rotowire")
    "sleeper_player_id": pl.Utf8,
    "position": pl.Utf8,
    "proj_pts_ppr": pl.Float64,
    "proj_pts_half": pl.Float64,
    "proj_pts_std": pl.Float64,
    "proj_pass_yd": pl.Float64,
    "proj_pass_td": pl.Float64,
    "proj_rush_yd": pl.Float64,
    "proj_rush_td": pl.Float64,
    "proj_rec": pl.Float64,
    "proj_rec_yd": pl.Float64,
    "proj_rec_td": pl.Float64,
    "snapshot_date": pl.Date,       # when WE captured it (append/history axis)
    "source_updated_at": pl.Utf8,   # when the source last revised the projection
    "fetched_at": pl.Utf8,
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_nfl_state() -> dict:
    resp = requests.get(f"{_SLEEPER_BASE}/state/nfl")
    resp.raise_for_status()
    return resp.json()


def _determine_completed_weeks(state: dict, year: int) -> int:
    """Return the number of completed regular-season weeks for the given year.

    Accounts for the offseason window where season_type is "offseason" but the
    season counter has not yet incremented — in that state the season is complete.
    """
    current_season = int(state["season"])

    if year < current_season:
        return 18                              # past season, fully complete

    if year > current_season:
        return 0                               # future season

    # year == current_season
    season_type = state.get("season_type", "")
    if season_type == "pre":
        return 0                               # season hasn't started yet
    if season_type == "regular":
        leg = int(state.get("leg", 0))
        return min(max(leg - 1, 0), 18)        # subtract 1: current week may be in progress
    # "post", "offseason", or anything else: regular season is complete
    return 18


def _write_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    print(f"  Wrote {path.name} → {path}")


def _rows_to_df(data: list):
    """Normalise a Sleeper list-payload into a DataFrame — nested dict/list values are
    JSON-serialised so every column is a scalar. Returns None for an empty response
    (offseason or a week not yet played), which the caller treats as "skip the write"."""
    if not data:
        return None
    normalized = [
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        for row in data
    ]
    return pl.from_dicts(normalized)


def _snapshot_list(data: list, writer, year: int, week: int, label: str) -> bool:
    """Persist one week's Sleeper list-payload via a data_layer writer, skipping (with a
    log line) when the response is empty. The fetcher keeps the shaping + skip concern;
    the file I/O lives behind data_layer (write_sleeper_matchups / write_sleeper_transactions)."""
    df = _rows_to_df(data)
    if df is None:
        print(f"  {label}: empty response from Sleeper (offseason or week not yet played) — skipping write.")
        return False
    writer(df, year, week)
    print(f"  {label}: {len(df)} rows → snapshots/sleeper/{year}/")
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_players(force: bool = False) -> None:
    """Cache the Sleeper /players/nfl endpoint to players.parquet.

    Skips the network call if the cache file is less than 24 hours old,
    unless force=True. The full response is ~5 MB with 100+ fields per player;
    we normalise it down to the columns needed for position resolution plus the
    injury/depth-chart fields the Trust axis's "security" read needs
    (DECISION_READS.md §1) — this endpoint already carries them, so surfacing
    security requires no new dependency.

    Position values in this endpoint use Sleeper's internal codes:
      skill positions: QB, RB, WR, TE
      kickers:         K
      defense/ST:      DEF  (not team abbreviations like in matchup data)
    """
    if not force and data_layer.sleeper_players_exists():
        age = data_layer.sleeper_players_age_seconds()
        if age is not None and age < _PLAYERS_CACHE_MAX_AGE_SECONDS:
            print(f"  players cache is fresh ({age / 3600:.1f}h old) — skipping fetch.")
            return

    print("  Fetching /players/nfl from Sleeper...")
    resp = requests.get(f"{_SLEEPER_BASE}/players/nfl")
    resp.raise_for_status()
    raw: dict = resp.json()

    rows = []
    for player_id, player in raw.items():
        rows.append({
            "sleeper_player_id": str(player_id),
            "full_name": player.get("full_name") or player.get("last_name", ""),
            "position": player.get("position"),
            "team": player.get("team"),
            "status": player.get("status"),
            "injury_status": player.get("injury_status"),
            "injury_body_part": player.get("injury_body_part"),
            "depth_chart_order": player.get("depth_chart_order"),
            "depth_chart_position": player.get("depth_chart_position"),
            "practice_participation": player.get("practice_participation"),
        })

    # infer_schema_length=None: most players have null injury/practice fields, so a
    # partial-row schema scan can pin the wrong dtype for a column that's all-null in
    # the sampled prefix but stringy further down — scan every row instead.
    data_layer.write_sleeper_players(pl.DataFrame(rows, infer_schema_length=None))
    print(f"  players: {len(rows)} players → cache/sleeper/players.parquet")


def fetch_teams(league_id: str, year: int) -> None:
    """Fetch league users + rosters and write a roster_id → names map for the season.

    Produces teams_{year}.parquet (roster_id, team_name, owner_name) via data_layer.
    `team_name` is the manager's custom team name (users[].metadata.team_name); it is
    null when a manager never set one — the consumer falls back to `owner_name`
    (their Sleeper display_name).
    """
    print(f"Fetching Sleeper teams for league {league_id} ({year})...")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/users")
    resp.raise_for_status()
    users = resp.json()

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/rosters")
    resp.raise_for_status()
    rosters = resp.json()

    # user_id → (display_name, custom team name)
    users_by_id = {
        u["user_id"]: (
            u.get("display_name"),
            (u.get("metadata") or {}).get("team_name"),
        )
        for u in users
    }

    rows = []
    for r in rosters:
        display_name, team_name = users_by_id.get(r.get("owner_id"), (None, None))
        rows.append({
            "roster_id": int(r["roster_id"]),
            "team_name": team_name,
            "owner_name": display_name,
        })

    df = pl.from_dicts(rows)
    data_layer.write_sleeper_teams(df, year)
    print(f"  teams: {len(df)} rosters → snapshots/sleeper/{year}/teams_{year}.parquet")


def fetch_roster_positions(league_id: str, year: int) -> None:
    """Fetch the league object and write its raw roster_positions slot list.

    Produces roster_positions_{year}.parquet (slot_index, slot) via data_layer —
    the league's declared starting-lineup configuration straight from Sleeper, e.g.
    ['QB','RB','RB','WR','WR','TE','FLEX','FLEX','BN','BN',...]. Bench/IR/taxi slots
    are kept here as the faithful source of truth; transforms/derive_lineup_slots.py
    filters to the starting skill slots the optimal-lineup calc needs.
    """
    print(f"Fetching Sleeper roster_positions for league {league_id} ({year})...")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}")
    resp.raise_for_status()
    league = resp.json()

    slots = league.get("roster_positions") or []
    if not slots:
        print("  No roster_positions on the league object — nothing to write.")
        return

    df = pl.DataFrame(
        {"slot_index": list(range(len(slots))), "slot": [str(s) for s in slots]}
    )
    data_layer.write_roster_positions(df, year)
    print(f"  roster_positions: {len(df)} slots → snapshots/sleeper/{year}/roster_positions_{year}.parquet")
    print(f"  slots: {slots}")


def fetch_league_config(league_id: str, year: int) -> None:
    """Fetch the league object and persist its scoring_settings + playoff/league settings.

    Produces league_settings_{year}.parquet (section, key, value) via data_layer — the league's
    real scoring rules (so the scoring dispatcher picks the right projection column instead of
    assuming PPR) and playoff config (playoff_teams / playoff_week_start, so the bracket sim reads
    them instead of hardcoding). Same /league object fetch_roster_positions uses; the interesting
    keys were previously discarded.
    """
    print(f"Fetching Sleeper league config for league {league_id} ({year})...")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}")
    resp.raise_for_status()
    league = resp.json()

    scoring = league.get("scoring_settings") or {}
    settings = league.get("settings") or {}
    # Only the playoff/postseason keys the sim needs; the full settings blob has dozens of
    # unrelated knobs (waiver_type, trade_deadline, …) — keep the persisted set intentional.
    playoff_keys = ("playoff_teams", "playoff_week_start", "playoff_type",
                    "playoff_round_type", "playoff_seed_type", "num_teams")

    rows = []
    for key, value in scoring.items():
        rows.append({"section": "scoring", "key": str(key), "value": float(value)})
    for key in playoff_keys:
        if key in settings and settings[key] is not None:
            rows.append({"section": "league", "key": key, "value": float(settings[key])})

    if not rows:
        print("  No scoring_settings/settings on the league object — nothing to write.")
        return

    df = pl.DataFrame(rows, schema={"section": pl.Utf8, "key": pl.Utf8, "value": pl.Float64})
    data_layer.write_league_settings(df, year)
    print(f"  league_settings: {df.height} keys ({len(scoring)} scoring) → "
          f"snapshots/sleeper/{year}/league_settings_{year}.parquet")
    _lg = {r["key"]: r["value"] for r in df.filter(pl.col("section") == "league").iter_rows(named=True)}
    print(f"  playoff config: {_lg}")


def _ms_to_iso(ms) -> str | None:
    """Convert a Sleeper epoch-milliseconds timestamp to an ISO-8601 UTC string."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _projection_rows(payload: list, season: int, week: int, snapshot_date, fetched_at: str) -> list[dict]:
    """Normalise the Sleeper projections payload into the source-agnostic schema.

    One row per skill-position player (FB/CB and other non-skill rows dropped). `season`
    and `week` come from the caller (authoritative) rather than the row so the write's
    dedup key is exact. Player id is kept as a string — never cast to int (it's the
    sleeperPlayerId join key). Points (pts_ppr/half/std) are already computed by the
    source; component stats are carried as legible evidence and default to null when a
    position doesn't produce them (a QB has no rec_yd).
    """
    rows = []
    for r in payload:
        player = r.get("player") or {}
        position = player.get("position")
        if position not in SKILL_POSITIONS:
            continue
        stats = r.get("stats") or {}
        rows.append({
            "season": season,
            "week": week,
            "source": "sleeper",
            "company": r.get("company"),
            "sleeper_player_id": str(r["player_id"]),
            "position": position,
            "proj_pts_ppr": stats.get("pts_ppr"),
            "proj_pts_half": stats.get("pts_half_ppr"),
            "proj_pts_std": stats.get("pts_std"),
            "proj_pass_yd": stats.get("pass_yd"),
            "proj_pass_td": stats.get("pass_td"),
            "proj_rush_yd": stats.get("rush_yd"),
            "proj_rush_td": stats.get("rush_td"),
            "proj_rec": stats.get("rec"),
            "proj_rec_yd": stats.get("rec_yd"),
            "proj_rec_td": stats.get("rec_td"),
            "snapshot_date": snapshot_date,
            "source_updated_at": _ms_to_iso(r.get("updated_at") or r.get("last_modified")),
            "fetched_at": fetched_at,
        })
    return rows


def fetch_projections(season: int, week: int) -> bool:
    """Fetch one week of Sleeper (RotoWire) projections and append via data_layer.

    League-agnostic — this is the whole NFL skill-position pool's forward prior, not a
    league entity, so it takes no league_id. Written with source="sleeper" to the shared
    multi-source projections file; a re-run of the same (season, week) replaces its
    sleeper slice (dedup guard in write_projections). Returns False (skips the write) on
    an empty response.
    """
    now = datetime.now(timezone.utc)
    resp = requests.get(
        f"{_SLEEPER_STATS_BASE}/projections/nfl/{season}/{week}",
        params={
            "season_type": "regular",
            "position[]": ["QB", "RB", "WR", "TE"],
            "order_by": "pts_ppr",
        },
    )
    resp.raise_for_status()
    rows = _projection_rows(
        resp.json(), season, week, now.date(), now.isoformat(timespec="seconds")
    )
    if not rows:
        print(f"  projections {season} week {week}: empty response — skipping write.")
        return False
    df = pl.DataFrame(rows, schema_overrides=_PROJECTIONS_SCHEMA)
    data_layer.write_projections(df, season, week, source="sleeper")
    print(f"  projections {season} week {week}: {len(df)} skill players "
          f"→ snapshots/projections/projections_{season}.parquet")
    return True


def fetch_projections_season(season: int, through_week: int = 18) -> None:
    """Backfill every regular-season week's Sleeper projections for a season."""
    print(f"Backfilling Sleeper projections for {season} (weeks 1–{through_week})...")
    for week in range(1, through_week + 1):
        fetch_projections(season, week)
        time.sleep(0.3)  # be polite; Sleeper's limit is generous
    print(f"Projections backfill complete for {season}.")


def backfill(league_id: str, year: int) -> None:
    """Fetch all completed regular-season weeks and write parquet snapshots."""
    print(f"Backfilling Sleeper data for league {league_id} ({year})...")

    state = _get_nfl_state()
    completed_weeks = _determine_completed_weeks(state, year)
    print(f"  Completed weeks: {completed_weeks}")

    if completed_weeks == 0:
        print(f"  No completed weeks found for {year}. Nothing to backfill.")
        return

    for week in range(1, completed_weeks + 1):
        print(f"  Week {week}/{completed_weeks}...")

        resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}")
        resp.raise_for_status()
        _snapshot_list(resp.json(), data_layer.write_sleeper_matchups, year, week, f"matchups week {week}")

        resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}")
        resp.raise_for_status()
        _snapshot_list(resp.json(), data_layer.write_sleeper_transactions, year, week, f"transactions week {week}")

        time.sleep(0.5)

    print(f"Backfill complete for league {league_id} ({year}).")


def refresh(league_id: str) -> None:
    """Fetch current league state to cache and this week's data to snapshots."""
    print(f"Refreshing Sleeper data for league {league_id}...")

    state = _get_nfl_state()
    year = state["season"]
    week = int(state.get("leg", 0))
    print(f"  Current season: {year}, current week: {week}")

    # Cache files — current state only, overwritten each run
    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "league.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/users")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "users.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/rosters")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "rosters.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/winners_bracket")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "winners_bracket.json")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/losers_bracket")
    resp.raise_for_status()
    _write_json(resp.json(), CACHE_DIR / "losers_bracket.json")

    # Players registry — refreshed at most once per 24 hours.
    fetch_players()

    # Current week snapshots — same entities as backfill
    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}")
    resp.raise_for_status()
    _snapshot_list(resp.json(), data_layer.write_sleeper_matchups, year, week, f"matchups week {week}")

    resp = requests.get(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}")
    resp.raise_for_status()
    _snapshot_list(resp.json(), data_layer.write_sleeper_transactions, year, week, f"transactions week {week}")

    print(f"Refresh complete for league {league_id}.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    usage = (
        "Usage: sleeper.py backfill <year> | sleeper.py refresh | "
        "sleeper.py fetch-players | sleeper.py fetch-teams <year> | "
        "sleeper.py fetch-roster-positions <year> | "
        "sleeper.py fetch-league-config <year> | "
        "sleeper.py projections <season> [week]"
    )

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]

    # projections are league-agnostic (the whole NFL pool's forward prior) — handled
    # before the league_resolver import so they need no league config to run.
    if cmd == "projections":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _season = int(sys.argv[2])
        if len(sys.argv) >= 4:
            fetch_projections(_season, int(sys.argv[3]))
        else:
            fetch_projections_season(_season)
        sys.exit(0)

    # league_resolver lives in application/shared/ — insert application/ into sys.path
    sys.path.insert(0, str(_HERE.parent.parent))
    from shared import league_resolver

    if cmd == "backfill":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _year = int(sys.argv[2])
        _league_id = league_resolver.resolve_league_id(_year)
        backfill(_league_id, _year)

    elif cmd == "refresh":
        _state = _get_nfl_state()
        _year = int(_state["season"])
        _league_id = league_resolver.resolve_league_id(_year)
        refresh(_league_id)

    elif cmd == "fetch-teams":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _year = int(sys.argv[2])
        _league_id = league_resolver.resolve_league_id(_year)
        fetch_teams(_league_id, _year)

    elif cmd == "fetch-roster-positions":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _year = int(sys.argv[2])
        _league_id = league_resolver.resolve_league_id(_year)
        fetch_roster_positions(_league_id, _year)

    elif cmd == "fetch-league-config":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        _year = int(sys.argv[2])
        _league_id = league_resolver.resolve_league_id(_year)
        fetch_league_config(_league_id, _year)

    elif cmd == "fetch-players":
        fetch_players(force=True)

    else:
        print(usage)
        sys.exit(1)
