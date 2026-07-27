# Session 3 — Players + Teams API Endpoints (a brief for Code)

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code (Will operates + eyeballs)

> **What this session does:** move the **Players** and **Teams** screens' data reads (plus the shared
> league-meta and weeks reads) out of the browser and into FastAPI endpoints backed by the Session-2
> Postgres tables — porting their SQL to Postgres and their inline JavaScript calculations to Python. The
> frontend is **not** wired to these yet (that's Session 5); this session builds and verifies the endpoints.
> Stage A of `MULTI_LEAGUE_STORE_MIGRATION.md`; single league, no auth, no new formats.
>
> **The contract:** each endpoint must return the **same shape** the matching `queries.js` loader returns
> today, so the Session-5 frontend swap is drop-in. `queries.js` is the source of truth for shapes.

## Your part, Will (~10 minutes)
Kick off the session with the brief below. At the end, glance at Code's endpoint check — it should show a
couple of endpoints' JSON output matching today's app for the same week. That's your "looks right."

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Match the `queries.js` loader shapes exactly** (field names, nulls, ordering). The loader is the contract.
2. **Defer the team-detail "this week" projection bar to Session 4.** `loadTeamDetail` pulls in the entire
   Matchups projection/win-probability chain (`teamMatchupSummary` → `expandSlots`/`optimalLineup`,
   `projection_consensus`, μ/σ roll-up, `normalCdf`/`erf`). That same chain **is** Session 4's core, so
   building it now duplicates work and blows the 3-commit cap. `/api/teams/{rosterId}` returns everything
   **except** `thisWeek` this session; Session 4 adds `thisWeek` **before** the Session-5 frontend swap.
   (Parity only has to hold at Session 5, so a tracked temporary gap on this one sub-panel is fine.)
3. **Keep `MY_USERNAME` behavior identical** — `isMe`/`onYours`/`myOwner` stay exactly as today. Do **not**
   refactor to `viewer_roster_id` yet; that's Stage B. Read `MY_USERNAME` from server config/env.
4. **Leave the `projection_consensus` `*_ppr` naming wart alone** — it's only touched by the deferred
   `thisWeek` chain, and renaming it is a Stage-B job (it's coupled to the `queries.js` rewrite).

## Endpoints to build this session

| Endpoint | Ports (queries.js) | Notes |
|---|---|---|
| `GET /api/weeks` | `loadWeeks` (l.644) | `{weeks, latest}` — needed by the others' "latest" default |
| `GET /api/league-meta?as_of_week=N` | `loadLeagueMeta` (l.659) | top-bar label; scoring + QB/SF derivation |
| `GET /api/players?as_of_week=N` | `loadPlayers` (l.87) | VOR table, sorted PROD VOR desc |
| `GET /api/players/{sleeperId}?as_of_week=N` | `loadPlayerCard` (l.120) | player card; 6 reads |
| `GET /api/standings?as_of_week=N` | `loadStandings` (l.278) | record + all-play + odds + posture |
| `GET /api/teams/{rosterId}?as_of_week=N` | `loadTeamDetail` (l.448) | **minus `thisWeek`** (see decision 2) |
| `GET /api/managers/{rosterId}` | `loadManagerDossier` (l.583) | clean passthrough, no calc |

## Calculations to port to Python (read `queries.js` for exact logic)

- `seriesRead` (l.616) — value=last, delta=last−first, up flag.
- Trade lean (l.193–200), threshold `TRADE_GAP_T = 0.25` → SELL/BUY/HOLD (player card).
- **All-play "true record"** (l.302–312 standings; l.496–505 team detail) — each week, score vs every other
  team → W/L; `pct = w/(w+l)*100`. Must match exactly.
- `derivePosture(playoffPct, allPlayPct)` — **imported from `src/posture.js`** (read that file; it wasn't in
  my inspection snapshot). Standings + team posture chip.
- Standings sort + 1-indexed rank (l.353): playoffPct desc (nulls last), tiebreak allPlayPct desc.
- Positional-depth rank + `SHAPE_LABEL` (l.435, l.517–534): sort teams by `starter_value`, rank the target;
  map `surplus/adequate/gap → SURPLUS/EVEN/GAP`.
- `loadLeagueMeta` label derivation (l.671–683): scoring label from `rec`; QB/SF from lineup slots.
- `round1`/`num` coercion helpers (l.623–625).
- The as-of-week seam: `n == null → latest`; `as_of_week = max()` vs `= N`; `week <= N` vs `TRUE`
  (`asOfSlice`/`weekCutoff`, l.632/636). Replicate server-side.

## The brief to paste to Code

```
Goal: Session 3 of the store migration (Stage A, MULTI_LEAGUE_STORE_MIGRATION.md A3). Port the PLAYERS and
TEAMS reads (+ shared /api/weeks and /api/league-meta) from the browser's DuckDB SQL in
application/frontend/src/queries.js to FastAPI endpoints in application/api/, backed by the Session-2
Postgres tables. Move each loader's SQL to Postgres and its inline JS calculations to Python. Do NOT wire
the frontend (that's Session 5) and do NOT touch queries.js/db.js/views.

Contract: every endpoint returns the SAME shape as its queries.js loader (field names, nulls, ordering) —
that shape is the contract for the Session-5 swap. Read queries.js + src/posture.js + application/data/
serve/schema.sql + application/data/serve/MANIFEST.md first.

Endpoints: GET /api/weeks; GET /api/league-meta; GET /api/players; GET /api/players/{sleeperId};
GET /api/standings; GET /api/teams/{rosterId} (EXCEPT the "this week" bar — deferred to Session 4);
GET /api/managers/{rosterId}. All week-scoped ones take ?as_of_week=N and default N=latest.

Port these calcs to Python: seriesRead; trade lean (TRADE_GAP_T=0.25); all-play "true record"; derivePosture
(from posture.js); standings sort+rank; positional-depth rank + SHAPE_LABEL; league-meta label (scoring +
QB/SF); round1/num; the as-of-week latest/cutoff seam.

Decisions (hold these): (a) DEFER the team-detail thisWeek projection bar to Session 4 — it needs the whole
Matchups projection/win-prob chain; return the rest of team detail now, TODO-mark thisWeek. (b) Keep
MY_USERNAME semantics identical (isMe/onYours/myOwner) — no viewer_roster_id refactor yet (Stage B). (c)
Don't rename the projection_consensus *_ppr columns (Stage B).

Watch-items: Postgres dialect port is the main risk — DuckDB QUALIFY / arg_max / any_value need Postgres
equivalents (window + subquery, DISTINCT ON, etc.). slots.parquet maps to the lineup_slots table.
team-detail and standings both need LEAGUE-WIDE rows (all-play; depth rank), even for one team.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push.

Verify (endpoint-level; frontend not wired): for a couple of weeks (e.g. as_of_week=4 and one earlier),
curl each endpoint and confirm its JSON matches today's app output for the same inputs — spot-check the
Players table order (PROD VOR desc) and a few values, the standings all-play %, a player card, a team detail.
Show me two endpoints' output next to the current app's numbers.

Close: update STATUS.md (shipped + next move = Session 4: League + Matchups endpoints AND the deferred
team-detail thisWeek chain). Merge/push.
```

## Definition of done
✅ The seven endpoints live in `application/api/`, each returning its `queries.js` loader's shape from Postgres;
the ported Python calcs match; endpoint output verified against today's app at ≥2 weeks; team-detail `thisWeek`
cleanly deferred (TODO → Session 4); `MY_USERNAME` semantics unchanged; `STATUS.md` updated. Frontend untouched.

## Notes
- **The Postgres dialect port is the real work** — the DuckDB SQL leans on `QUALIFY`, `arg_max`, `any_value`.
- **`posture.js` must be read and ported** — it's an external import the standings/posture depend on.
- **Nothing visible changes** — success is correct JSON from the endpoints, not anything on screen.
