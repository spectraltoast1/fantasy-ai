"""
Team-news-dossier gate — an INTERNAL-CONSISTENCY check on the AI news sheets (no answer key).

The synthesized claims can't be scored against ground truth (they're live/qualitative), so this
verifies they are self-consistent, grounded, and honest — reading only the PERSISTED dossier +
`team_news_raw` + the Sleeper player registry (no API calls, so it's free and repeatable). Five hard
checks (exit 0 iff all pass) plus soft synthesis evidence:

  1. Consistency — no team mixes an `is_empty` row with real claims; report teams covered / 32.
  2. Schema — every claim's scope / claim_type / direction / salience is in its vocabulary and its
     note/subject are non-empty; empty rows carry null claim fields.
  3. Grounding — every cited article id exists in team_news_raw AND belongs to that same team; the
     stored source_types / n_sources match the cited articles' true sources (no invented provenance).
  4. Player resolution — a sleeper id appears only on player-scope claims, and every resolved id is a
     real active skill player ON that team (deterministic resolver, never guessed).
  5. Zero-signal honesty — an is_empty row has no fabricated claim (null fields, empty sources).

Soft evidence (reported, not gated): claim/scope breakdown, player-resolution rate, and how many
claims cite >1 source type (cross-source corroboration = the trust signal).

Usage:
    python3 -m application.ai.check_team_news_dossier [--season 2026] [--week 0]
"""

import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.ai import news_prompt as np


def _check_consistency(d: pl.DataFrame, n_teams_total: int) -> bool:
    per = d.group_by("team").agg(
        pl.col("is_empty").any().alias("has_empty"),
        (~pl.col("is_empty")).any().alias("has_claims"),
    )
    mixed = per.filter(pl.col("has_empty") & pl.col("has_claims")).height
    covered = per.height
    ok = mixed == 0
    print(f"  1. consistency: {covered}/{n_teams_total} teams covered, {mixed} mix empty+claims  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def _check_schema(d: pl.DataFrame) -> bool:
    claims = d.filter(~pl.col("is_empty"))
    empties = d.filter(pl.col("is_empty"))
    bad = 0
    for r in claims.iter_rows(named=True):
        if r["scope"] not in np.SCOPES or r["claim_type"] not in np.CLAIM_TYPES:
            bad += 1
        elif r["basis"] not in np.BASES:
            bad += 1
        elif r["direction"] not in np.DIRECTIONS or r["salience"] not in np.SALIENCES:
            bad += 1
        elif not str(r.get("subject") or "").strip() or not str(r.get("note") or "").strip():
            bad += 1
    # empty rows must carry null claim fields
    empty_bad = empties.filter(
        pl.col("scope").is_not_null() | pl.col("claim_type").is_not_null()
        | pl.col("direction").is_not_null() | pl.col("salience").is_not_null()
    ).height
    ok = bad == 0 and empty_bad == 0
    print(f"  2. schema: {claims.height} claims checked, {bad} invalid enum/empty, "
          f"{empty_bad} empty-rows with claim fields  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_grounding(d: pl.DataFrame) -> bool:
    raw = data_layer.read_team_news_raw()
    id_team = dict(zip(raw["article_id"].to_list(), raw["team"].to_list()))
    id_source = dict(zip(raw["article_id"].to_list(), raw["source_type"].to_list()))
    claims = d.filter(~pl.col("is_empty"))
    bad_ground, bad_prov = 0, 0
    for r in claims.iter_rows(named=True):
        cited = list(r["source_article_ids"] or [])
        if not cited or any(id_team.get(i) != r["team"] for i in cited):
            bad_ground += 1
            continue
        true_types = sorted({id_source[i] for i in cited})
        if sorted(r["source_types"] or []) != true_types or r["n_sources"] != len(true_types):
            bad_prov += 1
    ok = bad_ground == 0 and bad_prov == 0
    print(f"  3. grounding: {claims.height} claims, {bad_ground} ungrounded/wrong-team ids, "
          f"{bad_prov} provenance mismatch  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_player_resolution(d: pl.DataFrame) -> bool:
    players = data_layer.read_sleeper_players().filter(
        pl.col("position").is_in(news.SKILL_POSITIONS) & pl.col("team").is_not_null()
    )
    pid_team = dict(zip(players["sleeper_player_id"].to_list(), players["team"].to_list()))
    claims = d.filter(~pl.col("is_empty"))
    # a sleeper id may only appear on a player-scope claim
    misscoped = claims.filter(
        pl.col("sleeper_player_id").is_not_null() & (pl.col("scope") != "player")
    ).height
    bad_pid = 0
    for r in claims.filter(pl.col("sleeper_player_id").is_not_null()).iter_rows(named=True):
        if pid_team.get(r["sleeper_player_id"]) != r["team"]:
            bad_pid += 1
    ok = misscoped == 0 and bad_pid == 0
    print(f"  4. player resolution: {misscoped} ids on non-player claims, "
          f"{bad_pid} ids not a skill player on that team  {'PASS' if ok else 'FAIL'}")
    return ok


def _check_zero_signal(d: pl.DataFrame) -> bool:
    empties = d.filter(pl.col("is_empty"))
    bad = empties.filter(
        (pl.col("n_sources") != 0) | (pl.col("source_article_ids").list.len() != 0)
        | pl.col("note").is_null()
    ).height
    ok = bad == 0
    print(f"  5. zero-signal honesty: {empties.height} empty rows, {bad} with fabricated content  "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def _evidence(d: pl.DataFrame) -> None:
    claims = d.filter(~pl.col("is_empty"))
    if claims.is_empty():
        print("  evidence: no claims (off-season / quiet window) — sheet is all empty rows")
        return
    scope_mix = claims.group_by("scope").len().sort("scope")
    print("  evidence: scope mix — " + ", ".join(f"{r['scope']}={r['len']}"
          for r in scope_mix.iter_rows(named=True)))
    pl_claims = claims.filter(pl.col("scope") == "player")
    resolved = pl_claims.filter(pl.col("sleeper_player_id").is_not_null()).height
    print(f"  evidence: player claims resolved to an id: {resolved}/{pl_claims.height}")
    corrob = claims.filter(pl.col("n_sources") > 1).height
    print(f"  evidence: claims corroborated across >1 source type: {corrob}/{claims.height}")


def run(season: int, week: int) -> bool:
    d = data_layer.read_team_news_dossier(season=season, week=week)
    n_total = len(news._TEAM_SITES)
    print(f"=== Team news dossier gate: season={season} week={week}  rows={d.height} ===")
    if d.is_empty():
        print("  no dossier rows for this season/week — nothing to check  FAIL")
        return False

    c1 = _check_consistency(d, n_total)
    c2 = _check_schema(d)
    c3 = _check_grounding(d)
    c4 = _check_player_resolution(d)
    c5 = _check_zero_signal(d)
    _evidence(d)

    ok = c1 and c2 and c3 and c4 and c5
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — sheets are "
          f"{'consistent, grounded, resolution-sound, and honest' if ok else 'INCONSISTENT'}.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Internal-consistency gate for team news dossiers.")
    parser.add_argument("--season", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--week", type=int, default=None, help="default: live Sleeper nfl-state")
    args = parser.parse_args()
    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    sys.exit(0 if run(season, week) else 1)


if __name__ == "__main__":
    __main()
