# Session Guide (Claude Code)

A repeatable lifecycle for a Claude Code build session. One session = one
worktree = a bounded chunk of work = one merge into main.

> Replaces the earlier PRE_CODE_GUIDE / POST_CODE_GUIDE, which assumed a Claude
> Chat (PM) + Claude Code (engineer) split. The workflow is now Code-only.

---

## The model

Each session is intentionally fresh — LLMs work better without accumulated
context drift. The **document layer carries continuity**, not conversation
history:

- `STATUS.md` — project state and the next move
- `TECHNICAL_ARCHITECTURE.md` — stack, data layer, technical principles

These take precedence over anything in chat. A stale STATUS.md is the fastest way
to lose continuity between sessions.

Work happens in a **git worktree**, not the main checkout. The point is
isolation: main stays clean and runnable while a build is in progress, and a
botched change never reaches main until you choose to merge. The cost of that
isolation is that a fresh worktree has none of the runtime assets — which the
setup step fixes.

---

## Phase 1 — Setup

### 1.1 Be in a worktree
Confirm the session is in a worktree (e.g. `.claude/worktrees/<name>`), not main.
If you're in main and about to do real work, create/enter a worktree first.

### 1.2 Make the worktree runnable
```bash
scripts/worktree-setup.sh
```
This links the gitignored runtime from main into the worktree:

| Linked into the worktree | Why it's needed |
|---|---|
| `application/config.py` | Sleeper credentials |
| `application/data/snapshots` + `cache` | the parquet data the pipeline/app reads |
| `application/frontend/node_modules` | installed deps (no reinstall) |
| `application/frontend/public/data` | the files the dev server serves |

These are symlinks ("signposts") to main, so nothing is duplicated and writes
land in main's single store. They're disposable — they vanish when the worktree
is removed. After running, `git status` should show only real code edits.

### 1.3 Orient
Read `STATUS.md`. Know the current state, the stated next move, and whether that
move still feels right.

---

## Phase 2 — Work

- **Plan first** for non-trivial tasks; confirm file paths and approach before writing code.
- **Execute**, then **verify** by actually running it — start the dev server / browser
  preview, read the output, confirm the change. Don't ask the user to check manually.
- **Commit per logical unit** with clear messages.

### Commit cap: 3 per session
When you hit 3 commits (or finish the task, whichever comes first), close down.
The cap is a forced checkpoint — it keeps sessions bounded and guarantees the
doc-update + merge happen regularly, which is what prevents worktree drift.

---

## Phase 3 — Closedown

### 3.1 Clean tree
All work committed; `git status` shows nothing but intended edits.

### 3.2 Update docs
- `STATUS.md`: move what you built into "Today"; write the new next move.
- `TECHNICAL_ARCHITECTURE.md`: only if the stack, folder structure, or a technical
  decision changed (new data source wired, new principle, etc.).

### 3.3 Review, then merge
```bash
scripts/worktree-close.sh            # review: status, diff, commit count, doc reminder
scripts/worktree-close.sh --merge    # merge into main + remove the worktree
```
The review form is a dry run — read the diff and commit list it prints. When it
looks right, re-run with `--merge`. It merges the branch into your local main and
removes the worktree (and with it, the signposts).

### 3.4 Push
The merge is local. Push main when ready:
```bash
git -C <main-repo-root> push
```

The next task starts a fresh session and a fresh worktree.

---

## Runtime gotchas (why setup is the way it is)

- **Some data was once committed.** `player_id_map.parquet` and
  `nfl_stats_2025.parquet` were untracked via `git rm --cached`. Don't re-add data
  files; the `.gitignore` keeps them out. (This is why the setup script can safely
  symlink the whole `data/snapshots` and `cache` dirs — nothing tracked lives there.)
- **`.gitignore` + symlinks.** Trailing-slash patterns (`node_modules/`) match
  directories but not symlinks, so the setup script adds the linked paths to
  `.git/info/exclude` (local-only) to keep `git status` clean.
- **Python env.** `application/venv` is missing polars; the system `python3` has it.
  Run fetchers/transforms with `python3`.

## Common issues

- **Files landed in the wrong place** — Claude was likely pointed at the wrong dir.
  Confirm the worktree root before re-running.
- **Branch ahead of main by unexpected commits** — review with
  `git log main..HEAD`; cherry-pick only what you want.
- **Worktree won't remove (busy)** — make sure no shell is `cd`'d inside it, then
  `git worktree remove --force <path>` from the main checkout.
