# Stage B — Session B4: Parameterize the reads on `league_id` (+`season`) — a brief for Code

**Last reviewed:** 2026-07-26 · **Status:** Ready to run · **Owner:** Code drives; Will kicks off + eyeballs
the parity + live-endpoint checks. **Depends on:** B3 (all 31 slices in the DB + the `demo_manifest`
catalog — done). This is the **last backend step** before the B5 frontend selectors make multi-league
visible.

> **What this session does:** turn every read endpoint from "hardwired to the is_mine league via
> `settings.league_id()`" into "takes an **optional** `league_id` (+`season`), defaulting to the is_mine
> slice." Omitting the params reproduces today's behavior **exactly** (parity) — so nothing a user sees
> changes yet; the deployed app still shows the one is_mine league until B5 adds the dropdowns. This
> session also **closes the two carry-forward items from the B3 audit**: (A) redeploy so `GET /api/leagues`
> is finally live, and (B) make the ROS catalog flag honest. `MULTI_LEAGUE_STORE_MIGRATION.md` B4.

## Your part, Will (~10 min to kick off; then it runs)
Kick it off. Three "looks right" checks when it's done, all on the **deployed** URL:
1. **Parity:** with no params, the app is byte-identical to today (standings Wk4, weeks, matchups).
2. **Multi-league works:** an endpoint hit with `?league_id=<a corpus league>` returns *that* league's data.
3. **The catalog is finally live:** `https://fantasy-ai-api.fly.dev/api/leagues` returns your 12-lineage
   tree (it **404s today** — B3 loaded the data but never redeployed the app).

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Query params, not path params — default to the is_mine slice (PARITY).** Every read endpoint gains an
   **optional** `?league_id=&season=`. When omitted → `settings.league_id()` (today's Fly secret) → the
   endpoint behaves **exactly** as it does now. So the deployed app is unchanged and the existing `/api/*`
   URLs keep working until B5 starts passing params. (Path-style `/api/leagues/{id}/{season}/players` is
   cleaner REST but a bigger rewrite that breaks current URLs — not now, maybe never.)
2. **`league_id` is the operative key; `season` is optional/defensive — don't over-engineer it.** Redraft
   leagues get a **new `league_id` every season**, so a `league_id` already pins one `(league, season)`
   slice — the reads today filter on `league_id` only and that is *correct*. Accept `?season=` for
   robustness + future dynasty, but **do not** add a per-season SQL filter that could mis-scope a slice.
   Validate `(league_id[, season])` against `demo_manifest`; return empty/404 for an unknown slice. (The
   manifest has 31 unique `league_id`s across 12 lineages — one season each — so this holds for the whole
   demo. `projection_consensus` is stamped per `(league_id, season)`, so `league_id` filtering is right
   there too.)
3. **Viewer identity ("me") stays in B5 — parameterize the DATA filter only.** The
   `MY_USERNAME → viewer_roster_id` swap and the panel gating (`readiness.jsx`) are B5. Interim B4 state:
   for a non-is_mine league, `MY_USERNAME` matches nobody → no "me" highlight → personal panels come back
   empty. That's an **acceptable** B4 state — don't do the viewer swap now (one change at a time). For the
   is_mine league (no params) "me" still resolves exactly as today.
4. **Thread it through `reads.py`, keep every shape byte-identical.** Each `load_*` gains `league_id=None`
   (+`season=None`) and resolves to `settings.league_id()` when `None`. The helpers that bake
   `settings.league_id()` into the SQL (`_week_cutoff` / `_as_of_slice` / `_le_cutoff` and the `%(lid)s`
   param dict) take the **resolved** `lid`. No Pydantic, plain dicts — the JSON payloads must stay
   identical (that's the parity proof).

## Two carry-forward items from the B3 audit — close them here

**A. Redeploy + live smoke-test `/api/leagues` (closes the B3 gap).** B3 reloaded the DB but did **not**
redeploy the app, so `GET /api/leagues` **404s on the deployed app** today (I verified — sibling Stage-A
routes 200, the new route 404s). After B4's changes, **redeploy the Fly app** and verify **on the deployed
URL** (not just the worktree uvicorn): (1) `/api/leagues` returns the 12-lineage tree (root `lineage_id`,
seasons desc, `viewer_roster_id` 8, `weeks_available` [1..4] for lorp-2025); (2) a parameterized endpoint
with `?league_id=<a corpus league>` returns that league's rows; (3) with **no** params, is_mine parity
holds (spot-check `standings?as_of_week=4` + `weeks` == today). **This is the first time `load_leagues`
runs against the real Postgres — treat it as a real smoke-test, not a formality.**

**B. Make the ROS catalog flag truthful (Will's call — ratified).** The 2026-news→2025 ROS was a
proof-of-concept; it's **retired for good** (B3 loads 0 rows). Set **`panels_ros = false` for the lorp-2025
slice** in the manifest source (`demo_slate.csv` / `build_demo_manifest.py` — the data-through-`data_layer`
path), regenerate `demo_manifest.parquet`, and **reload the `demo_manifest` catalog table** so
`/api/leagues` no longer advertises ROS anywhere. This is a **catalog-only** write — the 31 data slices are
untouched, parity on panel *data* holds — and it's **inert on the live app until B5** reads the `panels`
map. **Keep** the `ros_synthesis` table + read path: a future **year-matched 2025 news read** is how the
grades come back honestly.
> **B5 follow-through (do NOT do now, note it):** gate the bull/bear/sit panel off (or show an explicit
> "no rest-of-season outlook yet" state, matching the dossier "no intel" pattern) and remove the cross-time
> POC copy (`PlayerCard.jsx`, `Players.jsx`, `TeamDetail.jsx`, `League.jsx`).

## The brief to paste to Code

```
Goal: Stage B, Session B4 (MULTI_LEAGUE_STORE_MIGRATION.md B4) — parameterize every /api read endpoint on
an OPTIONAL league_id (+season), defaulting to the is_mine slice, so multi-league data is reachable by
param while the deployed app stays byte-identical when the params are omitted. Also close two B3
carry-forward items: redeploy so GET /api/leagues is live, and set panels_ros=false for lorp-2025 in the
catalog. Depends on B3 (31 slices loaded + demo_manifest catalog). Parity guard below is non-negotiable.

Part 1 — parameterize the reads (application/api/routes.py + reads.py):
- Every read route gains optional ?league_id= (+ ?season=), passed through to its reads.load_* function.
  Default: when league_id is None, resolve to settings.league_id() — i.e. TODAY's behavior exactly. Keep
  every JSON shape byte-identical (no Pydantic; plain dicts/lists).
- reads.py: each load_* takes league_id=None (+season=None) and resolves None -> settings.league_id().
  Thread the resolved lid through the %(lid)s param dict AND the SQL helpers that currently bake in
  settings.league_id() (_week_cutoff / _as_of_slice / _le_cutoff). league_id is the operative filter —
  redraft league_ids are unique per season, so DO NOT add a per-season SQL filter; season is optional and
  defensive only. Validate (league_id[,season]) against demo_manifest; unknown slice -> empty/404.
- Viewer identity stays B3-style: keep MY_USERNAME/settings.my_username() as the "me" default. The
  MY_USERNAME -> viewer_roster_id swap + panel gating is B5. For a non-is_mine league, MY_USERNAME simply
  matches nobody (no "me") — acceptable interim state; do NOT swap viewer identity this session.

Part 2 — close the B3 carry-forward items:
- REDEPLOY the Fly app (B3 reloaded the DB but never redeployed, so GET /api/leagues 404s on the deployed
  app today). After deploy, smoke-test ON THE DEPLOYED URL: /api/leagues returns the 12-lineage tree;
  ?league_id=<a corpus league> on a data endpoint returns that league's rows; no-params parity holds.
- Set panels_ros=false for the lorp-2025 slice in the manifest source (demo_slate.csv /
  build_demo_manifest.py), regenerate demo_manifest.parquet, and reload the demo_manifest catalog table so
  /api/leagues no longer claims ROS anywhere. Catalog-only write; the 31 data slices are untouched. Keep
  the ros_synthesis table + read path for a future year-matched news read. (Frontend gating + POC-copy
  removal is B5 — not this session.)

PARITY GUARD (this touches production — do it, don't skip it):
- Before: capture the is_mine endpoint responses (standings wk4 + wk2, weeks, league, matchups) from the
  live app.
- After redeploy: with NO params, confirm those responses are byte-identical to before. Then confirm
  ?league_id=<a corpus league> returns that league's data, and /api/leagues returns the 12-lineage tree on
  the DEPLOYED url. Do NOT change Fly secrets (LEAGUE_ID/MY_USERNAME stay the default).

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md,
close/merge, push. Suggested commits: (1) parameterize routes.py + reads.py on league_id(+season) with
is_mine defaults; (2) catalog honesty (panels_ros=false for lorp-2025) + reload demo_manifest; (3) redeploy
+ live smoke-test (/api/leagues tree, a corpus league by param, no-params parity) + STATUS. Show me: an
endpoint's JSON with no params vs with ?league_id=<corpus> (side by side), and the live /api/leagues tree.

Close: update STATUS.md (B4 done: reads parameterized on league_id, is_mine parity held, /api/leagues live
on deploy, panels_ros honest; next = B5 frontend selectors + viewer_roster_id + panel gating). Merge/push.
```

## Definition of done
✅ Every read endpoint accepts optional `league_id`(+`season`) defaulting to the is_mine slice; **omitting
them reproduces today byte-for-byte** (parity). Passing `?league_id=<corpus>` returns that slice's data.
`GET /api/leagues` is **live on the deployed app**, returning the 12-lineage tree. `panels_ros=false` for
lorp-2025 in the catalog. Viewer identity untouched (B5). Fly secrets unchanged. STATUS updated, B5 next.

## Notes / gotchas
- **Parity is still the guard rail.** The no-params path must stay byte-identical — that's how the deployed
  app keeps working through B4. The whole design (optional params, is_mine default) exists to preserve it.
- **Redeploy is required this session** (unlike B3). `/api/leagues` must be reachable on the deployed URL
  at the end — that's the explicit close of the B3 gap.
- **Don't touch Fly secrets** (`LEAGUE_ID`/`MY_USERNAME`) — they stay the default when params are omitted;
  the selector that varies them is B5.
- **`season` is mostly redundant with `league_id`** for redraft — carry it, validate it, don't filter on it.
- **Separate 1-line frontend tweak (NOT this session):** land the app on the **League** tab instead of
  **Players** — `App.jsx` `useState('players')` → `useState('league')`. Do it in B5 (which rewrites
  `App.jsx` anyway) or as a tiny standalone; keep it out of this backend session. (While there, the two
  stale "only Players is wired" comments in `App.jsx` are no longer true — all four tabs render.)
