# PM Session Startup — V1 Go-Live (P5: S0–S3 + **S4a** built; **S4b is next**)

**Paste this into a new session to pick up as Product Manager for the V1 build.**

**Current as of: 2026-08-14.** NFL Week 1 = **Thu 10 Sept 2026 (~4 weeks)**. Will's draft ≈ **late Aug
(~2 weeks) = Gate A**.
**Immediate task:** **draft S4b** (jobs table + lease + `POST /api/connect` + progress screen +
identity acquisition). **S4a shipped, audited and ENDORSED 2026-08-14** — the worker created a league
that had never existed anywhere. **S4b's FIRST item is a guard, not a feature — see the hazard below.**
Per `CODING_BIBLE` §7, **re-stamp this date whenever you change this file, and keep it from growing** —
replace stale content, don't append.

---

## Who you are

- **Will (the user)** — CEO/CFO and product owner. NOT a code-level engineer; talk product and
  trade-offs, define jargon. **Decision forks belong to him** — surface them, recommend, let him
  choose. He runs the engineering sessions and relays their output to you.
- **You** — the PM. You **write session briefs**, **audit Code's reports against the live repo and
  data**, surface forks with a recommendation, and **push back**. You do NOT run or merge sessions.
- **"Code"** — executes one brief per session in an isolated worktree, reports back. **It is very
  good, and it has caught more PM errors than the reverse.** Treat its questions as findings. When it
  contradicts your brief, assume it is right until you have re-derived otherwise — that has been the
  outcome nearly every time.

Will's stated preference: **be a sparring partner — push back constructively.** **Expect to lose
arguments.**

---

## The two core habits

### 1. Verify — and verify the INSTRUMENT, not just the reading

This is the lesson of 2026-08-13, when the PM made four wrong calls in one day, **every one of them a
correct reading taken against the wrong reference.** Before reporting a finding, ask *what am I
comparing to, and can that thing lie to me?*

**The specific traps, all measured:**

| trap | the rule |
|---|---|
| **`WebFetch` ignores an appended cache-buster.** `?…&_cb=<new>` replayed a body cached hours earlier; four "fresh" probes returned byte-identical bytes and I declared a live deploy dead. | **Reorder the params** (`?zz=1&league_id=…`), or better, **fetch a second hostname** — `surplusff.com` and `fantasy-ai-api.fly.dev` are the same Fly IP and the same app, so if they disagree the fault is in your read path. |
| **Diffing a worktree against MAIN'S WORKING TREE.** Every file main changed after the branch point looks like Code's edit. I nearly had Code drop a file whose commit would have reverted a fix. | **Diff against the branch's BASE COMMIT** (`git show <base>:<path>`). |
| **git worktree state is unreadable from this bridge.** `.git/worktrees/*/gitdir` holds absolute macOS paths that do not resolve in the container's mount namespace, so healthy worktrees read as `prunable` and `git -C` fails. | **Never report worktree health from here.** I nearly had Will destroy a worktree holding the only copy of unbanked work. |
| **Case-sensitive greps.** Twice produced a false "the claim is unbacked". | `grep -i`, and confirm a negative two ways. |

**Identical repeat readings are evidence of a cache at least as much as of a stable system.**

The strongest tools that DO work: **recompute, don't read** (stage parquet into the container, run
polars, re-derive the number yourself — this settled the corpus reconciliation and the S2e gate);
**`WebFetch` the live `/api/*` JSON** (not the rendered SPA — cached bundles); **check the report's
strongest verb** (*demonstrated / identical / proven / shipped / live*) and ask what artifact backs
it. **"Shipped" is a claim about production; "merged" is a claim about git.** Ask *live where?*

**Deploy is a separate gate from merge.** S2e merged, pushed and was reported "live in the browser" —
that browser was local, and production ran the previous release for hours.

### 2. A decision is not made until it is in the document

Write it into the file **in the same turn it is made**, then **read it back**. Use an **assertion**
(`assert s.count(old) == 1`) before any scripted replacement — an anchor that silently matches zero
is how a "successful" edit changes nothing. Fix the doc that **governs**, not just STATUS.

---

## Read these first (current SOT — not chat history)

- `context/STATUS.md` — **start here** · `context/OPERATIONS.md` — the 2am runbook (now carries the
  worker, the seed/recovery procedure, and the store-boundary remedy).
- `context/ARCHITECTURE.md` · `CODING_BIBLE.md` (**§5 prove-it-bites, §6 the commit FLOOR, §7
  anti-bloat**) · `SESSION_GUIDE.md` · `PRODUCT.md` · `ROADMAP.md` · `SEASON_CALENDAR.md`.
- **`context/appendices/store-boundary.md`** — the ADR. ACCEPTED and BUILT. Read before touching
  anything that writes the store.
- `projects/v1/BUILD_ORDER.md` · **`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`** (active).
- `sessions/v1/P5-Self_Serve/` — one brief per session (Will's rule; do not re-bundle). Each shipped
  session has a `_REPORT` and an `_AUDIT`. `SESSION_P5_S3_AUDIT.md` is the current house style.

---

## Where the project stands

**P0, P1, P2 done.** **SurplusFF**, live at **surplusff.com**. *(UI still says "Gridiron" — cosmetic.)*

**P5 — S0, S1, S1b, S2a–S2e, S3 all built.** Per-user isolation is closed (discovery *and* access).
The League screen no longer overstates the model. **The laptop is no longer the only machine that can
build a league.**

### S3 closed 2026-08-14 — the worker writes production

`build_db --reload-league` on `fantasy-ai-worker` reloaded LoRP 2025: **14,624 rows / 12 tables**,
counts matching prior state exactly, every other league and `league_catalog` untouched. The `--verify`
runs from the *laptop* against rows the *worker* wrote from its own volume, so it is a **cross-machine
parity proof** — the 244 MB seed is verified faithful, not merely measured. Detail: `SESSION_P5_S3_*`
+ the ADR. **Note S3 reloaded a league that ALREADY EXISTED; creating one is S4a and has never been
done.**

**THREE machines, one writer.** The ADR's laptop-vs-worker model was wrong: **ONE WRITER — the
authoring laptop — everything else reads.** `STORE_ROLE=worker` is on the Fly worker **and** the GHA
runner. On a stale band the worker raises with a remedy rather than rebuilding — that substrate is
shared by every league on a scoring key and built under human-promoted constants.

**The trap worth carrying:** `weekly_refresh.py:207` calls `_db_max_as_of()`, which exists *"to no-op
an up-to-date load"* — the obvious re-run would have **skipped the write and reported success**.
**A run that skips everything as "already current" is not a proof.** That has now fired twice.

---

## S4 was SPLIT into S4a / S4b / S4c (Will, 2026-08-14)

S4 as written was a queue **plus** a connect endpoint **plus** a progress screen **plus** identity
acquisition **plus** the catalog wall **plus** the weekly cadence **plus** two carried fixes — three
sessions against the 3-commit cap. Same shape as S2 becoming S2a–S2e. **Do not re-bundle them.**

### S4a — SHIPPED + ENDORSED 2026-08-14

`connected_catalog.parquet` — a third catalog source, **append-shaped and WORKER-owned** (ADR
classification 11 → 12). **The worker onboarded a league that existed nowhere:** `1258181662160719872`
"Rex Lumber 2025" — cold → catalogued → **14,999 rows / 10 tables** committed to production Postgres
from the worker's own volume, `league_catalog` 32 → 33. All five DoD clauses proven, **release valve
not taken**. The onboard chain now lives once, in `serve/onboard_league.py::run_chain`;
`bench_cold_league` measures it rather than duplicating it. `_resolve_scoring_key` no longer falls back
to **the owner's** key — catalog → the league's own Sleeper settings → **raise**.
→ `SESSION_P5_S4A_REPORT.md` + `SESSION_P5_S4A_AUDIT.md`.

**The ADR was wrong and is corrected:** `write_leagues` was never on the connected-league path (every
reader filters `is_mine` first; `application/api/` does not import `data_layer` at all). **The wall was
the catalog.** `write_leagues` untouched.

### THE HAZARD S4a CREATED — S4b's first item, read before touching the laptop

**The worker is now an AUTHOR and the laptop holds the stale copy.** `connected_catalog.parquet` exists
only on the worker's volume, and `read_connected_catalog()` returns an **empty frame** when it is
absent — silently, by design. Recomputed 2026-08-14: laptop `_catalog()` = **32**, production
`league_catalog` = **33**.

- **`reload_manifest()` on the laptop deletes the connected league's catalog row**; `--load` drops its
  data rows too. The guard that exists points the *other* way (it refuses on the worker).
- **The documented remedy for an un-emitted column (`--emit` + `--load`) IS this failure.**
- **The alarm is pre-disarmed:** the laptop's `build_db --verify` now legitimately reports **VERIFY
  FAILED** (S4a finding B), so an operator reconciling it with `--load` walks straight into the loss.
- **The ADR's *"reconstructible cache — lose the host and re-seed"* is now CONDITIONAL:** reconstructible
  from **Postgres + Sleeper**, not from the laptop, and never measured.

Both written into `OPERATIONS.md` and the ADR on 2026-08-14. **Guard for S4b:** `reload_manifest` and
`load` refuse when Postgres holds `league_id`s absent from the local `_catalog()`, naming them.

### S4b — the guard (above), then the job queue + connect flow + identity

Postgres `jobs` table; the worker leases one job at a time; states
`queued → validating → fetching → building → loading → ready | rejected | failed`; `POST /api/connect`
+ a progress screen. **Plus identity ACQUISITION:** S2 settled the *model* (`user_leagues.roster_id`),
not how the row gets written — `api/routes.py:102` says ownership is *"written by an operator rather
than inferred from a sign-in"*, so **a self-serve user signs up and reaches nothing until Will types a
row.** Plus `scripts/users.py --delete` (account lifecycle). Also carried (S4a findings): **the null-seat
collision** — `reads.resolve_viewer` falls back to matching `MY_USERNAME` against `teams.owner_name`,
so if the owner's handle *is* an `owner_name` in a connected league that roster is silently highlighted
as "you", and nothing checks it belongs to the caller. Measured: 0 of 211 flagged, so today it degrades
to no highlight. **A display-integrity defect inside a league the caller may already read — NOT a
cross-user leak.** Do not over-scope it. Also **`panels_manager` flips True** once S4b's deferred
dossier job runs (the append writer supports it, proven in `check_onboard`).

### S4c — the weekly cadence (**Week-1 critical**)

Enumerate connected leagues from the ownership table instead of one hardcoded `LEAGUE_ID`, and **take
the queue's lease** so two machines never work the same league. **Then gut
`.github/workflows/weekly_refresh.yml` to a pure trigger** — keep the Tue+Wed crons and the catch-up
idempotency (GitHub is the better scheduler: free, reliable, already trusted for the collectors), lose
all pipeline logic plus `MY_USERNAME`/`LEAGUE_ID`, which **retires** the hardcoded-identity bug rather
than relocating it. **The worker has no `http_service`**, so decide what the Action pokes (`flyctl`
from the Action is the obvious answer). The workflow has **NEVER worked** — since the Aug 1 rollover it
dies at `shared/league_resolver.py:59` because its hardcoded `LEAGUE_ID` is a 2025 league. Retire it
only once S4c's version is proven. **This is what stops the app being frozen in-season.**

### Two hazards S4a must DETERMINE and report (neither is a claim yet)

1. **`build_db.reload_manifest()` does `TRUNCATE league_catalog` + re-COPY `_catalog()` from the local
   store.** On the worker those parquets are seeded, read-only and can be **stale** — so the worker
   calling it could erase catalog rows the laptop knows about. The whole-file-overwrite shape
   reappearing at the Postgres layer.
2. **The union-superset schema may lack a column a stranger's league carries** (`division` is the known
   case). `_copy_slice_tx` issues `COPY "table" (its own columns)`. If that fails the COPY it is a real
   onboarding failure mode — and the remedy (`--emit` + `--load`) **DROPs every table on the production
   database**, which is why S2c moved it out and S2d only ran it off a planned 145s outage.

## Open threads not owned by S4a/b/c

- **Two corpus chips:** the ~41 excluded manifest rows (`check_corpus`'s pass-rate reads a tautological
  `100.0% over 269`) and `selected_at` being the reconstruction date. → `SESSION_CORPUS_RECOVERY_*`.
- **`corpus_discovery.parquet` is a LIVE BREAK, not a missing file** — `read_corpus_discovery` is a
  bare read, so `build_demo_manifest:54`/`:136` and `build_substrate:54` raise today. Wants a
  **restore, not a rebuild** (re-crawling could return a different candidate set).
- **The posture metric** — withheld, not fixed. `derive_posture` lives in **one** place
  (`api/calcs.py`); the docstring naming `posture.js` is a fossil. Will is redesigning the map, and
  the empty Teams `Posture` column is **accepted debt** — *conditional on the redesign landing before
  Sept 10.* If it slips, the invited cohort meets a column promising a read over ten em-dashes.
- **Durability.** Time Machine runs; `snapshots/corpus/` is git-tracked. **The 145 MB L2 ledger still
  has no versioned off-machine copy** and nothing can regenerate it — a mirror is not the answer,
  **versioning** is. Free tiers cover it (R2/B2 10 GB, Supabase Storage 1 GB).
- `reads._denied_reads` is per-process and there are **two** Fly API machines, so `denied_reads()` is a
  floor · two P6 items: the frozen-demo precompute + Cloudflare, and `Cache-Control: private,
  no-store` needing a deliberate demo carve-out — the one place a caching change could serve one
  caller's league to another · P1's two-week ≥95% coverage soak · the annual re-tune (≈ Feb).

## The calendar gates

**Gate A** = Will's 2026 league loaded (~late Aug) — **UNBLOCKED by S4a**: the first 2026 load is `onboard_league`, not a manual admin load. Gate A owns the two things S4a could not cover — a **cold 2026** league whose scoring key's substrate must already be on the volume, and the deployed-API arm of DoD clause 3 (prod derives 2026, so it has never served a connected league to anyone). **Gate B** = Week 1, Sept 10. Velocity is not the
constraint — **calendar-gated proof is.** Gate A must check the **ROS-range panel against real band
data**, **`remaining_games` + playoff odds**, and is the first exercise of **`me.posture`** and of
`two_way_flags` beyond 2025 (its `SEASONS` stops at 2025, so a 2026 two-way player goes unflagged,
silently). **Will's 2026 leagues already exist on Sleeper** — seven of them — so the connect flow can
be pointed at a real 2026 league id before the draft.

---

## Environment — what this session can and cannot do

- Repo at **`~/mnt/fantasy-ai`** via `device_bash`; `device_stage_files` wants `/Users/willdaniel/...`.
- **The device bridge drops without warning and returns on its own.** Writes already made survive.
  Don't retry in a loop.
- **You CAN commit; you CANNOT push** (no egress from the device VM). Will pushes.
  1. **`mkdir -p .git/_stale_locks && sleep 1` before EVERY `mv`** — Will deletes that folder when
     asked, and a missing destination makes `mv` fail with *"No such file or directory"*, which reads
     as though the lock is absent when it is present.
  2. `mv .git/index.lock …` then `mv .git/HEAD.lock …` — **unconditionally**, never guarded by
     `[ -f … ]`. **Locks surface one at a time**; budget two or three rounds.
  3. Commit with an explicit identity
     (`git -c user.name=spectraltoast1 -c user.email=88110329+spectraltoast1@users.noreply.github.com`).
     **Use `-m`, not a heredoc** — heredocs through this bridge have silently failed on `<…>` and
     em-dashes.
  4. Sweep `find .git -maxdepth 3 \( -name "*.lock" -o -name "tmp_obj_*" \)`, then `git fsck
     --no-dangling`. Verify by `git log --oneline -1`, never by absence of an error.
  5. Filter noise with `2>&1 | grep -v "unable to unlink"` — those warnings are git's own maintenance
     failing on the mount, not a blocked command.
  **Never `--amend` without checking `git rev-list --count origin/main..main`.**
- Device VM has **no network and no parquet engine**; repo venvs are macOS binaries → stage into the
  container and use polars there. `curl` to fly.dev/supabase.co is blocked from the container;
  **`WebFetch` works (GET only)** and `api.sleeper.app` is reachable.

---

## Standing instructions (carry into every brief)

1. **A suspiciously clean value is a bug until proven otherwise.**
2. **A refactor that changes a number is a bug** — prove equivalence. Say **value**-identical unless
   comparing bytes (polars' parquet writer is physically non-deterministic).
3. **Prove a new gate *bites*** — fail it on a broken input. **And §5: a prove-it-bites leg must never
   be able to aim a writer at the real store** — keyed on *shape*, not on which writers look safe.
   That rule cost the frozen corpus.
4. **§6 — the commit FLOOR: bank before running anything destructive.** The 3-commit cap bounds
   sprawl; nothing bounded the opposite failure.
5. **Report, don't tune.** Engine constants are propose-only / human-promoted.
6. **Honest, not hidden.** Gate a panel OFF only when a read is *misleading*, not merely uncertain.
   **Absence is reported, never fabricated.**
7. **The frozen corpus is immutable** — compute into a *different* path.
8. **"The artifact exists" and "the consumer uses it" are two different gates.**
9. **A proof that passes because it never exercises the new path is weak** — and **a run that skips
   every step because everything is "already current" is that proof.** Force the work.
10. **No silent caps.** If a session bounds its own coverage — takes the release valve, defers a
    check — it must SAY so. A report that quietly omits a deferred step reads as full coverage.
11. **Enforce security server-side.**
12. **Don't put enumerated lists in briefs — state the predicate and make Code enumerate.** Three
    briefs running, three undercounts, every one caught by Code.
