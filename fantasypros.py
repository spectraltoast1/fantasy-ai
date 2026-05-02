import json
import requests
from datetime import datetime, timezone, timedelta
from config import FANTASY_PROS_API_KEY

BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl"
HEADERS = {"x-api-key": FANTASY_PROS_API_KEY}

NEWS_CACHE = "data/news.json"
PROJECTIONS_CACHE = "data/projections_{season}_week{week}.json"
NEWS_MAX_AGE_DAYS = 14
NEWS_FETCH_LIMIT = 50
PROJECTION_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DST"]


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def refresh_news():
    print(f"Fetching FantasyPros NFL news (latest {NEWS_FETCH_LIMIT})...")
    r = requests.get(
        f"{BASE_URL}/news",
        headers=HEADERS,
        params={"limit": NEWS_FETCH_LIMIT},
    )
    r.raise_for_status()
    items = r.json().get("items", [])

    existing = _load_news_raw()
    existing_ids = {a["id"] for a in existing}

    added = 0
    for item in items:
        if item["id"] not in existing_ids:
            existing.append({
                "id": item["id"],
                "created": item["created"],
                "team_id": item.get("team_id"),
                "player_id": item.get("player_id"),
                "title": item.get("title"),
                "desc": item.get("desc"),
                "impact": item.get("impact"),
                "categories": item.get("categories", []),
                "link": item.get("link"),
            })
            added += 1

    # Prune articles older than NEWS_MAX_AGE_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_MAX_AGE_DAYS)
    before = len(existing)
    existing = [
        a for a in existing
        if datetime.fromisoformat(a["created"].replace(" ", "T")).replace(tzinfo=timezone.utc) >= cutoff
    ]
    pruned = before - len(existing)

    # Sort newest first
    existing.sort(key=lambda a: a["created"], reverse=True)

    cache = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "articles": existing,
    }
    with open(NEWS_CACHE, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"  Added {added} new articles, pruned {pruned} old. Total: {len(existing)}")
    return cache


def load_news(team_ids=None, days=7):
    """Return articles, optionally filtered to specific team IDs and recency."""
    data = _load_news_raw()
    if not data:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    for a in data:
        created = datetime.fromisoformat(a["created"].replace(" ", "T")).replace(tzinfo=timezone.utc)
        if created < cutoff:
            continue
        if team_ids and a.get("team_id") not in team_ids:
            continue
        results.append(a)
    return results


def _load_news_raw():
    try:
        with open(NEWS_CACHE) as f:
            return json.load(f).get("articles", [])
    except FileNotFoundError:
        return []


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def refresh_projections(season, week):
    print(f"Fetching FantasyPros projections for {season} week {week}...")
    players = {}
    for position in PROJECTION_POSITIONS:
        r = requests.get(
            f"{BASE_URL}/{season}/projections",
            headers=HEADERS,
            params={"position": position, "week": week},
        )
        if r.status_code != 200:
            print(f"  Warning: {position} returned {r.status_code}, skipping.")
            continue
        for p in (r.json().get("players") or []):
            stats = p.get("stats", {})
            players[str(p["fpid"])] = {
                "name": p["name"],
                "position": p["position_id"],
                "team": p.get("team_id"),
                "fpid": p["fpid"],
                "points_ppr": stats.get("points_ppr"),
                "points_std": stats.get("points"),
                "points_half": stats.get("points_half"),
                "rec_rec": stats.get("rec_rec"),
                "rec_yds": stats.get("rec_yds"),
                "rec_tds": stats.get("rec_tds"),
                "rush_att": stats.get("rush_att"),
                "rush_yds": stats.get("rush_yds"),
                "rush_tds": stats.get("rush_tds"),
                "pass_yds": stats.get("pass_yds"),
                "pass_tds": stats.get("pass_tds"),
                "pass_int": stats.get("pass_int"),
            }

    cache = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "week": week,
        "players": players,
    }
    path = PROJECTIONS_CACHE.format(season=season, week=week)
    with open(path, "w") as f:
        json.dump(cache, f)
    print(f"  Cached {len(players)} players to {path}")
    return cache


def load_projections(season, week):
    path = PROJECTIONS_CACHE.format(season=season, week=week)
    try:
        with open(path) as f:
            return json.load(f).get("players", {})
    except FileNotFoundError:
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from sleeper import get_nfl_state

    state = get_nfl_state()
    season = state.get("season", "2025")
    week = state.get("week") or 1

    if "--news" in sys.argv or len(sys.argv) == 1:
        cache = refresh_news()
        print(f"\nSample article:")
        if cache["articles"]:
            a = cache["articles"][0]
            print(f"  [{a['team_id']}] {a['title']}")
            print(f"  Impact: {a['impact']}")

    if "--projections" in sys.argv or len(sys.argv) == 1:
        cache = refresh_projections(season, week)
        sample = next(iter(cache["players"].values()), None)
        if sample:
            print(f"\nSample projection: {sample['name']} ({sample['team']}) — {sample['points_ppr']} PPR pts")
