# Session 4b — The Ledger, Part 2: `outcomes` + `resolutions` (join the claims to realized truth, grade nothing)

**Hand this file to Claude Code as the session brief.**

**Type:** L2 ledger — the `outcomes` entity + the `compute_resolutions` join (grading **primitives**, not verdicts) + a corpus ledger gate · **Commits:** 3
**Reads first:** `CLAUDE.md` · `IMPROVEMENT_LOOP.md` **§L2** (the `outcomes` / `resolutions` schemas + the PIT primitive are quoted there) · `SESSION_4A_LEDGER_PREDICTIONS.md` (the claims this resolves; the schema is verbatim-reused) · `SESSION_3B_MATCHED_SPINE.md` (the `bracket_odds` playoff-mass check this mirrors on the realized side)
**Prior:** Session 4a (`predictions_{season}` — 2,893,834 immutable `served=false` claims across the 270 spined league-seasons) **and the 4a-fix** (see the blocker below).
**Reads the FROZEN `join_season` / `matchups` / `league_settings` + the frozen 4a `predictions`** — it derives realized facts and joins. It does **not** fetch, recompute a read, re-select, re-tune, or **grade** (no scorer here).

> ### ⛔ Hard prerequisite — the 4a-fix must land first
> 4b joins on `prediction_id`, and the 4a-fix **re-stamps `code_version` → regenerates every `prediction_id`.** Running 4b against the pre-fix (087e740-stamped) ids would build `resolutions` on ids that are about to change. **Do not start 4b until the 4a-fix has merged and `predictions` carries a single committed `code_version`.** Verify that first (one `code_version`, names a real commit) — standing instr 8.

---

## Why this exists

4a laid the engine's claims flat as immutable rows. They are still ungraded — there is no record of **what actually happened**. 4b builds the other half of the ledger: `outcomes` (realized truth) and `resolutions` (the `predictions ⋈ outcomes` join that attaches the **grading primitives**). After 4b, every corpus claim sits next to its realized outcome and its `error` / `in_band` / `pit` / `brier` / `rank_error` — the raw material the scorer (Session 5) will judge.

**The primitives are not verdicts.** This is the line that keeps Law 1 intact across the entity boundary:

- In **`predictions`**, grading columns are **forbidden** (4a's `check_predictions` enforces `_FORBIDDEN_COLS`).
- In **`resolutions`**, they are **required** — but a per-row `pit` of 0.97 or an `abs_error` of 40 is a **primitive**, not a judgement. **`resolutions` emits no aggregate pass/fail, no per-read verdict, no "this claim was wrong."** The scorer is the first thing that judges, and it only ever judges **distributions** of these primitives (PIT-uniformity, skill vs baseline, confidence-honotonicity). **Report the primitives; grade nothing.** (Standing instr 4, sharpened: here it means *compute the primitive, emit no verdict*.)

**Same schema, live-path-ready.** As with 4a, this is the exact `outcomes` / `resolutions` shape the live 2026 path reuses — the live delta is `served=true` predictions flowing into the *same* join. Build the horizon alignment correctly now (weekly vs ROS-tail vs season-end), because the live path inherits it.

### Verified against the live store (2026-07-16 — grounding, don't re-derive)

- **Realized weekly points** live on `join_season` as **`sleeper_points`** (scored under the **league's** scoring — two leagues sharing a `scoring_key` give a player identical weekly points, so player point-facts are **scoring-scoped**, `league_id` null). `matchup_result ∈ {W, L, T}` (uppercase — handle the tie), `roster_total_points` per roster-week.
- **`league_settings` is long-format `(section, key, value)`** — `playoff_week_start` and `playoff_teams` are **rows**, not columns (e.g. is_mine 2025: `playoff_week_start=15`, `playoff_teams=4`, `num_teams=8`). `reg_end = playoff_week_start − 1`, floored by the existing shared helper `compute_bracket_sim._sane_playoff_week_start` (reuse it — do not re-derive the floor).
- **Realized standings / made-playoffs must reuse the existing division-aware seeding** (`compute_bracket_sim._standings_as_of` / `_seed_table` / `_division_map`). A naive wins-then-points sort **misranks the 25 real division leagues** (3d/3e activated division seeding for exactly this reason). The realized answer key must respect division winners' auto-seeds, or `bracket_odds`/`true_rank` get graded against a wrong truth.

---

## The design decisions (recommendations on the forks — Will confirms the ones marked ★)

**1. `outcomes_{season}` — append-only, `league_id` nullable, keyed by the fact's natural scope.** Mirror the 4a/`team_news_raw` immutable-append. `league_id` is **null for scoring-scoped player facts** (weekly points — identical across leagues of a scoring_key, stored once) and **set for league-scoped roster facts** (wins, standing, made-playoffs). This resolves the keying subtlety flagged in 4a: `roster_id` is only unique within a league, so every roster fact carries `league_id`. Outcomes are **realized truth, not model output** — no `constants_hash`; tag `recorded_at` + a data-source marker for reproducibility.

**2. Store weekly points ONCE (scoring-scoped); sum the tail in `resolutions`.** Don't materialize a per-`as_of_week` ROS outcome (that multiplies the same fact ~14×). Persist `player_weekly_pts` per `(scoring_key, player, week)`; `compute_resolutions` sums weeks `≥ as_of_week` to realize each ROS claim's answer. Cheaper and it keeps the ROS horizon a property of the *claim*, not the *outcome*.

**3. ★ PIT only where the read states a distribution.** `pit = Φ((truth − value)/sigma)` needs a stated distribution. The interval read (band: center+sigma) and the probability read (`playoff_odds`) have one; **point** claims (`production_vor`, `player_signal` expected_ppg, `proj_wins`) do **not**. Recommendation: **compute PIT for interval + probability only; point claims get `error`/`abs_error`, `pit=null`.** Do **not** fabricate a sigma for a point claim — that invents confidence the read never stated (the anti-law-2 move). The scorer still gets calibration from the reads that *do* declare a distribution.

**4. ★ `positional_depth`'s answer key — the one genuinely fuzzy outcome; grade the clean subset, flag the rest.** `production_vor`/`true_rank`/`bracket_odds`/band all have crisp realized truth. `positional_depth`'s claim (`surplus_value` / `shape` per roster×position) has no obvious single answer key. Recommendation: grade it against **realized points scored by that roster's players at that position over the horizon** (the closest honest realization of "did this positional surplus/gap matter"), and where that mapping is ambiguous, **FLAG and grade only the clean subset — report the coverage gap, do not invent an answer key** (standing instr 1 + 6). This is the read most likely to need a Will judgment call; surface what fraction resolves cleanly rather than forcing 100%.

**5. `direction` → realized trend sign, a hit/miss primitive.** `player_signal` `direction` (up/steady/down) resolves against the realized forward-ppg trend vs the as-of baseline → a `direction_hit` primitive (match / no-match), **not** a verdict. Keep it a primitive the scorer aggregates.

**6. Horizon-correct alignment — build it right, the live path inherits it.** Each claim's `resolves_at` dictates which realized window it joins: `player_signal` (weekly) → the forward week(s); `production_vor` / band (ros) → the tail from `as_of_week`; `true_rank` / `bracket_odds` (season) → season-end standings. In the corpus everything is resolved, but the *join must still align the right window per family* — do not grade a weekly claim against a season fact.

---

## The claim → outcome → primitive mapping (grounded in the 4a schema + the verified sources)

| Claim (`read` / `claim_type`) | Realized outcome | Primitive(s) in `resolutions` |
|---|---|---|
| `production_vor` / point (`ros_value`) | Σ `sleeper_points`, weeks ≥ `as_of_week` (scoring-scoped) | `error`, `abs_error` |
| `ros_player_band` / interval (`value`+`lo`/`hi`/`sigma`) | same realized ROS points | `in_band`, **`pit`** = Φ((truth−`value`)/`sigma`) |
| `player_signal` / point (`expected_ppg`) | realized forward ppg (weeks > `as_of_week`) | `error`, `abs_error` |
| `player_signal` / direction | realized forward-trend sign vs baseline | `direction_hit` |
| `true_rank` / ordinal (`rank`) | realized final standing (division-aware seed) | `rank_error` |
| `positional_depth` / point (`surplus_value`) | realized roster×position points (★ clean subset) | `error` (+ coverage flag) |
| `bracket_odds` / probability (`playoff_odds`) | `made_playoffs` (top `playoff_teams`, division-aware) | `brier`, **`pit`** |
| `bracket_odds` / point (`proj_wins`) | realized regular-season wins | `error`, `abs_error` |
| `bracket_odds` / ordinal (`avg_seed`) | realized final seed | `rank_error` |

- **`pit` is the unifying primitive** — one column, every read family that states a distribution; the scorer's PIT-uniformity test is the same math for the band, playoff odds, and (live) the AI grades. Where undefined (point/ordinal/direction), `pit=null` and the family is graded on its native primitive.
- **Unmatched claims are named, never silently dropped.** A player with no realized games (injured, cut) has no ROS outcome → the claim resolves as **explicitly unresolved with a reason**, not dropped and not a fake zero (standing instr 1). Report the unresolved count per family.

---

## Commit 1 — `outcomes_{season}`: derive + persist realized truth from the frozen sources

- **`data_layer` write/read for `outcomes_{season}`** (append-only, diagonal concat, `league_id` nullable) — mirror the 4a `predictions` helpers.
- **Derive the facts** from the **frozen** `join_season` + `matchups` + `league_settings` (long-format) across the 270 league-seasons:
  - `player_weekly_pts` — `(scoring_key, player, week)` from `sleeper_points` (stored once per scoring_key; **verify two same-scoring_key leagues agree** before deduping).
  - `roster_wins` (W over weeks ≤ `reg_end`; T → 0.5 or a stated tie rule), `roster_total_pts`, `roster_position_pts` (for §6).
  - `roster_final_standing` / `roster_seed` / `roster_made_playoffs` — **reuse `compute_bracket_sim`'s division-aware seeding at `reg_end`** (the shared `_sane_playoff_week_start` floor for garbled configs — the 2 known garbled leagues). Do **not** naive-sort.
- **Gate teeth — realized playoff mass = slot count** (the realized-side twin of 3b's `bracket_odds` check): per league, exactly `playoff_teams` rosters have `made_playoffs=true`; division winners auto-seed correctly on the 25 division leagues. No roster silently missing.
- **Determinism + no silent loss** — twice-derive value-identical (`_frame_eq`); every rostered player/roster resolves or is a **named** exception; report per-league coverage.

> **Seam holds — no `queries.js` / view edits** (standing instr 3). `outcomes` is a new derived entity; the front end doesn't read it.

## Commit 2 — `compute_resolutions.py`: the join + the grading primitives (no verdicts)

- **`compute_resolutions.py`** joins `predictions_{season} ⋈ outcomes_{season}` per the mapping table, horizon-correct (decision 6), and writes `resolutions_{season}` (append-only) with the primitives: `error`, `abs_error` (point), `in_band` + **`pit`** (interval; Gaussian CDF via `sigma`), `brier` + `pit` (probability), `rank_error` (ordinal), `direction_hit` (direction). Carry the claim's provenance (`prediction_id`, `code_version`, `constants_hash`, `inputs_ok`, `served`) onto each resolution row so a resolution is always traceable to the exact claim + code + constants that made it.
- **PIT only where a distribution is stated** (decision 3); point/ordinal/direction → `pit=null`, native primitive only.
- **Join integrity — no cartesian blow-up, no silent unmatched drop.** Each claim resolves to **exactly one** outcome (assert row counts: `|resolutions of family f| == |claims of family f that are resolvable|`); unresolved claims are emitted with a **reason**, counted, not dropped.
- **Report distributions, emit no verdict.** Print per-family primitive distributions (mean abs_error, PIT histogram, Brier, in-band coverage, rank_error spread, direction hit-rate) as a **first look** — explicitly labelled "not a grade." If a distribution looks alarming (PIT piled at 0/1, coverage far off nominal), **surface it as a finding**, change no constant, add no verdict (standing instr 4). The scorer judges; 4b reports.

## Commit 3 — the corpus ledger gate + docs (+ scope Session 5)

- **`check_resolutions`** (mirror `check_predictions` / `check_spine`), asserting over the 270 league-seasons:
  1. **Resolution coverage** — every resolvable claim family joined; unresolved claims each carry a reason; coverage reported per family (esp. §6's ★ clean subset).
  2. **Primitive validity** — `pit ∈ [0,1]`, `brier ∈ [0,1]`, `in_band ∈ {0,1}`, `rank_error` integer; `pit` non-null **iff** interval/probability; point families have `error` non-null.
  3. **Law 1 — no verdict.** `resolutions` holds primitives but **no aggregate pass/fail, no per-read judgement column**; assert the forbidden-*verdict* set (an aggregate `read_score`, a boolean `claim_correct`, a `suppress` flag) is **absent** — those belong to the scorer. Prove-bite: injecting an aggregate verdict column fails.
  4. **Traceability + determinism** — every resolution rejoins to its `prediction_id` + `outcome`; twice-compute value-identical.
  5. **Realized integrity rides through** — playoff mass = slot count survives into the graded `brier`/`pit` rows (the property, not just the file — standing instr 7).
- **Prove each check bites** (drop an outcome → coverage fails; a `pit=1.3` → validity fails; an aggregate verdict column → Law-1 fails; a wall-clock nondeterminism → determinism fails).
- **Docs:** `STATUS.md` (the ledger is COMPLETE — `predictions ⋈ outcomes → resolutions`; primitive distributions as a first look, labelled not-a-grade; unresolved + §6 coverage), `TECHNICAL_ARCHITECTURE.md` (the two new entities + `compute_resolutions`; the primitives-not-verdicts boundary), `IMPROVEMENT_LOOP.md` (L2 built end-to-end). **Scope Session 5 — the scorer (L3) — in the closedown** (see *Out of scope*).

---

## Acceptance gates

1. **4a-fix confirmed first** — `predictions` carries a single committed `code_version`; 4b joins the corrected ids.
2. **`outcomes` complete + immutable** — all realized facts derived from frozen sources across 270 league-seasons; append-only; `league_id` nullable by scope; weekly points deduped once per scoring_key (agreement verified).
3. **Realized seeding correct** — made-playoffs / standings via the **division-aware** logic; realized playoff mass = `playoff_teams` per league incl. the 25 division leagues; garbled configs floored via the shared helper.
4. **`resolutions` primitives valid + horizon-correct** — `error`/`in_band`/`pit`/`brier`/`rank_error`/`direction_hit` per the mapping; PIT only where a distribution is stated; each claim → exactly one outcome; unresolved **named + counted**.
5. **Law 1 structural** — `resolutions` emits **no verdict / aggregate score / suppress flag**; the primitives are not judgements; prove-bite fires.
6. **Determinism** — twice-derive `outcomes` and twice-compute `resolutions` value-identical (`_frame_eq`, not raw bytes).
7. **Traceability** — every resolution rejoins to its claim's `prediction_id` + provenance (`code_version`/`constants_hash`/`inputs_ok`).
8. **Budget + seam** — row counts / wall-clock / ≈0 re-run reported; `queries.js` / views untouched; the frozen `predictions` + reads + substrate unchanged (value-identical if read).

---

## Out of scope

- **Session 5 — the Scorer (L3) (scope it in the closedown; DO NOT start it).** `compute_engine_scorecard.py` over `resolutions`: **skill** (MAE vs each read's declared naive baseline — `recent_ppg` for §1, coin-flip for §5), **calibration** (PIT-uniformity KS, coverage, Brier reliability), **confidence-honesty** (the headline law-2 metric — is error monotone in the read's stated `confidence`? — using the `confidence`/`confidence_label` 4a stamped), **discrimination** (Spearman). Sliced by league/position/week/confidence-tier/`inputs_ok`/cohort; the Trust Report + traffic lights. **This is the first thing that judges** — the ledger grades nothing; the scorer does. Pre-registered predictions to hold it to live in `PM_SESSION_STARTUP.md` / `IMPROVEMENT_LOOP.md`.
- **The tuner (L4), AI eval (L5), live path (L1/served=true).** Not here.
- **Re-grading, verdicts, suppression, any constant change.** 4b computes primitives and reports distributions; it judges nothing.
- **Re-opening 4a `predictions`, the reads, or the substrate.** Frozen inputs (verify value-identical if read). `market_vor` / `ros_synthesis` remain un-backfillable (forward-only) — graded live, not here.
- **The `data_health` entity.** Still the live path's (Session 7); 4b consumes the `inputs_ok` column 4a already derived.

---

## Definition of done

- `outcomes_{season}` — realized truth from the frozen sources across the 270 league-seasons; append-only; scoped keying; **division-aware** standings/made-playoffs with realized mass = slot count.
- `compute_resolutions.py` — `predictions ⋈ outcomes → resolutions_{season}` with valid, horizon-correct **primitives** (PIT the unifier, defined only where a distribution is stated); unresolved claims **named + counted**; §6 coverage reported.
- **Law 1 holds structurally** — no verdict/aggregate-score/suppress column exists; the scorer (Session 5) is the first judge.
- `check_resolutions` **green with teeth** (coverage · primitive validity · Law-1 · traceability · determinism all proven to bite); budget reported; seam held.
- **Session 5 (the scorer) scoped in the closedown — not started.**

---

> ## Standing instructions
> 1. **A suspiciously clean value is a bug until proven otherwise.** *(A player with a clean-zero realized ROS may be uninjured-but-unmatched — resolve as unresolved-with-reason, not a real 0. A read whose PIT is perfectly uniform on the first try is suspicious, not triumphant.)*
> 2. **A refactor that changes a number is a bug** — prove equivalence. *(Deriving `outcomes` must not perturb the frozen `join_season` / `predictions`; verify value-identical if read.)*
> 3. **If the fix wants to touch `queries.js` or a view, the seam has leaked.** *(Both new entities are internal ledger plumbing.)*
> 4. **Report, don't grade.** *(Compute the primitives, print the distributions labelled "not a grade," surface alarming ones — but emit no verdict and change no constant. The scorer judges; the tuner tunes.)*
> 5. **Deleting dead code must not move a live number.**
> 6. **A plausible explanation is not a diagnosis** — name the mechanism, or write UNKNOWN and escalate. *(A family with low resolution coverage: name why — unmatched players? an ambiguous §6 answer key? — don't hand-wave.)*
> 7. **"The artifact exists" and "the consumer uses it" are two different gates.** *(An `outcomes` row on disk ≠ made-playoffs mass sums to the slot count ≠ the resolution grades against the right truth. Gate the property.)*
> 8. **Persist the substrate; never re-derive from a moving source.** *(Realized truth comes from the frozen persisted `join_season`/`matchups`, not a re-fetch; determinism is value-equality on a re-run. And: confirm the 4a-fix landed — resolutions must join corrected `prediction_id`s.)*
