# Standard (non-PPR) Scoring Support — Assessment & Plan

**Last reviewed:** 2026-07-16 · **Status:** Scope / design doc — **not yet started.**

> **Verdict:** Standard scoring is **engine-complete**. The delta engine is built *on* the standard
> baseline, `scoring_profile` classifies `std`, `standard_scoring("std")` exists, and `build_substrate`
> already accepts `std`. The gap is **100% data + one substrate build**, not engine work — and because
> standard is the delta engine's exact baseline, it needs **no new tuning, only certification** (it is the
> *easiest* profile to certify).
>
> **Origin:** produced 2026-07-16 from a code-grounded inspection of the scoring engine
> (`transforms/_scoring.py`), the substrate builder (`transforms/build_substrate.py`), and the corpus
> (`corpus/`, `corpus_discovery.parquet` / `corpus_manifest.parquet`). Companion to
> [`CUSTOM_SCORING_SUPPORT.md`](./CUSTOM_SCORING_SUPPORT.md) and [`DYNASTY_SUPPORT.md`](./DYNASTY_SUPPORT.md);
> the shared invariance thesis is stated once below and referenced by all three.

---

## Context

**Why:** The engine is `scoring_key`-parameterized (`ppr` / `half` / `std` / `cust-<hash>` —
`transforms/_keys.py:17-23`), but only `ppr` and `half` are "flipped": harvested, substrate-built, and in
the tuning corpus. This doc asks what it takes to make **standard** a first-class, browsable profile.

**Corrected mental model:** "add standard support" sounds like an engine feature. It is not. Standard is
the profile the engine was *built around* — every canned projection column (`proj_pts_std`) and every
actual column (`fantasy_points`) already expresses it, and the custom delta engine is defined as *"the
standard canned baseline plus per-component deltas"* (`_scoring.py:18-24`). A standard league is the delta
engine with **all deltas zero** — i.e. the baseline itself, exact by construction. So there is nothing to
*build* in the scoring path; the only questions are (1) has the standard **substrate** been generated, and
(2) do any standard **leagues** exist to render.

**The shared invariance thesis (all three docs).** The five tuned constants —
`BAND_Z=0.55` (`compute_projection_consensus.py:86`), `SKEW_GAIN=1.5` (`:95`),
`BULL_Z=1.44` (`compute_ros_player_band.py:56`), `ANCHOR_W=0.25` (`:57`),
`OPP_HALF_LIFE_WK=None` (`compute_player_signal.py:109`) — are fit **only on the matched stratum**
(`ppr/half · 1qb · redraft · 10-14 teams`, `_corpus.is_matched_eligible`, `_corpus.py:23`), the only
stratum with `never_tune=False` (`select.py:313`). The project's deliberate stance is *"stay NARROW
(PPR/half·1QB·redraft); exotic leagues are a robustness test set, never a tuning input"*
(`LEAGUE_CORPUS.md:44-46`). **For a scoring change (std/custom), those constants are scoring-invariant** —
they describe NFL player-week residual shape and horizon decay, not the points transform. **⇒ certify that
the matched constants hold on `std`; never re-fit them per key.** The out-of-sample machine for that is the
proposed **L4 Tuner** (constant registry `transforms/_constants.py` + TRAIN 2020-23 / DEV 2024 / TEST 2025
season split + league-wise holdout; `IMPROVEMENT_LOOP.md:239-289`) — not built yet.

---

## What the engine supports today (grounded)

- **Classification.** `scoring_profile(scoring)` returns `"std"` when `rec == 0.0`, every shape-defining
  offensive weight matches `_STANDARD` (`pass_yd 0.04`, `pass_td 4`, `rush/rec_yd 0.1`, `rush/rec_td 6`),
  and no bonus/first-down key is active — `_scoring.py:105-124`. The float32-tolerance guard (`_TOL=1e-6`,
  `_weights_match`, `:98-102`) means a drifted standard league is no longer misclassified as custom (the
  Session 0.6 fix).
- **A settings-free standard dict.** `standard_scoring("std")` returns the canonical std scoring dict —
  written **explicitly** so the NFL substrate can be built *independent of any league's settings*, since
  "historical seasons have no is_mine league to read settings from" (`_scoring.py:130-139`).
- **Exact points.** `projection_points_expr("std", …)` selects `proj_pts_std`; `actual_points_expr("std",
  …)` selects `fantasy_points` (`_scoring.py:200-218`). The delta engine reproduces these exactly (all
  deltas 0 — the module's correctness proof, `:18-24`).
- **Substrate builder accepts it.** `build_substrate.py` lists `std` as a first-class `--scoring-keys`
  choice (`:87`); its default is only `["ppr", "half"]` (`:34`) because those are what Session 2 built.
- **The compute spine is key-agnostic.** `compute_spine._compute_league` passes `scoring_key` straight
  through to `compute_production_vor` / `compute_bracket_sim` (`compute_spine.py:114-127`) — it already
  runs any key.

## The gap (grounded)

1. **Standard leagues effectively do not exist.** The discovery crawl's stored classification over 2,729
   league-seasons is `custom` / `ppr` / `half` only — **zero `std`**; the corrected classifier reduced the
   custom pool but surfaced ppr/half, not std (`LEAGUE_CORPUS.md:52-58`, *"pure std = 0"* `:44`). No `std`
   key appears in `corpus_manifest` (keys are `ppr` 207, `half` 93, ~11 `cust-…` at 1-2 each). Standard
   scoring is essentially extinct on Sleeper — so this is a **data-acquisition/synthesis** problem, not a
   harvest-what-exists problem.
2. **No standard substrate is built.** On disk, `derived/scoring/` holds `ppr`, `half`, and 8 `cust-…`
   directories — **no `std/`**. So `projection_consensus_std` and `ros_player_band_std` don't exist yet.
   `build_substrate --generalization` only builds the *gen manifest's* keys (`build_substrate.py:45-62`),
   and since no std league is in the manifest, std was never triggered.

Nothing else is missing: no classifier change, no delta-engine change, no new read.

---

## Plan (staged; store-agnostic backend + a demo slice)

**Stage 1 — Build the standard substrate.**
`python3 -m application.data.transforms.build_substrate --scoring-keys std` across 2020-2025. This runs
`compute_projection_consensus` then `compute_ros_player_band` for `std` (one deterministic pass; std is the
baseline column, so consensus is a straight column-select). Gate with `backtest_projection_consensus` and
`backtest_ros_player_band` on the `std` key. Prerequisite already banked: `projections` 2020-25 carry
`proj_pts_std`, and `adp_points_curve/holdout_{S}` exists (`build_substrate.py:9-12`).

**Stage 2 — Get a standard slice to render.** (recommend (a))
- **(a) Synthesize** a demo `std` slice by **re-scoring an already-harvested league** under `std`. Every
  read consumes the same `join_season` + the scoring-scoped substrate; because `actual_points_expr("std")`
  / the delta engine are exact, re-running the spine for an existing league with `scoring_key=std` produces
  a faithful standard view at **zero acquisition cost**. This is the realistic path given std's extinction.
- **(b) Onboard** a genuine `std` league if the crawl ever surfaces one (rare; keep the crawl's classifier
  watching for `rec==0` boards).

**Stage 3 — Certify, do not tune.** Run the **matched** constants against the std slice through
`check_spine`; confirm skill/calibration hold (standard carries the *least* model risk — it is the baseline
the residuals were measured against). Record `std` as **certified-invariant**. If/when the L4 Tuner exists,
`std` may enter only as a **league-wise holdout**, never a fit input (honoring "report, don't tune").

**Stage 4 — Register + expose.** Add the std slice(s) to `leagues.parquet` (the registry
`compute_spine`/`build_substrate` resolve keys from). The multi-league frontend
(`MULTI_LEAGUE_STORE_MIGRATION.md`) then surfaces `std` with no per-key frontend change — `scoring_key` is
already a column/label in the catalog.

---

## Risks / can't-generalize

- **No wild standard leagues.** Synthesis (Stage 2a) is the realistic demo path; a purely "harvest real
  std leagues" plan would likely never fill. State this honestly rather than waiting on the crawl.
- **Certification power.** A single std slice certifies at the same low-n bound as any one league; but std
  is the simplest case (zero deltas), so the certification claim is the strongest of the three profiles.
- **Synthesis honesty.** A synthesized std slice is a *re-scoring* of a real league's player-weeks, not a
  real std league's behavior (roster construction under std differs). Label it a **demo/certification
  slice**, not a claim about how std managers play.

---

## Critical files

**Modify:** none structurally.
**Run:** `transforms/build_substrate.py` (`--scoring-keys std`), `corpus/compute_spine.py`,
`transforms/check_spine`-equivalent gates.
**Create (optional):** a small `transforms/resynthesize_scoring.py` helper to re-score an existing league's
persisted `join_season` under a target `scoring_key` for the demo slice (reuses `_scoring.actual_points_expr`
/ `projection_points_expr`; writes through `data_layer` under the new key).
**Reference (reuse, don't rebuild):** `_scoring.standard_scoring` (`:130`), `_scoring.actual_points_expr` /
`projection_points_expr` (`:200-218`), `build_substrate.run` (`:37-42`).

---

## Verification

- **Substrate:** after Stage 1, `derived/scoring/std/` exists with `projection_consensus_std` /
  `ros_player_band_std` for each season; `backtest_projection_consensus --scoring-key std` passes.
- **Exactness check:** assert `actual_points_expr("std")` on a sample of players equals the raw
  `fantasy_points` column (the delta engine's zero-delta identity) — a cheap correctness proof.
- **Slice:** after Stage 2-3, the synthesized std league's spine (`production_vor` … `bracket_odds`) is
  present and `check_spine` is green on the std key; spot-check that std points < ppr points for
  reception-heavy players by exactly `receptions` (the ppr−std identity, `_scoring.py:64`).

---

## Session / commit sequencing

Small: ~1-2 sessions (3-commit cap each). Session 1 = substrate build + gate + the optional resynthesis
helper. Session 2 = demo slice + certify + register. Docs-only until then. Fresh worktree →
`worktree-setup.sh` → work → update `STATUS.md` → `worktree-close.sh --merge`.
