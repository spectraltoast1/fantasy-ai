#!/usr/bin/env bash
# Worktree closedown — review, then merge the session branch into main, remove the
# worktree, and delete the now-merged branch (so merged sessions leave no cruft).
#
#   scripts/worktree-close.sh            # review only: status, diff, commit count
#   scripts/worktree-close.sh --merge    # execute: merge + remove worktree + delete branch
#
# Run the review form first, confirm it looks right, then re-run with --merge.
# See: project_management/co-build guides/SESSION_GUIDE.md
set -euo pipefail

COMMIT_CAP=3
DO_MERGE=0
[ "${1:-}" = "--merge" ] && DO_MERGE=1

WT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_COMMON="$(git -C "$WT_ROOT" rev-parse --path-format=absolute --git-common-dir)"
MAIN_ROOT="$(dirname "$GIT_COMMON")"
BRANCH="$(git -C "$WT_ROOT" rev-parse --abbrev-ref HEAD)"

if [ "$WT_ROOT" = "$MAIN_ROOT" ]; then
  echo "✖ Run this from the worktree, not main."; exit 1
fi

echo "Worktree: $WT_ROOT"
echo "Branch:   $BRANCH"
echo "Main:     $MAIN_ROOT"
echo

# 1. All work must be committed.
if [ -n "$(git -C "$WT_ROOT" status --porcelain)" ]; then
  echo "✖ Uncommitted changes remain — commit (or discard) before closedown:"
  git -C "$WT_ROOT" status --short
  exit 1
fi

# 2. Commit count vs the session cap.
N="$(git -C "$WT_ROOT" rev-list --count "main..$BRANCH")"
echo "Commits ahead of main: $N  (session cap: $COMMIT_CAP)"
[ "$N" -gt "$COMMIT_CAP" ] && echo "  ⚠ over cap — this session may have taken on too much."
[ "$N" -eq 0 ] && { echo "  Nothing to merge."; exit 0; }

# 3. What will land on main.
echo
echo "=== files changed (main..$BRANCH) ==="
git -C "$WT_ROOT" diff --stat "main..$BRANCH"
echo
echo "=== commits ==="
git -C "$WT_ROOT" log --oneline "main..$BRANCH"

# 4. Doc-update reminder.
if ! git -C "$WT_ROOT" diff --name-only "main..$BRANCH" | grep -q 'STATUS.md'; then
  echo
  echo "⚠ STATUS.md untouched this session — update it before merging if state changed."
fi

# 4b. Runtime-data-deletion guard. A merge applies the branch's tree deletions to
# main's working tree — so if this branch untracked a gitignored runtime data
# file, merging would delete main's on-disk copy (which won't return from git).
DELETED_DATA="$(git -C "$WT_ROOT" diff --diff-filter=D --name-only "main..$BRANCH" \
  | grep -E '^application/data/(snapshots|cache)/' || true)"
if [ -n "$DELETED_DATA" ]; then
  echo
  echo "⚠ This branch removes runtime data file(s) from the tree:"
  echo "$DELETED_DATA" | sed 's/^/    /'
  echo "  Merging would delete main's on-disk copies. Back them up first, then"
  echo "  restore them after the merge (they are gitignored — git won't return them)."
  if [ "$DO_MERGE" -eq 1 ]; then
    echo "✖ Refusing to auto-merge with runtime-data deletions — handle it manually."
    exit 1
  fi
fi

if [ "$DO_MERGE" -eq 0 ]; then
  echo
  echo "Review the above. To merge into main and remove this worktree, re-run:"
  echo "  scripts/worktree-close.sh --merge"
  exit 0
fi

# 5. Merge into main (checked out at MAIN_ROOT) and remove the worktree.
echo
echo "Merging $BRANCH into main..."
git -C "$MAIN_ROOT" merge --no-ff "$BRANCH" -m "Merge $BRANCH"
echo "Removing worktree..."
# --force: a worktree always holds untracked runtime (the setup symlinks,
# generated parquets), which a plain remove would refuse on.
git -C "$MAIN_ROOT" worktree remove --force "$WT_ROOT"

# 6. Delete the now-merged branch + prune stale worktree admin state, so merged
# sessions don't accumulate dead branches/worktrees. `branch -d` is the SAFE delete —
# it succeeds only because the branch is already merged into main (a stray unmerged
# branch would be kept, not force-dropped). It must run AFTER the worktree is gone: a
# branch checked out in a worktree cannot be deleted. Guarded with `|| echo` so a
# cleanup hiccup can never fail a close whose merge already landed.
echo "Deleting merged branch $BRANCH..."
git -C "$MAIN_ROOT" branch -d "$BRANCH" \
  || echo "  ⚠ could not delete $BRANCH (unmerged, or checked out elsewhere) — left in place."
git -C "$MAIN_ROOT" worktree prune

echo
echo "✓ Merged into local main, removed the worktree, deleted the branch."
echo "  Push when ready:  git -C \"$MAIN_ROOT\" push"
echo "  Next task = fresh session + fresh worktree."
