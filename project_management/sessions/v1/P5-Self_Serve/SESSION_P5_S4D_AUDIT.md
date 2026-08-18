# P5 · S4d — PM audit of the weekly cadence

**Audited:** 2026-08-17 · **Report:** `SESSION_P5_S4D_REPORT.md` · **Brief:**
`SESSION_P5_S4D_WEEKLY_CADENCE.md` · **Range:** `2c2bd9c..4eba45f` (3 commits + merge), diffed against
the branch's base.
**Verdict: ENDORSED, and S4d is CLOSEABLE.** Both defects from Will's live test are fixed and shown
before/after on the same league in production. The valve was taken and **declared**, which is correct.
**Two findings of my own, one of which fires tomorrow.**

---

## FINDING 1 — the workflow file itself has never run, and the cron fires Tue 18 Aug

The report proves the **enqueue module** end to end (`enumerate → INSERT+NOTIFY → leased 0.09s later →
the executor ran`) and proves the **worker image** shipped (the same job kind returned *"unknown job
kind 'refresh'"* before the deploy). **Neither is the GitHub Action.**

`weekly_refresh.yml` changed substantially in this session: a different dependency install
(`api/requirements.txt`), a different entrypoint (`python -m application.api.enqueue_refresh`), and
`STORE_ROLE` removed. **A YAML error, a missing import under the api-tier venv, or a secret this
workflow no longer requests would surface only at fire time.**

**It fires tomorrow — Tue 18 Aug, 15:00 UTC (11:00 ET)** — for the first time, unattended, and with
**zero connected 2026 leagues** it should enumerate nothing and exit cleanly. That is the ideal
rehearsal: the blast radius is zero and the signal is real.

**Nobody is watching it.** Will should look at the Actions run tomorrow, and a green run is the
missing half of DoD clause 5. **This is a check, not a defect** — but the difference between "the
module works" and "the workflow works" is exactly the difference S2e's merged-but-not-deployed
release cost this project once already.

## FINDING 2 — the refresh executor's SUCCESS path has never run

`_execute_refresh` calls `refresh_league(..., live=True)`, and the live path derives season and week
from Sleeper's state. **I confirmed the state independently: `season_type: "pre"`, `leg: 0`.** So the
executor has only ever reached a terminal refusal, never a completed advance.

**Its first successful run will be in production, unattended, on a real user's league, at Week 1** —
the same moment the cohort arrives and the same moment several other things happen for the first time.

**A rehearsal is available and cheap.** Rex Lumber 2025 is connected, has real weeks, and
`refresh_league` supports a replay (`target_week`) — but **the queue can only reach the live path**,
because the executor hardcodes `live=True` and no job column carries a target week. So either the job
learns a replay parameter, or somebody runs one refresh by hand on the worker against that league
before 10 Sept.

**I would do the hand-run.** It costs one command, changes no code, and converts "the executor's
success path is unproven" into "it worked once." → **S4f or a Will-check; not a reason to reopen S4d.**

## The two brief-DoD clauses that are only half met — honestly reported

- **Clause 6, the legible no-op.** The *enumeration* half is proven (a league with an active job lands
  in `skipped=[]`, not an error, exercised in an uncommitted transaction the live worker could never
  see). The *refresh* half is not, and the report says why plainly: **`jobs` cannot distinguish
  "advanced" from "was already current" — both are a clean `ready`.** That was the harder half of what
  I asked for. It lands with the first real advance; the report's suggested nullable `result` column is
  the right shape.
- **Clause 1, linking at Week 1.** Proven by **replay of the week arithmetic**, not by a live link —
  and it could not be otherwise today. Correctly labelled as such rather than dressed up.

---

## Verified independently — recomputed, not read

| claim | verified |
|---|---|
| **the allow-list is a deny-list** | ✅ **recounted myself**: `data_layer` has **50** `write_*` defs and **15** `_require_laptop(` call sites (the 16th guard is `write_ros_player_band`'s bespoke verify-instead-of-refuse from S3). So ~34 writers carry no guard, and *"anything unclassified refuses by default"* — in `data_layer`'s header, `ARCHITECTURE.md` **and** the ADR — was wrong in all three |
| the preseason state underpinning everything | ✅ fetched Sleeper directly: **`season_type: "pre"`, `leg: 0`, season 2026**. `completed = 0` and `current = 0` today, exactly as the report's boundary table claims |
| signed-out prod is **exactly the demo** | ✅ one league, `DEMO-2025`, on `fantasy-ai-api.fly.dev` |
| the workflow is gutted | ✅ installs `application/api/requirements.txt`, runs `python -m application.api.enqueue_refresh`, **no `STORE_ROLE`**, no pipeline step |
| `MY_USERNAME` / `LEAGUE_ID` **retired, not relocated** | ✅ gone from `weekly_refresh.yml` **and** `fly.worker.toml` (which keeps `STORE_ROLE` and comments the removal) |
| `collectors.yml` — my open question | ✅ **answered and closed**: it set no `STORE_ROLE`; now it does. The ADR's claim counted *machines* while enforcement is per-*workflow* — a real gap in the reasoning, no live hole |
| one predicate, two callers | ✅ `platforms.league_has_started` (`api/platforms.py:85`), imported **advisory** by `classify` and **authoritative** by `onboard_league.assert_in_scope`. Exactly the shape, in the image that both sides can reach |
| the enqueue seam was not re-split | ✅ `application/api/enqueue_refresh.py` calls the existing producer; the `INSERT … SELECT` was dropped |

**Not verifiable from the PM seat:** the `jobs` row states, the 0.09s lease, and every Postgres count.
Unchanged from every prior session.

## What this session did unusually well

**It dropped my `INSERT … SELECT` for the reason I gave and then found a better one.** I said a raw
INSERT forgets the NOTIFY and duplicates the season derivation. The report adds the deciding one:
`check_connect`'s ONE SEAM leg scans `application/**/*.py`, **so SQL in YAML is invisible to it** — the
second producer would have arrived through the one door the gate cannot see, **and the gate would have
stayed green.**

**It caught a bug in the cadence that would only have appeared in production, weekly.**
`sleeper.refresh()` writes five `CACHE_DIR` blobs that are **not league-keyed**, so pointing it at a
stranger's league overwrites the owner's cache. Nothing reads them today, which is why it had never
bitten — but S4d puts `weekly_refresh` on the queue for *every* connected league, so it would have
done that in turn, every Tuesday, at five wasted Sleeper GETs each.

**The spine finding is better than the fix I asked for.** Three of the five reads already carry
well-worded named diagnoses for a zero-results league — **and all three are unreachable**, because each
one's own unguarded `read_join_season` raises first. So the answer is *one refusal in the chain that
knows why*, not five guards in transforms that only know a file is missing. It also answered the
question I asked honestly: `player_signal` cannot produce on zero results, `bracket_odds` would
simulate a 0-0 slate, **and the existing thin-data window already covers the Week-1 case** — no new
claim on thin data.

**It found its own executor defect before shipping:** `refresh_league(..., live=True)` overwrites
season *and* week from Sleeper, so it ignored the job's own `season` — a job enqueued across a season
rollover would have run the new season under the old season's league id.

**Three enumeration details, all confirmed against production rather than reasoned:** `DISTINCT` is
load-bearing because **Rex Lumber has three owners** and the raw join returns three rows for one
league; `season` comes from the catalog because `user_leagues` deliberately has none; and `NOT EXISTS`
rather than `ON CONFLICT` because `jobs_active_league_idx` does not include `kind`, so a refresh
collides with an in-flight **onboard** too.

## Carried forward — none of it reopens S4d

- **The workflow's first real fire (Finding 1) — Tue 18 Aug.**
- **The refresh executor's success path (Finding 2)** — a hand-run against Rex Lumber 2025 before
  10 Sept.
- **The valve was taken:** `check_ownership` / `check_isolation` still hardcode the retired demo id,
  and the report shows it is bigger than two constants — `DEMO` is threaded through *every* call of the
  function under test, so ~49 of 59 and ~70 of 89 assertion sites depend on it. **→ S4f**, as directed.
- **The store-boundary gate leg** that would make default-deny true (enumerate `data_layer`'s writers,
  fail on any unclassified). Recorded, not built, and correctly outside S4d's mandate. **It needs an
  owner — I would give it to P6**: it is cheap, and it guards the *class* of failure the corpus
  overwrite came from, which is "a writer nobody classified."
- **`jobs` cannot distinguish "advanced" from "already current"** — a nullable `result` column.
- **`sleeper.refresh()` now has no caller in the cadence**; its five non-league-keyed blobs are written
  by nothing else and read by nothing at all. A deletion candidate for a session that owns that file.

## Verdict

**Endorsed. S4d closes.** The league that produced a raw `FileNotFoundError` with an internal path in
Will's browser now returns *"the draft hasn't happened yet…"* at attempt 1 — the same league, the same
route, on production. The workflow stopped being a pipeline machine, `MY_USERNAME`/`LEAGUE_ID` are
retired rather than relocated, and the boundary claim that had been wrong in three documents since S3
is corrected.

**The honest limit is the report's own headline and it is the right one to lead with: no 2026 league is
linkable today, so the week-advance is proven as plumbing and not as behaviour.** That is the strongest
argument for S4f that anyone has made — the product's current answer to Will's own league is *"come
back later."*
