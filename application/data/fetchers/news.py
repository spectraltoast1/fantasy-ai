"""
Team-news collector — Stage A of the §2 ROS AI-interpretation news pipeline.

The §2 layer needs a news feed. This collector banks per-NFL-team article coverage from three
NATIVE RSS sources per team — SB Nation (grounded analysis), FanSided (player/fantasy-flavored,
noisier), and the official team site (authoritative team-intent, PR-heavy) — into a raw article
store the weekly AI extraction step (Stage B) distills into tagged claims, which a per-player
slice (Stage C) then inherits. This module only COLLECTS.

Why per-team (not national): source investigation settled that the national desks (ESPN/CBS/Yahoo)
publish league-level feeds, not team-level, so they don't serve a per-team design; SI/FanNation
has no usable native RSS (ruled out, tested). SB Nation + FanSided are the two viable independent-
blog networks (team-by-team, native RSS); the official site is the authoritative-but-PR third.
`source_type` is stored per article so the downstream synthesis can weight the sources and treat
their agreement as corroboration. 3 feeds/team → one source going quiet degrades, not breaks.

Why store the article CONTENT (unlike the v1 player-news collector, which kept headlines only):
the weekly extraction needs the text. Feed-provided content only — no scraping; the product
surfaces derived claims + a link, and raw content is prunable after the extraction window.

Mirrors the leaguelogs collector: `_get_feed` timeout + backoff, per-feed isolation (one dead feed
never kills the run), incremental per-feed persistence, dedup guard in the data_layer writer
(append-only-of-new by article_id → idempotent re-runs). Live-acquired forward pipeline.

Player resolution has moved OUT of collection (into Stage B extraction + Stage C slice); the
resolver here (`build_index` / `resolve_players`) is RETAINED for those stages to import.

Usage:
    python3 -m application.data.fetchers.news snapshot [--team KC]   # fetch team feeds + persist
    python3 -m application.data.fetchers.news feeds                  # list the team registry
    python3 -m application.data.fetchers.news check                  # resolver self-check
"""

import argparse
import hashlib
import html
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import polars as pl
import requests

from application.data import data_layer
from application.data.fetchers import sleeper

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")

# Content retention (§2 Stage C): keep raw article `content` this long, then null it (the row/link
# survive). Must exceed the Stage-B synthesis window (WINDOW_DAYS=14) by a safe margin, so pruning
# can never null a body still inside an extraction window.
RETENTION_DAYS = 28

# --- Team feed registry: 3 native RSS sources per team, all 96 validated live ---
# (abbr, official_domain, sbnation_domain, fansided_domain). Feed URLs are built by _build_registry:
#   official → https://www.<domain>/rss/news   (NFL.com network, consistent)
#   SB Nation → https://www.<domain>/rss/index.xml
#   FanSided → https://<domain>/feed/
# National desks dropped (league-level). SI/FanNation ruled out (no native per-team RSS).
_TEAM_SITES = (
    ("ARI", "azcardinals.com",       "revengeofthebirds.com",    "raisingzona.com"),
    ("ATL", "atlantafalcons.com",    "thefalcoholic.com",        "bloggingdirty.com"),
    ("BAL", "baltimoreravens.com",   "baltimorebeatdown.com",    "ebonybird.com"),
    ("BUF", "buffalobills.com",      "buffalorumblings.com",     "buffalowdown.com"),
    ("CAR", "panthers.com",          "catscratchreader.com",     "catcrave.com"),
    ("CHI", "chicagobears.com",      "windycitygridiron.com",    "beargoggleson.com"),
    ("CIN", "bengals.com",           "cincyjungle.com",          "stripehype.com"),
    ("CLE", "clevelandbrowns.com",   "dawgsbynature.com",        "dawgpounddaily.com"),
    ("DAL", "dallascowboys.com",     "bloggingtheboys.com",      "thelandryhat.com"),
    ("DEN", "denverbroncos.com",     "milehighreport.com",       "predominantlyorange.com"),
    ("DET", "detroitlions.com",      "prideofdetroit.com",       "sidelionreport.com"),
    ("GB",  "packers.com",           "acmepackingcompany.com",   "lombardiave.com"),
    ("HOU", "houstontexans.com",     "battleredblog.com",        "torotimes.com"),
    ("IND", "colts.com",             "stampedeblue.com",         "horseshoeheroes.com"),
    ("JAX", "jaguars.com",           "bigcatcountry.com",        "blackandteal.com"),
    ("KC",  "chiefs.com",            "arrowheadpride.com",       "arrowheadaddict.com"),
    ("LV",  "raiders.com",           "silverandblackpride.com",  "justblogbaby.com"),
    ("LAC", "chargers.com",          "boltsfromtheblue.com",     "boltbeat.com"),
    ("LAR", "therams.com",           "turfshowtimes.com",        "ramblinfan.com"),
    ("MIA", "miamidolphins.com",     "thephinsider.com",         "phinphanatic.com"),
    ("MIN", "vikings.com",           "dailynorseman.com",        "thevikingage.com"),
    ("NE",  "patriots.com",          "patspulpit.com",           "musketfire.com"),
    ("NO",  "neworleanssaints.com",  "canalstreetchronicles.com","whodatdish.com"),
    ("NYG", "giants.com",            "bigblueview.com",          "gmenhq.com"),
    ("NYJ", "newyorkjets.com",       "ganggreennation.com",      "thejetpress.com"),
    ("PHI", "philadelphiaeagles.com","bleedinggreennation.com",  "insidetheiggles.com"),
    ("PIT", "steelers.com",          "behindthesteelcurtain.com","stillcurtain.com"),
    ("SF",  "49ers.com",             "ninersnation.com",         "ninernoise.com"),
    ("SEA", "seahawks.com",          "fieldgulls.com",           "12thmanrising.com"),
    ("TB",  "buccaneers.com",        "bucsnation.com",           "thepewterplank.com"),
    ("TEN", "tennesseetitans.com",   "musiccitymiracles.com",    "titansized.com"),
    ("WAS", "commanders.com",        "hogshaven.com",            "riggosrag.com"),
)


def _build_registry() -> tuple:
    """Flatten the team-site table into the feed list: {team, source_type, url} per feed."""
    feeds = []
    for abbr, off, sbn, fan in _TEAM_SITES:
        feeds.append({"team": abbr, "source_type": "team_official",      "url": f"https://www.{off}/rss/news"})
        feeds.append({"team": abbr, "source_type": "team_blog_sbn",      "url": f"https://www.{sbn}/rss/index.xml"})
        feeds.append({"team": abbr, "source_type": "team_blog_fansided", "url": f"https://{fan}/feed/"})
    return tuple(feeds)


_TEAM_FEEDS = _build_registry()

_TIMEOUT = 20
_RETRIES = 3
_BACKOFF = 2.0
# A descriptive UA — several feeds 403 the default python-requests UA.
_UA = "fantasy-ai-news/1.0 (+https://github.com/fantasy-ai)"
_CONTENT_LIMIT = 12000         # store the feed-provided article text, bounded (never scraped)

# Pinned schema so the growing store stays stable across runs.
_SCHEMA = {
    "article_id": pl.Utf8,          # sha1(url)[:16] — dedup / idempotency key
    "team": pl.Utf8,                # NFL team abbr (the feed's team)
    "source_type": pl.Utf8,         # team_official | team_blog_sbn | team_blog_fansided
    "title": pl.Utf8,
    "content": pl.Utf8,             # feed-provided article text (tag-stripped, bounded)
    "url": pl.Utf8,                 # provenance + recall link
    "published_at": pl.Utf8,        # from the feed (may be null)
    "collected_at": pl.Utf8,        # our fetch timestamp
    "season": pl.Int64,             # nfl-state context at collection
    "week": pl.Int64,
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


def _entry_content(entry) -> str:
    """The article text the feed provides — full `content:encoded` when present, else the summary.
    Tag-stripped and bounded. Feed-provided only; we never fetch the article page (no scraping)."""
    if entry.get("content"):
        raw = entry["content"][0].get("value", "")
    else:
        raw = entry.get("summary") or entry.get("description") or ""
    return _clean(raw, _CONTENT_LIMIT)


# --- Player resolution (RETAINED for Stage B extraction + Stage C slice; not used in collection) ---

def _normalize(name: str) -> str:
    """Lowercase, drop punctuation and Jr/Sr/II-V suffixes, collapse whitespace.

    Both the registry names and article text pass through this, so 'A.J. Brown',
    'Amon-Ra St. Brown', and "De'Von Achane" match their mentions.
    """
    s = name.lower()
    s = re.sub(r"[.'`\-]", "", s)          # O'Dell -> odell, A.J. -> aj, Amon-Ra -> amonra
    s = re.sub(r"[^a-z ]", " ", s)
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_index() -> dict:
    """name(normalized) -> [player rows] for CURRENT active skill players (on an NFL roster now).

    team-not-null gives ~967 skill players with ZERO full-name collisions — a high-precision
    exact-match key. Reused by the extraction step to resolve player-scoped claim subjects.
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
# collision. Matched against RAW-lowercase text (keeps digits like "49ers"), separate from the
# digit-stripping name normalization. Shared-market teams (NY, LA) carry nickname only.
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
    """Every current skill player named (full name, whole-token) in `text`.

    A name mapping to exactly one active player → `exact_full`; a name mapping to >1 is resolved by
    a team mention → `disambiguated`, else skipped (never guessed — law 2). Returns
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


# --- Article assembly ---

def _article_row(entry, feed: dict, ctx: dict) -> dict | None:
    """One raw-article row for a feed entry (team-tagged); None if it has no url/title."""
    url = (entry.get("link") or "").strip()
    title = _clean(entry.get("title") or "")
    if not url or not title:
        return None
    return {
        "article_id": hashlib.sha1(url.encode()).hexdigest()[:16],
        "team": feed["team"],
        "source_type": feed["source_type"],
        "title": title,
        "content": _entry_content(entry),
        "url": url,
        "published_at": _entry_published(entry),
        "collected_at": ctx["collected_at"],
        "season": ctx["season"],
        "week": ctx["week"],
    }


def _nfl_state() -> tuple[int, int]:
    """(season, current week) from Sleeper's nfl-state (reuses sleeper's retry-wrapped HTTP)."""
    state = sleeper._get_nfl_state()
    return int(state["season"]), int(state.get("week") or state.get("leg") or 0)


# --- The run ---

def snapshot(*, team_filter: str | None = None) -> None:
    """Fetch every team's feeds, persist raw articles incrementally per feed (idempotent).

    Per-feed isolation: a dead / blocked feed is logged and skipped — never aborts the run. Each
    feed's articles are persisted right after fetch (a later failure can't discard earlier feeds);
    the data_layer writer dedups by article_id, so re-polls add nothing. Reports per-team volume
    (feeds ok / articles / kchars) — the thinness-tripwire input (Stage C) — and flags teams that
    fell below the 2-of-3 resilience floor.
    """
    season, week = _nfl_state()
    ctx = {"collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "season": season, "week": week}
    feeds = [f for f in _TEAM_FEEDS if team_filter in (None, f["team"])]
    teams = sorted({f["team"] for f in feeds})
    print(f"News team-collection {ctx['collected_at']} (season={season}, week={week}) — "
          f"{len(feeds)} feeds across {len(teams)} team(s)")

    stat = {t: {"ok": 0, "articles": 0, "chars": 0} for t in teams}
    for feed in feeds:
        t = feed["team"]
        net = feed["source_type"].split("_")[-1]       # official / sbn / fansided
        try:
            parsed = _get_feed(feed["url"])
        except Exception as exc:                        # noqa: BLE001 — isolate any feed failure
            print(f"  [{t:<3} {net:<8}] FAILED: {type(exc).__name__} — {feed['url']}")
            continue
        rows = [r for r in (_article_row(e, feed, ctx) for e in parsed.entries) if r]
        stat[t]["ok"] += 1
        stat[t]["articles"] += len(rows)
        stat[t]["chars"] += sum(len(r["content"]) for r in rows)
        if rows:
            data_layer.write_team_news_raw(pl.DataFrame(rows, schema_overrides=_SCHEMA))
        time.sleep(0.2)                                 # be polite between feeds

    below = [t for t in teams if stat[t]["ok"] < 2]
    tot_ok = sum(stat[t]["ok"] for t in teams)
    tot_art = sum(stat[t]["articles"] for t in teams)
    for t in teams:
        s = stat[t]
        print(f"  {t:<4} {s['ok']}/3 feeds  {s['articles']:>4} articles  {s['chars'] // 1000:>4} kchars")
    store = data_layer.read_team_news_raw().height if data_layer.team_news_raw_exists() else 0
    print(f"  {tot_ok}/{len(feeds)} feeds ok; {len(teams)} teams; {tot_art} articles this run; "
          f"store now {store} rows")
    if below:
        print(f"  ⚠ BELOW RESILIENCE FLOOR (<2/3 feeds): {', '.join(below)}")


def prune(*, dry_run: bool = False) -> None:
    """Retention: null raw article `content` older than RETENTION_DAYS (keeps the row + link + claims).

    The store grows unbounded (daily append-only; the first run was a ~5k backfill reaching to 2018).
    Content is only extraction fuel inside the ~2-week window, so old bodies are pure weight. This
    computes the cutoff from RETENTION_DAYS and calls the data_layer pruner. `--dry-run` reports the
    numbers without writing — always eyeball those first (nulling content is irreversible).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).date().isoformat()
    rep = data_layer.prune_team_news_raw_content(cutoff, dry_run=dry_run)
    tag = "DRY-RUN" if dry_run else "LIVE"
    print(f"News content retention [{tag}] — cutoff {cutoff} (keep last {RETENTION_DAYS}d of content)")
    print(f"  store {rep['total']} rows; oldest {rep['oldest']}; {rep['eligible']} older than cutoff; "
          f"{rep['to_null']} with content to null (~{rep['chars_freed'] // 1000} kchars)")
    if dry_run:
        print("  (dry-run — nothing written; re-run without --dry-run to apply)")
    elif rep["written"]:
        print("  ✓ content nulled for pruned rows; article_id / title / url / published_at + the "
              "derived claims are kept")
    else:
        print("  nothing to prune")


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
    parser = argparse.ArgumentParser(description="Team-news RSS collector (§2 pipeline Stage A).")
    parser.add_argument("command", nargs="?", default="snapshot",
                        choices=["snapshot", "feeds", "check", "prune"])
    parser.add_argument("--team", default=None, help="limit snapshot to one team abbr (e.g. KC)")
    parser.add_argument("--dry-run", action="store_true",
                        help="prune: report what would be nulled without writing")
    args = parser.parse_args()

    if args.command == "feeds":
        for abbr, off, sbn, fan in _TEAM_SITES:
            print(f"  {abbr:<4} official=www.{off}/rss/news  sbn=www.{sbn}/rss/index.xml  "
                  f"fansided={fan}/feed/")
        print(f"  {len(_TEAM_FEEDS)} feeds across {len(_TEAM_SITES)} teams")
    elif args.command == "check":
        sys.exit(0 if check() else 1)
    elif args.command == "prune":
        prune(dry_run=args.dry_run)
    else:
        snapshot(team_filter=args.team)


if __name__ == "__main__":
    main()
