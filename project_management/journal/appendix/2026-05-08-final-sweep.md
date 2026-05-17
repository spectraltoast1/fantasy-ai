# 2026-05-08 — Final session sweep before extended break

**LLM session:** Claude Opus via Cowork
**Goal:** Identify lingering questions and missing context before user wraps for hours/days. Surface gaps that could otherwise stall a future LLM session picking up cold.
**Status:** wrapped — user is leaving for extended break

---

## What was done

- Read all current constitution docs and pipeline prompts critically, looking specifically for: missing context, unresolved questions, internal inconsistencies, and assumptions that would block a future LLM cold-start
- Updated PRODUCT_ROADMAP.md to reorganize Open Questions into three priority blocks (Critical / Important / Defer-able) and added 6 new questions surfaced during the sweep
- Added a "Known Architectural Gaps (TBD)" section to TECHNICAL_ARCHITECTURE.md flagging things that are intentionally underspecified, so future LLMs flag them rather than inventing answers
- Wrote this entry to capture the sweep

## Decisions made

- **Open questions reorganized into priority blocks.** Block 1 = critical gates; Block 2 = important but defer-able; Block 3 = defer to later phases. → captured in PRODUCT_ROADMAP.md
- **TECHNICAL_ARCHITECTURE.md now explicitly documents what's underspecified.** Future LLMs are instructed not to invent answers to TBD items. → captured in TECHNICAL_ARCHITECTURE.md
- **Token vocabulary file status clarified.** Currently a populated draft. Not locked. Will be renamed when locked. → captured in TECHNICAL_ARCHITECTURE.md gaps section.
- **No new constitution-level decisions made in this sweep.** This was a documentation-quality session, not a direction-setting session.

## Top gaps surfaced (full list in PRODUCT_ROADMAP.md Block 1-3)

### Critical (block forward progress)

1. **User's actual league configuration unknown.** PPR/Half/Standard, 1QB/SF, league size. Drives LeagueLogs profile selection and projection scoring assumptions. Without this, the orchestrator cannot fetch correct data.
2. **Sleeper league_id + user_id not captured.** Required to identify "your roster" vs others.
3. **API key/account status unconfirmed.** Anthropic key assumed exists; FantasyPros plan and Odds API signup unknown.
4. **Token vocabulary not locked.** Currently populated draft. Gates all Pass 3 work.
5. **Strategy file count at runtime is ambiguous.** Pipeline produces 4 batch files; orchestrator likely needs 1 redraft + 1 dynasty. Either add a 5th cross-batch merge step or have orchestrator query both batch files at runtime. Docs were inconsistent on this — now flagged in TECHNICAL_ARCHITECTURE.md.

### Important (defer-able by 1-2 sessions)

6. NWS forecast integration: V1 or V2?
7. Re-extract earlier 3 batches with v2 prompts: yes/no?
8. Test cases for V1 validation: which historical scenarios?
9. Cost ceiling for Pass 2 + merge: hard cap?
10. Dashboard V1 chart confirmation.

### Defer-able

11. Repository / project structure (where Python code lives).
12. Secrets management plan.
13. Git / version control plan.
14. Dashboard hosting model (always-on vs on-demand).

## Things a future LLM should know that aren't fully obvious from reading docs cold

1. **The pipeline has never been tested end-to-end.** Even one transcript through Pass 1 v2 has not been validated. The first extraction will likely surface prompt-quality issues that no design review caught. Strongly recommend testing Pass 1 on ONE transcript before any bulk execution.

2. **The four strategy MD files in `.archive/` are NOT canonical.** They were produced by v1 prompts and have known truncation issues. They are reference-only, kept as archaeology. Don't use them as ground truth for any rule the system needs to evaluate.

3. **The 55 transcripts in this folder are the FSE redraft batch only.** The other three batches (flock_dynasty, flock_redraft, fse_dynasty) live elsewhere — possibly in another folder on user's machine, possibly only as the JSON caches that were uploaded earlier in the session. Future LLM should ask the user where those original transcripts live before assuming they have access.

4. **The user co-builds with Claude Code.** They write very little code themselves. When proposing implementation plans, structure them so Claude Code can execute them with minimal back-and-forth. The user's job is directional decisions and debugging assistance, not code authorship.

5. **The user is enthusiastic about complexity and that's intentional.** Don't reflexively suggest simplifying the architecture. The complexity is part of why the project is fun for them. Push back on scope CREEP (new features) but not scope COMPLEXITY (depth of existing features).

6. **The "Anthropic Product Management skill" the user mentioned is a Claude capability, not an external tool.** They considered Notion mirroring but decided against it. Markdown is the canonical source.

7. **PFF was declined for cost reasons** ($9.99/mo annual). Don't propose adding it without acknowledging this constraint. Coverage-tendency rules are tagged `[paywalled]` deliberately.

8. **The K/DEF data layer is intentionally thin.** Streaming logic is Vegas-driven. Don't add data sources for K/DEF without a strong reason.

9. **Out-of-season constraint is real.** No live feedback loop until next NFL regular season. V1 is "build the right system"; V2 is "prove it works." Future LLMs may be tempted to suggest validation patterns that require live signal — those go in the V2 backlog.

10. **The user prefers a sparring-partner posture over a yes-and posture.** They've explicitly said they want pushback that helps them grow. Don't over-validate. Surface real concerns. Disagree when warranted.

## Files created / modified

- `PRODUCT_ROADMAP.md` — reorganized Open Questions into priority blocks; added 6 questions
- `TECHNICAL_ARCHITECTURE.md` — added "Known Architectural Gaps (TBD)" section
- `journal/2026-05-08-final-sweep.md` — this entry

---

## Next session should...

**Start here when picking up cold:**

1. Read PROJECT_OVERVIEW.md (5KB, ~5 min)
2. Read this journal entry + the prior two (2026-05-08-doc-restructure, 2026-05-08-architecture-pipeline-wrapped)
3. Skim PRODUCT_ROADMAP.md, focus on the Block 1 Open Questions
4. Ask the user the Block 1 questions before proposing any code or pipeline runs

**The single highest-leverage next move** is to lock the token vocabulary against actual planned Python fetcher names. This unblocks Pass 3 and prevents downstream rework. Estimated 30-60 minute conversation.

**The single cheapest way to validate the pipeline** is to run Pass 1 on ONE FSE redraft transcript (~$0.10, 15 min). Do this before any bulk execution. The output will reveal prompt-quality issues that no design review catches.

**Avoid these tempting detours:**
- Building the dashboard before the data layer (Phase 4 before Phase 2) — premature
- Re-extracting all four batches before validating Pass 1 v2 quality on one — wasteful
- Adding features from V2/V3 backlog ("Monte Carlo would be cool") — scope creep
- Refactoring the constitution docs — they were just refactored; let them settle