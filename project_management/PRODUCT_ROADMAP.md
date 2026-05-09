# Product Roadmap

> What's next, in what order, and what's deferred. Constitution document — refer here to find the current phase, the gates between phases, and the open decisions ahead.

**Last reviewed:** 2026-05-08

---

## Current Phase

**Phase 1 — Strategy Mind Synthesis**

The three-pass synthesis pipeline (Pass 1 → Pass 2 → Merge → Pass 3) is designed and prompts are written. Token vocabulary is templated. No transcripts have been synthesized with v2 prompts yet. The four existing strategy MD outputs from v1 are baseline-only.

**Active gate:** Token vocabulary must be locked against actual planned Python fetcher names before Pass 3 runs.

---

## V1 Phasing

### Phase 1 — Strategy Mind (in progress)

Sub-phases, in order:

1. **1a. Lock token vocabulary** against actual Python fetcher function names. Update DATA_TOKEN_VOCABULARY_TEMPLATE.md to match implementation plan exactly. *Gate to all of Phase 1c onward.*
2. **1b. Test Pass 1 on one transcript.** Validate v2 prompt quality on a representative transcript before bulk execution. Cheap sanity check.
3. **1c. Run Pass 1 on FSE redraft batch** (55 transcripts, the largest and last remaining batch).
4. **1d. (Decision point)** Re-run Pass 1 on the three earlier batches (flock_dynasty, flock_redraft, fse_dynasty) with v2 prompts? Or accept v1 baseline?
5. **1e. Run Pass 2** three times at temperature 0.3–0.5 per batch, then run Merge.
6. **1f. Run Pass 3** to add data-dependency tags to each merged strategy MD.

**Phase 1 exit criteria:** All four strategy MD files exist as v2 outputs, each with applicability tags + data-dependency tags + variance audit completed.

### Phase 2 — Data Orchestrator

Build Python fetchers for every `available` token. Implement caching per the data_sources.txt cadences. Mock or fallback for `gap` and `paywalled` tokens with documented behavior.

**Phase 2 entry gate:** Phase 1 complete (token vocabulary stable).
**Phase 2 exit criteria:** Every token in the vocabulary has either a working fetcher or a documented fallback.

### Phase 3 — Advisor APIs

Implement the four output types end-to-end:
- Start/sit advisor
- Waiver advisor
- Trade advisor
- Ad hoc prompt generator

Each fixed advisor: parse question → filter strategy rules by tags → assemble pre-filtered data context per `{needs: ...}` blocks → API call → structured response.

Ad hoc generator: question → API call returns `(data_plan, prompt)` → Python packages data per plan → user gets two artifacts to use in separate Claude session.

**Phase 3 exit criteria:** All four output types tested against 5+ historical scenarios each.

### Phase 4 — Dashboard

Streamlit + Altair limited-interactive dashboard with:
- Current roster status
- Last week's matchup
- Recent advisor outputs (timestamped with input snapshot)
- One data-driven chart that proves valuable

**Phase 4 exit criteria:** Dashboard renders without errors, all four panels populated, theme tuned beyond Streamlit defaults.

### Phase 5 — V1 Validation

Run the full advisor pipeline against historical test cases. Document API cost per output type. Confirm V1 success criteria from PROJECT_OVERVIEW.md.

**Phase 5 exit criteria:** All six PROJECT_OVERVIEW V1 success criteria objectively true.

---

## V2 Roadmap

V2 begins with the start of next NFL regular season, when live signal becomes available.

- **Live feedback loop.** Log every advisor recommendation alongside the actual outcome. Surface patterns where advice was wrong.
- **Periodic strategy re-synthesis.** Schedule the three-pass pipeline to re-run on a cadence as new creator content emerges. Patch corrections back into the strategy mind.
- **Local trend derivation.** Build the trend metric for `market_value_trend` from accumulated LeagueLogs snapshots (their trend fields are stubbed at zero).
- **NWS weather forecast integration** if it didn't ship in V1.
- **Recommendation correctness scoring.** Once feedback exists, build a metric that grades the advisor against actual high scorers.

---

## V3+ Ideas

Tracked but not committed. Move to V2 only if they earn their place against more pressing work.

- **Monte Carlo simulations.** Lineup MC (best lineup given projection variance), playoff odds MC (rest-of-season probability), trade impact MC (playoff probability with vs. without a trade). ~100-200 lines of numpy each. Great dashboard features.
- **PFF coverage data integration** if it becomes affordable. Re-run Pass 3 only; ~5-10% of currently-flagged rules become evaluable.
- **Multi-league support.** Generalize roster/league context tokens.
- **Auction draft / salary cap formats.**
- **Off-season trade evaluation tool** standalone for dynasty managers.
- **Coordinator/coaching tendency surfacing** — currently in static layer; could be dynamic.
- **In-game live decision support** (partial-game start/sit tweaks, swap suggestions). Unclear if this is wanted; logged for future consideration.

---

## Phase Gates Summary

| Gate | Required Before |
|---|---|
| Token vocabulary locked | Phase 1c (bulk Pass 1 execution) |
| All Phase 1 batches tagged | Phase 2 (data orchestrator build) |
| All fetchers + fallbacks implemented | Phase 3 (advisor API build) |
| All four advisors tested | Phase 4 (dashboard build) |
| Dashboard renders + V1 criteria met | V1 ship |

---

## Risks (Tracked)

1. **Strategy mind quality is the leverage point.** Generic synthesis produces generic advisors. Mitigation: v2 prompts, three-run merge, variance audit.
2. **Out-of-season validation is necessarily synthetic.** No live signal until next season. Mitigation: historical test cases. Accept this as a real constraint, not a defect.
3. **API cost overshoot.** Pass 2 + merge across 4 batches at Opus rates is ~$70-100. Runtime cost TBD. Mitigation: track costs from day one, shift to Sonnet if budgets tighten.
4. **Token vocabulary churn.** Renaming tokens mid-build invalidates Pass 3 outputs. Mitigation: lock vocabulary BEFORE Pass 3 runs.
5. **Scope creep.** Enthusiastic-builder failure mode. Mitigation: V1 non-goals list in PROJECT_OVERVIEW.md, updated whenever new tempting features appear.
6. **Cross-session context loss.** Mitigation: this doc + journal entries. Future LLM sessions read PROJECT_OVERVIEW + this + recent journal entries to cold-start.

---

## Open Questions (To Resolve in Order)

These are the active decisions blocking forward progress. Resolve top-down. Items in **Block 1** are critical and gate the next concrete work; items in **Block 2** are important but defer-able by 1-2 sessions.

### Block 1 — Critical (resolve before any Phase 1c+ work)

1. **What is the user's actual fantasy league configuration?** PPR / Half / Standard? 1QB or Superflex? League size? This drives LeagueLogs profile selection (one of: redraft-1qb-12t-ppr1, redraft-1qb-12t-ppr0_5, redraft-2qb-12t-ppr1, dynasty-1qb-12t-ppr1, dynasty-2qb-12t-ppr1) and scoring assumptions for projections. **Without this, the orchestrator cannot fetch correct data.**
2. **Sleeper league_id + user_id.** Required for the orchestrator to know "your roster" vs other teams. Captured where? Suggested: a `config.local.json` file at project root, gitignored.
3. **API keys + accounts status:** Anthropic API key (assumed exists), FantasyPros API access (paid plan? key in hand?), Odds API key (free tier signed up?). Needed for Phase 2.
4. **Lock the data token vocabulary.** DATA_TOKEN_VOCABULARY_TEMPLATE.md is currently populated as a draft. Walk through token-by-token, decide which Python function each maps to, rename for consistency, then declare it locked. **This is the gate to all Pass 3 work.**
5. **Single redraft strategy file at runtime, or per-batch?** We have 4 batch files (flock_dynasty, flock_redraft, fse_dynasty, fse_redraft). At runtime the orchestrator queries by league format — so it needs ONE redraft strategy file and ONE dynasty file, not two each. Decision: do we add a fifth synthesis step that merges per-format batch files into a single canonical file? Or does the orchestrator query both batch files at runtime and reconcile? **TECHNICAL_ARCHITECTURE.md and PRODUCT_ROADMAP.md currently reference "four strategy MD files" without resolving this.**

### Block 2 — Important (resolve in early Phase 2 work)

6. **Is NWS forecast integration in V1 scope or V2?** Decision needed before Phase 2 build.
7. **Re-extract earlier 3 batches with v2 prompts, or accept v1 baseline?** Cost: ~$3-5 Sonnet. Benefit: consistency across all four strategy mind files.
8. **What specific historical test cases will V1 be validated against?** Suggestion: pick 5 specific Week N decisions from a prior season with retrospective ground truth.
9. **What's the cost ceiling for Pass 2 + merge on Opus across 4 batches?** Currently estimated $70-100. If too high, fallback: Sonnet for runs + Opus only for merge (~$30-40).
10. **What's the one specific data-driven chart for the dashboard's V1?** Suggestion: market value trend per roster player over recent snapshots.

### Block 3 — Defer-able (decide when reaching Phase 4 or later)

11. **Repository / project structure.** Where does Python code live (top-level `src/`? sibling `code/` folder? inside `fse2024/`?). Where do strategy MD files live at runtime (`strategy/` subfolder?). Where do JSON caches live (`caches/`?). **No future LLM can write code without this decision.**
12. **Secrets management plan.** API keys for Anthropic, FantasyPros, Odds API need a `.env` file (gitignored) or similar. Critical to decide before any code is committed to git, otherwise keys leak.
13. **Git / version control.** Is this a git repo? Is there a `.gitignore` covering `.archive/`, `caches/`, `.env`, `*.parquet`?
14. **Dashboard hosting.** Local Streamlit run-on-demand? Always-on background process? Cron-triggered cache refresh + manual UI launch?
