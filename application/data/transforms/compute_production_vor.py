"""
Compute Production VOR — value over replacement from the borrowed projection (DECISION_READS.md §4).

The first read that *consumes* the Phase-2 projection substrate. For every rostered skill
player it answers the roster-management question behind adds/drops: **is this player worth
more than what's sitting on waivers, and by how much on a scale I can compare across
positions?** Per design law 3 it borrows the projection (never builds one) and adds only the
decision layer: anchoring and normalisation.

  - ros_value: rest-of-season production = the sum of the borrowed weekly consensus centres
    (projection_consensus.center_ppr, the §3 band's p50) over the player's **remaining**
    schedule (weeks > the as-of cutoff N). Borrowed, not built. Using each week's own centre
    over the remaining weeks is the best ROS proxy the substrate offers — richer than a single
    static preseason number, and it flows straight from the transform Build 1 just shipped.
  - waiver_line: the replacement level = the best **available** (unrostered as of N) player's
    ros_value in that player's pool. Volatile by design (§4): drop a stud and the line jumps.
  - pool_top: the best rosterable player's ros_value in the pool (the pool's ceiling).
  - vor = (ros_value − waiver_line) / (pool_top − waiver_line): waiver line = 0, a top
    rosterable player ≈ 1, negative = dead weight (below what's freely available). Normalised
    by the **pool spread** (top − waiver), not by the waiver value — §4's settled choice: the
    spread stays stable where a waiver-denominator would collapse, and a tiny spread reads as a
    real "no separation at this position" signal rather than blowing up.

**Pools (§4 flex reconciliation).** Projected points is the common currency. The league's
dedicated QB slot is its own pool (best available QB); the flex-eligible positions (RB/WR/TE,
from lineup_slots' FLEX eligibility) share **one pooled waiver line** — the best available
flex-eligible player — so a bench WR and a bench RB are measured against the same replacement.
Both pools are anchored waiver = 0 and divided by their own spread, so QB and flex VORs land on
one comparable, unit-free scale. **Documented simplifications:** (1) the pooled flex line does
not model dedicated-slot scarcity (a scarce TE is measured against the flex replacement, which
is usually a WR/RB — §4's deliberate settled choice, not slot-aware marginal value); (2) this is
a **1QB league** (lineup_slots has a dedicated QB slot, QB not flex-eligible) — a superflex/2QB
league would drop QB into the flex pool and is the latent assumption to revisit then. Market VOR
(LeagueLogs) and the Production−Market trade gap are V4, out of scope here.

Tall over as_of_week like the three team/player analytics: for each cutoff N = 1..maxweek the
roster is resolved **as of N** (a player's latest team ≤ N — roster-as-of-N, the same idiom as
compute_player_signal.py) and the ROS sums the weeks after N. Roster membership comes from the
season join, which is frozen at weeks 1–4, so N is bounded there; the projection horizon runs to
week 18. read via read_production_vor(season, as_of_week=None) (default = latest).

Output: snapshots/derived/production_vor_{season}.parquet, one row per (as_of_week, rostered player).

Usage:
    python3 -m application.data.transforms.compute_production_vor --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1, position_pools
from application.data.transforms._scoring import scoring_profile, actual_points_expr, standard_scoring
# FORM_ANCHOR_W (the S7 de-bias λ) is homed in the L4 dials registry and re-exported here so its canonical
# path (production_vor.FORM_ANCHOR_W) and any `from …import FORM_ANCHOR_W` resolve. Ships at 0.0 → identity.
from application.data.transforms._constants import FORM_ANCHOR_W  # noqa: F401  (re-exported dial)

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def recent_ppg_expr(as_of) -> pl.Expr:
    """The canonical 'recent form' term — mean(pts | wk ≤ as_of), leak-safe. This is the `recent` half of the
    scorer's declared `recent_ppg_forward` naive (compute_engine_scorecard._naive_forward_points), the signal
    L3 proved beats the borrowed centre. ONE definition, reused by the de-bias blend so it can't drift from
    the baseline it is measured against (standing instr 5). The points column must be `pts`, weeks `week`;
    `as_of` is an int or a pl.Expr."""
    return pl.col("pts").filter(pl.col("week") <= as_of).mean()


def _resolve_scoring(season: int, scoring_key, *, reader=data_layer):
    """The scoring dict for the read's centre basis, so recent-form is scored the SAME way the borrowed
    centre was (compute_projection_consensus scores actuals via actual_points_expr on this dict). None →
    the persisted league settings (is_mine default); an explicit standard key → its canonical profile; a
    custom key with no resolvable standard profile → None (→ recent-form unavailable → pure borrowed centre,
    the documented graceful fallback that keeps λ=0 identity and the transform runnable everywhere)."""
    if scoring_key is None:
        return reader.read_scoring_settings(season)
    try:
        return standard_scoring(scoring_key)
    except (KeyError, ValueError):
        return None


def _realized_weekly_pts(season: int, scoring, *, reader=data_layer) -> pl.DataFrame:
    """Per (player, week) realized points scored under `scoring` — the de-bias recent-form input. Derived the
    SAME way compute_projection_consensus builds its actuals (nfl_stats via actual_points_expr), so recent-form
    shares the borrowed centre's scoring basis (== canonical for ppr/half/std). Scoring-scoped / league-
    independent, so the de-biased ros_center stays identical for production_vor AND the band (the L0 no-
    regression invariant). Returns (sleeper_player_id, week, pts); empty when scoring is unresolvable."""
    if scoring is None:
        return pl.DataFrame(schema={"sleeper_player_id": pl.Utf8, "week": pl.Int64, "pts": pl.Float64})
    profile = scoring_profile(scoring)
    return (
        reader.read_nfl_stats(season)
        .select(
            "sleeper_player_id", pl.col("week").cast(pl.Int64),
            actual_points_expr(profile, scoring).alias("pts"),
        )
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        # `.max()` (not `.first()`): a two-way player can have >1 nfl_stats row per (pid, week) with different
        # scored points, and `.first()` is order-dependent under polars' multi-threaded group_by — a promoted
        # λ>0 must recompute value-identical, so reduce dups deterministically (== the single value when
        # there are no dups). Recent-form only feeds the blend at λ>0; the shipped λ=0 is unaffected.
        .agg(pl.col("pts").max())
    )


def _recent_form(realized_pts: pl.DataFrame, n: int) -> pl.DataFrame:
    """Per player: recent_ppg = mean(realized pts | wk ≤ n), for the as-of cutoff N. Leak-safe (only weeks
    ≤ N). Reuses `recent_ppg_expr` (the scorer's naive definition). Players with no realized game in 1..N
    have a null mean and are dropped → they keep the borrowed centre (no evidence to anchor toward).
    Returns (sleeper_player_id, recent_ppg)."""
    return (
        realized_pts.group_by("sleeper_player_id")
        .agg(recent_ppg_expr(n).alias("recent_ppg"))
        .drop_nulls("recent_ppg")
    )


def _pool_of(lineup_slots: pl.DataFrame) -> dict:
    """position → pool key (the §4 replacement pool), derived from the league's declared lineup slots.

    Delegates to the shared `_analytics.position_pools`: positions sharing a multi-position slot are
    pooled against one waiver line; dedicated-only positions are their own pool. Standard 1QB →
    QB/'FLEX'; **superflex → QB joins the flex pool** (`SUPER_FLEX`), removing the old latent that
    matched only a slot literally named 'FLEX'. Config-driven, no hard-coding.
    """
    return position_pools(lineup_slots.to_dicts())


def _ros_values(consensus: pl.DataFrame, remaining_weeks, *,
                recent_form: pl.DataFrame | None = None,
                form_anchor_w: float | None = None) -> pl.DataFrame:
    """Per player: rest-of-season production value = the borrowed ROS centre, DE-BIASED toward recent form
    (DECISION_READS.md §2/§4; Session 7). `consensus` carries (week, sleeper_player_id, position, center_ppr)
    for the whole projected pool; `remaining_weeks` are the weeks strictly after the cutoff. One row per
    player with any projected remaining week (position = his projected position).

    The de-bias is a SECOND anchor (the first is the band's preseason ADP anchor) — a convex blend of two
    series the substrate already carries (design law 3: the decision layer, not a projection model):

        ros_value = (1-λ)·borrowed_ros_centre + λ·(recent_ppg × n_weeks),   λ = form_anchor_w

    where borrowed_ros_centre = Σ center_ppr over the remaining weeks (today's value) and recent_ppg is
    `recent_form`'s mean(pts|wk≤N). recent_ppg × n_weeks reuses the SAME remaining-week count, so the blend
    is convex and on one ROS-points scale. Both production_vor and the band call this, so a single blend
    de-biases both identically.

    **λ=0 (the shipped default) OR no recent-form is a STRICT no-op** — short-circuited to the borrowed sum,
    byte-identical to the frozen spine (standing instr 2). Players absent from `recent_form` (no realized
    sample in 1..N) keep the borrowed centre — no evidence to anchor toward.

    `form_anchor_w=None` reads the live registry dial `FORM_ANCHOR_W` at call time (so promotion / a gate
    flipping the module global takes effect); the tuner passes an explicit λ per swept candidate.
    """
    lam = FORM_ANCHOR_W if form_anchor_w is None else float(form_anchor_w)
    borrowed = (
        consensus.filter(pl.col("week").is_in(list(remaining_weeks)))
        .group_by("sleeper_player_id")
        .agg(
            pl.col("position").first().alias("position"),
            pl.col("center_ppr").sum().alias("ros_value"),
            pl.len().alias("n_weeks"),
        )
    )
    if not lam or recent_form is None:
        return borrowed
    return (
        borrowed.join(recent_form.select("sleeper_player_id", "recent_ppg"),
                      on="sleeper_player_id", how="left")
        .with_columns(
            pl.when(pl.col("recent_ppg").is_not_null())
            # .round(6): the blend can land EXACTLY on a downstream round1 boundary (x.x5), where polars'
            # vectorized float arithmetic flakes at the ULP (…44999999 vs …45000001) and round1 flips run-to-
            # run. Rounding to 6 dp collapses the ULP flake so round1 is deterministic (a promoted λ must
            # recompute value-identical). 6 dp is far below the round1 the reads apply, so it moves no number.
            .then(((1.0 - lam) * pl.col("ros_value") + lam * pl.col("recent_ppg") * pl.col("n_weeks")).round(6))
            .otherwise(pl.col("ros_value"))
            .alias("ros_value")
        )
        .select("sleeper_player_id", "position", "ros_value", "n_weeks")
    )


def _pool_lines(ros: pl.DataFrame, rostered_ids: set, pool_of: dict) -> dict:
    """Per pool: the waiver line (best ros_value among **unrostered** players) and the top
    (best ros_value among all). Pure — `ros` is the per-player ROS frame, `rostered_ids` the
    set on any roster as of the cutoff, `pool_of` the position→pool map. Returns
    pool → {"waiver": float, "top": float}."""
    lines: dict = {}
    tagged = ros.with_columns(
        pl.col("position").replace_strict(pool_of, default=None).alias("pool"),
        pl.col("sleeper_player_id").is_in(list(rostered_ids)).alias("rostered"),
    )
    for pool, g in tagged.group_by("pool"):
        pool = pool[0]
        if pool is None:
            continue
        top = float(g["ros_value"].max())
        avail = g.filter(~pl.col("rostered"))
        waiver = float(avail["ros_value"].max()) if avail.height else 0.0
        lines[pool] = {"waiver": waiver, "top": top}
    return lines


def _vor(ros_value: float, waiver: float, top: float) -> float:
    """(ros − waiver) / (top − waiver): waiver line = 0, pool top ≈ 1, negative = dead weight.
    A non-positive spread (degenerate pool with no separation) falls back to 0.0 at/below the
    line — §4's "tiny spread = no separation" read, guarded against a divide-by-zero blowup."""
    spread = top - waiver
    if spread <= 0.0:
        return 0.0
    return (ros_value - waiver) / spread


def _roster_as_of(season_df: pl.DataFrame, n: int) -> dict:
    """sleeper_player_id → roster_id as of week N: the team a player belonged to in his latest
    week ≤ N (arg_max over the ≤ N slice) — the roster-as-of-N idiom shared with
    compute_player_signal, so a mid-season trade/add changes who is on
    the team at week N, not just their numbers."""
    sub = season_df.filter(pl.col("week") <= n)
    return {
        row["sleeper_player_id"]: int(row["roster_id"])
        for row in sub.group_by("sleeper_player_id")
        .agg(pl.col("roster_id").sort_by("week").last().alias("roster_id"))
        .iter_rows(named=True)
    }


def _compute_as_of(consensus: pl.DataFrame, season_df: pl.DataFrame, n: int, max_proj_week: int,
                   season: int, *, pool_of: dict, two_way_ids=frozenset(),
                   realized_pts: pl.DataFrame | None = None) -> list:
    """Production VOR rows for one as-of cutoff N: resolve the roster as of N, value every
    projected player's remaining schedule (de-biased toward recent form through week N), set each pool's
    waiver/top from who's available, then score the rostered players. Returns row dicts tagged as_of_week =
    N. `two_way_ids` is the set of `is_two_way` players (from join_season) — carried through as a first-class
    flag so the scorer can slice the cross-position answer-key points out. `realized_pts` (per-player weekly
    realized points) feeds the de-bias recent-form anchor; None → pure borrowed centre (λ=0 identity)."""
    roster = _roster_as_of(season_df, n)
    rostered_ids = set(roster)
    remaining = range(n + 1, max_proj_week + 1)
    if not remaining:
        return []

    recent_form = _recent_form(realized_pts, n) if realized_pts is not None else None
    ros = _ros_values(consensus, remaining, recent_form=recent_form)
    lines = _pool_lines(ros, rostered_ids, pool_of)

    rows = []
    for r in ros.filter(pl.col("sleeper_player_id").is_in(list(rostered_ids))).iter_rows(named=True):
        pool = pool_of.get(r["position"])
        line = lines.get(pool)
        if line is None:
            continue
        rows.append({
            "season": season,
            "as_of_week": n,
            "roster_id": roster[r["sleeper_player_id"]],
            "sleeper_player_id": r["sleeper_player_id"],
            "position": r["position"],
            "pool": pool,
            "ros_value": round1(r["ros_value"]),
            "n_weeks": int(r["n_weeks"]),
            "waiver_line": round1(line["waiver"]),
            "pool_top": round1(line["top"]),
            "vor": round(_vor(r["ros_value"], line["waiver"], line["top"]), 3),
            "is_two_way": r["sleeper_player_id"] in two_way_ids,
        })
    return rows


def compute(season: int, *, league_id=None, scoring_key=None) -> pl.DataFrame:
    consensus = data_layer.read_projection_consensus(season, scoring_key=scoring_key).select(
        "week", "sleeper_player_id", "position", "center_ppr"
    ).filter(pl.col("position").is_in(SKILL_POSITIONS))
    season_df = data_layer.read_join_season(season, league_id=league_id).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    )
    pool_of = _pool_of(data_layer.read_lineup_slots(season, league_id=league_id))
    # is_two_way rides join_season from 3a; carry the flagged-player set onto the VOR rows (it may be
    # absent on a pre-3a join — then no player is flagged, not an error).
    two_way_ids = (set(season_df.filter(pl.col("is_two_way"))["sleeper_player_id"].to_list())
                   if "is_two_way" in season_df.columns else frozenset())
    # De-bias recent-form anchor (S7): realized weekly points on the centre's own scoring basis. Consumed
    # only when FORM_ANCHOR_W>0 (the shipped 0.0 short-circuits to the borrowed centre — value-identical).
    realized_pts = _realized_weekly_pts(season, _resolve_scoring(season, scoring_key))

    max_proj_week = int(consensus["week"].max())
    max_roster_week = int(season_df["week"].max())  # roster data frozen here (season join)

    all_rows = []
    for n in range(1, max_roster_week + 1):
        all_rows.extend(_compute_as_of(consensus, season_df, n, max_proj_week, season,
                                       pool_of=pool_of, two_way_ids=two_way_ids,
                                       realized_pts=realized_pts))

    # sleeper_player_id is the unique tie-break: within a (as_of_week, roster_id) many players share a
    # rounded vor, so a sort on vor alone is parallelism-dependent (the 1.7 lesson). One row per
    # (as_of_week, sleeper_player_id) ⇒ it fully orders the frame → byte-stable output.
    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "roster_id", "vor", "sleeper_player_id", descending=[False, False, True, False]
    )
    latest = df.filter(pl.col("as_of_week") == max_roster_week)
    print(f"=== Production VOR: season={season}  as_of_week 1..{max_roster_week}  "
          f"(ROS horizon → week {max_proj_week}; rows={df.height}) ===")
    for pool in ("QB", "FLEX"):
        pl_slice = latest.filter(pl.col("pool") == pool)
        if pl_slice.height:
            w = pl_slice["waiver_line"][0]
            t = pl_slice["pool_top"][0]
            print(f"  week {max_roster_week} {pool:<4} pool: waiver_line={w}  pool_top={t}  "
                  f"(rostered={pl_slice.height})")
    print(f"  week {max_roster_week} top VOR (rostered):")
    print(latest.head(6).select("sleeper_player_id", "position", "ros_value", "waiver_line", "pool_top", "vor"))
    print(f"  week {max_roster_week} dead weight (negative VOR): {latest.filter(pl.col('vor') < 0).height}")
    return df


def run(season: int, *, league_id=None, scoring_key=None) -> None:
    df = compute(season, league_id=league_id, scoring_key=scoring_key)
    data_layer.write_production_vor(df, season, league_id=league_id)
    lid = league_id or data_layer._active_league(season)[0]
    print(f"  → snapshots/derived/league/{lid}/production_vor_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute Production VOR from the borrowed projection.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
