# Session 3c — The Expected-Points Substrate Backfill (light up §1 Quality across the corpus)

**Hand this file to Claude Code as the session brief.**

**Type:** substrate backfill (additive) + bounded re-compute · **Commits:** 3
**Reads first:** `CLAUDE.md` · `SESSION_2_NFL_SUBSTRATE_BACKFILL.md` (the schema-honesty precedent) · `SESSION_3B_MATCHED_SPINE.md` · `DECISION_READS.md` (§1)
**Blocks:** the Tuner's §1 work — without this, §1 Quality can only be tuned on the TEST season.
**Prior:** Session 3b surfaced the gap and correctly held the axis null (law 2) rather than fabricate.
**Naming:** this is a **Session-2-style substrate backfill**, not the generalization robustness pass — **that
resequences to Session 3d** (scoped in Out of scope). It's numbered 3c per direction.

---

## Why this exists

3b computed the matched measurement spine, and in doing so surfaced that **§1 `player_signal`'s Quality axis
is TEST-only.** Verified 2026-07-15:

| season | `quality_rate` / `luck` / `point_correlation` |
|---|---|
| 2020–2024 | **100% null** (the entire TRAIN + DEV window) |
| 2025 | populated (~8% null) |

**Root cause (verified, not assumed).** The Quality axis reads the ffverse `ff_opportunity` expected-points
components — the 14 `*_exp` columns (`pass_yards_gained_exp`, `rush_touchdown_exp`, `receptions_exp`, …). Those
land via `nfl_stats._load_ff_opportunity(year)` → `nflreadpy.load_ff_opportunity(year, stat_type="weekly")`.
The 2020–2024 `nfl_stats` parquets were built **before** that join was added to the fetcher, so they carry
**zero** `*_exp` columns; 2025 was rebuilt after and has all 14 populated. It's a **stale-substrate gap**, the
same class Session 2 fixed for `projections` — not a 3b bug.

**A second, unrelated schema wart — leave it (decided).** The 2020–2024 parquets also carry a stale, **provably
unconsumed** `xtd` column (the retired hand-rolled TD-proxy) that 2025 lacks — verified: the only reference in
the whole codebase is a comment in the fetcher; no transform / backtest / `queries.js` / view reads it. **Do
NOT drop it in this session.** Keeping it preserves the *pure* additive byte-check — every pre-existing column
(including `xtd`) stays byte-identical, so the only deltas are the added `*_exp` and the downstream Quality
columns, with no carve-out to muddy attribution. A destructive column-drop is a different discipline than a
byte-preserving backfill; `xtd`'s removal is **queued as a cosmetic cleanup** (bundle it with the degenerate-
league fix), not folded in here.

**Blast radius is contained to the Quality axis — verified against the code.** `compute_player_signal`'s
**core** read (`opp_g` → `ppo` shrunk to the positional mean → `expected_ppg = opp_g·shrunk_ppo` →
`regression_risk`) is *volume-anchored and independent of `*_exp`* — the docstring is explicit that the
model-expected efficiency "was tested and **lost to the positional mean**… **kept separate, not fused into the
shipped engine**." Only `quality_rate` / `luck` / `point_correlation` (and `exp_pts_g`) consume `*_exp`. So
populating the components must change **only** the Quality axis and **nothing else** in the spine.

That fact dictates the method: **an additive backfill, not a re-pull.** Re-pulling `nfl_stats` wholesale from
nflreadpy today would risk 1.7-style drift (a moving source — realized stats, positions) that would move the
**frozen** corpus and invalidate the 3b spine. Instead we **append the missing `*_exp` columns** and prove
every pre-existing column byte-identical.

---

## Commit 1 — Schema-honesty pre-check, then additively backfill `*_exp` into `nfl_stats` 2020–2024

### ⚠️ Pre-check FIRST (Session 2's discipline — do not write a partial substrate)

Pull `nflreadpy.load_ff_opportunity(<year>, stat_type="weekly")` for **each of 2020–2024** and report the
per-season presence + null rate of the `EXP_COMPONENT_COLS` set. **If any season doesn't serve them (or serves
them mostly-null), STOP and report** — a silently-null `*_exp` would re-create the exact gap under a different
guise. *(Expectation: ffverse `ff_opportunity` reaches back to ~2006, so this should pass — but verify, don't
assume; that is the whole reason this session exists.)*

### Then the additive backfill

- **Append the `*_exp` columns (14 in the 2025 schema) onto the EXISTING `nfl_stats_{2020..2024}` parquets**
  via a left join on `(gsis_id, week)`. Do **NOT** re-pull `load_player_stats` / snaps / team-rates / redzone —
  only `_load_ff_opportunity`. **Every pre-existing column stays byte-identical** (`xtd` included — it is NOT
  dropped); the only change is columns added.
- **2025 is untouched** (already has them) — verify byte-identical.
- **Gate teeth:** `*_exp` present + populated for 2020–2025; every pre-existing `nfl_stats` column
  byte-identical (prove it — hash the pre-existing column set before/after).

## Commit 2 — Append `*_exp` to `join_season`, then re-run `player_signal` across the matched corpus

- **Append the `*_exp` columns onto the EXISTING league-keyed `join_season` parquets** (2020–2024, matched
  leagues) — the same additive join on `(sleeper_player_id/gsis_id, week)`, sourced from the now-augmented
  `nfl_stats`. **Don't re-run the join logic** (that would re-touch the pinned-registry path — 1.7 —
  needlessly); just append the columns so `compute_player_signal` (which reads the join) sees them. Every
  pre-existing join column byte-identical.
- **Re-run `player_signal` for the matched corpus** (2020–2024; 2025 already full — verify byte-identical).
  The Quality axis (`quality_rate` / `luck` / `point_correlation` / `exp_pts_g`) now **populates**; **every
  other `player_signal` column is byte-identical** (the core is `*_exp`-independent — proven above; now prove
  it holds on the data). **This CHANGES NUMBERS BY DESIGN**, so the discipline inverts: **bounded + explained +
  twice-run-identical**, not "nothing moved." Name the changed columns (the four Quality columns) and show the
  rest is byte-identical.
- **Prove the blast radius is contained:** `production_vor` / `true_rank` / `positional_depth` /
  `bracket_odds` do not read `*_exp` or `player_signal` — re-read the augmented join and confirm they are
  **byte-identical.** The 3b spine is otherwise frozen.
- **Report:** §1 Quality null-rate by season after the backfill (should fall to ~2025's level across
  2020–2024). *(Generalization leagues pick `*_exp` up for free when 3d computes their spine — nothing to do
  here.)*

## Commit 3 — Gate + docs

- **Extend `check_spine` (or a sibling `check_expected_points`):**
  1. `*_exp` populated for **2020–2025** (no null-season).
  2. **No-regression:** `nfl_stats` + `join_season` pre-existing columns byte-identical (additive only).
  3. `player_signal` **core columns byte-identical**; **Quality axis non-null across all six seasons.**
  4. **Blast radius contained:** `production_vor` / `true_rank` / `positional_depth` / `bracket_odds`
     byte-identical to their 3b output.
- **Prove it bites:** a season still missing `*_exp` fails check 1; a moved core `player_signal` column fails
  check 3; a moved `production_vor` fails check 4.
- **Docs:** `STATUS.md`, `TECHNICAL_ARCHITECTURE.md` (`nfl_stats` now carries `*_exp` for all six seasons; the
  additive-backfill pattern), `READ_BUILD_ORDER.md`, `LEAGUE_CORPUS.md`. Note the Tuner can now do §1-quality
  out-of-sample. **Scope Session 3d in the closedown.**

---

## Acceptance gates

1. **Feasibility pre-check reported** for 2020–2024; the session **STOPS** if `ff_opportunity` doesn't serve a
   season with populated components.
2. `*_exp` present + populated for **2020–2025**; 2025 unchanged (byte-identical).
3. **Additive only** — every pre-existing `nfl_stats` + `join_season` column byte-identical.
4. `player_signal`: Quality axis **populated** for 2020–2024; **all other columns byte-identical**;
   **twice-run byte-identical** (bounded + explained, not "nothing moved").
5. **Blast radius contained:** `production_vor` / `true_rank` / `positional_depth` / `bracket_odds`
   byte-identical to 3b.
6. Gate green with **teeth**; §1 Quality now spans the corpus.
7. **Seam held** — `queries.js` / views untouched; live is_mine app renders (2025 unchanged).

---

## Out of scope

- **Session 3d — the generalization robustness pass (resequenced from 3c; scope it, don't start it).** The 48
  `never_tune` leagues through the 5-read spine, where superflex hits `position_pools`, divisions hit
  `bracket_sim._seed_table` / `_division_map`, and custom scoring hits `_scoring.recompute_custom_points`.
  **Budget it for bugs.** (It inherits the `*_exp` fix for free — `nfl_stats` will already carry the
  components.)
- **Re-pulling the rest of `nfl_stats`** — the moving-source trap (1.7). Additive `*_exp` only.
- **A small "corpus cleanup" pass — queued, not this session.** Two cosmetic/data warts that each deserve
  their own focused, provably-safe change rather than being folded into a byte-preserving backfill:
  - the stale **`xtd`** column (2020–24, retired TD-proxy, provably unconsumed) — a `1.5`-style dead-column
    retirement (prove unconsumed + moves no number) that harmonizes the six-season schema;
  - the one **degenerate matched league** (`1124876463083261952`, 2024 — `reg_end=-1` from a broken
    `playoff_week_start`, week-1-only 3a harvest) — a `reg_end` sanity floor + a targeted full-season
    re-harvest, bringing the matched spine to 221/221.
  Both are cheap; keeping them out preserves this session's pure additive byte-check (220/221 holds for now).
- **The ledger / scorer / tuner.** This unblocks §1-quality tuning; it does not tune. Report, don't tune.
- **Re-selecting the corpus or recomputing the substrate** beyond the `*_exp` addition (frozen).

---

## Definition of done

- Feasibility confirmed; `*_exp` **additively** backfilled into `nfl_stats` 2020–2024 (2025 unchanged), every
  pre-existing column byte-identical.
- `join_season` carries `*_exp`; `player_signal` re-run across the matched corpus — **Quality axis populated
  2020–2024, all other columns byte-identical, twice-run-identical.**
- **Blast radius proven contained** — the rest of the 3b spine byte-identical.
- Gate green with teeth; docs updated; **Session 3d scoped in the closedown.**

---

> ## Standing instructions
> 1. **A suspiciously clean zero is a bug until proven otherwise.** *(A season whose `*_exp` come back all-null
>    after the backfill is exactly this — STOP, don't ship a partial substrate.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(This session changes numbers BY
>    DESIGN, so the discipline inverts: the ONLY things that may move are the four §1 Quality columns for
>    2020–2024; everything else — every other `nfl_stats`/`join`/`player_signal` column and the whole rest of
>    the spine — must be byte-identical + twice-run-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.**
> 4. **Report, don't tune.** *(Surface the now-corpus-wide §1 Quality coverage; the Tuner fits it, on
>    TRAIN/DEV/TEST.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism. *(If a pre-existing column moves,
>    name why before proceeding — an additive join should make that impossible.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(`*_exp` on disk ≠
>    `player_signal` Quality populated ≠ the core stayed byte-identical. Gate each.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(This is why the backfill is ADDITIVE —
>    appending `ff_opportunity`'s components onto the frozen `nfl_stats`, not re-pulling stats that would drift
>    the corpus.)*
