# P5 · S2a — PM audit of the ownership + scoped-catalog session

**Audited:** 2026-08-09 · **Report:** `SESSION_P5_S2A_REPORT.md` · **Brief:**
`SESSION_P5_S2_OWNERSHIP_AND_ISOLATION.md` + its 2026-08-09 amendment ·
**Range:** `9f226c6..8a6526d` (3 commits + merge) · **Verdict: ENDORSED — merge stands, deploy stands.**

**No isolation defect found.** The security property S2a claims — the catalog answers per caller, the two
accounts separate, the season term bites, an unresolved season narrows — holds when re-derived
independently rather than read. Seven findings below; none blocks. **F1 and F3 belong in S2b's brief**,
F2 is a ten-minute hardening.

## What I verified independently (not from the report)

1. **The live signed-out catalog.** `GET https://surplusff.com/api/leagues`, fetched directly:
   exactly **one** league — LoRP 2025 (`1182101676608823296`), `weeks_available [1..5]`. **LoRP 2024
   shares that lineage and is correctly absent**, which is the season term biting in production on a row
   the fixtures do not contain. DoD 5 and the deployed state confirmed without trusting the transcript.
2. **The predicate, re-run against MY fixtures, not Code's** — `reads.build_catalog` imported directly
   with stubbed deps, driven with a row set that adds LoRP 2024 (the demo's own lineage), int-typed ids,
   string seasons, and a grant for a league absent from the manifest:

   | case | result |
   |---|---|
   | signed out, `current=2026` (reality) | demo only ✅ |
   | A owns Trap 2025 + Trap 2024, `current=2026` | demo only ✅ |
   | A owns Trap 2025 + Trap 2024, `current=2025` | `[Trap25, demo]` — **owned first** ✅ |
   | owner of the demo league itself | demo once, not duplicated ✅ |
   | `current_season=None` (Sleeper down, no cache) | demo only — **fails closed** ✅ |
   | `demo_league_id=None`, owns nothing | empty **and the loud ERROR log fires** ✅ |
   | grant of a league absent from `demo_manifest` | invisible, no crash ✅ |

   Lineage order with A owning Trap: `['trap', 'lorp']` — the SPA lands on `leagues[0]`, so this is the
   mechanism behind "your league, not the demo," and it is real rather than inherited from the old
   `is_mine` sort (the fixture sets `is_mine` on the demo lineage precisely to prevent that).
3. **DoD 6, which the report never demonstrates, is correct anyway** — read the SQL: `--grant` is
   `ON CONFLICT (user_id, league_id) DO NOTHING` and reports "already owned"; `--revoke` of nothing prints
   "nothing to revoke". Better than asked: a grant for a league not in `demo_manifest` **warns explicitly**
   that it cannot surface until S4 catalogues it, rather than blocking or silently doing nothing.
4. **DoD 1** — FK `REFERENCES auth.users(id) ON DELETE CASCADE` present in `auth_schema.sql`; both new
   tables in `init_auth_schema._TABLES`, inheriting the absent-from-generated-DDL assertion. `fly.toml`
   `[env]` carries `DEMO_LEAGUE_ID` and **no `CURRENT_SEASON`**.
5. **Amendment #4 was handled honestly.** Code proved the signed-out default follows config rather than
   `MY_USERNAME` by repointing `DEMO_LEAGUE_ID` at Trap 2025 and reading three endpoints — the claim that
   would have been true and worthless is instead the claim that was tested.
6. **`check_override_is_process_env_only` is structural, not textual** — it inspects signatures rather
   than grepping prose, and the docstring records that the textual version tripped over `nfl_state`'s own
   comments. That is the "grep finds the name, not the concept" lesson applied without being told.

## Findings

### F1 — `/api/leagues` can now 401/503, and the SPA still has no fallback (medium; S2b)

S2a put `Depends(auth.optional_user)` on the **one route the SPA cannot survive failing**. The route's own
docstring names the requirement — *"it must never 401 (`loadLeagues()` only console.errors, leaving a
permanent 'Loading…')"* — and then guarantees only the second of the two properties it lists. `App.jsx`'s
handler is unchanged: `.catch((e) => console.error(...))`, and `slice` stays `null` forever.

Reachable by: an expired or revoked refresh token, a **deleted account** (two were deleted today), clock
skew, or a Supabase JWKS outage. Anonymous visitors are fine by design — so the failure mode is *the app is
dead for signed-in users only*, which is also the hardest version to notice. Before S2a this route took no
auth dependency and could not fail this way.

**Fix (small, S2b):** on 401/503 from `loadLeagues`, drop the token and retry **once** anonymously — the
visitor gets the demo instead of a dead app — and give the surfaces a real error state instead of an
infinite "Loading…". This weakens nothing: anonymous is strictly less than signed-in, and the API still
refuses the bad token, which is the property `optional_user` was written for.

### F2 — DoD 7 (cascade) is asserted, never measured, and nothing verifies the constraint took (low-med)

The report's only mention is in *For S2b*: "the two disposable accounts were deleted at the end, which is
how the `ON DELETE CASCADE` was demonstrated." **No orphan count.** Deleting a user and not then counting
`user_leagues` rows demonstrates nothing — and it cannot be re-derived now, because the accounts are gone.

Compounding it: `init_auth_schema.verify()` checks column names, types and nullability plus absence from
the generated DDL — **not constraints**. With `CREATE TABLE IF NOT EXISTS`, a table that already existed in
another shape keeps its old constraints and nothing notices.

**Fix:** two queries in `verify()` — assert the FK on `user_leagues.user_id` exists with `confdeltype='c'`,
and count orphans (`LEFT JOIN auth.users … WHERE u.id IS NULL`). Converts a claim into a standing gate.

### F3 — the demo gets swallowed by Will's own lineage at Gate A (medium; sequencing, S2b input)

`build_catalog` groups by `lineage_id`. The demo **is** LoRP 2025, and Will's league **is** the LoRP
lineage. When his 2026 league is onboarded and granted (~2 weeks), the catalog returns **one** lineage
entry with seasons `[2026, 2025]` — his league and the demo fused into a single switcher entry.
Reproduced: owning LoRP 2024 with `current=2024` yields `['demo/LoRP25', 'LoRP24']`, one lineage, two
seasons.

Then **S2b removes the season selector** — at which point the demo becomes unreachable from Will's account
entirely. The settled model promises "signed in with a league → their own league first, **demo still
switchable**"; for the one account that most needs to show people the demo, it will not be.

It dissolves when the demo clone lands (that brief already gives the clone its own id). **So this is a
sequencing decision with a date on it:** land the clone before S2b removes the selector, or make the demo
its own catalog entry regardless of lineage. Not a defect in S2a.

### F4 — `visible()` stringifies the row's id but not the `owned` set (low; a trap laid for S2b)

`if str(league_id) not in owned` — pass `owned` as ints and every membership test silently fails. No live
path does this (`owned_league_ids` builds strings), so it is not a bug today. It matters because **S2b's
stated first move is to lift this exact function into `slice_params`** and call it from new sites. One
line — `owned = {str(x) for x in owned}` — and it stays fail-closed either way (a user mysteriously loses
their league; nobody gains one).

### F5 — the anonymous-vs-bad-token check passes on 401 **or** 503 (low)

`check_anonymous_is_not_denied` accepts either. On a machine with no Supabase config a garbage token
yields 503 and the check goes green **having never verified a token**. A refusal alone proves nothing.
Record which code came back, and have `--live` require 401 specifically.

### F6 — a >12h Sleeper outage adds 5s to every catalog request (low)

`resolve()` runs per request. Once the cached value passes `_TTL_S` (12h), every request attempts Sleeper
and pays the 5s timeout before falling back to the stale value. Bounded and rare, but S0 was a latency
session. A short negative-cache/backoff on failure closes it.

### F7 — "the override is gone" is not observable from outside (low)

The final state rests on `fly.toml` (verified) plus a startup log line read at one moment. Under
`CURRENT_SEASON=2025` a signed-out caller still sees demo-only, so the difference is **invisible without an
account** — there is no runtime assertion and no way for a later session to re-check cheaply. Expose the
resolved season + source on the existing unauthenticated health endpoint: Sleeper publishes the season
anyway so it leaks nothing, and it turns a log line into a property anyone can check at any time.

## Carried into S2b

- **F1** (catalog failure fallback) and **F3** (demo/lineage fusion before the selector is removed) go in
  the brief. F3 needs a decision, not just a task.
- **F4** before `visible` moves into `slice_params`; **F2**, **F5**, **F7** are cheap and can ride along.
- Unchanged from the report: `slice_exists` still doubles as the authorization boundary; the eleven
  per-panel reads are still open; the unowned-league 404 and `viewer_roster_id` validation are S2b's.
- S2b must mint its own accounts — S2a deleted both.
