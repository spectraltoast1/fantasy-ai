# Session 4a — The Ledger, Part 1: `predictions` (reconstruct the engine's claims as `served=false`)

**Hand this file to Claude Code as the session brief.**

**Type:** L2 ledger — the `predictions` entity (schema + read→claim mapping + corpus backfill + gate) · **Commits:** 3
**Reads first:** `CLAUDE.md` · `IMPROVEMENT_LOOP.md` **§L2** (the schema is quoted there — follow it) · `SESSION_3A_RAW_HARVEST.md` + `SESSION_3B_MATCHED_SPINE.md` (house style + the spine this reconstructs) · `LEAGUE_CORPUS.md`
**Blocks:** Session 4b (outcomes + resolutions) — the join needs these rows first.
**Prior:** Session 3a–3e (the 5-read measurement spine computed for **269 corpus league-seasons** — 221 matched + 48 generalization — plus **is_mine 2025**, on a frozen, deterministic substrate; division seeding validated on all 25 real division leagues).
**Reads the FROZEN spine + the frozen scoring-scoped band** — it **reshapes** existing reads into claim rows. It does **not** fetch, re-compute a read, re-select, or re-tune.

---

## Why this exists

The spine is computed, but the engine's **claims are trapped inside per-read parquets** with no record of *what each read predicted* or *how confident it was*. L2 turns every read into an explicit, immutable **claim row**. This session builds the first of the ledger's two entities: **`predictions`**.

**Backfill-first (`served=false`), and this is the load-bearing point:** a completed league-season is a fully-resolved answer key, so we reconstruct the engine's claims *as-of* each week and — in 4b — grade them against known truth. **The schema this session defines is the exact one the live 2026 path reuses verbatim.** The live path becomes `served=true` + an L1 health flag on the *same* columns — a switch to flip, not a system to build. So the schema decisions here are the highest-stakes design in the whole ledger track. Get them right for the live path, not just the backfill.

**4a is the `predictions` entity only.** Outcomes, the resolutions join, and the grading primitives (`error`/`in_band`/`pit`/`brier`/`rank_error`) are **Session 4b** — scoped in *Out of scope*, **not started**. The 3a→3b precedent: split at the entity/risk boundary. `predictions` is a pure reshape of frozen reads (low risk, schema-defining); `outcomes`+`resolutions` introduce realized-truth derivation and grading math (the harder half). Keep them apart.

**Law 1 is structural and starts here:** `predictions` holds *claims*, nothing more. **No grade, no verdict, no single-claim judgement exists in this entity or this session.** The scorer (Session 5) is the first thing that judges. **Report, don't grade.**

### Verified state (checked against the live store 2026-07-16 — don't re-derive, but know it)

- **270 league-seasons carry the full 5-read spine:** 269 corpus (221 matched + 48 generalization) **+ is_mine 2025**. All five reads (`production_vor`, `player_signal`, `true_rank`, `positional_depth`, `bracket_odds`) present for every one; 0 partial.
- **is_mine 2024 (`1132400260048977920`) is harvested but was never spined** — no 5-read spine exists for it, so it **cannot** be reconstructed and is **out of the backfill target** (don't fabricate claims for a league with no reads). Backfill target = **the 270 spined league-seasons.**
- The scoring-scoped interval substrate `ros_player_band` lives under `derived/scoring/<scoring_key>/ros_player_band_<season>.parquet` (`ros_center` / `ros_bull` / `ros_bear` / `ros_sigma` / `ros_cv`) — frozen from Session 2.5. It is **shared** across leagues of the same `scoring_key`.

---

## The design decisions (Will already ruled on the forks — they are settled; implement them)

**1. Entity + write semantics — `predictions_{season}`, season-partitioned, append-only, immutable.** Follow the `market_values` / `team_news_raw` precedent already in `data_layer` (diagonal concat, never overwrite). One file per season holding **all leagues'** claims for that season; every row carries `league_id` (**nullable** — `null` for the scoring-scoped band, set for the 5 league-scoped reads). A re-run under the **same** `code_version` + `constants_hash` appends **nothing new** (idempotent on `prediction_id`); a re-run under a **new** `code_version` writes a **parallel population** and keeps both. Overwriting is the one thing this entity must make impossible.

**2. Provenance columns — all present now, even the ones the corpus can't fill (free here, expensive later).**

- `code_version` — the git sha at write time.
- `constants_hash` — hashed from a **pinned constants snapshot** (decision 4).
- `prompt_version` — **the column exists now**; `null` for every corpus row (no AI reads in the corpus). This is the whole reason to add it here: retrofitting it after the live AI reads land is expensive.
- `model` — `null` for the corpus.
- `inputs_ok` — derived (decision 3).
- `served` — **`false`** for every row this session writes.

**3. `inputs_ok` — a derived column from *versioned* integrity thresholds. No `data_health` entity.** (Will's call, and the correct scope: the corpus inputs are frozen and already integrity-gated at harvest; a daily `(date, source)` `data_health` table is a **live-path** concern that Session 7 owns — its grain doesn't even fit a frozen 2022 league.) Derive `inputs_ok` per `(league_id, season)` from signals **already computed** at harvest/selection: the manifest's `filter_result`, `id_resolution_pct`, the degenerate-league flag, and the per-league remainder rate from `join_season`. **Pin the threshold definition** in a small versioned constant (a `INPUTS_OK_THRESHOLDS` block or sibling of the constants snapshot) so that when the perpetual-refinement loop re-derives `inputs_ok` on new leagues a year from now, "ok" means the same thing.
   - **Do not stamp a blanket `true`.** A column whose `false` path is never exercised offline is the "suspiciously clean value" trap (standing instr 1) — the `false` branch would then debut untested in a live week. Set the thresholds so the **marginal** corpus leagues (highest remainder / lowest id-resolution near the selection boundary) genuinely resolve `inputs_ok = false`, giving the path real offline coverage. If, after honest thresholds, every league is still clean, then **at minimum a prove-bite test** flips a synthetic degraded input and confirms the flag flips.

**4. `constants_hash` — a pinned constants snapshot, hashed per row; a gate that reddens on drift. NOT the L4 registry.** Capture the constant vector that produced the frozen spine into a small, **read-only, checked-in snapshot** (`{name: value}`), and hash it. Scope it hard: **enumerate + snapshot + hash only** — no `Tunable` dataclass, no grids, no objectives, no sweep harness (that is L4's `_constants.py`; building it here is cramming). The constants the 5 reads + band + consensus actually consume (verified in-code 2026-07-16):

   | module | constants |
   |---|---|
   | `compute_projection_consensus` | `BAND_Z=0.55`, `SKEW_GAIN=1.5`, `SHRINK_K=4`, `SKEW_SHRINK_K=8` |
   | `compute_ros_player_band` | `BULL_Z=1.44`, `ANCHOR_W=0.25`, `POOL_SIZE=300`, `POSITION_FLOORS` |
   | `compute_player_signal` | `SHRINK_K=6`, `MIN_GAMES=3`, `POS_MEAN_MIN_OPP=3.0`, `SPIKE_BAND`, `STICKY_BAND`, `OPP_HALF_LIFE_WK`, `DIRECTION_HALF_LIFE_WK`, `DIRECTION_BAND` |
   | `compute_positional_depth` | `GAP_VOR=0.0`, `SURPLUS_SPECTRUM=0.66` |
   | `compute_bracket_sim` | `SIMS=10_000`, `SEED`, `MAGIC_ODDS=0.90`, `_DEFAULT_PLAYOFF_WEEK_START=15` |

   - The snapshot is a **fingerprint** ("which model made this claim?"), distinct from L4's future proposal doc ("why did we change it?"). Its value is that the hash **changes when a constant changes** — so a spine recompute under different constants writes a second, distinguishable population instead of silently collapsing two regimes into one string (the exact provenance lie the ledger exists to prevent).
   - **Gate teeth (prove it bites):** the snapshot is cross-checked against the live module globals; change a module constant without updating the snapshot → the gate goes **red**. This is the drift guard Will asked for, and it earns its keep on day one: **STATUS records `BULL_Z=1.645`, the code is `1.44`** — the snapshot documents the *actual* value and the gate pins it. **Report this drift; do not "fix" it** (changing a constant is the Tuner's job — standing instr 4).
   - IMPROVEMENT_LOOP names five as the eventual **tunables** (`BAND_Z`, `SKEW_GAIN`, `BULL_Z`, `ANCHOR_W`, `OPP_HALF_LIFE_WK`); tag them in the snapshot as L4's initial targets, but hash the **full** vector so the fingerprint is complete.

**5. Backfill target = the 270 spined league-seasons, `served=false`.** Include is_mine 2025 as `served=false` (it has a spine; it's the natural dress-rehearsal that proves the schema against the live league before kickoff). Exclude is_mine 2024 (no spine).

**6. Physical representation of the heterogeneous `value` + `confidence` — TYPED SIDECAR COLUMNS (settled; this is the schema the live path reuses, so it is ruled on here, not deferred).** The flat §L2 doc lists a single `value` and single `confidence`; that can't faithfully hold a numeric point claim, a categorical `direction`, and `player_signal`'s four confidence signals at once. Store them typed, not stringified and not lossy:

   | column | type | holds | populated when |
   |---|---|---|---|
   | `value` | `Float64` | numeric claim (point / interval-center / probability / ordinal) | numeric claim_types |
   | `value_str` | `Utf8` | categorical claim (`direction`) | `claim_type = direction` |
   | `lo`, `hi` | `Float64` | interval bounds (`ros_bear` / `ros_bull`) | `claim_type = interval` |
   | `sigma` | `Float64` | interval **scale** (`ros_sigma`) — 4b's PIT reads it directly | `claim_type = interval` |
   | `confidence` | `Float64` | the **one canonical confidence scalar** the scorer stratifies error by (law 2) | graded reads that state confidence |
   | `confidence_label` | `Utf8` | **names which signal** `confidence` is (e.g. `"regression_risk"`, `"ros_cv"`) | wherever `confidence` is set |
   | `confidence_json` | `Utf8` | supplementary/audit payload (e.g. `player_signal`'s full 4-signal set) — **never the scorer's input** | `player_signal` only; null elsewhere |

   Three non-negotiables that come with this shape:
   - **`confidence` is a single designated scalar; `confidence_json` never decides the metric.** Picking which of `player_signal`'s four signals is *the* confidence (and naming it in `confidence_label`) is a **decision made now, in the open** — not a blob the scorer secretly reaches into. Letting the metric hide in an untyped JSON is the same provenance-lie pattern `constants_hash` exists to kill.
   - **`sigma` is its own typed column, not stuffed in JSON.** 4b computes `pit = Φ((truth − value)/sigma)`; making it parse a string — or back sigma out of `lo`/`hi` via `BULL_Z` — recouples the ledger to a constant we're pinning. Persist `ros_sigma` explicitly.
   - **Typing is XOR-gated and JSON is sparse.** `value` XOR `value_str`; `lo`/`hi`/`sigma` present **iff** interval; `confidence_json` populated only where it exists (null across the ~3.5M numeric rows). Diagonal-concat absorbs the nullable columns, so append-immutability is unaffected.

   **The ledger stays internal — it does NOT feed the front end.** User-facing confidence already reaches the app the correct way: the *read* (`player_signal`) computes it and `queries.js` renders it. The ledger's `confidence` exists to be **graded** ("is this confidence honest?"), a different question and a different audience than the user's ("how much should I trust this?"). If the scorer later finds a read's confidence isn't honest (law 2 fails → suppress), that flows scorer → read → `queries.js` — a view must never read raw, possibly-miscalibrated ledger confidence directly. (Standing instr 3: the seam holds.)

---

## The core work — the read → claim mapping

Every read is already computed **per `as_of_week`** (the read chose its own as-of grid). Record a claim at **every `as_of_week`** the read carries — that as-of *is* "the week the claim was made," and the week-over-week grid is what later lets the scorer ask *does confidence sharpen as the season resolves?* This is the proposed mapping; **verify each column against the live read** and flag anything that doesn't fit rather than forcing it.

| Read | scope | `subject_type` | `subject_id` | `claim_type` | `value` | `lo` / `hi` | `horizon` / `resolves_at` | `confidence` (the read's OWN stated confidence) |
|---|---|---|---|---|---|---|---|---|
| `production_vor` | league | `player` | `roster_id`:`sleeper_player_id` | `point` | `ros_value` | — | `ros` / `season_end` | *(none native — see flag below)* |
| `ros_player_band` (§2/§3) | scoring | `player` | `sleeper_player_id` | `interval` | `ros_center` | `ros_bear` / `ros_bull` (+ `ros_sigma`) | `ros` / `season_end` | `ros_cv` (+ band width) |
| `player_signal` (§1) | league | `player` | `roster_id`:`sleeper_player_id` | `point` | `expected_ppg` (baseline: `recent_ppg`) | — | `week` / weekly | `regression_risk` / `reliability` / `read` / `security` |
| `player_signal` direction (§1) | league | `player` | `roster_id`:`sleeper_player_id` | `direction` | `direction` | — | `week` / weekly | — |
| `true_rank` (§5) | league | `roster` | `roster_id` | `ordinal` | `rank` | — | `season` / `season_end` | `spectrum_pos` |
| `positional_depth` (§6) | league | `roster` | `roster_id`:`position` | `point` | `surplus_value` (or `marginal_vor`) | — | `season` / `season_end` | `shape` |
| `bracket_odds` playoff (§5) | league | `roster` | `roster_id` | `probability` | `playoff_odds` | — | `season` / `season_end` | *(the probability itself)* |
| `bracket_odds` wins (§5) | league | `roster` | `roster_id` | `point` | `proj_wins` | — | `season` / `season_end` | — |
| `bracket_odds` seed (§5) | league | `roster` | `roster_id` | `ordinal` | `avg_seed` | — | `season` / `season_end` | — |

- **`prediction_id`** = a stable hash over `(league_id ‖ scoring_key, read, subject_id, as_of_week, horizon, code_version)` — deterministic, order-insensitive, uniquely tie-broken (the 1.7 / 3b lesson: never let polars' thread order or a float boundary move it). The band's rows key on `scoring_key` (league_id null); the 5 league reads key on `league_id`.
- **The confidence column is load-bearing for law 2 (confidence-honesty is the scorer's headline metric) — so where a read states *no* confidence, FLAG it, do not fabricate one.** `production_vor` has no native confidence field and `bracket_odds` wins/seed don't either; that is a real finding to surface ("law-2 is unmeasurable for these reads until a confidence signal is defined"), not a hole to paper over (standing instr 1 + 6). The band and `player_signal` are rich in confidence signal; make sure it rides through.
- **`subject_id` must disambiguate league-scoped subjects.** `roster_id` is only unique *within* a league, so for roster/matchup subjects namespace it (`roster_id` alongside the row's `league_id` is enough since every row carries `league_id`; the band's player subjects are league-independent). Note this now because 4b's outcomes join depends on it.
- **Volume budget.** `production_vor` alone is ~3.5k rows per league-season; across 270 league-seasons × 9 claim families × ~14 as-of weeks this is on the order of low-millions of rows. That's fine for parquet — but **report the actual total and per-season file sizes**, and confirm the write/read round-trips at that size (the 3a/3b budget-and-report discipline).

---

## Commit 1 — The `predictions` schema + provenance scaffolding (prove immutability + drift-red on is_mine first)

- **`data_layer` write/read for `predictions_{season}`** — `write_predictions(df, season)` (diagonal-concat append, never overwrite; idempotent on `prediction_id`) + `read_predictions(season, league_id=None, read=None)`, mirroring the `team_news_raw` immutable-append helpers. Season-partitioned; `league_id` nullable.
- **The constants snapshot + `constants_hash`** (decision 4) — the checked-in `{name: value}` snapshot, a `constants_hash()` over it, and the **cross-check gate** that reddens if any live module constant drifts from the snapshot. Record the `BULL_Z` 1.44-vs-1.645 drift in the snapshot's doc comment; **do not change the constant.**
- **The `inputs_ok` threshold definition** (decision 3) — the versioned `INPUTS_OK_THRESHOLDS` block + the per-`(league, season)` derivation from the frozen manifest/harvest signals.
- **Prove it before backfilling anything:** write the is_mine 2025 predictions, then re-run and assert **zero new rows** (immutability/idempotence); bump a fake `code_version` and assert a **parallel population** appears (both kept, neither overwritten); flip a snapshot constant and assert the drift gate goes **red**; confirm at least one `inputs_ok=false` path is exercised (a marginal league or the prove-bite).

> **Seam holds — no `queries.js` / view edits** (standing instr 3). The ledger is a new derived entity; the front end doesn't read it. If a change wants to touch a view, stop.

## Commit 2 — Backfill the read→claim mapping across the 270 spined league-seasons

- **A driver** (`corpus/backfill_predictions.py`, sibling of `compute_spine.py` / `backfill_expected_points.py`) iterates the 270 spined league-seasons, reads each of the 5 league reads + the shared `ros_player_band` for the league's `scoring_key`, and emits the claim rows per the mapping table. **Idempotent + resumable per league-season** (skip what's already written — the 3a precedent). `served=false`, `prompt_version=null`, `model=null`.
- **The band is scoring-scoped — read it once per `(scoring_key, season)`, emit its claims once with `league_id=null`,** don't re-emit per league (that's the whole point of the shared substrate; re-emitting would multiply-count in 4b's join).
- **Determinism is the load-bearing property** (this is the ledger's spine): `prediction_id` stable and tie-broken; twice-run **value-identical** (the frozen-substrate + `_frame_eq` discipline — value equality, not raw parquet bytes, per the cleanup finding). Verify on a sample first, then run the full 270 as a resumable batch — don't discover a mapping bug on league 250.
- **Report, don't grade / don't tune.** This is the first look at the claims laid flat across the corpus. If a read's confidence field is missing, a claim value looks degenerate, or a subject fails to key — **surface it with the named mechanism** (standing instr 1, 6). Change no constant, grade nothing.
- **Budget:** report total rows, per-read and per-claim-type counts, per-season file sizes, wall-clock, and incremental re-run cost (≈ 0 on a resumed run).

## Commit 3 — The `check_predictions` gate + docs (+ scope 4b)

- **A corpus-level `check_predictions` gate** (mirror `check_spine` / `check_harvest`), asserting over the 270 league-seasons:
  1. **Claim coverage** — every spined `(league, season, as_of_week, subject)` in each of the 5 reads produced its mapped claim row(s); no read silently dropped; the band contributes exactly one scoring-scoped population per `(scoring_key, season)`.
  2. **Schema integrity** — every row has non-null `prediction_id`, `read`, `subject_type`, `subject_id`, `claim_type`, `value`, `code_version`, `constants_hash`, `served=false`; `prompt_version`/`model` null; `lo`/`hi` present **iff** `claim_type=interval`; `league_id` null **iff** the band, set otherwise.
  3. **Immutability** — re-run appends nothing under the same `code_version`; a new `code_version` writes a parallel population (both retained).
  4. **Provenance bites** — the `constants_hash` drift gate reddens on a changed module constant; `inputs_ok` exercises its `false` path.
  5. **Determinism** — twice-backfill a sample league-season value-identical, incl. a stable `prediction_id`.
  6. **Confidence honesty is trackable OR flagged** — every `claim_type` that will be graded for confidence-honesty has a populated `confidence`, or the read is on the named "no native confidence" flag list.
- **Prove each check bites** (a dropped read fails 1; a fabricated verdict column fails Law-1 structural check; a drifted constant fails 4; a wall-clock-seeded id fails 5).
- **Docs:** `STATUS.md` (the `predictions` entity: schema, backfill counts, the `BULL_Z` drift finding, any confidence-gap flags), `TECHNICAL_ARCHITECTURE.md` (L2 `predictions` is now a keyed immutable entity; the constants snapshot; the `inputs_ok` derivation), `IMPROVEMENT_LOOP.md` (L2 partially built). **Scope Session 4b in the closedown** (see *Out of scope*).

---

## Acceptance gates

1. **Immutable + idempotent** — `predictions_{season}` never overwrites; same-`code_version` re-run appends nothing; new-`code_version` re-run keeps both populations. **Proven, not assumed.**
2. **Provenance complete** — every row carries `code_version` + `constants_hash`; `prompt_version`/`model` columns exist and are null; `inputs_ok` derived (not blanket-true) with its `false` path exercised; `served=false` universally.
3. **Constants snapshot bites** — the drift gate reddens on a changed module constant; the `BULL_Z` 1.44-vs-1.645 discrepancy is documented (**not fixed**).
4. **Mapping coverage** — all 270 spined league-seasons reshaped; the 9 claim families present per the table; the band emitted once per `(scoring_key, season)` with `league_id=null`; missing-confidence reads flagged, not fabricated.
5. **Determinism** — twice-backfill value-identical; `prediction_id` stable + tie-broken.
6. **Law 1 structural** — no grade / verdict / resolution column exists anywhere in `predictions`; nothing in this session judges a claim.
7. **Budget reported** — total rows, per-read/claim-type counts, file sizes, wall-clock, ≈0 re-run.
8. **Seam held** — `queries.js` / views untouched; the reads and substrate are untouched (verify byte/value-identical if read); the live is_mine app still renders.

---

## Out of scope

- **Session 4b — `outcomes` + `resolutions` (scope it in the closedown; DO NOT start it).** Derive realized truth from the **frozen** `join_season` (`sleeper_points` = realized weekly points under the league's scoring → sum to realized ROS; `matchup_result` → realized wins; `roster_total_points`) and `league_settings` (`playoff_week_start`/`playoff_teams` → realized made-playoffs + final standing). Build `outcomes_{season}` (append-only) + `compute_resolutions.py` (the `predictions ⋈ outcomes` join) with the grading primitives — `error`/`abs_error` (point), `in_band` + **`pit`** (interval; `pit = Φ((truth − ros_center)/ros_sigma)`), `brier` + `pit` (probability; `playoff_odds` vs made-playoffs), `rank_error` (ordinal; `rank`/`avg_seed`) — and a corpus-level ledger gate. **PIT is the unifying primitive; still no single-claim verdicts** (the scorer, Session 5, is the first judge). Note the `outcomes` keying subtlety already flagged: roster/matchup subjects need `league_id` (or a namespaced `subject_id`) to disambiguate; scoring-scoped player facts don't.
- **The scorer (L3), tuner (L4), AI eval (L5).** 4a produces claims; it grades nothing, tunes nothing, suppresses nothing.
- **The `data_health` entity + live `(date, source)` L1.** Live-path, Session 7. 4a derives only the `inputs_ok` column from frozen signals.
- **Any constant change, re-tune, re-select, re-harvest, or read recompute.** The spine and substrate are frozen (verify value-identical if read).
- **Front-end / product surface for the ledger.** The ledger is internal loop plumbing; no view consumes it yet.

---

## Definition of done

- `predictions_{season}` exists as an **append-only, immutable** entity with the full provenance column set (`code_version`, `constants_hash`, `prompt_version`, `model`, `inputs_ok`, `served`); immutability + idempotence **proven**.
- The **read→claim mapping** backfilled `served=false` across the **270 spined league-seasons**; the band emitted once per scoring key; missing-confidence reads **flagged**.
- The **constants snapshot** pins the real vector, hashes it per row, and **reddens on drift**; the `BULL_Z` drift is documented, not fixed.
- `inputs_ok` derived from **versioned** thresholds with its `false` path exercised; **no `data_health` entity built.**
- `check_predictions` **green with teeth**; determinism value-identical; **Law 1 holds structurally** (no verdict in the schema).
- Budget reported; seam held; **Session 4b scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A read whose claims are all-zero, an `inputs_ok` that's blanket-true, a confidence column that's silently empty — name it, don't ship it.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(Reshaping a read into claims must preserve its values exactly; the reads and substrate stay value-identical.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(The ledger is a new derived entity; the front end doesn't read it.)*
> 4. **Report, don't tune — and here, don't grade.** *(Surface the `BULL_Z` drift, missing-confidence reads, degenerate claims — change no constant, and add no verdict; the scorer judges, not the ledger.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate. *(A subject that won't key, a band that double-counts — name why.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(A claim row on disk ≠ it carries the read's stated confidence ≠ it will resolve in 4b. Gate the property.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(The backfill reads the frozen spine + frozen band; determinism is proven by value-equality on a re-run, not raw parquet bytes. Provenance rows by `code_version`/`constants_hash`, never file bytes.)*
