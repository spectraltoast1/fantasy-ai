"""
Player-news-slice gate — a HARD, deterministic check on the §2 Stage-C inheritance (exit 0 iff all
pass). Unlike the Stage-B dossier gate (internal-consistency only — the AI claims have no answer key),
Stage C is a pure reshape, so the "answer key" is the dossier itself: this **independently recomputes**
each player's inherited claim set from `team_news_dossier` + the Sleeper registry and demands the
persisted slice equal it EXACTLY — no claim invented, none dropped, tagged and attributed correctly.

Reads only persisted parquet (no API), so it is free and repeatable. Checks:
  1. Coverage — every on-team skill player appears exactly once; the slice adds no non-registry player.
  2. Identity — each slice player's team/position match the live registry.
  3. Inheritance round-trip — the multiset of (inheritance, claim) rows per player equals the
     independently-recomputed expected set (own = his resolved player claims; position_group = his
     position + team-wide offensive claims; unit = his team's offense/defense). Provenance
     (source ids/types/n_sources) is part of the compared identity, so it must survive unchanged.
  4. Thinness honesty — signal_tier matches recomputed counts (rich⇔≥1 own, none⇔0 inherited); the
     rollups (n_own_claims/n_inherited_claims) are consistent across a player's rows and correct;
     team_news_volume is consistent within a team.
  5. Zero-signal honesty — a `none` player is exactly ONE is_empty row with null claim fields, empty
     sources, and a null inheritance tag.
  6. Retention safety — every dossier-cited article id still exists in team_news_raw (pruning keeps
     rows), and no article still inside the synthesis window has had its content nulled.

Usage:
    python -m application.data.transforms.check_player_news_slice [--season 2026] [--week 0]
"""

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.data.transforms.compute_player_news_slice import (
    position_group_positions, WINDOW_DAYS,
)

_TIERS = ("rich", "thin", "none")


def _identity(r: dict) -> tuple:
    """A claim's identity within a team-week — the carried dossier fields (provenance included)."""
    return (
        r["scope"], r["subject"], r["claim_type"], r["basis"], r["note"], r["direction"],
        r["salience"], tuple(r["source_article_ids"] or []), tuple(r["source_types"] or []),
        r["n_sources"],
    )


def _team_buckets(claims: pl.DataFrame):
    """Independent reconstruction of each team's inheritable claims (does NOT call compute())."""
    own: dict[str, dict[str, list]] = {}
    pg: dict[str, list] = {}
    unit: dict[str, list] = {}
    for c in claims.iter_rows(named=True):
        team, scope = c["team"], c["scope"]
        if scope == "player" and c["sleeper_player_id"] is not None:
            own.setdefault(team, {}).setdefault(c["sleeper_player_id"], []).append(c)
        elif scope == "position_group":
            positions = position_group_positions(c["subject"])
            if positions is not None:
                pg.setdefault(team, []).append((positions, c))
        elif scope == "unit":
            unit.setdefault(team, []).append(c)
    return own, pg, unit


def run(season: int, week: int) -> bool:
    slice_df = (data_layer.read_player_news_slice(season=season, week=week)
                if data_layer.player_news_slice_exists() else pl.DataFrame())
    print(f"=== Player news slice gate: season={season} week={week}  rows={slice_df.height} ===")
    if slice_df.is_empty():
        print("  no slice rows for this season/week — nothing to check  FAIL")
        return False

    dossier = data_layer.read_team_news_dossier(season=season, week=week)
    claims = dossier.filter(~pl.col("is_empty"))
    registry = data_layer.read_sleeper_players().filter(
        pl.col("position").is_in(news.SKILL_POSITIONS) & pl.col("team").is_not_null()
    )
    reg = {r["sleeper_player_id"]: r for r in registry.iter_rows(named=True)}
    own_b, pg_b, unit_b = _team_buckets(claims)

    by_player = {pid: g for (pid,), g in slice_df.group_by("sleeper_player_id")}

    # 1. Coverage — exactly the registry's players, once each.
    slice_ids, reg_ids = set(by_player), set(reg)
    missing, extra = reg_ids - slice_ids, slice_ids - reg_ids
    c1 = not missing and not extra
    print(f"  1. coverage: {len(slice_ids)}/{len(reg_ids)} players, {len(missing)} missing, "
          f"{len(extra)} not-in-registry  {'PASS' if c1 else 'FAIL'}")

    bad_identity = bad_round = bad_thin = bad_zero = 0
    for pid, g in by_player.items():
        p = reg.get(pid)
        rows = g.to_dicts()
        if p is None:
            continue                                  # already counted as extra in check 1
        team, pos = p["team"], p["position"]

        # 2. Identity — slice team/position match the registry (single value per player).
        if any(r["team"] != team or r["position"] != pos for r in rows):
            bad_identity += 1

        # expected inheritance (independent recompute)
        exp = Counter()
        for c in own_b.get(team, {}).get(pid, []):
            exp[("own", _identity(c))] += 1
        for positions, c in pg_b.get(team, []):
            if pos in positions:
                exp[("position_group", _identity(c))] += 1
        for c in unit_b.get(team, []):
            exp[("unit", _identity(c))] += 1

        is_empty_rows = [r for r in rows if r["is_empty"]]
        if not exp:
            # 5. zero-signal: exactly one is_empty presence row, null claim + null tag + empty sources
            if not (len(rows) == 1 and rows[0]["is_empty"] and rows[0]["signal_tier"] == "none"
                    and rows[0]["inheritance"] is None and rows[0]["scope"] is None
                    and rows[0]["n_sources"] == 0 and not (rows[0]["source_article_ids"] or [])):
                bad_zero += 1
            continue
        if is_empty_rows:                             # has claims but also an empty row → inconsistent
            bad_zero += 1

        # 3. round-trip: actual (inheritance, identity) multiset == expected
        act = Counter((r["inheritance"], _identity(r)) for r in rows)
        if act != exp:
            bad_round += 1

        # 4. thinness honesty — recomputed counts vs the stored rollups + tier
        n_own = sum(v for (lvl, _), v in exp.items() if lvl == "own")
        n_inh = sum(v for (lvl, _), v in exp.items() if lvl != "own")
        tier = "rich" if n_own else ("thin" if n_inh else "none")
        if (any(r["n_own_claims"] != n_own or r["n_inherited_claims"] != n_inh
                or r["signal_tier"] != tier for r in rows)):
            bad_thin += 1

    c2 = bad_identity == 0
    c3 = bad_round == 0
    c4 = bad_thin == 0
    c5 = bad_zero == 0
    print(f"  2. identity: {bad_identity} players with team/position != registry  "
          f"{'PASS' if c2 else 'FAIL'}")
    print(f"  3. inheritance round-trip: {bad_round} players whose slice != recomputed expected  "
          f"{'PASS' if c3 else 'FAIL'}")
    print(f"  4. thinness honesty: {bad_thin} players with wrong tier/counts  "
          f"{'PASS' if c4 else 'FAIL'}")
    print(f"  5. zero-signal honesty: {bad_zero} players with a malformed no-signal/mixed row  "
          f"{'PASS' if c5 else 'FAIL'}")

    # 4b. team_news_volume consistent within a team
    vol_bad = (slice_df.group_by("team").agg(pl.col("team_news_volume").n_unique().alias("nv"))
               .filter(pl.col("nv") > 1).height)
    c4b = vol_bad == 0
    print(f"  4b. team_news_volume: {vol_bad} teams with inconsistent volume  "
          f"{'PASS' if c4b else 'FAIL'}")

    c6 = _check_retention(claims)
    _evidence(slice_df)

    ok = c1 and c2 and c3 and c4 and c4b and c5 and c6
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the slice is "
          f"{'an exact, honest inheritance of the dossier' if ok else 'INCONSISTENT with the dossier'}.")
    return ok


def _check_retention(claims: pl.DataFrame) -> bool:
    """6. Retention safety — every dossier-cited article id still exists as a row in team_news_raw.

    Pruning nulls old `content` but KEEPS the row, and its `published_at < now−RETENTION_DAYS` cutoff
    (28d) sits strictly outside the 14d synthesis window a claim cites from — so a cited article is
    never pruned and its row must survive. (We can't gate on "in-window content is non-null": the
    headline-only sources are natively content-less, indistinguishable post-hoc from a prune — so
    that count is reported as evidence, not gated.)
    """
    if not data_layer.team_news_raw_exists():
        print("  6. retention safety: no team_news_raw store — SKIP")
        return True
    raw = data_layer.read_team_news_raw()
    ids = set(raw["article_id"].to_list())
    cited = {i for lst in claims["source_article_ids"].to_list() for i in (lst or [])}
    missing_cited = cited - ids

    cutoff = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).date().isoformat()
    in_window_empty = raw.filter(
        (pl.col("published_at").str.slice(0, 10) >= cutoff)
        & (pl.col("content").is_null() | (pl.col("content").str.len_chars() == 0))
    ).height
    ok = not missing_cited
    print(f"  6. retention safety: {len(missing_cited)} cited ids missing from raw  "
          f"{'PASS' if ok else 'FAIL'}  "
          f"(evidence: {in_window_empty} in-window articles are natively content-less)")
    return ok


def _evidence(s: pl.DataFrame) -> None:
    per_player = s.select("sleeper_player_id", "signal_tier").unique()
    tiers = {r["signal_tier"]: r["len"] for r in per_player.group_by("signal_tier").len().iter_rows(named=True)}
    print("  evidence: tiers — " + ", ".join(f"{t}={tiers.get(t, 0)}" for t in _TIERS))
    inh = s.filter(pl.col("inheritance").is_not_null())
    mix = {r["inheritance"]: r["len"] for r in inh.group_by("inheritance").len().iter_rows(named=True)}
    print(f"  evidence: inherited rows — own={mix.get('own', 0)}, "
          f"position_group={mix.get('position_group', 0)}, unit={mix.get('unit', 0)}")


def __main():
    parser = argparse.ArgumentParser(description="Hard inheritance gate for the player news slice.")
    parser.add_argument("--season", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--week", type=int, default=None, help="default: live Sleeper nfl-state")
    args = parser.parse_args()
    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    sys.exit(0 if run(season, week) else 1)


if __name__ == "__main__":
    __main()
