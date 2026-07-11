"""
Per-player news slice by inheritance — the §2 news pipeline **Stage C** (the final stage).

Collapses each team's Stage-B news sheet (`team_news_dossier`) down to ONE player. A skill player
inherits, from his team's sheet for that (season, week):
  - **own** — the `player` claims Stage B already resolved to HIS sleeper id (the resolver ran in
    Stage B; the slice only filters — it never re-resolves).
  - **position_group** — claims scoped to his position room (subject QB/RB/WR/TE), plus team-wide
    offensive context (subject 'offense' / 'offensive line' / a coaching/scheme note) that bears on
    every skill player.
  - **unit** — his team's `unit` claims: 'offense' and the single condensed 'defense' note (the
    defense lightly shapes game script for the offense, so every skill player inherits it).

This is a **deterministic reshape** — no AI, no credits — so the gate (`check_player_news_slice.py`)
can recompute the inheritance and demand an exact match. The output is the per-player consumable the
§2 synthesis (QUEUED #2) reads next to the `ros_outcome_shape` anchors.

**Thinness tripwire** (columns on the slice — no second entity): every row carries a `signal_tier`
(rich = ≥1 own claim / thin = only inherited context / none = nothing) + `n_own_claims` /
`n_inherited_claims` / `team_news_volume` (the team's in-window raw-article count). A player who
inherits nothing gets ONE explicit is_empty "no-signal" row (honest-zero, like positional_depth's
zero-count rows) so thinness is queryable, not an inferred absence.

Whole-pool + forward: the universe is EVERY on-team skill player in the live Sleeper registry (~967),
not the frozen-2025 league — the news layer is the forward/live pipeline by design.

Usage:
    python -m application.data.transforms.compute_player_news_slice [--season 2026] [--week 0] \
        [--force] [--player 4046]
"""

import argparse
from datetime import datetime, timedelta, timezone

import polars as pl

from application.data import data_layer
from application.data.fetchers import news
from application.ai.write_team_news_dossier import WINDOW_DAYS   # the synthesis window (single source)

_SCHEMA = {
    "season": pl.Int64, "week": pl.Int64,
    "sleeper_player_id": pl.Utf8, "player_name": pl.Utf8, "team": pl.Utf8, "position": pl.Utf8,
    "inheritance": pl.Utf8,
    "scope": pl.Utf8, "subject": pl.Utf8, "claim_type": pl.Utf8, "basis": pl.Utf8, "note": pl.Utf8,
    "direction": pl.Utf8, "salience": pl.Utf8,
    "source_article_ids": pl.List(pl.Utf8), "source_types": pl.List(pl.Utf8), "n_sources": pl.Int64,
    "signal_tier": pl.Utf8, "n_own_claims": pl.Int64, "n_inherited_claims": pl.Int64,
    "team_news_volume": pl.Int64,
    "generated_at": pl.Utf8, "is_empty": pl.Boolean,
}

# The dossier claim fields carried through onto a slice row, unchanged (provenance preserved).
_CLAIM_FIELDS = ("scope", "subject", "claim_type", "basis", "note", "direction", "salience",
                 "source_article_ids", "source_types", "n_sources")


def position_group_positions(subject: str) -> set[str] | None:
    """Which skill positions a `position_group` claim applies to (SHARED with the gate).

    A subject naming a skill room (QB/RB/WR/TE) is position-specific — only that room's players
    inherit it. A team-wide offensive subject ('offense', 'offensive line', a coaching/scheme note)
    bears on every skill player, so all four positions inherit it. Anything else is unmapped drift
    (the Stage-B prompt asks for a position word) → returns None so the caller drops + reports it.
    """
    s = (subject or "").strip().upper()
    if s in news.SKILL_POSITIONS:
        return {s}
    low = (subject or "").strip().lower()
    if "offens" in low or "coach" in low or "scheme" in low or "line" in low:
        return set(news.SKILL_POSITIONS)          # team-wide offensive context → everyone
    return None


def _team_volume(season: int, now: datetime) -> dict[str, int]:
    """Per-team in-window raw-article count (the Stage-C thinness input; the Stage-A volume report).

    Same window as the Stage-B synthesis (WINDOW_DAYS ending now), so it reflects how much news the
    dossier had to work with. Counts ROWS (retention nulls old `content` but keeps the row), so it is
    unaffected by pruning.
    """
    if not data_layer.team_news_raw_exists():
        return {}
    raw = data_layer.read_team_news_raw(season=season)
    if raw.is_empty():
        return {}
    cutoff = (now - timedelta(days=WINDOW_DAYS)).date().isoformat()
    w = raw.filter(pl.col("published_at").str.slice(0, 10) >= cutoff)
    return {r["team"]: r["len"] for r in w.group_by("team").len().iter_rows(named=True)}


def _base(pid, name, team, pos, season, week, tier, n_own, n_inh, vol, generated_at) -> dict:
    return {
        "season": season, "week": week,
        "sleeper_player_id": pid, "player_name": name, "team": team, "position": pos,
        "signal_tier": tier, "n_own_claims": n_own, "n_inherited_claims": n_inh,
        "team_news_volume": vol, "generated_at": generated_at,
    }


def _claim_row(base: dict, claim: dict, inheritance: str) -> dict:
    row = dict(base)
    row["inheritance"] = inheritance
    for f in _CLAIM_FIELDS:
        row[f] = claim[f]
    row["is_empty"] = False
    return row


def _empty_row(base: dict) -> dict:
    row = dict(base)
    row["inheritance"] = None
    row["scope"] = row["subject"] = row["claim_type"] = row["basis"] = row["note"] = None
    row["direction"] = row["salience"] = None
    row["source_article_ids"] = []
    row["source_types"] = []
    row["n_sources"] = 0
    row["is_empty"] = True
    return row


def compute(season: int, week: int) -> pl.DataFrame:
    dossier = (data_layer.read_team_news_dossier(season=season, week=week)
               if data_layer.team_news_dossier_exists() else pl.DataFrame())
    if dossier.is_empty():
        raise SystemExit(f"No team_news_dossier for season={season} week={week} — run Stage B first "
                         f"(python -m application.ai.write_team_news_dossier).")

    players = data_layer.read_sleeper_players().filter(
        pl.col("position").is_in(news.SKILL_POSITIONS) & pl.col("team").is_not_null()
    )
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat(timespec="seconds")
    vol_by_team = _team_volume(season, now)

    claims = dossier.filter(~pl.col("is_empty"))
    # Bucket the team's claims once per team (each team sheet is small).
    own_by_team: dict[str, dict[str, list]] = {}     # team -> pid -> [player claims]
    pg_by_team: dict[str, list] = {}                 # team -> [(positions, claim)]
    unit_by_team: dict[str, list] = {}               # team -> [unit claims]
    unmapped_pg: dict[str, int] = {}                 # drift report: subject -> count
    for c in claims.iter_rows(named=True):
        team, scope = c["team"], c["scope"]
        if scope == "player":
            pid = c["sleeper_player_id"]
            if pid is not None:                       # unresolved (null id) claims reach no player
                own_by_team.setdefault(team, {}).setdefault(pid, []).append(c)
        elif scope == "position_group":
            positions = position_group_positions(c["subject"])
            if positions is None:
                unmapped_pg[c["subject"]] = unmapped_pg.get(c["subject"], 0) + 1
                continue
            pg_by_team.setdefault(team, []).append((positions, c))
        elif scope == "unit":
            unit_by_team.setdefault(team, []).append(c)

    rows = []
    for p in players.iter_rows(named=True):
        pid, name, team, pos = (p["sleeper_player_id"], p["full_name"], p["team"], p["position"])
        own = own_by_team.get(team, {}).get(pid, [])
        pg = [c for positions, c in pg_by_team.get(team, []) if pos in positions]
        unit = unit_by_team.get(team, [])
        n_own, n_inh = len(own), len(pg) + len(unit)
        tier = "rich" if n_own else ("thin" if n_inh else "none")
        base = _base(pid, name, team, pos, season, week, tier, n_own, n_inh,
                     vol_by_team.get(team, 0), generated_at)
        if n_own + n_inh == 0:
            rows.append(_empty_row(base))
            continue
        rows.extend(_claim_row(base, c, "own") for c in own)
        rows.extend(_claim_row(base, c, "position_group") for c in pg)
        rows.extend(_claim_row(base, c, "unit") for c in unit)

    df = pl.DataFrame(rows, schema_overrides=_SCHEMA)
    _report(df, season, week, players.height, unmapped_pg)
    return df


def _report(df: pl.DataFrame, season, week, n_players, unmapped_pg) -> None:
    print(f"=== Player news slice: season={season} week={week}  players={n_players}  rows={df.height} ===")
    tiers = {r["signal_tier"]: r["len"] for r in
             df.select("sleeper_player_id", "signal_tier").unique()
               .group_by("signal_tier").len().iter_rows(named=True)}
    print(f"  signal_tier — rich {tiers.get('rich', 0)}, thin {tiers.get('thin', 0)}, "
          f"none {tiers.get('none', 0)}")
    inh = df.filter(pl.col("inheritance").is_not_null())
    mix = {r["inheritance"]: r["len"] for r in inh.group_by("inheritance").len().iter_rows(named=True)}
    print(f"  inherited claim rows — own {mix.get('own', 0)}, "
          f"position_group {mix.get('position_group', 0)}, unit {mix.get('unit', 0)}")
    if unmapped_pg:
        drift = ", ".join(f"{s!r}×{n}" for s, n in sorted(unmapped_pg.items()))
        print(f"  ⚠ dropped unmapped position_group subjects (Stage-B drift): {drift}")


def run(season: int, week: int, *, force: bool = False) -> None:
    if not force and data_layer.player_news_slice_exists():
        existing = data_layer.read_player_news_slice(season=season, week=week)
        if existing.height:
            print(f"Player news slice for season={season} week={week} already exists "
                  f"({existing.height} rows) — run once per week. Use --force to regenerate.")
            return
    df = compute(season, week)
    data_layer.write_player_news_slice(df)
    print(f"  → snapshots/news/player_news_slice.parquet  (+{df.height} rows)")


def _inspect(season: int, week: int, player: str) -> None:
    """Print one player's inherited slice from a fresh compute (no write) — an eyeball tool."""
    df = compute(season, week).filter(pl.col("sleeper_player_id") == player)
    if df.is_empty():
        print(f"  (no on-team skill player with sleeper_player_id={player})")
        return
    with pl.Config(fmt_str_lengths=90, tbl_rows=40):
        print(df.select("player_name", "team", "position", "signal_tier", "inheritance",
                        "scope", "subject", "claim_type", "basis", "direction", "salience",
                        "note", "n_sources"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Per-player news slice by inheritance (§2 Stage C).")
    parser.add_argument("--season", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--week", type=int, default=None, help="default: live Sleeper nfl-state")
    parser.add_argument("--force", action="store_true", help="regenerate even if the week exists")
    parser.add_argument("--player", default=None, help="inspect one player's slice (no write)")
    args = parser.parse_args()

    _season, _week = news._nfl_state()
    season = args.season if args.season is not None else _season
    week = args.week if args.week is not None else _week
    if args.player:
        _inspect(season, week, args.player)
    else:
        run(season, week, force=args.force)
