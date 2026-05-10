#!/usr/bin/env python3
"""
Run all playlist downloads from playlists.json, retrying automatically on IP blocks.

Usage:
    caffeinate python3 run_all.py
    caffeinate python3 run_all.py --cookies-from-browser chrome
    caffeinate python3 run_all.py --delay 2.0 --retry-wait 2.0
"""
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "playlists.json"
LOG_FILE = BASE_DIR / "run_all.log"

# Default hours to wait before retrying after an IP block
DEFAULT_RETRY_WAIT_HOURS = 2.0


def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_urls(playlist):
    """Support 'url' as a string or list, and 'urls' as a list."""
    raw = playlist.get("urls") or playlist.get("url") or []
    if isinstance(raw, str):
        raw = [raw]
    return [u for u in raw if u.strip()]


def load_playlists():
    with open(CONFIG_FILE) as f:
        playlists = json.load(f)
    # Filter out entries with no URLs set
    return [p for p in playlists if get_urls(p)]


def is_complete(playlist, overwrite=False):
    """A playlist is considered complete if its output folder has at least one .txt file and no IP block is pending."""
    if overwrite:
        return False
    output_path = BASE_DIR / playlist["output"]
    return output_path.exists() and any(output_path.glob("*.txt"))


def run_all(cookiesfrombrowser=None, delay=3.0, retry_wait_hours=DEFAULT_RETRY_WAIT_HOURS, overwrite=False, language="en"):
    from transcripts.temp_work.download_transcripts import download_playlist_transcripts

    playlists = load_playlists()
    if not playlists:
        log("No playlists with URLs found in playlists.json. Add URLs and re-run.")
        return

    log(f"Starting run — {len(playlists)} playlist(s) to process.")
    if cookiesfrombrowser:
        log(f"Using cookies from: {cookiesfrombrowser}")

    # Track which playlists still need work (index into list)
    pending = list(range(len(playlists)))

    while pending:
        still_pending = []

        for idx in pending:
            playlist = playlists[idx]
            name = playlist["name"]
            urls = get_urls(playlist)
            output_dir = str(BASE_DIR / playlist["output"])

            log(f"--- {name} ({len(urls)} playlist(s)) ---")

            ip_blocked = False
            totals = {"saved": 0, "skipped": 0, "already_done": 0}

            for url in urls:
                log(f"  URL: {url}")
                result = download_playlist_transcripts(
                    playlist_url=url,
                    output_dir=output_dir,
                    overwrite=overwrite,
                    language=language,
                    delay=delay,
                    cookiesfrombrowser=cookiesfrombrowser,
                )

                if result is None:
                    log(f"  SKIP: could not fetch playlist metadata.")
                    continue

                totals["saved"] += result["saved"]
                totals["skipped"] += result["skipped"]
                totals["already_done"] += result["already_done"]

                if result["ip_blocked"]:
                    ip_blocked = True
                    break

            if ip_blocked:
                log(f"IP blocked during '{name}'. Will retry all remaining playlists after {retry_wait_hours}h.")
                still_pending.append(idx)
                remaining = [i for i in pending if i not in still_pending and i != idx]
                still_pending.extend(remaining)
                break
            else:
                log(f"Finished '{name}': {totals['saved']} saved, {totals['skipped']} skipped, {totals['already_done']} already existed.")

        pending = still_pending

        if pending:
            retry_at = datetime.now() + timedelta(hours=retry_wait_hours)
            log(f"Waiting {retry_wait_hours}h before retry. Will resume at {retry_at.strftime('%H:%M:%S')}.")
            log(f"Playlists still pending: {[playlists[i]['name'] for i in pending]}")
            time.sleep(retry_wait_hours * 3600)
            log("Resuming after wait...")

    log("All playlists done.")


def main():
    parser = argparse.ArgumentParser(description="Download transcripts for all playlists in playlists.json.")
    parser.add_argument(
        "--cookies-from-browser",
        dest="cookiesfrombrowser",
        metavar="BROWSER",
        help="Load YouTube cookies from browser (chrome, firefox, safari, edge, brave)",
    )
    parser.add_argument("--delay", type=float, default=10.0, help="Seconds between transcript fetches (default: 3.0)")
    parser.add_argument("--retry-wait", type=float, default=DEFAULT_RETRY_WAIT_HOURS, dest="retry_wait_hours",
                        help=f"Hours to wait before retrying after an IP block (default: {DEFAULT_RETRY_WAIT_HOURS})")
    parser.add_argument("--overwrite", action="store_true", help="Re-download and overwrite existing files")
    parser.add_argument("--language", default="en", help="Preferred transcript language (default: en)")
    args = parser.parse_args()

    run_all(
        cookiesfrombrowser=args.cookiesfrombrowser,
        delay=args.delay,
        retry_wait_hours=args.retry_wait_hours,
        overwrite=args.overwrite,
        language=args.language,
    )


if __name__ == "__main__":
    main()
