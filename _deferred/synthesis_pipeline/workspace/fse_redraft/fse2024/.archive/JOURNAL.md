# Project Journal

> Append-only log of meaningful work across LLM sessions. Each entry captures what was done, decided, deferred, and what's open. Future LLMs and future-self should read the most recent 2–3 entries before starting work.

**How to use this file:**
- Add a new entry at the TOP of the log section after every meaningful session
- Never edit past entries — append corrections to the new entry instead
- "Meaningful" = made decisions, produced artifacts, or surfaced new questions. Pure code-debugging sessions don't need entries unless they revealed a design issue.
- Keep entries scannable. Bullet points over prose. Specifics over summaries.

**Entry template (copy this for new entries):**

```markdown
---

## YYYY-MM-DD — Session Title

**LLM session:** model + interface (e.g., "Claude Opus via Cowork", "Claude Code Sonnet")
**Session goal:** one-line goal that motivated this session
**Status:** [active | wrapped | deferred]

### What was done
- bullet
- bullet

### Decisions made
- **[decision]** — short rationale
- **[decision]** — short rationale

### Deferred / not done
- bullet (and why deferred)

### Open questions surfaced
- bullet
- bullet

### Files created / modified
- path/to/file.md — what changed

### Next session should...
- pick up at X
- decide between Y and Z
```

---

# Log

---

## 2026-05-08 — Architecture and pipeline prompts wrapped

**LLM session:** Claude Opus via Cowork
**Session goal:** finalize the strategy synthesis pipeline before processing the FSE redraft transcript batch
**Status:** wrapped (next: product scoping, then execute Pass 1 on FSE redraft)

### What was done
- Cleaned up the FSE redraft transcript batch (212 → 55 files: deduped, removed Dynasty/MNF/TNF/Pick'em/Best Ball, curated by week + decision type)
- Reviewed three existing strategy MD outputs (flock_dynasty, flock_redraft, fse_dynasty) and identified shared weakness: all three are silently truncated by the v1 synthesis prompt
- Drafted a four-prompt pipeline (v2): FIRST_PASS → SECOND_PASS → SECOND_PASS_MERGE → THIRD_PASS
- Built the data token vocabulary contract (DATA_TOKEN_VOCABULARY_TEMPLATE.md) as the bridge between strategy MD files and Python fetcher functions
- Restructured data_sources.txt to reflect the actual stack (Sleeper, nfl_data_py, LeagueLogs, Odds API, FantasyPros, NWS, NFL official)
- Wrote ARCHITECTURE.md as the single onboarding doc for future LLM sessions

### Decisions made
- **Three-pass pipeline (Pass 1, Pass 2, Pass 3) plus a merge step** — separates extraction, synthesis, and tagging into independent re-runnable steps
- **Model assignment: Sonnet for Pass 1 + Pass 3; Opus for Pass 2 + merge** — judgment-heavy synthesis gets Opus; structured extraction/tagging stays on Sonnet
- **Run Pass 2 three times at temperature 0.3–0.5, then merge** — captures the union of high-quality rules instead of forcing a one-of-three pick
- **Anti-truncation marker pattern** — explicit `<!-- SYNTHESIS INCOMPLETE -->` line at clean section break preferred over silent truncation
- **Player takes get transmuted to reasoning patterns, not skipped** — the most important first-pass extraction skill, especially for in-season redraft content
- **Stay all-Python; do not split with R** — Claude Code is materially better at Python; LLM ecosystem is Python-first; visual viz benefit of R is outweighed by operational complexity
- **JSON files now, DuckDB later if needed** — no premature SQL setup
- **Streamlit + Altair for the dashboard** — Altair gives ggplot-quality aesthetics in Python
- **Ad hoc generator returns (data_plan, prompt) for the user to paste into a separate Claude session** — uses subscription for chat, only pays API for the routing/planning step
- **Drop datawithbliss historical weather; keep only stadium location data; add NWS forecast** — historical weather doesn't inform forward decisions
- **K/DEF intentionally thin in data layer; advisor hedges confidence on these calls** — Vegas + spread is sufficient for streaming logic
- **LeagueLogs market_value treated as strong signal** (multi-source consensus ADP-anchored, normalized, validated against other rankings) — but flag deep-roster (rank 150+) values as projection-fallback rather than consensus

### Deferred / not done
- Pass 1 has NOT been run against any transcript batch yet with v2 prompts
- Pass 2/3 have NOT been run against new caches yet
- NWS weather forecast integration NOT implemented
- Token vocabulary NOT yet aligned to actual planned Python fetcher names (still a template)
- Dashboard NOT started
- Live feedback loop deferred to V2 (out-of-season, no live signal available)

### Open questions surfaced
- What's the actual measurable success criterion for v1?
- What is and isn't in scope for v1?
- Should the merge step run on every batch or only when variance audit suggests it's worth the cost?
- How aggressive should the redraft player-take filter be? Some "evergreen patterns" hide inside very player-specific takes — calibration is judgment.
- Should the dashboard cache Claude outputs at all, or always regenerate?

### Files created / modified
- `FIRST_PASS_PROMPT_v2.md` — created
- `SECOND_PASS_PROMPT_v2.md` — created
- `SECOND_PASS_MERGE_PROMPT_v2.md` — created
- `THIRD_PASS_PROMPT_v2.md` — created
- `DATA_TOKEN_VOCABULARY_TEMPLATE.md` — created and updated through stack refinements
- `data_sources.txt` — restructured from raw notes into reference doc
- `ARCHITECTURE.md` — created as canonical project overview
- `JOURNAL.md` — created (this file)

### Next session should...
- Wrap up product scoping (PROJECT_SCOPE.md) and mirror to the Product connector
- Lock the data token vocabulary against actual Python fetcher names
- Run a sample Pass 1 extraction on ONE transcript to validate v2 prompt quality before bulk execution
- Decide whether to re-extract earlier batches with v2 prompts or accept the existing strategy MD files as v1 baseline
