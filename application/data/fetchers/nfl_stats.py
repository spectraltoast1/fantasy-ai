"""
nflreadpy fetcher — player-week snapshots and player ID mapping.

Public API:
    backfill(year)  — pull full season for a given year and write parquet
    refresh()       — pull the most recently completed week of the current season
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy
import polars as pl

_HERE = Path(__file__).resolve().parent       # .../application/data/fetchers/
_DATA_DIR = _HERE.parent                      # .../application/data/

# data_layer.py lives one level up in application/data/ — all snapshot/cache I/O
# goes through it (the fetcher constructs no paths and calls no polars read/write).
from application.data import data_layer
# The expected-points component list is owned by the scoring seam so the fetcher (which stores the
# raw components) and the read (which re-scores them) agree on one source of truth.
from application.data.transforms import _scoring


def _build_player_id_map() -> pl.DataFrame:
    """Load ff_playerids, write player_id_map.parquet, return the DataFrame."""
    df = nflreadpy.load_ff_playerids()
    df = (
        df
        .select(["gsis_id", "sleeper_id", "pfr_id"])
        .filter(pl.col("gsis_id").is_not_null())
        .with_columns(pl.col("sleeper_id").cast(pl.Utf8).alias("sleeper_player_id"))
    )
    data_layer.write_player_id_map(df)
    print(f"  Player ID map: {len(df)} rows → cache/player_id_map.parquet")
    return df


def _load_player_stats(year: int) -> pl.DataFrame:
    df = nflreadpy.load_player_stats(year, summary_level="week")
    return df.filter(pl.col("season_type") == "REG")


def _load_snap_pct(year: int) -> pl.DataFrame:
    """Return (gsis_id, week, snap_pct) via pfr_id join."""
    snaps = nflreadpy.load_snap_counts(year).filter(pl.col("game_type") == "REG")
    ids = (
        nflreadpy.load_ff_playerids()
        .select(["pfr_id", "gsis_id"])
        .filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null())
    )
    return (
        snaps
        .join(ids, left_on="pfr_player_id", right_on="pfr_id", how="left")
        .select(["gsis_id", "week", "offense_pct"])
        .rename({"offense_pct": "snap_pct"})
        .filter(pl.col("gsis_id").is_not_null())
    )


def _load_team_rates(year: int) -> pl.DataFrame:
    """Return (team, week, team_pass_rate, team_rush_rate)."""
    df = nflreadpy.load_team_stats(year, summary_level="week").filter(
        pl.col("season_type") == "REG"
    )
    total = pl.col("attempts") + pl.col("carries")
    return df.with_columns([
        (pl.col("attempts") / total).alias("team_pass_rate"),
        (pl.col("carries") / total).alias("team_rush_rate"),
    ]).select(["team", "week", "team_pass_rate", "team_rush_rate"])


def _load_redzone_touches(year: int) -> pl.DataFrame:
    """Return (gsis_id, week, redzone_touches) from play-by-play — the legible companion evidence for
    the Quality read (a player's touches inside the 20). The Quality axis *itself* is now the
    ff_opportunity expected-points model (`_load_ff_opportunity`, DECISION_READS §1), which retired the
    old hand-rolled `xtd = Σ td_prob` TD-proxy (dropped from the fetcher output, then purged from the stale
    2020-24 parquets by `corpus/retire_xtd.py` — no season carries it now); this keeps only the red-zone
    volume that model doesn't express. Player ids are already gsis_id format, matching every other join
    here — no id mapping.
    """
    pbp = nflreadpy.load_pbp(year).filter(pl.col("season_type") == "REG")
    redzone = pl.col("yardline_100") <= 20

    rush = pbp.filter(
        pl.col("rush_attempt") == 1, pl.col("rusher_player_id").is_not_null()
    ).select(pl.col("rusher_player_id").alias("gsis_id"), "week", redzone.alias("redzone"))
    targets = pbp.filter(
        pl.col("pass_attempt") == 1, pl.col("receiver_player_id").is_not_null()
    ).select(pl.col("receiver_player_id").alias("gsis_id"), "week", redzone.alias("redzone"))
    passes = pbp.filter(
        pl.col("pass_attempt") == 1, pl.col("passer_player_id").is_not_null()
    ).select(pl.col("passer_player_id").alias("gsis_id"), "week", redzone.alias("redzone"))

    touches = pl.concat([rush, targets, passes], how="vertical")
    return touches.group_by("gsis_id", "week").agg(
        pl.col("redzone").sum().cast(pl.Int64).alias("redzone_touches"),
    )


def _load_ff_opportunity(year: int) -> pl.DataFrame:
    """Return (gsis_id, week, *expected-points components) from ffverse's ff_opportunity model.

    The empirical Quality basis (DECISION_READS §1): ffverse fits, from historical play-by-play, the
    **expected** fantasy value of each chance (target depth / air yards, field position, down &
    distance) and exposes it as per-component expectations — `receptions_exp`, `rec_yards_gained_exp`,
    `rec_touchdown_exp`, `rush_*_exp`, `pass_*_exp`, `*_first_down_exp`, `*_two_point_conv_exp`. The
    read re-scores these under the league's settings (`_scoring.expected_points_expr`) at the
    consumption layer — so the fetcher stores the raw components, scoring-agnostic. `player_id` is
    gsis_id (joins like every other source here). Non-null ids, REG weeks (≤ 18) — 1 row per
    (gsis, week).
    """
    df = nflreadpy.load_ff_opportunity(year, stat_type="weekly").filter(
        pl.col("player_id").is_not_null() & (pl.col("week") <= 18)
    )
    return df.select(
        pl.col("player_id").alias("gsis_id"),
        pl.col("week").cast(pl.Int64),
        *_scoring.EXP_COMPONENT_COLS,
    )


def _fetch_and_save(year: int, week: int | None = None) -> None:
    """Core assembly: join all sources, derive columns, write parquet."""
    print(f"  Loading player stats ({year}" + (f" week {week}" if week else "") + ")...")
    stats = _load_player_stats(year)
    if week is not None:
        stats = stats.filter(pl.col("week") == week)

    print("  Building player ID map...")
    id_map = _build_player_id_map()

    stats = stats.join(
        id_map.select(["gsis_id", "sleeper_player_id"]),
        left_on="player_id", right_on="gsis_id", how="left",
    )

    print("  Loading snap counts...")
    snaps = _load_snap_pct(year)
    if week is not None:
        snaps = snaps.filter(pl.col("week") == week)
    stats = stats.join(snaps, left_on=["player_id", "week"], right_on=["gsis_id", "week"], how="left")

    print("  Loading team stats...")
    rates = _load_team_rates(year)
    if week is not None:
        rates = rates.filter(pl.col("week") == week)
    stats = stats.join(rates, on=["team", "week"], how="left")

    print("  Loading red-zone touches (companion evidence)...")
    redzone = _load_redzone_touches(year)
    if week is not None:
        redzone = redzone.filter(pl.col("week") == week)
    stats = stats.join(
        redzone, left_on=["player_id", "week"], right_on=["gsis_id", "week"], how="left"
    ).with_columns(pl.col("redzone_touches").fill_null(0))

    print("  Loading ff_opportunity expected-points components (Quality axis)...")
    ff_opp = _load_ff_opportunity(year)
    if week is not None:
        ff_opp = ff_opp.filter(pl.col("week") == week)
    stats = stats.join(
        ff_opp, left_on=["player_id", "week"], right_on=["gsis_id", "week"], how="left"
    ).with_columns(
        [pl.col(c).fill_null(0.0) for c in _scoring.EXP_COMPONENT_COLS]
    )

    stats = stats.with_columns([
        (pl.col("receiving_air_yards") / pl.col("targets").replace(0, None)).alias("adot"),
        pl.lit(datetime.now(timezone.utc).replace(tzinfo=None)).alias("fetched_at"),
    ])

    data_layer.write_nfl_stats(stats, year, week=week)
    print(f"  Wrote {len(stats)} rows → snapshots/nflreadpy/nfl_stats_{year}.parquet")


# --- Expected-points additive backfill (Session 3c) ----------------------------------------------
# The 2020–2024 nfl_stats parquets were built BEFORE _load_ff_opportunity was added to the fetcher, so they
# carry none of the *_exp components the §1 Quality axis reads; 2025 was built after and has all 14. Rather
# than re-pull the whole season (the moving-source trap — realized stats/positions drift, which would move
# the FROZEN corpus and invalidate the 3b spine, §1.7), these functions ADDITIVELY append the components
# onto the existing parquets: every pre-existing column stays byte-identical, only the *_exp columns are
# added. The join mirrors _fetch_and_save exactly (left join on (player_id/gsis_id, week) + fill_null(0.0)).

_EXP_BACKFILL_SEASONS = (2020, 2021, 2022, 2023, 2024)   # 2025 already carries *_exp (built post-join)
_EXP_MAX_NULL_RATE = 0.02   # a served-but-mostly-null component is as bad as an absent one (std instr 1)


def precheck_exp(years=_EXP_BACKFILL_SEASONS) -> dict:
    """Feasibility pre-check (Session 2's schema-honesty discipline): confirm ff_opportunity SERVES all 14
    EXP_COMPONENT_COLS, populated, for every year — BEFORE any additive write. A season that doesn't serve
    them (or serves them mostly-null) would silently re-create the exact TEST-only Quality gap under a new
    guise (standing instruction 1 — a clean zero is a bug). Reads the RAW source (not _load_ff_opportunity,
    whose select assumes every component present) so a missing column is reported, not crashed on. Reports
    per-year presence + worst null-rate; returns the per-year dict plus a top-level `ok`. No writes."""
    report = {}
    for yr in years:
        raw = nflreadpy.load_ff_opportunity(yr, stat_type="weekly").filter(
            pl.col("player_id").is_not_null() & (pl.col("week") <= 18)
        )
        present = [c for c in _scoring.EXP_COMPONENT_COLS if c in raw.columns]
        missing = [c for c in _scoring.EXP_COMPONENT_COLS if c not in raw.columns]
        null_rates = {c: float(raw[c].is_null().mean()) for c in present}
        worst = max(null_rates.values()) if null_rates else 1.0
        report[yr] = {
            "rows": raw.height, "present": len(present), "missing": missing,
            "worst_null_rate": round(worst, 4), "ok": (not missing) and (worst <= _EXP_MAX_NULL_RATE),
        }
    all_ok = all(r["ok"] for r in report.values())
    n = len(_scoring.EXP_COMPONENT_COLS)
    print("=== ff_opportunity *_exp feasibility pre-check ===")
    for yr, r in report.items():
        print(f"  {yr}: {r['present']}/{n} components present, worst null-rate {r['worst_null_rate']:.4f}  "
              f"{'OK' if r['ok'] else '✗ FAIL'}" + (f"  MISSING {r['missing']}" if r["missing"] else ""))
    print(f"  → {'ALL SEASONS SERVE THE COMPONENTS' if all_ok else 'STOP — a season is unserved/mostly-null'}")
    report["ok"] = all_ok
    return report


def backfill_exp(year: int) -> dict:
    """Additively append the 14 ff_opportunity expected-points components onto the EXISTING nfl_stats season
    parquet, WITHOUT re-pulling player stats / snaps / team-rates / red-zone (the moving-source trap, §1.7).
    Left-join _load_ff_opportunity on (player_id==gsis_id, week) + fill_null(0.0) — the same join the fetcher
    does at _fetch_and_save — preserving the EXISTING row order (a byte-identical additive backfill, not a
    rebuild). Every pre-existing column is ASSERTED byte-identical and the row count unchanged; only the
    *_exp columns are added. Idempotent (a re-run drops the prior *_exp and re-adds the same values)."""
    existing = data_layer.read_nfl_stats(year)
    exp_present = [c for c in _scoring.EXP_COMPONENT_COLS if c in existing.columns]
    base = existing.drop(exp_present)              # clean slate so a re-run is idempotent
    pre_cols = base.columns

    ff = _load_ff_opportunity(year).with_columns(
        pl.col("week").cast(base.schema["week"])   # match the stored week dtype (Int32) for the join key
    )
    augmented = base.join(
        ff, left_on=["player_id", "week"], right_on=["gsis_id", "week"], how="left",
        maintain_order="left",
    ).with_columns([pl.col(c).fill_null(0.0) for c in _scoring.EXP_COMPONENT_COLS])

    # Additive-only guarantees (standing instruction 2, inverted — the ONLY change may be the 14 appended
    # columns): no row added/removed, and every pre-existing column byte-identical to what was on disk.
    if augmented.height != base.height:
        raise RuntimeError(f"backfill_exp({year}): row count {base.height}→{augmented.height} "
                           f"(non-unique ff_opportunity (gsis, week) key) — aborting, not additive")
    moved = [c for c in pre_cols if not augmented[c].equals(existing[c])]
    if moved:
        raise RuntimeError(f"backfill_exp({year}): pre-existing columns moved {moved[:5]} — NOT additive")

    data_layer.write_nfl_stats(augmented, year)
    added = list(_scoring.EXP_COMPONENT_COLS)
    nonzero = {c: round(float((augmented[c] != 0.0).mean()), 3) for c in ("receptions_exp", "rush_touchdown_exp")}
    print(f"  {year}: +{len(added)} *_exp cols ({base.width}→{augmented.width}); {augmented.height} rows "
          f"unchanged; nonzero% {nonzero}")
    return {"year": year, "rows": augmented.height, "added": len(added),
            "cols_before": base.width, "cols_after": augmented.width}


def backfill_exp_all(years=_EXP_BACKFILL_SEASONS) -> None:
    """Pre-check THEN backfill (Session 2's discipline: don't write a partial substrate). Aborts before ANY
    write if the pre-check fails for a season."""
    report = precheck_exp(years)
    if not report["ok"]:
        raise SystemExit("Feasibility pre-check FAILED — no *_exp written (standing instruction 1).")
    print("\n=== additive *_exp backfill (2020–2024) ===")
    for yr in years:
        backfill_exp(yr)
    print("  done — 2025 left untouched (already carries *_exp).")


def backfill(year: int) -> None:
    """Pull the full season for a given year and write to snapshots."""
    print(f"Backfilling {year}...")
    _fetch_and_save(year)
    print(f"Backfill complete for {year}.")


def refresh() -> None:
    """Pull the most recently completed week of the current season."""
    year = nflreadpy.get_current_season()
    print(f"Detecting most recent REG week for {year}...")
    df = nflreadpy.load_player_stats(year, summary_level="week").filter(
        pl.col("season_type") == "REG"
    )
    if df.is_empty():
        print(f"No REG season data available for {year}. Nothing to refresh.")
        return
    week = df["week"].max()
    print(f"Refreshing {year} week {week}...")
    _fetch_and_save(year, week=week)
    print(f"Refresh complete ({year} week {week}).")


if __name__ == "__main__":
    usage = ("Usage: python3 -m application.data.fetchers.nfl_stats "
             "{backfill <year> | refresh | precheck-exp | backfill-exp <year|all>}")
    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "backfill":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        backfill(int(sys.argv[2]))
    elif cmd == "refresh":
        refresh()
    elif cmd == "precheck-exp":
        precheck_exp()
    elif cmd == "backfill-exp":
        if len(sys.argv) < 3:
            print(usage)
            sys.exit(1)
        if sys.argv[2] == "all":
            backfill_exp_all()
        else:
            backfill_exp(int(sys.argv[2]))
    else:
        print(usage)
        sys.exit(1)
