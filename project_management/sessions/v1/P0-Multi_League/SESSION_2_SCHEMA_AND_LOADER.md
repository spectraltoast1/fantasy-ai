# Session 2 — Postgres Schema + Loader (a brief for Code)

**Last reviewed:** 2026-07-24 · **Status:** Ready to run · **Owner:** Code (Will operates + eyeballs the result)

> **What this session does:** create the Postgres tables that mirror the 13 data files your app reads
> today, and build a **loader** that fills them from the existing parquet for your one 2025 league. This
> permanently replaces the hand-made file symlinks as the "publish" step. Still no app changes, no
> analytics moved yet, no new leagues or formats — this is Session 2 of the store migration in
> `MULTI_LEAGUE_STORE_MIGRATION.md` (Stage A).
>
> **After this session:** your real league data lives inside Supabase, and a query returns rows. The app
> itself still runs the old way (that switch is Session 5).

---

## Your part, Will (small — ~10 minutes of attention)

1. Start a session and paste Code the brief below.
2. **Have your Supabase connection string handy** (from your password manager). Code will ask for it once, early, to set up a durable secret — because Session 1's copy lived in a worktree that got cleaned up. Paste it when asked.
3. At the end, glance at Code's verification output (row counts + a sample query). That's your "looks right."

That's it — the rest is Code.

## Decisions I made for you (Code should follow unless it hits a reason not to)

- **Load from the exact files the app serves today** (`application/frontend/public/data/*.parquet`), so the database is a byte-for-byte copy of what's currently on screen — the cleanest possible parity guarantee.
- **Put `league_id` + `season` columns on every table now** (single values today), so the multi-league phase later doesn't require reshaping the schema.
- **Give the database secret a durable home** that survives worktrees (mirror the existing `config.py` pattern), because Session 1's `.env` is gone.
- **Make the loader idempotent** (truncate-and-reload) so re-running it never duplicates data.

---

## The 13 datasets to load (authoritative — from `application/frontend/src/db.js`)

| # | Table | Holds | Grain / join key *(confirm from the parquet)* |
|---|---|---|---|
| 1 | `season` | weekly join: roster ↔ team, weekly scores | roster_id × week |
| 2 | `teams` | roster_id → team & owner names | roster_id |
| 3 | `lineup_slots` | starting slot config (drives optimal lineup) | league-level |
| 4 | `league_settings` | league config | league-level |
| 5 | `player_signal` | per-player spike / signal-quality read | sleeper_player_id |
| 6 | `production_vor` | Production VOR (2025 frozen roster) | sleeper_player_id × as_of_week |
| 7 | `market_vor` | Market VOR (cross-time 2026 market) | sleeper_player_id |
| 8 | `ros_synthesis` | AI 1–10 grades (sparse; 2026 news world) | sleeper_player_id |
| 9 | `bracket_odds` | playoff odds + trend | roster_id × as_of_week |
| 10 | `positional_depth` | per team/position value + shape | roster_id × position × as_of_week |
| 11 | `manager_dossiers` | AI headline + tendencies (one row/team) | roster_id |
| 12 | `projection_consensus` | per-player p25/p50/p75 + center/band | sleeper_player_id × week (1–18) |
| 13 | `schedule` | week → matchup_id pairings (points dropped) | week × matchup_id |

Source files are `public/data/<name>_<year>.parquet`. Note the year is **2025 for all except `ros_synthesis` (2026)** — carry each table's real source year in its `season` column; don't blindly stamp everything 2025.

---

## The brief to paste to Code

```
Goal: Session 2 of the store migration (see project_management/scope docs/future work/
MULTI_LEAGUE_STORE_MIGRATION.md, Stage A). Define the Postgres schema and build a loader that fills it
from the EXISTING derived parquet for the single is_mine 2025 league. This replaces the hand-symlink
publish step. No app/frontend changes, no analytics moved, no new leagues/seasons/formats. Read-only on
all existing data — do not recompute or modify any parquet.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh (it symlinks snapshots + public/data in),
3-commit cap, update STATUS.md, scripts/worktree-close.sh --merge, push.

0. DURABLE SECRET FIRST. Session 1 created .env inside a worktree that was removed on merge, and .env is
   gitignored — so DATABASE_URL is probably gone locally. Establish a durable home for it that survives
   worktrees, mirroring how config.py is handled: keep the secret in the MAIN checkout (gitignored) and
   symlink it into worktrees via scripts/worktree-setup.sh (add it to that script's link list). Ask me to
   paste the Supabase SESSION-POOLER connection string; store it there. Confirm both this session and the
   FastAPI app read DATABASE_URL from that durable location. Verify connectivity (SELECT 1) before moving on.

1. ENUMERATE + INSPECT. The authoritative list of what to load is the 13 registerParquet calls in
   application/frontend/src/db.js (cross-check the loaders in queries.js). For each, read the parquet's
   schema (columns + types) with polars. Produce a short manifest (table -> source file -> columns) and
   include it in the commit.

2. SCHEMA. Create one Postgres table per dataset, mirroring the parquet schema. On EVERY table add
   league_id + season columns (fill with the is_mine league_id and the file's real year — 2025 for all
   except ros_synthesis = 2026). Keep the DDL in a reviewable file (e.g. application/data/serve/schema.sql).
   Add indexes on the filter columns each table actually uses: as_of_week, week, roster_id,
   sleeper_player_id, plus league_id + season. Map types cleanly (dates, floats; use JSONB for any
   structured/nested column such as the AI dossier fields if applicable).

3. LOADER. Build application/data/serve/build_db.py that reads the exact published parquet the app serves
   today (application/frontend/public/data/*.parquet) and writes each into its Postgres table via
   DATABASE_URL. Make it idempotent (truncate-and-reload per table) so re-runs never duplicate. Keep it
   deterministic and minimal — this is the new publish seam that replaces the hand symlinks.

4. RUN. Execute the loader against Supabase; load the 2025 slice.

5. VERIFY (database-level — the frontend is NOT wired to this yet, that's Session 3):
   - Row counts per Postgres table equal the source parquet row counts (assert programmatically).
   - Spot-check a handful of values against the parquet.
   - Run 2-3 representative queries (e.g. production_vor for as_of_week=4; the schedule for a week) and
     confirm sane results.
   Show me the row-count comparison and one sample query result.

6. CLOSE. Update STATUS.md (what shipped + next move = Session 3: port the first read endpoints, Players +
   Teams, from browser SQL to FastAPI/Postgres). Then close/merge/push per SESSION_GUIDE.

Boundaries: do not touch the frontend, queries.js, or db.js this session; do not modify or recompute any
derived data; one league, one slice. If the bulk load misbehaves through the session pooler at this size
(it shouldn't — it's tiny), you may use the DIRECT connection string for the load step only.
```

---

## Definition of done

✅ A durable `DATABASE_URL` that survives future worktrees; all **13 tables** created in Supabase with `league_id`/`season` columns and sensible indexes; the **loader** (`build_db.py`) runs idempotently and fills them from today's published parquet; **row counts match** the source files and a sample query returns real data; `STATUS.md` updated with Session 3 as the next move. The app is untouched and still runs the old way.

## Notes / gotchas

- **The secret-continuity fix (Step 0) is the real "gotcha" of this session** — get it right once and Sessions 3–6 all just work. Skipping it means re-pasting the connection string every session.
- **Parity comes from the source, not from cleverness:** loading the exact `public/data` parquet means the database can't drift from what the app shows today. Keep it that literal.
- **`ros_synthesis` is the odd one** (2026, sparse AI grades) — expected. Just carry its real year; don't force it to 2025.
- **Nothing visible changes this session.** Success looks like rows in a database, not anything on screen. The screens don't move onto this until Session 5.
