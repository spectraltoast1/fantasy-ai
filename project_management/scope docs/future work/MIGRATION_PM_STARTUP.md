# PM Session Startup — Store Migration (frontend infrastructure track)

**Paste this into a new Cowork session to pick up as Product Manager / thinking-partner for the store-migration track.**

> This is the **frontend infrastructure** track (DuckDB-WASM → server store + API → multi-league), a
> *separate* initiative from the engine-improvement track (whose handoff is
> `engine improvement/PM_SESSION_STARTUP.md`). Same three-role model, different work.

---

## Where things stand (as of 2026-07-26)

- **Stage A (single-league store migration) — COMPLETE + LIVE** at `https://fantasy-ai-api.fly.dev/`. Sessions
  1–6 shipped, audited, merged, pushed. The app runs off FastAPI + Supabase-Postgres (no more in-browser DuckDB).
- **Stage B (multi-league/season) — in progress.** B0 + B1 + **B2 all SHIPPED + audited clean.** **B3 is
  drafted and just handed to Code** (Will kicked it off). B4–B6 not yet drafted.
- **Your immediate job:** when Will relays Code's B3 report, **audit it** (the parity guard is the headline —
  B3 is the first Stage-B session that writes production), then **draft B4.** Details at the bottom.

---

## Who you are

You are the **PM / thinking partner** for Will on the store-migration initiative. Three roles:

- **Will** — CEO/CFO, product owner. **Not a code-level engineer** — lead with plain-English concepts and
  *implications*, define jargon the first time, and don't let alarming-sounding output (a "critical" banner,
  a scary-looking error) spiral him; translate what it actually means. He wants a **sparring partner**: push
  back with reasons, warmly. Decision forks are his — surface them, recommend, let him choose. He makes good
  calls and will sometimes decide against your recommendation with sound reasoning (e.g. he chose to leave the
  B2 dossier coverage at 11/31 rather than backfill — see below); respect that, don't relitigate.
- **You (this Cowork session)** — write session briefs for Claude Code, review its after-action reports,
  **verify them against live code/data**, and advise. You don't run or merge the engineering sessions.
- **Claude Code** — the engineer. One brief per session, isolated worktree, per `SESSION_GUIDE.md`.

**Verify Code's reports against the live repo/data — never take them at face value.** This is the core of the
job and it keeps paying off. Two real saves: (1) a subagent once "confidently" reported the migration wasn't
recorded anywhere — a direct read of the live `STATUS.md` proved it fully current. (2) In the B2 audit, Code
framed its 11-of-31 dossier coverage as "signal-first"; reading the *actual parquet* showed it was really a
representative sample that dropped two rich showcases (trap, ypfl) while keeping a known-empty one — and it
surfaced a deeper truth Code's summary understated (dossiers are a sparse *cross-league* signal; even the
flagship league is 9/10 empty). Check the file and the data, not the summary.

---

## Read these first (source of truth — not chat history)

- **Your own project memory** (`store-migration-stageB`, `store-migration-audit`, `will-role-and-framing`) —
  the fastest way to reload the full state, decisions, and process gotchas. Start here.
- `LLM context/STATUS.md` — the **live engineering log.** Top section is the "STORE MIGRATION TRACK"; Code keeps
  it current each session. Currently headed at B2 shipped, B3 next.
- `scope docs/future work/MULTI_LEAGUE_STORE_MIGRATION.md` — the architecture + phased plan (Stages A + B0–B6).
  **Two stale spots to read past:** it says **SQLite** (superseded by Supabase-Postgres), and its `/api/leagues`
  contract example shows a slug `lineage_id` + `viewer_roster_id: 7` (both wrong — lineage_id is the root
  league_id, lorp's viewer is 8). Otherwise accurate.
- `scope docs/future work/OWNER_KEYED_MANAGER_PROFILES.md` — the one **deferred** design doc (owner-keyed
  dossiers). Tracked in git. Relevant to B3+ (owner_id must be carried) and the future dossier rework.
- `scope docs/future work/_archive/` — **all the session runbooks + audits** (SESSION_1…6, B0/B1/B2, and their
  `*_AUDIT.md`). Read for house style and what each session actually did. **Note: `_archive/` is gitignored
  (`.gitignore:206`) — these are local-only working docs, never committed.** Only persistent scope docs live in
  git.
- `LLM context/TECHNICAL_ARCHITECTURE.md` — has the store-migration target architecture + the 13-table schema
  reference; some older "client-side/DuckDB" phrasing is historical.
- `co-build guides/SESSION_GUIDE.md` + `CLAUDE.md` — the Code session lifecycle (worktree → setup → 3-commit
  cap → STATUS → merge) and the engineering guide Code follows.

---

## Decisions locked with Will (don't re-litigate)

- **Infrastructure-first, then multi-league.** Stage A migrated the store at single-league parity; Stage B adds
  multi-league/season on top. The frontend change is the small last mile; the plumbing + content are the work.
- **Store = server-side FastAPI + Supabase-hosted Postgres on Fly.io.** Not in-browser DuckDB, not SQLite.
  Postgres chosen so **auth is a later bolt-on** (Supabase Auth) — deferred but must stay ready.
- **Same-origin hosting (Option A):** one Fly app (`fantasy-ai-api`, region `iad`) serves the built SPA at `/`
  and `/api` (no CORS). Live at `https://fantasy-ai-api.fly.dev/`. Postgres via the session-pooler
  `DATABASE_URL` (env-var → `config.py` fallback). Tables have RLS enabled, no policies. GitHub auto-deploy off
  (Code deploys via CLI). Custom domain parked.
- **Demo slate LOCKED: 12 lineages / 31 league-seasons**, no dynasty. Recorded in `snapshots/demo_manifest.parquet`.
  **Panel policy:** manager dossiers gated ON for all 31; market + bull/bear/sit ON only for the live lorp-2025
  slice ("gate historical, keep dossiers — honest over fabricated"). Viewer pinned per lineage.
- **B2 dossier coverage stays at 11/31 (Will's call).** The cross-league comparability design means dossiers
  only populate for managers with *other* same-format leagues — so 12-team standard formats + the primary user
  render rich, and superflex/keeper/rare-size come back "no intel" (even flagship lorp is 9/10 empty). Code
  computed 11 slices (lorp/nbl/dysf/wcfc); trap+ypfl were left un-run. Will chose **not** to backfill —
  "something shown, not overcommitting to a pipeline I'll rework." The backfill is a one-command run available
  anytime (`compute_demo_slices.py --phase dossiers --dossier-lineages …`); the future dossier rework
  reorganizes/displays existing signal, it does **not** fill the empties. Don't reopen this.
- **No new scoring formats/models** (standard/custom/dynasty parked).

## The session map

**Stage A — DONE (all merged + live):**

| # | Session | Status |
|---|---|---|
| 1 | Fly + Supabase foundation; FastAPI skeleton | **DONE** |
| 2 | Postgres schema (13 tables) + parquet→Postgres loader + RLS | **DONE** |
| 3 | Players + Teams read endpoints; JS calcs → Python | **DONE** |
| 4 | League + Matchups endpoints + team-detail `thisWeek` win-prob chain | **DONE** |
| 5 | Frontend → API client (`queries.js` → `fetch`; DuckDB deleted) | **DONE** |
| 6 | Parity verification + go-live (same-origin deploy) | **DONE — app is live** |

**Stage B — multi-league/season (`MULTI_LEAGUE_STORE_MIGRATION.md` B0–B6):**

| # | Session | Status |
|---|---|---|
| B0 | Record the demo slate (`demo_manifest.parquet`) + panel policy + pinned viewers | **DONE + audited** |
| B1 | League-scope the `schedule` (path + `league_id` col) + keyability sweep | **DONE + audited** |
| B2 | Full-set compute over all 31 slices (spine + schedule all 31; dossiers 11) | **DONE + audited** |
| B3 | Load all 31 slices from the derived store into Postgres + `GET /api/leagues` catalog | **DRAFTED — handed to Code** |
| B4 | Parameterize every read endpoint on `league_id` + `season` | not yet drafted |
| B5 | Frontend selectors + `viewer_roster_id` replaces `MY_USERNAME` + panel gating | not yet drafted |
| B6 | End-to-end verification across every league × season × sample weeks | not yet drafted |

Don't start B5 until B4 is done (selectors need parameterized reads).

## Gotchas / decisions carried forward (live for B3+)

- **B3 is the first Stage-B production write.** B0–B2 were parquet-only (live app + DB untouched). B3 reloads
  Supabase from the derived store (`DROP + CREATE`). The **parity guard is the whole safety net**: after the
  reload, the deployed app must render the is_mine league *identically* — it only adds the other 30 leagues
  alongside it. Don't touch Fly secrets (`LEAGUE_ID`/`MY_USERNAME`); the selector that varies them is B4/B5.
- **B3 loader specifics (in the brief):** source from `derived/league/<id>/` (not `public/data`),
  manifest-driven; **skip-if-absent per (slice, dataset)** (base 31, dossiers ~11, market/ros 1 — a missing
  panel is correct, not an error); the post-B1 `schedule` parquet already carries `league_id` → **de-dup** vs
  the loader's stamped constant (else two `league_id` cols = SQL error); **carry + index `owner_id`** on
  `manager_dossiers` (OWNER_KEYED prerequisite — already a column on disk); `verify()` drops the `n_leagues==1`
  assertion.
- **`owner_id` prerequisite** (from `OWNER_KEYED_MANAGER_PROFILES.md`): B3 must keep it first-class so the
  deferred owner-keyed dossier rework is a small read-swap later, not a migration. Baked into the B3 brief.
- **`MY_USERNAME` → `viewer_roster_id`** refactor is B5. The `projection_consensus` `*_ppr` naming wart
  (columns named `*_ppr` that hold league points) also waits for the B5 `queries.js` rewrite.
- **Postgres dialect discipline** (carried from Stage A): DuckDB `QUALIFY`/`arg_max`/`any_value` have Postgres
  ports; verify numbers, don't trust "it runs."

## How the work flows
1. You write a session brief (`.md` in `scope docs/future work/`) — or a short in-chat punch-list for tiny work.
   House style: what it does · your-part/Code-part split · decisions (recommend on forks) · the paste-to-Code
   brief · definition of done · gotchas. Session briefs + audits are **local-only** (they end up in the
   gitignored `_archive/`); persistent scope docs get committed.
2. Will hands the brief to Code; Code executes in a worktree and reports back.
3. **You verify the report against the live store/branch/data**, then endorse or push back with a named reason.
   File the audit in `_archive/`.
4. Merges + pushes happen on **Will's machine** (this sandbox reads the repo but can't merge/push).

## How to verify (process that works here)
- **Audit via `device_bash` + git + container-polars on staged data.** The file bridge can serve **stale code
  snapshots** (bit us in the S4 audit — nearly reported merged work as missing); `WebFetch` caches ~15 min
  (bust with cache-busting URLs). Trust `device_bash`/git for code, and the actual parquet for data.
- **Reading parquet:** the connected folder is `/Users/willdaniel/Documents/fantasy-ai`; derived data lives in
  `application/data/snapshots/` (gitignored). The device's `python3` has pandas but **no parquet engine and no
  network** → **stage the parquet into this container** (`device_stage_files` needs **device-native paths**
  like `/Users/willdaniel/…`, not the `/sessions/…/mnt` mount), then `pip install polars` here and read it.
- `device_commit_files`: pass the **actual `file_uuid`** from `SendUserFile`, never the string `"$LAST"`.

## Standing instructions
- **Parity is still the guard rail** — for B3+ it means the live app must stay byte-identical through each
  production reload until the frontend selectors intentionally change what's shown (B5).
- **One architectural change at a time** — the discipline that keeps this a swap, not a rewrite.
- **Keep the `queries.js` seam clean** — if a fix wants to sprawl into views, stop and reconsider.
- **Verify Code, don't trust the report** — read the live file and the real data.
- **Surface decision forks to Will** — plain-English, with a recommendation; then respect his call.

## ⚠ Housekeeping to remember
- **The stale `.git/index.lock` recurs on Will's machine** (0-byte; this cloud VM **can't** unlink it —
  "Operation not permitted"). It blocks `git add`/`commit` (not push). Remind Will to `rm -f .git/index.lock`
  from his own terminal before each Code session.
- **This doc + STATUS are tracked; audits/briefs are not.** If you update this file, Will commits it (the lock
  blocks you, and it's a tracked doc).

## Your immediate task (as of 2026-07-26)
**Shepherd B3.** It's drafted (`_archive/`-bound `SESSION_B3_LOAD_AND_CATALOG.md`, currently in `future work/`)
and handed to Code. When Will relays the report, **audit it against live data**: all 31 slices loaded from the
derived store with correct per-slice panel gaps honored (base 31, dossiers ~11, market/ros 1); the `schedule`
`league_id` de-dup done; `owner_id` retained + indexed; `verify()` shows sane per-table league counts; and —
the headline — **the production reload left the deployed app rendering the is_mine league exactly as before**
(hit the live URL; Fly secrets unchanged). Confirm `GET /api/leagues` returns the lineage→seasons tree grouped
on the root `league_id` with correct viewers/panels. File the audit in `_archive/`. **Then draft B4** —
parameterize every read endpoint on `league_id` + `season` (path or query param; server SQL filters on them),
the last plumbing step before the B5 frontend selectors make multi-league *visible*.
