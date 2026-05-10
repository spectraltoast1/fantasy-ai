#!/usr/bin/env python3
import argparse
import re
import time
from pathlib import Path

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript, IpBlocked


def load_browser_cookies(browser):
    import browser_cookie3
    loaders = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "safari": browser_cookie3.safari,
        "edge": browser_cookie3.edge,
        "brave": browser_cookie3.brave,
    }
    loader = loaders.get(browser.lower())
    if not loader:
        raise ValueError(f"Unsupported browser '{browser}'. Choose from: {', '.join(loaders)}")
    return loader(domain_name=".youtube.com")


def get_playlist_videos(playlist_url, cookiesfrombrowser=None):
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    if cookiesfrombrowser:
        ydl_opts["cookiesfrombrowser"] = (cookiesfrombrowser,)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    entries = info.get("entries") or []
    return [
        {"video_id": e["id"], "title": e.get("title", e["id"])}
        for e in entries
        if e and e.get("id")
    ]


def sanitize_filename(title):
    safe = re.sub(r'[/\\:*?"<>|]', "-", title)
    safe = safe.strip(". ")
    safe = re.sub(r"\s+", " ", safe)
    return safe[:200]


def make_session(cookiesfrombrowser=None):
    session = requests.Session()
    if cookiesfrombrowser:
        cookies = load_browser_cookies(cookiesfrombrowser)
        session.cookies.update(cookies)
    return session


class IpBlockedError(Exception):
    pass


def fetch_transcript(video_id, language="en", session=None):
    api = YouTubeTranscriptApi(http_client=session) if session else YouTubeTranscriptApi()
    for attempt in range(2):
        try:
            fetched = api.fetch(video_id, languages=[language])
            return " ".join(e.text for e in fetched)
        except IpBlocked:
            raise IpBlockedError("YouTube is blocking requests from this IP address.")
        except CouldNotRetrieveTranscript:
            return None
        except Exception as e:
            if attempt == 0:
                time.sleep(2)
            else:
                print(f"  WARNING: {e}")
                return None


def save_transcript(text, title, output_dir):
    filename = sanitize_filename(title) + ".txt"
    filepath = Path(output_dir) / filename
    filepath.write_text(f"Title: {title}\n\n{text}\n", encoding="utf-8")
    return filepath


def download_playlist_transcripts(playlist_url, output_dir, overwrite=False, language="en", delay=0.5, cookiesfrombrowser=None):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    session = None
    if cookiesfrombrowser:
        print(f"Loading YouTube cookies from {cookiesfrombrowser}...")
        try:
            session = make_session(cookiesfrombrowser)
            print("Cookies loaded.\n")
        except Exception as e:
            print(f"WARNING: Could not load cookies — {e}\n")

    print("Fetching playlist metadata...")
    try:
        videos = get_playlist_videos(playlist_url, cookiesfrombrowser=cookiesfrombrowser)
    except yt_dlp.utils.DownloadError as e:
        print(f"ERROR: Could not fetch playlist — {e}")
        return

    total = len(videos)
    print(f"Found {total} videos.\n")

    skipped, saved, already_done = 0, 0, 0

    for i, video in enumerate(videos, 1):
        title = video["title"]
        video_id = video["video_id"]
        prefix = f"[{i}/{total}]"

        dest = output_path / (sanitize_filename(title) + ".txt")
        if dest.exists() and not overwrite:
            print(f"{prefix} SKIP (exists): {title}")
            already_done += 1
            continue

        print(f"{prefix} Processing: {title}")
        try:
            text = fetch_transcript(video_id, language=language, session=session)
        except IpBlockedError as e:
            print(f"\nERROR: {e}")
            print("Your IP has been temporarily blocked by YouTube. Wait a few hours and try again.")
            print(f"Progress: {saved} saved so far. Re-run the same command to resume (already-saved files will be skipped).")
            return {"saved": saved, "skipped": skipped, "already_done": already_done, "ip_blocked": True}

        if text is None:
            print(f"  SKIP: no transcript available")
            skipped += 1
        else:
            save_transcript(text, title, output_dir)
            print(f"  Saved: {dest.name}")
            saved += 1

        if i < total:
            time.sleep(delay)

    print(f"\nDone. {saved} saved, {skipped} skipped (no transcript), {already_done} already existed.")
    return {"saved": saved, "skipped": skipped, "already_done": already_done, "ip_blocked": False}


def main():
    parser = argparse.ArgumentParser(description="Download transcripts from a YouTube playlist.")
    parser.add_argument("--url", required=True, help="YouTube playlist URL")
    parser.add_argument("--output", required=True, help="Output directory for transcript files")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing transcript files")
    parser.add_argument("--language", default="en", help="Preferred transcript language code (default: en)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between API calls (default: 0.5)")
    parser.add_argument(
        "--cookies-from-browser",
        dest="cookiesfrombrowser",
        metavar="BROWSER",
        help="Load YouTube cookies from browser to bypass rate limits (chrome, firefox, safari, edge, brave)",
    )
    args = parser.parse_args()

    download_playlist_transcripts(
        playlist_url=args.url,
        output_dir=args.output,
        overwrite=args.overwrite,
        language=args.language,
        delay=args.delay,
        cookiesfrombrowser=args.cookiesfrombrowser,
    )


if __name__ == "__main__":
    main()
