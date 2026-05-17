# 2026-05-08 — Architecture and pipeline prompts wrapped

**LLM session:** Claude Opus via Cowork
**Goal:** Finalize the strategy synthesis pipeline before processing the FSE redraft transcript batch
**Status:** wrapped

---

## What was done

- Cleaned up the FSE redraft transcript batch (212 → 55 files: deduped, removed Dynasty/MNF/TNF/Pick'em/Best Ball, curated by week + decision type)
- Reviewed three existing strategy MD outputs (flock_dynasty, flock_redraft, fse_dynasty) and identified shared weakness: all three are silently truncated by the v1 synthesis prompt
- Drafted a four-prompt pipeline (v2): FIRST_PASS → SECOND_PASS → SECOND_PASS_MERGE → THIRD_PASS
- Built the data token vocabulary contract (DATA_TOKEN_VOCABULARY_TEMPLATE.md) as the bridge between strategy MD files and Python fetcher functions
- Restructured data_sources.txt into reference doc reflecting the actual stack (Sleeper, nfl_data_py, LeagueLogs, Odds API, FantasyPros, NWS, NFL official)
- Wrote ARCHITECTURE.md as monolithic project overview (later split into three constitution docs)

## Decisions made

- **Three-pass pipeline (Pass 1, Pass 2, Pass 3) plus a merge step.** Separates extraction, synthesis, and tagging into independent re-runnable steps. → captured in TECHNICAL_ARCHITECTURE.md
- **Model assignment: Sonnet for Pass 1 + Pass 3; Opus for Pass 2 + merge.** Judgment-heavy synthesis gets Opus; structured extraction/tagging stays on Sonnet. → captured in TECHNICAL_ARCHITECTURE.md
- **Run Pass 2 three times at temperature 0.3–0.5, then merge.** Captures the union of high-quality rules instead of forcing a one-of-three pick. → captured in TECHNICAL_ARCHITECTURE.md
- **Anti-truncation marker pattern.** Explicit `<!-- SYNTHESIS INCOMPLETE -->` line at clean section break preferred over silent truncation. → captured in pipeline prompts
- **Player takes get transmuted to reasoning patterns, not skipped.** The most important first-pass extraction skill, especially for in-season redraft content. → captured in FIRST_PASS_PROMPT_v2.md
- **Stay all-Python; do not split with R.** Claude Code is materially better at Python; LLM ecosystem is Python-first. → captured in TECHNICAL_ARCHITECTURE.md
- **JSON files now, DuckDB later if needed.** No premature SQL setup. → captured in TECHNICAL_ARCHITECTURE.md
- **Streamlit + Altair for the dashboard.** Altair gives ggplot-quality aesthetics in Python. → captured in TECHNICAL_ARCHITECTURE.md
- **Ad hoc generator returns (data_plan, prompt) for the user to paste into a separate Claude session.** Uses subscription for chat, only pays API for the routing/planning step. → captured in TECHNICAL_ARCHITECTURE.md
- **Drop datawithbliss historical weather; keep only stadium location data; add NWS forecast.** → captured in data_sources.txt
- **K/DEF intentionally thin in data layer; advisor hedges confidence on these calls.** Vegas + spread is sufficient for streaming logic. → captured in PROJECT_OVERVIEW.md non-goals
- **LeagueLogs market_value treated as strong signal** (multi-source consensus ADP-anchored, normalized, validated). Flag deep-roster (rank 150+) values as projection-fallback rather than consensus.

## Deferred / not done

- Pass 1 NOT yet run against any transcript batch with v2 prompts
- Pass 2/3 NOT yet run against new caches
- NWS weather forecast integration NOT implemented
- Token vocabulary NOT yet aligned to actual Python fetcher names (still a template)
- Dashboard NOT started
- Live feedback loop deferred to V2 (out-of-season)

## Open questions surfaced

- What's the actual measurable success criterion for v1?
- What is and isn't in scope for v1?
- Should the merge step run on every batch or only when variance audit suggests it's worth the cost?
- How aggressive should the redraft player-take filter be?
- Should the dashboard cache Claude outputs at all?

## Files created / modified

- `FIRST_PASS_PROMPT_v2.md` — created
- `SECOND_PASS_PROMPT_v2.md` — created
- `SECOND_PASS_MERGE_PROMPT_v2.md` — created
- `THIRD_PASS_PROMPT_v2.md` — created
- `DATA_TOKEN_VOCABULARY_TEMPLATE.md` — created and refined
- `data_sources.txt` — restructured into reference doc
- `ARCHITECTURE.md` — created (later archived in doc restructure)
- `PROJECT_SCOPE.md` — created (later archived in doc restructure)
- `JOURNAL.md` — created (later archived in doc restructure)

---

## Next session should...

- Lock the data token vocabulary against actual Python fetcher names
- Test Pass 1 on one transcript before bulk execution
- Decide whether to re-extract earlier batches with v2 prompts
