"""What a matchup IS: gradeable, tied, or decided — the single definition.

Pure, leaf module (imports polars and nothing else from the tree), so the JOIN
(`join_nfl_sleeper_weekly._derive_matchup_result`, vectorized) and the SIM
(`compute_bracket_sim._standings_as_of`, row-wise) answer the same question from ONE rule
— the `_keys.py` leaf precedent, and the same anti-drift motive as
`harvest._reg_end` borrowing `compute_bracket_sim._sane_playoff_week_start`. A leaf both
import is the right shape here because the join is UPSTREAM of the sim: importing the sim
into the join would invert the pipeline layering.

THE RULE, stated once:

    A matchup is GRADEABLE iff it has a matchup_id, has exactly two rosters, and at least
    one roster posted a non-zero total. Otherwise there is NO result, reported as null —
    never fabricated (CODING_BIBLE §3 Law 2).

    A gradeable matchup with equal totals is a TIE ('T'; the sim's 0.5 wins each).
    Otherwise the higher total is 'W' and the lower 'L'.

UNPLAYED IS NOT A TIE. Sleeper returns a full, paired slate at `points: 0.0` from the
moment the schedule exists — i.e. from the DRAFT, weeks before kickoff. That is the
absence of a result, not a draw, and conflating them is what minted 6 W / 6 L in a league
that had played nothing (`sessions/v1/P2-Go_Live_2026/FINDING_matchup_tie_gate_a.md`).

The scored term is week-level in effect and matchup-level in form: the join grades one
week at a time, so "at least one roster in this matchup scored" and "somebody scored this
week" coincide on a real slate — a whole week is unplayed or it isn't. That keeps this in
step with the app's other depth clock, `api/reads.load_slices`, which counts a week as
played only when somebody scored (S4a). Two homes, one rule; neither can import the other
(the API layer imports nothing from `application/data`), so they cross-reference instead.

ACCEPTED LIMITATION, MEASURED: `join_nfl_sleeper_weekly._parse_sleeper_matchups` collapses
a Sleeper `points: null` to 0.0, so "unplayed" and "played, scored exactly 0" are
indistinguishable at the frame level — a real matchup where BOTH rosters scored exactly
0.0 reads as ungraded. Across the 271-league corpus (21,642 matchup groups) there are ZERO
all-zero groups, so this costs nothing historically, and silence is the direction Law 2
asks for. If that call is ever revisited, the scored term below is the only edit.
"""
import polars as pl

RESULT_WIN = "W"
RESULT_LOSS = "L"
RESULT_TIE = "T"

# A matchup is two rosters. Anything else — a bye, an odd roster count, a whole league
# swept into one null-matchup_id group — is not a matchup and cannot be graded.
SIDES_PER_MATCHUP = 2


def is_gradeable(matchup_id, totals) -> bool:
    """Row-wise shape (the sim): `totals` = this matchup's roster totals, as floats."""
    return (
        matchup_id is not None
        and len(totals) == SIDES_PER_MATCHUP
        and any(float(t) != 0.0 for t in totals)
    )


def gradeable_expr(*, matchup_id="matchup_id", roster_id="roster_id",
                   total="roster_total_points", over=None) -> pl.Expr:
    """Vectorized shape (the join): the same predicate, as a window over the matchup group.

    `over` names the window key and defaults to `matchup_id` alone, which is correct for the
    join because it grades ONE week at a time. A frame spanning several weeks must pass
    `over=["week", "matchup_id"]` or two weeks' matchup 1 would merge into one group.

    The `is_not_null()` term is NOT redundant with the pair test. Polars puts every null
    `matchup_id` in ONE window group — the playoff-week shape, and 2025 week 18 is entirely
    null — so without it a 14-roster null group would read as a single 'matchup' whose
    roster count merely happens not to be 2. Double-guarded on purpose: the null case is
    what the sim's own `matchup_id.is_not_null()` filter has always guarded against.
    """
    grp = over or matchup_id
    return (
        pl.col(matchup_id).is_not_null()
        & (pl.col(roster_id).n_unique().over(grp) == SIDES_PER_MATCHUP)
        & (pl.col(total).abs().max().over(grp) > 0.0)
    )


def result_expr(*, matchup_id="matchup_id", roster_id="roster_id",
                total="roster_total_points", over=None) -> pl.Expr:
    """W / L / T, or null when the matchup is not gradeable. Unaliased — the caller names it.

    `.abs()` in the scored term so a roster with a legitimately negative total still counts
    as having played. See `gradeable_expr` for `over`.

    The trailing `.cast(pl.Utf8)` is load-bearing, not decoration: on an EMPTY frame every
    branch infers Null dtype, and `data_layer.write_join_nfl_sleeper_weekly` appends weeks
    with `pl.concat(..., how="diagonal")` under strict dtypes — a Null column would break
    the season append at week 1 of a brand-new league, which is exactly the path this fix
    exists to make safe.
    """
    grp = over or matchup_id
    top = pl.col(total).max().over(grp)
    bot = pl.col(total).min().over(grp)
    return (
        pl.when(~gradeable_expr(matchup_id=matchup_id, roster_id=roster_id,
                                total=total, over=over))
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(top == bot).then(pl.lit(RESULT_TIE))
        .when(pl.col(total) == top).then(pl.lit(RESULT_WIN))
        .otherwise(pl.lit(RESULT_LOSS))
        .cast(pl.Utf8)
    )
