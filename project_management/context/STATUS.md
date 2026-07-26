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
- **Multi-league, no auth.** A **league + season selector** switches across the **12 demo lineages**; the
  owner's league (2025, **frozen at Week 4** — a season *replay*) is the default, and the "you" highlight
  follows the selected league. A week selector re-scopes every surface.
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

- **ROS bull/bear/situation shows an explicit "No rest-of-season outlook yet" empty state** — the read runs on
  live in-season news, which isn't wired yet; an honest empty state, not fabricated grades.
- **Rostered-only** — no free-agent / waiver value yet.
- **Data collection runs on a laptop** (~63–71% daily coverage) — not yet moved off-host. → *see appendix:
  data-collection.*

## In flight — Stage B (multi-league)

- **B0–B5 shipped — multi-league is live and VISIBLE.** All 31 demo league-seasons are in the production DB
  (`schedule` league-scoped, `GET /api/leagues` catalog); every read is parameterized on
  `league_id`(+`season`+`viewer_roster_id`), defaulting to the owner's league (byte-identical parity when
  omitted); and the deployed SPA has **league + season selectors** — switching re-renders any of the 12
  lineages with the right "you" highlight and honest per-slice panel gating (market only where computed, ROS
  the empty state everywhere). → *detail + audits: `sessions/v1/`.*
- **NEXT — B6:** full end-to-end verification across every league × season × sample weeks (the per-league
  quirks it shakes out, e.g. B4's playoff-week NULL `matchup_id`). → `projects/v1/` (P0).

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
