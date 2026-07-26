# Stage B Audit — B0 (demo slate) + B1 (schedule league-scoping)

**Reviewed:** 2026-07-25 · **By:** PM (independent, against live git + the actual data outputs)
**Scope:** the two store-agnostic Stage-B prep sessions (record the demo slate; league-scope the schedule),
shipped in one combined worktree (3 commits, merged).

**Bottom line: both clean, correct, and independently verified. No findings of substance.** The live app and
production DB were untouched (correct — B3 owns the reload). One item is a note to *me*: my B0 brief had a wrong
viewer value, which Code caught and corrected.

## Verified (I re-checked the data myself, not just the report)

**B0 — `demo_manifest.parquet`:**
- **31 rows, 12 lineages, zero null viewers.** Columns as designed (`lineage_id, league_id, season, name,
  scoring_key, num_teams, is_mine, previous_league_id, viewer_roster_id, panels_market, panels_ros, panels_manager`).
- **Panel policy exact:** `panels_manager` ON for all 31; `panels_market` + `panels_ros` ON for **exactly one**
  slice — LORP 2025 (`is_mine`) — OFF for the other 30. That's the locked "dossiers everywhere, market/news only
  on the live slice" decision.
- **`lineage_id` is the true root league_id and is stable across seasons.** LORP's is `1132…977920` (its 2024
  league, `previous_league_id` = null) for both seasons. Confirmed Code's important find: `bgb`/`ypfl`/`nbl`/`rost`
  root to an ancestor *earlier* than their earliest demo season — so root-keying (walk `previous_league_id` to the
  chain root) was necessary, not just tidy. 12 distinct roots, one per lineage.
- **Viewers pinned and consistent per lineage** (one viewer roster across a lineage's seasons — e.g. `trap` = 1
  across all six years, LORP = 8 across both). Corpus viewers use the most-tenured owner (provisional; the
  mid-table refinement is a post-B2 polish, as scoped).

**B1 — schedule league-scoping:**
- **Parity proven independently:** the is-mine 2025 pairings (`week/roster_id/matchup_id`, 180 rows) are
  **byte-identical** old-root vs new-league-path. The regeneration relocated + stamped `league_id`, it did not
  move a single pairing.
- **No-collision proven:** the new file lives at `derived/league/1182…/schedule_2025.parquet` (league_id stamped,
  180 rows/10 rosters); `trap` 2025 writes to its own `derived/league/1207…/` (216 rows/12 rosters). The old bug
  would have overwritten one with the other at the shared root.
- **Code + data_layer are right:** `export_schedule.py` adds `--league-id` (default is-mine) + a `league_id`
  column; `data_layer` schedule accessors now key on `_league_dir(league_id)`. Mirrors the L0 keying of every
  other derived read.
- **Keyability sweep done:** all 13 loader-ingested datasets are attributable (11 league-path,
  `projection_consensus` scoring-keyed, `schedule` now fixed) — schedule was the only gap; no others.
- **Live app untouched:** B1 deliberately left the old `derived/schedule_2025.parquet` root + the
  `public/data` publish symlink in place, so the deployed app/DB are unaffected.

## The one flag — and it's on me

My B0 brief's parenthetical "LORP viewer `roster_id` 7 in 2025" was **wrong**. Code verified against the data
(and the S6 live app — the viewer team resolves to `rosterId` 8) and recorded **8**, then flagged the slip. The
manifest is correct; nothing to fix. Worth noting only because it cuts the right way: Code didn't take my brief
on faith any more than I take Code's reports on faith — which is exactly the discipline that keeps this clean.

## Forward handoffs (carry into the next briefs — not defects)

- **B3 must read `schedule` from the new `derived/league/<id>/schedule_<season>.parquet` (+ `league_id` column)**,
  not the old root; B3 repoints the loader/publish symlink and can retire the old root file. Code flagged this in
  STATUS; I'll bake it into the B3 brief.
- **B2 reads `demo_manifest.parquet` for the slate** and must **honor the panel flags** — compute market/ros only
  where flagged (i.e. essentially just LORP 2025), dossiers for all 31. The manifest is the authoritative input.
- **Corpus viewers are provisional** (most-tenured owner). Optional post-B2 refinement to a mid-table team for
  more interesting personal-panel reads.

## Recommendation
Both done and correct. Clear to proceed to **B2** (the heavy compute over all 31 slices) — it now has everything
it needs: B0's slate + panel policy, and B1's league-scoped, non-colliding schedule.
