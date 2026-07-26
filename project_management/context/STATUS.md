# STATUS

**What this is:** Gridiron — a fantasy-football decision-support dashboard whose unit is the manager's
*decision*, not the player. Live, single-league, on the server stack.
**Live at:** https://fantasy-ai-api.fly.dev/ · **Updated:** 2026-07-26
**Read next:** `ARCHITECTURE.md` (how it's built) · `CODING_BIBLE.md` (rules for coding agents) ·
`ROADMAP.md` (where it's going) · `projects/v1/` (the active build).

---

## What's live today

- A deployed, mobile-responsive React SPA on **FastAPI + Supabase Postgres** (Fly.io, same-origin). Five
  surfaces: **Players, Teams, League, Matchups, Manager Dossier**.
- **Single league, no auth.** It serves one league (the owner's, 2025) **frozen at Week 4** — a season
  *replay*, not live data. A week selector (1–4) re-scopes every surface.
- Fully migrated off in-browser DuckDB-WASM (Stage A complete); the client is now a thin API client.

## The engine

- Built, measured, and deliberately made **honest** — i.e. tuned so its stated confidence is truthful rather
  than flattering (the shipped "8c" change: a lower center + a wider two-sided band). Reads it produces:
  production VOR, projection bands, playoff odds (Monte Carlo), positional depth, true rank, player signal,
  market VOR, the ROS bull/bear/situation outlook, and manager dossiers.
- **Current honesty state:** production VOR ranks rest-of-season value well but runs the *level* high (trust
  the order, not the total); the band was re-tuned to ~0.86 coverage; playoff odds and true rank are honest;
  four reads still carry no confidence signal. **The honest band is live in the engine's constants but not
  yet shown in the UI** — the front-end still renders the older band. → *see appendix: engine-trust,
  engine-decision-reads.*

## What's real vs. proof-of-concept (current caveats)

- **Market value + trade lean = cross-time POC** — 2026 prices against 2025 rosters, explicitly not a live
  call. Resolves once the app runs on live 2026 data.
- **ROS bull/bear/situation grades render "—"** (empty). The old 2026-news-vs-2025 splice was retired; this
  is the honest empty state until a year-matched live-news read exists.
- **Rostered-only** — no free-agent / waiver value yet.
- **Data collection runs on a laptop** (~63–71% daily coverage) — not yet moved off-host. → *see appendix:
  data-collection.*

## In flight — Stage B (multi-league)

- **B0–B3 shipped:** all 31 demo league-seasons are loaded into the production database, `schedule` is
  league-scoped, and the lineage catalog endpoint `GET /api/leagues` exists. **Parity held** — the deployed
  app still renders only the owner's league. → *detail: `sessions/v1/`.*
- **Two items to close in B4:** `/api/leagues` is loaded but the app wasn't redeployed, so it **404s on the
  live URL**; and the 2025 catalog entry still flags `panels_ros=true` while ROS is empty (set false).
- **NEXT — B4:** parameterize every read endpoint on `league_id`(+`season`), defaulting to the current league
  so nothing visibly changes (parity), and redeploy. **Drafted and ready to run.** Then B5 (selectors +
  `viewer_roster_id` + panel gating) and B6 (verify). → `projects/v1/` (P0).

## The active roadmap

**V1** = a working, **invite-gated self-serve** product for **Sleeper PPR / half-PPR redraft** (1QB and
superflex), running on **live 2026 data**, ready for the invited cohort by **Week 1**. Seven projects
(P0 finish multi-league → P6 launch hardening); critical-path spine is P0 → P2 → P5. →
`ROADMAP.md` + `projects/v1/BUILD_ORDER.md`.

## Deferred / parked (not blocking; each picked up in its project)

- **Silent-reads confidence** — give production VOR, player-signal direction, and playoff wins/seed a
  confidence signal (the current law-2 gap).
- **`*_ppr` naming wart** — the `center_ppr` / `band_ppr` / … columns hold *league* points, not PPR; the
  rename is coupled to a frontend + schema change. → *see appendix: scoring-mechanism.*
- **Superflex market-VOR QB-pool latent** — verify when the live market read lands.
- **Post-V1 features** — other scoring formats, dynasty, other platforms, owner-keyed dossiers, annual
  re-tune → `projects/post-v1/`.
