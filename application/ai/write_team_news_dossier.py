"""
Team News Dossier — the AI news-sheet writer (§2 news pipeline Stage B).

Distills the raw article store (Stage A, `team_news_raw`) into a compact, situation/security-focused
"news sheet" per NFL team-week: a set of scope-tagged claims (player / position_group / unit),
clustered across the three sources, that a downstream model reads next to the numerical analytics.
Written to `derived`-style `news/team_news_dossier` via Claude Haiku — never the raw articles.

Reuse, not rebuild:
  - `ai/client.generate_claims` — the isolation seam (key gate + the single synchronous call).
  - `fetchers/news.build_index` / `resolve_players` / `_TEAM_ALIASES` — the RETAINED resolver that
    attaches `sleeper_player_id` to player-scope claims DETERMINISTICALLY (the AI never emits ids;
    an ambiguous/unresolvable subject keeps the claim with a null id — law 2, never guess).
  - `fetchers/news._nfl_state` — the (season, week) key, same as collection.

Opt-in and API-key-gated; synchronous sequential calls (one per team). A team-week with no recent
fantasy-relevant news gets one explicit `is_empty` row. Run-once-per (season, week); `--force` to
regenerate. The writer replaces only the team-weeks it produced, so `--team KC` is a safe partial run.

Usage:
    python -m application.ai.write_team_news_dossier [--season 2026] [--week 0] [--team KC] [--force]
"""

import argparse
from datetime import datetime, timedelta, timezone

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.ai import client
from application.ai import news_prompt as np

# Windowing — a weekly extraction reads only the recent slice of the growing store (which reaches
# back years for some feeds), capped so one team's payload stays a sane single call.
WINDOW_DAYS = 14
MAX_ARTICLES_PER_TEAM = 60

# Haiku 4.5 pricing ($ per 1M tokens) — for the cost summary line only.
_IN_RATE, _OUT_RATE = 1.0, 5.0

_SCHEMA = {
    "season": pl.Int64, "week": pl.Int64, "team": pl.Utf8,
    "scope": pl.Utf8, "subject": pl.Utf8, "claim_type": pl.Utf8, "basis": pl.Utf8, "note": pl.Utf8,
    "direction": pl.Utf8, "salience": pl.Utf8,
    "sleeper_player_id": pl.Utf8, "resolved_name": pl.Utf8, "match_confidence": pl.Utf8,
    "source_article_ids": pl.List(pl.Utf8), "source_types": pl.List(pl.Utf8), "n_sources": pl.Int64,
    "model": pl.Utf8, "generated_at": pl.Utf8, "is_empty": pl.Boolean,
}
_TEAMS = tuple(t[0] for t in news._TEAM_SITES)


def _window_articles(team: str, season: int, now: datetime) -> list[dict]:
    """The recent, capped article window for one team: published within WINDOW_DAYS, newest first."""
    if not data_layer.team_news_raw_exists():
        return []
    df = data_layer.read_team_news_raw(team=team, season=season)
    if df.is_empty():
        return []
    cutoff = (now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    df = df.filter(pl.col("published_at").str.slice(0, 10) >= cutoff)
    df = df.sort("published_at", descending=True).head(MAX_ARTICLES_PER_TEAM)
    return df.select("article_id", "source_type", "published_at", "title", "content").to_dicts()


def _empty_row(team, season, week, generated_at, model, note) -> dict:
    """A single explicit 'no news' row (is_empty) so a quiet team-week is visible, not missing."""
    return {
        "season": season, "week": week, "team": team,
        "scope": None, "subject": None, "claim_type": None, "basis": None, "note": note,
        "direction": None, "salience": None,
        "sleeper_player_id": None, "resolved_name": None, "match_confidence": None,
        "source_article_ids": [], "source_types": [], "n_sources": 0,
        "model": model, "generated_at": generated_at, "is_empty": True,
    }


def _valid_claim(c: dict) -> bool:
    """Structural + enum validation of one model-emitted claim (a bad claim is dropped, not fatal)."""
    if not isinstance(c, dict) or not all(k in c for k in np.CLAIM_KEYS):
        return False
    if c["scope"] not in np.SCOPES or c["claim_type"] not in np.CLAIM_TYPES:
        return False
    if c["basis"] not in np.BASES:
        return False
    if c["direction"] not in np.DIRECTIONS or c["salience"] not in np.SALIENCES:
        return False
    if not str(c.get("subject", "")).strip() or not str(c.get("note", "")).strip():
        return False
    return isinstance(c.get("source_article_ids"), list)


def _team_index(index: dict, team: str) -> dict:
    """The resolver index restricted to skill players CURRENTLY ON `team`.

    Resolving a team sheet against this (not the league-wide index) guarantees an id only attaches
    to a player actually on that team — a player-scope claim naming an opponent / former player /
    another team's guy resolves to nothing (null id), never a cross-team id.
    """
    out: dict[str, list] = {}
    for key, cands in index.items():
        on = [c for c in cands if c.get("team") == team]
        if on:
            out[key] = on
    return out


def _resolve_player(subject: str, team_index: dict):
    """(sleeper_player_id, resolved_name, match_confidence) for a player-scope subject, else Nones.

    Reuses the retained resolver against the TEAM-restricted index, so only an on-team skill player
    resolves; an off-team or unknown name → null id (never guessed — law 2).
    """
    hits = news.resolve_players(subject, team_index)
    if len(hits) == 1:
        h = hits[0]
        return h["sleeper_player_id"], h["player_name"], h["match_confidence"]
    return None, None, None


def build_team_rows(team, articles, index, season, week, generated_at, *, model):
    """Return (rows, usage_or_None) for one team. No articles → one empty row (no API call).

    The only side effect is the single `client.generate_claims` call (skipped for a quiet team).
    Claims are validated, their cited ids grounded against the window (hallucinated ids dropped), and
    player subjects resolved to ids deterministically. A team whose claims all fail → one empty row.
    """
    if not articles:
        return [_empty_row(team, season, week, generated_at, None,
                           "No recent articles in the window.")], None

    claims, usage = client.generate_claims(np.system_prompt(), np.user_prompt(team, articles),
                                           model=model)
    win_ids = {a["article_id"]: a["source_type"] for a in articles}
    tindex = _team_index(index, team)

    rows = []
    for c in claims:
        if not _valid_claim(c):
            continue
        cited = [i for i in c["source_article_ids"] if i in win_ids]   # ground: drop unknown ids
        if not cited:
            continue
        source_types = sorted({win_ids[i] for i in cited})
        pid, rname, conf = (None, None, None)
        if c["scope"] == "player":
            pid, rname, conf = _resolve_player(c["subject"], tindex)
        rows.append({
            "season": season, "week": week, "team": team,
            "scope": c["scope"], "subject": str(c["subject"]).strip(),
            "claim_type": c["claim_type"], "basis": c["basis"], "note": str(c["note"]).strip(),
            "direction": c["direction"], "salience": c["salience"],
            "sleeper_player_id": pid, "resolved_name": rname, "match_confidence": conf,
            "source_article_ids": cited, "source_types": source_types, "n_sources": len(source_types),
            "model": model, "generated_at": generated_at, "is_empty": False,
        })

    if not rows:
        rows = [_empty_row(team, season, week, generated_at, model,
                           "No fantasy-relevant news in the window.")]
    return rows, usage


def compute(season: int, week: int, teams, *, model: str = client.DEFAULT_MODEL) -> pl.DataFrame:
    index = news.build_index()
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat(timespec="seconds")
    print(f"=== Team news dossier: season={season} week={week}  model={model}  "
          f"teams={len(teams)}  window={WINDOW_DAYS}d ===")

    rows, tot_in, tot_out, n_api = [], 0, 0, 0
    for team in teams:
        arts = _window_articles(team, season, now)
        trows, usage = build_team_rows(team, arts, index, season, week, generated_at, model=model)
        rows.extend(trows)
        n_claims = sum(1 for r in trows if not r["is_empty"])
        n_pid = sum(1 for r in trows if r["sleeper_player_id"])
        tag = "empty" if (len(trows) == 1 and trows[0]["is_empty"]) else f"{n_claims} claims ({n_pid} pid)"
        print(f"  {team:<4} {len(arts):>3} articles  ->  {tag}")
        if usage:
            tot_in += usage["input_tokens"]
            tot_out += usage["output_tokens"]
            n_api += 1

    cost = tot_in / 1e6 * _IN_RATE + tot_out / 1e6 * _OUT_RATE
    print(f"  {n_api} API call(s); {tot_in} in / {tot_out} out tokens  ~= ${cost:.3f}")
    return pl.DataFrame(rows, schema_overrides=_SCHEMA)


def run(season: int, week: int, *, teams=None, force: bool = False,
        model: str = client.DEFAULT_MODEL) -> None:
    if not client.api_available():
        print("Team news dossier: LOCKED — set a real config.ANTHROPIC_API_KEY to enable this opt-in "
              "AI read. Nothing written.")
        return
    teams = teams or _TEAMS
    existing = (data_layer.read_team_news_dossier(season=season, week=week)
                if data_layer.team_news_dossier_exists() else pl.DataFrame())
    present = set(existing["team"].to_list()) if existing.height else set()
    if not force and present.issuperset(set(teams)):
        print(f"Team news dossier for season={season} week={week} already covers these teams — "
              f"run once per week. Use --force to regenerate.")
        return
    df = compute(season, week, teams, model=model)
    data_layer.write_team_news_dossier(df)
    print(f"  -> snapshots/news/team_news_dossier.parquet  (+{df.height} rows for {len(teams)} team(s))")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Write weekly per-team AI news sheets (§2 Stage B).")
    parser.add_argument("--season", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--week", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--team", default=None, help="limit to one team abbr (e.g. KC) for a verify run")
    parser.add_argument("--force", action="store_true", help="regenerate even if the week exists")
    parser.add_argument("--model", default=client.DEFAULT_MODEL)
    args = parser.parse_args()

    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    teams = (args.team,) if args.team else None
    run(season, week, teams=teams, force=args.force, model=args.model)
