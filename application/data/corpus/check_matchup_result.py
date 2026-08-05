"""
check_matchup_result.py — the gate for what a matchup RESULT is (P2 Gate-A fix).

`_derive_matchup_result` used to rank a matchup with `sort_by(points, descending).first()` and had no
tie branch, so three shapes with no winner were each given one anyway — decided by roster-id sort order:

  * an UNPLAYED slate. Sleeper returns a full, paired week at `points: 0.0` from the DRAFT onward, so a
    freshly drafted 2026 league minted 6 W and 6 L before a single game was played. The Gate-A blocker.
  * a GENUINE TIE (both sides played, equal points) — a real outcome the sim already scored 0.5/0.5.
  * a NULL matchup_id (playoff weeks; 2025 wk18 is entirely null). Polars groups nulls as ONE group, so
    the whole league became a single 'matchup' with one winner and everyone else an L.

All three now resolve through `transforms/_matchup`, the single definition the join reads vectorized and
`compute_bracket_sim._standings_as_of` reads row-wise.

  1. SEMANTICS — the real `_derive_matchup_result` on the shapes above: unplayed → null, tie → T/T, null
     matchup_id → null (not one W and 13 L), bye → null, normal → W/L, all five in one frame graded
     independently, and an empty frame still carrying a typed `pl.Utf8` column (the diagonal-concat
     contract `data_layer.write_join_nfl_sleeper_weekly` appends weeks under).
  2. ONE DEFINITION, TWO SHAPES — `is_gradeable` (row-wise) and `gradeable_expr` (vectorized) agree
     case-for-case. They cannot be collapsed into one another (`map_elements` is banned), so the thing
     that stops them drifting is this check.
  3. DEMO-SLATE PARITY — the parity oracle. Re-deriving every served slice's verdict from the RAW
     matchups reproduces the persisted `matchup_result` exactly. The 31 demo slices contain no tie, no
     all-zero group, no null matchup_id and no non-pair group, so a correct fix is value-identical
     there — any diff is a defect in the fix, not a change in the data.
  4. THE FOUR CORPUS TIES — measured, named, allowlisted. Across all 271 league-seasons (696,437 rows /
     21,642 matchup groups) there are exactly four genuine ties and nothing else degenerate, so corpus
     parity is "unchanged except these four", not blanket identity — a blanket gate would FALSE-FAIL a
     correct fix. The persisted rows are also asserted still W/L: that is a tripwire for anyone silently
     re-joining the frozen corpus the L2 ledger derives from.

Prove-it-bites (a gate that can't fail is not a gate): the shipped bug is the bite. `_legacy_result_expr`
is the old expression, frozen verbatim, and it must FAIL checks 1 and 2 on the same fixtures.

Run: python3 -m application.data.corpus.check_matchup_result [--rejoin-slices N] [--full-corpus]
"""
import argparse
import contextlib
import io
import shutil
import sys

import polars as pl

from application.data import data_layer
from application.data.transforms import _matchup, join_nfl_sleeper_weekly

# The four genuine ties in the corpus — (league_id, season, week, matchup_id, points-per-side).
# Measured 2026-08-05 over all 271 persisted joins; both sides played and scored identically.
_KNOWN_TIES = (
    ("1048227402238918656", 2024, 4, 4, 141.70),
    ("1124832205898522624", 2024, 6, 1, 142.32),
    ("784402021942943744", 2022, 2, 6, 165.48),
    ("860961965311410176", 2022, 5, 4, 144.36),
)

_TMP_LEAGUE = "__MATCHUPRESULT__"


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:64} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality: same columns + same VALUES, ignoring row order. Determinism is a
    property of the joined VALUES, not the parquet byte stream — polars' writer is physically
    non-deterministic, so a raw byte-hash flakes ~8%. (check_harvest / check_spine carry the same helper.)"""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


# --- fixtures -----------------------------------------------------------------------------------------

_JOIN_SCHEMA = {
    "sleeper_player_id": pl.Utf8, "roster_id": pl.Int64, "matchup_id": pl.Int64,
    "sleeper_points": pl.Float64, "is_starter": pl.Boolean, "roster_total_points": pl.Float64,
}


def _fixture(specs, players_per_roster=2) -> pl.DataFrame:
    """A one-week Sleeper frame in `_parse_sleeper_matchups` shape from [(roster_id, matchup_id, total)].

    Player-grain, like the real thing: `roster_total_points` repeats across a roster's rows, which is
    exactly the shape the window expression has to be correct over."""
    rows = [
        {"sleeper_player_id": f"p{rid}_{k}", "roster_id": rid, "matchup_id": mid,
         "sleeper_points": 0.0, "is_starter": True, "roster_total_points": tot}
        for rid, mid, tot in specs for k in range(players_per_roster)
    ]
    return pl.DataFrame(rows, schema=_JOIN_SCHEMA)


# The five shapes, defined once and reused by checks 1, 2 and the prove-bites block.
#   name -> (specs, expected {roster_id: result})
_SHAPES = {
    # The Gate-A reproduction: 12 rosters, paired matchup_ids 1-6, every roster at 0.0.
    "unplayed": ([(r, (r - 1) // 2 + 1, 0.0) for r in range(1, 13)],
                 {r: None for r in range(1, 13)}),
    "tie": ([(3, 1, 141.7), (9, 1, 141.7)], {3: "T", 9: "T"}),
    # Higher total on the HIGHER roster_id on purpose: the old bug degenerated to "lowest roster_id
    # wins", so an id-ordered fixture would pass under the bug and prove nothing.
    "normal": ([(3, 1, 99.5), (9, 1, 120.0)], {3: "L", 9: "W"}),
    "null_matchup": ([(r, None, 100.0 + r) for r in range(1, 15)],
                     {r: None for r in range(1, 15)}),
    "bye": ([(7, 4, 133.0)], {7: None}),
}


def _verdicts(df: pl.DataFrame) -> dict:
    """{roster_id: matchup_result} from a graded frame, asserting the value is constant per roster."""
    out = {}
    for rid, g in df.group_by("roster_id"):
        vals = set(g["matchup_result"].to_list())
        rid = int(rid[0]) if isinstance(rid, tuple) else int(rid)
        out[rid] = vals.pop() if len(vals) == 1 else f"<inconsistent:{sorted(map(str, vals))}>"
    return out


def _legacy_result_expr(*, total="roster_total_points", over="matchup_id") -> pl.Expr:
    """The SHIPPED BUG, frozen verbatim (join_nfl_sleeper_weekly.py:189-205 before this fix).

    It has two jobs. It is the prove-bites bite — every check must fail on real defective output rather
    than a strawman. And it is the PARITY ORACLE's other half: "a correct fix leaves every historical
    league unchanged" is precisely "legacy and new agree", which is a cleaner comparison than
    new-vs-persisted because the persisted artifact also carries POST-join repairs (`audit_join`) that
    were never the join's own output.

    The original used a group_by + left join; expressed as a window it is the same thing: the roster with
    the max points, ties broken by row order, and no branch that can produce a tie or a null."""
    winner = pl.col("roster_id").sort_by(total, descending=True).first().over(over)
    return pl.when(pl.col("roster_id") == winner).then(pl.lit("W")).otherwise(pl.lit("L")).cast(pl.Utf8)


# --- checks -------------------------------------------------------------------------------------------

def _check_semantics(results):
    print("  1 — semantics (the real _derive_matchup_result on every shape):")
    for name, (specs, expect) in _SHAPES.items():
        got = _verdicts(join_nfl_sleeper_weekly._derive_matchup_result(_fixture(specs)))
        _ok(f"{name}: graded as expected", got == expect, results,
            "" if got == expect else f"got {got}")

    # The null-matchup_id defect had a specific WRONG shape — one W and everyone else L. Assert the
    # absence of that shape by name, not just "not equal to expected".
    got = join_nfl_sleeper_weekly._derive_matchup_result(_fixture(_SHAPES["null_matchup"][0]))
    _ok("null matchup_id: not one league-wide winner", (got["matchup_result"] == "W").sum() == 0, results)

    # Every shape in ONE frame — proves the window is per-matchup, not per-frame.
    mixed_specs = [s for name in ("unplayed", "tie", "normal", "bye", "null_matchup")
                   for s in _renumber(name)]
    mixed_expect = {rid: res for name in ("unplayed", "tie", "normal", "bye", "null_matchup")
                    for rid, res in _renumber_expect(name).items()}
    got = _verdicts(join_nfl_sleeper_weekly._derive_matchup_result(_fixture(mixed_specs)))
    _ok("all five shapes in one frame, graded independently", got == mixed_expect, results,
        "" if got == mixed_expect else f"got {got}")

    # The empty-week path: `_parse_sleeper_matchups` returns this typed frame, and the season append
    # concats how="diagonal" under strict dtypes — a Null-dtype column would break week 1 of a new league.
    empty = join_nfl_sleeper_weekly._derive_matchup_result(pl.DataFrame([], schema=_JOIN_SCHEMA))
    _ok("empty frame keeps a typed pl.Utf8 matchup_result column",
        empty.height == 0 and empty.schema.get("matchup_result") == pl.Utf8, results,
        f"dtype={empty.schema.get('matchup_result')}")


# Roster/matchup ids are disjoint per shape so the shapes can be stacked into one frame.
_OFFSET = {"unplayed": (0, 0), "tie": (20, 20), "normal": (40, 40), "bye": (60, 60),
           "null_matchup": (80, 80)}


def _renumber(name):
    ro, mo = _OFFSET[name]
    return [(rid + ro, (mid + mo) if mid is not None else None, tot)
            for rid, mid, tot in _SHAPES[name][0]]


def _renumber_expect(name):
    ro, _ = _OFFSET[name]
    return {rid + ro: res for rid, res in _SHAPES[name][1].items()}


def _gradeable_vectorized(specs) -> dict:
    """{matchup_key: bool} from `gradeable_expr` — the vectorized half of the one definition."""
    df = _fixture(specs).with_columns(_matchup.gradeable_expr().alias("g"))
    return {(int(r["roster_id"])): bool(r["g"]) for r in df.unique(subset=["roster_id"]).iter_rows(named=True)}


def _check_one_definition(results):
    print("  2 — one definition, two shapes (row-wise `is_gradeable` == vectorized `gradeable_expr`):")
    agree = True
    for name, (specs, _expect) in _SHAPES.items():
        vec = _gradeable_vectorized(specs)
        # Group the specs the way the sim sees them: matchup_id -> the totals of its rosters.
        groups: dict = {}
        for rid, mid, tot in specs:
            groups.setdefault(mid, []).append((rid, tot))
        for mid, members in groups.items():
            scalar = _matchup.is_gradeable(mid, [t for _rid, t in members])
            for rid, _tot in members:
                if vec[rid] != scalar:
                    agree = False
                    print(f"      DRIFT {name} roster {rid}: expr={vec[rid]} scalar={scalar}")
    _ok("the two renderings agree on every shape", agree, results)


def _raw_verdicts(lid, season, weeks) -> pl.DataFrame:
    """(week, roster_id, matchup_id, expected, legacy) — verdicts re-derived from the RAW Sleeper
    matchups under BOTH definitions.

    The raw frame is roster-grain (one row per roster) with the total in `points`, so it is the honest
    independent witness: it never went through the join. Multi-week, hence `over=[week, matchup_id]`."""
    grp = ["week", "matchup_id"]
    raw = data_layer.read_season_matchups(season, through_week=max(weeks), league_id=lid)
    return (raw.filter(pl.col("week").is_in(list(weeks)))
            .with_columns(_matchup.result_expr(total="points", over=grp).alias("expected"),
                          _legacy_result_expr(total="points", over=grp).alias("legacy"))
            .select("week", "roster_id", "matchup_id", "expected", "legacy"))


def _parity_diffs(lid, season) -> tuple:
    """(n_team_weeks, changed_frame, persisted_diffs, roster_set_divergences) for one league-season.

    `changed` is the PARITY ORACLE: rows where the new definition disagrees with the frozen legacy
    expression on the same raw input. That is the exact claim "a correct fix leaves every historical
    league unchanged", and it is compared legacy-to-new rather than new-to-persisted on purpose — the
    persisted artifact also carries post-join repairs that were never the join's own output.

    `persisted_diffs` is the separate, weaker observation: where the stored `matchup_result` disagrees
    with what the join would produce today. Reported, not silently folded into the oracle.

    `divergences` counts groups where the raw roster set differs from the join's: the join's group is
    PLAYER-derived (a roster with no `players_points` contributes no rows) while the raw is
    ROSTER-derived, so they can in principle disagree about how many sides a matchup has. Expected 0 —
    reported as a number rather than assumed."""
    join = (data_layer.read_join_season(season, league_id=lid)
            .select("week", "roster_id", "matchup_id", "matchup_result").unique())
    weeks = sorted(int(w) for w in join["week"].unique().to_list())
    if not weeks:
        return 0, join.head(0), join.head(0), 0
    raw = _raw_verdicts(lid, season, weeks)
    changed = raw.filter(~pl.col("expected").eq_missing(pl.col("legacy")))
    merged = join.join(raw.drop("matchup_id"), on=["week", "roster_id"], how="left")
    persisted_diffs = merged.filter(~pl.col("matchup_result").eq_missing(pl.col("expected")))

    join_sides = join.group_by("week", "matchup_id").agg(pl.col("roster_id").n_unique().alias("j"))
    raw_full = (data_layer.read_season_matchups(season, through_week=max(weeks), league_id=lid)
                .filter(pl.col("week").is_in(weeks))
                .group_by("week", "matchup_id").agg(pl.col("roster_id").n_unique().alias("r")))
    sides = join_sides.join(raw_full, on=["week", "matchup_id"], how="inner")
    divergent = sides.filter(pl.col("j") != pl.col("r")).height
    return merged.height, changed, persisted_diffs, divergent


def _check_demo_parity(results, rejoin_slices: int):
    print("  3 — demo-slate parity (the served DB must not move):")
    slices = data_layer.read_demo_manifest().sort("season", "league_id").to_dicts()
    total_rows = total_changed = total_divergent = checked = 0
    stale_null = stale_other = 0
    for s in slices:
        lid, season = str(s["league_id"]), int(s["season"])
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        n, changed, persisted_diffs, divergent = _parity_diffs(lid, season)
        total_rows += n
        total_changed += changed.height
        total_divergent += divergent
        checked += 1
        if changed.height:
            print(f"      CHANGED {lid} {season}: {changed.height} rows")
            print(changed.head(5))
        stale_null += persisted_diffs.filter(pl.col("matchup_result").is_null()).height
        stale_other += persisted_diffs.filter(pl.col("matchup_result").is_not_null()).height
    _ok("no served slice changes verdict (legacy == new)", total_changed == 0 and checked > 0, results,
        f"{checked} slices, {total_rows} team-weeks, {total_changed} changed")
    _ok("join roster-set == raw roster-set (player-grain corner)", total_divergent == 0, results,
        f"{total_divergent} divergent groups")
    # The stored artifact is allowed to hold NULLs the join itself would not produce: `audit_join`'s
    # zero-stat repair rows (`_build_zero_stat_row`) set roster/matchup/points but never `matchup_result`.
    # Pre-existing and harmless — `max(matchup_result)` skips nulls, so the roster-week's other rows still
    # carry the verdict and no served record moves. A stored non-null that DISAGREES would be a real
    # defect, so that is the half held to zero.
    _ok("no stored non-null disagrees with the join's own verdict", stale_other == 0, results,
        f"{stale_other} disagreeing, {stale_null} audit_join null-repair rows")

    if rejoin_slices > 0:
        _check_rejoin(slices[:rejoin_slices], results)


def _check_rejoin(sample, results):
    """End-to-end: stage a slice's raw matchups under a scratch league id, run the REAL join, and check
    the verdicts it writes against the frozen legacy expression. Puts the WHOLE transform in the loop,
    not just the expression — the parity claim is about what a re-join produces, not what an expression
    evaluates to.

    Compared against the legacy derivation rather than the persisted parquet because the persisted file
    also carries `audit_join`'s post-join repair rows, which the join never emitted (see check 3).

    The worktree's snapshots dir is a symlink into main's single store, so an unstaged re-join would
    overwrite canonical corpus data. Everything here is staged and torn down in a `finally`."""
    print("  3b — full re-join parity (staged, never touches canonical data):")
    for s in sample:
        lid, season = str(s["league_id"]), int(s["season"])
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        canonical = data_layer.read_join_season(season, league_id=lid)
        weeks = [w for w in sorted(int(w) for w in canonical["week"].unique().to_list())
                 if data_layer._sleeper_matchups_path(season, w, lid).exists()]
        if not weeks:
            continue
        try:
            for w in weeks:
                dst = data_layer._sleeper_matchups_path(season, w, _TMP_LEAGUE)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(data_layer._sleeper_matchups_path(season, w, lid), dst)
            # Silence the join's own per-week validation report — 13 blocks would bury the verdict.
            with contextlib.redirect_stdout(io.StringIO()):
                for w in weeks:
                    join_nfl_sleeper_weekly.run(season, w, league_id=_TMP_LEAGUE)
            fresh = (pl.read_parquet(data_layer._join_season_path(season, _TMP_LEAGUE))
                     .select("week", "roster_id", "matchup_result").unique())
            legacy = _raw_verdicts(lid, season, weeks).select("week", "roster_id", "legacy")
            merged = fresh.join(legacy, on=["week", "roster_id"], how="left")
            bad = merged.filter(~pl.col("matchup_result").eq_missing(pl.col("legacy")))
            _ok(f"{lid} {season}: re-join verdicts == legacy", bad.height == 0, results,
                f"{len(weeks)} weeks, {merged.height} team-weeks")
            if bad.height:
                print(bad.head(5))
        finally:
            shutil.rmtree(data_layer._sleeper_league_dir(season, _TMP_LEAGUE), ignore_errors=True)
            shutil.rmtree(data_layer._join_league_dir(_TMP_LEAGUE), ignore_errors=True)


def _check_known_ties(results, full_corpus: bool):
    print("  4 — the four genuine corpus ties (allowlist parity, not blanket identity):")
    for lid, season, week, mid, pts in _KNOWN_TIES:
        raw = (data_layer.read_season_matchups(season, through_week=week, league_id=lid)
               .filter((pl.col("week") == week) & (pl.col("matchup_id") == mid)))
        both_at = raw.height == 2 and all(abs(float(p) - pts) < 0.005 for p in raw["points"].to_list())
        graded = set(_raw_verdicts(lid, season, [week])
                     .join(raw.select("roster_id"), on="roster_id", how="inner")["expected"].to_list())
        persisted = set(data_layer.read_join_season(season, league_id=lid)
                        .filter((pl.col("week") == week) & (pl.col("matchup_id") == mid))
                        ["matchup_result"].to_list())
        _ok(f"{lid} {season} wk{week} m{mid}: both sides at {pts}", both_at, results)
        _ok(f"{lid} {season} wk{week} m{mid}: now grades T/T", graded == {"T"}, results, f"{graded}")
        _ok(f"{lid} {season} wk{week} m{mid}: frozen corpus still W/L (tripwire)",
            persisted == {"W", "L"}, results, f"{persisted}")

    if not full_corpus:
        print("      (--full-corpus not set: the 271-league sweep is skipped)")
        return

    print("  4b — full-corpus sweep (every change must be one of the four above):")
    from application.data.corpus import harvest
    expected_keys = {(lid, season, week, mid) for lid, season, week, mid, _p in _KNOWN_TIES}
    changed: set = set()
    scanned = 0
    for r in harvest.targets():
        lid, season = str(r["league_id"]), int(r["season"])
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        scanned += 1
        _n, changed_rows, _p, _d = _parity_diffs(lid, season)
        for row in changed_rows.iter_rows(named=True):
            changed.add((lid, season, int(row["week"]), int(row["matchup_id"])))
    _ok("changed groups == exactly the four known ties", changed == expected_keys, results,
        f"{scanned} league-seasons, {len(changed)} changed")
    if changed != expected_keys:
        print(f"      unexpected: {sorted(changed - expected_keys)}")
        print(f"      missing:    {sorted(expected_keys - changed)}")


# --- the gate -----------------------------------------------------------------------------------------

def check(rejoin_slices: int = 1, full_corpus: bool = False) -> bool:
    results: list = []
    print("=== check_matchup_result — W / L / T / null, one definition ===\n")

    _check_semantics(results)
    _check_one_definition(results)
    _check_demo_parity(results, rejoin_slices)
    _check_known_ties(results, full_corpus)

    # prove-it-bites: the shipped bug IS the bite. Same fixtures, old expression, every check must fail.
    print("  PROVE-BITES (the old expression on the same fixtures):")
    legacy = {name: _verdicts(_fixture(specs).with_columns(_legacy_result_expr().alias("matchup_result")))
              for name, (specs, _e) in _SHAPES.items()}
    n_w = sum(1 for v in legacy["unplayed"].values() if v == "W")
    n_l = sum(1 for v in legacy["unplayed"].values() if v == "L")
    _ok("legacy mints 6 W / 6 L on the unplayed slate (check-1 bites)",
        n_w == 6 and n_l == 6 and legacy["unplayed"] != _SHAPES["unplayed"][1], results,
        f"{n_w}W/{n_l}L")
    _ok("legacy elects one winner on null matchup_id (check-1 bites)",
        sum(1 for v in legacy["null_matchup"].values() if v == "W") == 1
        and sum(1 for v in legacy["null_matchup"].values() if v == "L") == 13, results)
    _ok("legacy mints W/L on a genuine tie (check-1 bites)",
        sorted(legacy["tie"].values()) == ["L", "W"], results)
    _ok("legacy calls a bye a win (check-1 bites)", legacy["bye"] == {7: "W"}, results)

    # a weakened predicate (pair test only, scored term dropped) must disagree with the vectorized half
    weak = lambda mid, totals: mid is not None and len(totals) == 2   # noqa: E731
    unplayed_totals = [t for _r, _m, t in _SHAPES["unplayed"][0][:2]]
    _ok("a scored-term-less predicate disagrees with gradeable_expr (check-2 bites)",
        weak(1, unplayed_totals) and not _matchup.is_gradeable(1, unplayed_totals), results)

    _ok("value-equality bites (differing values ≠; row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — an unplayed slate and a null matchup produce no "
          f"result, a genuine tie produces T, and the served slate is unchanged.")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for matchup result derivation (W/L/T/null).")
    ap.add_argument("--rejoin-slices", type=int, default=1,
                    help="how many demo slices to fully re-join for the end-to-end proof (default 1)")
    ap.add_argument("--full-corpus", action="store_true",
                    help="sweep all 271 corpus league-seasons for the allowlist-parity claim")
    a = ap.parse_args()
    sys.exit(0 if check(a.rejoin_slices, a.full_corpus) else 1)


if __name__ == "__main__":
    main()
