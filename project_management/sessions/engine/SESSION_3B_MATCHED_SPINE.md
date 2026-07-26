# Session 3b — The Matched Measurement Spine (compute the graded reads for the 221-league tuning corpus)

**Hand this file to Claude Code as the session brief.**

**Type:** compute-key threading + corpus spine compute · **Commits:** 3
**Reads first:** `CLAUDE.md` · `LEAGUE_CORPUS.md` · `SESSION_1_L0_LEAGUE_KEYING.md` · `SESSION_3A_RAW_HARVEST.md` · `IMPROVEMENT_LOOP.md` (L0 scope table + the pre-registered predictions)
**Blocks:** the ledger (L2) — the reads this computes are what the ledger reconstructs as `served=false` predictions.
**Prior:** Session 3a (raw + `join_season` league-keyed and harvested for all 271 leagues; `is_two_way` rides every join). Session 2/2.5 (the frozen scoring-scoped substrate).
**Reads the FROZEN substrate + 3a's harvested join** — it computes; it does not fetch, re-select, or re-tune.

---

## Why this exists

3a gave every corpus league its raw + `join_season` under `…/league/<league_id>/…`. Now the reads that turn
that into decisions need to run per league. Two decisions define this session's scope.

**1. The compute side is still unkeyed.** Verified against the spine (2026-07-15): every `compute_*.compute()`
takes **`season` only** and implicitly resolves the is_mine league. The `data_layer` read/write side is
already keyed (Session 1's `*, league_id=None`), and the writes already land in `derived/league/<id>/` — but
the compute functions don't pass the keys through, so pointed at 271 leagues they'd recompute the same one
271 times. **Threading `league_id` + `scoring_key` through the computes is the core work.**

**2. This session computes the MEASUREMENT reads only — the ones with a realized answer key.** The corpus →
ledger → scorer → tuner is a **measurement engine**: it grades a read against what actually happened and
tunes the constant. That is only meaningful for reads that *predict something the season resolves*. Applying
that filter to the L0 league-scoped set leaves **5 reads**, which map exactly onto IMPROVEMENT_LOOP's
pre-registered predictions:

```
        FROZEN substrate (scoring-keyed)        3a harvest (league-keyed)
        projection_consensus · ros_player_band  join_season · matchups · lineup_slots
                     │                                  │
                     └──────────────┬───────────────────┘
                                    ▼
                             production_vor        ← scoring_key (consensus) + league_id (join/slots); the VOR foundation
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
          true_rank (§5)      positional_depth (§6)   bracket_odds (§5, 10k-MC / as-of wk)

        player_signal (§1)   ← league_id (join_season); independent of VOR
```

| Read | Answer key it's graded against |
|---|---|
| `production_vor` | the VOR foundation the team reads rest on (projection → realized value) |
| `player_signal` (§1) | realized quality/opportunity vs the signal |
| `true_rank` (§5) | realized standings / all-play |
| `positional_depth` (§6) | realized positional production |
| `bracket_odds` (§5) | realized made-playoffs (Brier) |

The scoring-scoped interval reads — **§2 bull/bear and §3 band** (`BAND_Z`, `BULL_Z`, `SKEW_GAIN`,
`ANCHOR_W`) — are **still graded**, but their answer-key content lives in `ros_player_band`, which is
**scoring-scoped substrate already frozen from 2.5.** They're graded at the ppr/half level, not per league,
so this session **reads the band, it does not recompute it.**

**Descoped from the corpus (see Out of scope): the narrative / behavioral reads.** `ros_league_view` and
`manager_features` are **not** graded reads — verified, their only consumers are the AI narrative writers
(`write_ros_synthesis` and `write_manager_dossiers`), nothing downstream that has an answer key. Per the
product call, that whole track is **too fuzzy to grade consistently and too expensive at scale**, so it is
out of the measurement corpus. Both stay **live, is_mine-only, untouched** — 3b simply doesn't corpus-compute
them. (This also removes the `manager_activity` cross-league fetch entirely: 3a never harvested it, and now
nothing needs it.)

**Matched-only (221 leagues) — the tuning corpus.** Per the approved split (raw all 271 in 3a; spine
matched-first): the 221 matched leagues (ppr/half · 1QB · redraft · 10–14t) route through **none** of the
synthetic-gated shape paths — same shape as the live league, the best-tested code in the repo. The 48
`never_tune` generalization leagues hit `position_pools` / `bracket_sim._seed_table` /
`_scoring.recompute_custom_points` where the docs promise real bugs; they are **Session 3c** (scoped below,
not started), so a division-league crash can't stall the corpus you tune on.

---

## Commit 1 — Thread `league_id` + `scoring_key` through the 5 computes (+ gates); prove is_mine equivalence

Mirror the L0 idiom once more: an explicit key argument that **defaults to the active league**, so the
single-league callers and the live front end are unchanged and only the corpus driver passes keys.

- **Add the keys to each `compute()` / `run()` and pass them to every `read_*` / `write_*` inside:**
  - `production_vor` — `scoring_key` for `read_projection_consensus`; `league_id` for `read_join_season` /
    `read_lineup_slots` / `write_production_vor`.
  - `true_rank`, `positional_depth` — `league_id` for `read_production_vor(as_of_week="all")` /
    `read_lineup_slots` / the write.
  - `bracket_sim` — `scoring_key` for the consensus it draws weekly scores from; `league_id` for the roster /
    `read_season_matchups` / `read_lineup_slots` / `write_bracket_odds`.
  - `player_signal` — `league_id` for `read_join_season` / the write.
- **Each league's `scoring_key` comes from the frozen manifest / registry** (`ppr` or `half` for matched) —
  resolve it once per league in the driver; do not re-derive it per read.
- **Thread the same keys through the 5 backtest gates** (`backtest_production_vor`, `backtest_true_rank`,
  `backtest_positional_depth`, `backtest_bracket_sim`, `backtest_player_signal`) so they can grade any league.
- **Prove equivalence on the is_mine league.** With keys defaulting to active, the is_mine 2025 reads must be
  **byte-identical** to their current on-disk parquet — the threading moves no number. Run each of the 5
  spine gates on is_mine and confirm green with identical output (standing instruction 2).
- **Leave `ros_league_view` and `manager_features` alone** — do not thread, corpus-compute, or gate them; the
  live is_mine app keeps reading them as-is.

> **No `queries.js` / view edits — the seam holds** (standing instruction 3). The keys are a compute/data-layer
> concern; the front end keeps reading the active league through the same `queries.js` calls.

## Commit 2 — Compute the matched measurement spine (221 leagues) against the frozen substrate

- **A driver** (extend `harvest.py` or a sibling `compute_spine.py`) reads the frozen manifest's **matched**
  stratum (221), resolves each league's `(league_id, season, scoring_key)`, and computes the 5 reads **in
  dependency order**: `production_vor → { true_rank · positional_depth · bracket_odds }`; `player_signal`
  independently. **Idempotent + resumable per league** (skip a league whose reads are already on disk — the
  3a precedent), so a long run resumes rather than restarts.
- **The reads inherit `is_two_way` for free** — it rides `join_season` from 3a, so `production_vor` and its
  descendants carry it; **verify** it survives each join/group-by rather than assuming (standing instruction 7).
- **Budget + report the compute cost.** `bracket_sim` is `SIMS = 10_000` Monte-Carlo **per league per as-of
  week** (~221 leagues × ~14 as-of weeks) — the heavy step by far; everything else is cheap polars. Report
  wall-clock per read + total, and confirm the incremental re-run cost (≈ 0 on a resumed run). **Validate the
  plumbing on is_mine + a small matched sample first,** then run the full 221 as a resumable batch — don't
  discover a compute bug on league 200 of 221.
- **Determinism is the load-bearing property here** (this is the ledger's substrate): `bracket_sim` uses a
  fixed-seed RNG (`rng.normal`, `SIMS`) — its seed must be **league-stable** (same league ⇒ same
  `bracket_odds` on re-run; different leagues ⇒ independent draws), **never wall-clock.** New sorted outputs
  must carry a **unique tie-break on `sleeper_player_id` / `roster_id`** (the 1.7 lesson — polars'
  multi-threaded order is parallelism-dependent). Verify twice-compute byte-identical on the sample.
- **Report, don't tune.** First per-league look at the measurement reads across the corpus. If a read's
  calibration looks off, **surface it and leave the constant alone** — retuning is the Tuner's job on the
  TRAIN 2020–2023 · DEV 2024 · TEST 2025 split (standing instruction 4).

## Commit 3 — The corpus-level measurement-spine gate + docs

- **A `check_spine` gate** (mirror `check_harvest` / `backtest_l0_keying`), asserting over all 221 matched leagues:
  1. **Spine present** — all 5 reads exist under `derived/league/<id>/` for every matched league.
  2. **Cohort integrity** — `true_rank` / `positional_depth` / `bracket_odds` cover every `roster_id` at every
     as-of week (no team silently dropped); `bracket_odds` playoff probabilities are in [0,1] and the
     made-playoffs mass per as-of week equals the league's playoff-slot count (a real spent-probability
     check, not just "file exists").
  3. **No roster-mass regression** — the spine's player coverage matches 3a's `join_season` (the 1.51%
     remainder story doesn't grow silently downstream).
  4. **Deterministic** — twice-compute a sample league byte-identical (incl. the `bracket_sim` seed).
  5. **Two-way sliceable** — `is_two_way` rides `production_vor` and is filterable.
- **Prove it bites:** a league with a dropped as-of week fails check 1; a `bracket_odds` with playoff mass ≠
  slot count fails check 2; a wall-clock-seeded sim fails check 4.
- **Docs:** `STATUS.md`, `TECHNICAL_ARCHITECTURE.md` (the measurement spine is now league-keyed +
  corpus-computed for matched; the narrative reads are explicitly out of the corpus), `READ_BUILD_ORDER.md`,
  `LEAGUE_CORPUS.md`. **Scope 3c in the closedown** (see Out of scope).

---

## Acceptance gates

1. **Refactor equivalence** — the is_mine 2025 spine (all 5 reads) is **byte-identical** after threading;
   every spine backtest green on is_mine.
2. **Coverage** — all 5 reads computed for every one of the 221 matched leagues; a resumed run recomputes
   nothing already present.
3. **Cohort + probability integrity** — `true_rank` / `positional_depth` / `bracket_odds` cover every
   `roster_id` × as-of week; `bracket_odds` probabilities valid and playoff mass = slot count.
4. **Determinism** — twice-compute byte-identical, incl. a **league-stable** `bracket_sim` seed; new sorts
   uniquely tie-broken.
5. **Two-way rides** — `is_two_way` present + sliceable on `production_vor` and downstream.
6. **Budget reported** — compute wall-clock per read + total; incremental re-run ≈ 0.
7. **Seam held** — `queries.js` / views untouched; `ros_league_view` / `manager_features` untouched; the live
   is_mine app still renders.

---

## Out of scope

- **Session 3c — the generalization robustness pass (scope it in the closedown; DO NOT start it).** The 48
  `never_tune` leagues through the same measurement spine, where superflex hits `position_pools`, divisions
  hit `bracket_sim._seed_table` / `_division_map` (currently returns `None`), and custom scoring hits
  `_scoring.recompute_custom_points`. **Budget it for bugs** — LEAGUE_CORPUS and IMPROVEMENT_LOOP (session 6)
  both promise real shapes will break synthetic-gated code; isolating it protects the matched corpus.
- **The narrative / behavioral reads — descoped from the corpus (product decision).** `ros_league_view` (§2
  AI-synthesis feed) and `manager_features` / `manager_dossiers` (§7) are not graded reads — too fuzzy to
  grade consistently, too expensive at scale — and their only consumers are the AI narrative writers. They
  stay live, is_mine-only, untouched; **not** threaded, corpus-computed, or gated. The `manager_activity`
  cross-league fetch is likewise not needed. *(Door left open: if a genuinely gradeable manager-behavior →
  team-outcome read is ever defined, the corpus would be the place to build it — but no such read exists
  today.)*
- **The ledger (L2), scorer (L3), tuner (L4).** 3b produces the reads the ledger will reconstruct; it does
  **not** build predictions/outcomes/resolutions or grade anything. **Report calibration, tune nothing.**
- **`market_vor` / `ros_synthesis`** — un-backfillable (cross-time / forward-only); not part of the corpus.
- **Re-selecting the corpus or recomputing the substrate** — both frozen (verify byte-identical if touched).
- **Known 2.5 latents — note, don't fix here:** the float32-vs-float64 duplicate `cust-` keys and the
  `projection_consensus` row-order non-determinism (band is byte-stable). Neither touches the matched spine;
  both are queued. 3b must still make **its own** new outputs order-deterministic (the tie-break requirement).

---

## Definition of done

- The 5 measurement computes + their gates take explicit `league_id` / `scoring_key`, defaulting to active;
  **is_mine byte-identical** (proven).
- **All 221 matched leagues' 5-read spine computed** against the frozen substrate, league-keyed,
  idempotent/resumable.
- `check_spine` **green with teeth**; cohort + probability + determinism + two-way checks proven to bite.
- Compute budget reported; front end + the (untouched) narrative reads unaffected.
- **Session 3c (generalization robustness pass) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean zero is a bug until proven otherwise.** *(A league whose `bracket_odds` are all 0
>    or whose `true_rank` cohort is short a team — name it, don't ship it.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(Threading the keys must leave the
>    is_mine spine byte-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(Keys are compute/data-layer only.)*
> 4. **Report, don't tune.** *(First per-league calibration look — surface it, change no constant. The Tuner
>    owns re-fitting, on TRAIN/DEV/TEST.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate.
>    *(A league whose spine diverges on re-run: name the source — RNG seed? sort tie? — don't hand-wave.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(`bracket_odds` on disk ≠
>    playoff mass sums to the slot count. Gate the property.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The spine reads the frozen substrate +
>    3a's persisted join; it computes deterministically off them, adds no fetch.)*
