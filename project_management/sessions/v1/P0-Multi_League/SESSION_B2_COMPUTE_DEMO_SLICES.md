# Stage B — Session B2: Full-set compute for the demo slices — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code drives (this one churns); Will kicks it off + eyeballs the validation

> **What this session does:** the **heavy one**. Compute the full set of derived analytics the app renders — for
> all **31 demo slices** (12 lineages × their seasons), not just your one league — **honoring the panel policy**
> recorded in B0 (dossiers everywhere; market + the AI news read only on the live 2025 slice). This is the long
> pole of Stage B: it's where the corpus leagues go from "raw data on disk" to "fully analyzed and ready to
> serve." Store-agnostic — it writes derived **parquet**; the load into Postgres is B3. The live app and the
> production DB are **not touched**. Stage B of `MULTI_LEAGUE_STORE_MIGRATION.md` (B2).
>
> **Dependencies (both done):** B0's `demo_manifest.parquet` (the slate + pinned viewers + panel flags) and B1's
> league-scoped schedule. B2 reads the manifest as its work-list.

## Your part, Will (~15 min to kick off; then it runs for a while)
Start the brief below. Unlike the other sessions, this one **churns** — it computes ~30 leagues' worth of
analytics and makes a few hundred cheap AI calls for the manager dossiers, so it can take a while and may run
across more than one sitting (it's built to resume). At the end, glance at Code's validation summary: every slice
green, and the panel gating respected (only your 2025 league has market + bull/bear/sit). That's your "looks
right." Nothing a user sees changes yet — that's B3+.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **The manifest is the work-list.** Read `demo_manifest.parquet` (via `data_layer.read_demo_manifest()`) — the
   31 `(league_id, season)` slices, each with its `scoring_key`, `viewer_roster_id`, and the three panel flags.
   **Compute exactly to the panel flags:** `manager_dossiers` for all 31; **`market_vor` and `ros_synthesis`
   ONLY where flagged** (in practice just your 2025 slice, which already has them — so effectively no new
   market/news compute). Do **not** compute a gated-off panel — that's the whole "honest over fabricated" point.
2. **Idempotent, resumable, per-league isolation** — model the driver on `compute_spine.py`. A slice already
   computed → skip it. A failure on one slice → log it and continue; a re-run picks up where it left off without
   redoing finished work or corrupting a half-written slice. With 31 slices × several stages × AI calls, this is
   non-negotiable — a mid-run hiccup must not mean starting over.
3. **Reuse what already exists — don't recompute:**
   - **Scoring-keyed substrate** (`adp_points_curve` → `projection_consensus` → `ros_player_band`, per
     `scoring_key`×`season`) is already built for **{ppr, half} × 2020–2025** by the engine track's
     `build_substrate.py`. The slate is entirely ppr/half (no custom), so the substrate the demo needs **already
     exists** — reuse it, don't rebuild. (If a `(key, season)` is somehow missing, build just that one.)
   - **The 5-read spine** exists for the matched corpus already; reuse where present, compute only what's missing
     (e.g. your **2024** league, whose `derived/league/…` is empty, and any slice not in the matched set).
   - **Your 2025 slice is fully computed (Stage A)** — the driver should recognize it as done.
4. **Store-agnostic.** Write derived parquet under `derived/league/<league_id>/` (+ the shared
   `derived/scoring/<key>/` substrate). Do **NOT** load Postgres or touch the live app / `public/data` — B3 owns
   the multi-slice reload.
5. **Validate, don't just run.** Every computed slice passes the existing `check_*` harness before it's called done.

## The compute recipe (per slice, in dependency order — mirrors `MULTI_LEAGUE_STORE_MIGRATION.md` B2)

For each `(league_id, season)` in the manifest, ensure the complete derived set the loader needs exists (reuse or
compute), gated by the panel flags:

1. **Base reads** — the season join + `teams` + `lineup_slots` + `league_settings` + the **league-scoped
   `schedule`** (B1's `export_schedule.py --league-id …`). These come from the raw harvest; compute any missing.
2. **Substrate** (reuse — see decision 3): `projection_consensus`, `ros_player_band` for the slice's
   `scoring_key`×`season`.
3. **Spine** — reuse `compute_spine._compute_league`: `production_vor`, `true_rank`, `positional_depth`,
   `bracket_odds`, `player_signal`.
4. **Narrative/market** — `compute_manager_features` **always** (feeds dossiers); `compute_market_vor` +
   `compute_ros_league_view` **only if the slice's `panels_market`/`panels_ros` is set** (i.e. your 2025 slice).
5. **AI** — `ai/write_manager_dossiers` **for all 31** (self-gates via `is_zero_signal` on thin managers);
   `ai/write_ros_synthesis` **only if `panels_ros`** (your 2025 slice).

New batch driver: **`application/data/corpus/compute_demo_slices.py`** (modeled on `compute_spine.py`).

## The brief to paste to Code

```
Goal: Stage B, Session B2 (MULTI_LEAGUE_STORE_MIGRATION.md B2) — the full-set compute. For every slice in
snapshots/demo_manifest.parquet (31 (league_id, season) rows), produce the complete derived analytics the app
renders, HONORING the panel flags, reusing existing substrate/spine, and writing derived PARQUET only. Store-
agnostic: do NOT load Postgres, do NOT touch the live app or public/data (B3 owns the reload). Needs B0 (manifest)
+ B1 (league-scoped schedule) — both done.

Build application/data/corpus/compute_demo_slices.py, modeled on compute_spine.py: idempotent, resumable, per-
league isolation (a slice already done → skip; a failure on one slice → log + continue, never corrupt a half-
written slice; a re-run resumes). Read the work-list via data_layer.read_demo_manifest().

Per slice (league_id, season), in dependency order, honoring panels:
1. Base reads: season join + teams + lineup_slots + league_settings + the league-scoped schedule
   (export_schedule.py --league-id <id> --season <s>). Compute any missing from the raw harvest.
2. Substrate (REUSE — do not rebuild): projection_consensus + ros_player_band for the slice's scoring_key×season.
   The slate is all ppr/half, already built by build_substrate.py for {ppr,half}×2020-2025 — reuse. Build only a
   (key,season) that's genuinely missing.
3. Spine (reuse compute_spine._compute_league where present; compute where missing — e.g. the is_mine 2024 league
   has an empty derived dir): production_vor, true_rank, positional_depth, bracket_odds, player_signal.
4. Narrative: compute_manager_features ALWAYS (feeds dossiers). compute_market_vor + compute_ros_league_view ONLY
   if the slice's panels_market/panels_ros is true (in practice only the is_mine 2025 slice, which already has
   them). Do NOT compute a gated-off panel.
5. AI: ai/write_manager_dossiers for ALL 31 (self-gates via is_zero_signal on thin managers). ai/write_ros_
   synthesis ONLY if panels_ros (is_mine 2025).

Reuse aggressively: the is_mine 2025 slice is already fully computed (Stage A) — recognize it as done. Substrate
exists. Much of the matched-corpus spine exists. Only compute what's genuinely missing.

Validate every computed slice with the existing harness (check_spine, check_market_vor where applicable,
check_manager_dossiers, check_ros_synthesis where applicable) before marking it done. Emit a run summary: per
slice, what was computed vs reused vs skipped, and its validation result.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, update STATUS.md, close/merge, push. NOTE on the
3-commit cap: the CODE is the driver + validation wiring (a couple of commits); the RUN over 31 slices is an
action, not a commit, and may span multiple invocations (resumable) — that's expected, don't force it into one
sitting. Suggested commits: (1) compute_demo_slices.py driver + reuse/skip logic; (2) panel-gated narrative/AI +
validation harness wiring; (3) the run's results + STATUS. If the AI dossier run is very long, ship the driver +
the base/spine/substrate pass first, then the dossiers as a resumable follow-on — both land before B3.

Watch-items: AI cost/time — manager_dossiers × ~30 new slices × ~8-14 teams ≈ a few hundred haiku calls (model
claude-haiku-4-5); it's cheap but not instant, hence resumable. has_transactions is true for all slate leagues, so
dossiers have signal. Per-league isolation: one bad slice must not kill the batch. Keep everything under
derived/league/<id>/ + derived/scoring/<key>/ — nothing to Postgres.

Close: update STATUS.md (B2 done: all 31 slices computed + validated, panel gating respected; next = B3 — load
all slices from the derived store [remember B1's new schedule path] + add GET /api/leagues). Merge/push.
```

## Definition of done
✅ All 31 demo slices have the complete derived set the loader needs, written as parquet under
`derived/league/<id>/` (+ shared `derived/scoring/<key>/`), **gated to the panel policy** (dossiers on all 31;
market + ros only on the live 2025 slice); each computed slice passes the `check_*` harness; a run summary shows
per-slice computed/reused/skipped + validation; `compute_demo_slices.py` is idempotent/resumable; `STATUS.md`
updated with B3 as the next move. **No Postgres load, no live-app/`public/data` change.**

## Notes / gotchas
- **This is the long pole — resumability is the whole game.** 31 slices × several stages × a few hundred AI calls
  means something *will* hiccup; the driver must resume cleanly, not restart. That's why it's modeled on
  `compute_spine.py` (which already does idempotent, per-league, resumable batch work).
- **Reuse, don't recompute.** The substrate is built; your 2025 slice is done; much of the corpus spine exists.
  The genuinely new work is: the 2024 slice, any unmatched corpus slices' spine, and manager dossiers for the ~30
  slices that don't have them. If you find yourself rebuilding substrate, stop — reuse it.
- **The gated panels are a no-op on purpose.** Market + bull/bear/sit compute only for your 2025 slice, which
  already has them — so B2 realistically computes *no new* market/news data. The other 30 slices deliberately get
  standings / VOR / projections / matchups / positional-depth / **dossiers** and nothing else. That's the locked
  "gate historical, keep dossiers" decision.
- **Store-agnostic, and the live app must stay live.** Everything lands as derived parquet; the DB and the deployed
  site are B3's to touch. If a change would alter what `public/data` serves, stop — that's out of scope here.
- **Hand-off to B3:** B3 loads all 31 slices from the **derived store** (not `public/data`), reading the
  league-scoped schedule from B1's new path, and adds `GET /api/leagues`. Note the completed slice list in STATUS
  so B3 knows exactly what to load.
