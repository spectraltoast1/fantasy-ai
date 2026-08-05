# V1 · P2 · audit_join repair rows + the `is_two_way` null recurrence — REPORT

**Shipped:** 2026-08-05 · **Branch:** `claude/audit-join-nulls` · **Commits:** 3 ·
**Status:** DONE — `check_harvest` is fully green for the first time.
**Next:** P5/S2, unchanged. One decision left with Will: the served-DB reload (below).
Spun out of: `SESSION_P2_MATCHUP_TIE_REPORT.md`.

## Headline

`check_harvest` had one standing FAIL. It is gone — and it was **not** what the task brief (or my own
earlier report) said it was.

## The correction, first

The brief and `STATUS` both blamed check 5 on `audit_join`'s two repair rows carrying "a wrong flag".
Verified false: those rows carry `is_two_way = false`, which is exactly right — Joe Mixon is not a
two-way player. The real cause was **147 week-5 rows with a null flag**:

| week | rows | `is_two_way` null | `matchup_result` null |
|---|---|---|---|
| 1 | 150 | 0 | 1 |
| 2 | 149 | 0 | 1 |
| 3–4 | 295 | 0 | 0 |
| **5** | **147** | **147** | 0 |

`join_nfl_sleeper_weekly` does not emit `is_two_way` — it is a corpus-era column `harvest._apply_two_way`
owns — and the per-week append concats `how="diagonal"`. So P2/S2's scoped week-5 advance brought the
week in *without* the column and it null-filled. **And nothing in `weekly_refresh` re-applied it**, so
every weekly advance of the 2026 season would have re-created the same rot. That moved this from corpus
housekeeping to a defect on the path that runs every week in-season.

Two defects, then, not one: a **null verdict** on the repair rows (real, and the brief's actual subject),
and a **null flag** on appended weeks (the thing that was actually red).

## What shipped

**1. `audit_join` repair rows carry what a real row carries** (`8724b62`) — `_build_zero_stat_row`
zero-filled only *numeric* dtypes, so every post-join String/Boolean/Datetime column fell through.
Now derived from the same sources the rest of the pipeline uses: `player_id` from the join's own
`player_id_map`, `position_group` from `position`, `is_two_way` from the corpus reference (*derived*,
not zero-filled — a flag defaulted to `false` is a fabrication), `fetched_at` from the week's snapshot.
`fill_null_matchup_result` is a second **call site** of `transforms/_matchup`'s single rule, not a second
implementation, and it fills **only where null** — so an already-graded verdict can never move and
verdict-neutrality holds by construction.

`game_id`, `opponent_team`, `team`, `headshot_url` stay null on purpose, and the docstring says which is
which and why: the player did not play a game, so there is no game to name (§3 Law 2).

**2. The recurrence closed + gated** (`046a00c`) — `weekly_refresh` re-applies the flag after its join
loop, guarded so a league with no corpus reference (i.e. every real user's league) still advances
normally. New `serve/check_weekly_refresh.py` stages a league under a scratch id and advances it; its
prove-bite is the shipped code itself — with the re-apply omitted it produces **147 nulls in week 5**,
reproducing the real defect exactly. `check_harvest` check 5 now reports NULL and WRONG as separate
lines, because they have different causes and different fixes; collapsing them is what sent me hunting
the wrong defect in the first place.

**3. The rows on disk repaired** (this commit) — `corpus/repair_join_nulls.py`, dry-run by default,
mirroring the `retire_xtd` one-off precedent. It refuses to write unless every other column is
value-identical *and* every already-graded verdict is unchanged.

## Proven

- **`check_harvest --sample-determinism 2` fully GREEN**, including the new
  `is_two_way never null` line (0 leagues, 0 rows) and `correctly applied` (0 mislabeled). Its
  PROVE-BITES now show check 5's two halves failing independently.
- **`check_weekly_refresh` green with its bite**: omit the re-apply → 147 nulls; keep it → 0 nulls and
  the flag matches the reference, including a real `True` (Travis Hunter).
- **`check_matchup_result` green**, with check 3 now reporting **0 audit_join null-repair rows** (was 2)
  and the frozen-corpus tripwire intact.
- **Parity, measured against a pre-repair snapshot** — 741 rows in, 741 out, column order identical,
  **169 untouched columns value-identical**, and every pre-existing non-null value in the four repaired
  columns unchanged (739 / 594 / 739 / 739). The two rows now read `W` (wk1) and `L` (wk2), agreeing with
  the rest of roster 7's cohort in those team-weeks.

## Judgement calls, stated

- **No re-join.** The brief said to re-join the league-season; that would have been a regression. The
  repair rows exist *because* the join excludes those players (Mixon has 0 `nfl_stats` 2025 rows → null
  position → dropped to remainders), so a re-join reproduces the exclusion and **deletes** them. The
  league is also `stratum='mine', never_tune=true` with 2,255 L2 prediction and 794 outcome rows derived
  from the current artifact.
- **`fetched_at` not backfilled on disk.** `audit_join` fills it for new rows, but it is null on 77 rows
  of this league — ordinary rows, not just repair rows — so a null there is pre-existing provenance
  state, not this defect. Borrowing a sibling's timestamp would fabricate provenance.
- **`headshot_url` left null**, a flagged deviation from the brief: it is recoverable from a prior
  season, but that is a cross-season identity read nothing else in the join performs, for a cosmetic
  field.

## Handoff — one decision for Will

**The served DB still holds the 147 nulls.** The `season` table is a straight COPY from this parquet, so
`build_db.reload_league('1182101676608823296')` is what carries the repair through. **Not run — a
production write is Will's call.**

- **User-visible impact is nil**: zero `is_two_way` consumers in `application/api/` or the frontend, and
  `production_vor` (which does carry the flag downstream) was already correct.
- **But the ordering is forced.** `check_scoped_reload`'s anchor *is* this league, and its design assumes
  the deployed rows are the full-load baseline. Repair the parquet without reloading and that gate's own
  `reload_league` pulls the repaired rows in, `before != after`, and it reports a **spurious** parity
  FAIL. So: **reload, then run `check_scoped_reload`** — not the other way round.
- **Sequencing:** `SESSION_P5_DEMO_LEAGUE_CLONE.md` builds the public demo from this league-season **at
  week 5** — exactly the week that held the nulls. Landing this first means the clone inherits clean data;
  cutting the clone first would bake 147 null flags into a hardcoded, cosmetically-frozen demo.

Deferred and written into STATUS: letting `_apply_registry_eligibility` resolve a **null** position from
the pinned registry would retire the repair-row class entirely — but it changes the corpus row
population, so it gets its own session whose first deliverable is a corpus-wide count.
