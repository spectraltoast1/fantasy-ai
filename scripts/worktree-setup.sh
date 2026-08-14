#!/usr/bin/env bash
# Worktree setup — make a fresh Claude Code worktree runnable.
#
# Git only carries TRACKED CODE into a worktree. The app's runtime assets
# (credentials, data, installed deps, the dev-server's data folder) are
# gitignored and live ONLY in the main checkout. This script lays the few
# "signposts" (symlinks) the worktree needs to reach into main, so the clean
# room can actually run and test before merging.
#
# Safe to re-run. See: project_management/co-build guides/SESSION_GUIDE.md
set -euo pipefail

WT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_COMMON="$(git -C "$WT_ROOT" rev-parse --path-format=absolute --git-common-dir)"
MAIN_ROOT="$(dirname "$GIT_COMMON")"

if [ "$WT_ROOT" = "$MAIN_ROOT" ]; then
  echo "✖ This is the main checkout, not a worktree."
  echo "  Main already has config, data, and node_modules in place — no setup needed."
  exit 1
fi

echo "Worktree: $WT_ROOT"
echo "Main:     $MAIN_ROOT"
echo

# link <relative-path> — create WT/<path> as a symlink to MAIN/<path>.
# Never clobbers a real file/dir in the worktree (only refreshes existing links).
link() {
  local rel="$1"
  local src="$MAIN_ROOT/$rel"
  local dst="$WT_ROOT/$rel"

  if [ ! -e "$src" ]; then
    echo "  skip   $rel  (not present in main — populate main's runtime first)"
    return
  fi
  if [ -L "$dst" ]; then
    ln -sfn "$src" "$dst"; echo "  relink $rel"
    return
  fi
  if [ -e "$dst" ]; then
    echo "  WARN   $rel is a REAL path in the worktree — leaving it untouched."
    echo "         Remove it and re-run if you meant to link it to main."
    return
  fi
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"; echo "  link   $rel -> main"
}

# link_children <relative-dir> — link each CHILD of MAIN/<dir> instead of the directory itself,
# skipping any child git tracks.
#
# Needed because `application/data/snapshots` stopped being wholly gitignored: the corpus recovery
# (2026-08-13) put `snapshots/corpus/` under version control so the frozen manifest can never again
# be lost to a bad write. That makes the whole-directory symlink impossible — git has to materialise
# the tracked files at that path, which replaces the link, and the worktree silently ends up with a
# 280 KB stub of the 389 MB store. Every pipeline read then resolves to nothing.
#
# So: link the ten gitignored children, leave the tracked one real. The invariant this preserves is
# the one the whole scheme rests on — writes land in main's single store, never a duplicate.
link_children() {
  local rel="$1"
  local src="$MAIN_ROOT/$rel"
  if [ ! -d "$src" ]; then
    echo "  skip   $rel  (not present in main — populate main's runtime first)"
    return
  fi
  mkdir -p "$WT_ROOT/$rel"
  local child name
  for child in "$src"/*; do
    [ -e "$child" ] || continue
    name="$(basename "$child")"
    if [ -n "$(git -C "$WT_ROOT" ls-files -- "$rel/$name" 2>/dev/null)" ]; then
      echo "  keep   $rel/$name  (git-tracked — stays a real path)"
      continue
    fi
    # An EMPTY directory here is a stub a previous run left behind (a check script that created
    # derived/league/<throwaway>/ and swept the file back out, say). It holds nothing, and leaving
    # it blocks the link — which is how a worktree ends up reading an empty store. Remove it and
    # link. A directory with anything in it is left alone and warned about, as before.
    if [ -d "$WT_ROOT/$rel/$name" ] && [ ! -L "$WT_ROOT/$rel/$name" ] \
       && [ -z "$(find "$WT_ROOT/$rel/$name" -type f -print -quit 2>/dev/null)" ]; then
      rm -rf "${WT_ROOT:?}/$rel/$name"
      echo "  clear  $rel/$name  (empty stub from an earlier run)"
    fi
    link "$rel/$name"
  done
}

# The seams where the clean room must reach into main.
link application/config.py
link_children application/data/snapshots
link application/data/cache
link application/frontend/node_modules
link application/frontend/public/data
# Python virtualenvs live in main and are shared by symlink so sessions don't rebuild
# them every worktree: application/venv = the data-side env (pipeline + the serve loader),
# application/api/.venv = the API's own env. Rebuild in main if stale (see SESSION_GUIDE).
link application/venv
link application/api/.venv

# .gitignore patterns use trailing slashes (e.g. node_modules/), which match
# directories but NOT symlinks — so a symlinked dir shows as untracked noise.
# Exclude those paths locally (config.py has no slash, so .gitignore catches it).
EXCLUDE="$(git -C "$WT_ROOT" rev-parse --git-path info/exclude)"
for p in \
  application/data/snapshots \
  application/data/cache \
  application/frontend/node_modules \
  application/frontend/public/data \
  application/venv
do
  grep -qxF "$p" "$EXCLUDE" 2>/dev/null || echo "$p" >> "$EXCLUDE"
done

echo
if [ -r "$WT_ROOT/application/frontend/public/data/season_2025.parquet" ]; then
  echo "✓ Runtime linked — season_2025.parquet resolves; the app is runnable here."
else
  echo "⚠ Links created, but season_2025.parquet did not resolve."
  echo "  Check that main's data/ and public/data/ are populated."
fi
echo "  'git status' should now show only your real code edits."
