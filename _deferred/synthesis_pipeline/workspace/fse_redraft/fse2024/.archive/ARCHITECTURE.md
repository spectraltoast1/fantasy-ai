# Fantasy Football Advisor — Project Architecture

> Reference document for the system design, decisions, and rationale behind this project. Read this first if you're a future LLM session or a future-self picking up after time away.

---

## Project Goal

Build a personal AI fantasy football advisor that gives high-quality, data-grounded recommendations across the four core in-season decision types (start/sit, waivers, trades, ad hoc questions). The system's intelligence comes from a "strategy mind" — markdown files synthesized from a curated set of fantasy football YouTube transcripts, augmented with live data from multiple sources at decision time.

**This is a personal project the user is co-building with Claude Code.** The user makes directional decisions and assists with debugging; Claude Code writes the code. Architectural decisions should favor patterns Claude Code is fluent in and avoid stacks that increase debugging friction.

---

## High-Level Architecture

```
TRANSCRIPT INGESTION
─────────────────────────────────────────────────────────────────
  YouTube transcripts (.txt)  ─▶  Pass 1 (Sonnet)  ─▶  JSON cache
                                  per-transcript        per source
                                  rule extraction       per batch

JSON cache  ─▶  Pass 2 (Opus, run 3x)  ─▶  Strategy MD (3 versions)
                synthesis to unified
                strategy file

Strategy MD x3  ─▶  Pass 2 Merge (Opus)  ─▶  Strategy MD (merged)
                    best-of merge with
                    [VARIANCE] flags

Strategy MD  ─▶  Pass 3 (Sonnet)  ─▶  Strategy MD (data-tagged)
                 append {needs: ...}
                 data dependency tags


RUNTIME (4 advisor types)
─────────────────────────────────────────────────────────────────
                              ┌──▶  Start/Sit Advisor (API call)
                              │
  Strategy MD (data-tagged)   ├──▶  Waiver Advisor (API call)
            +                 │
  Live data orchestrator      ├──▶  Trade Advisor (API call)
            +                 │
  User question               └──▶  Ad Hoc Prompt Generator
                                    (returns data plan + prompt
                                     for user to use in their own
                                     Claude session — not API call)


DASHBOARD
─────────────────────────────────────────────────────────────────
  Local data + cached Claude outputs ─▶ Streamlit + Altair dashboard
```

---

## The Three-Pass Synthesis Pipeline

The strategy MD files are the heart of the system. They are produced by a 3-pass pipeline (4 if you count the merge step) over curated YouTube transcripts.

### Pass 1: Per-Transcript Rule Extraction
- **Model:** Sonnet (sufficient for structured extraction; Opus is overkill)
- **Input:** Single `.txt` transcript file (NoteGPT auto-transcript, often messy)
- **Output:** Numbered list of rules separated by `\n\n`, stored as one entry in a JSON cache keyed by source filename
- **Prompt:** `FIRST_PASS_PROMPT_v2.md`
- **Critical extraction skill:** Transmute player-specific takes into transferable reasoning patterns. "Doubs is risky against zone" → "When evaluating WRs, weight man/zone success splits against defensive coverage tendency."

### Pass 2: Synthesis to Unified Strategy File
- **Model:** Opus (judgment-heavy task — conflict resolution, calibration logic)
- **Input:** JSON cache from Pass 1
- **Output:** Markdown strategy file with structural sections, applicability tags `[REDRAFT]`/`[DYNASTY]`/etc., and a Conflicts appendix
- **Prompt:** `SECOND_PASS_PROMPT_v2.md`
- **Run 3 times** at temperature 0.3–0.5 to produce variance for the merge step

### Pass 2 Merge: Best-Of Across 3 Runs
- **Model:** Opus
- **Input:** Three Pass 2 outputs from independent runs
- **Output:** Single merged strategy file with `[VARIANCE]` flags on retained singletons and threshold disagreements
- **Prompt:** `SECOND_PASS_MERGE_PROMPT_v2.md`
- **Why:** Variance reduction. With 200+ rules per output, "pick the best" loses good rules from runs you didn't pick. Merging captures the union of high-quality rules.

### Pass 3: Data Dependency Tagging
- **Model:** Sonnet (structured tagging, not synthesis — Opus overkill)
- **Input:** Merged strategy file + token vocabulary contract
- **Output:** Same strategy file with `{needs: token1, token2, ...}` blocks appended to each rule, plus a Data Coverage Summary
- **Prompt:** `THIRD_PASS_PROMPT_v2.md`
- **Why a separate pass:** When the data layer evolves (add coverage data, swap fetchers), re-run only Pass 3. The strategy file's intellectual content stays stable while the data layer changes.

---

## The Token Vocabulary Contract

Located at `DATA_TOKEN_VOCABULARY_TEMPLATE.md`. This is the **contract between the strategy file and the Python data orchestrator**: every token used in the strategy file must be defined here, every defined token must map to a Python fetcher function.

Key categories:
- Player identity & roster status
- Injury & practice status
- Player-level usage (snap %, target share, route participation, NGS metrics)
- Player-level efficiency (EPA, success rate, YPC)
- Defense / matchup
- Game environment (Vegas, weather)
- Market & consensus (LeagueLogs)
- Projections (Sleeper + FantasyPros)
- League / format / user context
- Historical / static (combine, draft capital)

**Availability flags** drive runtime decisions:
- `available` — ready to fetch
- `paywalled` — requires paid source (PFF coverage data)
- `paywalled-budgeted` — available but with budget limits (Odds API player props)
- `gap-low-effort` — needs implementation (weather forecast via NWS)
- `unavailable` — no acceptable source

---

## Tech Stack Decisions

### Language: Python end-to-end
- **Why:** Claude Code is materially better at Python than R. Anthropic SDK is Python-first. LLM tooling ecosystem (instructor, async patterns, agent frameworks) is 6-12 months ahead in Python. Async API calls to multiple data sources favor Python's asyncio.
- **Why not R:** Better for some statistical viz (ggplot, nflplotR), but the project's hard parts (Claude integration, async fetching, web services) are Python territory. Adding R doubles the operational complexity for minimal gain.
- **Why not split (Python + R):** Worst of both worlds. Two ecosystems, two debug workflows, parquet-as-IPC, two CI configs.

### Storage: JSON files (DuckDB later if needed)
- Strategy docs, token vocabulary, JSON caches: plain files
- Cached API responses: JSON or parquet
- Time-series data (e.g., LeagueLogs market value snapshots for trend derivation): parquet
- **DuckDB** when SQL queries against accumulated history get useful. No need for SQLite/Postgres at this scale.

### Data Fetching: `httpx` + `nfl_data_py`
- `httpx` for async REST calls (LeagueLogs, Sleeper, Odds API, FantasyPros, NWS)
- `nfl_data_py` for nflverse data (it IS the Python interface to nflverse — not an alternative to it)
- For nflverse datasets not yet exposed in `nfl_data_py`, download Parquet directly from `github.com/nflverse/nflverse-data/releases`

### Claude API: `anthropic` SDK
- Sonnet for Pass 1 and Pass 3 (structured tasks)
- Opus for Pass 2 and merge (judgment-heavy synthesis)
- Haiku for any high-frequency lightweight calls (planner stage of ad hoc generator if cost becomes an issue)

### Dashboard: Streamlit + Altair
- **Streamlit** for the framework — lowest setup cost, decent default aesthetics, matches "limited interactive" goal
- **Altair** as primary chart library — declarative grammar of graphics, beautiful defaults, closest Python equivalent to ggplot
- **Plotly** for charts that need richer interactivity (zoomable timelines, cross-filtering)
- **Custom theme via `config.toml`** — pick 2-3 accent colors and apply consistently. Avoid default Streamlit pink.

---

## Data Sources Summary

Full reference: `data_sources.txt`

| Source | Role | Auth | Budget |
|---|---|---|---|
| **LeagueLogs** | Player market values (consensus ADP-anchored), nfl-state, blurbs | None | Free |
| **Sleeper** | Roster/league/matchup data, projections | None | Free |
| **nfl_data_py / nflverse** | Production stats, snap %, target share, NGS, EPA | None | Free |
| **The Odds API** | Vegas lines (free) + player props (paid) | API key | 500 credits/mo |
| **FantasyPros** | Projections + news | API key | Plan-dependent |
| **NFL official** | Practice participation, injury designations, inactives | None | Free |
| **NWS API** | Weather forecast (TBD — replace historical-only datawithbliss) | None | Free |
| **datawithbliss** | Stadium location lookup only (lat/lng + roof type) | None | Free, one-time extract |

**Known gaps:**
- Coverage tendencies (man/zone splits) — PFF only, not currently in stack
- Weather forecast — NWS integration TBD (low effort)
- K/DEF — minimal coverage, intentional. Streaming logic from Vegas + spread + opposing offense rank.

---

## The 4 Output Types

### 1-3. Standard Advisors (start/sit, waivers, trades)
**Pattern:** narrow, predictable API calls.
- User submits a question (e.g., "should I start RB X over RB Y?")
- Python orchestrator parses the question type
- Strategy MD is queried for relevant rules (filter by tags)
- Each rule's `{needs: ...}` block tells Python which data tokens to fetch
- Python fetches ONLY those tokens (not a generic data dump)
- Tightly scoped context + question + relevant rules → Claude API call → structured advice

**Why this matters for cost:** the LLM doesn't parse a giant data blob to find what's relevant. Python does that filtering deterministically. The API call is short and focused.

### 4. Ad Hoc Prompt Generator
**Pattern:** routes the question, doesn't answer it.
- User submits an open-ended question
- ONE Claude API call returns `(data_plan, prompt)`:
  - `data_plan`: which tokens Python should fetch
  - `prompt`: a chatbot-ready prompt template
- Python packages the data per the plan
- User takes both artifacts (data file + prompt) into their own Claude session (not API)
- The chatbot session has full conversational flexibility (follow-ups, what-ifs) without each turn billing the API

**Cost design:** Pays one API call per ad-hoc question. The chat conversation that follows is free (uses the user's Claude subscription).

---

## Cost Management Strategy

The 4 fixed output types are the primary cost-control pattern: each is a known, narrow API call with predictable token usage.

**Model assignment by task:**
- **Sonnet:** Pass 1 (extraction), Pass 3 (data tagging), all standard advisor calls
- **Opus:** Pass 2 (synthesis) and merge — variance reduction matters most here
- **Haiku:** reserved for any high-frequency planner stages if costs balloon

**Estimated synthesis costs (one-time):**
- Pass 1 across 173 transcripts on Sonnet: ~$5
- Pass 2 + merge on Opus across 4 strategy files (3 runs each + merge): ~$60-90
- Pass 3 on Sonnet across 4 files: ~$2
- Total one-time investment: ~$70-100

**Estimated runtime costs (in season):**
- TBD based on usage. Each fixed-type advisor call should be cheap (focused context).
- Ad hoc generator pays one API call per question, not per turn.
- Dashboard caches Claude outputs to avoid re-paying for the same analysis.

---

## Cache Invalidation for the Dashboard

Caching Claude outputs in the dashboard creates a staleness question: a Tuesday recommendation is half-stale by Sunday morning when injury news drops.

**Design principle:** show the **input snapshot** alongside the cached output, not just the timestamp.

Example display:
```
Generated Tuesday 9:00 AM
Inputs: Wednesday practice = Limited, Vegas total = 47.5, weather forecast = clear
[Regenerate if any input has changed]
```

This lets the user (or the system) detect when conditions have shifted enough to warrant regeneration.

---

## Out-of-Season Constraint & V2 Feedback Plan

**Current limitation:** It is currently the off-season. There is no live feedback loop to validate whether advisor recommendations are accurate.

**V1 strategy:** Build the architecture and the strategy mind. Validate at the structural level (rules are well-formed, data tags resolve correctly, fixed-type advisors produce coherent output against historical data).

**V2 plan (next season):**
- Log every recommendation alongside the actual outcome (player score, decision validation)
- Build a feedback loop that surfaces patterns where advice was wrong
- Use those patterns to inform Pass 2 prompt refinements OR to add corrective rules to the strategy mind
- The 3-pass synthesis pipeline is designed to be re-runnable. New strategy syntheses can be produced periodically as new content emerges.

---

## File Inventory

### Pipeline prompts
- `FIRST_PASS_PROMPT_v2.md` — extraction prompt (Sonnet)
- `SECOND_PASS_PROMPT_v2.md` — synthesis prompt (Opus, run 3x)
- `SECOND_PASS_MERGE_PROMPT_v2.md` — merge prompt (Opus)
- `THIRD_PASS_PROMPT_v2.md` — data tagging prompt (Sonnet)

### Reference files
- `DATA_TOKEN_VOCABULARY_TEMPLATE.md` — token contract
- `data_sources.txt` — full data source reference
- `ARCHITECTURE.md` — this file

### Data
- `fse2024/` — curated transcript .txt files (55 files for FSE redraft batch)
- (Other batches: flock_dynasty, flock_redraft, fse_dynasty already processed in prior sessions)

### Generated artifacts (to be produced)
- `caches/{batch_name}_cache.json` — Pass 1 output per batch
- `strategy/{batch_name}_strategy.md` — Pass 2 + merge + Pass 3 output per batch

---

## Future Work / Open Questions

### Near-term (V1)
- Lock in the data token vocabulary against actual planned Python fetcher names
- Wire up NWS weather forecast integration
- Run the pipeline against the FSE redraft batch (55 transcripts, the largest batch)
- Re-extract earlier batches with v2 prompts if quality demands it

### V2 (next season)
- Live feedback loop: log recommendations + outcomes, refine strategy mind from results
- Cyclic re-synthesis: schedule periodic re-runs of the synthesis pipeline as new content emerges
- Trend metrics: derive `market_value_trend` locally from accumulated LeagueLogs snapshots (their trend fields are stubbed)

### V2/V3 (advanced features)
- **Monte Carlo simulations.** No polished Python equivalent of nflverse's `nflseedR` exists. ~100-200 lines of numpy/pandas to build:
  - **Lineup MC:** given projection mean + variance, simulate thousands of lineup outcomes; pick highest expected score / win probability
  - **Playoff odds MC:** given current standings + remaining schedule + roster value, simulate rest of season
  - **Trade impact MC:** simulate season with vs. without a trade, compare playoff probabilities
  - These are great dashboard features. Premature for V1.
- **Coverage data.** If PFF Premium becomes affordable, ~5–10% of currently-flagged rules become evaluable. Re-run Pass 3 only.
- **Multi-league support:** the architecture assumes one user / one league. Generalize roster/league context tokens for multi-league use.

### Open questions to revisit
- **Should the merge pass be every 3 runs, or 5?** Diminishing returns past 3, but if a particular synthesis is critical (e.g., FSE redraft, the largest batch), more variance might be worth it.
- **How aggressive should the redraft filter be?** Some "evergreen patterns" hide inside very player-specific takes. Calibration is judgment.
- **Should the dashboard cache Claude outputs at all?** Or always regenerate? Depends on usage patterns and cost tolerance.

---

## Design Principles (the things that should not change)

1. **Pre-filter data deterministically; don't ask the LLM to parse what's important.** This is the cost-management throughline of the entire architecture.
2. **The strategy mind is markdown, not vector-embedded retrieval.** Markdown rules are auditable, editable, and human-readable. RAG-style retrieval would lose this.
3. **Each pass has a single concern.** Extraction, synthesis, merge, tagging are separate so any one can be debugged or re-run independently.
4. **The data layer is a contract.** Tokens in the strategy file MUST match Python fetcher names exactly. Mismatch = silent runtime failure.
5. **Reasoning patterns over player names.** Player-specific takes go stale; reasoning patterns transfer across seasons.
6. **Variance reduction over single-run perfection.** Run synthesis 3x and merge — captures the union of high-quality rules instead of forcing a one-off pick.

---

## How to Onboard a Future LLM Session

If you're a future LLM session picking up this project, here's the suggested reading order:

1. **This file (`ARCHITECTURE.md`)** — high-level system design and rationale
2. **`data_sources.txt`** — what data is available and how
3. **`DATA_TOKEN_VOCABULARY_TEMPLATE.md`** — the contract between strategy and data
4. The pipeline prompts in order (Pass 1 → 2 → Merge → 3) to understand how strategy MDs get produced
5. The current state of strategy MDs (in `strategy/` once produced)
6. The user's most recent message — they'll usually orient you to which subsystem is currently active

The user is the architect; you're the implementer. They make directional decisions; you execute and surface tradeoffs they should weigh in on. Don't refactor architecture without explicit confirmation. Push back on questionable choices but accept their final call.
