# Journal Index

Chronological one-liner per session entry. Newest at top.

For full entries, open the corresponding file in `journal/`.

For LLM cold-start: read this file, then the most recent 1-2 full entries. Combined with the three constitution docs (PROJECT_OVERVIEW, PRODUCT_ROADMAP, TECHNICAL_ARCHITECTURE), that's enough context to pick up.

---

## 2026

### 2026-05-09

- **2026-05-15-reorg-v2** - serious product scoping and cutting. focusing v1 on a usable, python powered dashboard for redraft only. purposefully not biting off more than can be chewed at one time. pushed AI analysis to v2 and complex data analytics to v3. new next steps are pulling historical nfl data and poking around to find relevant trends to track for in-season dashboards.

- **2026-05-09-reorg** — Resolved the planned-vs-built architecture gap. V1 redirected from transcript-synthesis to interview-derived strategy doc. Synthesis pipeline frozen at `_deferred/synthesis_pipeline/`. Constitution docs rewritten. STATUS.md added. Code restructure deferred to a dedicated session. #appended

### 2026-05-08

- **2026-05-08-final-sweep** — Final sweep before extended break. Reorganized PRODUCT_ROADMAP open questions into priority blocks. Added "Known Architectural Gaps" section to TECHNICAL_ARCHITECTURE. Captured 10 things future LLMs need to know that aren't obvious from cold-reading the docs. #appended
- **2026-05-08-doc-restructure** — Split monolithic ARCHITECTURE + PROJECT_SCOPE into three orthogonal constitution docs. Moved journal to per-session files in `journal/` subfolder. Archived old docs. #appended
- **2026-05-08-architecture-pipeline-wrapped** — Drafted the four pipeline prompts (Pass 1, Pass 2, Merge, Pass 3). Built token vocabulary template. Restructured data_sources.txt. Created initial monolithic architecture and scope docs (later split). #appended

---

## How to add a new entry

Add an entry to the top of this document. If updates require more detail than a few sentences, summarize here and append a longer entry. Include the journal title to any commit descriptions.
