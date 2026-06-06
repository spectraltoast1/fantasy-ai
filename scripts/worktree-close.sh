#!/usr/bin/env bash
# Worktree closedown — review, then merge the session branch into main and
# remove the worktree.
#
#   scripts/worktree-close.sh            # review only: status, diff, commit count
#   scripts/worktree-close.sh --merge    # execute: merge into main + remove worktree
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
git -C "$MAIN_ROOT" worktree remove "$WT_ROOT"
echo
echo "✓ Merged into local main and removed the worktree."
echo "  Push when ready:  git -C \"$MAIN_ROOT\" push"
echo "  Next task = fresh session + fresh worktree."
