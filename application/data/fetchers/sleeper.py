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

_HERE = Path(__file__).resolve().parent        # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                       # .../application/data/
CACHE_DIR = _DATA_DIR / "cache" / "sleeper"    # raw JSON current-state dumps (see _write_json)

# data_layer.py lives one level up in application/data/ — all parquet snapshot/cache I/O
# goes through it (the fetcher constructs no parquet paths). The raw JSON dumps written by
# _write_json stay put: they're current-state API captures, not data-layer entities.
from application.data import data_layer
from application.data.fetchers import _http

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

# Pinned schema for the cross-league manager-activity write (DECISION_READS.md §7).
# Two row kinds share the file: "league" markers (one per searched comparable league) and
# "txn" rows (one per that manager's transaction) — the txn-only columns are null on league
# rows. Keeping the schema explicit stops a manager whose first league has no transactions
# from pinning a column all-null and then failing the diagonal concat on the next manager.
_MANAGER_ACTIVITY_SCHEMA = {
    "season": pl.Int64,              # the target run season (partition)
    "owner_id": pl.Utf8,            # the manager (Sleeper user_id) — the identity key
    "owner_name": pl.Utf8,
    "kind": pl.Utf8,               # "league" | "txn"
    "source_league_id": pl.Utf8,   # the comparable league this row came from (a COLUMN)
    "source_league_name": pl.Utf8,
    "source_season": pl.Int64,
    "scoring_profile": pl.Utf8,    # source-league classification (the comparability axes)
    "num_teams": pl.Int64,
    "qb_structure": pl.Utf8,
    "league_format": pl.Utf8,
    "faab_budget": pl.Float64,     # league FAAB budget (for bid-as-fraction-of-budget)
    "roster_id_in_source": pl.Int64,
    "transaction_id": pl.Utf8,     # txn rows only (null on league markers) below
    "txn_type": pl.Utf8,           # waiver | free_agent | trade
    "status": pl.Utf8,             # complete | failed
    "week": pl.Int64,
    "faab_bid": pl.Float64,        # waiver bid (settings.waiver_bid); null for FA/trade
    "adds_json": pl.Utf8,          # this manager's added player_ids (JSON list)
    "drops_json": pl.Utf8,         # this manager's dropped player_ids (JSON list)
    "fetched_at": pl.Utf8,
}


# ---------------------------------------------------------------------------
# Shared HTTP (timeout + retry/backoff + throttle)
# ---------------------------------------------------------------------------
# Sleeper has no documented hard rate limit but asks for < ~1000 calls/min. The
# once-a-season manager-activity fan-out (~10 managers x <=5 leagues x ~17 weeks)
# issues hundreds of calls, so every request routes through the shared _http layer:
# a bounded timeout, exponential-backoff retry on transient failures (timeouts /
# connection resets / 5xx), and the process throttle the fan-out raises to space calls.
# The retry/backoff/throttle logic lives ONCE in _http; `set_throttle` is re-exported so
# the fan-out (fetch_manager_activity) keeps calling sleeper.set_throttle unchanged.
_HTTP_TIMEOUT = 15.0     # seconds per request
_HTTP_RETRIES = 4        # total attempts before giving up
_HTTP_BACKOFF = 0.5      # base backoff seconds (exponential + jitter)

set_throttle = _http.set_throttle   # re-export: min gap between calls (the fan-out raises it)


def _get_json(url: str, params=None, *, timeout: float = _HTTP_TIMEOUT,
              retries: int = _HTTP_RETRIES, backoff: float = _HTTP_BACKOFF):
    """GET `url` and return parsed JSON via the shared _http resilience layer.

    Bounded timeout + transient retry/backoff + process throttle; a 4xx raises immediately
    (not retried). Sleeper returns null (not a 4xx) for "no leagues", which callers handle
    with `or []` / `or {}`, so this only ever raises on a genuine error.
    """
    return _http.get_json(url, params=params, timeout=timeout, retries=retries, backoff=backoff)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_nfl_state() -> dict:
    return _get_json(f"{_SLEEPER_BASE}/state/nfl")


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
    raw: dict = _get_json(f"{_SLEEPER_BASE}/players/nfl")

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

    Produces teams_{year}.parquet (roster_id, team_name, owner_name, owner_id) via
    data_layer. `team_name` is the manager's custom team name (users[].metadata.team_name);
    it is null when a manager never set one — the consumer falls back to `owner_name`
    (their Sleeper display_name). `owner_id` is the Sleeper user_id — the identity join
    key the cross-league manager dossiers (DECISION_READS.md §7) key on; previously
    dropped, it's read here transiently for the name lookup already.
    """
    print(f"Fetching Sleeper teams for league {league_id} ({year})...")

    users = _get_json(f"{_SLEEPER_BASE}/league/{league_id}/users")
    rosters = _get_json(f"{_SLEEPER_BASE}/league/{league_id}/rosters")

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
            "owner_id": r.get("owner_id"),
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

    league = _get_json(f"{_SLEEPER_BASE}/league/{league_id}")

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

    league = _get_json(f"{_SLEEPER_BASE}/league/{league_id}")

    scoring = league.get("scoring_settings") or {}
    settings = league.get("settings") or {}
    # Only the playoff/postseason keys the sim needs; the full settings blob has dozens of
    # unrelated knobs (waiver_type, trade_deadline, …) — keep the persisted set intentional.
    # `divisions` is the division count — the bracket sim seeds division winners ahead of
    # wildcards when it's ≥ 2 (the per-roster division assignment lives on the rosters endpoint;
    # persisting that map onto the teams entity is a follow-up when a real division league lands).
    playoff_keys = ("playoff_teams", "playoff_week_start", "playoff_type",
                    "playoff_round_type", "playoff_seed_type", "num_teams", "divisions")

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
    payload = _get_json(
        f"{_SLEEPER_STATS_BASE}/projections/nfl/{season}/{week}",
        params={
            "season_type": "regular",
            "position[]": ["QB", "RB", "WR", "TE"],
            "order_by": "pts_ppr",
        },
    )
    rows = _projection_rows(
        payload, season, week, now.date(), now.isoformat(timespec="seconds")
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


def _roster_for_owner(rosters: list, owner_id: str):
    """The manager's roster_id in a source league (primary owner, then co-owner)."""
    for r in rosters:
        if r.get("owner_id") == owner_id:
            return r.get("roster_id")
    for r in rosters:
        if owner_id in (r.get("co_owners") or []):
            return r.get("roster_id")
    return None


def _manager_leagues(owner_id: str, season: int, seasons_back: int = 2) -> list:
    """Every league a manager played across {season, season-1, ... season-seasons_back}.

    Each entry is the raw league object from /user/{id}/leagues/nfl/{S} (which carries
    scoring_settings + roster_positions + settings — verified), tagged with its season.
    """
    out = []
    for s in range(season, season - seasons_back - 1, -1):
        leagues = _get_json(f"{_SLEEPER_BASE}/user/{owner_id}/leagues/nfl/{s}") or []
        for lg in leagues:
            out.append((s, lg))
    return out


def fetch_manager_activity(league_id: str, season: int, *, only_username: str | None = None,
                           limit: int | None = None, throttle: float = 0.2) -> None:
    """Acquire each target-league manager's behaviour across their *comparable* other leagues.

    The cross-league acquisition half of Manager Dossiers (DECISION_READS.md §7, Phase A).
    For every manager in the target league: find the comparable leagues they play in (same
    scoring profile + size + QB structure + format) across the current + 2 prior seasons,
    select up to 5 (biased toward the prior season), and pull their transactions from each.
    Persists the tall cross-league `manager_activity_{season}` entity INCREMENTALLY per
    manager (recoverable + idempotent). Live public Sleeper data; run at most once/season.

    only_username / limit are dev knobs to validate the pipeline on a subset before the full
    ~10-manager fan-out. throttle spaces every HTTP call (hundreds per full run).
    """
    _manager = _import_manager_helpers()
    set_throttle(throttle)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    target_league = _get_json(f"{_SLEEPER_BASE}/league/{league_id}")
    target = _manager.classify_league(target_league)
    print(f"Manager activity for {season} — target league '{target_league.get('name')}': "
          f"{target['scoring_profile']} / {target['num_teams']}-team / {target['qb_structure']} / "
          f"{target['league_format']}")

    users = _get_json(f"{_SLEEPER_BASE}/league/{league_id}/users")
    rosters = _get_json(f"{_SLEEPER_BASE}/league/{league_id}/rosters")
    name_by_id = {u["user_id"]: u.get("display_name") for u in users}

    managers = [(r.get("owner_id"), r.get("roster_id")) for r in rosters if r.get("owner_id")]
    managers.sort(key=lambda m: m[1])  # deterministic order (roster_id)

    if only_username:
        me = _get_json(f"{_SLEEPER_BASE}/user/{only_username}")["user_id"]
        managers = [m for m in managers if m[0] == me]
        print(f"  [dev] restricted to {only_username} (user_id {me})")
    if limit is not None:
        managers = managers[:limit]
        print(f"  [dev] limited to first {limit} manager(s)")

    for owner_id, target_roster_id in managers:
        owner_name = name_by_id.get(owner_id)
        candidates = []
        for src_season, lg in _manager_leagues(owner_id, season):
            cls = _manager.classify_league(lg)
            cls["source_season"] = src_season
            cls["_raw_name"] = lg.get("name")
            if _manager.is_comparable(target, cls):
                candidates.append(cls)
        selected = _manager.select_comparables(
            candidates, target_league_id=league_id, current_season=season
        )

        rows: list[dict] = []
        for c in selected:
            src_id, src_season = c["league_id"], c["source_season"]
            src_rosters = _get_json(f"{_SLEEPER_BASE}/league/{src_id}/rosters")
            rid = _roster_for_owner(src_rosters, owner_id)
            base = {
                "season": season, "owner_id": owner_id, "owner_name": owner_name,
                "source_league_id": src_id, "source_league_name": c.get("_raw_name"),
                "source_season": src_season, "scoring_profile": c["scoring_profile"],
                "num_teams": c["num_teams"], "qb_structure": c["qb_structure"],
                "league_format": c["league_format"],
                "faab_budget": (float(c["waiver_budget"]) if c.get("waiver_budget") is not None else None),
                "roster_id_in_source": rid, "fetched_at": fetched_at,
            }
            # league marker row — keeps a searched-but-inactive league in the depth count
            rows.append({**base, "kind": "league", "transaction_id": None, "txn_type": None,
                         "status": None, "week": None, "faab_bid": None,
                         "adds_json": None, "drops_json": None})
            if rid is None:
                print(f"    ! {owner_name}: could not resolve roster in {c.get('_raw_name')} "
                      f"({src_id}) — league counted, transactions skipped")
                continue
            for wk in range(1, 19):
                for t in (_get_json(f"{_SLEEPER_BASE}/league/{src_id}/transactions/{wk}") or []):
                    if not _manager.manager_in_transaction(t, rid):
                        continue
                    adds = _manager.manager_moves(t.get("adds"), rid)
                    drops = _manager.manager_moves(t.get("drops"), rid)
                    bid = (t.get("settings") or {}).get("waiver_bid") if t.get("type") == "waiver" else None
                    rows.append({**base, "kind": "txn",
                                 "transaction_id": t.get("transaction_id"),
                                 "txn_type": t.get("type"), "status": t.get("status"),
                                 "week": wk,
                                 "faab_bid": (float(bid) if bid is not None else None),
                                 "adds_json": json.dumps(adds), "drops_json": json.dumps(drops)})

        df = pl.DataFrame(rows, schema=_MANAGER_ACTIVITY_SCHEMA)
        data_layer.write_manager_activity(df, season, owner_id, league_id=league_id)
        n_txn = df.filter(pl.col("kind") == "txn").height
        print(f"  {owner_name or owner_id}: {len(selected)} comparable league(s), "
              f"{n_txn} transaction(s) → manager_activity_{season}.parquet")

    print(f"Manager activity acquisition complete for {season}.")


def _import_manager_helpers():
    """Return the pure comparability helpers from the transforms package.

    The fetch mode must classify + select before it can fetch, so it reuses the same pure
    helpers compute_manager_features + the backtest use (single source of truth) rather than
    duplicating scoring_profile here. Imported inside the function to defer the transforms
    import to the one fetch mode that needs it (keeps the common sleeper.py modes lean).
    """
    from application.data.transforms import _manager
    return _manager


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

        _snapshot_list(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}"),
                       data_layer.write_sleeper_matchups, year, week, f"matchups week {week}")

        _snapshot_list(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}"),
                       data_layer.write_sleeper_transactions, year, week, f"transactions week {week}")

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
    _write_json(_get_json(f"{_SLEEPER_BASE}/league/{league_id}"), CACHE_DIR / "league.json")
    _write_json(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/users"), CACHE_DIR / "users.json")
    _write_json(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/rosters"), CACHE_DIR / "rosters.json")
    _write_json(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/winners_bracket"),
                CACHE_DIR / "winners_bracket.json")
    _write_json(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/losers_bracket"),
                CACHE_DIR / "losers_bracket.json")

    # Players registry — refreshed at most once per 24 hours.
    fetch_players()

    # Current week snapshots — same entities as backfill
    _snapshot_list(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/matchups/{week}"),
                   data_layer.write_sleeper_matchups, year, week, f"matchups week {week}")
    _snapshot_list(_get_json(f"{_SLEEPER_BASE}/league/{league_id}/transactions/{week}"),
                   data_layer.write_sleeper_transactions, year, week, f"transactions week {week}")

    print(f"Refresh complete for league {league_id}.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    usage = (
        "Usage: python3 -m application.data.fetchers.sleeper <command>  (run from repo root)\n"
        "  commands: backfill <year> | refresh | fetch-players | fetch-teams <year> | "
        "fetch-roster-positions <year> | fetch-league-config <year> | "
        "projections <season> [week] | capture-players-snapshot | "
        "fetch-manager-activity <season> [--me] [--limit N] [--throttle S]"
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

    # capture-players-snapshot pins the live registry into the active immutable snapshot (Session 1.7).
    # League-agnostic — handled before the league_resolver import; ensures players.parquet is fresh first.
    if cmd == "capture-players-snapshot":
        fetch_players()  # refresh the live cache if stale (≤24h no-op), then pin it
        path = data_layer.capture_players_snapshot()
        print(f"  pinned players snapshot {data_layer.ACTIVE_PLAYERS_SNAPSHOT!r} → {path}")
        sys.exit(0)

    # league_resolver lives in application/shared/ (imported here — only the CLI modes need it)
    from application.shared import league_resolver

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

    elif cmd == "fetch-manager-activity":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        from application import config
        _season = int(sys.argv[2])
        _flags = sys.argv[3:]
        _only = config.SLEEPER_USERNAME if "--me" in _flags else None
        _limit = int(_flags[_flags.index("--limit") + 1]) if "--limit" in _flags else None
        _throttle = float(_flags[_flags.index("--throttle") + 1]) if "--throttle" in _flags else 0.2
        _league_id = league_resolver.resolve_league_id(_season)
        fetch_manager_activity(_league_id, _season, only_username=_only,
                               limit=_limit, throttle=_throttle)

    elif cmd == "fetch-players":
        fetch_players(force=True)

    else:
        print(usage)
        sys.exit(1)
