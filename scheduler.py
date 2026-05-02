import argparse
import schedule
import time
from datetime import datetime

from sleeper import get_players, get_nfl_state
from nfl_stats import refresh_nfl_stats
from odds import refresh_odds


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


def run_daemon():
    schedule.every().day.at("04:00").do(job_players)
    schedule.every().tuesday.at("06:00").do(job_nfl_stats)
    schedule.every().wednesday.at("07:00").do(job_odds)

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
