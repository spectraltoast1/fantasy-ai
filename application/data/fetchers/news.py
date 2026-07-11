"""
Player-news collector — the aggregation half of the §2 ROS AI-interpretation layer.

DECISION_READS.md §2's AI layer needs a news feed, and none was fetched anywhere. This is
the collector: a live, scheduled RSS snapshot fetcher that banks current NFL player news as a
de-duplicated, player-resolved, source-attributed time-series. The on-demand AI synthesis that
turns this into consolidated headlines + a bull/bear blurb is a LATER build; this module only
collects (design record: project_management/LLM context/STATUS.md).

Mirrors the leaguelogs collector: incremental per-feed persistence (a mid-run feed failure
leaves a recoverable partial), a dedup guard in the data_layer writer (idempotent re-runs), and
a launchd plist for the daily rhythm. Live-acquired like manager_activity — the FORWARD pipeline,
NOT tied to the frozen-2025 league; it resolves against whatever skill players are on an NFL
roster right now (team-not-null: 0 full-name collisions → a high-precision exact-match key).

Only the compact item is stored — headline, summary, url, provenance — never the article body:
url + collected_at are the recall path (Wayback) if a source must be re-read, and it sidesteps
copyright/ToS on article text.

Scope: QB/RB/WR/TE only (the V1 skill-position non-negotiable). Nationals-only source list for
now; team beats drop in later as source_type="beat" entries (no schema change). Type-1
aggregators are deliberately excluded — aggregating aggregators destroys the source independence
the corroboration design rests on.

Usage:
    python -m application.data.fetchers.news snapshot       # fetch every feed + persist
    python -m application.data.fetchers.news feeds          # list the configured registry
    python -m application.data.fetchers.news resolve-test   # dry-run: parse + resolve, no write
"""

import argparse
import hashlib
import html
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import polars as pl
import requests

from application.data import data_layer
from application.data.fetchers import sleeper

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# National, team-neutral NFL feeds (source_type="national"). Team beats (source_type="beat")
# drop in later. Validated for parse + resolution during the build; dead/thin feeds are pruned.
_FEEDS = (
    {"key": "espn_nfl",  "source_type": "national", "url": "https://www.espn.com/espn/rss/nfl/news"},
    {"key": "cbs_nfl",   "source_type": "national", "url": "https://www.cbssports.com/rss/headlines/nfl/"},
    {"key": "yahoo_nfl", "source_type": "national", "url": "https://sports.yahoo.com/nfl/rss/"},
    {"key": "pft_nbc",   "source_type": "national", "url": "https://profootballtalk.nbcsports.com/feed/"},
    {"key": "pfrumors",  "source_type": "national", "url": "https://www.profootballrumors.com/feed/"},
)

_TIMEOUT = 20
_RETRIES = 3
_BACKOFF = 2.0
# A descriptive UA — several feeds 403 the default python-requests UA.
_UA = "fantasy-ai-news/1.0 (+https://github.com/fantasy-ai)"
_SUMMARY_LIMIT = 600           # store a compact summary, never the article body

# Pinned schema so the growing history file stays stable across runs.
_SCHEMA = {
    "item_id": pl.Utf8,             # sha1(url | player_id)[:16] — dedup / idempotency key
    "sleeper_player_id": pl.Utf8,
    "player_name": pl.Utf8,
    "source": pl.Utf8,              # feed key
    "source_type": pl.Utf8,         # national | beat
    "headline": pl.Utf8,
    "summary": pl.Utf8,
    "url": pl.Utf8,                 # provenance + Wayback recall anchor
    "published_at": pl.Utf8,        # from the feed (may be null / unreliable)
    "collected_at": pl.Utf8,        # our fetch timestamp (the Wayback anchor)
    "season": pl.Int64,             # nfl-state context at collection
    "week": pl.Int64,
    "match_confidence": pl.Utf8,    # exact_full | disambiguated
    "match_method": pl.Utf8,
}

_TAG_RE = re.compile(r"<[^>]+>")
_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


# --- HTTP + feed parsing ---

def _get_feed(url: str):
    """Fetch + parse one feed with a bounded timeout and backoff retry on transient errors.

    Returns a parsed feedparser result (entries in `.entries`) or raises the last error after
    exhausting retries — the caller isolates the failure so one dead feed can't kill the run.
    """
    last = None
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": _UA})
            resp.raise_for_status()
            return feedparser.parse(resp.content)
        except requests.RequestException as exc:
            last = exc
            if attempt < _RETRIES:
                time.sleep(_BACKOFF * attempt)
    raise last


def _clean(s: str, limit: int | None = None) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace; optionally truncate."""
    s = html.unescape(_TAG_RE.sub(" ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] if limit else s


def _entry_published(entry) -> str | None:
    """The feed's own publish time as an ISO string (UTC) when parseable, else the raw string."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
    return entry.get("published") or entry.get("updated") or None


# --- Player resolution (the accuracy core) ---

def _normalize(name: str) -> str:
    """Lowercase, drop punctuation and Jr/Sr/II-V suffixes, collapse whitespace.

    Both the registry names and the article text pass through this, so 'A.J. Brown',
    'Amon-Ra St. Brown', and "De'Von Achane" match their headline mentions.
    """
    s = name.lower()
    s = re.sub(r"[.'`\-]", "", s)          # O'Dell -> odell, A.J. -> aj, Amon-Ra -> amonra
    s = re.sub(r"[^a-z ]", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_index() -> dict:
    """name(normalized) -> [player rows] for CURRENT active skill players (on an NFL roster now).

    team-not-null gives 967 skill players with ZERO full-name collisions — the right universe for
    a live news feed and a high-precision exact-match key. A multi-word full name only matches when
    it appears whole, so last-name collisions never fire.
    """
    players = data_layer.read_sleeper_players().filter(
        pl.col("position").is_in(SKILL_POSITIONS) & pl.col("team").is_not_null()
    )
    index: dict[str, list] = {}
    for r in players.iter_rows(named=True):
        key = _normalize(r["full_name"])
        if key:
            index.setdefault(key, []).append(r)
    return index


# NFL team → lowercase alias substrings (city + nickname), for disambiguating the rare same-name
# collision. The current active universe has 0 collisions, but the registry mutates daily and two
# simultaneously-active skill players have shared a name before (the Michael Carter RB/WR pair), so
# this is defensive, not premature. Matched against RAW-lowercase text (keeps digits like "49ers"),
# separate from the digit-stripping name normalization. Shared-market teams (NY, LA) carry nickname
# only — the shared city can't disambiguate them, so a city-only mention stays ambiguous (skipped).
_TEAM_ALIASES = {
    "ARI": ("arizona", "cardinals"), "ATL": ("atlanta", "falcons"), "BAL": ("baltimore", "ravens"),
    "BUF": ("buffalo", "bills"), "CAR": ("carolina", "panthers"), "CHI": ("chicago", "bears"),
    "CIN": ("cincinnati", "bengals"), "CLE": ("cleveland", "browns"), "DAL": ("dallas", "cowboys"),
    "DEN": ("denver", "broncos"), "DET": ("detroit", "lions"), "GB": ("green bay", "packers"),
    "HOU": ("houston", "texans"), "IND": ("indianapolis", "colts"), "JAX": ("jacksonville", "jaguars"),
    "KC": ("kansas city", "chiefs"), "LV": ("las vegas", "raiders"), "LAC": ("chargers",),
    "LAR": ("rams",), "MIA": ("miami", "dolphins"), "MIN": ("minnesota", "vikings"),
    "NE": ("new england", "patriots"), "NO": ("new orleans", "saints"), "NYG": ("giants",),
    "NYJ": ("jets",), "PHI": ("philadelphia", "eagles"), "PIT": ("pittsburgh", "steelers"),
    "SF": ("san francisco", "49ers", "niners"), "SEA": ("seattle", "seahawks"),
    "TB": ("tampa bay", "buccaneers"), "TEN": ("tennessee", "titans"), "WAS": ("washington", "commanders"),
}


def _disambiguate(cands: list, text: str) -> dict | None:
    """Pick the colliding candidate whose NFL team is named in `text`; None if 0 or >1 teams
    match (never guess — law 2). Only reached when a name maps to >1 active player."""
    low = text.lower()
    matched = [c for c in cands if any(a in low for a in _TEAM_ALIASES.get(c["team"], ()))]
    return matched[0] if len(matched) == 1 else None


def resolve_players(text: str, index: dict) -> list[dict]:
    """Every current skill player named (full name, whole-token) in `text` = headline + summary.

    A name mapping to exactly one active player → `exact_full` (the case in the 0-collision current
    universe). A name mapping to >1 active player is resolved by a team mention → `disambiguated`,
    or skipped when no single team is named (never guessed — law 2). Returns
    [{sleeper_player_id, player_name, match_confidence, match_method}].
    """
    norm = f" {_normalize(text)} "
    hits = []
    for key, cands in index.items():
        if f" {key} " not in norm:
            continue
        if len(cands) == 1:
            picked, conf, method = cands[0], "exact_full", "full_name"
        else:
            picked = _disambiguate(cands, text)
            if picked is None:                        # ambiguous → skip, never guess
                continue
            conf, method = "disambiguated", "full_name+team"
        hits.append({
            "sleeper_player_id": picked["sleeper_player_id"],
            "player_name": picked["full_name"],
            "match_confidence": conf,
            "match_method": method,
        })
    return hits


# --- Row assembly ---

def _entry_rows(entry, feed: dict, index: dict, ctx: dict) -> list[dict]:
    """Zero or more (item × player) rows for one feed entry — one per resolved skill player."""
    url = (entry.get("link") or "").strip()
    headline = _clean(entry.get("title") or "")
    if not url or not headline:
        return []
    summary = _clean(entry.get("summary") or entry.get("description") or "", _SUMMARY_LIMIT)
    published = _entry_published(entry)
    rows = []
    for hit in resolve_players(f"{headline}. {summary}", index):
        item_id = hashlib.sha1(f"{url}|{hit['sleeper_player_id']}".encode()).hexdigest()[:16]
        rows.append({
            "item_id": item_id,
            "sleeper_player_id": hit["sleeper_player_id"],
            "player_name": hit["player_name"],
            "source": feed["key"],
            "source_type": feed["source_type"],
            "headline": headline,
            "summary": summary,
            "url": url,
            "published_at": published,
            "collected_at": ctx["collected_at"],
            "season": ctx["season"],
            "week": ctx["week"],
            "match_confidence": hit["match_confidence"],
            "match_method": hit["match_method"],
        })
    return rows


def _nfl_state() -> tuple[int, int]:
    """(season, current week) from Sleeper's nfl-state (reuses sleeper's retry-wrapped HTTP)."""
    state = sleeper._get_nfl_state()
    return int(state["season"]), int(state.get("week") or state.get("leg") or 0)


# --- The run ---

def snapshot(*, dry_run: bool = False) -> None:
    """Fetch every feed, resolve players, and (unless dry_run) persist incrementally per feed.

    Per-feed isolation: a dead / blocked feed is logged and skipped — it never aborts the run.
    Incremental write: each feed's new rows are persisted right after it's processed, so a later
    feed's failure can't discard feeds already collected. The data_layer writer dedups by item_id,
    so cross-feed reprints of the same article collapse and a re-run adds nothing.
    """
    index = build_index()
    season, week = _nfl_state()
    ctx = {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season,
        "week": week,
    }
    mode = "resolve-test (dry-run, no write)" if dry_run else "snapshot"
    print(f"News {mode} {ctx['collected_at']} (season={season}, week={week}) — "
          f"{len(_FEEDS)} feed(s); index = {sum(len(v) for v in index.values())} active skill players")

    total_entries, failed = 0, 0
    collected: list[dict] = []
    for feed in _FEEDS:
        try:
            parsed = _get_feed(feed["url"])
        except Exception as exc:                       # noqa: BLE001 — isolate any feed failure
            failed += 1
            print(f"  [{feed['key']:<9}] FAILED: {type(exc).__name__}: {exc} — skipped")
            continue
        feed_rows = []
        for entry in parsed.entries:
            feed_rows.extend(_entry_rows(entry, feed, index, ctx))
        total_entries += len(parsed.entries)
        collected.extend(feed_rows)
        n_items = len({r["url"] for r in feed_rows})
        print(f"  [{feed['key']:<9}] {len(parsed.entries):>3} entries → {n_items:>3} "
              f"player-relevant items, {len(feed_rows):>3} rows")
        if not dry_run and feed_rows:
            data_layer.write_player_news(pl.DataFrame(feed_rows, schema_overrides=_SCHEMA))
        time.sleep(0.3)                                # be polite between feeds

    ok = len(_FEEDS) - failed
    total_items = len({r["url"] for r in collected})   # union — an article in 2 feeds counts once
    print(f"  {ok}/{len(_FEEDS)} feeds ok; {total_entries} entries → {total_items} items, "
          f"{len(collected)} (item×player) rows"
          + ("" if dry_run else " persisted (new-only, idempotent)"))
    if dry_run:
        _report_resolution(collected)


def _report_resolution(rows: list[dict]) -> None:
    """Dry-run QA: confidence breakdown + the full resolved (player ⟵ headline) list to eyeball."""
    from collections import Counter
    conf = Counter(r["match_confidence"] for r in rows)
    print("  match_confidence: " + (", ".join(f"{k}={v}" for k, v in conf.items()) or "none"))
    print("  resolved matches (eyeball for false positives):")
    for r in sorted(rows, key=lambda r: (r["source"], r["player_name"])):
        print(f"    [{r['source']:<9}] {r['player_name']:<22} ⟵ {r['headline'][:70]}")


def check() -> bool:
    """Credit-free synthetic self-check of the resolver (registry-independent): exact match,
    non-match, same-name collision resolved by team, and collision-without-cue skipped."""
    idx = {
        _normalize("Josh Allen"): [
            {"sleeper_player_id": "1", "full_name": "Josh Allen", "position": "QB", "team": "BUF"}],
        _normalize("Michael Carter"): [
            {"sleeper_player_id": "2", "full_name": "Michael Carter", "position": "RB", "team": "NYJ"},
            {"sleeper_player_id": "3", "full_name": "Michael Carter", "position": "WR", "team": "ARI"}],
    }
    r_exact = resolve_players("Bills QB Josh Allen throws 3 TDs", idx)
    r_none = resolve_players("The Chiefs beat the Raiders", idx)
    r_disamb = resolve_players("Cardinals WR Michael Carter impresses in camp", idx)
    r_ambig = resolve_players("Michael Carter had a strong week", idx)
    checks = [
        ("exact_full", len(r_exact) == 1 and r_exact[0]["sleeper_player_id"] == "1"
            and r_exact[0]["match_confidence"] == "exact_full"),
        ("non_match", r_none == []),
        ("disambiguated", len(r_disamb) == 1 and r_disamb[0]["sleeper_player_id"] == "3"
            and r_disamb[0]["match_confidence"] == "disambiguated"),
        ("ambiguous_skip", r_ambig == []),
    ]
    for name, passed in checks:
        print(f"  {name:<16} {'PASS' if passed else 'FAIL'}")
    ok = all(p for _, p in checks)
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Player-news RSS collector (§2 aggregation half).")
    parser.add_argument("command", nargs="?", default="snapshot",
                        choices=["snapshot", "feeds", "resolve-test", "check"])
    args = parser.parse_args()

    if args.command == "feeds":
        for f in _FEEDS:
            print(f"  {f['key']:<9} [{f['source_type']}]  {f['url']}")
    elif args.command == "resolve-test":
        snapshot(dry_run=True)
    elif args.command == "check":
        sys.exit(0 if check() else 1)
    else:
        snapshot()


if __name__ == "__main__":
    main()
