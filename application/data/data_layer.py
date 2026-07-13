import time
from pathlib import Path

import polars as pl

_HERE = Path(__file__).resolve().parent
_SNAPSHOT_DIR = _HERE / "snapshots"
_CACHE_DIR = _HERE / "cache"


# --- Player ID Map ---

def _player_id_map_path() -> Path:
    return _CACHE_DIR / "player_id_map.parquet"


def write_player_id_map(df: pl.DataFrame) -> None:
    """Write the gsis_id → sleeperPlayerId mapping to cache (overwrite).

    Refreshed on every nflreadpy fetch run (see fetchers/nfl_stats.py).
    """
    path = _player_id_map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_player_id_map() -> pl.DataFrame:
    return pl.read_parquet(_player_id_map_path())


# --- Sleeper Players Registry ---

def _sleeper_players_path() -> Path:
    return _CACHE_DIR / "sleeper" / "players.parquet"


def write_sleeper_players(df: pl.DataFrame) -> None:
    """Cache the Sleeper /players/nfl registry (overwrite; current-state cache).

    The caller builds `df` — the fetcher normalises the endpoint down to the kept
    columns and constructs the frame with infer_schema_length=None (the mostly-null
    injury/depth-chart fields need a full scan to type correctly). This only persists it.
    """
    path = _sleeper_players_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_players() -> pl.DataFrame:
    """Read the cached Sleeper /players/nfl registry.

    Raises FileNotFoundError if fetch_players() has not been run yet.
    """
    path = _sleeper_players_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Sleeper players cache not found at {path}. "
            "Run: python3 -m application.data.fetchers.sleeper fetch-players"
        )
    return pl.read_parquet(path)


def sleeper_players_exists() -> bool:
    return _sleeper_players_path().exists()


def sleeper_players_age_seconds() -> float | None:
    """Age of the players cache in seconds, or None if it does not exist yet.

    Lets the fetcher/auditor apply their own freshness policy (the 24h cache TTL)
    without constructing a cache path themselves.
    """
    path = _sleeper_players_path()
    if not path.exists():
        return None
    return time.time() - path.stat().st_mtime


# --- Sleeper Teams (roster_id → names) ---

def _sleeper_teams_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"teams_{season}.parquet"


def write_sleeper_teams(df: pl.DataFrame, season: int) -> None:
    """Write the roster_id → team/owner name map for a season (overwrite).

    Roster identities are effectively fixed once a season is frozen, so this is a
    single overwrite file per season rather than an appended time-series.
    """
    path = _sleeper_teams_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_teams(season: int) -> pl.DataFrame:
    return pl.read_parquet(_sleeper_teams_path(season))


# --- Sleeper Roster Positions (league starting-lineup config) ---

def _roster_positions_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"roster_positions_{season}.parquet"


def write_roster_positions(df: pl.DataFrame, season: int) -> None:
    """Write the league's raw roster_positions slot list for a season (overwrite).

    One row per slot, in Sleeper's declared order (slot_index, slot). This is the
    source of truth straight from the league object — derive_lineup_slots shapes it
    into the starting skill-slot requirements the optimal-lineup calc consumes.
    Like team identities, league lineup config is fixed once a season is frozen, so
    this is a single overwrite file per season, not an appended time-series.
    """
    path = _roster_positions_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_roster_positions(season: int) -> pl.DataFrame:
    return pl.read_parquet(_roster_positions_path(season))


# --- Lineup Slots (derived starting skill-slot requirements) ---

def _lineup_slots_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"lineup_slots_{season}.parquet"


def write_lineup_slots(df: pl.DataFrame, season: int) -> None:
    """Write the derived starting skill-slot requirements for a season (overwrite).

    Output of transforms/derive_lineup_slots.py: one row per distinct starting slot
    type (slot, count, eligible) covering only slots a QB/RB/WR/TE can fill. Consumed
    by the front-end optimal-lineup ("perfect lineup") calculation.
    """
    path = _lineup_slots_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_lineup_slots(season: int) -> pl.DataFrame:
    return pl.read_parquet(_lineup_slots_path(season))


# --- League Settings (scoring_settings + playoff/league config) ---
# The league's real scoring and playoff configuration, pulled from the same Sleeper /league
# object that yields roster_positions. Persisted so transforms drive behavior from the league's
# actual rules instead of hardcoded/generic assumptions: the scoring dispatcher (transforms/
# _scoring.py) selects the projection column from scoring_settings, and compute_bracket_sim reads
# playoff_teams / playoff_week_start. Tall (section, key, value) so any scoring or league key is a
# lookup, not a schema change. Fixed once a season is frozen → single overwrite file, like
# roster_positions.


def _league_settings_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"league_settings_{season}.parquet"


def write_league_settings(df: pl.DataFrame, season: int) -> None:
    """Write the league's settings (scoring + playoff/league config) for a season (overwrite).

    Tall frame: section ∈ {"scoring", "league"}, key (the Sleeper setting name), value (float —
    scoring values and league settings are all numeric on Sleeper). Output of
    `python3 -m application.data.fetchers.sleeper fetch-league-config`.
    """
    path = _league_settings_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_league_settings(season: int) -> pl.DataFrame:
    return pl.read_parquet(_league_settings_path(season))


def read_scoring_settings(season: int) -> dict:
    """The league's scoring_settings as a {key: float} dict (the `scoring` section)."""
    df = read_league_settings(season).filter(pl.col("section") == "scoring")
    return {r["key"]: float(r["value"]) for r in df.iter_rows(named=True)}


def read_playoff_settings(season: int) -> dict:
    """The league's playoff/league config as a {key: value} dict (the `league` section)."""
    df = read_league_settings(season).filter(pl.col("section") == "league")
    return {r["key"]: r["value"] for r in df.iter_rows(named=True)}


# --- NFL Stats ---

def _nfl_stats_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "nflreadpy" / f"nfl_stats_{season}.parquet"


def write_nfl_stats(df: pl.DataFrame, season: int, week: int | None = None) -> None:
    """Write the nflreadpy player-week stats for a season.

    A full-season write (week=None) overwrites the file. A single-week refresh (week
    given) replaces just that week's rows in the existing season file — read, drop the
    week, concat (diagonal, since weeks can differ in columns), write. Mirrors
    write_join_nfl_sleeper_weekly's dedup guard.
    """
    path = _nfl_stats_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if week is not None and path.exists():
        existing = pl.read_parquet(path).filter(pl.col("week") != week)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_nfl_stats(season: int) -> pl.DataFrame:
    return pl.read_parquet(_nfl_stats_path(season))


# --- Preseason ADP (FantasyPros consensus, historical) ---
# The preseason-limits source for the §2 ROS bull/bear anchor (DECISION_READS.md §2). One tall
# file, `season` a COLUMN (the projections "source-as-a-column" idiom) so the historical
# curve-fit spans every season in one read and the current-season anchor is a filter. Fetched by
# `application/data/fetchers/adp.py backfill` from nflreadpy.load_ff_rankings — the latest August
# (pre-kickoff) redraft-overall snapshot per season, id-bridged FantasyPros→sleeper. Preseason ADP
# for a season is fixed once drafted, so a re-fetch replaces that season's slice (dedup-by-season),
# mirroring write_projections.


def _adp_preseason_path() -> Path:
    return _SNAPSHOT_DIR / "nflreadpy" / "adp_preseason.parquet"


def write_adp_preseason(df: pl.DataFrame, season: int) -> None:
    """Append one season's preseason ADP slice to the single history file (replace-by-season).

    `df` is treated as the COMPLETE set of rows for `season`. If the file exists, that season's
    rows are dropped first so a re-fetch replaces rather than duplicates; other seasons (which the
    live scrape can no longer reproduce) are preserved. One row per (season, sleeper_player_id):
    ecr / best / worst / sd (FantasyPros consensus rank + range) + pos_ecr_rank (rank of ecr within
    position at that snapshot).
    """
    path = _adp_preseason_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("season") != season)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_adp_preseason(season: int | None = None) -> pl.DataFrame:
    """Read the preseason ADP history, optionally filtered to one season (default = all seasons)."""
    df = pl.read_parquet(_adp_preseason_path())
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def adp_preseason_exists() -> bool:
    return _adp_preseason_path().exists()


# --- ADP Points Curve (historical rank -> realized-points floor/center/ceiling) ---
# The empirical anchor for the §2 ROS bull/bear range (DECISION_READS.md §2): "what does a player
# drafted at positional ADP rank r ACTUALLY produce in realized season points?" Fit by
# transforms/compute_adp_points_curve.py over prior seasons (preseason positional ADP rank ↔ realized
# season-total fantasy_points_ppr), one row per (position, pos_ecr_rank) carrying the P10/P50/P90 =
# floor/center/ceiling. Season-agnostic (pooled history), so a single overwrite file — the current
# season's anchor reads it directly. Kept in derived/ alongside the other compute_* outputs.


def _adp_points_curve_path() -> Path:
    return _SNAPSHOT_DIR / "derived" / "adp_points_curve.parquet"


def write_adp_points_curve(df: pl.DataFrame) -> None:
    """Write the pooled ADP rank→realized-points curve (overwrite; season-agnostic).

    Output of transforms/compute_adp_points_curve.py: one row per (position, pos_ecr_rank) with the
    smoothed floor_ppr / center_ppr / ceiling_ppr (P10/P50/P90 of realized full-season PPR over a
    rolling rank window across the training seasons) and the bin sample count n.
    """
    path = _adp_points_curve_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_adp_points_curve() -> pl.DataFrame:
    return pl.read_parquet(_adp_points_curve_path())


def adp_points_curve_exists() -> bool:
    return _adp_points_curve_path().exists()


# --- Sleeper Matchups ---

def _sleeper_matchups_path(season: int, week: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"matchups_week_{week:02d}.parquet"


def write_sleeper_matchups(df: pl.DataFrame, season: int, week: int) -> None:
    """Write one week's matchup snapshot for a season (overwrite)."""
    path = _sleeper_matchups_path(season, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_matchups(season: int, week: int) -> pl.DataFrame:
    return pl.read_parquet(_sleeper_matchups_path(season, week))


def read_season_matchups(season: int, through_week: int = 18) -> pl.DataFrame:
    """Stack every available weekly matchup snapshot into one (week, roster_id, matchup_id,
    points) frame — the schedule (matchup_id pairs two teams per week) + actual results, the
    seam the bracket-math sim reads for standings and the remaining schedule. Skips weeks whose
    snapshot is missing (offseason / not yet fetched)."""
    frames = []
    for week in range(1, through_week + 1):
        path = _sleeper_matchups_path(season, week)
        if not path.exists():
            continue
        frames.append(
            pl.read_parquet(path)
            .select("roster_id", "matchup_id", "points")
            .with_columns(pl.lit(week).alias("week"))
        )
    return pl.concat(frames) if frames else pl.DataFrame(
        schema={"roster_id": pl.Int64, "matchup_id": pl.Int64, "points": pl.Float64, "week": pl.Int32}
    )


# --- Sleeper Transactions ---

def _sleeper_transactions_path(season: int, week: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"transactions_week_{week:02d}.parquet"


def write_sleeper_transactions(df: pl.DataFrame, season: int, week: int) -> None:
    """Write one week's transaction snapshot for a season (overwrite)."""
    path = _sleeper_transactions_path(season, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_sleeper_transactions(season: int, week: int) -> pl.DataFrame:
    return pl.read_parquet(_sleeper_transactions_path(season, week))


# --- Join: NFL + Sleeper Weekly ---

def _join_season_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / f"season_{season}.parquet"


def read_join_season(season: int) -> pl.DataFrame:
    """Read the full season join file (all weeks)."""
    return pl.read_parquet(_join_season_path(season))


def read_join_nfl_sleeper_weekly(season: int, week: int) -> pl.DataFrame:
    """Read a single week's slice from the season join file."""
    return read_join_season(season).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    )


def write_join_nfl_sleeper_weekly(df: pl.DataFrame, season: int, week: int) -> None:
    """Append a week's rows to the single season join file.

    `df` is treated as the complete set of rows for (season, week). If the
    season file already exists, any rows matching the (season, week) combo are
    dropped first (dedup guard) so re-running a week replaces it rather than
    duplicating. Otherwise the week's rows seed a new season file.
    """
    path = _join_season_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(
            ~((pl.col("season") == season) & (pl.col("week") == week))
        )
        df = pl.concat([existing, df])
    df.write_parquet(path)


# --- Join Remainders ---

def _remainders_path(season: int, week: int) -> Path:
    return _SNAPSHOT_DIR / "nfl_sleeper_weekly_joined" / str(season) / f"remainders_{season}_w{week:02d}.parquet"


def write_join_remainders(df: pl.DataFrame, season: int, week: int) -> None:
    """Write unresolved Sleeper players to a remainders file.

    An empty DataFrame written here signals a clean join with no unknowns.
    """
    path = _remainders_path(season, week)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_join_remainders(season: int, week: int) -> pl.DataFrame:
    path = _remainders_path(season, week)
    if not path.exists():
        raise FileNotFoundError(f"Remainders file not found: {path}")
    return pl.read_parquet(path)


def remainders_exist(season: int, week: int) -> bool:
    return _remainders_path(season, week).exists()


# --- LeagueLogs Market Values ---

def _leaguelogs_market_path() -> Path:
    return _SNAPSHOT_DIR / "leaguelogs" / "market_values.parquet"


def read_leaguelogs_market() -> pl.DataFrame:
    """Read the full LeagueLogs market-value snapshot history (all dates, all profiles)."""
    return pl.read_parquet(_leaguelogs_market_path())


def leaguelogs_market_exists() -> bool:
    return _leaguelogs_market_path().exists()


def write_leaguelogs_market_snapshot(df: pl.DataFrame, snapshot_date) -> None:
    """Append one day's market snapshot (all profiles) to the single history file.

    `df` is treated as the complete set of rows for `snapshot_date`. If the file
    already exists, any rows for that date are dropped first (dedup guard), so a
    same-day re-run replaces the day rather than duplicating it. History for other
    dates is never touched — it cannot be re-fetched, so it is preserved.
    """
    path = _leaguelogs_market_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("snapshot_date") != snapshot_date)
        df = pl.concat([existing, df])
    df.write_parquet(path)


# --- Player News (news collector, DECISION_READS.md §2 aggregation half) ---
# The aggregation half of the §2 ROS AI-interpretation layer: a live, scheduled RSS
# collector (fetchers/news.py) banks current NFL player news as a de-duplicated,
# player-resolved, source-attributed time-series that the future on-demand AI synthesis
# call reads. Live-acquired like manager_activity — the forward pipeline, NOT tied to the
# frozen-2025 league; it resolves against whatever skill players are on an NFL roster now.
# One growing file (like leaguelogs market_values). Grain: one row per (news item ×
# resolved player) — a multi-player item is one row per player. Items are immutable once
# collected, so the writer is APPEND-ONLY-OF-NEW (anti-join on item_id): re-polling a feed
# (the same articles reappear every run) adds nothing, and a re-run is idempotent. Only the
# compact item is stored (headline / summary / url + provenance), never the article body —
# url + collected_at are the recall path (Wayback) and it sidesteps copyright/ToS on text.

def _player_news_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "player_news.parquet"


def write_player_news(df: pl.DataFrame) -> None:
    """Append only the genuinely-new items to the growing history file (idempotent by item_id).

    `df` is a batch of collected (item × player) rows. It is de-duplicated on `item_id`, then
    any item_id already on disk is dropped, so re-polling a feed never duplicates — the file
    grows only by new items. Existing history is never rewritten (news can't be re-fetched once
    gone). Concat is diagonal so a later schema tweak doesn't break the append.
    """
    path = _player_news_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="item_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("item_id").is_in(existing["item_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_player_news(season: int | None = None) -> pl.DataFrame:
    """Read the collected player-news history, optionally filtered to one season."""
    df = pl.read_parquet(_player_news_path())
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def player_news_exists() -> bool:
    return _player_news_path().exists()


# --- Team News Raw (per-team article collection, §2 news pipeline Stage A) ---
# The team-centric successor to player_news: the collector (fetchers/news.py) now pulls
# per-NFL-team RSS from three native sources per team (SB Nation + FanSided + the official
# team site) and banks the RAW ARTICLES (feed-provided content — not just headlines, because
# the weekly AI extraction step needs the text; feed-provided only, no scraping). Grain is one
# row per ARTICLE (team-tagged); player resolution has moved downstream to extraction/slice.
# One growing file. Immutable-once-collected, so the writer is APPEND-ONLY-OF-NEW by article_id
# (idempotent re-runs; cross-poll duplicates collapse). Superseded player_news is left in place
# as legacy. Consumed by the weekly team-dossier extraction (Stage B).


def _team_news_raw_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "team_news_raw.parquet"


def write_team_news_raw(df: pl.DataFrame) -> None:
    """Append only the genuinely-new articles to the growing store (idempotent by article_id).

    `df` is a batch of collected article rows. De-duplicated on `article_id`, then any article_id
    already on disk is dropped, so re-polling a feed never duplicates — the store grows only by new
    articles. Concat is diagonal so a later schema tweak doesn't break the append.
    """
    path = _team_news_raw_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.unique(subset="article_id", keep="first")
    if path.exists():
        existing = pl.read_parquet(path)
        df = df.filter(~pl.col("article_id").is_in(existing["article_id"]))
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_team_news_raw(team: str | None = None, season: int | None = None) -> pl.DataFrame:
    """Read the collected raw team articles, optionally filtered to one team and/or season."""
    df = pl.read_parquet(_team_news_raw_path())
    if team is not None:
        df = df.filter(pl.col("team") == team)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    return df


def team_news_raw_exists() -> bool:
    return _team_news_raw_path().exists()


def prune_team_news_raw_content(cutoff_date: str, *, dry_run: bool = False) -> dict:
    """Null the heavy `content` of raw articles older than `cutoff_date`, KEEPING the row.

    Retention for the growing raw store (§2 Stage C). The Stage-B extraction only ever reads a ~2-week
    window, so an article's `content` is dead weight once it's well past that — but the row itself is
    still worth keeping. This nulls `content` where `published_at < cutoff_date` (a YYYY-MM-DD string)
    and leaves everything else intact: `article_id` / `team` / `source_type` / `title` / `url` /
    `published_at` all survive, so the derived claims (which cite `article_id`, never the text) and the
    url+date Wayback-recall path are untouched. Idempotent (already-null content stays null; a re-poll
    can't restore it — the append-writer dedups on `article_id`). Rows with a null/undatable
    `published_at` are never pruned (can't be dated → kept conservatively).

    Returns a report dict; `dry_run=True` computes it without writing (the numbers to eyeball first).
    """
    empty = {"total": 0, "eligible": 0, "to_null": 0, "chars_freed": 0,
             "oldest": None, "cutoff": cutoff_date, "written": False}
    path = _team_news_raw_path()
    if not path.exists():
        return empty
    df = pl.read_parquet(path)
    if df.is_empty():
        return empty
    day = pl.col("published_at").str.slice(0, 10)
    old = day < cutoff_date
    has_content = pl.col("content").is_not_null() & (pl.col("content").str.len_chars() > 0)
    to_null = df.filter(old & has_content)
    report = {
        "total": df.height,
        "eligible": df.filter(old).height,                       # rows older than the cutoff
        "to_null": to_null.height,                               # rows whose content actually changes
        "chars_freed": int(to_null.select(pl.col("content").str.len_chars().sum()).item() or 0),
        "oldest": df.select(day.min()).item(),
        "cutoff": cutoff_date,
        "written": False,
    }
    if dry_run or to_null.height == 0:
        return report
    pruned = df.with_columns(
        pl.when(old).then(pl.lit(None, dtype=pl.Utf8)).otherwise(pl.col("content")).alias("content")
    )
    pruned.write_parquet(path)
    report["written"] = True
    return report


# --- Team News Dossier (weekly per-team synthesis, §2 news pipeline Stage B) ---
# Stage B distills team_news_raw (Stage A) into a compact, situation/security-focused
# "news sheet" per team-week: a set of scope-tagged claims (player / position_group / unit),
# each clustered across the 3 sources with a synthesized note + provenance. The scope tags are
# what let Stage C slice a team sheet down to a single player by inheritance. Written by the AI
# layer (application/ai/write_team_news_dossier.py) via Claude Haiku — NOT the raw articles;
# the deterministic resolver (fetchers/news.py) attaches sleeper_player_id to player-scope claims.
# Grain = one claim row per (season, week, team, claim); one growing file, tall over the team-weeks.
# The writer is REPLACE-BY (season, week, team): re-running a team-week overwrites just its rows
# (idempotent; a single-team verify run touches only that team), like manager_activity's
# replace-by-owner_id. A team-week with no fantasy-relevant news gets one explicit is_empty row.


def _team_news_dossier_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "team_news_dossier.parquet"


def write_team_news_dossier(df: pl.DataFrame) -> None:
    """Replace the (season, week, team) slices present in `df`, leaving other team-weeks intact.

    `df` is the freshly-synthesized claim rows for one or more team-weeks. Every (season, week,
    team) tuple appearing in `df` is dropped from the store first, then the new rows appended — so
    a re-run of a team-week overwrites it (idempotent) and a single-team run replaces only that
    team. Concat is diagonal so a later schema tweak doesn't break the append.
    """
    path = _team_news_dossier_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = df.select("season", "week", "team").unique()
    if path.exists():
        existing = pl.read_parquet(path)
        existing = existing.join(keys, on=["season", "week", "team"], how="anti")
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_team_news_dossier(team: str | None = None, season: int | None = None,
                           week: int | None = None) -> pl.DataFrame:
    """Read the synthesized team news-sheet claims, optionally filtered by team / season / week."""
    df = pl.read_parquet(_team_news_dossier_path())
    if team is not None:
        df = df.filter(pl.col("team") == team)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


def team_news_dossier_exists() -> bool:
    return _team_news_dossier_path().exists()


# --- Player News Slice (per-player inheritance view, §2 news pipeline Stage C) ---
# Stage C collapses each team's Stage-B news sheet (`team_news_dossier`) down to ONE player by
# INHERITANCE: a skill player inherits his own resolved `player` claims + his `position_group`
# claims (his position, plus team-wide offensive context) + his team's `unit` claims (offense +
# the one condensed defense note). Deterministic reshape — no AI. The per-player consumable the
# §2 synthesis (QUEUED #2) reads next to the ros_outcome_shape anchors. Every on-team skill player
# is present; one who inherits nothing gets an explicit is_empty "no-signal" row (honest-zero) so
# thinness is queryable, not an inferred absence. Each row carries a `signal_tier` (rich/thin/none)
# + counts (the thinness tripwire). Grain = one inherited-claim row per (season, week, player,
# claim). One growing file, tall over player-weeks. Writer is REPLACE-BY (season, week): the whole
# week's slice is a pure function of that week's dossier, so a re-run regenerates it wholesale.


def _player_news_slice_path() -> Path:
    return _SNAPSHOT_DIR / "news" / "player_news_slice.parquet"


def write_player_news_slice(df: pl.DataFrame) -> None:
    """Replace the (season, week) slices present in `df`, leaving other weeks intact.

    Every (season, week) tuple appearing in `df` is dropped from the store first, then the new rows
    appended — so a re-run of a week overwrites it (idempotent). Concat is diagonal so a later schema
    tweak doesn't break the append.
    """
    path = _player_news_slice_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = df.select("season", "week").unique()
    if path.exists():
        existing = pl.read_parquet(path)
        existing = existing.join(keys, on=["season", "week"], how="anti")
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_player_news_slice(sleeper_player_id: str | None = None, season: int | None = None,
                           week: int | None = None) -> pl.DataFrame:
    """Read the per-player inherited news slice, optionally filtered by player / season / week."""
    df = pl.read_parquet(_player_news_slice_path())
    if sleeper_player_id is not None:
        df = df.filter(pl.col("sleeper_player_id") == sleeper_player_id)
    if season is not None:
        df = df.filter(pl.col("season") == season)
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


def player_news_slice_exists() -> bool:
    return _player_news_slice_path().exists()


# --- Projections (multi-source: Sleeper now, FantasyPros in-season) ---
# The borrowed forward prior every Phase-2 read rests on (Product Roadmap Phase 2).
# Normalized, source-agnostic entity: one growing file per season, with `source` as a
# COLUMN (not a directory) — so consensus + disagreement across providers is a group-by
# and "pick a source" is a filter, and adding FantasyPros later is a new `source` value,
# not a schema change. Snapshot/append (mirrors write_leaguelogs_market_snapshot): a
# re-fetch of a (season, week, source) slice replaces it rather than duplicating. Rows
# carry snapshot_date + source_updated_at so an in-season daily history of how a
# projection moved can extend the dedup key later without a rewrite.


def _projections_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "projections" / f"projections_{season}.parquet"


def write_projections(df: pl.DataFrame, season: int, week: int, source: str) -> None:
    """Append one (season, week, source) projection slice to the season file.

    `df` is treated as the complete set of rows for (season, week, source). If the
    season file already exists, any rows matching that combo are dropped first (dedup
    guard) so re-running a week/source replaces it rather than duplicating. Concat is
    diagonal so a future source carrying extra component columns doesn't break the append.
    """
    path = _projections_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(
            ~(
                (pl.col("season") == season)
                & (pl.col("week") == week)
                & (pl.col("source") == source)
            )
        )
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_projections(season: int, week: int | None = None, source: str | None = None) -> pl.DataFrame:
    """Read the season projections file, optionally filtered by week and/or source.

    `source=None` returns every source (the multi-source read the consensus/disagreement
    transform consumes); passing a source is the "pick a provider" selection seam.
    """
    df = pl.read_parquet(_projections_path(season))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    if source is not None:
        df = df.filter(pl.col("source") == source)
    return df


def projections_exist(season: int) -> bool:
    return _projections_path(season).exists()


# --- Derived Analytics ---
# Pre-computed Team Overview analytics, promoted out of the front-end seam
# (queries.js) into polars transforms. Each is now a tall snapshot file per season,
# grain (season, as_of_week, entity): the dashboard as it would have read through each
# week N, every analytic recomputed on weeks ≤ N (the Season-replay dimension). One row
# per (as_of_week, roster_id/player), derived columns the front end reads directly. The
# read fns below take an optional `as_of_week` (default = latest), so existing callers
# get the current-week slice unchanged. When a server arrives, these become API
# endpoints that serve the same parquet — no JS math to port.


def _as_of_slice(df: pl.DataFrame, as_of_week) -> pl.DataFrame:
    """Filter a tall derived-analytics frame to a single as-of week (default = latest).

    `as_of_week="all"` returns the whole tall frame — for a consumer that re-aggregates every
    week's slice (e.g. compute_true_rank reading all of Production VOR) rather than viewing one."""
    if as_of_week == "all":
        return df
    if as_of_week is None:
        as_of_week = df["as_of_week"].max()
    return df.filter(pl.col("as_of_week") == as_of_week)

def _team_form_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"team_form_{season}.parquet"


def write_team_form(df: pl.DataFrame, season: int) -> None:
    """Write the per-team trajectory (form) analytics for a season (overwrite).

    Output of transforms/compute_team_form.py: one row per roster_id carrying the
    recency-weighted scoring slope, direction read, recent record, league-relative
    spectrum position, and the per-week series (serialised JSON).
    """
    path = _team_form_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_team_form(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the per-team form analytics for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_team_form_path(season)), as_of_week)


def _team_leakage_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"team_leakage_{season}.parquet"


def write_team_leakage(df: pl.DataFrame, season: int) -> None:
    """Write the per-team lineup-leakage analytics for a season (overwrite).

    Output of transforms/compute_team_leakage.py: one row per roster_id carrying
    lineup efficiency %, season points left, the coachable-vs-variance split,
    league-relative spectrum position, and the per-week leak + named fixes
    (serialised JSON).
    """
    path = _team_leakage_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_team_leakage(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the per-team leakage analytics for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_team_leakage_path(season)), as_of_week)


def _player_signal_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"player_signal_{season}.parquet"


def write_player_signal(df: pl.DataFrame, season: int) -> None:
    """Write the per-player spike signal-quality read for a season (overwrite).

    Output of transforms/compute_player_signal.py: one row per rostered skill player
    carrying the recent per-game production, the opportunity vs efficiency
    decomposition (opp_g, ppo, regression_risk), the TD share of scoring, a
    sample-gated categorical read, and the per-week points/opportunity series
    (serialised JSON). The first decision-critique engine slice ("is this production
    real, or noise?").
    """
    path = _player_signal_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_player_signal(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the per-player signal-quality read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_player_signal_path(season)), as_of_week)


def _projection_consensus_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"projection_consensus_{season}.parquet"


def write_projection_consensus(df: pl.DataFrame, season: int) -> None:
    """Write the per-(week, player) projection consensus + spread band for a season (overwrite).

    Output of transforms/compute_projection_consensus.py: one row per (week,
    sleeper_player_id) over the whole skill pool, carrying the borrowed consensus center
    (median proj across sources), a percentile band (p25/p50/p75) whose width is the
    player's residual std shrunk toward a positional prior, and the cross-source
    disagreement column (null until a 2nd source lands). The Phase-2 forward prior /
    law-2 confidence band (DECISION_READS.md §3).

    Unlike the other derived analytics this is NOT tall over as_of_week: a projection for
    week W is a fixed forward statement, and its band uses only history from weeks < W —
    the as-of information is baked into the projected week, so the read is keyed on `week`
    (like the projections entity it derives from), not on an as_of_week slice.
    """
    path = _projection_consensus_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_projection_consensus(season: int, week: int | None = None) -> pl.DataFrame:
    """Read the projection consensus + spread for a season, optionally filtered to one week."""
    df = pl.read_parquet(_projection_consensus_path(season))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    return df


# --- Production VOR ---
# The first read that *consumes* the projection substrate (DECISION_READS.md §4):
# rest-of-season production value per rostered player, anchored so the waiver line = 0 and
# normalised by the pool spread (top rosterable − waiver). Tall over as_of_week like the
# three team/player analytics — for each cutoff N the ROS value sums the borrowed weekly
# centres over the *remaining* schedule (weeks > N) and the waiver line is resolved against
# the roster-as-of-N, so the read plugs into the same "As of" week selector. Only Production
# VOR here; Market VOR (LeagueLogs) + the trade gap are V4.


def _production_vor_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"production_vor_{season}.parquet"


def write_production_vor(df: pl.DataFrame, season: int) -> None:
    """Write the per-(as_of_week, player) Production VOR read for a season (overwrite).

    Output of transforms/compute_production_vor.py: one row per rostered skill player per
    as-of week, carrying the rest-of-season production value (sum of borrowed weekly
    projection centres over the remaining schedule), the pool waiver line + top used to
    normalise it, and the resulting vor (waiver = 0, negative = dead weight, ~1 = a top
    rosterable player at that pool). QB is its own pool; RB/WR/TE share one flex pool.
    """
    path = _production_vor_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_production_vor(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the Production VOR read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_production_vor_path(season)), as_of_week)


# --- Market VOR ---
# The market-value twin of Production VOR (DECISION_READS.md §4): the same waiver = 0 ÷ pool-spread
# VOR, computed on the LeagueLogs market value instead of the borrowed projection, so both land on one
# comparable scale and the gap between them is the trade signal. Output of
# transforms/compute_market_vor.py: one row per (snapshot_date, rostered skill player), carrying the
# borrowed market value, the pool waiver/top used to normalise it, the resulting market_vor, and the
# joined Production VOR + trade_gap. TALL over `snapshot_date` (the market's own time axis — the analog
# of Production VOR's as_of_week), so the un-backdatable market series is banked in derived form.
# TIME-WORLD NOTE: the rosters are frozen-2025 but the market is current (2026 offseason) — every row
# carries `is_cross_time` + `market_season`, so the gap is never silently fused across time.


def _market_vor_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"market_vor_{season}.parquet"


def write_market_vor(df: pl.DataFrame, season: int) -> None:
    """Write the per-(snapshot_date, player) Market VOR read for a league season (overwrite)."""
    path = _market_vor_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_market_vor(season: int, snapshot_date=None) -> pl.DataFrame:
    """Read the Market VOR read for one market snapshot (default = latest banked date)."""
    df = pl.read_parquet(_market_vor_path(season))
    if snapshot_date is None:
        return df.filter(pl.col("snapshot_date") == df["snapshot_date"].max())
    return df.filter(pl.col("snapshot_date") == pl.lit(snapshot_date).str.to_date())


def market_vor_exists(season: int) -> bool:
    return _market_vor_path(season).exists()


# --- True Rank ---
# The team-level aggregation of the Value read (DECISION_READS.md §5, first half): sum the
# borrowed ROS production value of each team's *optimal* (lineup-slot-aware) lineup → a
# record-independent measure of how good a roster is, ranked within the league. No new engine —
# it re-aggregates Production VOR over the optimal-lineup rules. Tall over as_of_week like the
# other derived analytics, so it plugs into the same "As of" week selector. The integration
# precursor the Phase-4 bracket-math Monte Carlo (§5 full) will sit on top of.


def _true_rank_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"true_rank_{season}.parquet"


def write_true_rank(df: pl.DataFrame, season: int) -> None:
    """Write the per-(as_of_week, roster_id) True Rank read for a season (overwrite).

    Output of transforms/compute_true_rank.py: one row per team per as-of week, carrying the
    optimal-lineup ROS strength (sum of the borrowed weekly projection centres over the
    remaining schedule for each optimal starter), the bench value behind it, the within-league
    rank (1 = strongest), and a league-relative 0–1 spectrum position. Record-independent.
    """
    path = _true_rank_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_true_rank(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the True Rank read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_true_rank_path(season)), as_of_week)


# --- Positional Depth ---
# The Value read (DECISION_READS.md §6) re-sliced *per position*, benchmarked against the league:
# a team's positional surplus (startable-quality depth = trade capital) vs. gaps (a starting slot
# filled at ~replacement level). No new engine — it re-aggregates Production VOR per position,
# net of the position's starting requirement. Tall over as_of_week like the other derived
# analytics, so it plugs into the same "As of" week selector. Closes the Phase-3 read set.


def _positional_depth_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"positional_depth_{season}.parquet"


def write_positional_depth(df: pl.DataFrame, season: int) -> None:
    """Write the per-(as_of_week, roster_id, position) Positional Depth read for a season (overwrite).

    Output of transforms/compute_positional_depth.py: one row per team per position (QB/RB/WR/TE)
    per as-of week, carrying the position's rostered + starter ROS value, the surplus beyond the
    starting requirement (depth / trade capital), the marginal starter's VOR (the gap indicator),
    a league-relative 0–1 spectrum position within that position's cohort, and an advisory
    surplus/adequate/gap shape. A re-slice of Production VOR — borrows the value, builds no prior.
    """
    path = _positional_depth_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_positional_depth(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the Positional Depth read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_positional_depth_path(season)), as_of_week)


# --- Bracket Odds ---
# The bracket-math half of the Posture read (DECISION_READS.md §5): a Monte Carlo season
# simulation that turns the forward reads into playoff odds. Team weekly score distributions
# (mean = optimal-lineup projected points, spread = the §3 weekly band) drive per-matchup win
# probabilities; simulating the remaining real schedule → playoff odds + projected wins/seed +
# magic number. With True Rank (§5 first half) it completes Posture. Tall over as_of_week like
# the other derived analytics, so it plugs into the same "As of" week selector.


def _bracket_odds_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"bracket_odds_{season}.parquet"


def write_bracket_odds(df: pl.DataFrame, season: int) -> None:
    """Write the per-(as_of_week, roster_id) Bracket Odds read for a season (overwrite).

    Output of transforms/compute_bracket_sim.py: one row per team per as-of week, carrying the
    Monte Carlo playoff odds, projected regular-season wins, average final seed, magic number,
    and the current (as-of-N) wins/points-for the sim starts from.
    """
    path = _bracket_odds_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_bracket_odds(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the Bracket Odds read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_bracket_odds_path(season)), as_of_week)


# --- ROS Outcome Shape ---
# The forward player read (DECISION_READS.md §2): bull season / bear season / situation-security
# per rostered player. This is the *quantitative skeleton* — bull/bear is the rest-of-season-horizon
# analog of the §3 weekly spread: the borrowed ROS centre (Production VOR's ros_value) ± an
# accumulated band (√Σ of the §3 weekly band² over the remaining schedule, weekly independence),
# floored at 0. Time decay is emergent — fewer remaining weeks shrink the band toward the realised
# path. Situation/security carries the structured Sleeper security tier + the player_signal trust
# axis (direction/reliability) as evidence, not a fused grade. The AI narrative + 1-10 roll-up is
# Phase 6. Tall over as_of_week like the other derived analytics, so it plugs into the same "As of"
# week selector.


def _ros_outcome_shape_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"ros_outcome_shape_{season}.parquet"


def write_ros_outcome_shape(df: pl.DataFrame, season: int) -> None:
    """Write the per-(as_of_week, roster_id, player) ROS Outcome Shape read for a season (overwrite).

    Output of transforms/compute_ros_outcome_shape.py: one row per rostered skill player per as-of
    week, carrying the borrowed ROS centre (ros_center), the bull/bear rest-of-season band
    (ros_bull/ros_bear = centre ± bull_z·ros_sigma, floored at 0), the accumulated band std
    (ros_sigma = √Σ weekly band² over the remaining schedule) + relative dispersion (ros_cv), the
    number of remaining projected weeks, and the structured situation/security evidence
    (security tier + direction/reliability from the player_signal trust axis). Borrows the centre and
    band — builds only the ROS-horizon aggregation and the situation carry-through.
    """
    path = _ros_outcome_shape_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_ros_outcome_shape(season: int, as_of_week=None) -> pl.DataFrame:
    """Read the ROS Outcome Shape read for one as-of week (default = latest)."""
    return _as_of_slice(pl.read_parquet(_ros_outcome_shape_path(season)), as_of_week)


# --- ROS Synthesis (the §2 AI interpretation of ROS Outcome Shape) ---
# The interpretation half of §2 (DECISION_READS.md §2) — the last mile compute_ros_outcome_shape.py
# deferred ("the AI narrative + 1-10 grade roll-up is Phase 6"). Per player, one Claude call fuses the
# quantitative anchor (ros_outcome_shape) with the situation news (player_news_slice) into three 1-10
# grades (bull / bear / situation) EACH with a prose note, consolidated headlines (grounded in the
# cited claims), and a confidence flag. Keyed by the NEWS (season, week) = the current world; the ros
# anchor is a by-id lookup carrying anchor_season / anchor_is_prior_season so a prior-season anchor is
# flagged, never silently fused. Written by application/ai/write_ros_synthesis.py via Claude Haiku; a
# player with no anchor AND no news gets a hardcoded "insufficient data" row (is_zero_signal, AI
# skipped). One file per season; REPLACE-BY (season, week, sleeper_player_id) so a single-player
# re-run (news changed / --force) overwrites just his row — the per-player, cache-friendly grain the
# on-demand runtime will lean on (news_content_hash is the staleness seam).


def _ros_synthesis_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"ros_synthesis_{season}.parquet"


def write_ros_synthesis(df: pl.DataFrame) -> None:
    """Replace the (season, week, sleeper_player_id) rows present in `df`, per-player idempotent.

    A re-run of a player overwrites just his row (idempotent) and a single-player verify run replaces
    only that player, leaving the rest of the week intact. One file per season (from `df`'s season).
    Concat is diagonal so a later schema tweak doesn't break the append.
    """
    for season in df.select("season").unique().to_series().to_list():
        part = df.filter(pl.col("season") == season)
        path = _ros_synthesis_path(season)
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = part.select("season", "week", "sleeper_player_id").unique()
        if path.exists():
            existing = pl.read_parquet(path)
            existing = existing.join(keys, on=["season", "week", "sleeper_player_id"], how="anti")
            part = pl.concat([existing, part], how="diagonal")
        part.write_parquet(path)


def read_ros_synthesis(season: int, week: int | None = None,
                       sleeper_player_id: str | None = None) -> pl.DataFrame:
    """Read the per-player §2 ROS synthesis for a season, optionally one week / player."""
    df = pl.read_parquet(_ros_synthesis_path(season))
    if week is not None:
        df = df.filter(pl.col("week") == week)
    if sleeper_player_id is not None:
        df = df.filter(pl.col("sleeper_player_id") == sleeper_player_id)
    return df


def ros_synthesis_exists(season: int) -> bool:
    return _ros_synthesis_path(season).exists()


# --- Manager Activity (cross-league, DECISION_READS.md §7) ---
# The FIRST cross-league / user-keyed entity — every other store is single-league,
# per-season. Acquired by sleeper.py's `fetch-manager-activity` mode: for each manager in
# the target league, their behaviour across their *comparable* other Sleeper leagues (same
# scoring profile + size + QB structure + format). `owner_id` (Sleeper user_id) is the
# identity key and `source_league_id` / `source_season` are COLUMNS (the projections
# "source-as-a-column" idiom) so one tall file spans every manager, league, and season.
# Two row kinds share the file (a `kind` column): "league" markers (one per searched
# comparable league — so a league a manager was inactive in still counts toward signal
# depth) and "txn" rows (one per that manager's transaction). Written INCREMENTALLY per
# manager (replace-by-owner_id), so a mid-fan-out failure leaves completed managers on disk
# and a re-run is idempotent — the leaguelogs reliability lesson applied to an expensive
# once-a-season fan-out. Consumed by compute_manager_features.py.


def _manager_activity_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "sleeper" / str(season) / f"manager_activity_{season}.parquet"


def write_manager_activity(df: pl.DataFrame, season: int, owner_id: str) -> None:
    """Append one manager's complete activity slice to the season file (replace-by-owner_id).

    `df` is treated as the COMPLETE set of rows for `owner_id` (their league markers + txn
    rows). If the season file exists, any existing rows for that owner_id are dropped first
    so re-fetching a manager replaces their slice rather than duplicating (and a stale
    no-longer-comparable league can't linger). Concat is diagonal so a schema tweak on a
    later run doesn't break the append.
    """
    path = _manager_activity_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pl.read_parquet(path).filter(pl.col("owner_id") != owner_id)
        df = pl.concat([existing, df], how="diagonal")
    df.write_parquet(path)


def read_manager_activity(season: int, owner_id: str | None = None) -> pl.DataFrame:
    """Read the cross-league manager activity for a season, optionally one manager."""
    df = pl.read_parquet(_manager_activity_path(season))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_activity_exists(season: int) -> bool:
    return _manager_activity_path(season).exists()


# --- Manager Features (cross-league behavioural profile, DECISION_READS.md §7) ---
# The deterministic feature extraction over manager_activity — one row per manager (owner_id):
# FAAB aggression, waiver/free-agent mix, waiver success rate, add/drop churn, trade frequency,
# positional lean of adds, plus the signal-depth counts (n_leagues / n_seasons / n_transactions)
# Phase B gates AI confidence on. Rate/lean features are null when undefined (thin sample), never
# a fabricated 0. This is the pre-filtered, credit-free AI input for the Phase-B Haiku dossier
# writer (never raw transaction logs — credit optimization, principle #5). A computed analytic,
# so it lives in derived/ alongside the other compute_* outputs; overwrite per run.


def _manager_features_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"manager_features_{season}.parquet"


def write_manager_features(df: pl.DataFrame, season: int) -> None:
    """Write the per-manager behavioural feature profile for a season (overwrite).

    Output of transforms/compute_manager_features.py: one row per league manager (owner_id),
    carrying the deterministic behavioural features + signal-depth counts + an is_primary flag
    (the primary user gets a blindspot-scoped dossier in Phase B).
    """
    path = _manager_features_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_manager_features(season: int, owner_id: str | None = None) -> pl.DataFrame:
    """Read the per-manager feature profile for a season, optionally one manager."""
    df = pl.read_parquet(_manager_features_path(season))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_features_exists(season: int) -> bool:
    return _manager_features_path(season).exists()


# --- Manager Dossiers (AI-written cross-league behavioural profiles, DECISION_READS.md §7) ---
# The Phase-B AI layer's output: one qualitative dossier per manager (owner_id), synthesised by
# Claude Haiku from the deterministic manager_features (never raw logs). The project's first
# AI-written entity. Tendencies-not-verdicts, fixed schema (headline / waiver_faab / trade_tendency /
# positional_lean / roster_construction / edge_or_blindspot / confidence_note) so dossiers read side
# by side; blindspot framing for the primary user, exploitable-edge for opponents. A zero-comparable-
# league manager gets a hardcoded "no intel" dossier (is_zero_signal=True) with the AI skipped. Rows
# carry the signal-depth echo + provenance (model, generated_at). Written by application/ai/
# write_manager_dossiers.py; overwrite per run (run-once-per-season unless --force).


def _manager_dossiers_path(season: int) -> Path:
    return _SNAPSHOT_DIR / "derived" / f"manager_dossiers_{season}.parquet"


def write_manager_dossiers(df: pl.DataFrame, season: int) -> None:
    """Write the per-manager AI dossiers for a season (overwrite)."""
    path = _manager_dossiers_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_manager_dossiers(season: int, owner_id: str | None = None) -> pl.DataFrame:
    """Read the per-manager AI dossiers for a season, optionally one manager."""
    df = pl.read_parquet(_manager_dossiers_path(season))
    if owner_id is not None:
        df = df.filter(pl.col("owner_id") == owner_id)
    return df


def manager_dossiers_exist(season: int) -> bool:
    return _manager_dossiers_path(season).exists()


# --- League Corpus (Session 0.5): discovery crawl + the selected league registry ---
#
# Two additive, cross-season entities under snapshots/corpus/ — NOT keyed by season (the corpus
# spans 2020-2025 in one file each). corpus_discovery is the full classified BFS crawl (one row per
# (league_id, season), free classification, no game data); corpus_manifest is the SELECTED league
# registry the L0 keying sessions consume. Both written whole (overwrite) — the discovery crawl holds
# the full deduped set in memory and rewrites it each checkpoint (the leaguelogs.snapshot() precedent).
# Purely additive: no existing entity, path, or transform is touched here.

def _corpus_discovery_path() -> Path:
    return _SNAPSHOT_DIR / "corpus" / "corpus_discovery.parquet"


def write_corpus_discovery(df: pl.DataFrame) -> None:
    """Write the full deduped discovery crawl (one row per (league_id, season)); overwrite."""
    path = _corpus_discovery_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_corpus_discovery() -> pl.DataFrame:
    return pl.read_parquet(_corpus_discovery_path())


def corpus_discovery_exists() -> bool:
    return _corpus_discovery_path().exists()


def _corpus_manifest_path() -> Path:
    return _SNAPSHOT_DIR / "corpus" / "corpus_manifest.parquet"


def write_corpus_manifest(df: pl.DataFrame) -> None:
    """Write the selected league registry (one row per narrowed candidate); overwrite."""
    path = _corpus_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


def read_corpus_manifest() -> pl.DataFrame:
    return pl.read_parquet(_corpus_manifest_path())


def corpus_manifest_exists() -> bool:
    return _corpus_manifest_path().exists()
