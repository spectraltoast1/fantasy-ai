# STATUS

**Last updated:** 2026-07-18 (**BACKEND — L4 THE DE-BIAS (Session 7, 3 commits): the second anchor was
BUILT + TUNED and found NOT to fix the optimism — the lever is band WIDTH (Session 8).** `FORM_ANCHOR_W` is
the **6th dials-registry dial** (`_constants.py`, `current=0.0` → ships at **IDENTITY**; no frozen-snapshot
pin / no `check_tuner._MODULES` drift entry — it did not exist when the 2.9M predictions were made, so it is
NOT in `constants_hash`; `check_debias` gates it instead). The de-bias is a **decision-layer convex blend in
the shared ROS-centre aggregator** `compute_production_vor._ros_values`: `ros_value = (1−λ)·borrowed_centre +
λ·(recent_ppg × n_weeks)`, `recent_ppg = mean(pts|wk≤N)` (the scorer's `recent_ppg_forward` proxy, reused
via `recent_ppg_expr` — std instr 5), on the centre's own scoring basis (`nfl_stats` via `actual_points_expr`
== canonical for ppr/half/std). **Both `production_vor` AND the band inherit it** (the band's `ros_center` ==
production_vor's `ros_value`), so ONE blend de-biases both — a convex blend of two existing series, not a
projection model (design law 3). **λ=0 recomputes the frozen spine value-identical** (both reads); λ>0 moves
the number (consumer-uses-it, std instr 7). **Tuned through the Session-6 harness on the split**
(`backtest_production_vor.objective` = scoring-scoped **MAE(debiased centre, realized ROS CANONICAL)**, never
raw PPR): λ*=**0.1**, DEV 2024 MAE 21.946→21.743 (effect **0.20 < the 0.5 floor**) → **HELD**; all 3 coupled
gates pass. **THE RE-SCORE IS A NULL** (`rescore_debias.py` — SHADOW, no frozen-corpus mutation): de-biasing
the centre does **NOT** recover band coverage at the frozen `BULL_Z=1.44`/`ANCHOR_W=0.25` — coverage sits
~0.57 (2023-25, ≈ the cited ~0.55), FLAT then DECLINING as λ rises; the **~0.32–0.47 below-bear low-miss tail
is unmoved**. **This does NOT confirm the Session-6 entanglement thesis.** MECHANISM (std instr 6): the miss
is hugely asymmetric (~0.43 below-bear vs ~0.00 above-bull) — a band-**WIDTH** problem, not centre height;
recent form can't predict the *later* busts, so the bear tail is unmoved. The **honest, leak-safe** de-bias
barely helps centre-MAE — the scorer's "production_vor loses to carry-recent-form every season" relied on the
naive's **hindsight** realized-forward-week count (`n_fwd`) a shipped projection can't use; λ=1 (pure form) is
far worse (MAE ~35–40), so the shallow interior optimum near λ≈0.1 is real (std instr 1). **Delta-tracking:**
`data_layer.write/read_center_gap` (append-only, provenanced to the frozen L3 baseline) persists the seasonal
predicted-vs-realized centre gap per `(season, scoring_key)` — **+23 to +43 pts/season, always positive** (the
systematic optimism magnitude); the substrate for a future SEASONAL auto-update via a **SYSTEMATIC-shrink**
de-bias (NOT recent form — recent form is itself optimistic). `corpus/check_debias.py` **GREEN WITH TEETH**
(λ=0 identity + λ>0 bites · decision-layer convex-blend algebra · both reads consume it · the re-score writes
NOTHING to predictions/outcomes/resolutions/scorecard · delta-tracking idempotent · determinism — a two-way
player's duplicate `nfl_stats` rows made recent-form non-deterministic under `.first()`, fixed to `.max()`).
`check_tuner` **GREEN** (the 6th dial swept, ships at 0.0, HELD; `debias_lead` now carries the S7 outcome).
**Auto-tune, human promotes — `FORM_ANCHOR_W` ships at 0.0, λ* is a proposal, nothing merged, no band dial
touched; seam held (`queries.js`/views/reads/ledger/scorer untouched).** **Raw-PPR-vs-canonical lead
resolved:** the S7 objective + re-score grade on canonical; the shipped is_mine `run()` grades
(`backtest_production_vor._actual_ros`, `backtest_ros_player_band._actual_weekly`, `compute_player_signal`)
still read raw `fantasy_points_ppr` — a fixed-PPR basis (they only see ppr today, so no live number moves),
switching to canonical is a follow-on. **NEXT — Session 8 (band honesty):** re-tune `BULL_Z`/`ANCHOR_W` for
real coverage on the corpus objective — extend the `BULL_Z` grid upward (6b's OOS fit was right-censored at
1.96), sweep `BULL_Z × ANCHOR_W` jointly (6b's were marginal 1-D fits), make the coupled-regression guardrail
real (came back null in 6b), expect `SKEW_GAIN`→0, swap the band's confidence off `ros_cv` onto the
raw-points spread, un-freeze the objective from `GRADE_WEEK=4` to grade across as-of weeks. **The de-bias
proved the WIDTH is the lever, not the centre.** **Session 5b (the HTML Trust Report dashboard) still a named
fast-follow.** — Prior (2026-07-17): **BACKEND — L4 TUNER 6b: the ROS-band objective is now CORPUS-WIDE, so
BULL_Z/ANCHOR_W are testable out-of-sample (still HELD).** Session 6 left the band objective is_mine-scoped
→ no is_mine league pre-2024 → the tuner HELD `BULL_Z`/`ANCHOR_W` on "no OOS train window." 6b rewires
`backtest_ros_player_band.objective` to pool rostered-freeze players across the 221 **matched** leagues
grouped by `scoring_key` (`_corpus_test_points`): per-league `production_vor` freeze roster + the
scoring-scoped canonical answer key (`read_outcomes(…,"player_weekly_pts_canonical")` — nfl_stats PPR
mis-scores half by up to 7 pts/wk) + the SAME shipped `_blended_band`/`_preseason_anchor`/`_ros_sigma` math
(no re-derivation). Graded at **`GRADE_WEEK=4`** — the is_mine roster-freeze analog, an **INTERIM single
parameter** (the across-as-of-weeks objective is Session 8's; comparable to the is_mine 0.817 baseline),
**deduped to one row per (scoring_key, player, season)** (same-key leagues share the band + realized, so
duplicates are pure roster-popularity weight). Now **all 5 dials fit on a full TRAIN 2020–23 window.**
**FINDING:** the corpus band UNDER-covers at the is_mine-fit values — the OOS fit wants **BULL_Z 1.44→1.96**
(DEV 0.367→0.192) and **ANCHOR_W 0.25→1.0** (DEV 0.367→0.193), i.e. a much wider band / full anchor — but
both stay **HELD, entanglement CONFIRMED**: widening/anchoring compensates for the OPTIMISTIC center
(realized falls short of an over-high projection, so the bear tail breaks low); a de-biased center (S7)
needs less of it — the gain tracks the center bias, not real ROS width (re-fit in Session 8, post-de-bias).
**Testability, NOT promotion:** `BULL_Z=1.44`/`ANCHOR_W=0.25` unchanged, RECOMMEND still none, nothing
merged. The is_mine `run()` verdict is untouched (2025 freeze-week coverage **0.817 unchanged** —
equivalence). The split stays STRUCTURAL (the corpus objective's answer-key read raises on a sealed season;
`BULL_Z`/`ANCHOR_W` test-sealed + certify-not-train bite). **Guardrail honesty:** the band's own is_mine
gate has no computed 2024 spine, so `guardrail_coupled` reads **null (unverified)**, not a silent pass.
`corpus/check_tuner.py` **GREEN WITH TEETH** incl. the 6b bite (the corpus objective computes on TRAIN;
the is_mine-only grade still raises). **Session 7 no longer needs to build the corpus band objective — it
exists.** — Prior (same day): **BACKEND — L4 TUNER COMPLETE: the first thing that re-fits a constant —
honestly (Improvement-Loop Session 6, 3 commits).** `transforms/_constants.py` is the **dials registry** —
the ONE home for the 5 swept constants (`BAND_Z`, `SKEW_GAIN`, `BULL_Z`, `ANCHOR_W`, `OPP_HALF_LIFE_WK`) as
`Tunable(name, module, current, grid, gate, objective, scope, coupled_gates, …)`; the 3 owning modules
**re-export** their dial(s) so the canonical dotted path + drift gate + backtests still resolve, and every
re-exported value == its prior in-code literal (equivalence-gated — **NO live number moved**). **Registry
rule (durable, dials-by-purpose): one home per constant — a dial migrates into the registry the FIRST time
it is tuned; a pin never migrates.** Pins (`SEED`/`SIMS`/week-starts) + not-yet-tuned dials (`GAP_VOR`,
`MAGIC_ODDS`, the shrink Ks…) stay in their module; `constants_snapshot.py` is UNCHANGED (still fingerprints
the full 22-constant vector; `constants_hash` unmoved). **The recorded `BULL_Z` drift is RESOLVED by
declaration** — the registry declares the real **1.44** and the module imports it, so a STATUS-vs-code
disagreement is now structurally impossible (not a re-tune). `corpus/tuner.py` is the **one split-aware
sweep harness**: given a `Tunable` it drives the read's FROZEN `objective(season, consts, *, reader)` per
season, **fits on TRAIN 2020–23 (matched cohort), certifies on DEV 2024, seals TEST 2025 + the 48
`never_tune` generalization leagues** — the seal is STRUCTURAL (a `SplitReader` raises `ForbiddenPartition`
on any sealed read, so peeking is *unrepresentable*; proven to bite: test-sealed / generalization-sealed /
certify-not-train). **Two holdouts, one binds this session:** season-wise TRAIN/DEV/TEST is the operative
OOS test for all 5 dials; the **league-wise (generalization) seal is built + prove-bitten but
N/A-by-construction** here (these objectives don't fit a per-league value) and becomes load-bearing from
Session 7. The 3 backtests each gained `objective(...)` reusing their shipped internals; the 3 ad-hoc
`--sweep` flags retired into the one harness (grids now homed in the registry); all 3 default verdicts still
PASS (band freeze-week coverage 0.817 unchanged — the refactor moved no number). **`data_layer.write/
read_tune_proposals`** (immutable-append L4 ledger entity) + a human `proposals/{asof}-{constant}.md`
rendered FROM the machine row (prose can't drift from the gated numbers); `asof_date` pinned to the frozen
scorecard's config_version (never `now()`), provenanced by the frozen inputs' clean stamps (the tuner never
stamps its own dirty HEAD). **Four guardrails** — RECOMMEND only if ALL hold AND un-entangled: (a) the DEV
holdout improves (not train), (b) no coupled/own gate regresses (re-run at the candidate; band dials
decoupled-by-construction from the center reads), (c) `inputs_ok` over the fit window (read from the
persisted ledger), (d) effect > a per-objective floor. **The DISCIPLINED first run (as-of 2026-07-16):
`de-bias-the-center-first` is the rank-1 LEAD; `OPP_HALF_LIFE_WK` + `BAND_Z` are ALREADY the TRAIN+DEV
optimum → HOLD (no change — the harness refuses to churn); `SKEW_GAIN`'s OOS fit moves 1.5→1.0 (toward 0,
the pre-registered overfit) and improves DEV by 0.033 but is HELD — entanglement CONFIRMED (the skew
compensates for the optimistic center, and it also fails the read's OWN calibration verdict at 1.0 on DEV);
`BULL_Z`/`ANCHOR_W` have no OOS train window (is_mine-scoped pre-2024) → HOLD. RECOMMEND: none — nothing
clears the guardrails un-entangled this session (honest: the constants are already well-fit except where
entangled with the center).** `corpus/check_tuner.py` **GREEN WITH TEETH** (registry-is-truth · split-
structural · harness-general · the four guardrails bite — incl. a synthetic clean pass proving the harness
CAN recommend · first-run disciplined · determinism value-identical, + prove-bites for each). **Seam held —
`queries.js`/views/reads/substrate/ledger/scorer untouched; the tuner writes proposals only, edits NO
transform and merges NO constant (auto-tune, human promotes).** **NEXT — Session 7: the de-bias
read-improvement** — add a recent-form shrinkage dial to the projection center (a second anchor toward the
recent form the scorer showed is *beating* the projection), tuned THROUGH this harness on the split, +
delta-tracking for a future seasonal auto-update; re-score to measure the win, THEN Session 8 re-fits the
now-untangled band dials. **Session 5b (the self-contained HTML Trust Report dashboard) is still a named
fast-follow.** — Prior (2026-07-16): **BACKEND — L3 SCORER COMPLETE: the FIRST MEASUREMENT the project has ever
taken (Improvement-Loop Session 5, 3 commits) — `compute_engine_scorecard.py` turns the 2.89M frozen
`resolutions` primitives into per-read VERDICTS, and it is the first thing in the project allowed to JUDGE —
but only DISTRIBUTIONS, never a single claim (Law 1 structural: the grain is a slice, never a
`prediction_id`).** It scores four metric families per `(read × slice)` into `engine_scorecard_{season}`
(3,518 aggregate slice-verdicts over the 6 seasons): **skill** = `1 − metric_engine/metric_naive` vs a
DECLARED naive baseline; **calibration** = PIT-uniformity KS / coverage / Brier; **confidence-honesty (law
2, the headline)** = is realized error monotone in the read's OWN stated confidence; **discrimination** =
Spearman(claim, truth). **It judges but does NOT tune (no constant changed — L4) or promote (no suppression
— L6): measure and report.** **C1 — baseline registry + scorecard core.** New `corpus/scorecard_registry.py`
(versioned, gated declared naive-baseline + confidence-signal registry, `check_registry()` cross-checks the
9 families vs the 4a claim map and bites); `corpus/compute_engine_scorecard.py` reads frozen `resolutions`
(+ re-joins `predictions` for the claim `value`/`confidence` and derives every naive from frozen `outcomes`
— **grounding correction: `resolutions` carries NEITHER `confidence` NOR any naive baseline, contra the
brief**); slices `overall · week · league · position · cohort · scoring_key` (model quality, on `inputs_ok ∧
resolved` ONLY) + `inputs_ok · resolution_status · confidence_tier` (L1 quarantine + reliability, kept
SEPARATE — never blended into a model number); new `data_layer.write/read_engine_scorecard` (append-by-id,
provenance = scorer `code_version` + the ledger's `constants_hash`, so a re-score is a distinguishable
population). **Baseline reality (Will's ruling): only 2 of 6 reads had a baseline to PROMOTE
(`player_signal`→`naive_ppg` [equal-weight recent ppg, NOT the EWMA the brief named], playoff-odds→0.25
coin-flip Brier); the rest are DECLARED canonical (recent-form-forward, pool-mean, closed-form
random-permutation `(n²−1)/(3n)` [no RNG], .500-winrate), tagged promoted-vs-declared; the interval band is
`skill_kind=na` — calibration is its lens, NOT center-MAE (supersedes the brief's band baseline).** cohort
keyed off the AUTHORITATIVE corpus manifest `stratum` (`leagues.parquet` pilot_cohort is an incomplete
projection, missing 34 leagues). **C2 — confidence-honesty (the law-2 headline) + the markdown Trust
Report.** For the 5 confidence-bearing families the raw signal → a monotone `conf_strength` (extremeness
`|x−0.5|` for `spectrum_pos`/`playoff_odds`; `−x` for the inverted `ros_cv`/`regression_risk` — all DECLARED
in the registry, no drift) → `conf_monotonicity = Spearman(conf_strength, realized error)` [≤0 honest] +
per-tier reliability rows; the 4 without carry `measurable_law2=false` (named law-2 gaps, NEVER fabricated).
**Anti-sort prove-bite verified (anti-sorting confidence flips every honest read to dishonest).**
`corpus/trust_report.py` → `TRUST_REPORT.md` (force-tracked): per-read traffic lights + the "what we'd
honestly tell a user" line (front-end copy for later, not wired) + the pre-registered check + the
season/cohort OOS slices. **C3 — `corpus/check_scorecard.py` GREEN WITH TEETH (6 checks + 7 prove-bites all
fire):** coverage (9 overall verdicts · base slices · the 5 confidence-tier triples · quarantine slices) ·
metric ranges · confidence-honesty measured-for-5/flagged-for-4 + the anti-sort bite · baseline-registry
cross-check bites · determinism (recompute with the PERSISTED `code_version`, HEAD-independent,
value-identical) · **Law 1 structural (no `prediction_id`/single-claim column; the base model slices are on
the clean population, `n_claims==n_resolved`; the quarantine slices exist separately).** Deterministic
(twice/thrice-score value-identical; found + fixed a nested-`group_by` float-flake in `conf_top_minus_bottom`
— the `_standings_as_of` lesson, now a single `group_by`). **FINDINGS (surfaced, NOT tuned — the whole point
of report-don't-tune):** (1) **projection optimism is real + stable** — `production_vor` LOSES to
carry-recent-form-forward every season (skill −0.16…−0.39) while ranking well (Spearman ~0.88), and the band
UNDER-covers (~0.55 vs 0.80, PIT KS ~0.47) — two independent reads, one story; (2) **the measurement reads
HOLD out-of-sample** (§1 signal skill ~0, §5 true-rank 0.30–0.39, §6 depth weakly +; playoff Brier 0.11–0.14
< 0.25) — the pre-registered predictions stand; (3) **confidence-honesty is MIXED** — playoff-odds (ρ=−0.89)
+ true-rank + player_signal honest, but the **band's `ros_cv` is INVERTED** (ρ=+0.58 — its narrowest "most
confident" bands miss by the MOST) and positional_depth's `spectrum_pos` doesn't sort; 4 reads state no
confidence at all (law-2 unmeasurable). **The Tuner (L4) acts on these; the scorer only flags.** **Seam held
— `queries.js`/views/reads/substrate/ledger untouched; the scorecard is a new derived entity the front end
doesn't read.** **NEXT — Session 6: the Tuner (L4)** — the constant registry (`transforms/_constants.py`,
promote the 4a snapshot), the `--sweep` harness generalized, and the split discipline (TRAIN 2020–23 · DEV
2024 · TEST 2025, season-wise + league-wise holdout of the generalization cohort); auto-tune, human
promotes. **Session 5b (the self-contained HTML Trust Report dashboard) is a named fast-follow** — the
markdown Trust Report was the must-have (Will's ruling: HTML is its own session; there is NO existing
standalone-HTML generator in the repo to reuse, only the frontend DuckDB-WASM loader pattern). — Prior: **BACKEND — L2 LEDGER COMPLETE: `outcomes` + `resolutions` join the claims to
realized truth and attach the grading PRIMITIVES (Improvement-Loop Session 4b, 3 commits) — the ledger now
runs end-to-end `predictions ⋈ outcomes → resolutions`, grading nothing.** 4a laid the engine's claims flat
as immutable `served=false` rows; they were ungraded. 4b builds the other half from the FROZEN
`join_season`/`matchups`/`league_settings` — realized facts + the `error`/`in_band`/`pit`/`brier`/
`rank_error`/`direction_hit` primitives the scorer (Session 5) will judge. **Law 1 stays structural across
the entity boundary: a per-row `pit=0.97` is a PRIMITIVE, not a verdict — `resolutions` emits no aggregate
score, per-read pass/fail, `claim_correct`, or `suppress`; the scorer is the first thing that judges, and
only over DISTRIBUTIONS.** **C1 — `outcomes_{season}` (962,196 rows, append-only by `outcome_id`).** New
`data_layer.write_outcomes`/`read_outcomes` (immutable append-only-of-new, `league_id` nullable by scope,
the 4a precedent); `corpus/backfill_outcomes.py` derives realized truth across the 270 league-seasons.
Roster facts (`roster_wins`/`roster_total_pts`/`roster_final_standing`/`roster_made_playoffs` +
`roster_position_pts`) REUSE `compute_bracket_sim`'s division-aware seeding at `reg_end`
(`_playoff_config`/`_standings_as_of`/`_division_map`/`_seed_table`) — never a naive sort; **gate teeth:
realized playoff mass == slot count on all 270 incl. the 25 division leagues.** **SCOPING FINDING (a
correction to the brief's grounding — REPORTED not papered over, std instr 1/6):** the brief assumed
same-`scoring_key` leagues give a player identical weekly points; FALSE for ~9.5% of player-weeks (spreads
to ~21 pts) — `scoring_key` classifies only the RECEPTION tier, so two "ppr" leagues that differ on the INT
penalty / yardage & reception bonuses / first-down points genuinely score a player-week differently, and
`sleeper_points` faithfully reflects each league's FULL scoring. So realized points are a LEAGUE property:
`player_weekly_pts` is **league-scoped** (each point claim grades against ITS league's exact truth), while
`player_weekly_pts_canonical` is **scoring-scoped** (`_scoring.actual_points_expr`, league-independent by
construction — 0 disagreement — matching the basis the scoring-scoped `ros_player_band` was projected
under). **C2 — `compute_resolutions.py` → `resolutions_{season}` (2,893,834 rows = exactly the claim
population; 1:1 on `prediction_id`, asserted).** Horizon-correct per family (ros → Σ pts weeks ≥ as_of;
weekly → weeks > as_of; season → the season-end roster facts). PIT the unifier ONLY where a distribution is
stated: interval via `Φ((truth−center)/sigma)`, probability via the DETERMINISTIC randomized PIT of a
Bernoulli seeded by `prediction_id` (Uniform under calibration, verified ~flat — so the scorer's ONE
PIT-uniformity test is valid for playoff odds too); point/ordinal/direction get their native primitive and
`pit=null` (no fabricated sigma). `rank_error` is integer for `true_rank`, legitimately FRACTIONAL for
`avg_seed` (a Monte-Carlo average seed). **Unresolved claims are NAMED + counted, never dropped, never a
fake zero** (production_vor 9.6% / player_signal 19% / band 45% — band-pool players not rostered in any
league of the scoring_key past as_of). **First-look findings SURFACED, graded nothing, changed no constant:**
production_vor +28.6 median error and band PIT piled at 0 (projection optimism / injuries / roster churn);
positional_depth −62 (the ★ approximate answer key: `surplus_value` vs total roster×position pts, graded on
the clean subset with a coverage flag); direction ~chance hit-rate (non-degenerate classification). Each
resolution carries its claim's provenance (`code_version`/`constants_hash`/`inputs_ok`/`served`).
**C3 — `corpus/check_resolutions.py` GREEN with teeth:** coverage (1:1, resolved⇒answer, unresolved⇒reason)
· primitive validity (pit/brier∈[0,1], in_band∈{0,1}, pit non-null IFF interval/probability) · **Law 1 — no
verdict column** · traceability + determinism (recompute value-identical, `_frame_eq`) · **realized
integrity rides through** (Σ made-playoffs truth == playoff_teams per (league, as_of_week) in the GRADED
rows, std instr 7) — all 5 prove-bites fire. Deterministic (twice-derive/twice-compute value-identical),
idempotent (re-run appends 0). **Seam held — `queries.js`/views untouched; predictions + reads + substrate
value-identical (untouched).** **NEXT — Session 5: the Scorer (L3)** (`compute_engine_scorecard.py` over
`resolutions`: skill vs each read's declared baseline · calibration = PIT-uniformity KS / coverage / Brier
reliability · confidence-honesty = is error monotone in the read's stated `confidence`, the headline law-2
metric · discrimination = Spearman; sliced by league/position/week/confidence-tier/`inputs_ok`/cohort → the
Trust Report) — SCOPED, NOT STARTED; it is the FIRST thing that judges. — Prior: **BACKEND — L2 LEDGER, PART 1: the `predictions` entity built + backfilled
`served=false` across the 270 spined league-seasons (Improvement-Loop Session 4a, 3 commits): every frozen
read reshaped into an immutable, provenance-stamped CLAIM row — the ledger's first entity.** The 5-read
spine + scoring-scoped band were computed, but the engine's *claims* were trapped inside per-read parquets
with no record of what each read predicted or how confident it was. L2 turns each read into an explicit,
immutable claim. The schema defined here is the exact one the live 2026 path reuses (`served=true` + an L1
flag on the same columns). **C1 — schema + provenance scaffolding.** New immutable append-only
`predictions_{season}` under `derived/ledger/` (`data_layer.write_predictions`/`read_predictions` —
diagonal-concat append-only-of-new by `prediction_id`, never overwrite; the `team_news_raw` precedent); a
pinned **constants snapshot** (`corpus/constants_snapshot.py`) of the full 22-constant vector the 6 reads +
consensus consume, hashed per row (`constants_hash=a3d01b8e5f4d5131`) with a cross-check gate that reddens
on drift; a **versioned `inputs_ok`** derivation (`corpus/inputs_ok.py`, `INPUTS_OK_THRESHOLDS`
v2026-07-16) from four frozen integrity signals (manifest `filter_result`/`id_resolution_pct`, the
degenerate flag, the `join_season` remainder rate), thresholds set STRICTER than selection (id≥98 vs the
90 selection floor; remainder≤0.08 vs the 0.15 harvest bound) so **4 marginal league-seasons genuinely
resolve `inputs_ok=false`** — real offline coverage of the `false` path, not the blanket-true trap. **C2 —
the read→claim mapping** (`corpus/predictions_map.py` + driver `corpus/backfill_predictions.py`): **9 claim
families** across 6 reads (production_vor→point · band→interval · player_signal→point+direction ·
true_rank→ordinal · positional_depth→point · bracket_odds→playoff/wins/seed), with **typed sidecars** over
the flat §L2 schema (`value` XOR `value_str` by claim_type; `lo`/`hi`/`sigma` present iff interval —
`sigma`=band `ros_sigma` so 4b's `pit=Φ((truth−center)/sigma)` reads a typed scale and never backs it out
of BULL_Z; a canonical Float64 `confidence` + `confidence_label` naming the signal, `confidence_json`
audit-only, never the scorer's primary read). Backfilled **2,893,834 claims** over the 270 (221 matched +
48 generalization + is_mine 2025), `served=false`, `prompt_version`/`model`/`created_at`=null; the band
emitted **ONCE per (scoring_key, season)** with `league_id=null` (20 populations, not re-emitted per league
— 4b join-safety). Budget: 25.1s, per-season files 3.3–13.0 MB (~50 MB total), incremental re-run ≈0. **C3
— `check_predictions` gate, GREEN with teeth (26 checks, all prove-bites fire):** coverage (every league +
band-once-per-scoring-key + sample family counts == source non-null) · schema + typing-XOR + **Law 1
structural** (no grade/verdict/resolution column exists) · immutability (same-`code_version` re-run 0 new;
new-`code_version` writes a parallel population, both retained) · provenance bites (drift reddens on a
changed constant; `inputs_ok` false path exercised) · determinism (rebuild==persisted value-identical incl.
a stable `prediction_id`, rebuilt with the PERSISTED `code_version` so it's HEAD-independent) · confidence
honesty. **Findings (report, don't tune / don't grade):** (1) **BULL_Z drift** — STATUS narration recorded
`1.645`, the live code is **`1.44`**; the snapshot pins the ACTUAL 1.44 and the gate documents the
discrepancy — NOT fixed here (changing a constant is the Tuner's job). **[RESOLVED in Session 6: the dials
registry declares 1.44 and the module imports it — the drift class is now structurally impossible.]** (2) **`prediction_id` key extended**
— added `season` + `claim_type` to the §L2 key `(scope, read, subject_id, as_of_week, horizon,
code_version)`: `claim_type` because a read emits ≥3 families per subject-week (bracket_odds), `season`
because the scoring-scoped band recurs yearly — without them ids collide (caught by the gate's uniqueness
check, fixed). (3) **No-native-confidence flag list** — `production_vor`, `bracket_odds` wins/seed, **and**
`player_signal` direction carry null confidence (Law-2 confidence-honesty is unmeasurable for these until a
signal is defined) — FLAGGED, not fabricated. **Value-identity proven** — every claim value is byte-equal
to its source read across all 9 families (a reshape that moved a number would be a bug). **Seam held —
`queries.js`/views/reads/substrate untouched** (`data_layer` additive-only, +52 lines; the ledger is
internal loop plumbing, no view consumes it, nothing observable in the app). **4a-fix (`code_version`
provenance correction, +1 commit):** the initial backfill ran on a **dirty tree**, so
`backfill_predictions._git_sha()` captured the pre-4a **BASE** sha (`087e740`, which does NOT contain the
producing `backfill_predictions.py`) into all 2.89M rows' `code_version` — and hence into `prediction_id`.
Corrected before 4b joins on those ids: `_git_sha()` now **refuses a dirty tree** (raises), and the
`served=false` store was cleared + **re-stamped from the committed tip** so every row's `code_version`
names the real producing commit. **Proven that ONLY `code_version` + `prediction_id` moved** (row count
2,893,834 unchanged; schema identical; the 4 `inputs_ok=false` league-seasons unchanged; band-once; every
other column value-identical — a `_frame_eq` over the store minus those two columns). `check_predictions`
now asserts `served=false` is a single `code_version` whose tree carries `backfill_predictions.py`, and
that the dirty-tree guard bites. No `queries.js`/view/constant/read/substrate change; no cascade (4b not
started — nothing references the old ids). **Next — Session 4b:
`outcomes_{season}` + `compute_resolutions.py` (the `predictions ⋈ outcomes` join + grading primitives
`error`/`abs_error`/`in_band`/`pit`/`brier`/`rank_error`) from the frozen `join_season` + `league_settings`;
PIT the unifying primitive; still NO single-claim verdicts (the scorer, Session 5, is the first judge) —
SCOPED, NOT STARTED.**) — Prior: **BACKEND — MATCHED DIVISION SEEDING ACTIVATED (Improvement-Loop Session 3e, 2
commits): the 11 matched division leagues now seed division-aware — the last 3d latent closed, bounded to
their `bracket_odds`.** 3d activated division seeding on the 14 generalization division leagues but
deliberately LEFT the 11 matched division leagues flat-seeded to protect its byte-identity proof of the frozen
tuning spine. This closes that named latent — and **changes numbers BY DESIGN** (the 1.7 discipline: bounded +
proven, not "nothing moved"). **C1 — activate.** `backfill_division` gained `--stratum
{generalization,matched,mine}` (default generalization — 3d byte-preserved), mirroring
`backfill_expected_points`; `--stratum matched` targets exactly the 11 (`matched ∧ has_divisions`). Sleeper
still serves all 11 (2–3 divisions each; 11/11 added, 0 flagged no-divisions); `sleeper.backfill_division`
additively left-joined `division` onto the existing teams (names byte-identical) → recomputed **only
`bracket_odds`** (the other 4 reads are division-independent). mass==slots holds on every real matched division
bracket. **C2 — gate + docs. Bounded + proven:** (a) baseline SHA diff over 1110 files (223 leagues × 5 reads)
— **EXACTLY 11 changed, all `bracket_odds`, all matched, all the target 11**; the other 210 matched
bracket_odds + all `production_vor`/`true_rank`/`positional_depth`/`player_signal` + all is_mine
**BYTE-IDENTICAL**; (b) **no input drift** — a flat recompute (division forced None) reproduces the persisted
3b `bracket_odds` value-identical → division seeding is the SOLE delta; (c) division-aware odds moved 9–11
rosters/league (maxΔ 0.005–0.012), deterministic (recompute==persisted, twice-run identical, league-stable
seed). `check_spine` green both strata (the 11 now pass mass==slots + probs∈[0,1] with real division maps);
siblings unregressed (`check_harvest`, `check_expected_points`, matched-only gate). Retired the
"synthetic-gated only / no real division answer key" caveat in `_division_map` + `backtest_bracket_sim` +
`TECHNICAL_ARCHITECTURE` — division seeding is now validated on **all 25 real corpus division leagues** (14
gen + 11 matched). **Seam held — `queries.js`/views untouched. Next: the L2 ledger.**) — Prior: **BACKEND —
GENERALIZATION ROBUSTNESS PASS (Improvement-Loop Session 3d, 4
commits): the 48 `never_tune` generalization leagues computed through the 5-read measurement spine, and the
any-league shape paths certified on real superflex / division / custom shapes.** 3a/3b/3c built + lit the
matched 221 spine; the 48 generalization leagues (**21 superflex · 14 division · 8 custom `cust-` keys · sizes
4–18**) still had NO spine (`production_vor` 0/48) — the shapes the any-league code had only ever seen
synthetically. **C1 — §1 Quality + catalog.** Extended `backfill_expected_points` with `--stratum` (default
matched preserved byte-for-byte) and appended the 14 `*_exp` onto the 40 gen 2020–24 joins (gen 2025 already
carries them; every pre-existing column byte-identical) → §1 Quality lit for free; ran `compute_spine --strata
generalization` → **48/48 computed, 0 crashes, 0 flagged**. A clean run ≠ a clean bill (std instr 1) —
interrogated the OUTPUTS by mechanism. **Failure inventory (silent gaps, not stack traces):** (1) **DIVISION
SEEDING** — 14/14 division leagues silently FLAT-seeded (`_division_map=None`; 3a's `teams` fetcher dropped
`settings.division`) → C2; (2) **WEEK-1-ONLY JOIN** — `1004091381628588032` 2023 (garbled
`playoff_week_start=0` → reg_end=−1 at harvest → week-1-only join; the SAME class the cleanup fixed for the
matched degenerate league — STATUS predicted "one 2023 generalization league inherits the fix for free at 3d",
this is it) — **fixed here** by re-joining weeks 1–14 from **persisted raw** (`harvest._build_join`, no
network) + is_two_way + `*_exp` + recompute (join 1→14 weeks, pv 156→2724 rows); (3) **SUPERFLEX POOLS — no
bug** (15 real-`SUPER_FLEX` leagues merge QB into the SF pool; 6 multi-dedicated-QB (2QB/3QB) leagues keep QB
its own pool — `position_pools` keys off actual slot eligibility, not the coarse manifest label); (4) **LINEUP
SLOT CODES — no bug** (every code recognized, 0 silently dropped); (5) **CUSTOM SCORING — no bug** (all 8
`cust-` keys score non-degenerate; the selection-time `scoreable` gate holds). **C2 — division re-harvest (the
ONE sanctioned fetch of 3d — a static historical fact).** `fetch_teams` now persists `division` (forward fix;
retires the "follow-up when a real division league lands" caveat), and `backfill_division` additively
left-joins the freshly-fetched roster→division map onto the EXISTING teams parquet (name columns
byte-identical) for the 14 gen division leagues (2–4 divisions each) → division-aware seeding activated with
**no `_seed_table` edit** (the branch already existed, fed only by the data). **SCOPED TO GENERALIZATION:** the
**11 matched division leagues stay flat** — activating them would move the frozen tuning spine (report,
don't tune, std instr 2); `_division_map` returns None for their untouched teams. Proven: **mass == slot-count
on every real division bracket**; `_seed_table` lifts a losing-record division winner past a higher-record
wildcard (unit-proven + materially moves the 4-division league — 12/12 rosters, max Δ 0.144); division
recompute deterministic (recompute==persisted, twice-run identical, league-stable seed). **C3 — gate + prove
matched untouched.** `check_spine` extended with `--strata` (default matched+generalization): checks 1–5 over
both strata + **NEW check 6 `never_tune` intact** (every gen row never_tune, none leaked into the tunable set;
prove-bite fires); determinism sample spans both strata incl. a division league. **Green over 269 leagues,
exit 0**, all prove-bites fire; backward compatible (`--strata matched` reproduces the 3b/3c matched gate);
siblings unregressed (`check_harvest` 271 — incl. the re-joined league + division-column teams, twice-join
value-identical; `check_expected_points`). **Matched untouched (acceptance gate 3): all 666 matched + is_mine
spine files (`production_vor`/`bracket_odds`/`player_signal`) BYTE-IDENTICAL to the pre-3d baseline (0/666
changed)** — the shared-code + division-data changes moved nothing in the frozen tuning spine; the ONLY new
numbers are the 48-league generalization spine. **Seam held — `queries.js`/views untouched.** **The corpus
measurement spine is now COMPLETE across both strata (269 leagues: 221 matched + 48 generalization) — next:
scope the L2 ledger.**) — Prior: **BACKEND — CORPUS CLEANUP (3 commits): determinism gates de-flaked, dead
`xtd` retired, the degenerate league completed → matched spine 221/221.** Three loose ends from the
3a/3b/3c work, each touching shared/frozen ground with its own equivalence proof (no `queries.js`/view
edits). **C1 — de-flaked the determinism gates.** `check_spine` + `check_harvest` asserted determinism by
`sha256(read_bytes())` of the recomputed parquet, which flaked ~8%. Mechanism NAMED (not tied rows — the 3c
mislabel is corrected here): recomputing a read gives an **order-sensitive-identical in-memory frame every
time**; only polars' **parquet WRITER is physically non-deterministic** (compression/dictionary/metadata
bytes flake for a byte-identical frame). Converted both determinism sub-checks to order-insensitive
value-equality (`_frame_eq` = sort-by-all-cols + frame-eq — the 1.7 precedent `check_expected_points`
already used); corrected the mislabeled comments there too; added prove-bites (fails on differing values,
passes on a row permutation). Both gates **10/10 green, zero flake.** **C2 — retired the dead `xtd` column.**
The retired TD-proxy survived only on 2020-24 `nfl_stats` (5 files, 167→166 cols) + **202 join_seasons** (all
2020-24); 2025 lacked it. New idempotent driver `corpus/retire_xtd.py` drops it via the data_layer seam — an
additive-INVERSE that moves no live number (standing instr 5): every other column byte-identical + rows
unchanged (asserted per file), the 5 spine reads recompute **value-identical** (xtd unconsumed — its only
reference is a comment), the **six-season schema now uniform (166 cols).** **C3 — completed the degenerate
league → 221/221.** `1124876463083261952` (2024) got a week-1-only *join* (not raw — `sleeper.backfill`
pulls all completed weeks, so its raw weeks 1-15 were already fully persisted) because a garbled
`playoff_week_start=0` yielded reg_end=−1. Added a **reg_end sanity floor** (`playoff_week_start < 2` →
`_DEFAULT_PLAYOFF_WEEK_START=15`) as a **shared helper** `compute_bracket_sim._sane_playoff_week_start` that
both `_playoff_config` (the sim) and `harvest._reg_end` (the harvest) use — a single source so they can't
drift; a proven **no-op for all 220 valid matched leagues** (only 2 corpus leagues have garbled config: this
one + one 2023 generalization league that inherits the fix for free at 3d). Re-joined the league weeks 1-14
from **persisted raw (no network)** + computed its 5-read spine → **`check_spine` 221 present, 0
flagged-degenerate.** Completing it exposed a SECOND pre-existing bracket_sim non-determinism (named, standing
instr 6): **`_standings_as_of` accumulated cumulative points by iterating polars `group_by` in
non-deterministic order**, and float addition is non-associative, so a roster whose total lands on a `round1`
boundary flipped `current_points` ±0.1 run-to-run (the graded outputs — playoff_odds/seed/wins — stayed
stable; only that one reported column moved). Fixed by iterating the groups sorted; **PROVEN
equivalence-preserving — recompute == persisted for all 220 matched + is_mine 2025 (graded AND
current_points, 0 mismatches), only the new league made reproducible** (its 5-read spine now twice-run
value-identical). All three gates green (`check_spine`/`check_harvest`/`check_expected_points`); seam held
(no `queries.js`/view edits; is_mine unaffected). **Next — Session 3d: the generalization robustness pass;
the floor + `*_exp` fix are inherited for free.**) — Prior: **BACKEND — EXPECTED-POINTS SUBSTRATE BACKFILL: §1 `player_signal` Quality lit
across the whole matched corpus (Improvement-Loop Session 3c).** 3b surfaced that the §1 Quality axis
(`quality_rate` / `luck` / `point_correlation`) was TEST-only — 100% null for 2020–24, populated only for
2025 — because the pre-2025 `nfl_stats` parquets were built *before* `_load_ff_opportunity` was added to the
fetcher, so they carried **0/14** `*_exp` components (2025 has all 14). A stale-substrate gap (the class
Session 2 fixed for `projections`), NOT a 3b bug; 3b correctly held the axis null (law 2). Fix is **additive
+ data-only** — a wholesale re-pull would risk 1.7-style drift (a moving source) that would move the FROZEN
corpus and invalidate the 3b spine, so the 14 `*_exp` are **appended** onto the frozen substrate and
`player_signal` re-run, everything else proven byte-identical. **C1 — `nfl_stats.py` gains `precheck_exp`
(schema-honesty pre-check: confirm ff_opportunity SERVES all 14 `EXP_COMPONENT_COLS`, populated, for 2020–24
before ANY write — 14/14, 0.0000 worst null-rate, PASS) + `backfill_exp(year)` (left-join
`_load_ff_opportunity` on (player_id/gsis_id, week) + `fill_null(0.0)`, preserving existing row order — a
byte-identical additive backfill, not a rebuild; asserts every pre-existing column byte-identical + row
count unchanged; idempotent) + `backfill_exp_all` (pre-check THEN backfill).** Result: 2020–24 `nfl_stats`
153→167 cols, rows unchanged, receptions_exp nonzero ~24% (matches 2025's 23.3%); **independent before/after
proof — pre-existing columns byte-identical for 2020–24, 2025 fully byte-identical (untouched); twice-run
byte-identical.** **C2 — new driver `corpus/backfill_expected_points.py`:** (1) append `*_exp` onto each
matched 2020–24 `join_season` (keyed on **gsis/(player_id, week)** — faithful AND safe: each row already
carries the gsis of the nfl row that supplied its stats, (gsis, week) is unique ⇒ no cartesian expansion;
mirrors `harvest._apply_two_way` — additive, idempotent, rewrite-only-when-changed; does NOT re-run the join
logic, avoiding the 1.7 pinned-registry path); (2) re-run `player_signal` for the **160 non-degenerate**
matched 2020–24 leagues (the degenerate `1124876463083261952` 2024 has no spine — stays flagged). Run: 161
targets, joins added 158/unchanged 3, player_signal recomputed 160, flagged 1, **0 errors, 35.8s.** Verified
over all 161 vs a captured 3b baseline: **join pre-existing columns byte-identical + `*_exp` added;
`player_signal` CORE columns byte-identical; §1 Quality LIT — `quality_rate` null-rate 1.000→0.000; twice-run
byte-identical; blast radius contained — `production_vor`/`true_rank`/`positional_depth`/`bracket_odds` files
byte-identical to 3b (SHA unchanged).** Cross-season consistent (`quality_rate`/`luck` 0% null,
`point_correlation` structurally null ~0.2–0.29, same dtypes as 2025). **`compute_player_signal.py` is
UNCHANGED — it is already `has_exp`-aware (`all(c in join.columns for c in EXP_COMPONENT_COLS)`), so the
columns landing in the join light up Quality with no read-code edit.** **C3 — sibling gate
`corpus/check_expected_points.py`, GREEN with teeth:** (1) `*_exp` present + populated 2020–2025 (no
null/missing season), (2) matched joins carry `*_exp` (the consumer sees it — std instr 7), (3)
`player_signal` recompute byte-identical + §1 Quality lit, (4) blast radius — the 4 reads recompute
value-identical to 3b (they read neither `*_exp` nor `player_signal`); **all 4 prove-bites fire** (stripped
`*_exp` fails check 1; all-null Quality fails check 3; the value predicate bites, order-insensitively).
**Checks 3+4 compare recompute-vs-persisted ORDER-INSENSITIVELY** (`_frame_eq` = sort + frame-eq) — surfaced
a **pre-existing 3b flake** [MECHANISM CORRECTED in Corpus-cleanup C1: NOT tied rows — the recompute is an
order-sensitive-identical in-memory frame every time; the polars **parquet WRITER** is physically
non-deterministic, so only the on-disk bytes flake ~8%], so a byte-level recompute check flakes. NOT a 3c
regression (player_signal re-run is 0/12 flaky; the 4 reads were untouched); the project's sanctioned fix is a unique
sort tie-break + re-persist, deferred (touching the frozen spine is out of 3c scope) — **`check_spine`'s own
byte-based determinism check is correspondingly flaky (a 3b gate, ~8%/sampled-league); re-run to confirm
green.** `check_spine` (value-wise) **intact** (220 present + 1 flagged); the **2025 answer-key `backtest_player_signal` PASS** (Quality axis
`quality_rate`/exp_ppo beats realized efficiency, MAE 0.311 vs 0.506 — 2025 unchanged). **Seam held —
`queries.js` / frontend untouched (0 diff); is_mine 2025 (what the app renders) byte-identical/untouched.**
**Key facts:** `EXP_COMPONENT_COLS` = **14** (the brief's "12" is stale — used the authoritative constant);
`has_exp` keys off the **join** columns, and only matched-stratum joins were appended, so the **is_mine +
generalization leagues stay UNCHANGED even on recompute** (their joins still lack `*_exp`) — the clean 3d
handoff (`nfl_stats` already carries the components; 3d/the app additively backfill their joins the same
way). The stale, provably-unconsumed `xtd` column (2020–24 only, the retired TD-proxy) was **left untouched**
per the additive discipline (it never leaks into `player_signal` — derived reads select by name). **Next —
Session 3d: the generalization robustness pass (the 48 `never_tune` leagues through the 5-read spine —
superflex `position_pools`, division `_seed_table`/`_division_map`, custom `_scoring.recompute_custom_points`;
budget it for bugs; inherits the `*_exp` fix for free) — SCOPED, NOT STARTED; then the L2 ledger. Queued
(not this session) [ALL THREE DONE in Corpus-cleanup above]: the degenerate `1124876463083261952`
(reg_end floor + re-join → 221/221); the stale `xtd` cleanup (retired); the determinism-gate flake
(de-flaked — was the parquet writer, not tied rows). Remaining: optionally lighting is_mine historical
Quality.**) — Prior: **BACKEND — MATCHED MEASUREMENT SPINE COMPUTED (Improvement-Loop Session 3b):
the 5 graded reads threaded league-keyed and computed for the 221-league matched tuning corpus.** 3a
league-keyed the raw+join layer; the compute side was still unkeyed (every `compute_*.compute(season)`
implicitly resolved is_mine). **C1 — keys threaded:** an explicit keyword-only `league_id` (+ `scoring_key`
where a scoring-scoped read is consumed), defaulting to the active league, on `compute()`/`run()` for the
**5 measurement reads** — `production_vor` (scoring_key→consensus, league_id→join/slots/write),
`true_rank`/`positional_depth` (league_id→vor/slots/write), `bracket_sim` (scoring_key→consensus,
league_id→roster/matchups/slots/playoff-config/division-map/write), `player_signal` (league_id→join/scoring)
— and through their 5 backtest gates. **`ros_league_view` + `manager_features` are DESCOPED from the
corpus** (narrative/behavioral reads with no answer key — only the AI writers consume them, per the revised
brief's product call), so the `manager_activity` cross-league fetch is not needed; both stay
live/is_mine-only/untouched. is_mine 2025 **byte-identical** (threading moves no number); 5 backtests green.
**C2 — computed (`corpus/compute_spine.py`, mirrors harvest.py):** matched stratum (221), resolve
`(league_id, season, scoring_key)` from the manifest, compute the 5 in dependency order
(`production_vor → {true_rank·positional_depth·bracket_odds}`; `player_signal` independent),
idempotent/resumable (skip a league whose 5 reads are on disk), per-league isolation, budget report. Three
value-preserving hardenings: (1) **league-stable `bracket_sim` seed** — base `SEED` for is_mine
(byte-identical odds), a `blake2b(league_id)` hash for each corpus league (same league reproducible on
re-run, different leagues independent MC draws — one global SEED shared one stream across all 221, which the
ledger's calibration can't average away); (2) **unique tie-break** on the new sorts (production_vor /
player_signal +`sleeper_player_id`, true_rank / bracket_odds +`roster_id`; positional_depth already unique)
— the 1.7 parallelism lesson, now byte-stable; (3) **`is_two_way` rides `production_vor`** from 3a's join
(is_mine count=4). **220/221 computed** (5 reads each, league-keyed); **1 FLAGGED not dropped**
(`1124876463083261952` 2024: `playoff_week_start` unset=0 ⇒ `reg_season_end=-1`, only week-1 harvested — no
season to simulate; a clean zero NAMED, standing instruction 1 — the degenerate raw is a 3a-harvest latent
for a re-harvest follow-up). **ff_opportunity substrate is 2025-only** (`EXP_COMPONENT_COLS` absent
pre-2025), so `player_signal`'s §1 Quality axis (`quality_rate` / `luck` / `point_correlation`) is held
**null** for 2020–24 (law 2 — null when the substrate can't support the read), Float64-typed; the graded
core read (regression_risk / expected_ppg / the categorical read) is unaffected. **Budget:** `bracket_odds`
50.1s + `player_signal` 43.3s dominate, **104.5s total for 220**, incremental re-run ≈0. **C3 —
`corpus/check_spine.py` gate, GREEN with teeth over all 221:** spine present (220 + 1 flagged-degenerate) ·
cohort consistent (every team at every as-of week; bracket_odds a contiguous prefix — it legitimately can't
simulate from the final week, no remaining games) · playoff_odds∈[0,1] · **spent playoff mass == slot
count** every as-of week · production_vor ⊆ join skill players (no invented mass, 99.0% coverage) ·
**determinism recompute byte-identical incl. the league-stable seed** · `is_two_way` present+boolean (66
two-way rows across the corpus). Prove-bites all fire (missing read detected; mass≠slots rejected; seed a
pure fn of league_id). **No constant changed (report-don't-tune); substrate/manifest frozen;
`queries.js`/views + the narrative reads untouched — the seam held. Next — Session 3c (the 48 `never_tune`
generalization leagues through the same spine — superflex `position_pools`, division
`_seed_table`/`_division_map`, custom `_scoring.recompute_custom_points`; budget it for bugs) — SCOPED, NOT
STARTED; then the L2 ledger.**) — Prior: **BACKEND — L0 RAW-LAYER KEYING + CORPUS RAW HARVEST shipped (Improvement-Loop
Session 3a): the deferred half of L0 closed, and the first real data pulled through the collision isolation.**
Session 1 keyed the *derived* league layer but deferred the *raw* fetched + join layer — which was still
season-keyed only, so a second league pulled into a season would **overwrite the first** (audit S1.3). **C1 —
raw/join re-keyed by `league_id`:** a default-resolves-active `league_id=None` kwarg (mirroring the derived
idiom exactly) on every path/read/write for `sleeper_matchups`/`sleeper_transactions`/`teams`/
`roster_positions`/`lineup_slots`/`league_settings`/`join_season`(+`remainders`) → `sleeper/<season>/league/
<league_id>/…` · `nfl_sleeper_weekly_joined/league/<league_id>/…`; threaded through the sleeper fetchers +
`join_nfl_sleeper_weekly.run` + `derive_lineup_slots`; `league_registry` now passes the config league_id
**explicitly** to its raw reads (the default resolution reads the very `leagues.parquet` it builds — an
explicit key breaks that bootstrap cycle). The is_mine 2025 league (`1182…`) **migrated byte-preserving**
(SHA `9457b16e`, verify-then-remove) with the 4 `public/data` raw symlinks (teams/lineup_slots/
league_settings/season) repointed; `backtest_l0_keying` gains a **B2 raw-collision check + prove-bites**.
**C2 — the harvest driver (`corpus/harvest.py`):** reads the FROZEN manifest, filters `matched ∪
generalization ∪ mine = 271` (excludes the 41 `excluded`), and per league-season pulls the raw layer through
the throttled `_http` (idempotent/incremental — `join_season` is the terminal resumability artifact; **per-
league failure isolation** so one transient Sleeper timeout flags-and-continues instead of aborting 271
pulls) and builds a per-league `join_season` vs `nfl_stats` + the **pinned registry** (1.7). **Full harvest:
271/271 joined · 8,938 Sleeper calls · ~48 min · 41 calls/league · ≈0 incremental re-run · 0 drifted · 0
errored.** (`join` got per-process caches for the week-invariant reads — nfl_stats/registry/id-map — cutting
per-league join cost ~an order of magnitude; `backfill` gained a `pace` override.) Roster mass **65,049
resolved + 997 named remainders (1.51% aggregate loss, bounded)**; twice-join byte-identical. **Two-way flag:**
`corpus_two_way_flags` (10-row reference) rides each join as a first-class `is_two_way` boolean — **FLAG, not
exclude** (the scorer slices later). A **clean-zero bug was caught (standing instruction 1):** `group_by(
"season")` yields a TUPLE key, so the flag map missed the int-season lookup and `is_two_way` came out
all-False (exposure 0 despite Hunter being rostered); fixed (row-wise int keys + recompute-on-change), giving
the true **exposure = 5** (Travis Hunter `12530` is on the is_mine roster too; one flagged player rostered per
season 2021–2025). **C3 — `corpus/check_harvest.py` gate, GREEN over all 271** (raw present · join computes ·
roster-mass bounded · determinism byte-identical · two-way present+correct on every join), **prove-bites both
fire** (a truncated league fails completeness; a roster-mass-losing join fails the bound). **Historical-
accuracy footnote (1.7 residual — report, don't fix):** the pinned registry is current-state, so a 2020–24
league's skill-eligibility label is *today's*; the material exposure is exactly the bounded two-way set (5
rostered), reported. **No constant changed; substrate/manifest/flags frozen (untouched); `queries.js`/views
untouched — the seam held; front end renders** (is_mine resolves post-migration, `is_two_way` column added,
zero console errors). **Next — Session 3b: the league-scoped read spine (`production_vor` → {`true_rank`,
`positional_depth`, `bracket_odds`}, `player_signal`, `ros_league_view`, `manager_features`) with explicit
`league_id`/`scoring_key` threaded through the `compute_*` functions, matched-first then generalization, + the
10k-Monte-Carlo `bracket_sim` per league per as-of week (budget it) → then the L2 ledger.** — Prior: **BACKEND — SESSION 2.5 PRODUCER CODE COMMITTED + MERGED (re-run): the
corpus-finalization producers now live on main at `51940eb`.** The 2026-07-14 run shipped the artifacts (frozen
in the store) but committed the code only on an unmerged branch, so main had no producers — this re-run
**adopted that branch's 3 commits** (`26bf6d7` C1 season-aware + key-capped generalization re-select & gate
teeth · `5827e37` C2 8-key generalization substrate · `148d705` C3 `corpus_two_way_flags`) and **regenerated all
three artifacts from the committed code to prove reproducibility:** manifest identical to the frozen store modulo
`selected_at` (tie-breaks recovered exactly · twice-run deterministic · zero Sleeper calls); generalization band
substrate **byte-identical** + consensus **value-identical** (only on-disk row order differs — a Session-2
non-unique `(week,center_ppr)` sort, within-env deterministic, left as-is per report-don't-tune); two-way flags
identical (10 rows). Bundle internally consistent (manifest ⋈ substrate keys ⋈ flags); `check_corpus` PASS with
the season-spread + key-cap teeth proven to bite. **Docs otherwise kept at main's state** (the prior branch's
STATUS/LEAGUE_CORPUS/READ_BUILD_ORDER rewrites deliberately NOT ported). **Two carry-forwards for Session 3:**
(1) two-way material count is **~2/season (4 in 2025), BELOW the brief's "~4-6/season"** — the post-1.7 pinned
registry yields only 2-7 raw skill∧non-skill conflicts/season (not 28-37), ≥20-PPR floor keeps 10; honest +
reproduced, not a regression. (2) two generalization keys are **float32-vs-float64 duplicates** of the same
scoring (distinct JSON-hash, identical substrate) — a minor L0 keying inefficiency, within the cap. **Cleanup:**
main pushed to origin; the stale prior-run `claude/backend-engine-improvement-2-5` worktree/branch (`f864715`,
local-only, redundant) pruned. **Next = Session 3a (corpus harvest, MULTI-PART) — scoped, NOT started; its
worktree is on old main and must re-setup on `51940eb`.** — Prior: **BACKEND — ROSTER SUBSTRATE REPRODUCIBILITY: the registry PINNED as the
authority for rostered skill-eligibility (Improvement-Loop Session 1.7); the determinism the corpus +
ledger rest on.** The 1.6 finding is RESOLVED. **Reframe, not patch:** for a rostered player,
skill-eligibility ("what slot does he fill?") is a **fantasy** question (Sleeper registry); stats ("what did
he produce?") are an **NFL** question (nflreadpy). The bug was that eligibility was answered by the stats
source. **Mechanism correction (proven, not assumed):** the 1.6 brief said pin `audit_join` to keep Hunter,
but nflreadpy had since accumulated his **CB** rows (wk1–7), so a fresh join now **matches** his CB row and
the skill-filter drops him **before** the remainder step (**wk1–4 remainders empty — he is not a
remainder**); pinning the audit path alone would leave the gate red. **The fix:** an immutable, versioned,
write-once players snapshot (`data_layer.ACTIVE_PLAYERS_SNAPSHOT` + `read_pinned_sleeper_players` +
`capture_players_snapshot`; parquet gitignored, id git-tracked); `join_nfl_sleeper_weekly` arbitrates a
rostered player's eligibility in the registry's favour when it disagrees with nflreadpy; `audit_join`
(dormant today, wakes for the corpus) + `compute_market_vor` + `compute_player_signal` (security axis) all
read the pin, not the 24h cache. **This session CHANGES NUMBERS BY DESIGN**, so the discipline inverts:
**bounded + stable, not "nothing moved".** Rebuilt join_season (2025 wk1–4) + everything downstream; the
union of changed ids across all 8 entities = **exactly {Travis Hunter 12530}** (every changed row named,
proven not asserted), and the full pipeline run **twice is byte-identical**. `backtest_roster_shape` green
from determinism (frame-eq 635/40/160 + a new twice-compute check); `--diagnose` extended to name the full
changed set. Other gates exit 0 (production_vor/true_rank/positional_depth/bracket_sim, check_market_vor,
l0_keying). **Exposure quantified:** corpus-wide two-way ceiling ~4–6 material players/season; 2025
real-roster = 1 (Hunter). **Residual (named, not closed):** pinning gives determinism, NOT historical
accuracy (the registry is current-state — a Session-3 footnote). **Answer-key wrinkle:** Hunter's 63.8 PPR
are his CB line → recommend FLAG (cross-position two-way), not exclude; defer to Session 3. **⚠️ Concurrent
Session 2 (NOT a 1.7 regression):** `backtest_ros_player_band` is red because Session 2's in-flight
`adp_points_curve` migration (pooled→per-holdout) removed the pooled curve this branch reads → the §2 anchor
is a no-op (coverage = the UNCHANGED pre-anchor 0.744, identical to 1.6 → production_vor byte-identical,
exonerating 1.7); resolves post-merge. Sessions 1.7 & 2 are INDEPENDENT (disjoint writes: league-scoped vs
NFL-global/scoring-scoped; the only shared edited file is `data_layer.py`, additions in different regions).
**No `queries.js`/view edits — the seam held. Next: the has_ros_anchor→in_calibrated_pool rewire (post
Session 2).** **Fold-in (merged Session 2 into 1.7):** the §2 ADP anchor is live post-merge (Session 2 had
already repointed the reader to `read_adp_points_curve(holdout=season)`; the earlier `0.744` was only 1.7's
stale pre-merge worktree). Added the **missing anchor-consumption gate** to `backtest_ros_player_band`: it now
ASSERTS the anchor is non-trivial (coverage-with ≠ coverage-without, applied to N>0), so a silently-disabled
anchor FAILS the gate instead of passing — the check Session 2's "curve files exist" gate could not make
(teeth proven: a simulated missing curve flips the gate to FAIL). **Anchor live: coverage 0.744→0.817** on
the calibrated pool. Also hardened 1.7's own Part C determinism check to compare **order-insensitively**
(polars' multi-threaded group_by reorders tied rows — not a determinism property; the values are identical,
which Part A and the twice-run proof already sort for). **Report-only (BAND_Z):** Session 2's
"BAND_Z=0.55 generalizes, 2025 not the outlier" is **anchor-INDEPENDENT** — measured on `projection_consensus`,
which never consumes the ADP anchor (the anchor shifts the band CENTER in `ros_player_band`, not the width) —
so it stands unchanged with the anchor live; `backtest_projection_consensus` re-run PASS. **Regenerated the
whole merged tree** (substrate + roster chain) so data matches merged code; the twice-run determinism check
across it caught a **pre-existing (1.6) non-determinism in `ros_player_band.in_calibrated_pool`** — the
top-300 suppression cutoff broke `ros_center` ties by `ordinal` rank (i.e. by polars' parallelism-dependent
row order), flipping 6 boundary booleans run-to-run (no numeric change, not gated). **Fixed:** the tie-break
now pins on `sleeper_player_id` (`_mark_calibrated_pool` pre-sorts); the full substrate ({ppr,half}×2020–2025)
rebuilt via `build_substrate` — now **every** entity, incl. `ros_player_band`, is twice-run byte-identical.
All gates green (incl. `check_adp_curve_leakage`, `backtest_ros_player_band`, `backtest_roster_shape`). — Prior:
**BACKEND — NFL SUBSTRATE BACKFILL 2020–2025 (Improvement-Loop Session 2): the
corpus's multi-season forward-prior spine, which the engine has never had.** `projections` backfilled for
2020–2024 (existed only for 2025) after a schema-honesty pre-check proved every load-bearing component column
populated per season; `projection_consensus` + `ros_player_band` computed for **{ppr,half}×2020–2025** via a new
`_scoring.standard_scoring(key)` + `--scoring-key` on both computes + a `build_substrate.py` driver. **Leakage
fix:** the §2 ADP anchor curve — one season-agnostic pooled file — is now persisted **per held-out target
season** (`derived/adp_points_curve/holdout_{S}.parquet`, fit on every season EXCEPT S, with
`holdout_season`/`train_seasons` provenance), gated by a new **`check_adp_curve_leakage`** hard check (proven to
have teeth). **Band freeze retired:** `compute_ros_player_band` now spans the full projected season (dropping its
last `join_season`/roster-path read), and `write_ros_synthesis._read_anchor` is **pinned** to the league-view's
freeze as-of so the live 2026 AI anchor stays byte-identical. **Independence from the concurrent §1.7 verified
against the code:** §2 never reads the roster substrate §1.7 rebuilds; disjoint code regions + disjoint data
writes; §1.7's lone read of §2 territory (2025/ppr consensus) is byte-identical by gate #4. **Report-don't-tune
(gate #5):** first multi-season calibration look — BAND_Z=0.55 generalizes (2025 is NOT the outlier), SKEW_GAIN=1.5
is fragile (helps 2020/21/22/25, hurts 2023/24); constants left exactly as-is. **Verified:** all gates exit 0;
2025/ppr consensus + the wk4 band anchor slice + the 2026 render byte-identical; front end provably unaffected.
**Next — Session 3 (corpus harvest) on the substrate.** — Prior: BACKEND — GATE REPAIR + one REPRODUCIBILITY DIAGNOSIS (Improvement-Loop
Session 1.6): the broken instrument fixed before Sessions 2–3 measure against it.** Baseline measurement
first corrected the brief: only **3** of the "4 red gates" were actually red (`backtest_ros_player_band` was
already GREEN at 0.817 — its verdict grades the rostered-freeze population, not the whole pool the brief
described). **C1 — the two L0-fallout crashes.** `check_market_vor` TypeError: the brief's "give
`_market_vor_path` a default" mis-diagnosed — **no** `_*_path` helper default-resolves; the public
`read_*`/`*_exists` wrappers do, and the gate bare-called the private helper. Fixed by routing through
`market_vor_exists` + reading the FULL tall parquet via the resolved key (`read_market_vor` filters to the
latest snapshot, so it can't back the recompute-match); **also regenerated the stale 1-snapshot market_vor
cache to the 33 banked market days** (overlap byte-identical — purely newly-banked days; the recompute-match
is regenerate-then-verify by design for the daily market). Path-fn audit: only that one call site was
affected. `check_ros_synthesis` ValueError "No is_mine league for 2026": NOT a scoring-scope error
(ros_synthesis is deliberately league-scoped) — the news-world season (2026) was used as a league-registry
season, but the is_mine league is a 2025 redraft league (no 2026 `league_id` exists), and scoring_key
resolution ALSO goes through `_active_league`. Fixed with **`_active_league_any`**, a season-robust resolver
(exact is_mine season, else the latest ≤ it) wired into ros_synthesis read/write/exists ONLY (every other
entity keeps strict `_active_league`); guarded `_resolve_anchor_season`; and **completed the L0 migration
Session 1 couldn't** (it crashed on `_active_league(2026)`): byte-preserving flat→keyed copy of
`ros_synthesis_2026.parquet`, `public/data` symlink repointed, flat removed. **C2 — the 4 missing
`production_vor` rows, PROVEN not patched.** New read-only `--diagnose` mode names them: all one player —
**Travis Hunter (12530, JAX)** at as_of_week 1-4. Mechanism: `nfl_stats` labels him **CB** (his fantasy
points are IDP/return), the Sleeper registry labels him **WR** — a two-way rookie. `join_season` is rebuilt
from the 24h registry via `audit_join`, which keeps a rostered remainder only when the registry then calls
him a skill position, so his membership in the roster substrate **flips with the registry's label at rebuild
time**. This is audit S1.1's reproducibility hole, via the ROSTER path (`join_season ← audit_join ←
registry`), not the direct position join the brief hypothesised (that's `compute_market_vor`'s). Reported +
fix proposed (freeze `position` into `join_season` at write time, or pin the registry snapshot) in
`S1_6_FINDING_roster_reproducibility.md` for a follow-up session; **not fixed here** (regenerating would bake
in a transient registry state). `backtest_roster_shape` stays **honestly RED** with a named, proven reason.
**C3 — `ros_player_band` calibrated pool (report, don't tune).** Added `in_calibrated_pool` (first-class
suppression column): per (season, as_of_week) the top-300 skill players by `ros_center` UNION per-position
floors (QB32/RB80/WR90/TE32), league-agnostic so it keeps the scoring-scope. **BULL_Z UNCHANGED** — proven:
all 16 pre-existing band columns byte-identical, only the boolean added. Positional composition REPORTED at
freeze: QB48/RB80/TE55/WR121 (QB over-weight visible). Gate gains a whole-pool vs calibrated-pool coverage
evidence block. **MEASURED CORRECTION to the brief:** whole-pool coverage does NOT collapse to ~0.70 — at
freeze under BULL_Z=1.44 it is **0.841** (whole, n=529) vs **0.796** (calibrated, n=304), BOTH calibrated;
deep-bench fodder has near-zero projections AND near-zero actuals (trivially covered), so the pool
restriction's value is decision-relevance + suppression, not rescuing a collapse. **Reported gap (wiring
deferred):** `has_ros_anchor` keys off rostered membership, not `in_calibrated_pool` — 6 rostered players sit
outside the pool and would still reach the AI with an out-of-pool anchor. **Verified:** `check_market_vor` +
`check_ros_synthesis` exit 0; `backtest_ros_player_band` still green + evidence; `backtest_roster_shape`
honestly red (diagnosed); all 8 answer-key gates byte-identical to baseline (scoring_recompute's lone diff is
pre-existing display-sample non-determinism); front end renders live at 1280px with zero console errors —
Players table (MKT refreshed), Ja'Marr Chase card shows ROS BULL 9/10 from the repointed ros_synthesis. **No
`queries.js`/view edits — the seam held.** **Next — Session 2 (substrate backfill) / Session 3 (harvest) can
start on a trustworthy baseline; queued follow-ups: the roster-reproducibility fix + the `has_ros_anchor`
rewire.** — Prior: BACKEND — `team_form` + `team_leakage` RETIRED (Improvement-Loop Session 1.5):
the scope-correction before the corpus harvest.** Two fully-orphaned derived reads — neither a DECISION_READS
§1–§7 read, their only consumers pre-Gridiron panels imported by nobody — deleted across backend, front end and
docs (so the harvester won't compute them ~276× for reads that don't exist). `team_leakage` was retired **on
principle**: it graded start/sit against **realized points** — a design-law-1 violation that coached the exact
spike-week error `Error_Mapping.md` fights; the *process*-graded successor (start/sit vs the
`projection_consensus` prior knowable at decision time) is recorded as future work in `DECISION_READS.md`, **not
built**. **Commit 1 (backend):** deleted `compute_team_form.py`/`compute_team_leakage.py` + the six `data_layer`
read/write/path fns + the persisted parquets; dropped leakage from `backtest_roster_shape` (the frame-eq target
**and** its synthetic-superflex sub-check — kept production_vor/true_rank/positional_depth + the
position_pools/VOR checks) and the two entities from `backtest_l0_keying`'s `_LEAGUE_ENTITIES`; **`_analytics.py`
untouched.** **Commit 2 (front end):** deleted `TeamPanel.jsx`/`LeaguePanel.jsx` + the whole dead `queries.js`
cluster reachable only from them (loadPowerRankings / loadTeamDetails-**plural** / loadTeamRosters / loadTeams /
loadTeamPlayers + their SQL consts & row-assemblers), the two `db.js` registrations, and the two `public/data`
symlinks; **kept** the live **singular** `loadTeamDetail` + `expandSlots`/`optimalLineup`/`teamProjections`.
**Commit 3 (docs):** DECISION_READS "Retired reads", TECHNICAL_ARCHITECTURE (folder/derived/config-seed/
Known-Scope-Exclusions — `MIN_GAMES` now in one place), READ_BUILD_ORDER, PRODUCT_ROADMAP. **Verified:**
`compileall` clean + zero dangling refs; `backtest_l0_keying` still **exit 0**; `backtest_roster_shape` output
**byte-identical except the removed leakage lines** (deleting a dead read moved **no live number** — standing
instruction 5); all five front-end surfaces (Players · Teams · League · **Matchups** · Dossier) render live at
1280px with **zero console errors** and **no fetch** for the retired parquets. **⚠️ Pre-existing (NOT this
session):** `backtest_roster_shape`'s `production_vor` frame-eq FAILs at baseline — the on-disk derived parquet
(635 rows) is **stale** vs current compute (631); a shared-store data-regeneration concern, orthogonal to this
deletion and left unfixed here (regenerating would "move numbers"). **— Prior: BACKEND — L0 KEYING SHIPPED + REAL-DATA GATE GREEN (Improvement-Loop Session 1): the unlock —
every league/scoring-scoped derived parquet is now partitioned by its scope, so league #2 can't silently
overwrite #1 (audit S1.3), `projection_consensus` is stored per scoring profile not scoring-agnostically
(S3.1), and `ros_outcome_shape` is split into a scoring-scoped `ros_player_band` + a league-scoped
`ros_league_view` (S3.2).** **Commit 1** — `transforms/_keys.py` (the `scoring_key`/`shape_key` home,
re-exported by `corpus/_corpus.py`) + a `leagues.parquet` **league registry** (a projection of the corpus
manifest ∪ the live config league, built by `shared/league_registry.py`) + a registry-aware
`league_resolver` (`resolve_active` / registry-first `resolve_league_id`) + `data_layer._active_league`.
**Commit 2** — the 12 derived read/write pairs re-keyed to `derived/league/<league_id>/…` ·
`derived/scoring/<scoring_key>/…` · `sleeper/<season>/league/<league_id>/manager_activity` via a
**default-resolves-active** kwarg (every existing `compute_*`/`backtest_*` caller unchanged — only the
Session-2 harvester will pass explicit keys; the per-league partition also bounds the O(n²)
manager_activity/ros_synthesis read-modify-write) + a `backtest_l0_keying` no-regression gate (old-flat ==
new-keyed frame-for-frame · ROS reconstruction · collision isolation · registry/resolver smoke).
**Commit 3** — the `ros_outcome_shape` split: `compute_ros_player_band` (scoring-scoped, roster-free, over
the whole projected pool, **round1-the-centre-before-the-band invariant preserved** so the band reproduces
the old frame) + `compute_ros_league_view` (league-scoped: roster membership + league-relative
`spectrum_pos` + situation/security carry-through) + `backtest_ros_player_band` (renamed); `ros_synthesis`
rewired to anchor off `band ⋈ view` and **kept LEAGUE-scoped** (its grades depend on league-relative
`spectrum_pos`/`security`/`direction`, so a scoring-agnostic store would re-collide at n=2 same-scoring
leagues — the spec table's "truly shared" end-state is deferred to the live path, Sessions 7–8).
**Verified** (synthetic — this remote clone has no runtime/data): `band ⋈ league_view` reconstructs the old
`ros_outcome_shape` **frame-for-frame**; registry/resolver, collision isolation, and the ros-synthesis
anchor rewire all pass; 60+ modules import clean. **The real-data frame-for-frame gate PASSED on the 2025
snapshots (this session, on the runtime host):** registry built (`leagues.parquet`, 278 rows, primary
`1182…/ppr`); a **byte-preserving copy** migrated the 12 flat entities to keyed paths (never re-run —
`market_vor`/`manager_dossiers`/`manager_activity` would have drifted, violating "change no number") +
`ros_player_band`/`ros_league_view` computed; `backtest_l0_keying` **exit 0** — all 12 frame-identical, ROS
reconstruction green (a lone stale `security` cell in the old `ros_outcome_shape` — player_signal was
re-run after it was last built — was refreshed from current inputs, confirming the split is lossless), and
the **collision proof** green. Front end re-verified (Players/Teams render from the keyed paths after the
`public/data` symlinks were repointed; `db.js`/`queries.js` untouched; console clean); the redundant flat
parquets were then removed. **Deferred to Session 2** (nothing to collide until league
#2's data exists): the frontend `MY_USERNAME`→`is_me` swap, re-keying the *fetched* league entities
(teams/roster_positions/league_settings), and `db.js` multi-league addressing. **Next — the corpus harvester
(Session 2):** the BFS crawl (`_manager_leagues` + `classify_league`) reading `corpus_manifest`, persisting
the shape-matrix backfill under the new keyed paths — the first data that exercises the isolation L0 just
built. — Prior front-end: **GRIDIRON FRONT-END — MOBILE-RESPONSIVE PASS SHIPPED: the app is now
responsive (it was Web-1280 only — `styles.css` had zero media queries).** A single
`@media (max-width: 768px)` layer over the existing token/class system; the web layout is the
untouched base above 768px (verified unchanged at 1280). **Commit 1 — chrome + foundation:** flattened
`TopBar` to five grid-area-placed children (brand / league / tabs / week / avatar) so the layout
regroups per breakpoint without touching the DOM → mobile is a **2-row header** (brand + avatar /
league-card + week-card) + a **fixed bottom tab bar** (icon-over-label, active = violet); `gr-main`
gains bottom-nav clearance, `gr-detail` goes full-screen, `html/body` guard against horizontal page
scroll. **Commit 2 — per-surface reflow:** the **tables keep every column** — they break out to the
full viewport width with a restored edge gutter, tighter interior padding and **thicker rows** (the
shared-mockup look); Players fits all 7, Teams (which also carries a sparkline) drops only the
decorative **Trend** column (the Playoff % number carries the read) + caps the team name, keeping every
data column, and the owner sub truncates while the **YOU** badge always survives (a `tm-owner` span +
flex sub). League's Your Race band + 3-col dashboard **stack**; Player card / Team detail (stat blocks →
2×2, this-week bar stacks) / Matchup detail (rosters → one column) all reflow. **Commit 3 — Matchups
behavior:** a small **`useIsMobile()`** (matchMedia at 768) switches Matchups between the web
**two-pane** and a mobile **tap-through** (slate → the full-screen `matchup` stack detail, reusing the
type already wired); App passes `onOpenMatchup`. Views stay pure; no data-layer change. Verified live
375px (browser preview): 2-row header + bottom nav (tab tap switches surface, active violet);
Players/Teams fit all columns with taller rows + YOU preserved; League stacks (Posture Map + Positional
Talent intact); Player card, Team detail (2×2 + stacked this-week bar + depth), Matchup detail (stacked
rosters + gauges) reflow with no overflow; Matchups slate → tap → full-screen detail → Back; and at 1280
the web layout (top segmented tabs, League 3-col, Matchups two-pane) is unchanged; console clean.
**Next — the (backend-blocked) free-agent value read** that unblocks the Players `Available` filter +
the League Waiver-Wire strip (also queued: self-hosting the fonts for offline/static-hosting). — Prior
front-end: **GRIDIRON FRONT-END — MATCHUPS SLICE SHIPPED: the fifth and final
`DATA_CONTRACT` surface (§4.3), completing the 5-surface contract (Players · Dossier · Teams · League ·
Matchups).** As-of week N the Matchups tab shows week **N+1**'s head-to-head slate, fully *projected*
(the app is a season replay — the pairing is known in advance, the scores are the future it's pretending
not to know). New pairing-only **`schedule_{season}.parquet`** (`export_schedule.py` + `data_layer`
schedule helpers: the weekly Sleeper matchup snapshots stacked, **`points` dropped** so no future result
reaches the client) + `projection_consensus` wired into `public/data` + `db.js`. **Commit 1 — data seam +
slate:** `queries.loadMatchups`/`loadMatchupDetail` off a shared `teamProjections()` — the frozen
roster-as-of-N (same `arg_max` Team detail uses) set into its **optimal lineup** by the target week's
projection centre; μ = Σ starter `center_ppr`, σ = √(Σ `band_ppr²`), win prob =
**Φ((μA−μB)/√(σA²+σB²))**, mirroring `compute_bracket_sim.py`'s analytic core (ported
`expandSlots`/`optimalLineup` + an erf `normalCdf`; the 10k Monte Carlo stays server-side — playoff odds
already come from `bracket_odds`). `Matchups.jsx` slate: head-to-head cards, your game pinned +
violet-washed, records + projected totals, a new **`WinProbBar`** mark (your side violet, opponent steel).
**Commit 2 — matchup detail + web two-pane:** `MatchupDetail.jsx` — head-to-head win prob, each team's
**Score Range** (Σ starters' 25–75 on a shared scale, overlap = upset room; reuses `RangeGauge`),
per-starter range gauges, starters+bench (starters = the optimal projected lineup); the tab is a
persistent two-pane (slate left, detail right, your game selected by default) and a `matchup` detail type
in the App stack reuses `MatchupDetail`. **Commit 3 — integration:** the **this-week matchup bar** in Team
detail (§4.5, no longer deferred — `loadTeamDetail.thisWeek` drills into the full detail), the new marks'
styles, verify + docs. **Watch-game (§5) deferred honestly** — it needs playoff odds re-simulated per
outcome (a server-side Monte Carlo the client can't run), consistent with the app's honest-gaps discipline.
All data access through the `queries.js` seam; views stay pure renderers. Verified live 1280px (browser
preview): wk4→**wk5** slate, 5 games, your game pinned; win prob/μ cross-checked against an independent
bracket-sim-math recompute (my game **128.5/57% vs 124.4/43%** exact; one game ±1% from optimal-lineup
tie-break σ); two-pane selection swaps the right pane; starter projections sum exactly to team totals
(8 starters each); Team-detail this-week bar → matchup detail → Back chain; **season replay wk2 → wk3
slate** (roster/schedule/odds all re-target N+1); `schedule.parquet` carries no `points`; console clean.
**Next — the mobile-responsive pass** (both mockups ship a mobile layout; the app is Web-1280 today) **+
the (backend-blocked) free-agent value read** that unblocks the Players `Available` filter + the League
Waiver-Wire strip. — Prior (backend): **§0.6 — `_scoring` FLOAT32 TOLERANCE FIX (a LIVE engine bug the corpus caught)
+ corpus re-select.** `scoring_profile` compared weights at `_TOL=1e-9`, but Sleeper serves them at float32 (a
`0.1` → `0.10000000149…`, drift ~1.5e-9), so **every drifted standard PPR league was misclassified `custom`** —
which dropped clean leagues from §7 `is_comparable` AND was the real cause of §0.5's "clean zero" (0 matched in
2020 *and* 2021). Fixed at real-world precision: new `_weights_match` (round-4) at the classifier + `_TOL`→1e-6
for the numeric guards; **over-loosening guard holds** (a genuine custom weight, Δ0.01, still classifies
`custom`); 4 network-free guard tests. **No-regression PROVEN** (the real 2025 league is clean-ppr, unaffected):
all 9 backtests byte-identical before/after, `compute_projection_consensus(2025)` value-identical to the on-disk
parquet. **Corpus re-selected offline (no re-crawl)** by re-classifying from the persisted `scoring_settings_json`.
**The three numbers, corrected:** (1) matched-eligible is **SIX seasons, not four** — 2020:10 / 2021:19 / 2022:30 /
2023:66 / 2024:70 / 2025:125 (**eligible** total 261→320, +23%); manifest 319→**365 rows**, matched **selected**
2020:9 / 2021:15 / 2022:24 / 2023:53 / 2024:60 / 2025:60 (179→**221**). (2) split **TRAIN 2020-2023 · DEV 2024 ·
TEST 2025**; 2020-21 thin (9,15) ⇒ league-wise k-fold *within* train. (3) unscoreable **45.4%** (802/1,765), **not
39.2%** (802/2,045) — the denominator was inflated by the 280 standard leagues wrongly tagged `custom`; the rate
*rose* once they left. **§7 hypothesis — NO improvement on the real league:** 0/10 managers gained comparables
(activity identical before/after), so the "thin friend-group" §7 read is genuinely thin, **not** the bug (a real
finding either way). `check_corpus` exit 0 with a new **HARD floor** that would now FAIL on a suspiciously-empty
train season — the standing instruction *"a clean zero is a bug"* encoded. **Next was L0 keying (Session 1) — DONE, see top of file.** —
Prior: **CORPUS §0.5 — the league registry (`corpus_manifest`); its 2020-21=0 / 39.2%-of-2045 / matched-179
figures were the float32 bug above, now corrected.** — Prior front-end: **GRIDIRON FRONT-END — TEAMS CLUSTER SHIPPED: Teams standings + Team
detail + Manager Dossier, the 2nd front-end slice against the `DATA_CONTRACT` (§4.4 / §4.5 / §4.8).**
**Commit 1** the **Teams standings** — `queries.loadStandings()`: per team the real record + **all-play
"true record"** (score vs every team every week, luck-stripped) + `bracket_odds` playoff % (a 0–1 fraction
×100) with its weekly series for the trendline + the shared **posture** read. New pure **`src/posture.js`**
= the contract §5 rule (`BAND=9`, `LEVEL_CUT=60`, `POSTURE_TONE`) in ONE home — reused by the Teams chips
now and the League posture MAP later. `Teams.jsx` renders the sortable standings (rank · team+YOU · record ·
true rec · posture chip · playoff % · odds sparkline). **Commit 2** the **Team detail** —
`loadTeamDetail()`: 4 stat blocks (record, all-play true rec, playoff %+seed, pts/wk), **positional depth**
per QB/RB/WR/TE (`positional_depth` starter value + league-relative spectrum + rank + SURPLUS/EVEN/GAP shape)
via a new `DepthBar` mark, and the roster split starters/bench with each player's **Production + Market VOR
weekly series** behind a **PROD/MKT toggle** (MKT flagged cross-time POC); the **this-week matchup bar is
deferred honestly** to the Matchups slice (needs `bracket_sim`), not fabricated. **Commit 3** the **Manager
Dossier** — `loadManagerDossier()`: the cleanest 1:1 `manager_dossiers` map (headline + 5 tendency fields +
a signal-depth footer, deep/moderate/thin → HIGH/MED/THIN, + provenance; `is_zero_signal` → honest "no
intel"). `App.jsx` gains a **detail nav-stack** so multi-level drills (team → player, team → dossier) get a
correct one-level "‹ Back"; `Teams` rows drill in; `db.js` registers bracket_odds / positional_depth /
manager_dossiers (public/data symlinks added). All new data access through the `queries.js` seam; views are
pure renderers. Verified live 1280px (browser preview): standings ranked by odds with correct posture chips
(my team 87% odds × 61% all-play → Riding luck) + tone trendlines; week switcher **replays back to wk2**
(records/odds/depth all change); team detail blocks + depth bars/chips/ranks + PROD⇄MKT toggle + roster
player → card → Back returns to team detail; Bski dossier all 5 fields + MED badge + provenance; full Back
chain pops one level each; numbers match the parquet; console clean. **Next — League slice (Your Race /
Playoff Picture / Posture MAP reusing `posture.js` / Positional Talent, off `bracket_odds` + `true_rank` +
`market_vor`), then Matchups; + the mobile-responsive pass + the free-agent value read (unblocks Available/
waivers).** — Prior front-end: **GRIDIRON FRONT-END — FOUNDATION + PLAYERS SLICE SHIPPED: the first
front-end surfacing of the gated backend reads.** Recreates the Claude-Design `Gridiron` handoff (in
`scope docs/`, its `DATA_CONTRACT.md` mapping every visual → a backend entity) in the real React + Vite +
DuckDB-WASM app — Web-first, new-shell-with-placeholders migration. **Commit 1** the violet/posture design
system + 4-surface app chrome (brand + real derived league meta `10-tm · PPR · 1QB · 3-1` from teams/
league_settings/lineup_slots, segmented League/Matchups/Teams/Players tabs, the existing week selector
reused, coming-soon placeholders for the 3 unbuilt surfaces; new `icons.jsx`/`Placeholder.jsx`, `styles.css`
rewritten to the token set). **Commit 2** the **Players table** — `queries.loadPlayers()`: ONE read joining
`production_vor` (PROD VOR, default sort) + `market_vor` (MKT VOR, cross-time) + `ros_synthesis` (bull/bear/
situation 1-10 grades) + season identity, ALL on `sleeper_player_id`; VOR-anchored sortable table + position
filter, is_me YOU badges. **Commit 3** the **Player card** — `loadPlayerCard()` + shared `charts.jsx`
(Sparkline/TrendLine/GradeBar/RangeGauge): Value·VOR (Production + Market weekly series + value/delta) + a
BUY/HOLD/SELL trade lean off `trade_gap` (POC-GATED — cross-time, never a live call), Opportunity from
`player_signal` (quality_rate / opp_pct / direction+reliability / recent-vs-expected), ROS Outcome Shape
(grades + prose notes + confidence, prior-season flagged), all with honest empty states. **Honest gaps:**
rostered-only (no free-agent VOR entity → the Available filter + waiver strip are deferred, a backend
follow-up); `ros_synthesis` is sparse (~16 players → grades shown where present, full coverage needs a
roster-wide AI batch ~$0.75); MKT/trade-gap cross-time (2026 market × 2025 roster) so gated POC. All new
front-end data access is through the `queries.js` seam (loadPlayers/loadPlayerCard/loadLeagueMeta); the old
League/Team panels are retired from the shell (files kept, unimported). Verified live 1280px: real players
sorted by PROD VOR, MKT + negatives, is_me badges, PROD/MKT re-sort, QB filter, row→card→back; Player card
full (Gibbs honest ROS-empty; Hurts full ROS 8/6/6 + MED confidence + prior-season flag), no console errors.
**Next — Manager Dossier slice (trivial 1:1 map), then Teams/Team-detail → League → Matchups per the
contract build order.** — Prior backend: **§4 MARKET VOR + PRODUCTION−MARKET TRADE GAP SHIPPED — the primary
remaining backend read, and the one un-backdatable piece built on CURRENT (2026) data.** The market-value
twin of Production VOR: the same waiver=0 ÷ pool-spread VOR (reusing the shared `position_pools` /
`_pool_lines` / `_vor` engine — no new math, law 3) on the borrowed LeagueLogs `value` for the
format-matched `redraft-1qb-12t-ppr1` profile. New `data_layer` `market_vor` entity
(`derived/market_vor_{season}.parquet`, tall over the market's `snapshot_date` axis); `compute_market_vor.py`
(position from the Sleeper registry); the Production−Market **gap folded in** (`trade_gap`). The app is
frozen at 2025 wk4 but the LeagueLogs series is current 2026 and can't be backdated, so the gap is
**cross-time by construction** — every row carries `is_cross_time` + `market_season` + `has_production_vor`
as first-class columns (never fused — the `anchor_is_prior_season` precedent), and it's **POC/architecture
validation, not a live trade call** until the season rolls to 2026. **Purely additive — nothing reads it
yet, so the current-vs-2025 split does NOT affect app functioning.** Internal-consistency gate
`check_market_vor.py` (no answer key at the freeze). Verified live: 31 snapshots → 5270 rows, 170/171
frozen roster priced, gate exit 0, Production VOR gate unaffected. **Next = front-end surfacing of the
gated reads.** — Prior: **§2 ROS SYNTHESIS SHIPPED (QUEUED #2 done) — the AI interpretation
layer, completing the §2 read.** The last mile `compute_ros_outcome_shape.py` deferred ("the AI
narrative + 1-10 grade roll-up is Phase 6") now exists: a **per-player Claude call** (`application/ai/
write_ros_synthesis.py`, reusing the `ai/client.py` seam) that **fuses** the quantitative anchor
(`ros_outcome_shape`) with the situation news (`player_news_slice`) + Sleeper facts into the three §2
scores as **1-10 grades — bull / bear / situation — each with a prose note**, **consolidated headlines**
(grounded in the cited article ids), and a **confidence flag**. Graceful per-input degradation makes
the gaps FIRST-CLASS columns (`has_ros_anchor` / `has_news` / `anchor_is_prior_season` + confidence):
full-set → fully-anchored; news-only → news-led, confidence capped; nothing → a hardcoded "insufficient
data" row, **API skipped**. This is how the 2026-news × 2025-anchor **time-world mismatch** is handled
HONESTLY (the anchor is flagged prior-season, never silently fused). Output is a **structured parquet**
(`ros_synthesis_{season}`, replace-by (season,week,player)) — every grade / note / confidence is its
own column, extractable apart. The **prompt is a pure editable module** (`ai/ros_synthesis_prompt.py`)
with **no-AI iteration tooling** in the writer (`--render` prints the exact assembled prompt, `--replay`
runs a canned reply through validation — both need no API key / no cost). Gate
(`ai/check_ros_synthesis.py`) is internal-consistency (no answer key): coverage / schema / **grounding**
(headlines trace to the slice) / **confidence honesty** (thin/no-anchor ⇒ not 'high') / data-flag
honesty + a soft prose-leak scan. Verified live 2026 wk0: 16 players across all regimes (~$0.07,
grades spread bull 3-9), gate PASS, guard tests (run-once / locked-key / partial / zero-signal) all
clean. **Front-end surfacing + the browser-triggered on-demand runtime stay deferred with the
deployment/server decision** (no server exists; API key is server-side; the `news_content_hash` column
is laid down now as the future cache seam). **The prompt TEXT is expected to keep evolving — it lives in
that one pure module, and `--render`/`--replay` make tweaking it AI-free.** **Prior — Daily-collector
reliability SHIPPED — shared `_http` layer + collector
registry/dispatcher + coverage gate (QUEUED #1 done).** Separation of concerns: retry / backoff /
throttle / per-item isolation now live ONCE in `fetchers/_http.py`, and all three HTTP callers
(`sleeper` / `news` / `leaguelogs`) route through it — **leaguelogs gains the missing retry + per-item
isolation** (the fix for the audit's ~7 transient-fail + "dynasty profiles drop first" days).
`fetchers/run.py` is a declarative collector **REGISTRY + `run <name>` dispatcher** (cadence declared
per collector; the **meter stays external** — launchd → GitHub Actions, which will call this same
dispatcher, so nothing is wasted). `fetchers/check_collectors.py` **certifies** the banked series
(leaguelogs strict daily coverage; news recency), hard-gating a recent window so permanent powered-off
gaps don't fail forever; `--today` monitoring. The **off-laptop host** (the ~8 powered-off days) stays
**deferred to the deployment decision**. Verified: network-free retry/4xx self-test, live no-regression
on all three fetchers, isolation proof (a dead profile no longer aborts the run), gate reproduces the
audit (65% complete / 72% any-data) + flags the real recent gap. **Next = QUEUED #2** (§2 ROS synthesis
call — the news input `player_news_slice` now exists). **Prior — §2 news pipeline COMPLETE (Stage C):**
per-player slice by inheritance (`player_news_slice`) + thinness tripwire + retention; deterministic
reshape, hard gate, verified live 2026 wk0 (967 players → 3058 rows; prune kept all 5021 raw rows,
nulled 1243 old bodies). **Prior detail — Stage B (`application/ai/news_prompt.py`
+ `write_team_news_dossier.py` + `check_team_news_dossier.py`, reusing the `ai/client.py` seam + the
retained resolver) distills each team's recent `team_news_raw` window into a compact, **situation/security-
focused, attributed** set of **scope-tagged claims** (player / position_group / unit) a downstream AI reads
next to the numeric analytics. Per claim: `scope` / `subject` / `claim_type` / **`basis`** (official /
reported / opinion — so an opinion is never mistaken for fact) / `note` (one attributed cliffs-note) /
`direction` (positive / negative / neutral / **mixed** = cross-pressured) / `salience` / cited
`source_article_ids` + `source_types` (clustered across the 3 sources; diversity = trust). **Skill-only
(V1):** player claims are QB/RB/WR/TE and resolve to a Sleeper id via a **team-restricted** index (never a
cross-team id); all defensive news is condensed into ONE `defense` unit note (game-script context now,
pre-banked for later). Verified live: **32/32 teams, 317 claims, 1 Haiku call/team (~$0.46 total)**;
internal-consistency gate PASS (coverage / schema / grounding / on-team resolution / zero-signal honesty);
168/186 player claims resolved. Off-season window is thin by nature; richness ramps into camp.
**Design record — Stage A (still current):** `fetchers/news.py`
collects per-NFL-team from **3 native RSS sources per team** — SB Nation (grounded analysis), FanSided
(player-flavored, noisier), and the official team site (authoritative/PR) — into the new **`team_news_raw`**
entity (one row per article, **stores feed-provided content** so the extraction has text; feed-provided
only, no scraping). National desks dropped (league-level, not team); **SI/FanNation ruled out** (no native
per-team RSS — tested: zero autodiscovery, all team paths 404). Player resolution moved out of collection
into Stages B/C (the resolver is retained). Per-feed isolation + backoff + resilience-floor flag; per-team
volume reported (the Stage-C thinness-tripwire input); append-only-of-new by `article_id` (idempotent).
Verified live: **96/96 feeds across 32 teams, 5021 articles**; 0 duplicate titles; dead-feed isolation;
resolver `check` PASS; content + provenance (`published_at` 100%, url) stored. **Supersedes** the v1
`player_news` collector (left as legacy). **Design record (sparred + researched with the PM):** the value
is *interpretation + salience* (facts come from Sleeper), so trust = source diversity, not fake
corroboration; `source_type` stored for downstream weighting; the "no bodies" v1 rule was reversed because
extraction needs the text. **Prior build:** the v1 player-news collector (national feeds → `player_news`) —
now reworked.)
**Retention (Stage C — SHIPPED):** collection runs **daily** (append-only-of-new; first run was a
5021-article backfill). `news.py prune` (`RETENTION_DAYS=28`, safely > the 14d synthesis window) nulls raw
article **content** older than the cutoff while keeping the row + link + derived claims; idempotent,
`--dry-run` first. Verified: 5021 rows kept, 1243 old bodies nulled. **Scheduling deferred to QUEUED #1**
(wire `prune` into the daily job — it's a data-maintenance step, cheap + idempotent).
**Post-merge operator action: install the `com.fantasyai.news-snapshot` launchd plist** into
`~/Library/LaunchAgents/` + `launchctl bootstrap` (5am ET daily; the job now does **team** collection) —
see `scheduler/README.md`. (`feedparser` already installed in the framework Python on this machine.)
**Target ship:** NFL kickoff, mid August 2026

---

## Project Management
- my role is CEO/CFO managing the project as a whole, role responsibilities include:
    - owning product direction decisions
    - connecting Claude Chat input/output and Claude Code input/output
- Claude Chat sessions will serve as Product Manager, role responsibilities include:
    - advising on project goals, product direction, and build method
    - writing prompt instructions for Claude Code to execute singular build tasks
    - review the after-build action report from Claude Code
- Claude Code sessions will serve as Software Engineer, role responsibilities include:
    - receive the prompt instruction from the Claude Chat

## Project Overview (what are we working toward)

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

> Tech non-negotiables (polars-only, all I/O through data_layer.py, client-side
> DuckDB-WASM with src/queries.js as the server seam) live in **CLAUDE.md** and
> **TECHNICAL_ARCHITECTURE.md** — not restated here.

## Today (the current status toward v1)

> **Maintenance (rolling log):** keep only the **most recent build + the 2 prior**
> (3 prose entries max). At closedown, prepend the new build and delete the oldest
> prose entry. Nothing is lost — the cumulative record lives in `> built` below; this
> section is just the recent-detail window. Keeps the doc light for every session.

> most recent build
**§1.7 — Roster Substrate Reproducibility: pin the registry (Improvement-Loop; 3 commits).** Made the roster
substrate deterministic — the determinism the corpus (Session 3) and the prediction ledger rest on. The 1.6
finding is RESOLVED. **Reframe, not patch:** for a rostered player, skill-eligibility ("what slot does he
fill?") is a **fantasy** question (Sleeper registry); stats are an **NFL** question (nflreadpy) — the bug was
eligibility being answered by the stats source. **Mechanism correction (proven):** the 1.6 brief's premise
(pin `audit_join`) was outdated — nflreadpy accumulated Hunter's **CB** rows (wk1–7), so a fresh join now
matches his CB row and the skill-filter drops him **before** the remainder step (wk1–4 remainders empty; he
is not a remainder), so the audit-only fix would leave the gate red. **C1 (plumbing):** immutable versioned
write-once players snapshot + `read_pinned_sleeper_players` + tracked `ACTIVE_PLAYERS_SNAPSHOT`;
`join_nfl_sleeper_weekly` arbitrates eligibility in the pinned registry's favour on a nflreadpy⇄registry
disagreement; `audit_join` (dormant, wakes for the corpus) + `compute_market_vor` + `compute_player_signal`
(security) read the pin. **C2 (rebuild + gate):** rebuilt join_season (wk1–4) + all downstream; the union of
changed ids across all 8 entities = **exactly {Hunter 12530}** (every row named), full pipeline **twice
byte-identical**; `backtest_roster_shape` green from determinism (frame-eq 635/40/160 + a new twice-compute
check; `--diagnose` names the full changed set); other gates exit 0. **C3 (quantify + docs):** corpus-wide
two-way ceiling ~4–6 material/season, 2025 real-roster = 1 (Hunter); residual = determinism ≠ historical
accuracy (Session-3 footnote); answer-key wrinkle (Hunter's 63.8 PPR are CB) → recommend FLAG not exclude.
**⚠️ Concurrent Session 2 (NOT a 1.7 regression):** `backtest_ros_player_band` red = Session 2's in-flight
`adp_points_curve` pooled→per-holdout migration removed the pooled curve this branch reads → §2 anchor no-op
(coverage = the UNCHANGED pre-anchor 0.744 → production_vor byte-identical → 1.7 exonerated); resolves
post-merge (done — see the fold-in note in the header). **No `queries.js`/view edits.**

**§2 — NFL substrate backfill 2020–2025 (Improvement-Loop; the corpus's forward-prior spine; 2 code commits
+ a data backfill).** Session 3 (harvest) can compute nothing without a multi-season forward prior; it
existed only for 2025. **Independence from the concurrent §1.7 verified against the code, not assumed:** §2's
computes read only NFL-global/config inputs (`projections`/`nfl_stats`/`adp_preseason`/`projection_consensus`),
never the roster substrate §1.7 rebuilds; §1.7's lone read of §2 territory (`compute_production_vor` → 2025/ppr
consensus) is a file §2 is pinned NOT to move (gate #4); disjoint code regions + disjoint data writes. **Data
backfill (no code diff):** `projections` for 2020–2024 (5×18 fetches via the existing `sleeper.py projections`
mode) — schema-honesty pre-check FIRST (all load-bearing component columns populated per season, else STOP),
idempotent (re-run week ⇒ unchanged). **C2 — leak-free per-holdout ADP curve.** The §2 anchor curve was ONE
season-agnostic file, so grading `ros_player_band` on 2023 fit the anchor on 2023's own outcomes (silent,
optimistic, invisible). Now `derived/adp_points_curve/holdout_{S}.parquet` fit on every season EXCEPT S
(+ provenance `holdout_season`/`train_seasons`); `data_layer` adp fns take `holdout`; the band's
`_load_anchor_inputs(season)` reads `holdout=season`. New `check_adp_curve_leakage` HARD gate (provenance
honesty + train==complement + recompute-match), **proven to have teeth** (fails a deliberately-leaky curve on
both arms). No-regression: `holdout_2025` (train 2020–2024) is byte-identical on core cols to the retired flat
curve (already holdout=2025 by default), so 2025 doesn't move. **C3 — {ppr,half}×2020–2025 substrate +
full-season band + anchor pin.** New `_scoring.standard_scoring(key)` + `--scoring-key` on both computes
(explicit-key `run`, no `_active_league` for historical seasons) + a `build_substrate.py` driver (12 consensus
+ 12 band). **Retired the band's wk-4 freeze** — `compute_ros_player_band` now spans the full projected season
(dropping its LAST `join_season`/roster-path read); **pinned `write_ros_synthesis._read_anchor`** to the
league-view's freeze as-of so the live 2026 AI anchor cannot move. **Proven byte-identical:** 2025/ppr
consensus (gate #4), the band's wk1–4 anchor slice, and the 2026 `--render` prompt (sha256 match).
`backtest_ros_player_band`'s pool-coverage evidence re-pinned to the decision week (0.841/0.796 reproduced).
**Per-season calibration REPORTED, not tuned (gate #5):** BAND_Z=0.55 generalizes (every season's best-Z is
0.55–0.60 — **2025 is NOT the outlier**); SKEW_GAIN=1.5 is fragile (helps 2020/21/22/25, hurts 2023/24) — a
Tuner-session finding, constants left exactly as-is. **Verified:** all gates exit 0
(`backtest_projection_consensus`/`production_vor`/`ros_player_band`/`l0_keying` + `check_adp_curve_leakage`/
`check_ros_synthesis`/`check_market_vor`); front end provably unaffected (every entity it reads is byte-identical
or untouched; the band is not a front-end read). **Next — Session 3 (corpus harvest) on the substrate.**

> earlier build
**§1.6 — Gate Repair + one reproducibility diagnosis (Improvement-Loop; 3 commits).** Repaired the broken
gate instrument before Sessions 2–3 measure against it. Baseline measurement corrected the brief: only **3**
of the "4 red gates" were red — `backtest_ros_player_band` was already GREEN (0.817; its verdict grades the
rostered-freeze population). **C1 — two L0-fallout crashes.** `check_market_vor` TypeError: no `_*_path`
helper default-resolves (the public wrappers do); the gate bare-called the private `_market_vor_path`. Fixed
by routing through `market_vor_exists` + reading the FULL parquet via the resolved key (`read_market_vor`
filters to the latest snapshot); **regenerated the stale 1-snapshot market_vor to the 33 banked market days**
(overlap byte-identical — newly-banked days only). `check_ros_synthesis` ValueError "No is_mine league for
2026": the news-world season is used as a registry season, but the is_mine league is a 2025 redraft league
(no 2026 `league_id`). Fixed with **`_active_league_any`** (season-robust: exact is_mine season else the
latest ≤ it), wired into ros_synthesis read/write/exists ONLY; guarded `_resolve_anchor_season`; completed
the L0 migration Session 1 couldn't (crashed on `_active_league(2026)`) — flat→keyed byte-preserving copy of
`ros_synthesis_2026.parquet`, `public/data` symlink repointed, flat removed. **C2 — the 4 missing
`production_vor` rows, PROVEN not patched.** New read-only `--diagnose` mode: all 4 are one player, **Travis
Hunter (12530, JAX)** at as_of_week 1-4. `nfl_stats` labels him **CB** (IDP/return points), the registry
labels him **WR** — a two-way rookie; `join_season` (rebuilt from the 24h registry via `audit_join`) keeps a
rostered remainder only when the registry then calls him skill, so his substrate membership **flips with the
registry at rebuild time** — audit S1.1's reproducibility hole via the ROSTER path (not the direct position
join, which is `compute_market_vor`'s). Reported + fix proposed in `S1_6_FINDING_roster_reproducibility.md`
(freeze `position` into `join_season`, or pin the registry) for a follow-up; **not fixed** (regenerating bakes
in a transient state). `backtest_roster_shape` stays **honestly RED**, named + proven. **C3 —
`ros_player_band` calibrated pool (report, don't tune).** Added `in_calibrated_pool` (first-class suppression
column): per (season, as_of_week) top-300 by `ros_center` UNION per-position floors (QB32/RB80/WR90/TE32),
league-agnostic. **BULL_Z UNCHANGED** — all 16 band columns byte-identical, only the boolean added.
Composition reported at freeze QB48/RB80/TE55/WR121. Gate gains whole-pool vs calibrated-pool coverage
evidence. **MEASURED CORRECTION:** whole-pool coverage does NOT collapse to ~0.70 — 0.841 (whole, n=529) vs
0.796 (calibrated, n=304), both calibrated (fodder has near-zero projections AND actuals → trivially
covered); the pool's value is decision-relevance + suppression. **Gap reported (wiring deferred):**
`has_ros_anchor` keys off rostered membership, not the pool — 6 rostered players sit outside it. **Verified:**
`check_market_vor` + `check_ros_synthesis` exit 0; band gate green + evidence; roster_shape honestly red;
8 answer-key gates byte-identical to baseline; front end live at 1280px, zero console errors (Players MKT
refreshed, Chase card ROS BULL 9/10 from the repointed parquet). No `queries.js`/view edits — seam held.
**Next — Sessions 2/3 unblocked on a trustworthy baseline; queued: the roster-reproducibility fix + the
`has_ros_anchor` rewire.**

> built
    - nflreadpy fetcher
    - sleeper fetcher (includes fetch_players() for Sleeper player registry)
    - nfl_sleeper join (left join, Sleeper-authoritative)
    - audit_join (resolves unknown-position remainders post-join)
    - front-end skeleton (React + Vite + DuckDB-WASM, reads live parquet) — Power Rankings panel
    - leaguelogs fetcher (daily market-value snapshots, all profiles) + launchd 4am-ET scheduler
    - sleeper teams fetch (fetch_teams → teams_2025.parquet) — real team names on Power Rankings cards
    - roster_positions fetch + derive_lineup_slots transform — declared starting-lineup config (lineup_slots_2025.parquet)
    - Power Rankings team drill-down drawer — all-play true record, lineup efficiency, weekly scoring, consistency + positional-shape spectrums
    - tab nav shell (League | Team) — App.jsx shell + LeaguePanel/TeamPanel split
    - Team tab foundation — your-team resolver (loadTeams + MY_USERNAME), team switcher, Overview/Players sub-tabs (stubbed)
    - Team Overview sub-view — vitals + "how this team is built": rate-based depth chart, league-relative star dependence, auto-surfaced lineup/hole signals; loadTeamRosters(), shared posColors.js [Overview lenses 1–2 of 4]
    - Team Overview — Form / trajectory lens: direction headline (heating up/cooling off/steady), league-relative Fading↔Surging spectrum, weekly column chart (beat/below median); last-half vs first-half scoring swing in loadTeamRosters() [Overview lens 3 of 4]
    - Team Overview — Where-you-leave-points lens: season points-left + efficiency % on a league-relative Leaky↔Optimal spectrum, per-week leak chart, biggest specific start/sit misses (eligibility-aware pairing); shared optimalLineup()/expandSlots() helpers + computeLeakage() [Overview lens 4 of 4 — Overview complete]
    - Team Overview refinement — Form lens → recency-weighted EWMA slope (half-life 2wk, ±4%/wk direction band, recency-faded weekly bars); computeForm() rewritten [backlog item 2]
    - Team Overview refinement — Lens-4 reframe (retrospective → improvement): efficiency-led, season points-left split into variance vs coachable (repeatable >10% bench-over-starter fix, sum-exact), named-miss list replaced by one rate-gap fix; computeLeakage() takes season role+rate map [backlog item 1]
    - Architecture refactor — form + leakage analytics extracted from queries.js → Python transforms (compute_team_form.py + compute_team_leakage.py → snapshots/derived/), tuning constants moved with them; queries.js slimmed to a thin read+assemble seam (−253 lines); loadTeamDetails efficiency consolidated to read the leakage parquet. View components untouched.
    - Phase 1 spike signal-quality engine — compute_player_signal.py → derived/player_signal_{season}.parquet (opportunity-vs-efficiency decomposition, regression_risk, sample-gated read); backtest_player_signal.py validates the shipped function against the full-2025 answer key (beats naive recent-points 13% on MAE; spike group regresses ~3.9 pts/g while sticky holds). First decision-critique slice; data + backtest only, no UI yet.
    - Phase 1 Players sub-view — sortable table surfacing the signal read per player (recent /g, directional verdict, volume rank, TD share); loadTeamPlayers(rosterId) seam reads player_signal.parquet (no JS math); direction-not-projection, question-framed (laws 2+4), sample-gated. The front end's first decision-coach surface.
    - Phase 1 per-panel readiness gate — readiness.jsx (assessReadiness + Gate): per-panel regime (structural/point-in-time/trend) → ready/building/tooEarly, with a "too early" fallback slot (accepts preseason content later) and an early-read note when building; wired into the Team tab (?weeksOverride=N for QA). Closes Phase 1.
    - leaguelogs snapshot reliability — snapshot() rewritten to write incrementally (cumulative today's-rows persisted after each profile) so a mid-run API failure leaves a recoverable partial day instead of discarding the whole run; idempotent re-run replaces a partial day (dedup on snapshot_date). 2026-06-18 captured (5 profiles, 3,409 rows; history → 14 dates). Follow-up still open: retry/backoff + off-laptop host. **(2026-07-11 audit: over the full 41-day series 05-31→07-10 coverage is 63% complete / 71% any-data — ~8 laptop-off + ~7 no-retry days, all permanent. This follow-up is now specced as the generalized "Daily-collector reliability" item in `READ_BUILD_ORDER.md`, covering both `leaguelogs.py` and `news.py` via one shared `fetchers/_http.py` + a `check_*` coverage gate + an off-laptop host merged with Deployment.)**
    - Season-replay backend (Session A; parts 1–3) — `as_of_week` first-class column on the three derived analytics; tall grain `(season, as_of_week, entity)` materialized N=1..maxweek (each transform loops, filtering input to `week ≤ N`). Roster-as-of-N correctness fix falls out of that filter (`arg_max(week)` → "latest week ≤ N"). Per-analytic windowing framework: injected EWMA half-life via shared `_weighted_rates`; `backtest_player_signal.py --sweep` tunes the opportunity half-life on the 2025 answer key → ships cumulative (tested, not guessed). `data_layer` reads take optional `as_of_week` (default latest); `queries.js` default-latest guard keeps the front end on week 4. **Front-end week selector is Session B.**
    - Season-replay front-end (Session B; part 4 — grouping COMPLETE) — global "As of" week dropdown in the App shell (`App.jsx`); one selection drives League + Team and persists across tabs. `queries.js` threads `asOfWeek` via `asOfSlice(table, n)` (pick the week-N slice of the tall derived parquets) + `weekCutoff(n)` (bound inline `season.parquet` reads to `week ≤ N`, including `SQL_CURRENT_TEAM`'s `arg_max(roster_id, week)` → front-end roster-as-of-N); `n == null` ⇒ latest, so defaults are unchanged. New `loadWeeks()` feeds the dropdown (weeks 1..latest, default = latest = current week; travels back only). Readiness gate now runs off the selected week (`weeksElapsed = asOfWeek`); the temporary `?weeksOverride` QA param is retired. Verified live across weeks 1–4 (cutoff reshuffles rankings; trend panels degrade to too-early; roster-as-of-N departed flags; no console errors).
    - Phase 1 refinement — Opportunity to spec (`quality_rate`, `direction`/`reliability`, `security`, `point_correlation`) — see "most recent build" above for the full breakdown. `nfl_stats.py` gains a PBP-derived quality signal (`xtd`/`redzone_touches`); `sleeper.py`'s `fetch_players()` carries injury/depth-chart fields through. 2025 backtest gate unchanged (PASS/PASS, 13.2% MAE cut).
    - Data-layer I/O consistency — all fetcher parquet I/O routed through `data_layer.py` (Option-A coverage gap from a Phase 1 build audit). Added write_player_id_map / write_sleeper_players (+exists/age) / write_nfl_stats(week=) / write_sleeper_matchups / read+write_sleeper_transactions; rewired nfl_stats.py, sleeper.py (`_write_parquet_from_list` → `_rows_to_df` + `_snapshot_list`), audit_join.py. Raw JSON cache dumps kept as a documented fetcher exception. TECHNICAL_ARCHITECTURE truthed-up (fetchers in the I/O rule; LeagueLogs collect-only exception; MIN_GAMES 2→3 places). Behavior-preserving (byte-identical player_signal reproduction; backtest PASS/PASS).
    - Phase 2 projection substrate, source #1 (Sleeper) — multi-source `projections` entity in data_layer (write/read_projections; `source` a column on one growing snapshots/projections/projections_{season}.parquet; snapshot/append, dedup on (season,week,source)); `sleeper.py projections <season> [week]` mode pulls the NFL skill pool's weekly projections from api.sleeper.com (RotoWire), native sleeperPlayerId, QB/RB/WR/TE. 2025 backfilled wks 1–18 (54,594 rows); 100% coverage of rostered skill players at W1–4. FantasyPros joins later in-season via the same seam.
    - Phase 2 projection consensus + spread band — compute_projection_consensus.py → derived/projection_consensus_{season}.parquet (per week×player over the whole skill pool): borrowed consensus center + p25/p50/p75 band from the player's residual std (actual−proj) shrunk toward a full-pool positional prior, BAND_Z-scaled, floored at 0; disagreement_ppr column null under one source. Calibration-gated (backtest_projection_consensus.py, exit 0): 25–75 coverage 51.4% on the 2025 answer key, BAND_Z=0.6 swept-tuned; per-player shrink beats a naive one-size band on stratum uniformity. New _analytics.stdev + data_layer write/read_projection_consensus. 2nd source scouted: ffanalytics (in-season live disagreement), ESPN (deferred historical).
    - Phase 2 archetype skew (§3 c3) — completes the spread band to full 3-component spec. compute_projection_consensus.py gains a Cornish-Fisher skew shift (SKEW_GAIN·(g/6)·(BAND_Z²−1)) on p25/p75 driven by the player's residual skewness shrunk to a positional prior (new _analytics.skewness, SKEW_SHRINK_K=8); p50 stays the borrowed center. Design fork resolved by the answer key: the projection's TD-dependence archetype does NOT track residual skew (measured), the player's own residual 3rd moment does. Because BAND_Z<1 the shift moves both breakpoints down (center sits above realized median). Gate extended to per-tail calibration + joint BAND_Z×SKEW_GAIN sweep → (0.55, 1.5): coverage 0.493, tails 0.247/0.261 (tail error cut 5×), exit 0. No schema change to data_layer (new skew_ppr/resid_skew columns pass through).
    - Phase 2 Production VOR (§4) — compute_production_vor.py → derived/production_vor_{season}.parquet, the first read that consumes the substrate. Per rostered player: ROS value = sum of borrowed weekly consensus centers over remaining weeks; anchored waiver line=0, normalized by pool spread (top−waiver); QB its own pool, flex-eligible RB/WR/TE share a pooled waiver line (from lineup_slots). Tall over as_of_week (roster-as-of-N, roster frozen wks 1–4, projection horizon wk 18). New data_layer write/read_production_vor. Gate (backtest_production_vor.py, exit 0): projected ROS tracks actual at corr 0.944 QB / 0.955 FLEX, VOR tiers monotonic (dead<mid<stud). Simplifications documented: pooled flex line ignores dedicated-slot scarcity; superflex latent; Market VOR + trade gap V4.
    - Phase 3 True Rank (§5, first half) — compute_true_rank.py → derived/true_rank_{season}.parquet, the first league-level read consuming the substrate. Per team: roster_strength = sum of the optimal-lineup ros_value (fill QB/RB/WR/TE+FLEX from the roster by ros_value, most-constrained slot first) → record-independent roster-strength rank + league-relative spectrum_pos + bench_value. Re-aggregates Production VOR (no new engine); the optimal-lineup greedy lifted from compute_team_leakage into _analytics as shared expand_slots/optimal_lineup (leakage imports them, behavior-preserving). Tall over as_of_week (roster-as-of-N inherited from the VOR slice). New data_layer write/read_true_rank; _as_of_slice gains an "all" sentinel for whole-frame re-aggregation through the seam. Slot-aware: a 2-elite-QB roster ranks by its one startable QB (verified — roster 9 holds a 310-pt QB, ranks 9th of 10). Gate (backtest_true_rank.py, exit 0): projected strength tracks the actual ROS ceiling (mgmt-independent optimal lineup on realized points) at Pearson 0.802 / Spearman 0.842 (freeze wk4, n=10, floor 0.60); strong half +261.7 ROS over weak. No UI (data+gate, like VOR).
    - Phase 3 Positional Depth (§6) — compute_positional_depth.py → derived/positional_depth_{season}.parquet, the 4th and last Phase-3 cash-in read (3rd VOR re-aggregation). Per (as_of_week, roster_id, fine position QB/RB/WR/TE): re-slices the borrowed ros_value/vor net of the position's dedicated starter_need (from lineup_slots; shared FLEX excluded → flex-worthy depth = surplus). Carries starter_value, surplus_value + surplus_startable (beyond-need vor>0), marginal_vor (last dedicated starter's VOR = gap indicator), spectrum_pos within each position cohort, advisory surplus/adequate/gap shape (evidence-first). One row per (team, position) even at zero count (body-count gaps visible). Tall over as_of_week (roster-as-of-N from VOR). New data_layer write/read_positional_depth. Lossless re-slice (per-pos rostered_value sums to team VOR ros_value). Gate (backtest_positional_depth.py, exit 0): per position, projected starter_value tracks actual ROS ceiling (top-need by realized pts) at QB 0.792 / RB 0.867 / WR 0.855 / TE 0.928, mean 0.861 (freeze wk4, n=10/pos, floor 0.50); top half +85.3 over bottom. No UI (data+gate). Closes the Phase-3 read set (4/4).
    - Phase 4 Bracket Odds (§5 bracket-math) — compute_bracket_sim.py → derived/bracket_odds_{season}.parquet, the bracket-math half of Posture (with True Rank = §5 complete). Per team weekly score dist (μ = optimal-lineup Σ center_ppr, σ = √Σ band_ppr²; starters independent), analytic per-matchup win prob Φ((μA−μB)/√(σA²+σB²)) via math.erf; standings as-of-N from actual results; Monte Carlo (numpy, fixed seed, 10k) over the real remaining schedule → playoff_odds, proj_wins/points, avg_seed, magic_wins. Enabled by raw Sleeper matchups existing for all 18 wks. Playoff config (REG_SEASON_END_WEEK=15, PLAYOFF_TEAMS=6) inferred from schedule — documented latent. New data_layer write/read_bracket_odds + read_season_matchups. Verified wk4: Σ playoff_odds=6.00 (hard invariant); deterministic. Gate (backtest_bracket_sim.py, exit 0, config-light): Brier 0.224 beats coin-flip; expected wins vs actual Spearman 0.756; top-6 by odds = 6/6 actual playoff teams (at the originally-inferred 6-team cut). numpy is the one compute dep. Simplifications: starter independence, Normal draw (no §3 skew), frozen-roster byes reduce μ. **[Superseded: the playoff config REG_SEASON_END_WEEK/PLAYOFF_TEAMS is now read from real league settings — 4 teams, not the wrong inferred 6; at the corrected 4-team cut the gate reports Σ playoff_odds=4.00 and top-4 by odds = 3/4 — see the league-settings build.]**
    - League settings (scoring + playoff) persisted + consumed — sleeper.py fetch-league-config pulls scoring_settings + playoff config from the /league object → data_layer write/read_league_settings (tall section/key/value) + read_scoring_settings/read_playoff_settings. transforms/_scoring.py dispatcher: scoring_profile ppr/half/std/custom; standard selects the canned projection column + nfl_stats actual expr; custom → recompute_custom_points() stub (raises; engine is the next project). Wired into compute_projection_consensus (scoring, byte-identical for this ppr league) + compute_bracket_sim/backtest (playoff via _playoff_config, injected, no hardcoded fallback). Real league: playoff_teams=4, playoff_week_start=16, profile=ppr. Corrects the sim's playoff cut 6→4 (Σ playoff_odds=4.00); all gates green. Standard PPR/half/std leagues now supported; foundation for the "any league" project.
    - Custom-scoring recompute engine ("any league" piece 1) — fills `_scoring.recompute_custom_points()` (was a stub that raised) with a **delta-on-canned-baseline** engine: `points_league = std_baseline (proj_pts_std/fantasy_points) + Σ(w_custom−w_std)·component`, exact for standard by construction. Same weights on `proj_*` + `nfl_stats` so residuals stay matched. Supports non-{0,.5,1} PPR, 6-pt pass TD, non-standard yardage/TD, position-conditional reception bonuses (TE premium `bonus_rec_te`/`_rb`/`_wr`/`_qb`); rejects (raises, names key) first-down / threshold-yardage bonuses (no projection component); turnovers/2pt carried in baseline (tolerance). `recompute_custom_points(scoring, side)` → `pl.Expr`; `projection_column`→`projection_points_expr`; `actual_points_expr` gains scoring; `compute_projection_consensus.compute(season, scoring=None)` injectable. New `backtest_scoring_recompute.py` (exit 0): equivalence (custom==canned on standard: actuals exact, proj ~0.01 rounding), exact custom deltas, rejection, end-to-end custom consensus (100% QB centers rise under 6-pt pass TD). No-regression: real-ppr recompute == on-disk consensus parquet frame-for-frame (downstream gates unaffected); VOR runs on a custom consensus. Custom leagues now run the whole read spine.
    - Any-league pieces 2 & 3 (project complete) — **roster-shape/superflex:** new shared `_analytics.position_pools(slot_rows)` derives swap/replacement pools from `lineup_slots` (positions sharing a multi-position slot pooled; key = broadest inducing slot). `compute_production_vor._pool_of` + `compute_team_leakage._cls` now use it (fixes the `SUPER_FLEX` latent + generalizes leakage swap classes); standard config byte-identical, superflex pools QB with flex. `backtest_roster_shape.py` (exit 0): no-regression frame-equal on vor/leakage/true_rank/positional_depth + synthetic superflex. **Division seeding (synthetic-gated latent):** `_seed_table` extracted from `compute_bracket_sim._simulate`, division-aware when a roster→division map is present (winners seeded ahead of wildcards) else flat (proven identical); `sleeper.py fetch-league-config` persists `settings.divisions`; `_division_map` None today (teams entity has no `division` col — rosters-endpoint population deferred). NOT validated on a real division league. **Also fixed:** the fixed-SEED bracket sim wasn't reproducible (polars group_by order + zero-score bye ties) — sorting schedule pairings + roster player lists restores determinism (shared `optimal_lineup` untouched). `backtest_bracket_sim.py` extended (exit 0): Brier 0.224/Spearman 0.756 unchanged + determinism + Σ-invariant + synthetic 2-division correctness.
    - ROS Outcome Shape (§2 quantitative skeleton — completes the player-read backend §1–§4) — compute_ros_outcome_shape.py → derived/ros_outcome_shape_{season}.parquet, tall over (as_of_week, roster_id, player). Bull/bear = the borrowed ROS centre (Production VOR ros_value, reused directly) ± BULL_Z·ros_sigma, floored at 0, where ros_sigma = √(Σ band_ppr² over the remaining schedule) — the §3 weekly band summed under weekly independence (compute_bracket_sim's documented assumption). New pure `_ros_sigma` (mirrors `_ros_values`, aggregates band²) + `_outcome_band`; ros_cv = sigma/centre (fragility), per-position spectrum_pos on the bull ceiling. Time decay emergent (shrinking horizon → tighter band; 0/142 σ grew wk1→wk4). Situation/security borrows the player_signal trust axis (security tier + direction/reliability) as structured evidence — the AI narrative + 1-10 roll-up is Phase 6. New data_layer write/read_ros_outcome_shape (mirrors the Production VOR tall block). Gate (backtest_ros_outcome_shape.py, exit 0): calibration — freeze-wk actual ROS in [bear, bull] = 0.835 (target 0.80±0.05), BULL_Z swept to 1.645 (above the normal 1.28 because weekly residuals are positively autocorrelated → realised ROS more dispersed than the independent sum); decision-relevant — actual ROS monotonic by ros_bull tercile (dead 58 < mid 126 < stud 206); bonus — non-stable players broke their bear floor 15.9% vs stable 9.8%. Symmetric-by-design (ROS-level skew deferred). No-regression (reads-only of the three source parquets). No UI (data + gate).
    - Manager Dossiers Phase A (§7 — cross-league acquisition + deterministic behavioral features; the credit-free substrate the Phase-B AI writer consumes) — 3 commits. (1) sleeper.py: fetch_teams persists owner_id (the user_id identity key it dropped; teams_2025 regenerated, additive); new _get_json (timeout + backoff-retry on transient/5xx, 4xx raise, optional throttle), all bare requests.get routed through it. (2) transforms/_manager.py (pure comparability + attribution helpers, reuses _scoring.scoring_profile; shared by fetch mode + transform + gate) + sleeper.py fetch-manager-activity <season> [--me] [--limit N] [--throttle S]: per manager, fan out to their comparable other leagues (same scoring/size/QB-structure/format — redraft-only V1, format tagged), ≤5 across current+2-prior biased to prior; classifies off the /user/.../leagues payload (carries scoring_settings+roster_positions+settings, verified) so no per-candidate fetch; persists incrementally per manager (replace-by-owner_id, recoverable/idempotent). New manager_activity_{season} — the FIRST cross-league/user-keyed entity (owner_id key; source_league_id/source_season as columns; league-marker + txn row kinds). (3) compute_manager_features.py → manager_features_{season} (per manager: FAAB aggression/budget-spent [completed waivers only], waiver/FA mix, success rate, churn, trade freq, positional lean of adds, signal-depth counts + depth_tier + is_primary); pure manager_features (injected constants); rate/lean features null when undefined (law 2, never fabricated 0). Gate (backtest_manager_features.py, exit 0 — internal consistency, behaviour has no answer key): comparability invariant (0 leaked, grounded on persisted target facts) + accounting round-trip (independent re-aggregation; fractions ∈[0,1]; shares sum 1) + signal-depth honesty (all profiled; zero-signal → null). Verified live 2025: 10 managers, 431 activity rows, real differentiation; depth honestly thin (recurring-league friend group). No AI/credits/UI. Phase B (Haiku dossier writer) next.
    - Corpus §0.5 — discovery, selection & the league registry (Improvement-Loop Track A; unblocks L0). New additive application/data/corpus/ package (discover.py + select.py + check_corpus.py + pure _corpus.py; 4 additive data_layer entities under snapshots/corpus/), all network via _http, all parquet via data_layer, no existing path/entity touched. discover.py = persisted/resumable/idempotent manager-keyed BFS (depth 2, reuses sleeper._manager_leagues + _manager.classify_league) → corpus_discovery.parquet. select.py = classification-narrow → inclusion filter + scoreability on a bounded pool (verdict-only persist, cache-backed; harvest is Session 4) → corpus_manifest.parquet, the registry L0 keys against; strata matched (product shape, tunes+gates, ≤60/season) / generalization (never_tune robustness set) / mine. check_corpus.py = internal-consistency gate, exit 0. Narrow-corpus decision (neighbourhood is 72% custom, superflex>1qb, dynasty>redraft — a distribution shift if pooled). Live: discovery 2,729 league-seasons (325 managers, frontier 6,937 = lower bound); manifest 319 rows (matched 179 / generalization 58 / excluded 80 / mine 2); split TRAIN 2023-24 · DEV 2022 (thin) · TEST 2025, 2020-21 = 0 matched; 39.2% of 2,045 custom leagues unscoreable (threshold-yardage + first-down bonuses — roadmap number, engine untouched); gate exit 0. **[§0.6 CORRECTED these numbers — a float32-tolerance bug in `scoring_profile`: six matched seasons not four, matched selected 221, unscoreable 45.4%/1,765, split TRAIN 2020-2023 · DEV 2024 · TEST 2025. See the §0.6 bullet below.]**
    - Session 0.6 — `_scoring` float32 tolerance fix (a live engine bug the corpus caught) + corpus re-select. `scoring_profile` compared weights at `_TOL=1e-9`, but Sleeper serves float32 (`0.1`→`0.10000000149…`, drift ~1.5e-9), so every drifted standard PPR league was misclassified `custom` — thinning §7 `is_comparable` (live) and zeroing 2020-21 matched (the corpus "clean zero"). Fix: `_weights_match`(round-4) at the classifier + `_TOL`→1e-6 for the numeric guards; over-loosening guard holds (genuine custom Δ0.01 still `custom`); 4 guard tests in backtest_scoring_recompute. No-regression PROVEN (real 2025 = clean-ppr): all 9 backtests --season 2025 byte-identical before/after, compute_projection_consensus(2025) value-identical to on-disk. Re-selected the corpus offline (select.py re-classifies from persisted scoring_settings_json, zero API, no re-crawl). Corrected: matched-eligible SIX seasons not four (2020:10/2021:19/… total 261→320); manifest 319→365 rows, matched selected 179→221; unscoreable 39.2%/2045 → 45.4%/1765 (denominator held 280 mislabelled-standard leagues); split TRAIN 2020-2023 · DEV 2024 · TEST 2025 (2020-21 thin ⇒ league-wise k-fold within train). check_corpus exit 0 with a new HARD floor (a suspiciously-empty train season now FAILS — "a clean zero is a bug" encoded) + a SOLID floor flagging THIN seasons. §7 hypothesis: NO improvement on the real league (0/10 managers gained comparables, manager_activity byte-identical before/after) — the thin friend-group §7 read is genuine, not the bug; dossiers not regenerated. Correction notes added to LEAGUE_CORPUS + SPIKE_CORPUS_FINDINGS (marked corrected, not rewritten).
    - Manager Dossiers Phase B (§7 — the API-key-gated Haiku dossier writer; §7 COMPLETE) — the project's FIRST AI-layer code. New application/ai/ module (distinct from the polars transforms; parquet I/O still via data_layer, the Anthropic call is external like a fetcher's HTTP). (1) ai/client.py — the isolation seam: api_available() gates on a real config.ANTHROPIC_API_KEY (absent/placeholder/non-sk-ant → locked, no anthropic import to check); generate_dossier() is the ONE place that knows how a request reaches the model (synchronous messages.create, Haiku 4.5, no thinking/effort, tolerant json.loads NOT messages.parse — SDK-version-safe; returns (dossier, usage)) — a Batch path swaps here only. ai/dossier_prompt.py — pure: stable system prefix (fixed 7-key JSON schema + tendencies-not-verdicts guardrails) + per-manager user prompt (blindspot framing for is_primary / exploitable-edge for opponents) + hardcoded zero-signal "no intel" dossier. (2) ai/write_manager_dossiers.py (compute/run/--season/--force) → manager_dossiers_{season} (first AI-written entity; one row per owner_id: structured fields + is_primary + signal-depth echo + model/generated_at/is_zero_signal): per manager, zero comparable leagues ⇒ hardcoded (no API); else prompt→generate→validate schema; synchronous sequential (caching off — ~347-token prefix below Haiku's 4096 min); run-once-per-season guard; key-gate clean exit. New data_layer write/read_manager_dossiers. (3) ai/check_manager_dossiers.py — internal-consistency gate (no API, reads persisted only): coverage + schema completeness + depth-echo-matches-features + zero-signal honesty (exit 0). Design decision: synchronous not Batch (≤16 managers once/season → 50% batch discount is noise; concurrent batch can't share a prompt cache; seam lets Batch swap in later). Verified live 2025: 10 dossiers, 10 Haiku calls, ~$0.025, gate exit 0; primary=blindspot, opponents=exploitable-edge, 10/10 confidence notes cite the real txn count. Guards unit-tested credit-free (zero-signal skips API; locked-key refuses even with --force). No UI.
    - 710 backend-audit fixes (structural #1 + hygiene #5/#6/#7) — `application/` made a proper Python package: `__init__.py` in the 6 dirs + root `pyproject.toml`; every bare sys.path-dependent import rewritten to absolute package form and all 56 `sys.path.insert` lines across 31 files deleted (zero remain); scripts run as `python3 -m application.<pkg>.<module>` from the repo root (`-m` puts cwd on the path — no editable install); lazy `_import_manager_helpers` → top-level package import; ~30 usage strings + the two doc call-sites + the launchd plist (`-m` module, WorkingDirectory=repo root) + README updated. Hygiene: config.example gains SLEEPER_LEAGUE_ID + drops dead LEAGUE_TYPES/EXCLUDED_LEAGUES; requirements sheds unused pandas/nfl_data_py; bracket figure reconciled to top-4=3/4. Behavior-preserving (all backtest gates pass via -m, identical numbers; byte-compiles clean). Deferred: #2 scaling (no-op migration trigger), #3 §1 quality axis (net-new empirical-weighting transform), #4 §2 preseason anchor (blocked — no ADP source fetched). Post-merge: reinstall the launchd plist.
    - 710 audit #4 (§2 ROS preseason anchor) — overturns session-1's "#4 blocked on data": the ADP source was `nflreadpy.load_ff_rankings` (already a dependency). `fetchers/adp.py` fetches the historical FantasyPros preseason redraft-overall board (latest full-skill-board pre-kickoff snapshot/season; ecr/best/worst/sd + positional rank; id-bridged `fantasypros_id`→sleeper via ff_playerids, cbs/yahoo all-null; `adp_preseason` entity, 2020–2025, top-150 150/150). `compute_adp_points_curve.py` fits per-position `pos_ecr_rank → realized-points` floor/center/ceiling (P10/P50/P90 over a rolling ±3-rank window, isotonic non-increasing; drafted-never-produced = 0.0 floor signal; trained 2020–24, 2025 held out = leak-free; `adp_points_curve` entity; +`_analytics.quantile`). Historical realized points via existing `nfl_stats` backfill 2020–24 (sanctioned data-layer path — no transform hits nflreadpy). Anchor blended into `compute_ros_outcome_shape` bull/bear via horizon-decaying `w_N = ANCHOR_W·(remaining/total)`; `ros_center` stays borrowed (law 3); undrafted/uncovered degrade to the pure-projection band; +adp/anchor evidence cols. Joint `BULL_Z×ANCHOR_W` re-sweep (gate imports shipped `_preseason_anchor`/`_blended_band`; objective |cov−tgt|+|tail imbalance|) → (1.44, 0.25): freeze coverage 0.744→0.817, tails 0.195/0.061→0.091/0.091, gate exit 0, ros_bull terciles 58<127<205. Limitation: freeze bounds tested cutoffs to N=1..4 (early/prior-heavy) — decay's late tail by construction. Also re-scoped #3 (§1 quality) smaller: `load_ff_opportunity` ships the empirical expected-points model → consume-and-re-score, not fit-your-own-weights.
    - 710 audit #3 (§1 Quality axis) — CLOSES the 710 audit (7/7). `quality_rate` was `xtd_g/opp_g` (nflfastR `td_prob`, TD-only, ungated); now = **expected fantasy points per opportunity** from ffverse's `ff_opportunity` component model. `nfl_stats._load_ff_opportunity` joins the `*_exp` components (gsis-keyed, null-id rows filtered; REG weeks); `xtd` retired, `redzone_touches` kept as companion; latent bare `import audit_join` (package-refactor #1 miss) fixed. New `_scoring.expected_points_expr` re-scores the components from-scratch under league settings — exact (all components exposed), reproduces ffverse's `total_fantasy_points_exp` under PPR to ±0.02, scores first-down leagues too. `compute_player_signal`: `quality_rate = exp_pts_g/opp_g` (value per chance, separate from Volume), `point_correlation` → weekly actual-vs-expected full points, new `luck` = recent − expected ppg; scoring applied at the consumption layer. Gate (`backtest_player_signal.py`, exit 0): new 3rd verdict — quality_rate (exp_ppo) forecasts ROS realized efficiency at MAE 0.311 vs 0.506 recent-realized; core still beats naive 13.2%, spike<sticky. **Core-engine upgrade tested & REJECTED by the answer key**: shrinking the spike forecast toward exp_ppo lost to the positional mean at every SHRINK_K (K=6: 2.699 vs 2.599) — points-forecasting regresses to the *population*, exp_ppo (same recent weeks) too correlated with realized ppo to pull that way; kept the validated positional-mean prior (the model serves the §1 axis, not the forecast). No UI (data + gate).
    - §2 Player-News Collector (aggregation half of the ROS AI-interpretation layer, Phase 6) — `fetchers/news.py`, a live/scheduled RSS collector → new `player_news` entity (`snapshots/news/player_news.parquet`; grain = one row per news-item × resolved player; writer append-only-of-new by `item_id`, idempotent; compact items only — headline/summary/url + `collected_at`, never article bodies → url+date = Wayback recall path). National feed registry (source_type stored so team beats drop in later); `_get_feed` timeout+backoff; **resolution** = exact full-name match vs the 967 active-rostered (`team`-not-null) skill players (0 collisions) + defensive team-mention disambiguation (`match_confidence` exact_full/disambiguated; ambiguous skipped — law 2); incremental per-feed snapshot with per-feed isolation; entry points snapshot/feeds/resolve-test/check (synthetic resolver self-check). +feedparser dep + `com.fantasyai.news-snapshot` launchd plist (5am ET). Live-acquired like manager_activity (forward pipeline, NOT tied to frozen-2025). Verified live: 5/5 feeds, 151 entries→48 items→66 rows, idempotent, dead-feed isolation, check PASS, 0 false positives. Next: the §2 on-demand AI synthesis (one lazy cached per-player call → headlines + bull/bear blurb + confidence).
    - §2 News pipeline REWORK — team-centric collection (Stage A), supersedes the v1 player-news collector — `fetchers/news.py` reworked to collect per-NFL-team from **3 native RSS sources/team** (SB Nation `/rss/index.xml` grounded + FanSided `/feed/` player-flavored/noisier + official `<team>.com/rss/news` authoritative/PR); all **96 feeds (32×3) validated live** (96/96 ok, 5021 articles). Nationals dropped (league-level); SI/FanNation ruled out (no native per-team RSS — 0 autodiscovery, all paths 404). New data_layer **`team_news_raw`** entity (grain = one row per **article**; **stores feed-provided content** for the extraction — reverses v1's headline-only rule; feed-provided only, no scraping; append-only-of-new by `article_id`, idempotent). Player resolution moved out of collection into Stages B/C (resolver retained: `build_index`/`resolve_players`/`_TEAM_ALIASES`). Per-feed isolation + backoff + per-team volume report (Stage-C thinness-tripwire input) + resilience-floor flag; `source_type` per article for weighting; `player_news` left as legacy. Verified: 96/96 feeds / 32 teams / 5021 articles, 0 dup titles, dead-feed isolation, resolver `check` PASS, `published_at` 100%. Stage A of the 3-stage pipeline (B = weekly AI claim-extraction → `team_news_dossier`; C = per-player slice + thinness tripwire + retention).
    - §2 News pipeline Stage B — weekly per-team AI news synthesis → `team_news_dossier` (the interpretation half; the project's 2nd AI-layer read after §7 dossiers) — new `application/ai/`: `news_prompt.py` (pure; situation/security schema + cluster-across-sources + attribution guardrails), `write_team_news_dossier.py` (windows the raw store `WINDOW_DAYS`=14/cap 60 → 1 Haiku call/team → validate → deterministic on-team id resolution; run-once-per-week, `--force`, `--team`), `check_team_news_dossier.py` (internal-consistency gate). `client.py` refactored (`_raw_call` shared seam + `generate_claims` array path; `generate_dossier` behavior-identical). New data_layer **`team_news_dossier`** (one growing file; grain = one claim row per (season,week,team); replace-by-(season,week,team), idempotent). Per claim: scope (player/position_group/unit) / subject / claim_type / **`basis`** (official/reported/opinion — opinion never laundered into fact) / attributed `note` / direction (positive/negative/neutral/**mixed**) / salience / cited `source_article_ids` + `source_types` (clustered; source diversity = trust). Skill-only (V1): player claims QB/RB/WR/TE resolved via a **team-restricted** index (gate caught + fixed a cross-team-id bug); all defensive news condensed into ONE `defense` unit note (game-script context; pre-banked for later). Verified live 2026 wk0: 32/32 teams, 317 claims, ~$0.46; gate PASS (coverage/schema/grounding/on-team-resolution/zero-signal); 168/186 player claims resolved. Next — Stage C (per-player slice by inheritance + thinness tripwire + raw-content retention).
    - §2 News pipeline Stage C — per-player slice by inheritance + thinness tripwire + raw-content retention (COMPLETES the 3-stage news pipeline A→B→C) — a **deterministic reshape** (no AI), so the gate is **hard**. New data_layer **`player_news_slice`** entity (`snapshots/news/player_news_slice.parquet`; grain = one inherited-claim row per (season,week,player,claim); write replace-by-(season,week)). `transforms/compute_player_news_slice.py`: each on-team skill player (whole NFL skill pool ~967, forward/league-agnostic) inherits his **own** resolved `player` claims + his **position_group** claims (subject normalized to his skill position, OR team-wide offensive context — `offense`/`offensive line`/coaching-scheme → all skill players; unmapped subjects dropped + reported as Stage-B drift) + his team's **unit** claims (`offense` + the condensed `defense` note) from `team_news_dossier`. Thinness tripwire as columns: `signal_tier` (rich=≥1 own / thin=only inherited / none=nothing) + `n_own_claims`/`n_inherited_claims`/`team_news_volume`; a player who inherits nothing gets ONE `is_empty` honest-zero row (like positional_depth's zero-count rows). `transforms/check_player_news_slice.py`: HARD gate — **independently recomputes** each player's expected inherited set from the dossier+registry (does NOT call the compute) and demands an exact multiset match incl. inheritance tag + provenance; + coverage/identity/thinness-honesty/zero-signal/retention-safety. **Retention:** `data_layer.prune_team_news_raw_content` + `fetchers/news.py prune [--dry-run]` (`RETENTION_DAYS=28` > the 14d synthesis window) nulls raw article `content` older than the cutoff, KEEPS the row + `article_id`/`title`/`url`/`published_at` + the derived claims (which cite `article_id`, never the text); idempotent. Verified live 2026 wk0: 967 players → 3058 rows (own 168 = the resolved player claims / pg 626 / unit 2264; tiers rich 160 / thin 807 / none 0); eyeballed a TE inheriting his own claim + team offense but NOT the WR-room claim + a team-wide o-line claim reaching all 4 positions; slice gate exit 0. Prune: dry-run 1243/5021 rows → live kept all 5021 rows (0 null id/url), nulled all old content, kept the 28d window (3748 with content), idempotent; both gates exit 0 post-prune. The §2 synthesis (QUEUED #2) now has its news input: a player's inherited `player_news_slice`. No UI (data + gate). Next — QUEUED #1 (Daily-collector reliability).
    - Daily-collector reliability — shared `_http` resilience layer + collector registry + coverage gate (QUEUED #1) — separation of concerns: retry/backoff/throttle/per-item isolation now live ONCE in `fetchers/_http.py`, so every collector shares a consistent resilient fetch process. **3 commits.** (1) `_http.py`: `get`/`get_json` (bounded timeout + exponential-backoff-with-jitter retry on TRANSIENT failures — timeouts/conn-errors/5xx; a 4xx raises immediately) + `set_throttle` (process min-gap; the manager-activity fan-out raises it) + `isolate` (per-item catch+log+continue). All three HTTP callers migrated: `sleeper._get_json` → behaviour-identical thin wrapper (`set_throttle` re-exported); `news._get_feed` → `_http.get` + `_http.isolate`; **`leaguelogs._get` → `_http.get_json` (ADDS retry) + `snapshot()` per-item isolation** (ADDS it — the fix for the audit's ~7 transient-fail + "dynasty profiles drop first" days). (2) `fetchers/run.py`: declarative collector REGISTRY (leaguelogs + news — the banked daily series; NOT sleeper = on-demand) with cadence + coverage-shape per collector, + a `run <name>|--all|--list` dispatcher (uniform process → post-run freshness); the **meter stays external** (launchd → GitHub Actions calls this same dispatcher — nothing wasted). `fetchers/check_collectors.py`: network-free coverage/health gate — leaguelogs STRICT daily coverage (per-day distinct profiles vs max-seen full day), news RECENCY (append-only); HARD criterion is a recent window (default 7d, excl. today) so permanent powered-off gaps don't fail forever; `--today` monitoring; UTC-dated to match the collectors. (3) Docs. The **off-laptop host** (the ~8 powered-off days — a host problem retry can't fix) stays **deferred to the deployment decision** (GitHub Actions the lead: collects + publishes). Verified: network-free retry/4xx/isolate self-test (PASS); live no-regression on all 3 fetchers; isolation proof (2 forced-dead leaguelogs profiles → the 3 good ones collected + the run COMPLETED reporting "2/5 failed (isolated)" instead of aborting); gate reproduces the audit (leaguelogs full-span 28 complete / 65% / 72% any-data — matches the documented 63%/71%) + flags the real recent gap (07-05 partial → FAIL/exit 1; `--since 3` clean → PASS/exit 0). Next — QUEUED #2 (§2 ROS synthesis call).
    - §2 ROS Synthesis — the per-player AI interpretation call (QUEUED #2; completes the §2 read, the last mile compute_ros_outcome_shape deferred to Phase 6) — the project's 3rd AI-layer read, reusing the `ai/client.py` seam. New `application/ai/` trio + a `data_layer` entity. (1) **`ros_synthesis_prompt.py`** — the pure, editable prompt (`system_prompt()` + `user_prompt(ctx)` + `SYNTHESIS_KEYS` + `zero_signal_synthesis()` + plain-language translations of the internal security/direction labels). (2) **`write_ros_synthesis.py`** — per player: `assemble_player` gathers his `player_news_slice` claims + `ros_outcome_shape` anchor (by id, from `--anchor-season`) + Sleeper injury/depth facts → one `client.generate_dossier` Haiku call → `_validate` (grades 1-10, notes non-empty, headline ids ⊆ the slice, confidence vocab) → row. Modes: `run` (write, run-once superset guard by (season,week,player), `--force`), `--preview` (print output), and the **no-AI** `--render` (print the exact assembled prompt) / `--replay REPLY.json` (run a canned reply through validation) — both need no key/no cost, the prompt-iteration loop. Zero-signal (no anchor AND no news) → hardcoded row, API skipped. (3) **`check_ros_synthesis.py`** — internal-consistency gate (no answer key): coverage / schema / grounding (headlines trace to the slice) / confidence honesty (thin or no-anchor ⇒ not 'high'; zero rows are clean fallbacks) / data-flag honesty + a soft high-precision prose-leak scan. New **`data_layer` `ros_synthesis`** entity (`snapshots/derived/ros_synthesis_{season}.parquet`; grain one row per (season,week,player); replace-by-(season,week,player)). Output columns fully separable: `bull_grade`/`bear_grade`/`situation_grade` (Int, independent axes — no ordering) each with its `*_note`, `headlines` (List(Struct{text, source_article_ids})), `confidence`/`confidence_note`, availability flags (`has_ros_anchor`/`has_news`/`signal_tier`/`n_news_claims`), anchor carries + `anchor_is_prior_season`, `news_content_hash` (future on-demand-cache seam), provenance. **Grade convention (with the PM):** 10=best on all three; bull hard-anchored to a caliber bucket (elite→9-10 … fringe→1-2, full range) and decoupled from downside (that lives in bear/situation). **Prose discipline:** notes are natural manager language; the substrata (percentile/tier/projection/trend) drive the grades but are banned from the prose; attributed news stays. **Season/time-world honesty:** keyed by the news (season,week); a differing anchor season is flagged PRIOR-SEASON, never silently fused (the STATUS caveat — 2026 news × 2025 anchor). Verified live 2026 wk0: 16 players across all regimes (Chase bull 9 … Kraft/Rodriguez 3-4; ~$0.07), gate exit 0, guard tests (run-once / locked-key refusal / partial run hits the API only for the new player / zero-signal skip) all clean. Front-end wiring + the browser on-demand runtime + validated same-season fusion deferred with deployment (no server; key server-side). No UI (data + gate + prompt tooling).
    - §4 Market VOR + Production−Market trade gap — the market-value twin of Production VOR (completes §4; the primary remaining backend read, and the un-backdatable POC piece built on CURRENT 2026 data). Per law 3 borrows the LeagueLogs market value + adds only the decision layer, reusing the shared engine (`_analytics.position_pools`, `compute_production_vor._pool_lines`/`_vor`/`_roster_as_of`, `round1`) — **no new VOR math**. **2 code commits + docs.** (1) New `data_layer` **`market_vor`** entity (`snapshots/derived/market_vor_{season}.parquet`; grain one row per (snapshot_date, rostered skill player); **tall over the market's `snapshot_date` axis** — the analog of Production VOR's `as_of_week`, banking the un-backdatable series; `read_market_vor(season, snapshot_date=None)` → latest banked day) + `compute_market_vor.py`: filters to the format-matched profile **`redraft-1qb-12t-ppr1`** (redraft/1QB/full-PPR — resolves the §4 open prereq flag; 12t-vs-our-10t a documented non-issue since the waiver line is from OUR roster/available split), joins **position from the Sleeper registry** (feed carries only `position_rank`), resolves the frozen-2025 roster (`_roster_as_of` at the freeze week), per pool sets waiver=best-available / top=best value → `market_vor=(value−waiver)/(top−waiver)`; QB pool + pooled flex line identical to Production VOR. The **Production−Market gap folded in**: joins the frozen Production VOR slice → `trade_gap=market_vor−production_vor` + `is_cross_time`/`market_season`/`production_as_of`/`has_production_vor` as **first-class columns** (the market is CURRENT 2026, rosters/production are 2025 → cross-time by construction, never fused — the `anchor_is_prior_season` precedent; POC/architecture validation, NOT a live trade call, until the season rolls to 2026). **Purely additive** — nothing in the front end or any existing transform reads it, so the current-vs-2025 split does NOT affect app functioning. (2) **Internal-consistency gate `check_market_vor.py`** (no answer key at the 2026-offseason freeze — the `backtest_manager_features`/`check_ros_synthesis` regime): recompute-match (persisted == shipped `compute()`) / VOR algebra (waiver≤top, reproduces (value−waiver)/spread within a spread-aware rounding tol, top≈1.0) / pool integrity (= Production VOR's pools) / profile+coverage (single profile, no picks, ≥95%) / gap honesty (all cross-time flagged; `trade_gap` null iff no production row else exactly market−production). Verified live 2026 offseason: **31 snapshots → 5270 rows**, 170/171 frozen roster priced (99.4%), 248 no-production rows null (law 2), gate exit 0; Production VOR gate unaffected (0.944/0.955). No UI (data + gate). Next — front-end surfacing of the gated forward reads (Phase 4).
    - Manager Dossiers — removed the API-key gate (now an **included AI run**, not opt-in) — the §7 dossier run is cheap (~10 Haiku calls / ~$0.025 / once per season) and now ships as a standard product AI read using the app owner's key (in the gitignored `config.py`, never user-supplied). Dropped the `client.api_available()` LOCKED early-return in `write_manager_dossiers.run()` so the writer always executes; the **shared `client.api_available()` seam is untouched** and the other two AI writers (`write_team_news_dossier`, `write_ros_synthesis`) stay key-gated. Unrelated guards unchanged (run-once-per-season, zero-signal API skip). Docstring + `TECHNICAL_ARCHITECTURE.md`/`READ_BUILD_ORDER.md` reworded from "API-key-gated / key-gate clean exit". No key-storage change (key stays out of git). Docs-and-one-writer change; `check_manager_dossiers.py` gate unaffected.
    - Gridiron front-end — Foundation + Players slice (first front-end surfacing of the gated reads; 3 commits) — recreates the Claude-Design `Gridiron` handoff (`scope docs/`, `DATA_CONTRACT.md`) in the real React+Vite+DuckDB-WASM app, Web-first, new-shell-with-placeholders. (1) Gridiron design system (`styles.css` tokens — violet brand + reserved 5-color posture palette, Archivo/IBM Plex Mono) + 4-surface app chrome (`App.jsx`: brand + league switcher via new `queries.loadLeagueMeta` deriving `10-tm · PPR · 1QB · 3-1` from teams/league_settings/lineup_slots, segmented tabs with `icons.jsx` glyphs, week selector reused, `Placeholder.jsx` for League/Matchups/Teams; old League/Team panels retired from the shell). (2) Players table — `queries.loadPlayers(asOfWeek)` joins `production_vor` (PROD VOR, default sort) + `market_vor` (MKT VOR, cross-time) + `ros_synthesis` (bull/bear/situation grades, sparse) + season identity on `sleeper_player_id`; `Players.jsx` VOR-anchored sortable table + position filter + is_me badges + point-in-time `Gate`; Available/waiver DEFERRED (no FA-pool entity). (3) Player card — shared `charts.jsx` (Sparkline/TrendLine/GradeBar/RangeGauge) + `queries.loadPlayerCard()` → `PlayerCard.jsx`: Value·VOR series + BUY/HOLD/SELL lean off `trade_gap` (POC-gated cross-time), Opportunity from `player_signal`, ROS Outcome Shape from `ros_synthesis` (grades/notes/confidence, prior-season flagged); honest empty states. `db.js` registers production_vor/market_vor/ros_synthesis/league_settings (public/data symlinks added). All new data access through the `queries.js` seam. Verified live 1280px (browser preview): real players + sort/filter/is_me, full Player card (Gibbs ROS-empty; Hurts full ROS 8/6/6 + confidence + prior-season flag), no console errors. Next — Manager Dossier slice, then Teams/League/Matchups; + mobile pass + free-agent value read (unblocks Available/waivers) + roster-wide ros_synthesis batch.
    - Gridiron front-end — Teams cluster: Teams standings + Team detail + Manager Dossier (2nd front-end slice; 3 commits) — continues the `DATA_CONTRACT` build (§4.4/§4.5/§4.8). New pure `src/posture.js` = the §5 posture rule (`derivePosture`, `BAND=9`/`LEVEL_CUT=60`, `POSTURE_TONE`) in ONE home, reused by the Teams chips now + the League posture MAP later. (1) Teams standings — `queries.loadStandings()` assembles per team the real record + all-play "true record" (reusing the `loadTeamDetails` all-play loop) + `bracket_odds` playoff % (0–1 fraction ×100) with its weekly series for the trendline + the derived posture; `Teams.jsx` sorts by odds (rank · team+YOU · record · true rec · posture chip · playoff % · odds sparkline); `bracket_odds` registered in `db.js`. (2) Team detail — `loadTeamDetail()`: 4 stat blocks (record, all-play true rec, playoff %+seed, pts/wk), positional depth per QB/RB/WR/TE (`positional_depth` starter value + league spectrum + rank + SURPLUS/EVEN/GAP shape) via a new `DepthBar` mark, roster starters/bench with each player's Production+Market VOR weekly series behind a PROD/MKT toggle (MKT cross-time POC); `TeamDetail.jsx` + a Manager Dossier button; the this-week matchup bar deferred honestly to the Matchups slice (needs `bracket_sim`), not fabricated; `positional_depth` registered. (3) Manager Dossier — `loadManagerDossier()` reads the `manager_dossiers` row (already carries the feature counts, no 2nd fetch); `Dossier.jsx` = headline + 5 tendency fields + Signal-Depth footer (deep/moderate/thin → HIGH/MED/THIN + counts + confidence note) + provenance; `is_zero_signal` → honest "no intel"; `manager_dossiers` registered. `App.jsx` gains a detail nav-stack (push/pop) for correct multi-level Back (team → player, team → dossier); Teams rows drill in. All new data access through `queries.js`; views pure renderers. Verified live 1280px: standings + posture chips + trendlines, week switcher replays to wk2, team detail blocks/depth/roster toggle + player drill + Back, Bski dossier all 5 fields + MED badge, full Back chain; numbers match parquet; console clean. Next — League slice (Your Race/Playoff Picture/Posture MAP/Positional Talent off bracket_odds+true_rank+market_vor), then Matchups; + mobile-responsive pass + free-agent value read.
    - Gridiron front-end — League surface: Your Race + Playoff Picture + Posture Map + Positional Talent (3rd front-end slice; 3 commits) — the "whole league at a glance" (DATA_CONTRACT §4.2). Leans on the Teams-cluster `loadStandings` (one source for records/odds/posture). (1) Your Race + Playoff Picture — new `queries.loadLeague(asOfWeek)` composes `loadStandings` with the REAL playoff cut + team count from `league_settings` (`playoff_teams=4`, not the prototype's 6); `League.jsx` renders the full-width Your Race band (playoff chance + posture chip, Seed N of 10, "top 4 advance", magic number via `magicLine` off bracket_odds magic_wins/remaining_games) and the 3-col dashboard, Playoff Picture in col 1 (teams by odds, YOU, magic sublines, posture-toned odds trendlines, PLAYOFF LINE after seed 4); the this-week head-to-head + win% deferred honestly to Matchups (unsurfaced bracket-sim win prob), a note not a fake bar. (2) Posture Map — an SVG well reusing the standings: X=playoff odds, Y=all-play % inverted (the §5 shipped axis, not `true_rank`), quadrant tints + dashed on-pace diagonal + posture-palette corner labels, one dot/team colored by posture (mine ringed), dot→Team detail. (3) Positional Talent — new `loadPositionalTalent()` sums each team's positive `market_vor` per position at the latest market snapshot, ranked per position; QB/RB/WR/TE toggle + bars + the cross-time POC note (2026 market × 2025 roster, the locked decision); not week-parameterized (market is current, doesn't replay); Waiver Wire strip deferred (no free-agent pool entity in V1). `App.jsx` renders League for the league tab; NO db.js change (bracket_odds/market_vor/league_settings already registered). Seam discipline kept (all data access in `queries.js`; views pure). Verified live 1280px: Your Race 87%/Riding luck/Seed 3 of 10/top 4/Clinch in 6 of next 11; Playoff Picture Bski 91%→1% with the line after seed 4; posture dots placed+colored (Bski contender, my Tet riding-luck), dot→Team detail; talent QB toggle re-ranks (Won't you be my Naber 1.0 / Tet Lasso YOU 0.9, matches parquet); week switcher replays to wk2 (Your Race 35%, picture reshuffles, dots move) while talent stays constant (current market — honest cross-time); Playoff-row + posture-dot → Team detail → Back; console clean on a fresh load. Next — Matchups slice (slate + win prob + score-range bands, off `bracket_sim` + `projection_consensus`); + mobile-responsive pass + free-agent value read.

> not yet built
    >> backend
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - production front-end — React + DuckDB decided; Power Rankings panel built + deepened
          (team drill-down drawer with all-play, efficiency, weekly scoring, two spectrums).
          Remaining: more panels (per the Build Order below), deployment.

## Current build target

> **✅ §4 Market VOR + Production−Market trade gap — DONE (2026-07-12).** The **primary remaining backend
> read** and the only one buildable NOW rather than blocked at the freeze. The market-value twin of
> Production VOR: the same waiver=0 ÷ pool-spread VOR (reuses the shared `position_pools` / `_pool_lines`
> / `_vor` engine — no new math, law 3) computed on the borrowed LeagueLogs `value` for the
> **format-matched** profile `redraft-1qb-12t-ppr1` (resolves the §4 open prereq flag; 10-vs-12-team is a
> documented non-issue — the waiver line comes from our own roster/available split, not the profile).
> New `data_layer` `market_vor` entity (`derived/market_vor_{season}.parquet`, **tall over the market's
> `snapshot_date` axis** — banks the un-backdatable series in derived form); `compute_market_vor.py`
> (position joined from the Sleeper registry — the feed carries only `position_rank`); the
> Production−Market **gap folded in** (`trade_gap = market_vor − production_vor`). **Time-world honesty
> (the crux):** the app is frozen at 2025 wk4 but the market is **current (2026 offseason)** and can't be
> backdated, so the gap is **cross-time by construction** — every row carries `is_cross_time` +
> `market_season` + `has_production_vor` as first-class columns, never silently fused (the
> `anchor_is_prior_season` precedent). **Purely additive** — nothing in the front end or any existing
> transform reads it, so the current-vs-2025 split does NOT affect app functioning; it's the trade layer
> banked/wired for the eventual surface. Internal-consistency gate `check_market_vor.py` (no answer key
> at the freeze — the market has no future truth to grade against here): recompute-match / VOR algebra /
> pool integrity / profile+coverage / gap honesty. Verified live: 31 snapshots → 5270 rows, 170/171
> frozen roster priced (99.4%), gate exit 0, Production VOR gate unaffected (0.944/0.955). **The gap is
> POC/architecture validation, NOT a live trade call** until the season rolls to 2026 and production is
> recomputed there (at the freeze the largest gaps are cross-time + 1QB-pool-compression artifacts —
> e.g. "sell all your QBs" is noise, exactly what `is_cross_time` warns against). **Next — front-end
> surfacing of the gated backend reads** (Phase 4).
>
> ---
>
> **✅ §2 team-news pipeline (rework) — COMPLETE (2026-07-11).** All three stages shipped:
> **A collection** (`team_news_raw`) → **B weekly AI synthesis** (`team_news_dossier`) → **C per-player
> slice by inheritance** (`player_news_slice` — each skill player inherits his own `player` claims + his
> `position_group` claims + his team's `unit`/`defense` claims; + a **thinness tripwire** `signal_tier`
> for law-2 confidence honesty; + **raw-content retention** — `news.py prune`, `RETENTION_DAYS=28`, nulls
> old `team_news_raw.content` keeping row+link+claims). Deterministic reshape, **hard** round-trip gate
> (exit 0). The §2 synthesis (QUEUED #2) now has its news input. **Scheduling handoff (now deferred with
> the host):** QUEUED #1 built the `run.py` dispatcher + resilience layer, but wiring `news.py prune` +
> the weekly `write_team_news_dossier`/`compute_player_news_slice` into the meter (launchd → GitHub
> Actions) lands with the deployment/off-laptop-host decision.
>
> ---
>
> **✅ QUEUED #1 — Daily-collector reliability — DONE (2026-07-12).** Shipped the **portable** resilience
> layer (nothing wasted by the later hosting call): **`fetchers/_http.py`** — one shared
> retry/backoff/throttle/**isolation** path; all three HTTP callers routed through it (`sleeper` behaviour-
> identical, `news`, and **`leaguelogs` gained the missing retry + per-item isolation** — the fix for the
> audit's 63%/71% coverage). **`fetchers/run.py`** — a collector REGISTRY + `run <name>` dispatcher
> (cadence declared per collector; the **meter stays external**). **`fetchers/check_collectors.py`** —
> the coverage/health gate (leaguelogs strict daily coverage, news recency, `--today` monitoring;
> reproduces the audit + flags recent gaps). See the most-recent build for the full record.
>
> **Deferred — decide WITH web hosting (NOT done here):** the **off-laptop host** that closes the ~8
> powered-off days (a host problem retry can't fix) + where the canonical parquet lives. A static web
> deploy has no compute, so a scheduled runner — **GitHub Actions the lead** — both collects *and*
> publishes the parquet, **calling the `run.py` dispatcher**: the collector host is the same decision as
> Deployment. **Interim (cheap, still open — operator action):** install the written-but-unloaded
> `com.fantasyai.news-snapshot` plist + multi-fire both launchd jobs so the laptop only needs to be awake
> once. (Also still to wire into the meter: the weekly `write_team_news_dossier` + `compute_player_news_slice`
> + daily `news.py prune`.)
>
> **✅ QUEUED #2 — §2 ROS Synthesis — DONE (2026-07-12).** The AI interpretation half of §2 (Phase 6),
> completing the §2 read. Per-player Claude call (`application/ai/write_ros_synthesis.py`, reusing
> `ai/client.py`) fusing the `ros_outcome_shape` anchor + the `player_news_slice` news + Sleeper facts
> → bull/bear/situation 1-10 grades (each with a prose note) + grounded headlines + a confidence flag,
> persisted to the structured `ros_synthesis` entity; pure editable prompt (`ai/ros_synthesis_prompt.py`)
> + no-AI `--render`/`--replay` iteration tooling; internal-consistency gate (`ai/check_ros_synthesis.py`).
> Verified live 2026 wk0 (16 players, gate exit 0). See the most-recent build for the full record. The
> shipped shape differs from the original sketch below in three PM-decided ways: **(a)** it is a
> **batch-capable CLI writer → parquet + gate** (matching how every AI read shipped), NOT the live
> lazy/cached on-demand runtime — that (and front-end wiring) is **deferred with deployment** (no server
> exists; the key is server-side; `news_content_hash` is laid down now as the future cache seam);
> **(b)** the three §2 scores are **three independent 1-10 grades** (bull/bear/situation), not a single
> roll-up, each with its own note (extractable columns); **(c)** the 2026-news × 2025-anchor mismatch is
> handled by **graceful per-input degradation + a prior-season flag** (run on whatever resolves, make
> the gaps first-class), honoring the time-world caveat below. **The original design sketch (kept as the
> design record):**
>
> The §2 AI layer was decomposed (sparred with the PM) into
> **aggregation** (the news layer — REBUILT as the 3-stage team-news pipeline, now **COMPLETE**) and
> **interpretation** (this synthesis). The quantitative skeleton
> (`compute_ros_outcome_shape.py`: bull/bear band + preseason ADP anchor + situation/security evidence)
> exists and the news layer has **landed**; the synthesis reads them. **Note:** the
> news input is the team-pipeline **player-slice** — `player_news_slice` (Stage C output — a player's
> inherited scope-tagged claims + `signal_tier`), not the retired `player_news`.
>
> **The synthesis design (decided):** a **single lazy, cached, per-player** Claude call — NOT a batch
> pre-compute of all rostered players (you'd pay for players nobody views). It fires **on demand** when a
> user opens a player, reads his inherited `player_news_slice` (scope-tagged claims + `signal_tier`) + the Sleeper factual
> fields (injury/depth/practice) + the `ros_outcome_shape` structured anchors (`ros_bull`/`bear`/`cv`,
> `spectrum_pos`, `adp_*`, `anchor_floor`/`ceiling`, `security`/`direction`/`reliability`), and returns
> in **one pass**: (1) consolidated **news headlines** (the receipts), (2) the **bull/bear narrative**,
> (3) a **confidence-flagged grade**. One call, so the headlines and the blurb can't drift; cache keyed on
> (player + news-content-hash + week), invalidated when either changes. Guardrails (from `DECISION_READS
> §2`): **anchor to the structured inputs** so grades aren't free-floating, **always show the narrative
> with the grade**, and **flag confidence** (law 2 — qualitative + AI = the least provable read; thin/no
> news → explicitly tentative, the zero-signal-dossier move).
>
> **Reuse, don't rebuild:** `ai/client.py` is a generic isolation seam (`api_available()` API-key gate +
> one model-call point, Haiku, SDK-version-safe `json.loads`); mirror `ai/dossier_prompt.py` (a §2 prompt
> anchored to the news + anchors) and `ai/write_*` (the writer). **Gate = internal-consistency** (no
> answer key — it's live/qualitative): faithfulness (narrative only cites the clustered headlines),
> anchoring (grades consistent with the quantitative band/spectrum), confidence honesty. **Time-world
> caveat (design record):** live-2026 news can't be validly fused onto a frozen-2025 bull/bear number, so
> the grade *fusion with the band* is a live-season integration — the provable-now deliverable is the
> collect→synthesize chain over current players; don't staple a 2026 injury note onto a 2025 roster.

**Phase 1 (the spike signal-quality slice) is COMPLETE** — all four parts shipped:
(1) the engine (`compute_player_signal.py`), (2) the backtest gate (beats naive
recent-points −13% MAE on the full-2025 answer key), (3) the Players sub-view surface
(sortable table, direction-not-projection, question-framed), and (4) the per-panel
readiness gate (`readiness.jsx` — regimes + fallback slot). The descriptive dashboard
(Phase 0) plus the first decision-critique engine are both done; the project has made
the leap from *showing team state* to *grading a decision against a prior*. Still
frozen at Week 4 of 2025 for building. **The `READ_BUILD_ORDER.md` § Phase 1 "refine to
spec" delta is now also closed** — `quality_rate`/`direction`/`reliability`/`security`/
`point_correlation` bring the shipped engine's Opportunity read up to the full
`DECISION_READS.md` §1 definition (see "most recent build"). No UI surfaces these new
fields yet — that's a front-end follow-up, not blocking Phase 2.

**The Season-replay build grouping is COMPLETE (both sessions shipped).** Session A (the
`as_of_week` backend — parts 1–3) and Session B (the front-end week selector — part 4) are
both done (see the build log): the three derived analytics are tall snapshots over weeks
1–4, roster-as-of-N is fixed (backend + front-end), windowing is declared+tuned per analytic,
and a **global "As of" week dropdown** in the App shell threads the selected week through
`queries.js` (derived reads pick the matching slice; inline SQL reads filter `WHERE week ≤ N`),
drives the readiness gate, and retired the `?weeksOverride` param. Default = latest week
(today week 4); the selector travels back only.

**The Phase-2 substrate is DONE and Phase 3 (cash in the projection) is COMPLETE — all 4 cash-in
reads shipped** — per `READ_BUILD_ORDER.md`'s phase map (the authority the roadmap docs sync to).
Source #1 (Sleeper weekly projections) + the consensus/spread band with **its archetype-skew 3rd
component** (§3), **Production VOR** (§4, the first roster-management read), **True Rank** (§5 first
half, the first league-level read), **and now Positional Depth** (§6) have all landed (see "most
recent build"): the borrowed center + a **calibration-gated, fully-3-component band** is the forward
prior every read leans on; VOR proves the substrate cashes into a real add/drop surface (projected ROS
tracks actual at corr ~0.95); True Rank aggregates that VOR up into a record-independent roster-strength
rank (Pearson 0.802 / Spearman 0.842); Positional Depth re-slices it per position into surplus/gap
(per-position corr mean 0.861). **All four are answer-key gated, data + gate only (no UI yet).**
**Phase 4 is now UNDERWAY** — the **§5 bracket-math Monte Carlo** (`compute_bracket_sim.py`) ships the
posture integration point: team weekly score distributions (μ from the optimal-lineup projection, σ
from the §3 band) → analytic per-matchup win prob → a 10k-sim season over the real remaining schedule
→ **playoff odds** + projected wins/seed + magic number. With **True Rank** it **completes the §5
Posture read**. Gated config-light on actual 2025 results (Brier 0.224 beats coin-flip; expected-wins
Spearman 0.756; top-4 by odds = 3/4 actual playoff teams). **Source scouting settled the 2nd source**
— no clean historical-2025 projection source exists but Sleeper, so the **cross-source disagreement**
half (the Phase-2 substrate's other ingredient) comes **in-season via ffanalytics**; ESPN historical
is deferred (cookie-gated + `espn_id` join). **The §2 ROS outcome-shape skeleton is now DONE** (bull/bear/
situation, calibration-gated — see the most recent build), which **completes the player-read backend
(§1–§4).** **§7 Manager Dossiers is now COMPLETE** (Phase A cross-league features + Phase B the
API-key-gated Haiku dossier writer — the project's first AI-layer code, `application/ai/`; see the two
most recent builds). **Next — remaining Phase 4:** the deliberate **front-end
surfacing** of the now-six gated forward
reads (Spread/VOR/True Rank/Positional Depth/Bracket Odds/ROS Outcome Shape) — including the posture
*presentation* (True Rank + odds shown adjacent, the risk-appetite lens). **Blocked, not next:** cross-source
disagreement (Phase 2, needs the live 2nd source). Python/data-layer + front-end work.

## Version Roadmap
→ **Source of truth: `scope docs/PRODUCT_ROADMAP.md`** — phase detail, the four
design laws (grade process not outcome; speak only when confident; borrow the
substrate; consultation not autopilot), sequencing logic, and the scope filter.
Summary only here:

- **Phase 0 — Descriptive dashboard** *(done)* — team overview, league standings,
  power rankings. Frozen at Week 4 of 2025.
- **Phase 1 — Spike signal-quality slice** *(current; kickoff target)* — "is this
  production real or noise?" on usage data already fetched; validated against the
  full-2025 answer key before going live.
- **Phase 2 — Projections substrate** *(substrate done; disagreement blocked)* —
  the forward prior (the hinge everything credible depends on). **Source #1 = Sleeper**
  weekly projections + the consensus/spread band shipped; **cross-source disagreement**
  is blocked at the freeze and fills in-season via ffanalytics. Odds/Vegas optional add.
- **Phase 3 — Cash in the projection: the quantitative forward reads** *(COMPLETE —
  §3, §4, §5-half, §6 all done)* — the reads that consume the prior (per `READ_BUILD_ORDER.md`):
  Weekly Spread (§3 ✅), Production VOR (§4 ✅), True rank (half of §5 ✅), Positional Depth
  (§6 ✅). The leakage coachable-fix (backlog #1, regress-to-prior — law 1) lands in
  VOR; the shared-engines generalization is the cross-cutting *how*, not a separate gate.
- **Phase 4 — Integration + go live + opponent modeling** *(UNDERWAY — §5 bracket
  math + §2 ROS skeleton + §7 dossiers all done)* — the §5 posture read (bracket-math Monte Carlo ✅ +
  True Rank = complete), §2 ROS outcome-shape skeleton (✅ bull/bear/situation, calibration-gated),
  manager dossiers (✅ §7 COMPLETE — Phase A cross-league features + Phase B the API-key-gated Haiku AI
  writer); front-end surfacing of the gated forward reads; in-season weekly refresh; waiver and trade surfaces.
- **Phase 5 — Model of YOU** — graded decisions compound into a per-manager
  tendency profile that personalizes guidance.
- **Phase 6 — Forward advisory + AI layer (later)** — real-time "better call now";
  AI interpretation over the engines; draft & streaming surfaces.

> **Old V# → phase map** (so version references elsewhere in this doc still resolve):
> V1 dashboard → Phase 0; V1.5 scheduler + V2 waivers → Phase 4; V3 start/sit →
> Phase 3 (projections = Phase 2); V4 trades → Phase 4; V5 AI → Phase 6.

## Known Scope Exclusions
→ Source of truth: **TECHNICAL_ARCHITECTURE.md § Known Scope Exclusions** (DST/K, waiver
wire / full player pool, IR roster overages, zero-stat rows). One product note kept here:
**Market value (V1)** is snapshotted daily now to bank the time-series, but the features
that consume it (trade analysis, value-aware rankings) are V4; any UI showing it must
carry the "Powered by LeagueLogs API" attribution.

## Season-replay build grouping — COMPLETE (design record)

**One build grouping, two sessions, done before Phase 2.** Lets the user view the dashboard
*as of any past week N* — the tool exactly as it would have looked through week N, every
analytic recomputed on weeks ≤ N. A real product feature (the week selector), the in-season
"now advances each week" mechanism, and the QA instrument for every future engine. We are
**still frozen at week 4** — this did NOT expand the data; it lets us inspect weeks 1–3 states.

> **STATUS (2026-06-18):** ✅ **DONE — both sessions shipped & merged.** Session A (parts
> 1–3, the `as_of_week` backend + roster-as-of-N + windowing framework) and Session B (part
> 4, the front-end week selector) are complete and verified. The parts 1–4 text below is kept
> as the design record. **Next is Phase 2 (projections substrate)** — see "The step after".

> **Decided design (built reasons in chat 2026-06-18):**

**Part 1 — `as_of_week`, a temporal-snapshot dimension (backend).** Add `as_of_week`
as a first-class **column** on the three derived analytics (`player_signal`,
`team_form`, `team_leakage`). Grain becomes `(season, as_of_week, entity)` — one tall
table per analytic, NOT a file-per-week. This is the warehouse-correct modelling
(survives the eventual DuckDB→SQLite→server migrations) and matches the project's
existing append-snapshot pattern (leaguelogs by `snapshot_date`, the join by `week`) —
the column is *right*, not just convenient; file-per-week is the parquet-tied choice
that a SQLite layer would force you to undo. Each transform gains an as-of-week param:
filter the join to `week ≤ N` **before** computing, emit rows tagged `as_of_week = N`,
materialize all N=1..maxweek (cheap). data_layer read fns take an optional `as_of_week`
(default = latest). Current behavior = `WHERE as_of_week = max(as_of_week)` — nothing
existing breaks.

**Part 2 — windowing, per-analytic, decoupled from the cutoff.** `as_of_week` ⊥
window: the cutoff is *what data exists*; the window is *how data inside the cutoff is
weighted*. Each analytic declares its window by the **stationarity principle** (a
window is a bet about how fast the measured quantity actually drifts):
  - **Cumulative** (all weeks ≤ N, equal weight) → accounting/ledger metrics (leakage
    season points-left; record/all-play) and **structural baselines** (the league
    efficiency mean the spike signal regresses toward — ~stationary, wants max sample).
  - **Decayed (EWMA / half-life)** → state & trend reads: form (already EWMA, half-life
    2wk) and the spike signal's **player role/opportunity** component (role drifts).
  Where decayed, use a **half-life, not a hard rolling window** (smooth, no edge
  discontinuity, uses all data, graceful early-season). Half-life is a per-transform
  injected tuning constant (like `HALF_LIFE_WK`). The decayed windows are
  **backtest-tunable** — extend `backtest_player_signal.py` to sweep the opportunity
  half-life against the 2025 answer key and pick the best; don't guess. (At N ≤ ~2,
  cumulative and decayed converge anyway; the window mostly matters mid/late season.)

**Part 3 — roster-as-of-N (correctness fix; latent bug even today).** The transforms
currently resolve "current team" as `arg_max(roster_id, week)` = the *latest* week (4)
— that's "latest", not "as-of". Under `as_of_week`, roster membership must be "the
roster a player belonged to in their latest week **≤ N**." Thread the cutoff through
**roster resolution**, not just stat aggregation — it changes *who is even on the team*
at week N (trades/adds), not just their numbers. This is the cleanest proof `as_of_week`
is a true dimension; fix it as part of this work.

**Part 4 — the week selector (front-end product feature). ✅ BUILT (Session B).** A
selector that sets the active `as_of_week`, threaded through `queries.js` — derived reads
pick the matching `as_of_week` slice (`asOfSlice`), the still-in-JS SQL reads (power
rankings, construction, vitals, all-play) filter `WHERE week ≤ N` (`weekCutoff`, including
`SQL_CURRENT_TEAM` for front-end roster-as-of-N). Folded into the **readiness gate**
(`weeksElapsed = asOfWeek`) so past-week views render the real `building`/`tooEarly` states;
the temporary `?weeksOverride` QA param is **retired**. Default = latest week; travels back
only. **Resolved decisions:** placement = **global header** (App-shell dropdown, applies
across League + Team, editable from every tab); control = **dropdown** (weeks 1..latest).

**Suggested sequencing (respect the 3-commit cap):**
- ✅ **Session A — backend (DONE 2026-06-18):** parts 1–3 shipped. `as_of_week` in the
  three transforms + roster-as-of-N + windowing framework + data_layer; materialized all
  weeks; extended the backtest with `--sweep` to tune the opportunity half-life (→
  cumulative, tested). Verified per-week parquet contents (week-N slice carries only weeks
  ≤ N; N≤2 all `too_early`; roster = as-of-N for the 7 traded players). For Session B: the
  parquets are now **tall**, and `queries.js` already has a default-latest guard
  (`WHERE as_of_week = (SELECT max …)`) on the three derived reads — the selector
  parameterises that inner `max(as_of_week)`.
- ✅ **Session B — front-end (DONE 2026-06-18):** part 4. Global "As of" dropdown in `App.jsx`
  + threaded the week through `queries.js` (`asOfSlice`/`weekCutoff` + `loadWeeks()`) + panels;
  folded into the readiness gate (`weeksElapsed = asOfWeek`); retired `?weeksOverride`. Verified
  live across weeks 1–4 (week-2 trend panels "too early"; rankings reshuffle to the cutoff;
  roster-as-of-N departed flags; week persists across tabs; no console errors). **Preview
  gotcha (confirmed):** point the worktree's `.claude/launch.json` at a free port (`--port 5273`)
  — a stray 5173 server serves *main's* frontend, not this source.

**Non-goals:** not expanding past week 4; not Phase 2. This is the replay/inspection
layer that precedes Phase 2.

## Refinement backlog — Team Overview (deferred, not blocking)

These refine shipped lenses; pick up alongside or after the Players sub-view.

> ✅ **Done (2026-06-07):** Lens-4 reframe (retrospective → improvement) and the Form
> lens EWMA switch both shipped. ✅ **Done (2026-06-17):** item 2 (per-panel readiness
> gate) shipped as `readiness.jsx` — see the maintenance log. **One backlog item remains:**

1. **Reframe the Lens-4 "coachable" fix from confident imperative → advisory question
   (and own its predictive weakness).** The shipped coachable fix says *"start X over Y
   going forward — +N/g on the season,"* which silently converts a tiny realized sample
   into a forward claim it can't support. **Worked example that exposes it:** at the wk-4
   freeze, Cousin 'Chilling's roster fired *"start Keenan Allen (16.3/g) over A.J. Brown
   (8.8/g) at WR going forward."* Pulling the *actual* rest-of-season from
   `nfl_stats_2025.parquet`: **Brown W5+ = 16.8/g, Allen W5+ = 9.0/g** — a near-total
   reversal; Brown won 7 of the next 10 head-to-heads by +67.7 pts. The call would have
   been backwards. Mechanism: 4 games, equal-weighted, **no talent prior** — Brown's two
   near-zero early games were noise a prior would discount; stars are the *worst* case for
   realized-rate reads. The leakage total is descriptively true (you did leave those
   points in wks 1–3); only the **forward language** overreaches. Directions:
   - **Language (near-term, cheap):** drop the imperative + "+N/g going forward." Pose it
     as a **question the manager adjudicates**, per the project mission (consultation, not
     autopilot): *"Is it time to pivot off Brown? He's scored 8.8/g to Allen's 16.3 over
     4 weeks — past fluke territory; decide if you still believe in him."* Surfaces the
     decision point; defers the call to the user.
   - **Trade-timing angle (V4):** a sustained underperformance isn't only a start/sit
     question — even if you *don't* believe the player rebounds, selling while perceived
     value is high (≈$0.85 on the dollar) beats holding until the market reprices
     (≈$0.35). Ties to the **LeagueLogs market-value** layer (V4). The signal's real job
     is to flag "make a call here," not to make it.
   - **Real fix (V3):** regress realized rate toward a forward prior (FantasyPros
     projections / ADP) before calling anything coachable; gate the language on sample
     size (see item 2). Until then, keep coachable **retrospective**, not predictive.

2. ✅ **DONE (2026-06-17) — Per-panel readiness gate.** Shipped as `readiness.jsx`:
   `assessReadiness(regime, weeks)` + a `Gate` wrapper. Regimes — **structural** (ready at
   roster lock), **point-in-time** (ready week 1, confidence grows), **trend** (ready
   ~week 3–4) — map to ready / building / tooEarly; a **"too early" fallback slot** accepts
   custom children (the preseason-content hook, no rework) and a *building* note calibrates
   language on thin samples. Wired into the Team tab (construction = structural, Form +
   leakage = trend, Players = point-in-time). Frozen at week 4 → all ready; `?weeksOverride=N`
   drives the clock for QA. The deeper "calibrate to a forward prior" half is **Phase 2**
   (projections) — the gate is the seam; the prior that sharpens it comes next.

## Phase 2 — the projections substrate (substrate DONE; disagreement blocked) → Phase 3 COMPLETE

> **Phase labels follow `READ_BUILD_ORDER.md`** (the authority STATUS + PRODUCT_ROADMAP sync
> to): the **substrate** (consensus + spread band) is Phase 2; the reads that **consume** it —
> Weekly Spread §3, VOR §4, True rank half-§5, Positional Depth §6 (**all done**) — are
> Phase 3 "cash in the projection." This section covers the substrate + its progress; the
> Progress list below spans both.

The hinge — **the forward prior** every later decision slice rests on. Delivered as a
**multi-source `projections` entity** (all I/O through `data_layer.py`; keyed on
`sleeperPlayerId`; `source` a column so providers combine/select without a schema change),
plus a transform producing a **consensus + disagreement (spread)** read. Two payoffs: (a) the
spread is the law-2 confidence signal — tight consensus = act, wide = coin-flip; (b) it gives
the spike read a *forward* prior to regress toward, fixing the one honest blind spot the
backtest surfaced (Kamara: usage looked fine, the player declined — usage alone can't see
talent/situation change). It also lets the readiness gate *calibrate* early-season language
rather than merely gate it. Do **not** use prior-season carryover as the prior (biased by
age/injury/scheme).

**Progress:**
- ✅ **Source #1 — Sleeper weekly projections (DONE).** `sleeper.py projections <season> [week]`
  → `write_projections(source="sleeper")`. Historical (works with the frozen-2025 world),
  native `sleeperPlayerId`. See the build log.
- ✅ **Consensus + spread band, all 3 components (DONE).** `compute_projection_consensus.py` →
  `derived/projection_consensus_{season}.parquet`: borrowed consensus **center** + a percentile band
  whose **width** is the player's residual std shrunk to a positional prior + **archetype skew**
  (§3 c3) via a Cornish-Fisher shift from the player's residual *skewness* shrunk to a positional
  prior. Calibration-gated (`backtest_projection_consensus.py`, exit 0) — extended to **per-tail**
  (below-p25/above-p75 ≈ 0.25 each), joint `BAND_Z × SKEW_GAIN` sweep → (0.55, 1.5): coverage 0.493,
  tails 0.247/0.261. Skew driver resolved by the answer key (residual 3rd moment, not the
  TD-dependence archetype §3 names — see "most recent build"). The **cross-source disagreement**
  ingredient stays null under one source, additive when a 2nd lands.
- ✅ **Production VOR (§4) — first substrate-consuming read (DONE).** `compute_production_vor.py` →
  `derived/production_vor_{season}.parquet`: ROS value (borrowed centers summed over remaining weeks)
  over the waiver line, normalized by pool spread; QB pool + pooled flex line from `lineup_slots`;
  tall over as_of_week. Gate (`backtest_production_vor.py`, exit 0): projected ROS tracks actual at
  corr 0.944 QB / 0.955 FLEX, VOR tiers monotonic in realized production. Market VOR + trade gap V4.
- ✅ **True Rank (§5, first half) — first league-level substrate-consuming read (DONE).**
  `compute_true_rank.py` → `derived/true_rank_{season}.parquet`: per team, optimal-lineup ros_value
  sum → record-independent roster-strength rank + spectrum_pos + bench_value; re-aggregates
  Production VOR over the lineup rules (optimal-lineup greedy lifted into `_analytics` as shared
  `expand_slots`/`optimal_lineup`); tall over as_of_week. Gate (`backtest_true_rank.py`, exit 0):
  projected strength tracks the actual ROS ceiling at Pearson 0.802 / Spearman 0.842 (freeze wk4,
  n=10, floor 0.60); strong half +261.7 ROS over weak. Slot-aware (a 2-QB roster ranks by its one
  startable QB). No UI (data+gate). Bracket-math Monte Carlo (§5 full) is Phase 4.
- ✅ **Positional Depth (§6) — the last Phase-3 cash-in read (DONE).** `compute_positional_depth.py` →
  `derived/positional_depth_{season}.parquet`: per (as_of_week, roster_id, fine position QB/RB/WR/TE),
  re-slices VOR net of the position's dedicated `starter_need` (from `lineup_slots`; shared FLEX
  excluded → depth = surplus); carries starter_value, surplus_value/surplus_startable, marginal_vor
  (gap indicator), spectrum_pos per position cohort, advisory surplus/adequate/gap shape; one row per
  (team, position) even at zero count. New `data_layer.write/read_positional_depth`. Lossless re-slice.
  Gate (`backtest_positional_depth.py`, exit 0): per position, projected starter_value tracks the
  actual ROS ceiling at QB 0.792 / RB 0.867 / WR 0.855 / TE 0.928, mean 0.861 (floor 0.50); top half
  +85.3 over bottom. **Closes Phase 3 (4/4).**
- **2nd source — scouted, resolved:** no clean historical-2025 weekly projection source but Sleeper
  (ffanalytics = live-scrape + R; fantasyfootballdatapros = 2019/20 ESPN snapshot + actuals; ESPN =
  cookie-gated + `espn_id` join). Plan: **ffanalytics for the in-season live cross-source
  disagreement** (2026); ESPN historical only if we later want to backtest disagreement against 2025.
- ✅ **§5 bracket-math Monte Carlo (DONE — Phase 4 begun).** `compute_bracket_sim.py` → playoff odds
  from the forward reads; with True Rank = §5 Posture complete. Gated config-light (Brier 0.224 beats
  coin-flip; expected-wins Spearman 0.756; top-4 by odds = 3/4 actual playoff teams). See "most recent build".
- ✅ **§2 ROS Outcome Shape skeleton (DONE — Phase 4).** `compute_ros_outcome_shape.py` → bull/bear (borrowed
  ROS centre ± BULL_Z·√Σband², floored, emergent time decay) + situation/security (player_signal trust axis).
  Calibration-gated (coverage 0.835; BULL_Z swept to 1.645; monotonic by bull tercile). **Completes the
  player-read backend (§1–§4).** See "most recent build".
- ✅ **§7 Manager Dossiers COMPLETE (Phase A + B — Phase 4).** Phase A: cross-league acquisition
  (`fetch-manager-activity` → `manager_activity_{season}`, first cross-league/user-keyed entity) +
  deterministic features (`compute_manager_features.py` → `manager_features_{season}`). Phase B: the
  project's first AI-layer code — `application/ai/` writes one API-key-gated Claude-Haiku dossier per
  manager (`manager_dossiers_{season}`, first AI-written entity) from those features; synchronous calls
  behind a swappable seam, run-once, tendencies-not-verdicts, blindspot/edge framing, internal-consistency-
  gated. Both live-verified 2025 (Phase B: 10 dossiers, ~$0.025, gate exit 0). See the two most recent builds.
- **Next — remaining Phase 4:** the **front-end surfacing** of the six gated forward reads (incl. posture
  presentation) + the dossiers.
  **Blocked, not next:** cross-source **disagreement** (in-season, needs the live 2nd source).
- **Optional cheap add:** Vegas game totals via an `odds.py` fetcher (game environment).

> **V1 Dashboard Build Order — moved.** The dashboard build order, plus the full
> Built / Unbuilt breakdown (Built Backend · Built Frontend · Unbuilt+Blocked), now lives in
> `scope docs/READ_BUILD_ORDER.md`. Single source of truth — not duplicated here. The backend
> hygiene backlog is in `LLM context/710_AUDIT.md`.

> **Multi-league / multi-season frontend — scoped (2026-07-15, not started).** Inspection of the
> single-league frontend produced a concrete architecture + ordered migration in
> `scope docs/future work/MULTI_LEAGUE_STORE_MIGRATION.md`. **Locked decisions:** migrate the store
> from in-browser DuckDB-WASM → server-side **SQLite + HTTP API** *first* (single-league parity), then
> build the multi-league/season selectors on top (switch-league becomes an API param, not a file swap).
> Backend content compute for ~10 demo leagues (new `compute_demo_slices.py`) + a `schedule`
> league-scoping fix are store-agnostic prerequisites. ~8–12 sessions; see the doc for the phase order.

> **Scoring/format support — scoped (2026-07-16, not started).** Three code-grounded assessment docs in
> `scope docs/future work/`: `STANDARD_SCORING_SUPPORT.md`, `CUSTOM_SCORING_SUPPORT.md`,
> `DYNASTY_SUPPORT.md`. **Shared thesis:** the 5 tuned constants (`BAND_Z`/`SKEW_GAIN`/`BULL_Z`/`ANCHOR_W`/
> `OPP_HALF_LIFE_WK`) are fit only on the matched stratum → a scoring change (std/custom) is
> **certify-not-tune**; the format change (dynasty) needs its own value-layer substrate + fitting.
> **Verdicts:** standard = engine-complete, gap is data + one substrate build (pure-std=0, no `std/`
> substrate); custom = engine-partial, **45% of real custom leagues unscoreable** (first-down +
> threshold bonuses), lever is rule coverage not tuning; dynasty = value-model change (ADP anchor/market/
> multi-year `ros_value`), biggest lift.
