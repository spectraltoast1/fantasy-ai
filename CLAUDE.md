# CLAUDE.md

Engineering guide for Claude Code sessions on this project. **Read this first.**

## What this project is

A fantasy football analytics dashboard (V1) and a future AI advisor (V2+).
Authoritative context lives in two docs — read them; don't rely on chat history:

- `project_management/LLM context/STATUS.md` — current project state + next move
- `project_management/LLM context/TECHNICAL_ARCHITECTURE.md` — stack, data layer, principles

If a fact isn't in those two docs, it isn't established. **Update them — don't
duplicate their content here.**

## Session lifecycle

One session = one worktree = a bounded chunk of work = one merge. Full detail in
`project_management/co-build guides/SESSION_GUIDE.md`. The short version:

### Setup (start of every session)
1. **Work in a worktree, not main.** Isolation is the point: main stays clean and
   runnable while work is in progress, and a botched change never touches main
   until merge. If this session landed in main, create/enter a worktree before
   doing multi-commit work.
2. **Run `scripts/worktree-setup.sh`.** It links the gitignored runtime
   (config, data, node_modules, dev-server data) from main into the worktree.
   Without it the app cannot run here — see "Runtime lives in main" below.
3. **Read STATUS.md** to orient on the current state and next move.

### Work
- Plan → execute → **verify** (run the app / browser preview; never ask the user
  to check manually — verify and show proof).
- Commit per logical unit.

### Closedown — trigger: task done **OR 3 commits**, whichever comes first
1. `git status` clean — only intended edits remain.
2. Update STATUS.md (and TECHNICAL_ARCHITECTURE.md if the stack, folder structure,
   or a technical decision changed).
3. `scripts/worktree-close.sh` to review the diff, then
   `scripts/worktree-close.sh --merge` to merge into main, remove the worktree, and
   delete the now-merged branch (it self-cleans — no leftover branches/worktrees).
4. Done. The next task is a **fresh session + fresh worktree.**

**Commit cap: 3 per session.** It's a forced checkpoint, not red tape — it
guarantees the doc-update and merge happen regularly, which is exactly what keeps
worktrees from drifting and keeps main current.

## Runtime lives in main, not the worktree

`application/config.py`, `application/data/snapshots` + `cache`,
`application/frontend/node_modules`, and `application/frontend/public/data` are
gitignored and exist **only in the main checkout**. A fresh worktree is a
non-runnable shell until `scripts/worktree-setup.sh` links them. Data written
through the links lands in main's single store, so there's no duplicate/stale
copy. Gotchas (committed-file traps, symlink vs `.gitignore`, venv) are documented
in the SESSION_GUIDE.

## Non-negotiables (full list in TECHNICAL_ARCHITECTURE.md)

- **polars, never pandas.**
- All data I/O goes through `application/data/data_layer.py`.
- All front-end data access goes through `src/queries.js` (the client/server seam).
- V1 is **skill positions only** (QB/RB/WR/TE).
