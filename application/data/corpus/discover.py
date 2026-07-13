"""
Corpus discovery — persisted, resumable, manager-keyed BFS (Session 0.5, commit 1).

The Session-0 crawl mechanic, now durable: seed league → rosters → owner_ids →
sleeper._manager_leagues (every league a manager played, 2020-2025) → classify_league (free) →
dedupe on (league_id, season) → recurse to depth 2. All network I/O through fetchers/_http.py.

Discovery is free; harvest is what costs — so this stores ONLY the classification signature + the
raw scoring/roster/playoff fields select.py needs (no rosters/matchups/transactions). Writes the full
deduped set to snapshots/corpus/corpus_discovery.parquet each checkpoint (data_layer), plus a sidecar
crawl-state json so a killed run resumes instead of re-crawling (the leaguelogs.snapshot() precedent).

Stopping rule (NOT to exhaustion): stop once the RECENT seasons are over-supplied in the classification-
matched stratum, or the frontier empties, or a backstop trips. Early seasons (2020-21) stay thin by
nature (recency skew) — that is a finding, reported by select, not a failure here.

Run: python3 -m application.data.corpus.discover [--stop-per-season N] [--max-calls N] [--max-seconds N] [--fresh]
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

import polars as pl

from application import config
from application.data import data_layer
from application.data.corpus import _corpus
from application.data.fetchers import _http
from application.data.fetchers.sleeper import _SLEEPER_BASE, _manager_leagues
from application.data.transforms._manager import classify_league

MAX_DEPTH = 2
CHECKPOINT_EVERY = 25                       # managers between flushes
STOP_RECENT_SEASONS = (2022, 2023, 2024, 2025)   # the seasons that CAN be over-supplied
DEFAULT_STOP_PER_SEASON = 70                # matched supply per recent season before stopping (cap 60 + margin)
DEFAULT_MAX_CALLS = 30000                   # safety backstop
DEFAULT_MAX_SECONDS = 3300                  # ~55 min safety backstop

_DISCOVERY_COLS = [
    "league_id", "season", "name", "status", "scoring_profile", "num_teams", "qb_structure",
    "league_format", "waiver_budget", "has_divisions", "previous_league_id", "playoff_week_start",
    "roster_positions", "scoring_settings_json", "depth", "discovered_at",
]


def _state_path():
    return data_layer._corpus_discovery_path().parent / "corpus_crawl_state.json"


def _rosters_owners(league_id):
    rosters = _http.get_json(f"{_SLEEPER_BASE}/league/{league_id}/rosters") or []
    return [r.get("owner_id") for r in rosters if r.get("owner_id")]


def _candidate_row(season, lg, depth, now_iso):
    cls = classify_league(lg)
    settings = lg.get("settings") or {}
    return {
        "league_id": lg.get("league_id"),
        "season": int(season),
        "name": lg.get("name"),
        "status": lg.get("status"),
        "scoring_profile": cls["scoring_profile"],
        "num_teams": cls["num_teams"],
        "qb_structure": cls["qb_structure"],
        "league_format": cls["league_format"],
        "waiver_budget": cls["waiver_budget"],
        "has_divisions": bool(settings.get("divisions")),
        "previous_league_id": lg.get("previous_league_id"),
        "playoff_week_start": settings.get("playoff_week_start"),
        "roster_positions": lg.get("roster_positions") or [],
        "scoring_settings_json": json.dumps(lg.get("scoring_settings") or {}, sort_keys=True),
        "depth": int(depth),
        "discovered_at": now_iso,
    }


def _matched_supply_by_recent_season(candidates):
    counts = {s: 0 for s in STOP_RECENT_SEASONS}
    for row in candidates.values():
        s = row["season"]
        if s in counts and _corpus.is_matched_eligible(
                row["scoring_profile"], row["qb_structure"], row["league_format"], row["num_teams"]):
            counts[s] += 1
    return counts


def _persist(candidates, visited, expanded, queue, calls, t0):
    df = pl.DataFrame(list(candidates.values())).select(_DISCOVERY_COLS)
    data_layer.write_corpus_discovery(df)
    _state_path().write_text(json.dumps({
        "visited_mgrs": sorted(visited), "expanded_leagues": sorted(expanded),
        "queue": queue, "calls": calls, "elapsed": round(time.monotonic() - t0, 1),
    }))


def run(stop_per_season, max_calls, max_seconds, fresh):
    _http.set_throttle(0.1)   # ~10 calls/sec — polite across the long fan-out
    t0 = time.monotonic()

    if not fresh and data_layer.corpus_discovery_exists() and _state_path().exists():
        st = json.loads(_state_path().read_text())
        candidates = {(r["league_id"], r["season"]): r
                      for r in data_layer.read_corpus_discovery().to_dicts()}
        visited, expanded = set(st["visited_mgrs"]), set(st["expanded_leagues"])
        queue = [tuple(x) for x in st["queue"]]
        calls = st["calls"]
        print(f"[resume] candidates={len(candidates)} visited={len(visited)} queue={len(queue)} calls={calls}")
    else:
        seed = str(config.SLEEPER_LEAGUE_ID)
        calls = 1
        seed_owners = _rosters_owners(seed)
        candidates, visited, expanded = {}, set(), {seed}
        queue = [(o, 0) for o in seed_owners]
        print(f"[start] seed={seed} seed_managers={len(seed_owners)}")

    processed = 0
    while queue:
        est_calls = calls + 6 * (len(visited))    # _manager_leagues = 6 season-calls per manager
        if est_calls >= max_calls or (time.monotonic() - t0) >= max_seconds:
            print(f"[backstop] calls≈{calls} elapsed={time.monotonic()-t0:.0f}s — stopping (resumable)")
            break

        owner_id, depth = queue.pop(0)
        if owner_id in visited:
            continue
        visited.add(owner_id)
        processed += 1
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

        try:
            league_objs = _manager_leagues(owner_id, 2025, seasons_back=5)
            calls += len(_corpus.SEASONS)
        except Exception as exc:   # noqa: BLE001 — isolate a dead manager, keep crawling
            print(f"  [mgr {str(owner_id)[:8]}] FAILED: {type(exc).__name__} — {exc}")
            continue

        fresh_leagues = []
        for season, lg in league_objs:
            lid = lg.get("league_id")
            key = (lid, int(season))
            if not lid or key in candidates:
                continue
            candidates[key] = _candidate_row(season, lg, depth, now_iso)
            fresh_leagues.append(lid)

        if depth < MAX_DEPTH:
            for lid in fresh_leagues:
                if lid in expanded:
                    continue
                expanded.add(lid)
                try:
                    calls += 1
                    for o in _rosters_owners(lid):
                        if o not in visited:
                            queue.append((o, depth + 1))
                except Exception as exc:   # noqa: BLE001
                    print(f"  [league {lid}] roster FAIL: {type(exc).__name__} — {exc}")

        if processed % CHECKPOINT_EVERY == 0:
            _persist(candidates, visited, expanded, queue, calls, t0)
            supply = _matched_supply_by_recent_season(candidates)
            print(f"[progress] mgrs={len(visited)} cand={len(candidates)} queue={len(queue)} "
                  f"calls≈{calls} matched(recent)={supply}")
            if all(v >= stop_per_season for v in supply.values()):
                print(f"[stop] recent seasons all ≥ {stop_per_season} matched — over-supplied")
                break

    _persist(candidates, visited, expanded, queue, calls, t0)
    supply = _matched_supply_by_recent_season(candidates)
    done = not queue
    print(f"[done={done}] candidates={len(candidates)} managers={len(visited)} frontier_left={len(queue)} "
          f"calls≈{calls} elapsed={time.monotonic()-t0:.0f}s")
    print(f"  matched supply (recent seasons): {supply}")
    print(f"  → corpus_discovery.parquet ({len(candidates)} rows)")


def main():
    ap = argparse.ArgumentParser(description="Corpus discovery crawl (persisted, resumable).")
    ap.add_argument("--stop-per-season", type=int, default=DEFAULT_STOP_PER_SEASON)
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument("--max-seconds", type=int, default=DEFAULT_MAX_SECONDS)
    ap.add_argument("--fresh", action="store_true", help="ignore any prior state and start over")
    a = ap.parse_args()
    run(a.stop_per_season, a.max_calls, a.max_seconds, a.fresh)


if __name__ == "__main__":
    main()
    sys.exit(0)
