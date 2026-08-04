# Finding — the matchup tie bug is a **confirmed** Gate-A blocker

**Established:** 2026-08-04 · **By:** PM, against the **live Sleeper API** and the harvested corpus.
**Subject:** `_derive_matchup_result` — `application/data/transforms/join_nfl_sleeper_weekly.py:189`.
**Why this doc exists:** `STATUS.md` carried this as *parked, "worth doing before the season runs deep."*
It was re-filed as a Gate-A blocker on inference; this is the evidence, and the inference was right.

## The verdict, and the part that was wrong

**Confirmed: a freshly drafted 2026 league shows fabricated W/L records the first time it loads.** The
trigger is **schedule generation — i.e. the draft — not kickoff.** That distinction matters for the
calendar: the exposure starts at Will's draft (~late Aug), not at Week 1 (Sept 10).

## Evidence chain (each step reproducible)

1. **Sleeper's own clock, today:** `GET /v1/state/nfl` → `season 2026`, `season_type "pre"`, `week 0`,
   `season_start_date 2026-08-06`. No 2026 games have been played.
2. **A league that has NOT drafted returns nothing.** Will's `pre_draft` 2026 league
   (`1389327290164314112`) → `GET /league/…/matchups/1` = **empty array**. No rows, no bug. This is why
   the bug is invisible until the draft.
3. **A 2026 league that HAS a schedule returns a full slate at zero.** Will's `Legends League`
   (`1374520935519911936`, 12 rosters) → `GET /league/…/matchups/1` = **12 objects, `matchup_id`
   populated and paired (1–6), `points: 0.0` for every roster** — pre-kickoff, today.
4. **That exact shape, fed to the real function, mints records.** `_derive_matchup_result` copied
   verbatim and run on 12 rosters × `matchup_id` 1–6 × `0.0` points:
   **6 `W` and 6 `L`, decided purely by `roster_id` sort order**, in a league that has played nothing.
   Every matchup group has all-equal points, so `sort_by(roster_total_points, descending).first()`
   degenerates into "lowest roster_id wins."
5. **The historical corpus never trips it, which is exactly why nobody has seen it.** Across 7 joined
   league-seasons (2023 ×6, 2025 ×1) — **16,364 rows, 554 matchups: 0 tied, 0 degenerate, 0 null
   `matchup_id`.** Every replay matchup has a genuine winner. The bug has no replay footprint; the first
   real 2026 load is its debut.

## Second finding — latent, same function, fix it in the same session

Playoff-week snapshots carry **`matchup_id: null`** for every roster not in a matchup (verified on 2025
week 15 / 17 / 18 — week 18 is *entirely* null: 10–14 rosters, no matchup ids). **Polars groups nulls as
one group**, so `_derive_matchup_result` would elect a *single* winner across the whole league and mark
every other roster `L` for a week in which no matchup existed.

**Not reachable today.** `harvest._build_join` joins weeks `1 … playoff_week_start - 1`, so playoff weeks
are never joined — confirmed in the data: the 2025 league with `playoff_week_start = 15` has joined weeks
**1–14** and **zero** null `matchup_id` rows. It goes live the moment anything joins a playoff week.

## What the fix session must decide (and the free parity oracle it gets)

- **Two cases, and conflating them would be its own bug.** *Unplayed* (no results yet — every roster at
  0.0) is not a tie; it is **the absence of a result**, and should produce no W/L at all. A *genuine* tie
  (both sides played, equal points) is a real outcome — `compute_bracket_sim` already scores it 0.5 each,
  so the served record and `bracket_odds.current_wins` should finally agree instead of disagreeing by
  construction.
- **`matchup_result` has exactly two consumers** — `api/reads.py:179` and `:471`, both
  `max(matchup_result)`. A third value (or a null) has to be handled there and in whatever renders a
  record, or the fix stops at the parquet and never reaches the screen. *("The artifact exists" and "the
  consumer uses it" are two different gates.)*
- **The parity oracle is already measured, and it is a strong prediction rather than a hope:** because
  the corpus contains **zero** tied or degenerate matchups, a correct fix must leave every historical
  league **byte-identical** on re-join. Any diff in a 2020–2025 league is a defect in the fix, not a
  change in the data. Run it across the demo slices, not one league.
- **Suggested gate-that-bites:** a synthetic 12-roster, all-zero week must produce **no** W/L; a
  synthetic genuine tie must produce the tie result on both sides; the 2020–2025 re-join must be
  unchanged.

## Timing

The draft is the trigger, so this wants to land **before Will drafts (~late Aug)**, not before Week 1.
It is a small, bounded change to one function plus its two consumers, and it now has both a reproduction
and a parity oracle — so it does not need to compete with P5/S2 for the "careful" slot.
