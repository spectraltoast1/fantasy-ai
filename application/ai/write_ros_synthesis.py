"""
ROS Synthesis — the per-player AI outcome-shape writer (§2 ROS Outcome Shape, interpretation half).

Fuses the quantitative skeleton (compute_ros_player_band + compute_ros_league_view — the L0 split of the
old ros_outcome_shape) with the news layer (player_news_slice) into the three §2 grades + narrative +
headlines + a confidence flag — the last mile the skeleton deferred ("the AI narrative + 1-10 grade
roll-up is Phase 6").

Reuse, not rebuild:
  - ai/client.generate_dossier — the isolation seam (key gate + the single synchronous call).
  - ai/ros_synthesis_prompt — the pure prompt (schema + guardrails + zero-signal fallback). The prompt
    TEXT you iterate on lives there; this file only gathers data and calls the model.
  - data_layer.read_ros_player_band ⋈ read_ros_league_view / read_player_news_slice /
    read_sleeper_players — the anchors. This writer is league-scoped (its grades depend on league-relative
    anchor inputs); the two ROS halves rejoin here into the same anchor the pre-split reader saw.

Graceful per-input degradation (design decision): a player is graded on WHATEVER resolves, and the
output makes the gaps first-class (has_ros_anchor / has_news / anchor_is_prior_season + a confidence
flag). Full set => fully-anchored grade; news only => news-led, confidence capped; anchor only =>
graded off the band; nothing => a hardcoded "insufficient data" row, the API skipped.

Season note: the output is keyed by the NEWS (season, week) = the current world; the ros anchor is a
by-id lookup from --anchor-season (the latest season with a band on disk). When they differ the anchor
is flagged PRIOR-SEASON, not silently fused (the STATUS "time-world caveat").

No-AI prompt iteration (self-serve, no Claude Code session, no cost, no key needed):
  --render  <players>            gather a player's real inputs and PRINT the exact system+user prompt
                                 that would be sent (no API call). The loop for tweaking the prompt text.
  --replay  <players> --reply F  feed a canned JSON reply (file F) through validation + row assembly
                                 (no API call) — test the parsing/guards.
Live:
  --preview <players>            gather + generate + PRINT the model output (real call).
  (default) <players>            gather + generate + WRITE the rows (real call, run-once-guarded).

Usage:
    python3 -m application.ai.write_ros_synthesis --render  --player 7564
    python3 -m application.ai.write_ros_synthesis --preview --player 9758,9228 --anchor-season 2025
    python3 -m application.ai.write_ros_synthesis --player 9758,9228 --anchor-season 2025      # write
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.ai import client
from application.ai import ros_synthesis_prompt as rp

# Haiku 4.5 pricing ($ per 1M tokens) — for the cost summary line only.
_IN_RATE, _OUT_RATE = 1.0, 5.0

# Claim fields carried from a player_news_slice row into the prompt context (+ inheritance/scope tags).
_CLAIM_FIELDS = ("inheritance", "scope", "subject", "claim_type", "basis", "note", "direction",
                 "salience", "source_article_ids")

# A headline is one struct {text, source_article_ids}; the grades are nullable (zero-signal rows). The
# explicit schema is needed so all-null / empty rows type correctly on write.
_HEADLINE_DT = pl.List(pl.Struct({"text": pl.Utf8, "source_article_ids": pl.List(pl.Utf8)}))
_SCHEMA = {
    "season": pl.Int64, "week": pl.Int64, "sleeper_player_id": pl.Utf8,
    "player_name": pl.Utf8, "team": pl.Utf8, "position": pl.Utf8,
    "bull_grade": pl.Int64, "bull_note": pl.Utf8,
    "bear_grade": pl.Int64, "bear_note": pl.Utf8,
    "situation_grade": pl.Int64, "situation_note": pl.Utf8,
    "headlines": _HEADLINE_DT, "confidence": pl.Utf8, "confidence_note": pl.Utf8,
    "signal_tier": pl.Utf8, "has_news": pl.Boolean, "has_ros_anchor": pl.Boolean,
    "has_sleeper_facts": pl.Boolean, "n_news_claims": pl.Int64,
    "ros_bull": pl.Float64, "ros_bear": pl.Float64, "ros_cv": pl.Float64,
    "spectrum_pos": pl.Float64, "security": pl.Utf8, "direction": pl.Utf8,
    "anchor_season": pl.Int64, "anchor_is_prior_season": pl.Boolean,
    "news_content_hash": pl.Utf8, "is_zero_signal": pl.Boolean,
    "model": pl.Utf8, "generated_at": pl.Utf8,
}


# --------------------------------------------------------------------------- inputs / assembly

def _resolve_anchor_season(season: int, anchor_season) -> int:
    """The season whose ROS band anchors the read (default: this season if present, else 2025)."""
    if anchor_season is not None:
        return anchor_season
    if data_layer.ros_player_band_exists(season):
        return season
    return 2025


def _read_anchor(anchor_season: int) -> pl.DataFrame:
    """The §2 quantitative anchor per player, at the latest as-of: ros_league_view (roster + spectrum /
    security / direction) joined to ros_player_band (centre / bull / bear / cv + preseason-ADP evidence)
    — the L0 split of the old ros_outcome_shape, rejoined. Rostered players only (the league view's
    grain), so has_ros_anchor keeps its pre-split meaning (only a rostered player carries an anchor)."""
    view = data_layer.read_ros_league_view(anchor_season)    # league-scoped (is_mine), latest as_of
    band = data_layer.read_ros_player_band(anchor_season)    # scoring-scoped (is_mine profile), latest as_of
    return view.join(
        band.select("sleeper_player_id", "ros_center", "ros_bull", "ros_bear", "ros_sigma", "ros_cv",
                    "n_weeks", "anchor_applied", "adp_ecr", "adp_best", "adp_worst",
                    "anchor_floor", "anchor_ceiling"),
        on="sleeper_player_id", how="left",
    )


def _load_inputs(season: int, week: int, anchor_season: int):
    """(news_slice df for the week, ros anchor by id, sleeper facts by id). Missing inputs degrade to empty."""
    news_slice = data_layer.read_player_news_slice(season=season, week=week) \
        if data_layer.player_news_slice_exists() else pl.DataFrame()
    try:
        ros = _read_anchor(anchor_season)                              # band ⋈ view, latest as_of_week
        ros = ros.unique(subset=["sleeper_player_id"], keep="first")   # one anchor per player
    except FileNotFoundError:
        ros = pl.DataFrame()
    facts = data_layer.read_sleeper_players() if data_layer.sleeper_players_exists() else pl.DataFrame()
    return news_slice, ros, facts


def _news_content_hash(claims: list[dict]) -> str:
    """Stable hash of a player's claim notes+ids — the seam for the future on-demand cache (not yet a trigger)."""
    payload = json.dumps([[c.get("note"), sorted(c.get("source_article_ids") or [])] for c in claims],
                         sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def assemble_player(pid: str, news_slice: pl.DataFrame, ros: pl.DataFrame,
                    facts: pl.DataFrame, *, season: int, week: int, anchor_season: int) -> dict:
    """Build the per-player context: identity + anchor + facts + claims + availability flags."""
    prows = news_slice.filter(pl.col("sleeper_player_id") == pid) if news_slice.height else pl.DataFrame()
    arow = ros.filter(pl.col("sleeper_player_id") == pid) if ros.height else pl.DataFrame()
    frow = facts.filter(pl.col("sleeper_player_id") == pid) if facts.height else pl.DataFrame()

    # Identity: prefer the news slice, fall back to the anchor / registry.
    ident = (prows.row(0, named=True) if prows.height
             else arow.row(0, named=True) if arow.height
             else frow.row(0, named=True) if frow.height else {})
    signal_tier = ident.get("signal_tier")
    team_news_volume = ident.get("team_news_volume")

    # Claims = the non-empty slice rows (an is_empty honest-zero row carries no claim).
    claims = []
    if prows.height and "is_empty" in prows.columns:
        for r in prows.filter(~pl.col("is_empty")).to_dicts():
            claims.append({k: r.get(k) for k in _CLAIM_FIELDS})
    elif prows.height:
        for r in prows.to_dicts():
            claims.append({k: r.get(k) for k in _CLAIM_FIELDS})

    anchor = arow.row(0, named=True) if arow.height else None
    fdict = frow.row(0, named=True) if frow.height else None

    return {
        "sleeper_player_id": pid,
        "player_name": ident.get("player_name") or (fdict or {}).get("full_name"),
        "position": ident.get("position") or (fdict or {}).get("position"),
        "team": ident.get("team") or (fdict or {}).get("team"),
        "season": season, "week": week,
        "anchor": anchor, "anchor_season": anchor_season,
        "anchor_is_prior_season": bool(anchor) and anchor_season != season,
        "facts": fdict,
        "claims": claims, "signal_tier": signal_tier, "team_news_volume": team_news_volume,
        # availability flags (first-class in the output)
        "has_ros_anchor": anchor is not None,
        "has_news": len(claims) > 0,
        "has_sleeper_facts": fdict is not None,
        "n_news_claims": len(claims),
    }


# --------------------------------------------------------------------------- validation / row build

def _validate(d: dict, slice_ids: set) -> None:
    """Structural + guardrail validation of a model reply (raises ValueError on a bad reply)."""
    missing = [k for k in rp.SYNTHESIS_KEYS if k not in d]
    if missing:
        raise ValueError(f"missing keys: {missing}")
    for k in rp.GRADE_KEYS:
        g = d[k]
        if not isinstance(g, int) or not (rp.GRADE_MIN <= g <= rp.GRADE_MAX):
            raise ValueError(f"{k}={g!r} not an int in [{rp.GRADE_MIN},{rp.GRADE_MAX}]")
    # bull / bear / situation are INDEPENDENT axes (a safe-but-capped player: high bear, modest bull),
    # so no cross-grade ordering is enforced.
    for k in rp.NOTE_KEYS:
        if not str(d.get(k, "")).strip():
            raise ValueError(f"{k} is empty")
    if d["confidence"] not in rp.CONFIDENCE:
        raise ValueError(f"confidence={d['confidence']!r} not in {rp.CONFIDENCE}")
    hs = d.get("headlines")
    if not isinstance(hs, list) or not hs:
        raise ValueError("headlines must be a non-empty array")
    for h in hs:
        if not isinstance(h, dict) or not str(h.get("text", "")).strip():
            raise ValueError(f"bad headline: {h!r}")
        ids = h.get("source_article_ids")
        if not isinstance(ids, list):
            raise ValueError(f"headline source_article_ids not a list: {h!r}")
        stray = [i for i in ids if i not in slice_ids]
        if stray:
            raise ValueError(f"headline cites ids not in the slice: {stray}")


def _row_from_reply(ctx: dict, ai: dict, generated_at: str, *, model, is_zero: bool) -> dict:
    """Assemble a persisted row from a (validated-if-not-zero) model reply. Shared by live + replay."""
    if not is_zero:
        slice_ids = {i for c in ctx["claims"] for i in (c.get("source_article_ids") or [])}
        _validate(ai, slice_ids)
    # Normalize headlines to the struct shape (text + ids), dropping extra keys the model may add.
    headlines = [{"text": str(h.get("text", "")).strip(),
                  "source_article_ids": list(h.get("source_article_ids") or [])}
                 for h in (ai.get("headlines") or [])]
    a = ctx["anchor"] or {}
    return {
        "season": ctx["season"], "week": ctx["week"],
        "sleeper_player_id": ctx["sleeper_player_id"], "player_name": ctx["player_name"],
        "team": ctx["team"], "position": ctx["position"],
        "bull_grade": ai["bull_grade"], "bull_note": ai["bull_note"],
        "bear_grade": ai["bear_grade"], "bear_note": ai["bear_note"],
        "situation_grade": ai["situation_grade"], "situation_note": ai["situation_note"],
        "headlines": headlines, "confidence": ai["confidence"],
        "confidence_note": ai["confidence_note"],
        "signal_tier": ctx["signal_tier"], "has_news": ctx["has_news"],
        "has_ros_anchor": ctx["has_ros_anchor"], "has_sleeper_facts": ctx["has_sleeper_facts"],
        "n_news_claims": ctx["n_news_claims"],
        "ros_bull": a.get("ros_bull"), "ros_bear": a.get("ros_bear"), "ros_cv": a.get("ros_cv"),
        "spectrum_pos": a.get("spectrum_pos"), "security": a.get("security"),
        "direction": a.get("direction"),
        "anchor_season": ctx["anchor_season"], "anchor_is_prior_season": ctx["anchor_is_prior_season"],
        "news_content_hash": _news_content_hash(ctx["claims"]),
        "is_zero_signal": is_zero, "model": model, "generated_at": generated_at,
    }


def build_player_row(ctx: dict, generated_at: str, *, model: str):
    """Return (row_dict, usage_or_None). Zero-signal (no anchor AND no news) => hardcoded, no API."""
    if (not ctx["has_ros_anchor"]) and (not ctx["has_news"]):
        return _row_from_reply(ctx, rp.zero_signal_synthesis(), generated_at,
                               model=None, is_zero=True), None
    ai, usage = client.generate_dossier(rp.system_prompt(), rp.user_prompt(ctx), model=model)
    return _row_from_reply(ctx, ai, generated_at, model=model, is_zero=False), usage


def _regime(ctx: dict) -> str:
    if not ctx["has_ros_anchor"] and not ctx["has_news"]:
        return "zero"
    if not ctx["has_ros_anchor"]:
        return "news-only"
    if not ctx["has_news"]:
        return "anchor-only"
    return "full-set" if ctx["signal_tier"] == "rich" else "anchor+thin-news"


# --------------------------------------------------------------------------- compute / run (live)

def compute(season: int, week: int, anchor_season: int, players, *,
            model: str = client.DEFAULT_MODEL) -> pl.DataFrame:
    """Assemble → generate → collect rows for `players`. Real API calls (except zero-signal)."""
    news_slice, ros, facts = _load_inputs(season, week, anchor_season)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"=== ROS synthesis: news season={season} wk={week} | anchor_season={anchor_season} "
          f"| model={model} | players={len(players)} ===")
    rows, tot_in, tot_out, n_api = [], 0, 0, 0
    for pid in players:
        ctx = assemble_player(pid, news_slice, ros, facts, season=season, week=week,
                              anchor_season=anchor_season)
        row, usage = build_player_row(ctx, generated_at, model=model)
        rows.append(row)
        tag = (f"b{row['bull_grade']}/f{row['bear_grade']}/s{row['situation_grade']} "
               f"conf={row['confidence']}") if not row["is_zero_signal"] else "zero-signal (no API)"
        print(f"  {ctx['player_name'] or pid:<22} {_regime(ctx):<16} -> {tag}")
        if usage:
            tot_in += usage["input_tokens"]; tot_out += usage["output_tokens"]; n_api += 1
    cost = tot_in / 1e6 * _IN_RATE + tot_out / 1e6 * _OUT_RATE
    print(f"  {n_api} API call(s); {tot_in} in / {tot_out} out tokens  ~= ${cost:.4f}")
    return pl.DataFrame(rows, schema_overrides=_SCHEMA)


def run(season: int, week: int, anchor_season: int, players, *,
        force: bool = False, model: str = client.DEFAULT_MODEL) -> None:
    if not client.api_available():
        print("ROS synthesis: LOCKED — set a real config.ANTHROPIC_API_KEY to enable this opt-in AI "
              "read. Nothing written.")
        return
    if not players:
        print("ROS synthesis: no players given (pass --player or --limit). Nothing written.")
        return
    existing = (data_layer.read_ros_synthesis(season, week=week)
                if data_layer.ros_synthesis_exists(season) else pl.DataFrame())
    present = set(existing["sleeper_player_id"].to_list()) if existing.height else set()
    todo = players if force else [p for p in players if p not in present]
    if not todo:
        print(f"ROS synthesis for season={season} week={week} already covers these players — "
              f"run once per (player, news). Use --force to regenerate.")
        return
    df = compute(season, week, anchor_season, todo, model=model)
    data_layer.write_ros_synthesis(df)
    print(f"  -> snapshots/derived/ros_synthesis_{season}.parquet  (+{df.height} player row(s))")


# --------------------------------------------------------------------------- no-AI modes

def render(players, season: int, week: int, anchor_season: int) -> None:
    """PRINT the exact system+user prompt for each player — NO API call, NO key needed."""
    news_slice, ros, facts = _load_inputs(season, week, anchor_season)
    print("=" * 100)
    print("SYSTEM PROMPT (shared across players — edit the text in ros_synthesis_prompt.py):")
    print("=" * 100)
    print(rp.system_prompt())
    for pid in players:
        ctx = assemble_player(pid, news_slice, ros, facts, season=season, week=week,
                              anchor_season=anchor_season)
        print("\n" + "=" * 100)
        print(f"USER PROMPT — {ctx['player_name'] or pid} ({pid})  regime={_regime(ctx)}")
        print("=" * 100)
        print(rp.user_prompt(ctx))


def replay(players, season: int, week: int, anchor_season: int, reply_path: str) -> None:
    """Feed a canned JSON reply (file) through validation + row assembly — NO API call, NO key needed."""
    with open(reply_path) as fh:
        ai = json.load(fh)
    news_slice, ros, facts = _load_inputs(season, week, anchor_season)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for pid in players:
        ctx = assemble_player(pid, news_slice, ros, facts, season=season, week=week,
                              anchor_season=anchor_season)
        try:
            row = _row_from_reply(ctx, ai, generated_at, model="replay", is_zero=False)
            print(f"OK   {ctx['player_name'] or pid}: "
                  f"b{row['bull_grade']}/f{row['bear_grade']}/s{row['situation_grade']} "
                  f"conf={row['confidence']} headlines={len(row['headlines'])}")
        except ValueError as exc:
            print(f"FAIL {ctx['player_name'] or pid}: {exc}")


# --------------------------------------------------------------------------- CLI

def _sample_players(season: int, week: int, limit: int) -> list[str]:
    """First `limit` distinct players in the news-slice week (deterministic sample for a verify run)."""
    if not data_layer.player_news_slice_exists():
        return []
    ids = (data_layer.read_player_news_slice(season=season, week=week)
           .select("sleeper_player_id").unique().sort("sleeper_player_id")
           .head(limit)["sleeper_player_id"].to_list())
    return ids


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ROS synthesis writer (§2 interpretation).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--render", action="store_true", help="print the assembled prompt (no API, no key)")
    mode.add_argument("--replay", metavar="REPLY.json", help="run a canned reply through validation (no API)")
    mode.add_argument("--preview", action="store_true", help="generate + print the model output (real call)")
    parser.add_argument("--player", default=None, help="comma-separated sleeper_player_id(s)")
    parser.add_argument("--limit", type=int, default=None, help="sample the first N players of the week")
    parser.add_argument("--season", type=int, default=None, help="news season (default: live nfl-state)")
    parser.add_argument("--week", type=int, default=None, help="news week (default: live nfl-state)")
    parser.add_argument("--anchor-season", type=int, default=None, dest="anchor_season")
    parser.add_argument("--force", action="store_true", help="regenerate players already written")
    parser.add_argument("--model", default=client.DEFAULT_MODEL)
    args = parser.parse_args()

    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    anchor_season = _resolve_anchor_season(season, args.anchor_season)
    players = [p.strip() for p in (args.player or "").split(",") if p.strip()]
    if args.limit:
        players = players or _sample_players(season, week, args.limit)

    if args.render:                                        # no API, no key
        if not players:
            raise SystemExit("--render needs --player or --limit")
        render(players, season, week, anchor_season)
    elif args.replay:                                      # no API, no key
        if not players:
            raise SystemExit("--replay needs --player or --limit")
        replay(players, season, week, anchor_season, args.replay)
    elif args.preview:                                     # real call, no persistence
        if not client.api_available():
            raise SystemExit("--preview needs a real config.ANTHROPIC_API_KEY.")
        if not players:
            raise SystemExit("--preview needs --player or --limit")
        df = compute(season, week, anchor_season, players, model=args.model)
        for r in df.iter_rows(named=True):
            print(f"\n### {r['player_name']} ({r['position']} {r['team']})  "
                  f"bull={r['bull_grade']} bear={r['bear_grade']} situation={r['situation_grade']}  "
                  f"confidence={r['confidence']}")
            for k in ("bull_note", "bear_note", "situation_note", "confidence_note"):
                print(f"  {k}: {r[k]}")
            for h in r["headlines"]:
                print(f"  - {h['text']}  ids={h['source_article_ids']}")
    else:                                                  # real call, WRITE
        run(season, week, anchor_season, players, force=args.force, model=args.model)
