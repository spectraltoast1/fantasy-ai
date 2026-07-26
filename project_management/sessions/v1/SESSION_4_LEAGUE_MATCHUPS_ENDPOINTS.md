# Session 4 — League + Matchups API Endpoints (+ the deferred team-detail `thisWeek`) — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code (Will operates + eyeballs)

> **What this session does:** port the **League** and **Matchups** screens' data reads out of the browser
> into FastAPI/Postgres endpoints, **and** complete the team-detail `thisWeek` projection bar that Session 3
> deferred. The heart of it is one shared **projection/win-probability engine** (optimal lineup → μ/σ →
> analytic win prob) that three surfaces all use — the Matchups slate, matchup detail, and the team-detail
> `thisWeek` bar. Build it **once**. Stage A of `MULTI_LEAGUE_STORE_MIGRATION.md` (A3→A4); single league, no
> auth, no new formats. The frontend is still **not** wired to any of this (that's Session 5).
>
> **The contract:** each endpoint returns the **same shape** its matching `queries.js` loader returns today
> (field names, nulls, ordering). `queries.js` is the source of truth. After this session, every read the
> frontend needs exists server-side — Session 5 can flip `queries.js` to `fetch()` in one pass.

## Your part, Will (~10 minutes)
Kick off with the brief below. At the end, glance at Code's endpoint check — it should show a matchup's JSON
(both teams' projected totals + win %) and the League standings matching today's app for the same week.
That's your "looks right." This is the heaviest session so far — if Code says it's splitting off the League
tab to stay under the 3-commit cap (see the note in the brief), that's expected and fine.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Match the `queries.js` loader shapes exactly** (field names, nulls, ordering). The loader is the contract.
2. **Build the shared win-prob engine ONCE**, in a new module (e.g. `application/api/projections.py`):
   `expand_slots`, `optimal_lineup`, `team_projections`, `matchup_win_probs`, `normal_cdf`. The Matchups
   slate, matchup detail, and the team-detail `thisWeek` bar **all** call `team_projections` — do not inline
   it three times. This mirrors how `queries.js` shares `teamProjections`/`teamMatchupSummary`.
3. **Reuse Session-3's helpers — do not re-derive:** `reads._latest(col)` (the `arg_max(col, week)` port =
   roster-as-of-N — it **must** be the same definition team-detail already uses, so the surfaces agree),
   `reads._sql_standings_weeks(n)` (the team-week scores, for records), and `calcs.js_round`/`calcs.round1`
   (JS half-up rounding). `/api/league` should **call the existing `reads.load_standings(as_of_week)`** and
   assemble around it — the standings math is already ported and verified; don't rewrite it.
4. **`normal_cdf` → Python's `math.erf`.** The browser uses an Abramowitz–Stegun `erf` approximation
   (`queries.js` l.1027, `|ε| < 1.5e-7`); `math.erf` is exact and within that tolerance, and the win % is
   **rounded to an integer percent** (`Math.round(p*100)`), so the rounded result is identical. *If* any win %
   comes out different from the app, fall back to porting the A&S `erf` verbatim (it's 6 lines) — but `math.erf`
   should match.
5. **Null-safe guardrail (audit item 1) — applies to the NEW projection reads.** `projection_consensus`'s
   `center_ppr`/`band_ppr`/`p25_ppr`/`p50_ppr`/`p75_ppr` can be null. The JS already handles this — a rostered
   player with **no** projection row that week contributes `pts=0, band=0` and won't start (`queries.js`
   l.809-814), and the Score Range falls back to the μ term (`p25 ?? pts`, l.963-965). Reproduce those
   fallbacks with a **null-safe coercion** (a small `_num(x, default)` helper), **not** bare `float()` — which
   would 500. Establish that helper here; it's the pattern the whole read layer should adopt. *(The broader
   null-policy* decision *— show `0` vs render "—" — is Session 5's call; here you only need to not crash and
   to match the JS fallbacks.)*
6. **Determinism in the optimal lineup.** `optimal_lineup` breaks projected-points ties by **first-seen**
   player (JS uses strict `p.pts > best.pts`, so the first max wins). Iterate the roster in the **same order**
   the roster query returns — add `ORDER BY sleeper_player_id` to the roster read (matching team-detail) and
   keep the strict `>` — so the same player fills the slot the app picks. Each player keeps a stable index so
   "used across slots" tracks correctly.
7. **`targetWeek = N + 1`.** The app is a season replay: viewing as-of week N shows the **upcoming** week N+1
   fully projected. `target_week_for(n)`: null → `max(week)+1`. Leave the `projection_consensus *_ppr` column
   names alone (Stage-B rename).

## Endpoints to build this session

| Endpoint | Ports (`queries.js`) | Notes |
|---|---|---|
| `GET /api/league?as_of_week=N` | `loadLeague` (l.370) | **Light** — calls `load_standings(N)` + one `league_settings` read (`playoff_teams`, `num_teams`). Returns `{standings, me, playoffCut, nTeams}`. |
| `GET /api/positional-talent` | `loadPositionalTalent` (l.396) | Market-VOR per team×position (sum of positive `market_vor` at the latest snapshot), ranked. **Not** week-scoped. `{byPos, isCrossTime}`. |
| `GET /api/matchups?as_of_week=N` | `loadMatchups` (l.878) | The week-N+1 slate: each game's two teams w/ record, projected μ, win %. `{targetWeek, games, myGameId, empty}`. |
| `GET /api/matchups/{matchupId}?as_of_week=N` | `loadMatchupDetail` (l.942) | One game's full breakdown: win prob, Score Range (Σ starters' p25/p50/p75), per-starter gauges, starters+bench. `{matchupId, targetWeek, teams}` or `null`. |
| `PATCH /api/teams/{rosterId}` — add `thisWeek` | `teamMatchupSummary` (l.846) | **Replace the `"thisWeek": None` stub** in `reads.load_team_detail` with the real summary: opponent + both projected totals + win %. `null` when no next game. |

## The shared engine to port (read `queries.js` l.760–1036 for exact logic)

- **`expand_slots(slot_rows)`** (l.994) — one entry per physical starting slot (a FLEX `count` of 2 → two
  slots), each with its `eligible` position list; **sort most-constrained first** (`len(eligible)` ascending)
  so dedicated slots claim their stars before FLEX draws from the pool.
- **`optimal_lineup(players, slots)`** (l.1007) — greedy: for each slot in order, pick the highest-`pts`
  eligible **unused** player (strict `>`, first-seen wins ties). Returns the picks (each tagged with its
  filled `slot`) + total. This is the port of `transforms/_analytics.py` `expand_slots`/`optimal_lineup`.
- **`team_projections(as_of_week, target_week)`** (l.765) — the core. Roster-as-of-N (`_latest` arg_max, same
  as team detail) × `projection_consensus WHERE week = target_week`. Per team: attach each rostered skill
  player's `center_ppr` (→ `pts`, the μ term), `band_ppr` (→ the σ term), `p25/p50/p75`; run `optimal_lineup`;
  then **μ = Σ starters' `pts`, rounded via `round1`**, and **σ = √(Σ starters' `band²`), raw (not rounded)**.
  Returns `rosterId → {rosterId, name, owner, isMe, mu, sigma, starters, bench}` (bench = non-starters sorted
  by `pts` desc). **Watch:** `mu` is `round1`'d at the team level and that **rounded** μ is what the win-prob
  math consumes — round first, then compute win prob.
- **`matchup_win_probs(muA, sigA, muB, sigB)`** (l.837) — `[pa, 1-pa]`; `pa = normal_cdf((muA-muB)/√(σA²+σB²))`;
  `0.5` if both σ are 0. **`normal_cdf(z) = 0.5*(1 + erf(z/√2))`** (decision 4: use `math.erf`).
- Records for the slate come from **`reads._sql_standings_weeks(N)`** → a small `records_by_roster(rows)`
  (count W/L per roster over weeks ≤ N — same pass `load_standings` already does).

## Per-endpoint assembly (the shapes to reproduce)

- **`/api/league`:** `{ standings: load_standings(N), me: the isMe row or null, playoffCut:
  round(playoff_teams) or null, nTeams: round(num_teams) or standings length }`.
- **`/api/positional-talent`:** `WITH latest AS (SELECT roster_id, position, sum(greatest(market_vor,0)) AS
  pos_vor, bool_or(is_cross_time) AS is_cross_time FROM market_vor WHERE snapshot_date = (SELECT
  max(snapshot_date) …) AND position IN ('QB','RB','WR','TE') GROUP BY roster_id, position)` LEFT JOIN teams →
  `{ byPos: {QB:[{rosterId,name,isMe,vor,rank}], RB:[…], WR:[…], TE:[…]}, isCrossTime }`, each position sorted
  by `vor` desc, `rank = i+1`. (`greatest` and `bool_or` are native Postgres.)
- **`/api/matchups`:** target week N+1; if no schedule rows → `{targetWeek, games: [], myGameId: null, empty:
  true}`. Else group `schedule` by `matchup_id`, build each game's two sides from `team_projections` + records,
  win % from `matchup_win_probs`, each side `{rosterId, name, owner, isMe, record, proj: mu, winProb:
  round(p*100) or null}`. Sort **within** a game: my team first, else higher win % first; sort **games:** my
  game first, else by `matchup_id`. `myGameId` = my game's id or null.
- **`/api/matchups/{matchupId}`:** the two sides w/ `{rosterId, name, owner, isMe, record, proj: mu, sigma,
  range: {p25,p50,p75} = round1(Σ starters' p25/p50/p75, each quantile falling back to the player's `pts` when
  null), starters: [view], bench: [view], winProb}`; teams ordered "you" first then higher win %. Player view
  (`matchupPlayerView`, l.921): `{sleeperId, name, pos, nflTeam, slot (starter's filled slot, else null), proj:
  round1(pts) if hasProj else null, p25, p50, p75, hasProj}`.
- **`/api/teams/{rosterId}` `thisWeek`:** target week N+1; find my `matchup_id` in `schedule`; if none → `null`.
  Else compute both sides via `team_projections`, `{matchupId, targetWeek, me: {proj: mu, winProb}, opp:
  {rosterId, name, proj: mu, winProb}}`.

## The brief to paste to Code

```
Goal: Session 4 of the store migration (Stage A, MULTI_LEAGUE_STORE_MIGRATION.md A3→A4). Port the LEAGUE and
MATCHUPS reads from the browser DuckDB SQL in application/frontend/src/queries.js to FastAPI endpoints in
application/api/, backed by the Session-2 Postgres tables, AND complete the team-detail "thisWeek" projection
bar that Session 3 deferred. Do NOT wire the frontend (that's Session 5) and do NOT touch queries.js/db.js/views.

Contract: every endpoint returns the SAME shape as its queries.js loader (field names, nulls, ordering). Read
queries.js (loadLeague l.370, loadPositionalTalent l.396, loadMatchups l.878, loadMatchupDetail l.942,
teamMatchupSummary l.846, teamProjections l.765, expandSlots l.994, optimalLineup l.1007, matchupWinProbs
l.837, normalCdf/erf l.1027) + application/api/reads.py + calcs.py first.

Build the shared projection/win-prob engine ONCE in application/api/projections.py: expand_slots,
optimal_lineup, team_projections, matchup_win_probs, normal_cdf. The matchups slate, matchup detail, and the
team-detail thisWeek bar ALL call team_projections — don't inline it three times.

Endpoints: GET /api/league (=load_standings + league_settings playoff_teams/num_teams); GET
/api/positional-talent (market_vor sum(greatest(market_vor,0)) per roster x position, latest snapshot, ranked);
GET /api/matchups (week N+1 slate, projected mu + analytic win prob); GET /api/matchups/{matchupId} (one game's
Score Range + per-starter gauges); and REPLACE the "thisWeek": None stub in reads.load_team_detail with the real
teamMatchupSummary. Week-scoped ones take ?as_of_week=N (default latest); targetWeek = N+1.

Engine math: mu = sum of optimal-starter center_ppr, round1'd at the team level; sigma = sqrt(sum of starter
band_ppr^2), raw; win prob = round(normal_cdf((muA-muB)/sqrt(sigA^2+sigB^2)) * 100). Use math.erf for
normal_cdf (within 1.5e-7 of the app's Abramowitz-Stegun approx; win% is rounded to an integer so it matches —
if any % differs from the app, port the A&S erf verbatim). optimal_lineup: most-constrained slot first, greedy
top-pts eligible unused player, strict > so first-seen wins ties — iterate the roster in query order (ORDER BY
sleeper_player_id) so the picked starter matches the app.

Reuse Session-3 code, don't re-derive: reads._latest (arg_max roster-as-of-N — MUST match team detail),
reads._sql_standings_weeks, calcs.js_round/round1. Every query stays scoped by league_id = settings.league_id().

NULL-SAFE (do this): the new projection reads (center_ppr/band_ppr/p25/p50/p75) can be null — a player with no
projection that week contributes pts=0/band=0 and won't start (queries.js l.809-814), and the Score Range falls
back p25 ?? pts (l.963-965). Reproduce those with a null-safe coercion helper (e.g. _num(x, default)), NOT bare
float(). This is the guardrail from the Session-1-3 audit; establish the helper so the read layer adopts it.

Decisions (hold): (a) keep MY_USERNAME semantics (isMe) — no viewer_roster_id refactor (Stage B); (b) don't
rename projection_consensus *_ppr (Stage B); (c) round mu BEFORE computing win prob (the app does).

Watch-items (Postgres dialect): arg_max -> reads._latest; greatest()/bool_or() are native Postgres;
projection_consensus is keyed per week (WHERE week = targetWeek), NOT tall over as_of_week. schedule is
pairing-only (week -> matchup_id -> roster_ids).

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-COMMIT CAP, update STATUS.md, close/merge,
push. Suggested commits: (1) projections.py engine + a unit check of optimal_lineup and one hand-computed win
prob; (2) /api/matchups + /api/matchups/{id} + wire thisWeek into /api/teams/{id}; (3) /api/league +
/api/positional-talent + STATUS.md. IF commit 1 (the engine) proves hairy and you'd blow the cap, ship commits
1-2 (matchups + thisWeek — the parity-critical chain) and split /api/league + /api/positional-talent into a
quick "Session 4b" — note it in STATUS as the next move. Both must exist before the Session-5 swap either way.

Verify (endpoint-level; frontend not wired): for as_of_week=3 and 4, curl each endpoint and confirm its JSON
matches today's app for the same inputs — spot-check a matchup's two projected totals + win % (they should sum
to ~100), the Score Range ordering, the League standings + playoffCut/nTeams, and the team-detail thisWeek
opponent. Show me one matchup's output and the League payload next to the current app's numbers.

Close: update STATUS.md (shipped + next move — Session 5: frontend becomes an API client, queries.js -> fetch,
delete db.js/DuckDB-WASM; note the Session-5 null-policy decision). Merge/push.
```

## Definition of done
✅ `application/api/projections.py` holds the shared engine; `/api/league`, `/api/positional-talent`,
`/api/matchups`, `/api/matchups/{matchupId}` live and return their `queries.js` loader shapes from Postgres;
`reads.load_team_detail` returns a real `thisWeek` (the stub is gone); ported math matches the app at ≥2 weeks
(win % pairs sum to ~100; Score Range = Σ starter quantiles); the new projection reads are null-safe (no bare
`float()`); `MY_USERNAME`/`*_ppr` untouched; `STATUS.md` updated with Session 5 as the next move. Frontend
untouched. *(If split: 4b = `/api/league` + `/api/positional-talent`, recorded as the next move.)*

## Notes / gotchas
- **The win-prob engine is the real work** — optimal lineup + μ/σ + `normal_cdf`, shared by three surfaces.
  Get `team_projections` right once and the three endpoints are thin wrappers.
- **Round μ before the win prob.** `teamProjections` stores `round1(mu)` and the win-prob math reads that
  rounded μ (`queries.js` l.827 → l.862/901/983). Compute σ raw. Easy to miss; it shifts the integer %.
- **`projection_consensus` is per-week, not tall over `as_of_week`** — filter `WHERE week = targetWeek`, no
  `as_of` slice. It's the one derived table that isn't a season-replay slice.
- **`math.erf` vs the app's A&S `erf`:** identical after rounding to integer %. The A&S port is the fallback
  if you ever see a 1-point drift, but you shouldn't.
- **Determinism:** the optimal-lineup tie-break is first-seen; a stable `ORDER BY sleeper_player_id` on the
  roster read makes Postgres match the app's pick. Same reasoning as Session 3's added tiebreaks.
- **This is the biggest session** — the 3-commit cap is real. The escape hatch (ship matchups+thisWeek, spill
  League to 4b) exists precisely so you don't rush the win-prob engine to fit everything in.
- **Nothing visible changes** — success is correct JSON, not anything on screen. The frontend moves onto all
  of this in Session 5.
