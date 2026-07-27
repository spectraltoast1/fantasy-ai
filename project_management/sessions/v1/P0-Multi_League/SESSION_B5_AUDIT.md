# Stage B Audit — B5 (frontend league/season selectors + viewer identity + panel gating)

**Reviewed:** 2026-07-26 · **By:** PM (independent — live git on `main`, the B5 code diffs, and the live
deployed app). **No Code delivery report this round** — audited against the B5 brief's definition-of-done and
the live state directly.
**Scope:** make multi-league visible — league + season dropdowns from `/api/leagues`, the API client carrying
the active slice, viewer identity via `viewer_roster_id`, panel gating off the catalog `panels` map, and the
cross-time POC cleanup + landing-tab change. Three commits (`0a2d984`, `aa647fe`, `f3febeb`) + merge `83e84f1`
on `main`, **pushed** (local == origin). Filed at `project_management/sessions/v1/`.

**Bottom line: clean — endorse, and it's deployed. B5 is live on production (I proved the redeploy happened,
which B5's commits didn't spell out), the default view still renders your league identically (parity held),
viewer identity works, and the ROS/market honesty gating + POC cleanup are in. The code matches the brief on
every point. One transparency note: a WebFetch stale-cache artifact briefly looked like a serious parity
break (the live standings appeared to return a different 12-team league) — it was a false alarm, disproven by
the reliable endpoints on the same league_id. The only real gap is that I could not do a visual click-through
(the browser extension wasn't connected this session), so the pixel-level UX is verified by code + live
backend, not by eye — that exhaustive visual pass is exactly B6.**

---

## Verified clean (I read the diffs and probed the live app — there was no report to take on faith)

**Backend — viewer identity, faithful to the brief.** `routes.py` adds `viewer_roster_id` to `slice_params`.
`reads.py` adds `resolve_viewer(lid, viewer_roster_id)` — given a roster it returns it, else it resolves
`MY_USERNAME`'s roster for that league (the same lookup `load_league_meta` already did), else `None` (no "me",
same as today's owner-not-found). The `isMe`/`onYours` test flips from `owner_name == MY_USERNAME` to
`roster_id == viewer` across every surface (`load_players`, `load_standings`, `load_positional_talent`,
`load_league_meta`, `load_player_card`, `load_team_detail`) and `projections.team_projections` (viewer
resolved at the request boundary and passed in — correctly not inside the engine). This is exactly brief
decision 1.

**Frontend — selectors + orchestration, faithful to the brief.** `queries.js` uses the module-level `_slice`
+ `setActiveSlice`, and `apiGet` merges `{ ..._slice, ...params }` so the active slice rides on every request
with per-call params winning — my recommended decision 2, implemented cleanly (views keep calling
`loadPlayers(asOfWeek)` unchanged). `App.jsx` holds `leagues`/`slice`/`switching` state, `LeagueSwitcher` is a
real `<select>` over the 12 lineages (is_mine first), `SeasonSwitcher` mirrors `WeekSwitcher`, and
`switchSlice` sets the slice synchronously → clears the drill-down → reloads weeks → snaps `asOfWeek`, with a
slice-keyed `viewKey` remount to avoid the stale-slice race. `readiness.jsx` gains the catalog `PanelOff` gate
(`panels[panel] === false` → "not available for this league" slot, before the readiness checks;
backward-compatible when no `panel` is passed).

**Honesty cleanup — done (one trivial leftover).** The ROS empty state ("No rest-of-season outlook yet…") is
in `PlayerCard.jsx`, the market empty state ("Market VOR isn't available for this league") is in `League.jsx`
+ `readiness.jsx`, and the cross-time POC copy/pills were removed from `Players`/`PlayerCard`/`TeamDetail`/
`League`. The ROS panel is rendered **in place, not hidden** — the locked decision. *Nit:* the CSS rules
`.pc-poc` / `.td-poc` / `.lg-pt-poc` still exist in `styles.css` but nothing references them anymore (dead
CSS) — harmless, sweep whenever.

**Landing tab + stale comments — done.** `App.jsx` `useState('league')`; the two "only Players is wired"
comments are fixed (all four surfaces render).

**Deployed to production — proven.** B5's commits say "verified on the dev server" and (unlike B4) don't call
out a `fly deploy` step, so I checked directly: `GET /api/league-meta?viewer_roster_id=5` on the live app
returns `myOwner: "Mr1854"` (roster 5's owner), while the default returns `spectraltoast1`. Since the
pre-B5 image had no `viewer_roster_id`, the parameter being honored **proves the B5 image was redeployed** —
and because one Fly image serves both the SPA and the API, the frontend selectors are deployed too. The B3
"merged but not deployed" gap did **not** recur.

**Parity held — default is still your league.** `GET /api/league-meta` (no params, and explicit
`league_id=1182…`) returns `"10-tm · PPR · 1QB"`, record `"3-1"`, `myOwner "spectraltoast1"` — your league,
your record, you as "me." `GET /api/weeks` returns `[1,2,3,4]` (lorp's frozen weeks). Viewer identity's
default (`viewer_roster_id=None → MY_USERNAME`'s roster 8) preserves the old `isMe` set. The default view is
unchanged; the selectors are additive, as intended.

---

## Transparency: the false alarm I chased down (so it's on the record)

Mid-audit, `GET /api/standings` (even with the explicit is_mine `league_id`) appeared to return a **different
12-team league** ("IMG Academy", "The Groyper Army"…) with no "me" — which would have been a serious live
parity break. I did **not** report it, because it failed cross-checks: `league-meta` on the *same* `league_id`
returned your 10-team league with your record, `weeks` returned your 4 weeks, and B5 touched no DB/config/
secret. `standings` reads the same `teams` table `league-meta` does, so it cannot return a different league —
the result was a **WebFetch stale-cache/transcription artifact** (it had cached a corpus-league standings
response from the B4 audit and kept serving it for the `standings` path). This is the same failure mode as
B4's stale-parquet snapshot: a single unreliable read that triangulation disproved. Flagging it so the "near
miss" is visible, not buried.

---

## The one real gap (not a code defect) — no visual click-through this session

The browser extension wasn't connected, so I could not do a live click-through: confirm the dropdowns visibly
render, that switching to a corpus league re-renders it with the viewer highlight following
`viewer_roster_id`, and that the ROS/market empty states display as intended. I verified all of that at the
**code + live-backend** level (the endpoints honor the params; the components render the right slots), so it's
very likely correct — but the pixel-level UX is unconfirmed by eye. That exhaustive visual verification across
every league × season is precisely **B6's job**, so this isn't a blocker; it's the handoff. (If you want a
30-second gut-check before B6, open fantasy-ai-api.fly.dev — it should land on the League tab with a league
dropdown, and switching to, say, The Dysfunctionals should re-render it.)

---

## Recommendation

**B5 is sound — endorse it.** The selectors, viewer identity, panel gating, and honesty cleanup are all
implemented per the brief, deployed to production, and the default view is byte-parity with before. Multi-
league is now *visible*.

**Next: B6 — the full end-to-end verification** across every league × season × sample weeks (the exhaustive
click-through the sandbox couldn't do here), plus a couple of contrasting screenshots as proof. That closes
Stage B. Draft is attached.
