# Journal Index

Chronological one-liner per session entry. Newest at top.

For full entries, open the corresponding file in `journal/`.

For LLM cold-start: read this file, then the most recent 1-2 full entries. Combined with the three constitution docs (PROJECT_OVERVIEW, PRODUCT_ROADMAP, TECHNICAL_ARCHITECTURE), that's enough context to pick up.

---

## 2026

### 2026-05-08

- **2026-05-08-final-sweep** — Final sweep before extended break. Reorganized PRODUCT_ROADMAP open questions into priority blocks. Added "Known Architectural Gaps" section to TECHNICAL_ARCHITECTURE. Captured 10 things future LLMs need to know that aren't obvious from cold-reading the docs.
- **2026-05-08-doc-restructure** — Split monolithic ARCHITECTURE + PROJECT_SCOPE into three orthogonal constitution docs. Moved journal to per-session files in `journal/` subfolder. Archived old docs.
- **2026-05-08-architecture-pipeline-wrapped** — Drafted the four pipeline prompts (Pass 1, Pass 2, Merge, Pass 3). Built token vocabulary template. Restructured data_sources.txt. Created initial monolithic architecture and scope docs (later split).

---

## How to add a new entry

1. Copy `journal/_TEMPLATE.md` to `journal/YYYY-MM-DD-slug.md`
2. Fill in the entry
3. Add a one-liner to this INDEX.md at the top of the most recent date's section

This index is the only file that gets edited across sessions. Individual entries are append-only.
