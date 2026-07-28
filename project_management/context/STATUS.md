# STATUS

**What this is:** Gridiron — a fantasy-football decision-support dashboard whose unit is the manager's
*decision*, not the player. Live, single-league, on the server stack.
**Live at:** https://fantasy-ai-api.fly.dev/ · **Updated:** 2026-07-28
**Read next:** `ARCHITECTURE.md` (how it's built) · `CODING_BIBLE.md` (rules for coding agents) ·
`ROADMAP.md` (where it's going) · `projects/v1/` (the active build).

---

## What's live today

- A deployed, mobile-responsive React SPA on **FastAPI + Supabase Postgres** (Fly.io, same-origin). Five
  surfaces: **Players, Teams, League, Matchups, Manager Dossier**.
- **Multi-league, no auth.** A **league + season selector** switches across the **12 demo lineages**; the
  owner's league (2025) is the default, and the "you" highlight follows the selected league. A week
  selector re-scopes every surface.
- **The app can now advance week by week (P2/S2).** The loader has a **per-league scoped reload** and a
  **weekly-refresh orchestrator** advances one league to the current week without rebuilding the DB —
  proven on prod by advancing the owner's 2025 league Week 4 → 5 (the un-freeze). Ready for live 2026 at
  kickoff. → *see below + `sessions/v1/P2-Go_Live_2026/`.*
- Fully migrated off in-browser DuckDB-WASM (Stage A complete); the client is now a thin API client.

## The engine

- Built, measured, and deliberately made **honest** — i.e. tuned so its stated confidence is truthful rather
  than flattering (the shipped "8c" change: a lower center + a wider two-sided band). Reads it produces:
  production VOR, projection bands, playoff odds (Monte Carlo), positional depth, true rank, player signal,
  market VOR, the ROS bull/bear/situation outlook, and manager dossiers.
- **Current honesty state:** production VOR ranks rest-of-season value well but runs the *level* high (trust
  the order, not the total); the band was re-tuned to ~0.86 coverage; playoff odds and true rank are honest;
  four reads still carry no confidence signal. **The honest band is live in the engine's constants but not
  yet shown in the UI** — the front-end still renders the older band. Note the persisted 2020–2025 *substrate*
  band is likewise stale at the pre-8c `CENTER_SHRINK=1.0` (never rebuilt after 8c shipped); **the new 2026
  substrate is built fresh under the honest `0.8`**, so 2026 is honest from day one. → *see appendix:
  engine-trust, engine-decision-reads.*

## What's real vs. proof-of-concept (current caveats)

- **ROS bull/bear/situation shows an explicit "No rest-of-season outlook yet" empty state** — the read runs on
  live in-season news, which isn't wired yet; an honest empty state, not fabricated grades.
- **Rostered-only** — no free-agent / waiver value yet.
- **Data collection is hosted off-laptop and hardened (P1, ~done).** The two daily collectors run on **GitHub
  Actions → Supabase Storage** (S1, live), with fetch-timestamp sidecars, a same-day **catch-up retry**,
  flush-batched uploads, and a daily **coverage gate that emails on a missed/short day** (S2). The only thing
  left is the **rolling two-week soak proving ≥95%** coverage — **P1 closes when it clears.** → *see appendix:
  data-collection.*

## Stage B — COMPLETE (multi-league)

- **Multi-league is live, visible, and verified end-to-end.** All 31 demo league-seasons (12 lineages) are in
  the production DB (`schedule` league-scoped, `GET /api/leagues` catalog); every read is parameterized on
  `league_id`(+`season`+`viewer_roster_id`), defaulting to the owner's league (byte-identical parity when
  omitted); and the SPA has **league + season + week selectors** with per-league "you" identity and honest
  per-slice panel gating (Market VOR only where computed = lorp-2025; the ROS "no outlook yet" empty state
  everywhere; dossiers rich / "no intel" / "no dossier" per data).
- **B6 swept all 31 slices × sample weeks: 31/31 PASS** on renders + console/network, identity
  (`viewer_roster_id`), panel gating, and week-bounds; parity held; **0 bugs**, two minor observations logged
  (completed-season team-detail PLAYOFF % "—" vs standings 100%; graceful no-"YOUR MATCHUP"-pin at an upcoming
  playoff-bye week). → *full coverage matrix + the two proof screenshots: `sessions/v1/SESSION_B6_VERIFICATION_REPORT.md`.*

## The active roadmap

**V1** = a working, **invite-gated self-serve** product for **Sleeper PPR / half-PPR redraft** (1QB and
superflex), running on **live 2026 data**, ready for the invited cohort by **Week 1**. Seven projects
(P0 finish multi-league → P6 launch hardening); critical-path spine P0 → P2 → P5 — **P0 done; now in P2
(go-live on 2026).** **P2/S1 done:** the 2026 preseason substrate is built offline for ppr+half under the
honest constants (forward positional-prior band; `check_forward_substrate` green); a near-drafts refresh
firms up the thin July ADP. **P2/S2 done (the un-freeze):** the loader gained a **per-league scoped reload**
(`build_db.load_league` — delete+re-COPY one league in one transaction; others + the catalog untouched),
proven **byte-parity-identical to a full reload** and atomic (`serve/check_scoped_reload.py`, green on
prod); a **weekly-refresh orchestrator** (`serve/weekly_refresh.py`: fetch→join→spine→scoped-load, live +
replay, idempotent) advances a league to the current week; proven on prod by advancing the owner's 2025
league **Week 4 → 5** with a clean re-run no-op, ready for live 2026 at kickoff (the proven path is the
loader run **locally against prod**). A `weekly_refresh.yml` GitHub Actions cron ships the cadence (the
serve modules now import without `config.py` — env-first via `settings`, so CI works); the `DATABASE_URL`
repo secret is set. **Open before cloud CI runs green: the derived store must live in the Supabase Storage
bucket** (only the P1 daily collectors write there today) — else run the loader locally on a schedule.
**Next: P2/S3** — surface the honest band in the UI + convert the market read to a live 2026 read.
→ `ROADMAP.md` + `projects/v1/BUILD_ORDER.md` + `sessions/v1/P2-Go_Live_2026/`.

## Deferred / parked (not blocking; each picked up in its project)

- **Silent-reads confidence** — give production VOR, player-signal direction, and playoff wins/seed a
  confidence signal (the current law-2 gap).
- **`*_ppr` naming wart** — the `center_ppr` / `band_ppr` / … columns hold *league* points, not PPR; the
  rename is coupled to a frontend + schema change. → *see appendix: scoring-mechanism.*
- **Superflex market-VOR QB-pool latent** — verify when the live market read lands.
- **Post-V1 features** — other scoring formats, dynasty, other platforms, owner-keyed dossiers, annual
  re-tune → `projects/post-v1/`.
