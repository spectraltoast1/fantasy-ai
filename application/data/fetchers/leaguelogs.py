"""
LeagueLogs fetcher — daily market-value snapshots.

LeagueLogs (https://leaguelogs.com) publishes a forward-looking "market value"
for every skill-position player, keyed on Sleeper player ID — so it joins into
this project's pipeline (which pivots on sleeper_player_id) with no id mapping.

The API only ever serves "now" (values refresh every ~6h, no historical endpoint),
so the value time-series exists ONLY if we snapshot it. This fetcher pulls every
published profile once per run and appends to a single growing history file via
data_layer. History is never overwritten — it cannot be re-fetched.

Scope: QB/RB/WR/TE only (DEF/K excluded by the source). Dynasty profiles also
include rookie-pick rows (synthetic ids like "PICK#2026#01"), captured with a
flattened `pick` block and is_pick=True.

ATTRIBUTION: Any UI that displays this data must show "Powered by LeagueLogs API"
(https://leaguelogs.com) per the API terms. The data layer stores it; the
dashboard/playground must surface it.

Public API:
    snapshot()        — fetch all profiles for today and append to the history file
    list_profiles()   — return the currently published profile keys

Usage:
    python leaguelogs.py snapshot
    python leaguelogs.py profiles
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

_HERE = Path(__file__).resolve().parent   # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                   # .../application/data/
sys.path.insert(0, str(_DATA_DIR))
import data_layer

_BASE = "https://developer.leaguelogs.com/v1"
_TIMEOUT = 30

# Pin the schema so the growing history file stays stable across runs (and so
# redraft rows, which have no pick fields, don't collapse those columns to Null).
_SCHEMA = {
    "snapshot_date": pl.Date,
    "snapshot_ts": pl.Utf8,
    "season": pl.Int64,
    "week": pl.Int64,
    "profile": pl.Utf8,
    "format": pl.Utf8,
    "num_qbs": pl.Int64,
    "num_teams": pl.Int64,
    "ppr": pl.Float64,
    "source_last_refreshed": pl.Utf8,
    "source_version": pl.Int64,
    "sleeper_player_id": pl.Utf8,
    "value": pl.Float64,
    "raw_value": pl.Int64,
    "overall_rank": pl.Int64,
    "position_rank": pl.Int64,
    "is_pick": pl.Boolean,
    "pick_season": pl.Utf8,
    "pick_round": pl.Int64,
    "pick_in_round": pl.Int64,
    "pick_is_future": pl.Boolean,
    "pick_bucket": pl.Utf8,
}


def _get(path: str) -> dict:
    resp = requests.get(f"{_BASE}{path}", timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def list_profiles() -> list[str]:
    """Return the currently published profile keys (discovered, not hardcoded —
    the API contract is additive, so new profiles get picked up automatically)."""
    return [p["key"] for p in _get("/market")["profiles"]]


def _nfl_state() -> tuple[int, int]:
    state = _get("/nfl-state")
    return int(state["season"]), int(state.get("week") or 0)


def _profile_rows(profile_key: str, season: int, week: int,
                  snapshot_date, snapshot_ts: str) -> list[dict]:
    payload = _get(f"/market/{profile_key}")
    meta = payload.get("meta", {})
    prof = meta.get("profile", {})
    rows = []
    for r in payload.get("data", []):
        pick = r.get("pick")
        rows.append({
            "snapshot_date": snapshot_date,
            "snapshot_ts": snapshot_ts,
            "season": season,
            "week": week,
            "profile": profile_key,
            "format": prof.get("format"),
            "num_qbs": prof.get("numQbs"),
            "num_teams": prof.get("numTeams"),
            "ppr": float(prof["ppr"]) if prof.get("ppr") is not None else None,
            "source_last_refreshed": meta.get("lastRefreshed"),
            "source_version": meta.get("version"),
            "sleeper_player_id": str(r["sleeperPlayerId"]),
            "value": float(r["value"]),
            "raw_value": r.get("rawValue"),
            "overall_rank": r.get("overallRank"),
            "position_rank": r.get("positionRank"),
            "is_pick": pick is not None,
            "pick_season": pick.get("season") if pick else None,
            "pick_round": pick.get("round") if pick else None,
            "pick_in_round": pick.get("pickInRound") if pick else None,
            "pick_is_future": pick.get("isFuture") if pick else None,
            "pick_bucket": pick.get("bucket") if pick else None,
        })
    return rows


def snapshot() -> None:
    """Fetch every published profile for today and append to the history file.

    Writes incrementally: after each profile is fetched, the cumulative set of
    today's rows is persisted. So if a later profile's API call fails mid-run,
    the profiles already fetched are on disk instead of being discarded with the
    whole day. The writer dedupes by snapshot_date, so a later re-run cleanly
    replaces a partial day with the complete one (no duplicates).

    Caveat until retry/resilience lands: a failed run now leaves a PARTIAL day
    (e.g. 3 of 5 profiles) rather than no day. That's strictly more recoverable
    than total loss — re-running completes it — but downstream analysis should
    treat a day with fewer than the expected profile count as incomplete.
    """
    now = datetime.now(timezone.utc)
    snapshot_date = now.date()
    snapshot_ts = now.isoformat(timespec="seconds")

    season, week = _nfl_state()
    profiles = list_profiles()
    print(f"LeagueLogs snapshot {snapshot_date} (season={season}, week={week}) "
          f"— {len(profiles)} profile(s)")

    all_rows: list[dict] = []
    for i, key in enumerate(profiles, start=1):
        rows = _profile_rows(key, season, week, snapshot_date, snapshot_ts)
        picks = sum(1 for r in rows if r["is_pick"])
        all_rows.extend(rows)
        # Persist the cumulative set after each profile so a later failure can't
        # discard profiles already fetched this run. write_leaguelogs_market_snapshot
        # treats `df` as the full set for snapshot_date and replaces that day, so
        # each call simply grows today's rows on disk.
        df = pl.DataFrame(all_rows, schema_overrides=_SCHEMA)
        data_layer.write_leaguelogs_market_snapshot(df, snapshot_date)
        print(f"  {key}: {len(rows)} rows ({len(rows) - picks} players, {picks} picks) "
              f"— saved {i}/{len(profiles)} profiles, {len(all_rows)} rows for {snapshot_date}")
        time.sleep(0.3)  # be polite; limit is generous

    print('  Attribution required on any UI: "Powered by LeagueLogs API" (https://leaguelogs.com)')


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if cmd == "snapshot":
        snapshot()
    elif cmd == "profiles":
        for p in list_profiles():
            print(p)
    else:
        print("Usage: leaguelogs.py snapshot | leaguelogs.py profiles")
        sys.exit(1)
