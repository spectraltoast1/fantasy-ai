# Post-Code Session Guide

A repeatable workflow for reviewing and integrating Claude Code's work
after each session. Follow these steps after every Claude Code run.

---

## 1. Review what Claude Code did

Before touching anything, understand what changed:

Claude Code often writes files to the worktree directory but does not always commit them. Before running any git diff, check whether the files were committed.

```bash
cd .claude/worktrees/<branch-name>
git status
```

If files are showing untracked or modified, commit them first:
```bash
git add <files>
git commit -m "<message>"
```

Return to the repo root
```bash
cd .claude/worktrees/<branch-name>
```

To see all files changed in the worktree branch vs main
```bash
git diff main..claude/<branch name> --name-only
```

To see the full line-by-line diff
```bash
git diff main..claude/<branch name>
```

Read through the diff. Ask yourself:
- Did it create the files I expected?
- Did it touch any files I didn't expect?
- Does anything look wrong or unexpected?

If something looks off, do not merge. Go back to Claude Code and ask it
to explain or correct before proceeding.

---

## 2. Smoke test before merging

Run a quick sanity check on the output before it touches main:

- If it created a Python script: import it and call a function
- If it created data files: read them and check row counts / schema
- If it modified existing files: open them and read the changes

Catching problems here is cheap. Catching them after merging is not.

---

## 3. Merge the worktree branch into main

Once satisfied:

merge the worktree to main using the GitHub desktop app

---

## 4. Verify after merge

```bash
# Confirm you're on main
git branch

# Confirm the new files exist where expected
ls <expected-paths>

# Run the smoke test again from main to confirm nothing broke in the merge
```

---

## 5. Delete the worktree



---

## 6. Update project docs

After merging, update STATUS.md:
- Change "Next single highest-leverage move" to reflect what was just completed
- Write the new next move
- Update "Today" section if the project state changed meaningfully

Update TECHNICAL_ARCHITECTURE.md if:
- A new data source was wired up
- The folder structure changed
- A new technical decision was made

---

## 7. Clean up the worktree (optional)

```bash
git worktree remove .claude/worktrees/<branch-name>
```

Not required - stale worktrees don't cause problems. Clean them up
periodically to keep the repo tidy.

---

## Common issues

**Files landed in the wrong place**
Claude Code was likely pointed at the wrong directory. Copy files manually
to correct locations, then commit from main. See today's specific guide
for the copy commands pattern.

**Worktree branch is ahead of main by unexpected commits**
Review each commit individually: `git log main..HEAD`
Cherry-pick only what you want: `git cherry-pick <commit-hash>`

**Merge conflict on requirements.txt**
Usually means both branches added different dependencies. Open the file,
keep all the dependencies from both sides, remove the conflict markers,
save and commit.
