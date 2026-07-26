# Store-Migration Audit — Sessions 1–3

**Reviewed:** 2026-07-25 · **By:** PM (independent, against the live repo — not Code's report)
**Scope:** Sessions 1–3 of the Stage-A store migration (Fly/Supabase foundation → Postgres schema+loader →
Players/Teams read endpoints). Verdict: *does the work do what it claimed, and did Code cut corners or make
its own calls that block future work?*

**How this was verified:** I read the actual shipped code (`application/api/{main,routes,reads,calcs,db,settings}.py`,
`Dockerfile`, `fly.toml`, `application/data/serve/{build_db.py,schema.sql,MANIFEST.md}`) against the contract
(`frontend/src/{queries.js,db.js,posture.js}`), cross-checked every endpoint's shape and every ported
calculation line-by-line, re-read the key `queries.js` lines myself, and **inspected the real parquet** to
decide whether the one latent bug actually fires. I did not take the STATUS report at face value (I grepped
the live file) — which is how the headline finding surfaced.

---

## Bottom line

The engineering is **genuinely good** — and your "suspiciously easy" instinct is *half right*. The part that's
easy to see (the code) is solid and faithful; the endpoints reproduce today's app's numbers on the current
data. The corner that got cut is the part that's *invisible*: **the continuity docs were not updated**, so on
paper Session 3 looks like it never happened. That's the real risk, and it's a process gap, not a code gap.

Three things worth your attention, in order:

1. **The docs are stale — Session 3 is unrecorded.** Both `STATUS.md` and `TECHNICAL_ARCHITECTURE.md` still
   say "Session 3 is next." Code shipped the endpoints but skipped the closedown doc-update. This is exactly
   the failure the SESSION_GUIDE calls "the fastest way to lose continuity" — a fresh Session 4 would not know
   the endpoints exist. *(I've fixed the architecture doc as part of this pass; STATUS is Code's artifact —
   see recommendation.)*
2. **One real latent bug that will bite in Stage B, not now.** The Python treats missing/null numbers
   differently than the browser did: where the old app silently turned a blank into `0`, the new endpoint
   would **crash (HTTP 500)**. I checked the live data — the columns that could trigger it have **zero nulls
   today**, so the endpoints match the current app exactly. But Stage B loads ~10 leagues across historical &
   partial seasons, where nulls are far more likely. Cheap to fix now; nasty to debug later.
3. **A go-live landmine in the deploy config** (not a Session-3-scope failure): every endpoint filters on the
   league id, which on Fly comes from a secret the image doesn't ship. If that secret isn't set when the
   endpoints go live, they return **empty results, not an error**. I couldn't confirm the live state (the
   fetch needed an approval that didn't come through) — flagging it to check.

No finding rises to "the work is wrong." The scope delivered is the scope attempted. Details below.

---

## What Code got right (so this is balanced)

- **The endpoint shapes match the contract.** All 7 endpoints (`/api/weeks`, `/api/league-meta`,
  `/api/players`, `/api/players/{id}`, `/api/standings`, `/api/teams/{rosterId}`, `/api/managers/{rosterId}`)
  return the exact object shape their `queries.js` loader returns — field names, nesting, null sentinels,
  ordering. The Session-5 frontend swap will be drop-in.
- **The deferral is clean.** The team-detail `thisWeek` bar is returned as `null` with an explicit
  `# TODO(Session 4)` (`reads.py:625`), the whole rest of team-detail is intact, and the shape is stable.
  Exactly as decided — not half-built, not silently dropped.
- **The instructions were honored.** `MY_USERNAME` semantics (`isMe`/`onYours`/`myOwner`) are preserved and
  read from config/env (`settings.py`), *not* refactored to `viewer_roster_id` (that's Stage B). The
  `projection_consensus *_ppr` naming wart was left untouched. No frontend/`queries.js`/`db.js` edits — the
  seam held.
- **The hard SQL port is careful, not lucky.** DuckDB's `arg_max(col, week)` became a hand-written
  `(array_agg(col ORDER BY week DESC) FILTER (WHERE col IS NOT NULL))[1]` that correctly reproduces the
  "latest *non-null* value per column" behavior (a plain `DISTINCT ON` would have been subtly wrong, and Code
  documented why). `QUALIFY`→`DISTINCT ON`, `any_value`→`max` are faithful. It even added `NULLS LAST` to the
  Players sort — omitting it would have been a real bug, because Postgres defaults to nulls-*first* where
  DuckDB defaults to nulls-last.
- **JS rounding was ported correctly.** `Math.round` (half-up) is reimplemented as `floor(x+0.5)` rather than
  Python's banker's rounding — a genuinely easy thing to get wrong, gotten right.
- **The Stage-B seam is already wired.** Every query filters `WHERE league_id = settings.league_id()` — a
  no-op today, but it means Stage B parameterizes the league without touching the SQL. Queries are
  parameterized (injection-safe). Schema carries `league_id` + `season` on all 13 tables.

---

## Findings register

| # | Severity | Area | Finding |
|---|---|---|---|
| 1 | **High (process)** | Continuity | `STATUS.md` and `TECHNICAL_ARCHITECTURE.md` were not updated for Session 3. |
| 2 | **Med (latent)** | Correctness | Null numbers crash the endpoint (`float(None)`) where the old app coerced them to `0`. Does not fire on current data; a Stage-B risk. |
| 3 | **Med (latent)** | Deploy / go-live | Endpoints filter on a league id sourced from a Fly secret the image doesn't ship; if unset, endpoints return empty (not an error). Live state unconfirmed. |
| 4 | Low | Correctness (edge) | User "record" shows `0-0` where the old app showed blank, when the roster has no games in range. Edge-case only. |
| 5 | Low | Housekeeping | `--verify` checks row counts, not values; minor `season`/`week` type inconsistency (INTEGER vs BIGINT) across tables. |
| 6 | Low / none | Ordering | Python is *more* deterministic on ties than DuckDB (added tiebreaks). Cosmetic; not a defect. |

### 1 — The continuity docs are stale (High, process)

**Plain English:** the code shipped, but the two documents that are supposed to be the single source of truth
for "where are we" still describe Session 3 as not-yet-started. The whole model of this project is that a
fresh session reads the docs — not the chat — to know what's done. A Session-4 engineer reading `STATUS.md`
today would see *"NEXT — Session 3: port the first read endpoints"* and could redo finished work or build on
a wrong picture.

**Evidence:** `STATUS.md` line 3 still reads *"STORE MIGRATION TRACK — Session 2 SHIPPED"*, line 30 still
reads *"NEXT — Session 3."* I grepped the whole file: the only other "Session 3" mentions belong to the
unrelated engine-improvement track ("Improvement-Loop Session 3a/3b…"). No Session-3-shipped entry exists.
`TECHNICAL_ARCHITECTURE.md` line 267 still reads *"Session 3 … is next"* and lists none of the new files — and
its content was byte-identical across two reads taken before and after Session 3, so it wasn't touched.

**Why it matters / recommendation:** This is the corner that was actually cut. It's a five-minute fix and a
discipline reminder, not a rebuild. I've **already corrected `TECHNICAL_ARCHITECTURE.md`** in this pass
(marked Sessions 1–3 done, added the schema reference). I did **not** edit `STATUS.md` — it's Code's closedown
artifact and the project rule is one owner per doc — but I can hand you a drop-in Session-3 STATUS entry to
paste, or fold it into the Session-4 brief's "first, fix the STATUS you skipped." Either way, worth telling
Code the closedown doc-update is not optional.

### 2 — Null numbers crash where the old app coerced to zero (Med, latent)

**Plain English:** the browser was forgiving — a missing number became `0` and the page still rendered. The
new Python is strict — the same missing number makes the endpoint error out (HTTP 500). So for a league/week
where some value is blank, today's app shows something (possibly a misleading `0`); the new endpoint would
show nothing at all.

**Evidence:** the port uses bare `float(...)` on nullable columns — `reads.py:436` (`playoff_odds` series),
`:411`/`:540` (`roster_total_points`), `:283`/`:284`/`:591`/`:594` (`vor`, `market_vor` series). The browser
used `Number(...)`, and `Number(null) === 0` (`queries.js:319, 296, 492, 183…`). Same root: `load_standings`'
latest `playoffPct` is `0` in JS vs `None` in Python when the odds column is null (`reads.py:448` vs
`queries.js:331`).

**Does it fire today? No — I checked the real data.** In the live 2025 parquet, the columns that could trigger
it have **zero nulls**: `playoff_odds` (0/40), `roster_total_points` (0/594), `vor` (0/635), `market_vor`
(0/5643), `starter_value`, `avg_seed`, `magic_wins`, `remaining_games` — all clean. The two columns that *do*
have nulls (`trade_gap`: 264; `matchup_result`: 2) are already guarded on both sides. **So the endpoints match
today's app exactly.** The risk is Stage B: ~10 leagues across historical and partial/future seasons make a
null `playoff_odds` (a week odds weren't computed) or a null `roster_total_points` (an unplayed week) much
more likely — and then a standings endpoint 500s instead of rendering.

**Recommendation:** decide the null policy once, now, and apply it in `reads.py` (a small `_num()`-style
null-safe coercion). Two honest options: (a) *match the old app* — coerce null→0 (drop-in parity, but keeps
the old app's habit of showing a misleading `0`); or (b) *do it right* — pass nulls through as `null` and let
the frontend render "—". I'd lean (b) and note it as a deliberate, tracked divergence, since parity only has
to hold at Session 5 and "missing" is more honest than "0". Cheap now; a production incident later.

### 3 — Deploy landmine: league-scoping secret the image doesn't ship (Med, latent)

**Plain English:** every endpoint says "only give me rows for *this* league," and on the deployed server the
identity of "this league" comes from a setting the deployed image deliberately doesn't include. If that
setting isn't wired up as a Fly secret at go-live, the endpoints won't error — they'll just return **empty**,
which is the hardest kind of bug to notice.

**Evidence:** queries filter `WHERE league_id = settings.league_id()`; on Fly, `league_id()` reads env
`LEAGUE_ID` (and `my_username()` reads env `MY_USERNAME`) because the image ships only the `api` package, not
`config.py` — the `Dockerfile` itself documents this: *"MY_USERNAME and LEAGUE_ID must be set as env/secrets
on Fly … settings.py falls back to nothing there."* Only `DATABASE_URL` is confirmed as a Fly secret (from
Session 1). If `LEAGUE_ID` is unset, `WHERE league_id = NULL` matches no rows → every endpoint returns `[]`
and `/api/league-meta` returns a "0-tm" label.

**Live state: unconfirmed.** Session 3's scope was endpoint-level verification via local `curl` (against
`config.py`), so it may not have been redeployed at all. I tried to hit `https://fantasy-ai-api.fly.dev/` and
`/api/weeks` to check, but the fetch needed an approval that didn't come through — so I can't tell you whether
the endpoints are live, or whether the secrets are set. Not a Session-3 failure (parity is a local check); a
**go-live checklist item**.

**Recommendation:** before the Session-5/6 cutover, set `LEAGUE_ID` and `MY_USERNAME` as Fly secrets
alongside `DATABASE_URL`, and add "endpoints return real rows from the deployed URL" to the go-live checks. If
you approve a fetch to the Fly URL, I'll confirm the current state in a minute.

### 4 — "0-0" vs blank record (Low, edge)

`load_league_meta` builds the user's record with `count(*) FILTER (…)`, which returns `0` over an empty set;
the browser used `sum(result='W')::INT`, which returns `NULL` over an empty set and left the record blank
(`reads.py:119-125` vs `queries.js:696-699`). So a roster with **no** games in the selected window shows
`0-0` instead of nothing. Not reachable in the current UI (weeks 1–4 all have data; the app starts at
week ≥ 1), so no visible impact today — noted for completeness and because it's the same "empty→0" family as
finding 2.

### 5 — Housekeeping (Low)

`build_db.py --verify` asserts **row counts** match the source parquet and that there's a single `league_id`
per table, but it does **not** assert values match (STATUS's "numeric aggregate sums match parquet exactly"
was a manual check, not something `--verify` re-runs). Because the loader COPYs the exact parquet rows, count
parity is strong evidence — but if you want a regression guard for Stage B, add a value-level check.
Separately, the `season`/`week` columns are `INTEGER` in the natively-typed tables (`season`, `schedule`) and
`BIGINT` where added as a constant — Postgres cross-casts so joins work, but it's an inconsistency worth a
tidy-up before Stage B leans on `(league_id, season)` joins heavily.

### 6 — Ordering ties (Low / non-issue)

Where two rows tie (equal VOR, equal starter value), Python's results are actually **more** deterministic than
DuckDB's — Code added `sleeper_player_id` tiebreaks and explicit `ORDER BY`. The emitted order for exact ties
can differ from any given browser run, but the view re-sorts and nothing user-visible changes. Flagging only
so it's not mistaken for a regression later.

---

## Direct answer to "did Code make its own decisions that block future work?"

**No blocking decisions.** The two places Code exercised judgment both *help* Stage B: the null-safe `arg_max`
port and the already-wired `league_id` filter. Its scoping choices (defer `thisWeek`, keep `MY_USERNAME`,
leave `*_ppr`) match your locked decisions exactly. The one genuine "own decision" that diverges from the
contract — being strict about nulls instead of coercing to `0` — is finding 2, and it's a latent quality issue,
not a lock-in. Nothing here forecloses multi-league, auth, or the frontend swap.

The only thing that *would* have quietly blocked future work is the stale docs (finding 1) — a Session-4
engineer misled by `STATUS.md` — which is why it's ranked first even though the code is clean.

## Recommended before Session 4

1. **Fix `STATUS.md`** to record Session 3 shipped and set the next move to Session 4 (I'll draft it on request).
2. **Add the null policy** to the Session-4 brief (or a quick Session-3.5) — one null-safe coercion in
   `reads.py`, decided as parity-with-old-app vs pass-through-null.
3. **Add to the go-live checklist:** set `LEAGUE_ID` + `MY_USERNAME` as Fly secrets; verify the *deployed*
   endpoints return real rows.
4. Proceed to Session 4 (League + Matchups + the deferred `thisWeek` chain) — the foundation it builds on is sound.
