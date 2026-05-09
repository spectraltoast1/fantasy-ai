# Technical Architecture

> How the system works. Constitution document — refer here for tech stack, pipeline mechanics, data layer design, and the technical principles that should not change without explicit reason.

**Last reviewed:** 2026-05-08

---

## System Diagram

```
TRANSCRIPT INGESTION (one-time + cyclic re-runs)
─────────────────────────────────────────────────────────────────
  YouTube transcripts (.txt)  ─▶  Pass 1 (Sonnet)  ─▶  JSON cache
                                  per-transcript        per source
                                  rule extraction       per batch

JSON cache  ─▶  Pass 2 (Opus, run 3x)  ─▶  Strategy MD (3 versions)
                                            with applicability tags
                                            and conflicts

Strategy MD x3  ─▶  Pass 2 Merge (Opus)  ─▶  Strategy MD (merged)
                                              best-of merge with
                                              [VARIANCE] flags

Strategy MD  ─▶  Pass 3 (Sonnet)  ─▶  Strategy MD (data-tagged)
                 + token vocabulary    {needs: ...} appended


RUNTIME (4 advisor types)
─────────────────────────────────────────────────────────────────
                              ┌──▶  Start/Sit Advisor (API call)
                              │
  Strategy MD (data-tagged)   ├──▶  Waiver Advisor (API call)
            +                 │
  Live data orchestrator      ├──▶  Trade Advisor (API call)
            +                 │
  User question               └──▶  Ad Hoc Prompt Generator
                                    (returns data_plan + prompt
                                     for separate Claude session
                                     — not API call)


DASHBOARD
─────────────────────────────────────────────────────────────────
  Local data + cached Claude outputs ─▶ Streamlit + Altair dashboard
```

---

## Tech Stack

### Language: Python end-to-end

- Claude Code is materially better at Python than R
- Anthropic SDK is Python-first; LLM tooling ecosystem is 6-12 months ahead in Python
- Async API calls to multiple data sources favor Python's asyncio
- Splitting Python + R = worst of both worlds (two debug workflows, two CI configs, parquet-as-IPC)

### Storage: JSON files; DuckDB only when needed

- Strategy docs, token vocabulary, JSON caches: plain markdown / JSON files
- Cached API responses: JSON or parquet
- Time-series data (LeagueLogs market value snapshots): parquet
- DuckDB when SQL queries against accumulated history get useful — pip-installable, no server, reads parquet/JSON directly. Skip SQLite/Postgres.

### Data Fetching

- `httpx` for async REST calls (LeagueLogs, Sleeper, Odds API, FantasyPros, NWS)
- `nfl_data_py` for nflverse data (it IS the Python interface to nflverse — not an alternative)
- For nflverse datasets not yet exposed in nfl_data_py, download Parquet directly from `github.com/nflverse/nflverse-data/releases`

### Claude API: `anthropic` SDK

- **Sonnet** for Pass 1 (extraction), Pass 3 (data tagging), and runtime advisor calls
- **Opus** for Pass 2 (synthesis) and Merge — judgment-heavy synthesis where reasoning quality matters most
- **Haiku** reserved for any high-frequency planner stages if costs balloon

### Dashboard

- **Streamlit** as framework — lowest setup cost, decent default aesthetics, matches "limited interactive" goal
- **Altair** as primary chart library — declarative grammar of graphics, ggplot-quality aesthetics in Python
- **Plotly** for charts that need richer interactivity (zoomable timelines, cross-filtering)
- **Custom theme via `config.toml`** — pick 2-3 accent colors and apply consistently

---

## The Three-Pass Synthesis Pipeline

The strategy MD files are produced by a 3-pass pipeline (4 if you count the merge step) over curated YouTube transcripts.

### Pass 1: Per-Transcript Rule Extraction
- **Model:** Sonnet
- **Input:** Single `.txt` transcript (NoteGPT auto-transcript, often messy)
- **Output:** Numbered list of rules separated by `\n\n`, stored as one entry in a JSON cache keyed by source filename
- **Prompt:** `FIRST_PASS_PROMPT_v2.md`
- **Critical extraction skill:** Transmute player-specific takes into transferable reasoning patterns. "Doubs is risky against zone" → "When evaluating WRs, weight man/zone success splits against defensive coverage tendency."

### Pass 2: Synthesis to Unified Strategy File
- **Model:** Opus (judgment-heavy — conflict resolution, calibration logic)
- **Input:** JSON cache from Pass 1
- **Output:** Markdown strategy file with structural sections, applicability tags `[REDRAFT]`/`[DYNASTY]`/etc., and a Conflicts appendix
- **Prompt:** `SECOND_PASS_PROMPT_v2.md`
- **Run 3 times** at temperature 0.3–0.5 to produce variance for the merge step

### Pass 2 Merge: Best-Of Across 3 Runs
- **Model:** Opus
- **Input:** Three Pass 2 outputs from independent runs
- **Output:** Single merged strategy file with `[VARIANCE]` flags on retained singletons and threshold disagreements
- **Prompt:** `SECOND_PASS_MERGE_PROMPT_v2.md`
- **Why:** Variance reduction. With 200+ rules per output, "pick the best" loses good rules from runs you didn't pick.

### Pass 3: Data Dependency Tagging
- **Model:** Sonnet (structured tagging, not synthesis)
- **Input:** Merged strategy file + token vocabulary contract
- **Output:** Same strategy file with `{needs: token1, token2, ...}` blocks appended to each rule, plus a Data Coverage Summary
- **Prompt:** `THIRD_PASS_PROMPT_v2.md`
- **Why a separate pass:** When the data layer evolves (add coverage data, swap fetchers), re-run only Pass 3. The strategy file's intellectual content stays stable.

---

## Token Vocabulary Contract

Located at `DATA_TOKEN_VOCABULARY_TEMPLATE.md`. **Contract between the strategy MD files and the Python data orchestrator** — every token used in the strategy file must be defined in the vocabulary; every defined token must map to a Python fetcher function.

Categories: player identity & roster, injury & practice status, player-level usage, player-level efficiency, defense / matchup, game environment, market & consensus, projections, news, league / format / user context, historical / static.

**Availability flags drive runtime behavior:**
- `available` — fetch directly
- `paywalled` — requires paid source not currently in stack
- `paywalled-budgeted` — available but budget-constrained (Odds API player props)
- `gap-low-effort` — needs implementation soon (NWS weather forecast)
- `unavailable` — no acceptable source

---

## Data Sources

Full reference: `data_sources.txt`

| Source | Role | Auth | Notes |
|---|---|---|---|
| LeagueLogs | Market values, blurbs, NFL state | None | Skill positions only; trend fields stubbed at zero |
| Sleeper | League/roster/matchups, projections | None | Projections endpoint |
| nfl_data_py | Production stats, snap %, target share, NGS, EPA | None | Python interface to nflverse |
| The Odds API | Vegas lines (free) + player props (paid) | API key | 500 credits/mo budget |
| FantasyPros | Projections + news | API key | Plan-dependent |
| NFL official | Practice participation, inactives | None | |
| NWS | Weather forecast (TBD integration) | None | Replaces datawithbliss historical |
| datawithbliss | Stadium location only | None | One-time extract for lat/lng + roof type |

**Known data gaps:**
- Coverage tendencies (man/zone) — PFF only
- Weather forecast — NWS integration TBD
- K/DEF — minimal coverage by design

---

## The 4 Output Types — Implementation Pattern

### Fixed Advisors (start/sit, waivers, trades)

Predictable, narrow API calls.

```
1. User submits typed question (e.g. "should I start RB X over RB Y?")
2. Python parses question type and entities
3. Filter strategy MD rules by applicability tags
4. For each relevant rule, parse its {needs: ...} block
5. Fetch ONLY the listed data tokens (deterministic pre-filter)
6. Assemble: tight context + question + rules invoked
7. Single Claude API call → structured recommendation
8. Log: question, rules invoked, data fetched, output, timestamp
```

The LLM never receives a generic data dump and never has to decide what's relevant. Python does that filtering deterministically.

### Ad Hoc Prompt Generator

Routes the question; doesn't answer it.

```
1. User submits open-ended question
2. ONE Claude API call returns (data_plan, prompt)
   - data_plan: which tokens Python should fetch
   - prompt: chatbot-ready prompt template
3. Python packages the data per the plan
4. User takes both artifacts (data file + prompt) into a separate Claude session
   (web/desktop chat, not API)
5. Conversational follow-ups happen there for free against the user's subscription
```

Pays one API call per ad hoc question. Subsequent chat is free (subscription-billed).

---

## Cost Management Mechanism

**Architectural cost control:** the four output types are fixed surfaces with predictable token usage. No open-ended chat-style API calls.

**Model assignment by task:**
- Sonnet: Pass 1, Pass 3, fixed advisors, ad hoc planner
- Opus: Pass 2, Merge (variance reduction matters most)
- Haiku: held in reserve

**Pre-filtering as cost control:** Python filters strategy rules + data tokens before assembling the API call. Smaller context → smaller cost. The LLM is not paid to parse data it doesn't need.

**Caching:**
- Per-source TTLs documented in `data_sources.txt`
- Dashboard caches Claude outputs with input snapshot stamping for cache invalidation logic
- Re-fetch when input snapshot has materially changed, not on a fixed timer alone

**Estimated synthesis costs (one-time):**
- Pass 1 across all transcripts on Sonnet: ~$5
- Pass 2 + Merge on Opus across 4 batches: ~$70-100
- Pass 3 on Sonnet across 4 files: ~$2

**Runtime costs:** TBD; tracked from day one.

---

## Cache Invalidation Pattern

Cached Claude outputs in the dashboard get stale (a Tuesday recommendation is half-stale by Sunday morning when injury news drops).

**Design rule:** every cached output stores its input snapshot, not just its timestamp.

```
Generated Tuesday 9:00 AM
Inputs: Wednesday practice = Limited
        Vegas total = 47.5
        Weather forecast = clear
[Regenerate if any input has changed]
```

The dashboard surfaces the input snapshot inline. The user (or the system) detects when conditions have shifted enough to warrant regeneration.

---

## Technical Design Principles

The things that should not change without explicit reason. If you find yourself wanting to change one of these, escalate to a roadmap discussion first.

1. **Pre-filter data deterministically; don't ask the LLM to parse what's important.** This is the cost-management throughline of the entire architecture.
2. **The strategy mind is markdown, not vector-embedded retrieval.** Markdown rules are auditable, editable, and human-readable. RAG would lose this.
3. **Each pass has a single concern.** Extraction, synthesis, merge, tagging are separate so any one can be debugged or re-run independently.
4. **The data layer is a contract.** Tokens in the strategy file MUST match Python fetcher names exactly. Mismatch = silent runtime failure.
5. **Reasoning patterns over player names.** Player-specific takes go stale; reasoning patterns transfer across seasons.
6. **Variance reduction over single-run perfection.** Run synthesis 3x and merge — captures the union of high-quality rules instead of forcing a one-off pick.
7. **Single source of truth per fact.** Constitution docs hold current state. Journals record evolution. Never duplicate.

---

## Known Architectural Gaps (TBD)

These are areas where the architecture is intentionally underspecified pending decisions in PRODUCT_ROADMAP.md Block 1-3 open questions. Future LLMs picking up this project should NOT invent answers to these — flag them and ask the user.

- **Repository / project structure.** Where Python code lives, where generated artifacts live. Currently undecided.
- **Secrets management.** No pattern decided. Recommended: `.env` at project root, loaded via `python-dotenv`, gitignored.
- **Strategy file count at runtime.** Currently the pipeline produces 4 batch files. The runtime orchestrator likely needs 1 redraft + 1 dynasty file. Either add a fifth merge step (cross-batch, per format), or have the orchestrator query both batch files at runtime. Decision pending.
- **Token vocabulary status.** DATA_TOKEN_VOCABULARY_TEMPLATE.md is currently populated as a draft. It is NOT yet locked — token names are subject to revision before Pass 3 runs. Once locked, the file should be renamed `DATA_TOKEN_VOCABULARY.md` (drop "TEMPLATE") to signal stability.
- **Pipeline never tested end-to-end.** Pass 1 v2 prompt has not been run against any transcript yet. The first test extraction is the most important $0.10 in the project — it'll reveal prompt quality issues that no design review can catch. Recommended: run Pass 1 on ONE FSE redraft transcript before bulk execution.
- **User-specific runtime config not defined.** League format, scoring, league size, Sleeper league_id, Sleeper user_id, FantasyPros account, Odds API account — none captured. Recommended: a `config.local.json` (gitignored) holding these values.

## File Inventory

### Constitution docs (rarely change)
- `PROJECT_OVERVIEW.md` — why and what
- `PRODUCT_ROADMAP.md` — when and phasing
- `TECHNICAL_ARCHITECTURE.md` — how (this file)

### Pipeline prompts
- `FIRST_PASS_PROMPT_v2.md`
- `SECOND_PASS_PROMPT_v2.md`
- `SECOND_PASS_MERGE_PROMPT_v2.md`
- `THIRD_PASS_PROMPT_v2.md`

### Reference files
- `DATA_TOKEN_VOCABULARY_TEMPLATE.md` — token contract
- `data_sources.txt` — full data source reference

### Per-session evolution
- `journal/INDEX.md` — chronological one-liners across all sessions
- `journal/_TEMPLATE.md` — template for new entries
- `journal/YYYY-MM-DD-slug.md` — individual session entries

### Data
- `Default_medium_*.txt` — curated transcript files (55 FSE redraft batch)

### Generated artifacts (to be produced)
- `caches/{batch_name}_cache.json` — Pass 1 output per batch
- `strategy/{batch_name}_strategy.md` — Pass 2 + merge + Pass 3 output per batch

### Archive
- `.archive/` — old monolithic ARCHITECTURE.md, JOURNAL.md, PROJECT_SCOPE.md (superseded by current structure)
