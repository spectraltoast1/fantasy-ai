# P5 · S4d — report: the weekly cadence, and the two defects Will's live test found

**Shipped + deployed 2026-08-15** (API and worker both). **Brief:** `SESSION_P5_S4D_WEEKLY_CADENCE.md`.
**Commits:** 3 (`b81cb28`, `aab10d9`, this one) on `claude/p5-s4d-session-plan-f6d16a`.

**The one-line result:** the league that produced a raw `FileNotFoundError` with an internal path in
Will's browser now returns *"the draft hasn't happened yet…"* at attempt 1 — and the app has a
cadence for the first time. **The honest limit: no 2026 league is linkable today, so the week-advance
itself is still unproven.**

---

## The before and after, on the same league, on production

The actual row Will's test left in `public.jobs` at 00:46 UTC:

```
kind=onboard  league_id=1389327290164314112  season=2026  state=failed
error: FileNotFoundError: No such file or directory (os error 2):
       .../data/snapshots/nfl_sleeper_weekly_joined/league/1389327290164314112/season_2026.parquet
```

The same league, same route (`POST /api/connect` with a pasted id), after the deploy:

```
state=rejected   attempts=1
error: the draft hasn't happened yet, so this league has no rosters yet and there is nothing to
       build from.
         Nothing is wrong with the league or with your account. Link it again once your draft is
         done and the season is under way.
```

`failed`+retried-to-3+a filesystem path → `rejected`+attempt 1+words a person can act on.

---

## 1 · The blocker was completed weeks, not the draft

`sleeper.backfill` writes only **completed** weeks, and `_determine_completed_weeks` returns
`leg - 1` during the regular season. `leg` is 1 *during* Week 1, so completed is **0** at kickoff and
the first completed week arrives ~17 Sept. **Every cohort member linking at launch would have hit
this.**

`_determine_current_week` is `backfill`'s deliberate complement — `leg`, exactly the week it refuses
— and `fetch_current_week` snapshots it. `harvest._pull_raw` calls both. Measured across the boundary
that matters:

| NFL state | completed | current |
|---|---|---|
| `pre`, `leg=0` — **today** | 0 | 0 |
| `regular`, `leg=1` — **10 Sept** | 0 | **1** ← Week 1 works because of this |
| `regular`, `leg=5` | 4 | 5 |
| `post` | 18 | 0 |

**It does nothing before 10 Sept and that is correct** — there is no in-progress week in the
preseason. This does **not** fix the August window; S4f's pending hold is what does.

**Not `sleeper.refresh()`, which already fetched the current week.** `refresh` is is-mine-shaped: it
also writes five `CACHE_DIR` JSON blobs that are **not league-keyed**, so pointing it at a stranger's
league overwrites the owner's cache. Nothing reads those blobs today, which is why this had never
bitten — but `weekly_refresh` called it, and S4d puts `weekly_refresh` on the queue for **every**
connected league, so it would have overwritten one shared cache with each league's data in turn every
Tuesday at five wasted Sleeper GETs apiece. Both call sites now use the league-keyed function.

### The finding about the spine, which changed what "fix" meant

The join **writes no file at all** when it joins no weeks, and `compute_production_vor` reads that
parquet unguarded. Three of the five spine reads already carry well-worded named diagnoses for
precisely this state — and **all three are unreachable**, because each one's own unguarded
`read_join_season` raises first:

| read | reads the join | needs realized results | zero-results reality |
|---|---|---|---|
| `production_vor` | yes, **unguarded** | no — the join supplies roster membership and the as-of clock; value is projections-only | can produce honestly |
| `true_rank` / `positional_depth` | no (read `production_vor`) | no | can produce |
| `bracket_odds` | yes, **unguarded** | **yes** (standings) | named `RuntimeError`, shadowed |
| `player_signal` | yes, **unguarded** | **yes, entirely** | named `RuntimeError`, shadowed |

So the fix is one refusal in the chain that knows *why*, placed before the spine — not five guards in
transforms that only know a file is missing.

**Reported, not papered over:** `player_signal` cannot honestly produce on zero realized results and
`bracket_odds` would simulate a 0-0 slate. At Week 1 both get one zero-filled week. That is exactly
the case P2/S4a's thin-data window was built for — the depth clock counts weeks with real **results**,
not weeks loaded, and below three it withholds posture, clinch and trend. **No new claim is being
made on thin data; the existing honest-window behaviour covers it.**

## 2 · The error a user sees, and the retry semantics

`_job_payload` passes `error` through unchanged and `App.jsx` renders it raw, so **whatever the worker
writes into that column is on somebody's screen.** Three outcomes now, not two:

| | state | text |
|---|---|---|
| `SystemExit` — an authored refusal | `rejected` | **its own words**, unchanged (S4c's rule, still right) |
| `StoreBoundaryError` — a stale shared band | `rejected` | **sanitised** |
| anything else — a crash | `failed` (retryable) | **sanitised**, keeping only the class name |

`StoreBoundaryError` is the case that was neither: **deterministic** (attempts 2 and 3 recompute the
identical frame and refuse identically), so retrying it to the cap was wrong — but its message names a
laptop command line and `OPERATIONS.md`, so it is not shown either. Terminal like a refusal, sanitised
like a crash.

The crash branch keeps the **exception class name** and drops the message. A class name is a Python
identifier — never a path, an id, or user data — and it is the single most useful triage token for
whoever reads the `jobs` table instead of the worker's logs, which this brief required to be enough.

**The operator-aimed `SystemExit`s in `weekly_refresh`** (`is_synthetic`, `_resolve_scoring_key`) embed
shell commands, and putting `weekly_refresh` on the queue is what made them reachable. They cannot
reach a user: a refresh job has `requested_by = NULL`, and both `job_for_owner` and
`active_job_for_user` filter on it, so no banner and no `GET /api/connect/{id}` can return one.

## 3 · One predicate, two callers

`status` was **already fetched on both sides and discarded on both** — `platforms._shape` projected it
away, and `sleeper.league_summary` returned it into a dict `assert_in_scope` never read.

`platforms.league_has_started` now lives in `application/api/`, and **both images import it**:
advisory in `classify` (greys the button), **authoritative** in `assert_in_scope` (raises). The worker
is the half that has to be right, because `POST /api/connect` with a pasted league id runs **no
classification at all** — proven above. Zero extra Sleeper calls: `onboard()` already calls
`league_summary` one line earlier.

The direction is the one `jobs.enqueue` established and it is enforced, not merely observed:
`worker_loop` already did `from application.api import jobs, platforms`, and `check_connect`'s ONE
IMAGE leg fails on any `application.data` import under `api/`.

**Absence of `status` is treated as PLAYABLE** — the opposite of `settings.type`, deliberately: a
missing lifecycle field is a Sleeper omission about a league that demonstrably exists, while a missing
type genuinely does not say whether it is redraft.

**Terminal is not a dead end.** `jobs_active_league_idx` is partial on **non-terminal** states, so a
rejected job blocks nothing: the same person can link again after their draft. S4f replaces the
**branch**, not the predicate.

## 4 · The cadence

`weekly_refresh.yml` stopped being a pipeline machine. It runs
`python -m application.api.enqueue_refresh`, which enumerates `user_leagues ⋈ league_catalog` at the
current season and calls `jobs.enqueue(kind='refresh')` per league; the worker executes.

**The brief proposed one `INSERT … SELECT` in YAML. It was dropped, and the deciding reason was not
either of the obvious two.** A raw INSERT forgets the `NOTIFY` and re-derives the season — but
`check_connect`'s ONE SEAM leg scans **`application/**/*.py`**, so SQL embedded in YAML is invisible
to it: the second producer would have arrived through the one door the gate cannot see, **and the gate
would have stayed green.** The workflow keeps its checkout and installs `api/requirements.txt` (no
polars, no numpy).

Three things the enumeration query has to get right, all confirmed against production:

- **`DISTINCT` is load-bearing, not tidiness.** `user_leagues`' PK is `(user_id, league_id)`, and Rex
  Lumber has **three owners** in production today — so the raw join returns 3 rows for 1 league and
  two of them would hit the unique index. The run produced **exactly one job**.
- **`season` comes from the catalog**, because `user_leagues` deliberately has no season column.
- **`NOT EXISTS`, not `ON CONFLICT`.** `jobs_active_league_idx` does not include `kind`, so a refresh
  collides with an in-flight **onboard** too. Filtering makes that a row never inserted rather than an
  exception to explain away — and it is counted and printed **separately from an error**.

**The demo falls out twice over** — nobody owns it, and it is a 2025 league — and that is the *reason*
for sourcing from `user_leagues`, not a coincidence: `league_catalog` alone would enqueue
`DEMO-2025` every week, and `weekly_refresh` **raises** on a synthetic league by design.

**`MY_USERNAME` / `LEAGUE_ID` are retired, not relocated** — gone from the workflow *and* from
`fly.worker.toml`. Every job carries its own `league_id`, and `check_queue` asserts from the AST that
`_execute_refresh` passes it. While they were set, a path that forgot its league id fell back to the
**operator's** league and produced a healthy-looking job row for the wrong league.

**One defect found in my own executor before it shipped:** `refresh_league(..., live=True)` overwrites
season *and* target week from Sleeper's state, so it ignored the job's own `season` — a job enqueued
before a season rollover would have run against the new season under the old season's league id. A
mismatch is now a terminal refusal.

**`stage` threaded through `refresh_league`, and it is not decoration:** `job_queue.advance` is what
**renews the lease**, so a refresh reporting no stages would hold a 120s lease for its whole run and
anything longer would be reclaimed and executed twice.

## 5 · `collectors.yml`, the brief's open question — answered

**It set no `STORE_ROLE`.** The ADR claims the GHA runner is covered and S3's audit cited
`weekly_refresh.yml` as the evidence — but `collectors.yml` is a **second workflow on that same third
machine**. The claim counted *machines*; the enforcement is per-*workflow*.

**No live hole:** its three entrypoints reach five writers (`write_leaguelogs_market_snapshot`,
`write_team_news_raw`, `prune_team_news_raw_content`, two metadata writers) and none is in
`LAPTOP_OWNED_WRITERS`. But it **flushes to the shared Supabase bucket**, so a future collector
touching a laptop-owned path would land in the substrate every league reads, not on a scratch disk.
One line; added.

## 6 · A second finding — the allow-list is a deny-list

`data_layer`'s header, `ARCHITECTURE.md` and the ADR all claim *"anything unclassified refuses by
default."* **It does not.** Enforcement is an explicit `_require_laptop(...)` call inside each of the
16 writers, so of `data_layer`'s **50** `write_*` functions the other **34 are permitted**.
`check_store_boundary`'s REFUSES leg iterates `LAPTOP_OWNED_WRITERS` itself, so it catches a *listed*
writer whose guard was deleted and structurally **cannot** catch an *unlisted* writer that never had
one.

**The 16 are the right 16 — this is a wrong claim, not a live hole.** All three docs corrected. The leg
that would make it true (enumerate `data_layer`'s writers, fail on any unclassified) is **recorded and
not built**: S4d had no mandate to change that guard.

---

## Proven live, 2026-08-15

| # | claim | evidence |
|---|---|---|
| 1 | linking works **at** Week 1 | the week arithmetic across the boundary (table above). **Replay, not a live Week-1 link** — `leg` is 0 today, so this cannot be exercised naturally until 10 Sept |
| 2 | a crash leaks no path; a refusal keeps its words | both halves asserted in `check_queue`, and the live before/after above |
| 3 | a deterministic refusal is terminal | `state=rejected`, **`attempts=1`**, not `failed` retried to 3 |
| 4 | a `pre_draft` league is refused with a reason | live prod, on the **pasted-id path that runs no classification** |
| 5 | the cadence reaches the worker unattended | enumerate → INSERT+NOTIFY → **leased 0.09s later** → the `refresh` executor ran → terminal. **Proof the image shipped:** the identical job kind returned *"unknown job kind 'refresh'"* before the deploy |
| 6 | a second run is a legible no-op | with an active job, `due=[]` and `skipped=[the league]`, exercised in an **uncommitted transaction** the live worker could never see, rolled back — 0 rows left behind |
| 7 | `MY_USERNAME` / `LEAGUE_ID` gone | from `weekly_refresh.yml` **and** `fly.worker.toml`; AST-asserted that the executor passes `lid` |
| 8 | nothing else moved | signed-out prod returns **exactly** the demo; `/health` → season 2026 **derived**; `league_catalog` 33 → 33; **0** grants for the refused league |

`STORE_ROLE`'s removal from the workflow was verified rather than assumed: **no `application.data`
module loads on the enqueue path**, and in the api-tier venv `data_layer` is not importable at all
(no polars). It is dropped because what it guarded is unreachable — and if that ever changes, it
comes back.

**Gates:** `check_connect` 30 → **37**, `check_queue` 16 → **21**, both with the new legs proven to
bite (pre-S4d `classify` fails 2 of the 6 lifecycle cases and correctly passes the 4 permissive ones).
`check_ownership`, `check_isolation`, `check_store_boundary` unchanged and green.

---

## Carried forward

- **THE BIG ONE — no 2026 league is linkable today, so the week-advance is unproven.** All ten of
  Will's leagues are now correctly greyed: seven dynasty, one pre-draft, two prior-season. The
  enumeration returns **0 connected leagues for 2026**. The plumbing is proven end to end on the
  deployed worker; **a real advance through the queue is not**, and cannot be until a league drafts.
  **This is the strongest possible argument for S4f** — right now the product's answer to Will's own
  league is "come back later", which is the first impression nearly every invited user would get.
- **The release valve was NOT taken.** `check_ownership` / `check_isolation` still hardcode
  `DEMO = "1182101676608823296"`, the id S2d replaced. It is bigger than two constants: `DEMO` is the
  `demo_league_id` threaded through *every* call of the function under test, so ~49 of 59 and ~70 of
  89 assertion sites depend on it, and two assertions are only meaningful *because* the id maps to a
  non-current season. **→ S4f**, as the brief directed.
- **The store-boundary gate leg** that would make the default-deny claim true — recorded above, not built.
- **`jobs` cannot distinguish "advanced" from "was already current"** — both are a clean `ready`.
  A nullable `result` column would close it. Flagged, not assumed.
- **`sleeper.refresh()` now has no caller in the cadence.** It remains for the is-mine CLI. Its five
  non-league-keyed cache blobs are written by nothing else and read by nothing at all — a candidate
  for deletion by a session that owns that file.
