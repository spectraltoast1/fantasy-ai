# V1 · P2 · Session S2 — Weekly refresh + per-league scoped-reload loader — REPORT

**Shipped:** 2026-07-28 · **Branch:** `claude/p2-s2-weekly-refresh` · **Commits:** 3 · **Status:** DONE —
the un-freeze. **Next:** P2/S3 (surface the honest band + live market). Brief:
`SESSION_P2_S2_WEEKLY_REFRESH.md`. **This was the single riskiest V1 change (the production loader); the
byte-parity guard held.**

## What shipped
The app can now **advance week by week**. The loader gained a **per-league scoped reload** and a
**weekly-refresh orchestrator** advances one league to the current week without a whole-DB rebuild —
**proven on prod by advancing the owner's 2025 league Week 4 → 5** with a clean re-run no-op. Ready to run
on live 2026 the moment games start.

## The three pieces
1. **Scoped-reload loader** (`serve/build_db.py`, commit `2725f81`). Split `_copy_slice` into a commit-less
   `_copy_slice_tx` core + a committing wrapper (full-load path unchanged). New `load_league(conn, lid)` —
   in ONE transaction, `DELETE FROM "<t>" WHERE league_id=%s` across the 13 data tables + re-COPY the
   league's slice, single commit. Every other league + the `demo_manifest` catalog untouched. **Never
   DROP/CREATE per league** (the DDL is a union superset across 31 slices; `_tables_present` guards it).
   `reload_league()` + `--reload-league`. The full `--load` stays the fallback + parity baseline.
2. **Parity oracle** (`serve/check_scoped_reload.py`, commit `2725f81`). **Prod-safe / non-destructive** —
   prod is already the full-load output, so snapshot the league, scoped-reload, snapshot, compare (no
   destructive rebuild). Proves **parity** (scoped == full-load rows per table), **idempotency** (2nd reload
   identical), **isolation** (a second league untouched); value-equal via a canonical row multiset
   (JSONB/empty safe). `--prove-bites` shows teeth. **Green on prod at both week 4 and week 5** (14,076 →
   14,624 rows re-COPYd identically, all 13 tables, other league unchanged).
3. **Weekly-refresh orchestrator** (`serve/weekly_refresh.py`, commit `59cfd79`). `refresh_league(lid,
   season, target_week, live, do_load)` — FETCH (`sleeper.refresh`/`backfill` + `fetch_projections` +
   `nfl_stats.refresh`, skip-if-present) → JOIN (`join_nfl_sleeper_weekly.run`, dedup-idempotent) → SPINE
   (`compute_spine._compute_league`, gated on `_spine_covers`) → LOAD (`build_db.reload_league`, gated on
   `_db_max_as_of`). Live (`--live`, from `/state/nfl`) or replay (`--week`); modeled on
   `compute_demo_slices`. Preseason/no-actuals weeks are graceful (projections-only; the join zero-fills
   actuals, nothing fabricated).

## The advance, proven on prod (a runtime action; enabled by the commit-3 schema-align fix)
Owner's 2025 league `1182101676608823296`: join [1..4]→[1..5], spine recomputed to `as_of 1..5`, scoped-load
→ **prod `max(as_of_week)` 4→5** across `production_vor`/`player_signal`/`bracket_odds`/`positional_depth`;
`season` weeks 1..5. Week-5 rows carry **real game data** (top RB 32.4 pts). The **serve seam surfaces it
automatically**: `reads.load_weeks(is_mine)` → `{weeks:[1..5], latest:5}`. **Re-run is a clean no-op**
(fetch/join/spine skip as covered, scoped reload skipped — Postgres already at 5). **Isolation:** a second
league unchanged (`as_of=13`, 2426 rows); 31 leagues intact.

## Two fixes surfaced along the way (both committed)
- **`numpy` was undeclared** in `application/requirements.txt` yet `compute_bracket_sim` imports it at module
  load (division-seeding) — a transitive dep the venv had dropped, so the spine (and thus the refresh + its
  CI job) couldn't import. Declared `numpy==2.5.1`; installed. (Main couldn't run the spine either before this.)
- **Schema-drift on append** — the corpus-built is_mine 2025 season join carries an `is_two_way` flag the
  live join doesn't emit, so appending week 5 (172 cols) to weeks 1..4 (173) crashed a strict `pl.concat`.
  Made `data_layer.write_join_nfl_sleeper_weekly` align columns (`how="diagonal"`): week-5 `is_two_way`=null,
  weeks 1..4 preserved. The right general property for an in-season incremental loader (schemas drift over a
  season / across code versions) — dtypes stay strict so a genuine type change still surfaces.

## Cadence + the one Will action
`.github/workflows/weekly_refresh.yml` — Tue+Wed cron + `workflow_dispatch` (live or replay), modeled on
`collectors.yml`. A **new cadence class** (Sleeper is on-demand, not a metered collector; this job *writes*
Postgres). **It needs a `DATABASE_URL` repo Actions secret** (the Supabase Postgres URL) to activate — a
**repo secret, not a Fly secret**. The proven run is the local one against prod; a `workflow_dispatch`
after the secret is set validates CI.

## Scope guard held
Touched only `serve/build_db.py`, the two new `serve/*.py`, `data_layer.write_join_nfl_sleeper_weekly`,
`requirements.txt`, the workflow, and docs. **No frontend** (honest band + live market = S3), **no auth**
(P5), **no Fly secrets**. `config.py` (plaintext prod `DATABASE_URL`) confirmed gitignored.

## Handoff to S3
The data now advances. S3 makes what the user *sees* true: surface the honest 8c band in the UI and convert
the market read from cross-time POC to a live 2026 read (its quality rests on the P1 daily collection).
