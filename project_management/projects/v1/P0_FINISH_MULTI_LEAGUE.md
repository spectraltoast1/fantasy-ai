# Project 0 — Finish Multi-League & Make It Visible

**Created:** 2026-07-26 · **Status:** ✅ COMPLETE (B4–B6 shipped; Stage B verified end-to-end 2026-07-27 — see `sessions/v1/SESSION_B6_VERIFICATION_REPORT.md`) · **Track:** Critical spine — foundation for everything else · **Est:** 3–4 sessions

> **This project has no new architecture doc — it is the completion slice of the existing
> `MULTI_LEAGUE_STORE_MIGRATION.md` (Stage B).** That doc is the authoritative project brief; read it
> (and the `MIGRATION_PM_STARTUP.md` startup) for context, decisions-locked, and the full B0–B6 map. This
> page just isolates the *remaining* three sessions (B4 → B5 → B6) and their definitions of done so P0 is a
> clean unit in the build order.

---

## What this project delivers

The app can serve **any** loaded league/season through the API and render it correctly — including
resolving "you" per league. Today the reads are hardwired to one league and the "you" user is a hardcoded
username. Until that's fixed, none of the self-serve work (P5) has anything to target. This is the
foundation, and most of it is already built (Stage A + B0–B3 shipped).

## Where it stands (2026-07-26)

- **B0–B3 shipped + audited:** the 31-slice demo slate is loaded into Postgres, `schedule` is
  league-scoped, and `GET /api/leagues` (the catalog) exists.
- **Two carry-forward items** from the B3 audit are folded into B4: `/api/leagues` 404s on the *deployed*
  app (loaded but never redeployed), and the ROS catalog flag needs to be set honest.

## Session map (the remaining slice)

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **B4 — Parameterize the reads** *(drafted: `SESSION_B4_PARAMETERIZE_READS.md`)* | Every read endpoint takes an **optional** `league_id`(+`season`), defaulting to today's league | Thread `league_id` through `routes.py` + `reads.py`; validate against `demo_manifest`; **redeploy** so `/api/leagues` is live; set `panels_ros=false` for lorp-2025 | No-params calls are **byte-identical** to today (parity); `?league_id=<corpus>` returns that league; `/api/leagues` live on the deployed URL |
| **B5 — Frontend selectors + identity** | Make multi-league **visible** and replace the "you" hardcode | League + season dropdowns in `App.jsx`; `MY_USERNAME` → per-league `viewer_roster_id` (viewer-as-data); gate absent panels in `readiness.jsx`; remove cross-time POC copy; land on the League tab | A user can switch league/season in the UI; "you" highlights the right roster per league; leagues missing a panel gate cleanly instead of breaking |
| **B6 — End-to-end verification** | Prove it across the whole slate | Click through every league × season × sample weeks; check identity, gating, `read_network_requests`/`read_console_messages` clean | Every slice renders; identity correct; absent-analytics slices gate, not break; screenshots of two contrasting slices |

## Decisions already locked (don't reopen — see `MIGRATION_PM_STARTUP.md`)

- Query params (not path params), defaulting to the is_mine slice, to preserve parity.
- `league_id` is the operative filter; `season` is carried + validated but **not** SQL-filtered (redraft
  league_ids are unique per season).
- Viewer identity swap (`MY_USERNAME` → `viewer_roster_id`) happens in **B5**, not B4.

## Risks / notes

- **Parity is the guard rail** through B4 — the no-params path must stay byte-identical; that's how the
  deployed app keeps working until B5 intentionally changes what's shown.
- B5 is the substantive frontend change and the most likely to want a second session — budget for it.
- Remember the machine hygiene: clear `.git/index.lock` before each Code session; merges/pushes happen on
  Will's machine.

## Definition of done (project)

The API serves any loaded league/season by parameter, the frontend lets you select league + season and
resolves "you" per league, absent panels gate honestly, and it's verified across the demo slate. **This is
the seam every later project plugs into.**
