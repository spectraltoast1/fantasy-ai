# 2026-05-08 — Doc restructure into constitutional + journal

**LLM session:** Claude Opus via Cowork
**Goal:** Split monolithic ARCHITECTURE + PROJECT_SCOPE into three orthogonal constitution docs; restructure journal into per-session files
**Status:** wrapped

---

## What was done

- Identified that ARCHITECTURE.md and PROJECT_SCOPE.md had significant overlap and mixed constitution-level facts with journal-style session notes
- Designed a clean separation: each fact lives in exactly one place
  - Project Overview = WHY and WHAT (no implementation, no scheduling)
  - Product Roadmap = WHEN and PHASING (no implementation, no philosophy)
  - Technical Architecture = HOW (no business reasoning, no scheduling)
  - Journal = WHAT HAPPENED (refers to constitution docs; never duplicates facts)
- Created `journal/` subfolder structure with template, index, and per-session files
- Restructured the prior architecture wrap session as `journal/2026-05-08-architecture-pipeline-wrapped.md`
- Created this entry to record the restructure itself
- Archived the old monolithic docs to `.archive/`

## Decisions made

- **Three constitution docs, not one.** Project Overview / Product Roadmap / Technical Architecture, each scoped to a single concern. → captured in TECHNICAL_ARCHITECTURE.md design principle 7 ("single source of truth per fact")
- **Per-session journal files in `journal/`.** Filename convention `YYYY-MM-DD-slug.md`. Each entry ends with "Next session should..." to give the next LLM a starting point. → captured in journal/_TEMPLATE.md
- **Journal INDEX.md provides cold-start chronology** for new LLM sessions without forcing them to read every entry.
- **Old docs archived, not deleted.** `.archive/` retains the monolithic versions in case content was missed in the split. Can be deleted once the new structure proves out.

## Deferred / not done

- Mirroring scope to Notion explicitly deferred. User confirmed they don't actually need a Notion mirror — markdown is sufficient for solo project. Notion can be added later if mobile access becomes valuable.

## Open questions surfaced

- None new. The open questions in PRODUCT_ROADMAP.md are the gate to forward progress.

## Files created / modified

- `PROJECT_OVERVIEW.md` — created (split from old ARCHITECTURE + PROJECT_SCOPE)
- `PRODUCT_ROADMAP.md` — created (split from old PROJECT_SCOPE + ARCHITECTURE phasing)
- `TECHNICAL_ARCHITECTURE.md` — created (split from old ARCHITECTURE)
- `journal/_TEMPLATE.md` — created
- `journal/INDEX.md` — created
- `journal/2026-05-08-architecture-pipeline-wrapped.md` — created (reformatted from old JOURNAL.md entry)
- `journal/2026-05-08-doc-restructure.md` — created (this entry)
- `.archive/ARCHITECTURE.md` — archived
- `.archive/PROJECT_SCOPE.md` — archived
- `.archive/JOURNAL.md` — archived

---

## Next session should...

- Resolve the top open question in PRODUCT_ROADMAP.md: **lock the data token vocabulary against actual planned Python fetcher names**. This is the gate to all of Phase 1c onward.
- Once vocabulary is locked, decide between two paths:
  1. Test Pass 1 on one FSE redraft transcript to validate v2 prompt quality before bulk execution (~$0.10, 15-30 min)
  2. Decide whether to re-extract the three earlier batches with v2 prompts (~$3-5, larger commitment)
