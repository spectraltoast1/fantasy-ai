import argparse
import schedule
import time
from datetime import datetime

from sleeper import get_players, get_nfl_state, get_sleeper_user, get_sleeper_league, get_free_agents
from nfl_stats import refresh_nfl_stats
from odds import refresh_odds
from fantasypros import refresh_news, refresh_projections
from weather import refresh_stadiums
from config import SLEEPER_USERNAME


def _current_season_year():
    state = get_nfl_state()
    return int(state.get("season", datetime.now().year))


def job_players():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing players.json...")
    get_players()
    print("  Done.")


def job_nfl_stats():
    year = _current_season_year()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing NFL stats for {year}...")
    refresh_nfl_stats(year)
    print("  Done.")


def job_odds():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing odds...")
    refresh_odds()
    print("  Done.")


def job_news():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing FantasyPros news...")
    refresh_news()
    print("  Done.")


def job_projections():
    state = get_nfl_state()
    season = state.get("season", str(datetime.now().year))
    week = state.get("week") or 1
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing projections ({season} week {week})...")
    refresh_projections(season, week)
    print("  Done.")


def job_stadiums():
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing stadium data...")
    refresh_stadiums()
    print("  Done.")


def job_free_agents():
    user = get_sleeper_user(SLEEPER_USERNAME)
    leagues = get_sleeper_league(user["user_id"])
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] Refreshing free agents for {len(leagues)} league(s)...")
    for league in leagues:
        fas = get_free_agents(league["league_id"])
        print(f"  {league['name']}: {len(fas)} free agents")
    print("  Done.")


def run_daemon():
    schedule.every().day.at("04:00").do(job_players)
    schedule.every().day.at("04:30").do(job_news)
    schedule.every().tuesday.at("06:00").do(job_nfl_stats)
    schedule.every().tuesday.at("06:30").do(job_projections)
    schedule.every().tuesday.at("07:00").do(job_free_agents)
    schedule.every().wednesday.at("07:00").do(job_odds)
    schedule.every(30).days.do(job_stadiums)  # stadium data rarely changes

    print("Scheduler running. Jobs scheduled:")
    for job in schedule.get_jobs():
        print(f"  {job}")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


_JOBS = {
    "players": job_players,
    "nfl_stats": job_nfl_stats,
    "odds": job_odds,
    "news": job_news,
    "projections": job_projections,
    "stadiums": job_stadiums,
    "free_agents": job_free_agents,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fantasy AI data scheduler")
    parser.add_argument(
        "--force-refresh",
        choices=list(_JOBS) + ["all"],
        metavar="{" + ",".join(list(_JOBS) + ["all"]) + "}",
        help="Run a specific refresh job immediately and exit.",
    )
    args = parser.parse_args()

    if args.force_refresh:
        targets = list(_JOBS.values()) if args.force_refresh == "all" else [_JOBS[args.force_refresh]]
        for job in targets:
            job()
    else:
        run_daemon()
