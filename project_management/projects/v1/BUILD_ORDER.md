# V1 Build Order — Usable 2026 Product for Sleeper PPR / Half-PPR

**Created:** 2026-07-26 · **Owner:** Will (product) + PM/thinking-partner session · **Status:** Proposed build order, pending Will's sign-off.

**Companion docs:** the project briefs `P0`–`P6` (this folder); the post-V1 backlog (`../post-v1/`); `context/STATUS.md` (current state) and `context/ROADMAP.md` (master roadmap + doc organization).

---

## What "V1" means here (locked with Will, 2026-07-26)

A **working, usable, invite-gated self-serve** product for **Sleeper PPR and half-PPR redraft** leagues (1QB and superflex), running on **live 2026 data**, ready for the **whole invited cohort by NFL Week 1** (kickoff ~mid-September; drafts late August — roughly **7 weeks of runway**).

An invited user should be able to: **log in → connect their Sleeper league → and get the full dashboard on their own live 2026 league** — roster / standings / matchups, honest start/sit projection bands, production + market value with a *live* trade lean, a **free-agent / waiver value read**, playoff odds, positional depth, manager dossiers, and a **live 2026 bull/bear/situation AI outlook**.

Four scope decisions Will made that shape this plan:

| # | Decision | Consequence for the build |
|---|---|---|
| 1 | **Invite-gated self-serve** (real login + "connect your Sleeper league", access limited to invitees) | Auth + a self-serve ingestion pipeline are **inside V1**, not deferred. This is the single largest addition vs. the pilot-concierge minimum. |
| 2 | **Week 1 ready for the whole cohort** | Hard-ish deadline ~7 weeks out; everyone onboards around kickoff rather than trickling in. |
| 3 | **Include a basic free-agent / waiver value read** | A new free-agent VOR project is on the critical list, not the backlog. |
| 4 | **Populate the AI outlook live for 2026 at launch** | The live-news ROS read + its consistency/guardrails are inside V1 (with an honesty caveat — see Risk R2). |

**The definition of "done with V1"** (Will's bar): after this, the remaining work is *bug fixes, other scoring formats (standard/custom), dynasty, other platforms (ESPN/Yahoo), and refinements* — **not core functionality**. Everything in the "Post-V1 backlog" section below is deliberately out.

---

## The gap audit — current state vs. V1

**What already exists and is strong (don't rebuild):**

- A deployed, mobile-responsive dashboard on the new server stack (FastAPI + Supabase-Postgres on Fly.io), same-origin, no CORS. Five surfaces: Players, Teams, League, Matchups, Manager Dossier.
- A **measured, deliberately-honest analytics engine**: production VOR, projection consensus bands, playoff-odds Monte Carlo, positional depth, true rank, player signal, manager dossiers. Validated out-of-sample on 270 league-seasons and on 48 never-tune generalization leagues.
- **Half-PPR is engine-ready** — the scoring-scoped substrate is already computed for `{ppr, half} × 2020–2025`, and the scoring dispatcher handles ppr/half/std/custom.
- The store is **multi-league-shaped**: every derived row is keyed by `league_id`, Postgres was chosen so auth is a bolt-on, and the read seam (`queries.js` / `reads.py`) is already the single choke point.

**The five gaps between that and V1:**

1. **It's frozen at 2025 Week 4.** The whole app is a replay of one past season, not a live feed. There is no in-season weekly refresh path (loads today are full DROP+CREATE reloads). *This is the long pole.*
2. **It's one hardcoded league with no login.** League is a Fly server secret; "you" is a hardcoded username. No auth, no user model, no way for a user to bring their own league.
3. **Some of what the user sees isn't real yet.** The trade/market signal is a cross-time proof-of-concept (2026 prices × 2025 rosters — explicitly "not a live call"); the honest engine re-tune isn't surfaced to the UI; the bull/bear/situation grades render empty after the last reload.
4. **No waiver / free-agent value.** The app is rostered-only — it can't answer the most frequent weekly question ("who do I pick up?").
5. **Collection runs on a laptop** (~63–71% daily coverage) — not reliable enough to trust a live market read or a live news-driven AI outlook.

**What is *not* a V1 gap (correctly deferred):** standard/custom scoring, dynasty, other platforms, owner-keyed dossier refinement, and automating the annual re-tune. The engine's constants are tuned through 2025 and are season-invariant, so 2026 needs a *substrate build*, not a re-tune.

---

## The build order — 7 projects

Each project is multiple Claude Code sessions (one brief per session, isolated worktree, 3-commit cap, per `SESSION_GUIDE.md`). Projects are ordered by dependency; the **Track** column shows what can run in parallel.

| # | Project | Track | Depends on | Est. sessions |
|---|---------|-------|-----------|--------------|
| 0 | Finish multi-league & make it visible | **Critical spine** | in flight | 3–4 |
| 1 | Reliable off-laptop data collection | Parallel (start now) | — | 1–2 |
| 2 | Go live on the 2026 season | **Critical spine** | P0, P1 | 4–6 |
| 3 | Waiver / free-agent value | Feature | P0, P2 | 2–3 |
| 4 | Live 2026 AI outlook | Feature | P1, P2 | 2–3 |
| 5 | Accounts + invite-gated self-serve onboarding | **Critical spine** | P0, P2 | 6–9 |
| 6 | Launch hardening + instrumentation | Gate | P2, P5 | 3–5 |

**The critical path to "invited users using it live" is `P0 → P2 → P5`, with P1 as an early parallel prerequisite.** P3, P4, and the instrumentation half of P6 are high-value but the most deferrable if the deadline squeezes (see the Timeline section).

**Each project has its own brief** (scope + context + a session map + DoD, modeled on `MULTI_LEAGUE_STORE_MIGRATION.md`) — this doc guides you project → project; each brief guides you session → session:

- **P0** → `P0_FINISH_MULTI_LEAGUE.md` (a completion pointer to the existing migration doc + the B4/B5/B6 map)
- **P1** → `P1_RELIABLE_COLLECTION.md`
- **P2** → `P2_GO_LIVE_2026.md`
- **P3** → `P3_WAIVER_FREE_AGENT_VALUE.md`
- **P4** → `P4_LIVE_AI_OUTLOOK.md`
- **P5** → `P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`
- **P6** → `P6_LAUNCH_HARDENING.md`

---

## Where this sits

This build order and the `P0`–`P6` briefs are the **`projects/v1/`** roadmap. The session-level docs — the
detailed multi-league plan (`MULTI_LEAGUE_STORE_MIGRATION`), `SESSION_B4`, and the completed Stage-A/B
runbooks — are reference in **`sessions/v1/`**. For how the whole `project_management/` tree is organized, see
**`context/ROADMAP.md`**.

---

## Launch designation — must-have vs can-be-late

**The line:** *Must-have* = an invited user can log in, connect their live 2026 redraft league (1QB or superflex, PPR or half), and get a correct, honest, useful **core dashboard** — safely instrumented. *Can-be-late* = features that enrich that dashboard but that a user gets real value without for the first few weeks, and that can ship in-season without blocking onboarding.

### ✅ Must-have for Week 1 (the spine)

| Capability | Project | Why it blocks launch |
|---|---|---|
| Parameterized reads + viewer-as-data + league/season selector + panel gating | P0 (B4/B5/B6) | Self-serve can't target a user's league or resolve "you" without it. |
| Reliable off-laptop collection | P1 | Pilot go/no-go gate; irreversible lead-time (bank-it-or-lose-it). **Start now.** |
| 2026 preseason substrate (ppr+half, 1QB+SF) | P2 | Nothing renders on 2026 without it. |
| In-season weekly refresh | P2 | This *is* "live" — without it you're still frozen at 2025. |
| Honest projection band surfaced | P2 | Trust requirement; falls out of building 2026 substrate under the honest constants. |
| Auth + user model + per-user data isolation (RLS) | P5 | How invited users get in and stay separated. |
| Connect-your-league self-serve ingestion + invite gating | P5 | The core of "invite-gated self-serve." |
| Graceful reject of out-of-scope leagues | P5 | Real users bring dynasty / custom / exotic — decline honestly, don't break. |
| `served=true` instrumentation + basic ops + e2e verify on real shapes | P6 | Pilot gate: don't onboard before the live path is instrumented. Basic monitoring / cold-start because real people are on it. |

### ⏳ Can-be-late (ships in-season; doesn't block launch)

| Capability | Project | Late-plan |
|---|---|---|
| Waiver / free-agent value | P3 | **#1 in the late bucket — target Week 1.** A user can draft and set lineups without it, so it's the safest single thing to slip to ~Week 2 if the spine is tight. |
| Market value + live trade lean | P2 (market half) | Show the live read once collectors are proven; **gate the panel at launch if not — never show the old cross-time POC.** The SF market/QB-pool check rides here. |
| Live 2026 AI outlook (bull/bear/situation) | P4 | Target early in-season; gate honestly at launch if not ready. **Best candidate to be late** — both for the timeline and because the honesty guardrails (R2) benefit from not rushing. |
| AI cost caps, deeper monitoring/alerting, perf polish | P6 | Rides with the AI outlook and post-launch load. |

**Post-V1 stays out entirely** (standard/custom/dynasty scoring, other platforms, owner-keyed dossiers, annual-retune automation) — that's the "next improvements" state you're aiming for.

> **In one line:** launch = a user on their own live 2026 league with the honest core dashboard, instrumented. The trade lean, waiver read, and AI outlook fill in over the first few weeks.

---

### Project 0 — Finish the multi-league backend and make it visible
*Critical spine · in flight · 3–4 sessions · draws on `MULTI_LEAGUE_STORE_MIGRATION.md` B4–B6*

**Delivers:** the app can serve *any* loaded league/season and correctly render "you" for it — the foundation every self-serve capability sits on.

- **B4 — Parameterize the reads** (drafted, ready to run: `SESSION_B4_PARAMETERIZE_READS.md`). Every endpoint takes an optional `league_id`(+`season`), defaulting to today's league so nothing visibly changes. Also closes two carried-forward items: redeploy so `GET /api/leagues` is finally live, and make the ROS catalog flag honest.
- **B5 — Frontend selectors + identity.** League/season dropdowns; replace the `MY_USERNAME` hardcode with per-league `viewer_roster_id` (viewer-as-data); gate panels that a given league doesn't have; remove the cross-time POC copy. *(1–2 sessions — this is the substantive frontend change.)*
- **B6 — End-to-end verification** across the seeded slate (every league × season × sample weeks).

**Done when:** you can click through the seeded leagues, each renders correctly with the right "you" highlighted, and absent panels gate cleanly instead of breaking.

---

### Project 1 — Reliable off-laptop data collection
*Parallel — start immediately · 1–2 sessions · pilot go/no-go gate (`pilot-2026.md`)*

**Delivers:** ≥95% daily collection coverage from a hosted scheduler instead of the laptop.

- Move the daily collectors (LeagueLogs market values, NFL news RSS) off macOS launchd to a hosted scheduler (GitHub Actions is the lead).
- Add the `metadata.json` fetch-timestamp sidecar the cache is missing "before in-season use."
- Prove ≥95% coverage over a two-week window.

**Why now:** these are "bank it or lose it" time-series — every day the laptop is off is a permanent hole. It also gates the *live* market read (P2) and the *live* AI outlook (P4), so it has the longest lead-time value of anything small. **Start this in parallel with Project 0.**

**Done when:** collectors run unattended, timestamps are recorded, and a two-week coverage check clears 95%.

---

### Project 2 — Go live on the 2026 season
*Critical spine · 4–6 sessions · the un-freeze · this is the long pole*

**Delivers:** the app runs on **live 2026 data** for connected leagues, and everything it shows is true.

- **2026 preseason substrate** (ppr + half): build the 2026 ADP points curve, projection consensus, and ROS band — a re-run of the existing substrate builder for the 2026 season (constants unchanged; this is the manual, one-season version of what `annual-retune.md` later automates).
- **In-season weekly refresh pipeline:** fetch (Sleeper rosters/matchups/transactions, nflreadpy stats, Sleeper projections) → join → transforms → load, on a weekly cadence, per league, advancing the `as_of_week` seam. Move from full DROP+CREATE reloads to a safe, incremental, per-league in-season refresh.
- **Surface the honest engine:** 2026 substrate is built under the current (honest 8c) constants, so the live band is the honest one from day one. *(The 2025 replay keeps the old band unless separately re-derived — low stakes if V1 is live-2026.)*
- **Market read becomes contemporaneous:** on live 2026 data, market value (2026) × rosters (2026) is no longer cross-time — drop the POC flag and make the trade lean a real, live read.

**Done when:** a connected 2026 league shows correct current-week rosters, standings, matchups, honest projection bands, and a live (non-POC) market/trade read, and the weekly refresh runs cleanly.

---

### Project 3 — Waiver / free-agent value
*Feature · 2–3 sessions · the weekly-decision gap Will chose to close*

**Delivers:** the tool answers "who should I add?" — not just "how good is my roster?"

- A **free-agent VOR entity**: value-over-waiver for *unrostered* players, reusing the existing value engine, computed against each league's available pool.
- An **"Available" filter** on the Players tab and a **waiver strip** on the League tab (both were scoped-but-deferred as "no free-agent pool entity in V1" — this builds that entity).

**Done when:** a manager can see the top available players by value for their league and week, gated on sample size like every other read.

---

### Project 4 — Live 2026 AI outlook (bull / bear / situation)
*Feature · 2–3 sessions · draws on `ai-outlook-trust.md` · see Risk R2*

**Delivers:** the bull/bear/situation grades populated from **live 2026 news**, honestly.

- Run the roster-wide `ros_synthesis` AI read on live 2026 news for connected leagues.
- **Consistency:** wire the `news_content_hash` cache + temperature 0 + `prompt_version` so a grade only changes when the news or prompt actually changes.
- **Honesty guardrails (non-negotiable):** anchor the grade to the deterministic band and log divergence; present *situation* as a visibly different trust class than the calibrated bull/bear number; gate the language so a low-confidence read says so. Cost-cap the AI runtime.

**Done when:** grades render for connected leagues, are reproducible week-to-week, and are visibly confidence-gated rather than masquerading as calibrated numbers.

---

### Project 5 — Accounts + invite-gated self-serve onboarding
*Critical spine · 6–9 sessions · the big one · draws on the auth-ready seams throughout*

**Delivers:** an invited user logs in, connects their Sleeper league, and it just works.

- **Auth + user model:** wire Supabase Auth; sessions; a user→league ownership model.
- **Data isolation:** write the RLS policies (today RLS is enabled but empty and the app connects as an owner role that bypasses it) so users only see what they should.
- **Self-serve ingestion:** a "connect your Sleeper league" flow that runs the P2 fetch→join→transform→load pipeline on demand for a user-supplied PPR/half redraft league, registers it (`onboarded_at`, cohort), and surfaces progress.
- **Invite gating:** limit access to invited users.
- **Robustness for leagues you didn't hand-pick** (easy to under-scope): gracefully accept in-scope leagues and **honestly reject out-of-scope ones** (dynasty, un-scoreable custom scoring, exotic shapes) with a clear "not supported yet" message. Handle the reception-tier caveat (two "PPR" leagues can score ~10% of player-weeks differently on bonuses/INT — order stays right, level can drift; be honest about it).

**Done when:** an invited tester who is *not* you can sign up, connect a fresh PPR or half-PPR redraft league, and get a correct live dashboard — and an out-of-scope league is declined gracefully, not broken.

---

### Project 6 — Launch hardening + instrumentation
*Gate · 3–5 sessions · draws on `pilot-2026.md`*

**Delivers:** you can safely onboard the cohort at Week 1 and actually learn from it.

- **Served-decision instrumentation:** write `served=true` ledger rows, a minimal usage log (read-before-lineup-lock), and the decision-touch + divergence metrics. *(Per the pilot's own gate: don't onboard anyone before the live path writes `served=true` rows — an un-instrumented week is unrecoverable.)*
- **End-to-end verification** across real onboarded league shapes × weeks.
- **Ops:** error monitoring, cost caps on the AI runtime, the cache-metadata sidecar, cold-start behavior on Fly's scale-to-zero.

**Done when:** the cohort can be onboarded with monitoring, cost controls, and a real scoreboard for whether the product is helping.

---

## Critical path & the timeline reality-check

```
        ┌── P1 collectors (start now, parallel) ──┐
        │                                          ▼
  P0 multi-league ──► P2 live 2026 season ──► P5 accounts + self-serve ──► onboard cohort
                              │                       │
                              ├──► P3 waiver          └──► P6 hardening + instrumentation
                              └──► P4 live AI outlook
```

**The honest read on ~7 weeks:** the four choices (invite-gated self-serve + live data + waiver + live AI outlook, all correct and trustworthy) add up to roughly **21–33 engineer-sessions**. At a realistic cadence with one brief per session, delivering *all of it* by a hard Week-1 date is aggressive. That's not a reason to cut scope now — it's a reason to **sequence so the spine lands first and the flex is explicit**:

- **Minimum launchable V1 (the spine): P0 → P1 → P2 → P5 → the instrumentation half of P6.** This is "invited users, on their own live 2026 leagues, with the core dashboard, safely instrumented." If only this ships by Week 1, you have a real product.
- **Flex (land by Week 1 if the spine allows, otherwise early in-season): P3 (waiver), P4 (live AI outlook), the ops polish in P6.** These are genuine value, but a manager can use the tool for a few weeks without waiver suggestions or AI grades while you finish them — and shipping them a little late is far better than shipping the spine late or shaky.

My recommendation: commit the spine to Week 1, treat P3/P4 as "Week 1 if we're ahead, Week 2–4 otherwise," and revisit at the end of Project 2 (that's when you'll know your true velocity).

---

## Risks & sparring-partner flags

- **R1 — Scope vs. runway.** Invite-gated self-serve is the right *destination*, but it's the biggest single block of work and it's on the critical path. If any project slips, it should be P3/P4, never P5 or the P0→P2 spine. Guard P5's start date jealously.
- **R2 — The live AI outlook cuts slightly against your own north star.** Your engine's whole thesis is *confidence-honesty* — don't assert what you can't stand behind — and the pilot plan says the AI half "can only earn trust forward, live" and should be "most conservative about what it's allowed to say" until the Week-8 honesty gate. Populating it at launch is fine *if* the P4 guardrails hold: band-anchored, divergence-logged, situation shown as a distinct (lower) trust class, language gated on confidence. Ship the guardrails, not just the grades. I'd rather flag this than quietly build it the easy way.
- **R3 — Superflex is in; watch one read.** V1 accepts **redraft only, 1QB and superflex, PPR/half** (Will, 2026-07-26). Superflex is a roster *shape*, not a scoring change, and the core reads were validated on real SF leagues — so start/sit, roster strength, playoff odds, positional depth, and waiver are fine. The one SF-specific caveat is the **market-VOR QB-pool latent** (a known parking-lot item): verify the SF trade/market read when the market feature lands (it's in the can-be-late bucket anyway). Separately, the **reception-tier caveat** stands: displayed *actuals* are exact (Sleeper scores them), but the projection *center* is scoring-key-approximate for bonus-heavy same-key leagues — acceptable for V1 if surfaced honestly.
- **R4 — AI cost scales with invited leagues.** The ~$85/season figure was for ~10 slices; self-serve grows it. P4/P5 need a cost cap and a batch strategy, not per-request live calls.

---

## Post-V1 backlog — the "next improvements" bucket

This is the state Will wants to *reach* — where everything left is formats, platforms, and refinements, not core functionality. Each already has a scoped design doc:

- **Standard scoring** (`standard-scoring.md`) — engine-complete; a substrate build + a demo/certification slice. ~1–2 sessions.
- **Custom scoring** (`custom-scoring.md`) — the first-down projection bridge recovers ~25 points of coverage; threshold bonuses stay a gated experiment. ~2–4 sessions.
- **Dynasty** (`dynasty.md`) — a different *value model* (multi-year horizon, age curve), the biggest lift; the one place the program actually fits new constants. ~4–6 sessions.
- **Owner-keyed manager profiles** (`owner-keyed-dossiers.md`) — one coherent profile per person across their leagues; small once multi-league is standing, and a nice self-serve win (already protected by B3 carrying `owner_id`). ~1 session.
- **Other platforms** (ESPN / Yahoo import) — new fetchers behind the same seam. Not yet scoped.
- **Annual re-tune automation** (`annual-retune.md`) — turn the offseason calibration into one command. Next offseason, not 2026.
- **The full ROS-trust build** (`ai-outlook-trust.md`) — first-class divergence column, champion/challenger on the prompt — the mature version of what P4 starts.
- **Silent-reads confidence** — give `production_vor`, `player_signal` direction, and `bracket_odds` wins/seed a confidence signal (the law-2 gap the trust report flags).

---

## Immediate next actions

1. **Confirm this build order** (and the spine-vs-flex call) so I can start turning projects into per-session briefs.
2. **Run Project 0 / B4 now** — it's already drafted and ready; it's the first step of the spine and unblocks everything.
3. **Kick off Project 1 (collectors) in parallel** — it has the longest lead-time value and blocks the live market + AI reads.
4. **Scope resolved:** redraft only, 1QB + superflex, PPR/half. The only SF-specific follow-up is verifying the market/QB-pool read when the market feature lands (can-be-late).
