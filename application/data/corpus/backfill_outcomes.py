"""
backfill_outcomes.py — derive the L2 `outcomes` ledger from the frozen realized sources (Session 4b, C1).

Reads the FROZEN persisted `join_season` (player/roster realized points), `matchups` (schedule + actual
results) and `league_settings` (playoff config) across the 270 spined league-seasons, and emits immutable
REALIZED-FACT rows — "what actually happened". It derives + reshapes; it does NOT fetch, recompute a
read, re-select, re-tune, or GRADE (standing instr 8). No grade, no verdict, no error/pit — those are
`resolutions` primitives; Law 1 is structural.

### The scoring-scope finding (a correction to the brief's grounding — REPORTED, standing instr 1/6)

The brief assumed "two leagues sharing a scoring_key give a player identical weekly points, so player
point-facts are scoring-scoped." **That is false for ~9.5% of player-weeks** (spreads up to ~21 pts).
Mechanism: `scoring_key` (`ppr`/`half`/`std`) classifies only the RECEPTION tier, so two "ppr" leagues
that differ on the INT penalty, passing/reception yardage bonuses, first-down points, etc. genuinely
score the same player-week differently — and `sleeper_points` faithfully reflects each league's FULL
scoring. So realized points are a LEAGUE property, not a scoring_key property. The design respects that:

  • `player_weekly_pts` — **LEAGUE-scoped** (`league_id` set), from `join_season.sleeper_points`: each
    league-scoped point claim (`production_vor`, `player_signal`) resolves against ITS league's realized
    truth (exact — not a wrong sibling league's).
  • `player_weekly_pts_canonical` — **scoring-scoped** (`league_id=null`), realized points under the
    CANONICAL profile (`_scoring.actual_points_expr` → `fantasy_points_ppr`/`fantasy_points`; custom keys
    reuse `sleeper_points`, which agrees since a `cust-` key hashes the whole scoring dict). This is
    league-independent BY CONSTRUCTION (0 disagreement, verified) and matches the basis the scoring-scoped
    `ros_player_band` was PROJECTED under (`projection_consensus` uses `standard_scoring(scoring_key)`),
    so the band grades against a consistent answer key.

### League-scoped roster facts (division-aware — reuse, don't re-derive)

`roster_wins` / `roster_total_pts` / `roster_final_standing` / `roster_made_playoffs` (season-level) +
`roster_position_pts` (per (roster, position, week)), all carrying `league_id` (`roster_id` is only
unique within a league). Standings/made-playoffs REUSE `compute_bracket_sim`'s division-aware seeding at
`reg_end` (never a naive wins-then-points sort — that misranks the 25 real division leagues). Gate teeth
built in: per league exactly `playoff_teams` rosters get `made_playoffs=1` — asserted at derivation.

Idempotent + resumable (the 3a/4a precedent): append-only-of-new by `outcome_id` (a pure sha1 of the
fact's natural key, never wall-clock); a per-season done-cache skips leagues/scoring-keys already on disk.
Per-league failure is ISOLATED. A twice-derive is value-identical (verified by check_resolutions).

Usage:
    python3 -m application.data.corpus.backfill_outcomes --strata mine --limit 1   # is_mine 2025, proof
    python3 -m application.data.corpus.backfill_outcomes --pilot 6                  # cross-stratum sample
    python3 -m application.data.corpus.backfill_outcomes                            # full 270
"""
import argparse
import hashlib
import os
import sys
import time
from collections import Counter, defaultdict

import numpy as np
import polars as pl

from application.data import data_layer
from application.data.corpus import backfill_predictions
from application.data.transforms import _scoring
from application.data.transforms import compute_bracket_sim as bs

BACKFILL_STRATA = ("matched", "generalization", "mine")

# Canonical column order for `outcomes_{season}` (the live 2026 path reuses this verbatim).
OUTCOME_COLS = [
    "outcome_id", "league_id", "scoring_key", "season", "week",
    "subject_type", "subject_id", "outcome_type", "value",
    "data_source", "recorded_at",
]

_PTS_AGREEMENT_TOL = 1e-6   # the canonical series must agree across a key's leagues to this


def _outcome_id(scope_key: str, season: int, outcome_type: str, subject_id: str, week) -> str:
    """Stable sha1[:16] over the fact's natural key — machine-independent, never wall-clock (the 1.7/3b/4a
    lesson). `week` is stringified as "NA" for season-level facts so the key is total across grains."""
    wk = "NA" if week is None else str(int(week))
    key = "|".join([str(scope_key), str(season), outcome_type, str(subject_id), wk])
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _rows_to_frame(rows: list[dict]) -> pl.DataFrame:
    """Build the canonical outcomes frame (typed, ordered) from a list of fact dicts."""
    if not rows:
        return pl.DataFrame(schema={c: (pl.Int64 if c in ("season", "week")
                                        else pl.Float64 if c == "value" else pl.Utf8)
                                    for c in OUTCOME_COLS})
    return pl.DataFrame(rows).select(
        pl.col("outcome_id").cast(pl.Utf8),
        pl.col("league_id").cast(pl.Utf8),
        pl.col("scoring_key").cast(pl.Utf8),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("subject_type").cast(pl.Utf8),
        pl.col("subject_id").cast(pl.Utf8),
        pl.col("outcome_type").cast(pl.Utf8),
        pl.col("value").cast(pl.Float64),
        pl.col("data_source").cast(pl.Utf8),
        pl.col("recorded_at").cast(pl.Utf8),
    )


def _canonical_actual_expr(scoring_key: str) -> pl.Expr:
    """The realized-points Expr for the CANONICAL profile of a scoring_key (league-independent).
    ppr/half/std → `actual_points_expr` over the nflverse `fantasy_points*` columns; a custom `cust-` key
    → `sleeper_points` (all leagues of a cust- key share the exact normalised scoring, so it already
    agrees and IS the canonical value)."""
    if scoring_key in ("ppr", "half", "std"):
        return _scoring.actual_points_expr(scoring_key, {})
    return pl.col("sleeper_points")


# ---------------------------------------------------------------------------------------------------
# Derivations (pure over the frozen sources)
# ---------------------------------------------------------------------------------------------------

def derive_roster_facts(lid: str, season: int, sk: str) -> tuple[pl.DataFrame, dict]:
    """Season-level roster facts from the FROZEN matchups + league_settings, division-aware.

    Returns (frame, meta). `meta` carries the realized playoff mass + slot count for the gate. Reuses
    `compute_bracket_sim` verbatim: `_playoff_config` (reg_end + playoff_teams from the long-format
    settings, garbled configs floored), `_standings_as_of` (actual wins/points-for through reg_end,
    ties → 0.5), `_division_map` + `_seed_table` (division winners auto-seed; the flat table otherwise).
    The realized final SEED is both the `roster_final_standing` and the answer key for `bracket_odds`'
    avg_seed / `true_rank`'s rank."""
    reg_end, playoff_teams = bs._playoff_config(season, league_id=lid)
    matchups = data_layer.read_season_matchups(season, through_week=25, league_id=lid)
    standings = bs._standings_as_of(matchups, reg_end)          # {roster_id: {"wins","points"}}
    team_ids = sorted(standings.keys())                         # deterministic team order
    if not team_ids:
        return _rows_to_frame([]), {"playoff_teams": playoff_teams, "made_mass": 0, "n_rosters": 0}

    total_wins = np.array([[standings[r]["wins"] for r in team_ids]], dtype=float)   # shape (1, T)
    total_pts = np.array([[standings[r]["points"] for r in team_ids]], dtype=float)
    dmap = bs._division_map(season, league_id=lid)              # {roster_id: division} or None
    divisions = [dmap[r] for r in team_ids] if dmap is not None and all(r in dmap for r in team_ids) else None
    seed, made = bs._seed_table(total_wins, total_pts, playoff_teams, divisions)      # (1, T) each
    seed, made = seed[0], made[0]

    src = "matchups+seed_table" + ("+division" if divisions is not None else "")
    rows = []
    for i, rid in enumerate(team_ids):
        for otype, val in (
            ("roster_wins", float(standings[rid]["wins"])),
            ("roster_total_pts", float(standings[rid]["points"])),
            ("roster_final_standing", float(seed[i])),
            ("roster_made_playoffs", 1.0 if bool(made[i]) else 0.0),
        ):
            rows.append({
                "outcome_id": _outcome_id(lid, season, otype, str(rid), None),
                "league_id": lid, "scoring_key": sk, "season": season, "week": None,
                "subject_type": "roster", "subject_id": str(rid), "outcome_type": otype,
                "value": val, "data_source": src, "recorded_at": None,
            })
    meta = {"playoff_teams": int(playoff_teams), "made_mass": int(np.sum(made)), "n_rosters": len(team_ids)}
    return _rows_to_frame(rows), meta


def derive_league_player_facts(lid: str, season: int, sk: str) -> pl.DataFrame:
    """The LEAGUE-scoped player/roster-position facts from the FROZEN `join_season`:
      • `player_weekly_pts` per (league_id, sleeper_player_id, week) — this league's realized
        `sleeper_points` (its FULL scoring — the exact truth `production_vor`/`player_signal` resolve on).
      • `roster_position_pts` per (roster_id, position, week) — Σ realized points over that roster's
        players at that position that week (the depth realization §6 grades on its clean subset).
    Only non-null points are facts."""
    js = data_layer.read_join_season(season, league_id=lid)
    rows = []
    # player_weekly_pts (league-scoped)
    if {"sleeper_player_id", "week", "sleeper_points"}.issubset(js.columns):
        pw = (js.filter(pl.col("sleeper_player_id").is_not_null() & pl.col("sleeper_points").is_not_null())
                .select("sleeper_player_id", "week", "sleeper_points").unique())
        for r in pw.iter_rows(named=True):
            pid, wk = str(r["sleeper_player_id"]), int(r["week"])
            rows.append({
                "outcome_id": _outcome_id(lid, season, "player_weekly_pts", pid, wk),
                "league_id": lid, "scoring_key": sk, "season": season, "week": wk,
                "subject_type": "player", "subject_id": pid, "outcome_type": "player_weekly_pts",
                "value": float(r["sleeper_points"]), "data_source": "join_season", "recorded_at": None,
            })
    # roster_position_pts (league-scoped)
    if {"roster_id", "position", "week", "sleeper_points"}.issubset(js.columns):
        agg = (js.filter(pl.col("sleeper_points").is_not_null()
                         & pl.col("roster_id").is_not_null() & pl.col("position").is_not_null())
                 .group_by("roster_id", "position", "week")
                 .agg(pl.col("sleeper_points").sum().alias("pts")))
        for r in agg.iter_rows(named=True):
            rid, pos, wk = int(r["roster_id"]), str(r["position"]), int(r["week"])
            subj = f"{rid}:{pos}"
            rows.append({
                "outcome_id": _outcome_id(lid, season, "roster_position_pts", subj, wk),
                "league_id": lid, "scoring_key": sk, "season": season, "week": wk,
                "subject_type": "roster", "subject_id": subj, "outcome_type": "roster_position_pts",
                "value": float(r["pts"]), "data_source": "join_season", "recorded_at": None,
            })
    return _rows_to_frame(rows)


def derive_player_weekly_canonical(sk: str, season: int, league_ids: list[str]) -> tuple[pl.DataFrame, list]:
    """`player_weekly_pts_canonical` per (scoring_key, sleeper_player_id, week), `league_id=null` — realized
    points under the CANONICAL profile of the scoring_key, the UNION over the key's leagues stored ONCE.
    league-INDEPENDENT by construction, so the cross-league agreement check is expected clean (a residual
    disagreement — a custom key whose leagues somehow differ — is FLAGGED, not de-duped away)."""
    expr = _canonical_actual_expr(sk)
    frames = []
    for lid in league_ids:
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        js = data_layer.read_join_season(season, league_id=lid)
        if "sleeper_player_id" not in js.columns or "week" not in js.columns:
            continue
        try:
            sel = js.select(
                pl.col("sleeper_player_id").cast(pl.Utf8),
                pl.col("week").cast(pl.Int64),
                expr.cast(pl.Float64).alias("cpts"),
            ).filter(pl.col("sleeper_player_id").is_not_null() & pl.col("cpts").is_not_null())
        except pl.exceptions.ColumnNotFoundError:
            continue
        frames.append(sel)
    if not frames:
        return _rows_to_frame([]), []
    allrows = pl.concat(frames)
    agg = (allrows.group_by("sleeper_player_id", "week")
                  .agg((pl.col("cpts").max() - pl.col("cpts").min()).alias("spread"),
                       pl.col("cpts").min().alias("pts")))
    disagreements = [(r["sleeper_player_id"], int(r["week"]), round(r["spread"], 4))
                     for r in agg.filter(pl.col("spread") > _PTS_AGREEMENT_TOL).iter_rows(named=True)]
    rows = []
    for r in agg.sort("sleeper_player_id", "week").iter_rows(named=True):
        pid, wk = str(r["sleeper_player_id"]), int(r["week"])
        rows.append({
            "outcome_id": _outcome_id(sk, season, "player_weekly_pts_canonical", pid, wk),
            "league_id": None, "scoring_key": sk, "season": season, "week": wk,
            "subject_type": "player", "subject_id": pid, "outcome_type": "player_weekly_pts_canonical",
            "value": float(r["pts"]), "data_source": "join_season:canonical", "recorded_at": None,
        })
    return _rows_to_frame(rows), disagreements


# ---------------------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------------------

def _sk_leagues(season: int) -> dict:
    """(scoring_key) -> [league_id] over ALL spined leagues of a season (every stratum), so the
    scoring-scoped canonical population is COMPLETE even on a partial-strata run (mirrors the 4a band's
    once-per-scoring-key emission)."""
    m = defaultdict(list)
    for r in backfill_predictions.targets():
        if int(r["season"]) == season:
            m[str(r["scoring_key"])].append(str(r["league_id"]))
    return m


def _done_cache(season: int) -> dict:
    """What's already on disk for a season — {leagues: set(league_id with league-scoped facts),
    scoring_keys: set(scoring_key with the canonical player series)}."""
    if not data_layer.outcomes_exists(season):
        return {"leagues": set(), "scoring_keys": set()}
    df = data_layer.read_outcomes(season)
    leagues = set(df.filter(pl.col("league_id").is_not_null())["league_id"].unique().to_list())
    sks = set(df.filter(pl.col("outcome_type") == "player_weekly_pts_canonical")["scoring_key"]
              .unique().to_list())
    return {"leagues": leagues, "scoring_keys": sks}


def run(strata=BACKFILL_STRATA, limit=None, pilot=None) -> dict:
    tgts = (backfill_predictions.pilot_targets(pilot, strata) if pilot
            else backfill_predictions.targets(strata, limit))

    t0 = time.time()
    league_written = league_skipped = sk_written = sk_skipped = 0
    rows_written = 0
    by_type = Counter()
    mass_ok = mass_bad = 0
    mass_failures = []          # (lid, season, made_mass, playoff_teams)
    disagree = []               # (scoring_key, season, count)
    errored = []                # (lid, season, error)
    seasons_touched = set()
    done = {}
    sk_leagues_cache = {}
    emitted_sk = defaultdict(set)

    for i, r in enumerate(tgts, 1):
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        tag = f"[{i}/{len(tgts)}] {r['stratum']:14} {lid} {season} {sk}"
        if season not in done:
            done[season] = _done_cache(season)
            sk_leagues_cache[season] = _sk_leagues(season)
        try:
            wrote = False
            # --- league-scoped facts (roster facts + league player_weekly_pts) [once per league] ---
            if lid in done[season]["leagues"]:
                league_skipped += 1
            else:
                rf, meta = derive_roster_facts(lid, season, sk)
                if meta["made_mass"] != meta["playoff_teams"]:
                    mass_bad += 1
                    mass_failures.append((lid, season, meta["made_mass"], meta["playoff_teams"]))
                    raise RuntimeError(f"realized playoff mass {meta['made_mass']} != slot count "
                                       f"{meta['playoff_teams']} (division seeding / roster set bug)")
                mass_ok += 1
                lp = derive_league_player_facts(lid, season, sk)
                batch = pl.concat([rf, lp], how="vertical")
                data_layer.write_outcomes(batch, season)
                league_written += 1
                rows_written += batch.height
                seasons_touched.add(season)
                for ot, cnt in batch.group_by("outcome_type").len().iter_rows():
                    by_type[ot] += cnt
                wrote = True

            # --- scoring-scoped canonical player series [once per (scoring_key, season)] ---
            if sk in done[season]["scoring_keys"] or sk in emitted_sk[season]:
                sk_skipped += 1
            else:
                pw, dis = derive_player_weekly_canonical(sk, season, sk_leagues_cache[season][sk])
                if dis:
                    disagree.append((sk, season, len(dis)))
                    print(f"      ⚠ {len(dis)} canonical player-week disagreements for {sk} {season} "
                          f"(e.g. {dis[:3]}) — FLAGGED, not de-duped away")
                data_layer.write_outcomes(pw, season)
                sk_written += 1
                rows_written += pw.height
                seasons_touched.add(season)
                emitted_sk[season].add(sk)
                by_type["player_weekly_pts_canonical"] += pw.height
                wrote = True
            print(f"  {tag}  {'written' if wrote else 'SKIP (present)'}")
        except Exception as exc:   # noqa: BLE001 — isolate one league; a re-run retries it
            errored.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:160]}")

    report = {
        "targets": len(tgts),
        "league_written": league_written, "league_skipped": league_skipped,
        "sk_written": sk_written, "sk_skipped": sk_skipped,
        "rows_written": rows_written, "elapsed_s": round(time.time() - t0, 1),
        "by_type": dict(by_type), "mass_ok": mass_ok, "mass_bad": mass_bad,
        "mass_failures": mass_failures, "disagree": disagree,
        "file_sizes": {s: round(os.path.getsize(data_layer._outcomes_path(s)) / 1e6, 2)
                       for s in sorted(seasons_touched) if data_layer.outcomes_exists(s)},
        "errored": errored,
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== outcomes backfill report ===")
    print(f"  targets={rep['targets']}  leagues written={rep['league_written']} skipped={rep['league_skipped']}"
          f"  |  scoring-keys written={rep['sk_written']} skipped={rep['sk_skipped']}")
    print(f"  rows written this run={rep['rows_written']:,}  wall-clock={rep['elapsed_s']}s  "
          f"(incremental re-run ≈ 0 — append-only-of-new)")
    print("  by outcome_type:")
    for ot, cnt in sorted(rep["by_type"].items()):
        print(f"    {ot:28} {cnt:>10,}")
    print(f"  realized playoff mass == slot count: {rep['mass_ok']} ok / {rep['mass_bad']} bad")
    for lid, season, mass, slots in rep["mass_failures"]:
        print(f"    ✗ {lid} {season}: mass {mass} != {slots}")
    if rep["file_sizes"]:
        print("  per-season file size (MB):")
        for s, mb in rep["file_sizes"].items():
            print(f"    outcomes_{s}.parquet  {mb}")
    print(f"  canonical point disagreements (flagged, not de-duped): {len(rep['disagree'])}")
    for sk, season, cnt in rep["disagree"]:
        print(f"    {sk} {season}: {cnt} player-weeks disagree across leagues")
    print(f"  errored (isolated; retried on re-run): {len(rep['errored'])}")
    for lid, season, err in rep["errored"]:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Backfill the L2 outcomes ledger (Session 4b).")
    ap.add_argument("--strata", nargs="+", default=list(BACKFILL_STRATA),
                    choices=["matched", "generalization", "mine"])
    ap.add_argument("--limit", type=int, default=None, help="first N spined targets (deterministic order)")
    ap.add_argument("--pilot", type=int, default=None, help="N leagues across strata + budget report")
    a = ap.parse_args()
    run(strata=tuple(a.strata), limit=a.limit, pilot=a.pilot)


if __name__ == "__main__":
    main()
    sys.exit(0)
