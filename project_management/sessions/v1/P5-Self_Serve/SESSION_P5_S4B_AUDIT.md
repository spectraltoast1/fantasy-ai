# P5 · S4b — PM audit of the job queue

**Audited:** 2026-08-14 · **Report:** `SESSION_P5_S4B_REPORT.md` · **Brief:**
`SESSION_P5_S4B_JOB_QUEUE.md` · **Range:** `af40a60..30e970b` (3 commits + merge) — diffed against
the **branch's base commit**, not main's working tree.
**Verdict: ENDORSED, and S4b is CLOSEABLE.** All five DoD clauses met on the live worker, the release
valve not taken, and **two latent defects found and fixed that would each have produced a permanently
broken league.**
**One new finding of my own: two individually-correct guards have composed into an operation with no
home. Not a blocker — S4c needs to know before it flips a panel flag.**

---

## THE FINDING — `reload_manifest()` now refuses on BOTH machines

The S4a guard refuses it on the **worker** (`store_role() == "worker"`, function line 13). The S4b
guard refuses it on the **laptop** (`assert_catalog_covers_postgres`, function line 27 — the real
33-vs-32 drift). **Both refusals are individually correct. Together they leave the catalog-only
refresh with nowhere to run.**

Verified by reading both guards in the same function body rather than inferring from either.

**Why it matters, and it lands on S4c.** `reload_manifest`'s own docstring says it exists for the case
where *"only panel-flag values differ"* — which is **exactly** what S4c does when it flips
`panels_manager` after the dossier job. The alternatives:

- **`upsert_catalog_row(conn, lid)`** — per-league, worker-safe, transactional. **This is the answer**
  for S4c, and it is already built. The per-league case is the case that actually arises.
- A full `--load` on the worker — correct but an outage for a panel flag.

**The elegant fix, if S4c or S4d wants it: `assert_catalog_covers_postgres` SUBSUMES the role guard.**
The role check was a *proxy* for "your catalog might be stale"; the set comparison **measures** it, and
measures it in both directions — a worker whose seed predates a laptop-authored demo change fails
`pg_ids - local` just as the laptop does today. Retiring the role guard in favour of the measured one
would restore `reload_manifest` on the worker without weakening anything. **Do not do this
speculatively** — do it when something needs it, and prove the worker half bites.

---

## Verified independently — recomputed, not read

| claim | verified |
|---|---|
| signed-out live prod is **exactly the demo** | ✅ `surplusff.com` → one league, `DEMO-2025`. `/health` on the **second hostname** still `season 2026, derived` — no `CURRENT_SEASON` override crept in, and two hostnames means this is not a cached read path |
| the guard compares **sets**, not counts | ✅ `build_db:569-570` — `pg_ids - local` on `league_id` sets. The *"`--verify` compares counts, never sets"* claim is the load-bearing one and it is correct |
| the guard runs **before** the destructive statement | ✅ `assert_catalog_covers_postgres(conn)` precedes the `TRUNCATE` in `reload_manifest` and precedes `_run_sql_script` (the DROPs) in `load()`. Checked the call, not the comment — which is the mistake the report says it made twice and then fixed |
| `_ORPHANS_SQL` nullable-FK bug | ✅ real, and the fix is right: `AND t.{column} IS NOT NULL`. Without it **every hand-enqueued job — i.e. every job in S4b — fails `--verify` on correct data.** The two prior entries were safe only because `user_leagues.user_id` is `NOT NULL` and `app_users.id` is a PK |
| the brief's `_TABLES` claim was **half wrong** | ✅ `_TABLES` drives the column dump only; `_verify_cascades` iterates `_CASCADE_FKS`. `jobs` is in **both** (`:26`, `:65`). **My brief said adding to `_TABLES` inherits the cascade assertion. It does not.** Code caught it |
| `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` | ✅ and the client-held-vs-internal rule is written into the file, not just the report |
| the lease's parentheses | ✅ the disjunction is bracketed and the comment states the failure mode (`AND` binds tighter, so the cap would apply only to the reclaim branch) |
| `SystemExit` handled **before** `except Exception` | ✅ `worker_loop:160` precedes `:170`. Genuinely load-bearing: `onboard_league` signals all five refusals with `SystemExit`, which is a `BaseException` |
| `STORE_ROLE` missing → **idles, does not exit** | ✅ and the reasoning is the right one: *"you cannot `fly ssh` into a crash-looping machine to fix the config that caused it. This box has no other door."* |
| LISTEN + 60s wake, served in **5s slices** | ✅ `_WAIT_SLICE_SECONDS = 5`, `IDLE_WAKE_SECONDS = 60`; the slicing exists because SIGTERM does not interrupt a single 60s `notifies()` |
| the transaction-pooler foreclosure is **recorded where it would be lost** | ✅ `api/.env.example:8-9` **and** `config.example.py:18-19`. This is the right instinct: it would not error, the worker would simply, silently, stop being woken |
| damage check | ✅ `git status` under `snapshots/` **clean** |

**Not verifiable from the PM seat, and it is Will's check — third session running.** *"Worker
redeployed and proven live"*, the Fly init line, `fly status`, and every Postgres row count. The worker
has no HTTP surface by design, so nobody outside the session can confirm any of it.

## What this session did unusually well

**It found two latent defects that the queue converted from annoyances into permanent breakage, and
neither was in the brief.**

- **A · A crashed cold run was permanently un-onboardable.** The catalog row is written *after* the
  chain, so a crash in those ~10s left directories and no row; `classify()` then called the league
  warm and refused **by every route, for ever**. Under the queue that refusal is a `rejected` job,
  which is **terminal by design** — so *the first crash on a real user's league would have been the
  last time it could ever be connected.* The fix separates **recorded** warmth (somebody decided this
  league belongs elsewhere) from **on-disk** warmth (the wreckage of a run, which decided nothing).
- **B · A truncated fetch read as complete.** `harvest._raw_present` is true on config + teams +
  **week one**, so a run that died at week 6 of 14 would have gone on to a spine, a schedule, a
  catalog row, a Postgres load and `state='ready'` **on a truncated season.** That is the P5 risk
  register's exact words — *"never a half-built league that looks complete"* — and nothing compared
  joined weeks to the target. The fix reuses `_determine_completed_weeks`, **the same function
  `backfill` uses**, so the two cannot drift.

**Both are the direct product of the instruction to verify the idempotency claim rather than inherit
it.** My brief asserted idempotency was "already paid for" because a re-onboard is a proven no-op.
**That is true of a completed run and false of an interrupted one, and the queue is what makes
interrupted runs routine.** The brief was wrong; checking it is what found the bugs.

**It caught its own instrument twice, unprompted.** The first kill drill *killed nothing and reported
success* — `pkill` does not exist on `python:3.13-slim` (no procps), so the command failed silently and
the job completed normally. The drill now walks `/proc` and **aborts unless it can name the pids it
killed.** And two gate assertions matched *prose describing* a statement (a comment saying
`# BEFORE the TRUNCATE`, then `reload_manifest`'s own error string) rather than the statement — both
reported correctly-placed code as broken. **That is the fourth and fifth instance of this project's
signature failure being caught inside the session that could have shipped it.**

**The `LIKE` detail is small and exactly right.** Throwaway rows are swept on **exact** ids, never
`LIKE`, because `_` is a LIKE wildcard and `__QUEUECHECK%` would match real league ids. That is
CODING_BIBLE §5 applied to a row instead of a file — S4a finding D's shape, generalised.

**It corrected the brief three times and said so each time:** the `_TABLES` cascade claim, the
`_CASCADE_FKS` omission, and the 80s dossier fan-out — which is **not** on this path
(`run_chain`'s `dossiers` defaults to `False` and `onboard()` never passes it), so my lease-timeout
reasoning was sized against a stage a queued job cannot reach.

## Code's open issue — assessed, and it gets an owner

**`init_auth_schema.py:117-121` swallows an orphan-count failure and `continue`s without setting
`ok = False`.** Confirmed by reading it. The cascade *constraint* is still asserted above and does set
`ok = False`; it is only the **count of what the constraint prevents** that goes unreported.

**Code's call to report rather than fix was right** — it is not this session's subject, and it prints
`??` rather than claiming success, so it does not lie to a reader. **But the exit code is green while
an assertion produced nothing, which is this project's most-repeated failure class**, and "not lying
to a human reading the output" is a weaker property than "not passing."

**Owner: S4c.** It adds `scripts/users.py --delete` — account lifecycle is *precisely* what the
cascade and the orphan count exist to protect — and it writes `user_leagues` from a sign-in. The right
shape is a third state (**unknown ≠ pass**), not a louder failure: an unavailable count genuinely is
not a failure, it just must not be counted as a success.

## My errors in the brief, for the record

1. **The `_TABLES` claim was half false** — adding a name there inherits the column dump, **not** the
   cascade assertion. I stated it as fact; Code checked it.
2. **I sized the lease against the 80s dossier fan-out**, which a queued job cannot reach.
3. **"Idempotency is already paid for"** — true of completed runs, false of interrupted ones. I told
   Code to verify it rather than inherit it, which is the only reason that error cost nothing.

## Verdict

**Endorsed. S4b closes.** The worker leases, runs, fails, is killed, restarts by itself and finishes
the job — measured at **130s** reclaim, which is `LEASE_SECONDS` plus a wake, *"a number rather than a
hope."* The guard closes the hazard S4a opened, and closes it by a **new comparison** rather than a
louder version of an existing one. The empty-queue answer is `LISTEN` with a real number behind it
(**~2,880 statements/day**, one held connection), and the connection cost is **recorded rather than
solved**, which is the honest half.

**Carried into S4c:** the homeless `reload_manifest` (use `upsert_catalog_row`), the
`init_auth_schema` unknown-vs-pass state, and S4a finding F's null-seat collision. **None reopens
S4b.**
