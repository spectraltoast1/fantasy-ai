# Stage B — Session B5: Frontend league/season selectors + viewer identity + panel gating — a brief for Code

**Last reviewed:** 2026-07-26 · **Status:** Ready to run · **Owner:** Code drives; Will kicks off + eyeballs
the switch. **Depends on:** B4 (every read parameterized on `league_id`+`season`, `/api/leagues` live — done).
**This is the session that makes multi-league VISIBLE** — the biggest frontend change in Stage B.

> **What this session does:** wire the catalog into the UI so a user can actually **switch leagues and
> seasons** and read any of the 12 lineages, with the right "you" highlighted and the sparse panels gated
> honestly. Four moving parts: (1) **selectors** — a real league dropdown + a season dropdown, driven by
> `GET /api/leagues`; (2) **the API client passes the active slice** (`league_id`+`season`+`viewer_roster_id`)
> on every request; (3) **viewer identity** — `MY_USERNAME` gives way to the per-slice `viewer_roster_id`
> (the "me" highlight follows the selected league); (4) **panel gating + honesty cleanup** — `readiness.jsx`
> hides/empties panels the slice doesn't have (ROS off everywhere, market only on lorp-2025), and the old
> cross-time POC copy comes out. Plus the small landing-tab change Will asked for.
> `MULTI_LEAGUE_STORE_MIGRATION.md` B5.

## Your part, Will (~10 min to kick off; then a real click-through)
When it's done the app finally *does the thing*: a **league dropdown** (your 12 leagues) and a **season
dropdown** next to the week selector. Two checks: (1) **on first load it looks exactly like today** — your
league, your season, you highlighted, same numbers (the selectors are additive, nothing about the default
view changes); (2) **switch to a corpus league** (say Trap or The Dysfunctionals) and it re-renders that
league — its standings, its teams, and no fake ROS panel. The full every-league sweep is B6; B5 just has to
make the switch work and keep your default view identical.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Viewer identity → `viewer_roster_id`, parameterized like `league_id` (default = today's "me").** Add an
   optional `?viewer_roster_id=` to the reads (same shape as B4's `league_id`). The "me" test flips from
   `owner_name == MY_USERNAME` to `roster_id == viewer_roster_id` in `reads.py` **and** `projections.py`
   (both compute `isMe`/`onYours`). **Default for parity:** when no `viewer_roster_id` is passed, resolve it
   from `MY_USERNAME` for the is_mine league exactly as today — so the no-param path is byte-identical. Keep
   the `MY_USERNAME` Fly secret as that default resolver; don't rip it out. **Parity anchor:** the is_mine
   `viewer_roster_id` is **8**, which is the roster `MY_USERNAME='spectraltoast1'` already resolves to
   (Tet Lasso) — so the swap is a **no-op for your league** (verify `isMe` is unchanged). This is a
   backend + frontend change; it's the one piece of B5 that isn't purely frontend.
2. **How the frontend passes the active slice — one setter, not prop-threading (recommended).** Rather than
   thread `league_id`/`season`/`viewer_roster_id` through every surface and detail component (a big,
   error-prone diff), give `queries.js` a module-level **`setActiveSlice({league_id, season,
   viewer_roster_id})`** that `apiGet` merges into every request. App calls it **synchronously on slice
   change, before issuing the reloads** — so the surfaces (`Players.jsx`, `Teams.jsx`, …) stay unchanged and
   keep calling `loadPlayers(asOfWeek)` as they do today. (This mirrors how `MY_USERNAME` was a single module
   constant.) *Ordering caveat:* set the slice before the reload fires. Prop-threading is the more
   "React-pure" alternative if you prefer explicitness — your call, but the setter is the smaller, safer diff.
3. **Selector orchestration — the switch is a reload, not a merge.** Add `league`+`season` global state in
   `App.jsx` beside `asOfWeek`. Turn `LeagueSwitcher` (the static name display) into a real dropdown from
   `GET /api/leagues`; add a `SeasonSwitcher` mirroring `WeekSwitcher`. On **league change** → resolve that
   lineage's seasons → default to its latest → set the slice → reload `/api/weeks` for the new slice → reset
   `asOfWeek` to that slice's latest → set `viewer_roster_id`. On **season change** → same, within the
   lineage. Clear the drill-down stack on any switch (like a tab change). Show a light loading state during
   the swap.
4. **Panel gating — gate on the catalog `panels` map first, data-presence second.** Extend `readiness.jsx`
   to read the selected slice's `panels` (`market`/`manager`/`ros_synthesis`) from `/api/leagues`:
   - **ROS (`ros_synthesis`) is false everywhere** → the bull/bear/sit panel shows an explicit
     **"No rest-of-season outlook yet"** empty state — **NOT hidden** (Will's call, locked 2026-07-26).
     Render the message **in the panel's place** (match the dossier "no intel" pattern) so the layout stays
     stable and it reads as honest rather than broken. Do not remove the panel or collapse its slot.
   - **market** is true only on lorp-2025 → market/positional-talent panels gate off elsewhere.
   - **manager** is true on all 31, but the *data* is sparse → keep the existing data-presence "No dossier /
     no intel" fallback for empty managers. So: `panels` map = "is this panel meaningful for this slice,"
     data-presence = "is there content to show."
5. **Honesty cleanup — remove the cross-time POC copy.** With ROS off and market honest per-slice, strip the
   "2026 cross-time preview / POC" copy from the player + team + league surfaces (the
   `PlayerCard`/`Players`/`TeamDetail`/`League` components — find the actual strings; the old line numbers in
   the migration doc are stale). Don't leave copy that describes a behavior that no longer exists.
6. **Landing tab → League (Will's ask, folded in).** `App.jsx`: `useState('players')` → `useState('league')`
   so the app opens on the League overview. While in that file, **fix the two stale comments** ("during the
   migration only Players is wired; …coming-soon slot") — all four tabs render now; that note is no longer true.

## The brief to paste to Code

```
Goal: Stage B, Session B5 (MULTI_LEAGUE_STORE_MIGRATION.md B5) — make multi-league VISIBLE: league + season
selectors driven by GET /api/leagues, the API client passing the active slice, viewer identity via
viewer_roster_id, and panel gating off the catalog panels map. Depends on B4 (reads parameterized on
league_id+season; /api/leagues live). PARITY: the DEFAULT view (is_mine league, its latest season, you
highlighted) must render exactly as today — the selectors are additive.

Part 1 — viewer identity (backend + frontend):
- Add optional ?viewer_roster_id= to the reads (mirror B4's league_id). Flip the "me" test from
  owner_name==MY_USERNAME to roster_id==viewer_roster_id in reads.py AND projections.py (isMe/onYours).
  When no viewer_roster_id is passed, default to the roster MY_USERNAME resolves to for the is_mine league —
  so the no-param path is byte-identical. Keep the MY_USERNAME secret as that default resolver.
- Parity anchor: is_mine viewer_roster_id is 8 = MY_USERNAME's roster (Tet Lasso). Confirm isMe is unchanged
  for the is_mine league after the swap.

Part 2 — the API client passes the active slice (queries.js):
- Add a module-level setActiveSlice({league_id, season, viewer_roster_id}); apiGet merges it into every
  request's query params. App sets it SYNCHRONOUSLY on slice change, before issuing reloads. Surfaces keep
  calling loadPlayers(asOfWeek) etc. unchanged. Add loadLeagues() is already there (B3).

Part 3 — selectors + orchestration (App.jsx):
- Add league+season global state beside asOfWeek. LeagueSwitcher -> real dropdown from GET /api/leagues
  (12 lineages, is_mine first); add SeasonSwitcher mirroring WeekSwitcher. On league change: resolve seasons
  -> latest -> setActiveSlice -> reload /api/weeks -> reset asOfWeek to latest -> set viewer_roster_id. On
  season change: same within the lineage. Clear the detail stack on switch; show a loading state.
- Default landing tab: useState('players') -> useState('league'). Fix the two stale "only Players is wired"
  comments (all four tabs render now).

Part 4 — panel gating + honesty cleanup (readiness.jsx + surfaces):
- readiness.jsx gates on the selected slice's panels map (market/manager/ros_synthesis) from /api/leagues,
  PLUS the existing data-presence fallback. ros_synthesis=false everywhere -> bull/bear/sit panel shows an
  explicit "No rest-of-season outlook yet" empty state rendered IN the panel's place (NOT hidden, NOT fake
  grades) — locked decision, match the dossier "no intel" pattern. market=false off lorp-2025 ->
  market/positional-talent gate off. manager=true everywhere but keep the data-presence "no intel" fallback.
- Remove the cross-time POC copy from PlayerCard/Players/TeamDetail/League (find the actual strings; old line
  numbers are stale).

PARITY GUARD:
- First load with the default slice (is_mine, latest season, viewer 8) must render every surface exactly as
  today — same standings/players/matchups/league numbers, same "me" highlight. The selectors ADD the ability
  to switch; they don't change the default. Do NOT change Fly secrets.
- Verify by switching: pick 1-2 corpus leagues (e.g. Trap, The Dysfunctionals), confirm they render (their
  standings/teams), the viewer highlight follows viewer_roster_id, ROS panel shows the empty state, market
  panels gate off. read_network_requests shows /api/* 200s with the slice params; read_console_messages clean.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push. Suggested commits: (1) viewer_roster_id backend param + queries.js setActiveSlice/apiGet; (2) App.jsx
league+season selectors + orchestration + landing tab; (3) readiness.jsx panel gating + POC-copy removal +
verify (default parity + a corpus switch, screenshotted) + STATUS. Show me: the default is_mine view
unchanged, and one corpus league rendered via the selector.

Close: update STATUS.md (B5 done: selectors live, viewer_roster_id identity, panels gated, POC copy removed,
default parity held; next = B6 full E2E every league x season x sample weeks). Merge/push.
```

## Definition of done
✅ League + season dropdowns (from `/api/leagues`) let you switch across all 12 lineages; the API client sends
`league_id`+`season`+`viewer_roster_id` on every request. Viewer identity is `viewer_roster_id` (the "me"
highlight follows the slice); the is_mine default is byte-identical to today (viewer 8 == `MY_USERNAME`'s
roster). `readiness.jsx` gates panels off the catalog `panels` map + data presence — ROS shows the honest
empty state everywhere, market gates off outside lorp-2025. Cross-time POC copy removed. App opens on the
League tab; stale comments fixed. Fly secrets unchanged. STATUS updated, B6 next.

## Notes / gotchas
- **Parity now means "the default view," not "the only view."** B5 is the first session that intentionally
  adds a visible control. The guard is: default slice renders identically to today; switching is the new
  capability. The viewer swap (8 == `MY_USERNAME`'s roster) is the anchor that keeps the default identical.
- **Set the active slice before reloading.** With the module-level `setActiveSlice` approach, order matters —
  set it synchronously, then fire the reloads, or a stale slice leaks into the first request.
- **`season` is cosmetic server-side** (B4) — but the frontend still needs it to resolve `(lineage, season)`
  → the concrete `league_id` from the catalog, which is what actually scopes the read.
- **Don't over-reach into a full E2E** — B5 proves the switch works on the default + a corpus league or two.
  The exhaustive every-league × every-season × sample-weeks sweep (and the per-league quirks it'll surface,
  like B4's NULL `matchup_id`) is **B6**.
- **The `projection_consensus *_ppr` naming wart** (columns named `*_ppr` that hold league points) can wait —
  don't fold a rename into this session.
```
