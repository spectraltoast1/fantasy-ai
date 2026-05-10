# Synthesis Pipeline — Deferred to V2

> **This folder is frozen for v1.** Do not reference these files from active v1 work in `project_management/` or `application/`. The contents are preserved here so v2 can resume cleanly.

---

## What this was

An attempt to synthesize a "strategy mind" markdown document for the AI advisor by feeding curated YouTube transcripts from trusted fantasy football creators through a multi-pass LLM pipeline. The output of the pipeline (a tagged strategy MD with applicability tags and data-dependency tags) was originally intended to be the canonical strategy document the runtime advisor reasons against.

## Why it's deferred

For v1, the strategy document is being produced via a **Claude-driven interview** with the user instead — much faster, cheaper, and good enough as a starting point. The transcript-synthesis approach is preserved here because:

1. The pipeline design itself (extraction → synthesis → merge → tag) is sound and may be the right v2 path once v1 has proven the advisor's value.
2. The collected transcripts and intermediate caches represent real work — re-collecting them later would cost time and a paid YouTube transcription tool.
3. The four prompts are non-trivial artifacts. Rebuilding them from scratch would lose accumulated calibration.

## What's in this folder

### Pipeline prompts (the blueprints)

- `FIRST_PASS_PROMPT_v2.md` — per-transcript rule extraction (Sonnet)
- `SECOND_PASS_PROMPT_v2.md` — synthesis to unified strategy MD (Opus, run 3x at temp 0.3-0.5)
- `SECOND_PASS_MERGE_PROMPT_v2.md` — best-of merge across 3 runs (Opus)
- `THIRD_PASS_PROMPT_v2.md` — data-dependency tagging via token vocabulary (Sonnet)

### Token vocabulary contract

- `DATA_TOKEN_VOCABULARY_TEMPLATE.md` — the contract Pass 3 was designed to tag against. Was never locked against actual fetcher names. Re-validate against `application/data/fetchers/*` before any v2 Pass 3 run.

### `workspace/` (gitignored — work in progress)

The actual synthesis workshop, preserved as it was when v1 reorg started:

- **Raw transcripts**: `flock_dynasty/`, `flock_redraft/`, `fse_dynasty/`, `fse_redraft/` (NoteGPT auto-transcripts of curated YouTube videos from Flock Fantasy and Fantasy Sports Experts)
- **Pipeline scripts**:
  - `download_transcripts.py` — pulls transcripts from YouTube (uses `playlists.json` for source list)
  - `run_all.py` — orchestrates Pass 1 across a batch
  - `insights.py` — utilities used by `run_all.py`
- **Pass 1 outputs** (caches): `flock_dynasty_insights_cache.json`, `flock_redraft_cache.json`, `fse_dynasty_cache.json`. The fse_redraft batch cache was never produced — that's the unrun extraction.
- **Pass 2 outputs** (v1 prompts, known-truncated): `flock_dynasty_strategy.md`, `flock_redraft_strategy.md`, `fse_dynasty_strategy.md`. These were produced by an earlier prompt iteration and are not canonical.
- `playlists.json` — source playlist URLs
- `run_all.log` — last run's log

## Pipeline status when frozen (2026-05-09)

- v1 prompts → produced 3 strategy MDs (above), all silently truncated. Known-broken; archaeology only.
- v2 prompts → drafted (this folder) but never run end-to-end. **The first $0.10 — running Pass 1 on a single transcript with the v2 prompt — was never executed.** That's the most important validation step before any future bulk run.
- Token vocabulary → populated as a draft, never locked against actual Python fetcher names.
- 4 batches: 3 had Pass 1 runs with v1 prompts (caches above); the FSE redraft batch (55 transcripts, the largest) was the next planned Pass 1 run and never happened.

## How to resume in v2

1. Read `project_management/PROJECT_OVERVIEW.md` for v1 outcomes — what worked in the advisor with the interview-derived strategy, what didn't. That tells you what kind of strategy rules actually matter at runtime, which sharpens what synthesis needs to produce.
2. Validate the v2 Pass 1 prompt: run it on **one** transcript from any batch, read the output critically. If the output is high-quality raw material, proceed. If not, iterate the prompt before bulk execution.
3. Lock the token vocabulary against `application/data/fetchers/*`. Every `available` token must map to a fetcher; every fetcher should map to (at least one) token.
4. Decide whether to re-run Pass 1 on the three earlier batches with v2 prompts (~$3-5 in Sonnet) or accept the v1 caches as good-enough.
5. Run Pass 2 three times per batch at temperature 0.3-0.5 → run Merge → run Pass 3.
6. Diff the synthesized strategy doc against the interview-derived v1 strategy doc. Where they disagree is where the v2 synthesis is teaching you something new.

## What absolutely should NOT happen

- Active v1 docs (`project_management/PROJECT_OVERVIEW.md`, `PRODUCT_ROADMAP.md`, `TECHNICAL_ARCHITECTURE.md`) should not reference this folder as a current dependency. References here belong in a "Deferred capabilities" section or in journal entries about why this was deferred.
- The runtime advisor in `application/` should not be coded to load any file from this folder. The advisor reads `application/strategy/strategy_redraft.md` (the interview-derived doc), not anything here.
- `application/data/fetchers/` should not be reshaped to fit this vocabulary template. The vocabulary should be reshaped to fit the fetchers, when v2 begins.
