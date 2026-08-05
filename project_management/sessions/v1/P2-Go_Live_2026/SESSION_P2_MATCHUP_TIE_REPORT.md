# V1 · P2 · Matchup tie / unplayed slate — the Gate-A blocker — REPORT

**Shipped:** 2026-08-05 · **Branch:** `claude/fantasy-ai-matchup-tie-gate-5b1016` · **Commits:** 3 ·
**Status:** DONE — the Gate-A blocker is cleared; Will can draft.
**Next:** P5/S2 (ownership + per-user isolation), unchanged.
Finding: `FINDING_matchup_tie_gate_a.md`.

## Headline

A freshly drafted league no longer invents a record. Fed the slate Sleeper actually returns after a
draft — every matchup paired, every roster at `0.0` — the join used to mint **5 W and 5 L**; it now
produces **no result at all**, and the app reads `0-0` with the honest "too early" state. A genuine tie
is a real outcome and now renders as one (`2-1-1`) instead of being silently converted into a win for
whoever had the lower roster id.

## What shipped

**1. `transforms/_matchup` — one definition, in two renderings** (`5951910`)

A pure leaf module both the join and the sim import: *a matchup is gradeable iff it has a `matchup_id`,
has exactly two rosters, and at least one roster scored; otherwise there is no result, reported as null.*
A leaf rather than one importing the other because the join is **upstream** of the sim — the `_keys.py`
precedent. The vectorized `result_expr` and the row-wise `is_gradeable` cannot be collapsed into one
another (`map_elements` is banned), so a gate check asserts they agree case-for-case.

`_derive_matchup_result` collapses to a single `with_columns`. Three shapes that used to be given a
fabricated winner now produce null: an unplayed slate, a null `matchup_id`, and a bye. A genuine tie
produces `'T'`.

**2. The record surfaces** (`741296f`)

Three tally bodies feeding four sites became one (`records_by_roster`, now with a `t` bucket and an
`EMPTY_RECORD` default), behind one formatter (`calcs.format_record`). `Teams.jsx` was the app's only
client-side record construction and now renders the server's string like the other four surfaces.

**3. The sim** (this commit)

`_standings_as_of` gates its win credit on the same gradeability rule — an all-zero week used to read
`0.0 == 0.0` as a draw and hand every roster 0.5 wins. The simulated window now starts after the last
week actually **played** rather than after `N`, so an unplayed week isn't consumed (its real games get
simulated and `remaining_games` is right).

## Proven

- **`check_matchup_result`** (new, `application/data/corpus/`) — five synthetic shapes against the real
  function, the two renderings agreeing, demo-slate parity, the four corpus ties, the sim no-op, and a
  prove-bites block that runs **the shipped bug** on the same fixtures and requires every check to fail.
- **Parity of the record-bearing VALUES** — stated precisely, because the payload itself is not
  unchanged. Over 4 demo slices × 4 week cutoffs (**80 entries**) covering all five reads, every
  pre-existing field diffs identically between `main` and this branch: the `record` strings, `wins`,
  `losses`, `allPlayW/L`, `rank`, `playoffPct`, `allPlayPct`, and team-detail's `record`/`trueRec`/`ptsWk`.
  **`load_standings` deliberately GAINS two keys, `ties` and `record`** (additive; `Teams.jsx` now
  consumes `record`), so the payload contract did change and "byte-identical payload" would be the wrong
  claim. Re-runnable: `verify_record_parity.py` in this directory, run once against each checkout. It is
  a **one-off cross-version comparison, not a gate** — it needs two git refs and a live DB, so it can't
  live in `check_*`; what *is* gated is `format_record(w, l, 0) == "{w}-{l}"`, the property that makes
  the old strings reproduce exactly.
- **Corpus, all 271 league-seasons** (696,437 rows / 21,642 matchup groups): exactly **4** groups change
  verdict, and they are the 4 genuine ties, named in the gate. None is in the demo slate, so **the
  served DB does not move**. Blanket identity would have been the wrong oracle — it would false-fail a
  correct fix.
- **The sim is an identity on real data**: `_standings_as_of` unchanged on every as-of week of all 271,
  the simulated window unchanged everywhere, and a full `compute_bracket_sim.compute()` recompute is
  identical to the persisted `bracket_odds` for three leagues across three seasons — so `playoff_odds`,
  `proj_wins`, `avg_seed`, `magic_wins` and the L2 ledger's `roster_wins` are all untouched.
- **On screen**, against the real Postgres with `season` shadowed by a **session-local TEMP table** (the
  only reachable database is production Supabase, and a verification must not write to it):
  - a genuine tie renders `2-1-1` / `1-2-1` on the Teams standings while untied teams keep the
    two-segment form;
  - a simulated fresh draft renders `0-0` in the header and the honest "too early" state, where the same
    data under `main` produces a fabricated `0-1` header and a 5 W / 5 L standings table.

## Fixes surfaced along the way

- **`load_team_detail` averaged points over JOINED weeks, not played ones**, so a freshly drafted league
  rendered **"Pts/Wk 0.0"** — the same fabrication in a different cell. Fixed in the same commit as the
  record surfaces; a no-op on every served slice.
- **The finding's "two consumers" was three tally bodies / four sites**, and one of the two SQL sites
  needed no change at all. `_sql_standings_weeks` is deliberately untouched, with the reason now written
  down: Postgres `max()` skips nulls and returns NULL only for an all-null team-week, which *is* the
  ungraded-week signal.
- **`weekly_refresh` does not clamp to `playoff_week_start - 1`.** The finding called the null-`matchup_id`
  case unreachable on the strength of `harvest._build_join`; the live weekly path has no such clamp, so
  it is reachable in-season. That moved it from "latent" to "fixed now", as planned.
- **`audit_join._build_zero_stat_row` writes repair rows without the post-join columns** — 2 rows in
  league `1182101676608823296`/2025 carry a null `matchup_result` and a wrong `is_two_way`. Pre-existing
  (reproduced on unmodified `main`), harmless to the served record (`max()` skips the nulls), and the
  cause of the **one pre-existing FAIL in `check_harvest` check 5**. Not fixed here — spun out as its own
  task, and the new gate reports the count rather than tolerating it silently.

## Scope guard held

Touched: `transforms/_matchup.py` (new), `join_nfl_sleeper_weekly.py`, `compute_bracket_sim.py`,
`corpus/check_matchup_result.py` (new), `api/calcs.py`, `api/projections.py`, `api/reads.py`,
`api/check_projections.py`, `frontend/src/Teams.jsx`.

Deliberately **not** touched: no parquet re-joined, no corpus rewritten, no Postgres reload — the fix
changes only what a *future* join writes, and the frozen corpus stays frozen (the gate asserts the 4 tie
rows are *still* `W`/`L` on disk, as a tripwire for anyone who re-joins it). No DDL: `matchup_result` is
already nullable `TEXT` with no CHECK and the schema is generated from parquet dtypes. `audit_join`,
the all-play "true record", and standings rank (playoff-odds-ordered, so no reordering) left alone.

## Handoff

**This change must be DEPLOYED, not just merged.** It touches `api/reads.py`, `api/calcs.py`,
`api/projections.py` and `frontend/Teams.jsx` — all served artifacts — so merge → push → **`fly deploy`**
→ confirm on https://surplusff.com/. The project has shipped a merged-but-undeployed change before
(P0/B3). The *data* path needs nothing extra, which is what made this easy to miss: at Gate A the fixed
join reaches Postgres through `weekly_refresh` step 4's existing `build_db.reload_league` call.

**On the first real 2026 league, look at `remaining_games` and the playoff odds, not just the standings
string.** The sim-window change is the one piece whose proof is structurally weaker than the rest: on the
corpus, "last played week" and `N` are the same week for every league, which is why the 271-league
identity holds — and equally why that proof does not exercise the new behaviour. Its first genuinely
novel run is Will's own league. A wrong window shows up as a season short or long by a week, which is
legible on sight.

The one thing this could not prove end-to-end is a `'T'` travelling parquet → COPY → Postgres, because
the only reachable database is production. The transform half is proven on the four real corpus ties and
the serving half on the real Postgres via the temp shadow, so no link rests on a stub — but the first
real 2026 load should still glance at the standings, which it will be doing anyway.
