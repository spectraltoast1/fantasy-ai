# The Improvement Loop — Architecture Spec

**Created:** 2026-07-12 · **Revised:** 2026-07-18 (corpus-first sequencing)
**Status:** BUILT through **L4** (L0 keying · L1 health-flag · L2 ledger · L3 scorer · L4 tuner) — the loop
runs end-to-end on the frozen corpus and emits reviewed proposals. Latest iteration: **Session 8 — band
honesty** (the ROS bull/bear band re-tuned for honest coverage via a new `BEAR_Z` down-side half-width + a
raw-points confidence signal, both PROPOSED via shadow re-scores; see `SESSION_8_BAND_HONESTY.md` +
`proposals/2026-07-16-{BULL_Z,BEAR_Z,ANCHOR_W}.md` + `proposals/2026-07-16-band_confidence_ros_sigma.md`).
NEXT: Session 9 (cleanup) then silent-reads confidence, then the live/AI track (L5 AI-eval + the live
`data_health` / `served=true` writes remain design-only).
**Premise:** [`LLM context/712_BACKEND_AUDIT.md`](../LLM%20context/712_BACKEND_AUDIT.md)
**Feeds it:** [`LEAGUE_CORPUS.md`](./LEAGUE_CORPUS.md) (offline) · [`PILOT_2026.md`](./PILOT_2026.md) (live)

The system that makes the **existing** reads better as weeks, leagues and users accumulate. It adds
**no new features**. It adds memory, measurement, and a proposal surface — so that improving a read
becomes a repeatable, evidenced process instead of a one-off session.

**Autonomy contract (decided):** the loop **auto-tunes constants and auto-evaluates prompts. It never
promotes.** Every change to shipped behaviour arrives as a reviewed proposal with evidence, and you
merge it. AI is used in exactly one place — writing the *narrative* of an improvement lead that the
programmatic scorer has already ranked. Everything that decides anything is deterministic.

---

## 0. The shape of it

```
                        ┌───────────────────────────────────────────────┐
                        │ L0  KEYING   league_id · scoring_key          │  ← the unlock
                        └───────────────────────────────────────────────┘
                                          │
   fetchers ──▶ ┌──────────────┐          ▼
                │ L1  HEALTH   │   data_health_{season}       "were the inputs clean?"
                └──────────────┘   (daily, append-only)
                                          │  inputs_ok flag rides on every claim
   transforms ─▶┌──────────────┐          ▼
   + ai/ ──────▶│ L2  LEDGER   │   predictions_{season}   ⋈  outcomes_{season}
                └──────────────┘   (append-only, immutable)     │
                                          │                     │
                                          ▼                     ▼
                                   resolutions_{season}  ← the join: error, PIT, brier
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
      ┌──────────────┐            ┌──────────────┐            ┌──────────────┐
      │ L3  SCORER   │            │ L4  TUNER    │            │ L5  AI EVAL  │
      │ skill        │            │ constant     │            │ grounding    │
      │ calibration  │            │ registry +   │            │ outcome      │
      │ CONF-HONESTY │            │ CV sweeps    │            │ champion/    │
      └──────────────┘            └──────────────┘            │ challenger   │
              │                           │                   └──────────────┘
              └───────────────┬───────────┴───────────────────────────┘
                              ▼
                    ┌──────────────────────┐
                    │ L6  PROPOSER         │   weekly digest → YOU
                    │ trust report         │   • traffic lights
                    │ tune proposals       │   • merge-ready constant diffs
                    │ improvement leads    │   • ranked improvement projects
                    └──────────────────────┘
                              │
                              ▼
                    human promotes (a normal worktree session)
```

Everything is a `python3 -m application.…` module writing parquet through `data_layer`. **Host-agnostic
by construction** — launchd today, GitHub Actions or the app host tomorrow, zero code change. The loop's
jobs register in the existing `fetchers/run.py` registry; *the meter stays external*, as already decided.

---

## L0 — Keying (`league_id`, `scoring_key`) · **the unlock; everything is blocked on it**

Three scopes, made explicit in `data_layer` instead of implicit in the filenames.

| Scope | Key | Entities | Compute cost |
|---|---|---|---|
| **NFL-global** | `season[, week]` | `nfl_stats`, `projections`, `adp_*`, `market_values`, `team_news_raw`, `team_news_dossier`, `player_news_slice` | **once**, all leagues |
| **Scoring-scoped** | `+ scoring_key` | `projection_consensus`, `ros_player_band`*, `ros_synthesis` | once **per distinct scoring profile** |
| **League-scoped** | `+ league_id` | `player_signal`, `production_vor`, `market_vor`, `ros_league_view`*, `true_rank`, `positional_depth`, `bracket_odds`, `team_form`, `team_leakage`, `manager_*` | per league |

`scoring_key` = `ppr` / `half` / `std` / `cust-<8-char hash of the normalised scoring dict>`. Two PPR
leagues **share one file**. This is what keeps AI cost flat as leagues grow (audit cost table).

\* **Required split** (audit S3.2): `ros_outcome_shape` becomes two entities —
`ros_player_band` (scoring-scoped: center, bull, bear, sigma, cv — needs no roster) and
`ros_league_view` (league-scoped: `spectrum_pos` vs the league's pools, roster membership). Then
`ros_synthesis` reads the scoring-scoped half and legitimately stays shared.

**Also here:** `config.SLEEPER_LEAGUE_ID` (one string) → a **league registry** (`leagues.parquet`:
`league_id`, `season`, `scoring_key`, `shape_key`, `is_mine`, `onboarded_at`, `pilot_cohort`), and the
`MY_USERNAME` hardcode in `queries.js` dies with it (bake `is_me` into the teams parquet at fetch time —
already flagged as a latent in TECHNICAL_ARCHITECTURE).

> **Why first:** a ledger row without a `league_id` is worthless, and every downstream metric slices by
> league. There is no cheaper moment to do this than before league #2 exists.

---

## L1 — Health (the precondition layer)

> *You didn't rank input quality as an improvement channel. It isn't one — it's a **precondition**. A
> report that says "calibration fell in week 9" when the real cause was three missing market days
> teaches you the wrong lesson. This layer's only job is to make the scorer incapable of lying to you
> about **why** something moved.*

**New entity `data_health_{season}`** (append-only, one row per `(date, source)`), written by promoting
the existing `fetchers/check_collectors.py` from a stdout gate to a persisting one:

```
date · source · rows · expected_rows · coverage · staleness_days · errors · degraded (bool) · note
```

Sources: the 3 collectors (`leaguelogs`, `news`, `sleeper`) **plus derived-input health** — join
remainder count, projection coverage % of the rostered pool, `signal_tier` distribution of the news
slice, market-profile presence.

**Contract:** a week is `inputs_ok = false` if any source feeding a read was `degraded`. The scorer
**quarantines** those weeks into a separate bucket and is **forbidden** from attributing a metric move
to the model within them. That is the entire point of the layer.

*Operational note:* 65% collector coverage today. The loop's numbers are only as good as this, so
moving the collectors off the laptop is a **loop prerequisite**, not a nice-to-have.

---

## L2 — The Ledger · **the missing spine; the only piece with a hard deadline**

Two append-only entities, plus their join. These are the first entities in the project whose write
semantics are **immutable** — following `market_values` and `team_news_raw`, which already prove the
pattern.

> **STATUS — L2 BUILT END-TO-END (`predictions ⋈ outcomes → resolutions`).** **`outcomes` + `resolutions`
> are DONE (Session 4b):** `outcomes_{season}` (962,196 realized facts from the frozen sources; division-aware
> standings; realized playoff mass == slot count) and `resolutions_{season}` (`corpus/compute_resolutions.py`,
> 2,893,834 rows = 1:1 with the claims) carrying the grading primitives — `error`/`abs_error`, `in_band`,
> `pit` (interval Gaussian + probability's deterministic randomized-PIT), `brier`, `rank_error`,
> `direction_hit` — gated green by `corpus/check_resolutions.py`. **Two schema realities vs the block below:**
> (a) a **scoping correction** — realized player points are LEAGUE-scoped (`scoring_key` is only a
> reception-tier classifier; ~9.5% of player-weeks differ across same-key leagues), so `outcomes` carries a
> league-scoped `player_weekly_pts` (for the league point claims) AND a scoring-scoped
> `player_weekly_pts_canonical` (for the band); (b) `pit` is the unifier but ONLY where a distribution is
> stated (interval + probability) — point/ordinal/direction get `pit=null`, no fabricated sigma.
> **Law 1 holds across the entity split: `resolutions` carries primitives, NEVER a verdict / aggregate
> score / suppress column** — the scorer (L3, Session 5) is the first thing that judges. **L3 is now BUILT
> (Session 5) — see the L3 status marker below. NEXT = L4 (the Tuner).**
>
> **STATUS — `predictions` is DONE (Session 4a):** the entity, its provenance
> scaffolding (constants snapshot + `constants_hash`, versioned `inputs_ok`), and the read→claim reshape
> are built and backfilled `served=false` across the 270 spined league-seasons (2,893,834 claims), gated
> green by `corpus/check_predictions.py`. Two schema refinements landed vs the block below: (a) the
> `prediction_id` key adds **`season`** and **`claim_type`** (the scoring-scoped band recurs yearly, and
> one read emits several claim families per subject-week — without them ids collide); (b) the flat `value`
> / `confidence` columns gained **typed sidecars** — `value_str` (categorical `direction`), `sigma`
> (interval scale, so PIT reads a typed param not BULL_Z), and `confidence_label` / `confidence_json`
> (canonical numeric confidence + which signal it is + an audit-only payload). `production_vor` +
> `bracket_odds` wins/seed + `player_signal` direction have **no native confidence** — flagged, not
> fabricated. **`outcomes` + `resolutions` are now BUILT (Session 4b — see the status note above).** The `predictions` schema below
> is otherwise as-built (the corpus fills only the 5 spine reads + `ros_player_band`; the AI reads and
> `market_vor` in the `read` enum are the live-path future).

### `predictions_{season}` — one row per *claim the engine made*

```
prediction_id     hash(league_id, read, subject_id, week, horizon, code_version)
league_id         null for NFL-global / scoring-scoped reads
scoring_key
season · week     the week the claim was MADE (the as-of)
read              projection_consensus | player_signal | production_vor | ros_player_band |
                  ros_synthesis | true_rank | positional_depth | bracket_odds | market_vor | ...
subject_type      player | roster | matchup | league
subject_id        sleeper_player_id | roster_id | matchup_id
claim_type        point | interval | probability | ordinal | grade | direction
value             the number (center / p_win / grade / rank / vor)
lo, hi            interval bounds where they exist (p25/p75, bear/bull) — else null
horizon           week | ros | season
resolves_at       the week truth becomes knowable (or 'season_end')
confidence        the engine's OWN stated confidence — low/med/high, band width, signal_tier, ros_cv
── provenance ──
code_version      git sha at write time
constants_hash    hash of the tuning-constant vector in play
prompt_version    hash of the prompt module (AI reads) — else null
model             AI model id — else null
inputs_ok         from L1
served            true = shown to a user · false = backfilled reconstruction
created_at
```

**Written at serve time. Never overwritten.** A re-run with different code writes a **new row** with a
new `code_version` — you keep both and can see the delta. This is the inverse of today's semantics and
it is the whole ballgame.

**Critically: the AI grades go in here too.** `bull_grade` / `bear_grade` / `situation_grade` are
`claim_type = ordinal` rows. Which means the AI layer becomes gradeable by the **same scorer as
everything else** — no separate eval infrastructure. That is the load-bearing design choice in this
spec.

### `outcomes_{season}` — one row per *fact that resolved*

```
season · week · scoring_key · subject_type · subject_id · outcome_type · value · recorded_at
```
e.g. player weekly PPR under scoring_key; player realized ROS points; matchup win/loss; final standing;
made-playoffs y/n; role-change occurred y/n (for `situation_grade`).

### `resolutions_{season}` = predictions ⋈ outcomes → `compute_resolutions.py`

Adds the **grading primitives**:

| Column | For | Meaning |
|---|---|---|
| `error`, `abs_error` | point claims | signed / absolute miss |
| `in_band` | intervals | did truth land in `[lo, hi]` |
| **`pit`** | intervals + probabilities | **where in the predicted distribution truth landed, ∈ [0,1]** |
| `brier` | probabilities | `(p − outcome)²` |
| `rank_error` | ordinals | claimed rank − realized rank |

> **PIT is the unifying primitive.** A well-calibrated engine has PIT ~ Uniform(0,1) — *for weekly
> bands, for ROS bull/bear, for playoff odds, for AI grades, all of it*. One scorer, one metric, every
> read. It is why L3 is small instead of seven bespoke scorers.

**Law 1 is enforced structurally here:** a single PIT of 0.97 is *not an error*. The scorer only ever
judges **distributions** of PIT. **No single-claim verdicts are ever emitted, by construction.** Grade
process, not outcome — encoded, not just intended.

### The ledger has two sources — and that is what un-scrambles the schedule

| Source | `served` | Where from | When |
|---|---|---|---|
| **Corpus backfill** | `false` | [`LEAGUE_CORPUS.md`](./LEAGUE_CORPUS.md) — completed league-seasons, reconstructed as-of and graded against known truth | **now, offline** |
| **Live serving** | `true` | 2026, as weeks land | from week 1 |

**Same schema. Same scorer. Two sources.** This is the load-bearing consequence of the corpus:

> You build the ledger **for the backfill** — where it pays off immediately, with real *n*, before
> kickoff — and it is **already standing** when week 1 arrives. The live path becomes a small delta
> (`served=true` + the L1 health flag), not a pre-kickoff scramble.

> ### ⏰ What is still deadline-bound
> Reconstruction can be rebuilt forever; **the *served* record cannot.** Once 2026 is live, any week that
> passes without a `served=true` row is a week of *live* learning you never get back. But the *schema* and
> the *scorer* will already exist by then, because the corpus needed them first. **The deadline is now a
> switch to flip, not a system to build.**

---

## L3 — The Scorer → `compute_engine_scorecard.py` → `derived/engine_scorecard_{season}`

> **STATUS — L3 BUILT (Session 5, 3 commits): the first measurement the project has ever taken.**
> `corpus/compute_engine_scorecard.py` scores the frozen `resolutions` into `engine_scorecard_{season}`
> (3,518 aggregate slice-verdicts over the 6 seasons) — **skill** vs a declared naive baseline
> (`corpus/scorecard_registry.py`), **calibration** (PIT-KS/coverage/Brier), **confidence-honesty (law 2)**,
> **discrimination** — sliced `overall · week · league · position · cohort · scoring_key` (model quality, on
> `inputs_ok ∧ resolved`) + `inputs_ok · resolution_status · confidence_tier` (quarantine + reliability,
> never blended). Gated green-with-teeth by `corpus/check_scorecard.py`; the human **Trust Report**
> (`corpus/trust_report.py` → `TRUST_REPORT.md`). **Grounding corrections vs the block below:** (a)
> `resolutions` carries NEITHER `confidence` NOR any naive baseline → the scorer re-joins `predictions` +
> derives naives from `outcomes`; (b) only 2 reads had a baseline to *promote* (player_signal→`naive_ppg`,
> playoff-odds→0.25 Brier), the rest are *declared* canonical, and the band is `skill=na` (calibration is its
> lens). **Findings (reported, NOT tuned):** projection optimism is real + stable (`production_vor` loses to
> carry-recent-forward every season; the band under-covers ~0.55 vs 0.80); the measurement reads HOLD
> out-of-sample; confidence-honesty is MIXED — playoff-odds/true-rank honest, the band's `ros_cv` is
> **INVERTED**, positional_depth's `spectrum_pos` doesn't sort, 4 reads state no confidence. Law 1 STRUCTURAL
> (judges distributions, never a `prediction_id`); report-don't-tune / don't-promote held; seam held. **The
> HTML dashboard is deferred to a fast-follow "Session 5b" (the markdown Trust Report is the must-have).
> NEXT = L4 (the Tuner).**

Per `(read × slice × week)`, from `resolutions`:

1. **Skill** — MAE/RMSE against the read's **declared naive baseline**. Every backtest already has one
   informally (`recent_ppg` for §1, coin-flip for §5); promote it to a registry field so the scorer can
   compute `skill = 1 − MAE_engine / MAE_naive` uniformly. **A read that stops beating its baseline
   out-of-sample should stop shipping.**
2. **Calibration** — PIT uniformity (KS statistic), coverage at nominal levels, Brier + a reliability
   curve for probabilistic reads.
3. **Confidence honesty (law 2) — the headline metric.** *Do the engine's own high-confidence claims
   actually have lower realized error than its low-confidence claims?* Computed as error stratified by
   the `confidence` column, and required to be **monotone**. If it isn't, the confidence signal is
   laundering noise as caution and the read should be **suppressed, not shipped**. Nothing measures this
   today; it is the single most important number the loop will produce.
4. **Discrimination** — Spearman(claim, truth): does the *ranking* carry, independent of the level.

**Slices:** league · position · week · confidence tier · signal_tier · `inputs_ok` · cohort.

**Output:** the parquet, plus a **Trust Report** (markdown + a self-contained HTML dashboard — reuse
the DuckDB-WASM/`build-dashboard` idiom already in the stack):

- traffic light per read × {skill, calibration, confidence-honesty}
- **what moved since last week, and whether the cause was data or model** (L1 makes this answerable)
- the *"what we'd honestly tell a user"* line per read — which is also the copy the front end should use

---

## L4 — The Tuner (auto-tune · **human promotes**)

> **BUILT — Improvement-Loop Session 6 (2026-07-17).** `transforms/_constants.py` (the dials registry) +
> `corpus/tuner.py` (the one split-aware sweep harness) + `data_layer.tune_proposals` + `corpus/check_tuner.py`.
> Two refinements to the spec below, both from building it against the real corpus:
> 1. **Dials-by-purpose, not all-constants.** The registry holds only the constants actually swept — ONE
>    home per constant (a dial migrates in the first time it is tuned; a pin never migrates). A module
>    re-exports a migrated dial, so no live number moves and `constants_snapshot` stays the full-vector
>    fingerprint. The `BULL_Z` drift is resolved by DECLARING the real 1.44, not by re-tuning.
> 2. **Two holdouts, one binds per session.** Season-wise (TRAIN/DEV/TEST) is the operative OOS test.
>    League-wise (hold out the generalization cohort) is built + structurally sealed now, but is
>    **N/A-by-construction for a constant whose objective doesn't fit a per-league value** — it binds from
>    Session 7's genuinely league-scoped reads. ("The only honest test of an any-league constant" below is
>    right in general, but was an overstatement for the five scoring/nfl/player-level dials tuned first.)
>
> First run (as-of 2026-07-16): `de-bias-the-center-first` is the top LEAD; all four band dials HELD
> (entangled with the optimistic center — `SKEW_GAIN`'s OOS fit even moves 1.5→1.0, confirming it);
> `OPP_HALF_LIFE_WK`/`BAND_Z` already OOS-optimal → HOLD; zero RECOMMENDs (nothing clears the guardrails
> un-entangled — the constants are already well-fit except where entangled with the center). The split is
> enforced STRUCTURALLY: a `SplitReader` raises on any read of a sealed partition, so a peeking fit is
> unrepresentable (proven to bite in `check_tuner`).

Generalises the five ad-hoc `--sweep` flags into one harness.

### 4a. Constant registry — `transforms/_constants.py`

Today the tunables are scattered module globals with no single source of truth (audit S3.3: STATUS says
`BULL_Z=1.645`, the code says `1.44`). Declare them:

```python
Tunable(name="BAND_Z", module="compute_projection_consensus", current=0.55,
        grid=[0.5, 0.55, ..., 1.4], gate="backtest_projection_consensus",
        objective="|coverage−0.50| + |tail imbalance|",
        fitted_on="2025", last_tuned="2026-06-xx", scope="scoring")
```

This is the config seam TECHNICAL_ARCHITECTURE already says is coming. Build it here — the loop needs
it, and it kills the drift class of bug outright.

### 4b. Split discipline (the fix for the in-sample problem)

**The sweep fits on TRAIN and certifies on HELDOUT. Always.** The corpus gives you **two** independent
holdout dimensions where you previously had zero:

- **Season-wise:** fit 2021–2023 · dev 2024 · **test 2025** (untouched until the end).
- **League-wise:** fit on leagues A–M · **holdout N–T** — the only honest test of the any-league
  generalisations, since a held-out superflex or division league is a genuinely unseen *shape*.

Both are available **offline, before 2026 kicks off**. All five constants (`BAND_Z`, `SKEW_GAIN`,
`BULL_Z`, `ANCHOR_W`, `OPP_HALF_LIFE_WK`) get retuned out-of-sample — and for the first time the
**league-level** constants can be tuned at all, which a single 10-team league could never support.

> **Previously this section said league reads "stay under-powered until pilot leagues land." The corpus
> retires that constraint.** Statistical power is now a *backfill* problem, not a *recruitment* problem.

### 4c. The proposal artifact

The tuner never edits a transform. It writes `proposals/{date}-{constant}.md` + a machine-readable row:

```
constant · current → proposed · train metric · HELDOUT metric · Δ on every other gate
· effect size · inputs_ok over the fit window · RECOMMEND / HOLD
```

**Guardrails — a proposal is only surfaced if all four hold:**
1. the **holdout** improves (not the train metric),
2. **no other gate regresses** beyond tolerance (constants are coupled: `BAND_Z` → VOR → true rank → bracket odds),
3. `inputs_ok` over the whole fit window,
4. the effect exceeds a minimum — **don't churn constants for noise.**

You merge it in a normal worktree session. That is the "auto-tune, human promotes" contract.

---

## L5 — AI evaluation (today's biggest blind spot)

**Do this cheaply first:** add `prompt_version` (hash of the prompt module) alongside the existing
`model` / `generated_at`. One column. Without it, nothing below is possible.

**Track 1 — Grounded eval (deterministic, no AI judge).** Promote what `check_ros_synthesis` /
`check_team_news_dossier` already compute from a stdout gate to a **persisted, per-run score**:
headline→article traceability rate, prose-leak rate, schema validity, on-team resolution rate,
zero-signal honesty. Cheap, deterministic, trended over time.

**Track 2 — Outcome eval (the new thing).** Because the grades are already `ordinal` rows in the ledger
(L2), the L3 scorer grades them **with no new machinery**:

- does `bull_grade` rank-correlate with **realized** ROS ceiling?
- does a high `situation_grade` actually predict fewer role changes / lower ROS variance?
- **does `confidence = high` actually mean lower error?** (law 2, applied to the AI)

**Track 3 — Anchor divergence.** Log every case where the AI grade contradicts its quantitative anchor.
Systematic divergence is *either* a prompt bug *or* a signal the anchor is missing something real. Both
are improvement leads, and you can't tell which without the log.

**Champion / challenger.** `ros_synthesis` is scoring-scoped and cheap (~$4.25/wk full pool). Run two
prompt versions, write both rows, **serve the champion, score both.** After N weeks the scorer tells you
which wins on outcome *and* grounding. You promote. Cost ~2× — still under $10/week. **Cost is not a
constraint here; don't let it shape the design.**

**Explicitly rejected: an LLM-as-judge as a primary metric.** It is unfalsifiable and it drifts. AI is
used **only** in L6, to write the narrative of a lead the data has already ranked.

---

## L6 — The Proposer (your human-in-the-loop surface)

The weekly artifact you actually read. One scheduled job, four sections:

1. **Trust report** (L3) — traffic lights; what moved; data-vs-model attribution.
2. **Tune proposals** (L4) — merge-ready constant diffs with holdout evidence.
3. **Improvement leads — ranked programmatically, narrated by AI.** The data mines and ranks; Claude
   writes the brief. Sources, in priority order:
   - the worst **confidence-honesty** violation (a law-2 breach outranks everything),
   - the worst **skill** slice (*"TE bands are 12 pts under-covered"*, *"rookie WRs break the bear floor
     3× as often"*),
   - the input most often implicated in a degraded week,
   - where the AI most often **diverges from its anchor**.
   Each lead: the pattern · a hypothesis · **the experiment that would settle it** · the expected effect
   size. That last one is what makes it a *project proposal* and not an observation.
4. **Suppression recommendations** — reads whose confidence isn't earning should stop speaking (law 2).
   The loop is allowed to *recommend silence*, and that is a feature.

---

## Design laws — how the loop honours them

| Law | Encoded as |
|---|---|
| **1. Grade process, not outcome** | The scorer judges **distributions** of PIT/error, never a single claim. `code_version` + `inputs_ok` mean a read is only ever graded against **what was knowable when it spoke**. No single-claim verdicts exist in the schema. |
| **2. Speak only when confident** | Confidence-honesty is the **headline metric**, and the loop can recommend **suppressing** a read that fails it. |
| **3. Borrow the substrate; build the layer** | The loop tunes the thin decision layer's constants. It never builds a projection engine. |
| **4. Consultation, not autopilot** | The loop **proposes; you promote.** Same discipline the product applies to its user — applied to its builder. |

---

## Build order — **corpus-first** (respecting one-session/one-worktree/≤3-commits)

The corpus reorders this. The old plan raced to instrument the live path before kickoff. The new plan
**builds the same machinery for the backfill — where it pays off immediately — and then flips a switch
when the season starts.**

### Track A — offline, before kickoff · *the value is here*

| # | Session | Why now |
|---|---|---|
| **1** | **L0 keying** — `league_id` + `scoring_key`, league registry, partition derived parquet **by league**, split `ros_outcome_shape` (fixes audit S1.3 / S3.1 / S3.2) | **Blocks everything.** And now it's ~10 leagues, not 2 — the partitioning also dodges the O(n²) write. |
| **2** | **Corpus harvester** — BFS crawl (`_manager_leagues` + `classify_league`, already built) + corpus registry + the **shape matrix** (superflex, division, custom scoring, 12-team) | The asset. See [`LEAGUE_CORPUS.md`](./LEAGUE_CORPUS.md). |
| **3** | **L2 ledger schema, populated by backfill** (`served=false`) + `outcomes` + `compute_resolutions` · **include the `prompt_version` column now** (free here, expensive later) | The schema the live path will reuse verbatim. |
| **4 ✅** | **L3 scorer** + trust report **(DONE — Session 5)** | **First real measurement the project has ever taken.** 3,518 slice-verdicts; projection optimism confirmed, measurement reads hold, confidence-honesty mixed (band `ros_cv` inverted). HTML dashboard → fast-follow 5b. |
| **5** | **L4 tuner** — constant registry + season-wise **and** league-wise holdout + retune all five constants OOS **(NEXT)** | The payoff. Expect regressions; that's the point. The scorer hands it the worst skill/confidence-honesty slices as targets. |
| **6** | *(reactive)* **Fix what the corpus broke.** Real superflex / division / custom-scoring leagues hitting synthetic-gated code **will** find bugs. Budget the session. | Better in July than in someone's live league in week 6. |

### Track B — live, at kickoff · *a small delta, not a build*

| # | Session | Why |
|---|---|---|
| **7** | **Live path** — `served=true` writes + **L1 health** (`data_health`; collectors off the laptop) | The schema and scorer already exist. This is the switch. |
| 8 | **L5 AI eval** — grades→ledger, champion/challenger on `ros_synthesis` | §2's AI half is **the one thing the corpus cannot grade** (no historical RSS) — it can only be graded forward. So this is genuinely in-season work. |
| 9 | **L6 proposer** — the weekly digest | Reads an accumulating ledger. |

### The reframe

> **Old:** race to instrument before week 1, then wait a whole season to learn anything.
> **New:** learn everything the corpus can teach you **before** week 1 — six of seven reads, retuned
> out-of-sample — and let 2026 teach you only what it uniquely can: **news-anchored §2, market VOR, live
> reliability, and real served decisions.**

The pre-kickoff window stops being a scramble to build a recorder and becomes **five weeks of actual
measurement.** That is a much better use of the time you have.
