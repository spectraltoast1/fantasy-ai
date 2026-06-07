# STATUS

**Last updated:** 2026-06-07 (Team Overview — roster construction)
**Target ship:** NFL kickoff, mid August 2026

---

## Project Management
- my role is CEO/CFO managing the project as a whole, role responsibilities include:
    - owning product direction decisions
    - connecting Claude Chat input/output and Claude Code input/output
- Claude Chat sessions will serve as Product Manager, role responsibilities include:
    - advising on project goals, product direction, and build method
    - writing prompt instructions for Claude Code to execute singular build tasks
    - review the after-build action report from Claude Code
- Claude Code sessions will serve as Software Engineer, role responsibilities include:
    - receive the prompt instruction from the Claude Chat

## Project Overview (what are we working toward)

Winning a redraft fantasy football championship is about more than just collecting all of the best players. It is about how you manage your specific team in your specific league. Knowing when you need to act - or not act - as a team manager is as valuable as knowing which individual players to target or avoid. This tool focuses on helping you navigate your league using real data signals: how your team is trending, where your real weaknesses are, and what your opponents look like. The goal is fewer decisions driven by anxiety or noise, and more decisions made on league-winning signal.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

> Tech non-negotiables (polars-only, all I/O through data_layer.py, client-side
> DuckDB-WASM with src/queries.js as the server seam) live in **CLAUDE.md** and
> **TECHNICAL_ARCHITECTURE.md** — not restated here.

## Today (the current status toward v1)

> **Maintenance (rolling log):** keep only the **most recent build + the 2 prior**
> (3 prose entries max). At closedown, prepend the new build and delete the oldest
> prose entry. Nothing is lost — the cumulative record lives in `> built` below; this
> section is just the recent-detail window. Keeps the doc light for every session.

> most recent build
**Team Overview** sub-view filled in (was a stub). This gives the Team tab its own
identity vs. the League drawer: the League tab is **comparative** ("how do I stack
up?", starters only); the Team tab is **constructive** ("how is THIS team built?")
and looks *inside* one roster — **bench included**, the data the drawer throws away.
The page leads with the answer, then shows the work: **vitals strip** (power rank,
record, points/wk ±std, power score — a deliberate recap that bridges from the League
card) → **"How this team is built"** with three pieces:
- **Star dependence** — single-player exposure (top-1 share of starting points),
  placed on a **league-relative** Balanced↔Star-led spectrum (chose top-1 over top-3:
  top-3 barely varied across teams — ~half for everyone with 8 starters — while top-1
  reads as real character and isn't confounded by lineup churn). Names the star.
- **Auto-surfaced signals** — the headline. **Lineup** calls (a benched player
  out-rating a same-position starter by >10% per game → fix in house, e.g. "Gainwell
  15.9/g > starter Pacheco 6.8/g at RB") and **Holes** (a position whose best current
  option trails the league benchmark by >15% → outside upgrade). Surfaces the insight
  rather than leaving the user to hunt the depth chart. "All set" when clean.
- **Depth chart** — every skill player as a bar by **points per game**, **scaled
  within each position** (so cliffs read clearly and QBs don't squash TEs). Starter
  solid / bench dimmed / departed struck-through with "→ new team". ≤1-game samples
  flagged "1g", hatched, sorted to the bottom, and excluded from signals + bar scale
  (kills the one-big-week distortion).

New seams: queries.js `loadTeamRosters()` (per-team, keyed by roster_id — depth,
star dependence, signals, league per-position benchmarks; current-team resolved via
`arg_max(roster_id, week)` so traded/dropped players are marked departed while still
credited for weeks played). `POS_COLORS` extracted to `posColors.js`, shared by both
panels. Roster set is **cumulative season**, departed players retained. Verified live
across teams; metrics reconcile with a polars prototype (Naber top-1 23%/star-led +
Gainwell lineup signal; Tet Lasso all-set). This covers **2 of the 4 planned Overview
lenses** (roster construction + reliance) plus the signals layer — remaining 2 below.

> earlier build
Tab navigation + the **Team tab** foundation. Introduced the app's first nav layer:
`App.jsx` is now a thin shell owning top-level tab state (**League | Team**); the
Power Rankings content moved into `LeaguePanel.jsx` (owns its own data load). The
former single panel is the **League** tab (Power Rankings today; manager dossiers +
other league overviews to follow). New **Team** tab is a single-team drill-down:
opens on the logged-in user's roster, flips to any team via a switcher, and toggles
two inner sub-tabs — **Overview** (team strengths/weak spots, to be deepened from the
League drawer metrics) and **Players** (per-player real-world metrics + interpretive
viz). Both sub-views are scaffolded/stubbed — content lands in later sessions. New
seam: queries.js `loadTeams()` + `MY_USERNAME` constant (mirrors
config.SLEEPER_USERNAME, matched against teams_2025.parquet `owner_name` to resolve
"your" roster). Identity seam to formalize later: bake an `is_me` flag into the teams
parquet at fetch time so the constant can go away. Verified live (Team tab opens on
"Tet Lasso"/roster 8, switcher + sub-tab toggles work, no console errors).

> earlier build
Power Rankings team drill-down — click a card to open a side drawer that decomposes a
team's record into its three real drivers: roster quality (all-play "true record" — W/L
as if each team played all others every week, luck-stripped, with a Lucky/Earned/Unlucky
tag), manager skill (lineup efficiency vs. the optimal lineup achievable from the roster
= points left on the bench), and luck (the gap between them). Plus a weekly-scoring chart
(bars tinted by beat/below league median, mean line) and two qualitative spectrums:
Consistent↔Volatile (CV of weekly scores) and Balanced↔Hero-led (concentration of
per-position vs-league output), with per-position vs-league bars. Markers are league-
relative. All five metrics aggregate over `week` with no hardcoded count, so they sharpen
automatically as V1.5 appends weeks. Built in 3 passes: (1) roster_positions fetcher +
derive_lineup_slots transform → declared QB1/RB2/WR2/TE1/FLEX2 config (replaces inference,
makes the optimal-lineup calc exact); (2) all-play + efficiency + weekly scoring in the
drawer; (3) the two spectrums. Verified live — every metric reconciles with a polars
prototype (e.g. Bski: all-play 31–5/Earned, 88% eff; DebTheDeb: 19–17/Lucky, balanced).
New seam: queries.js `loadTeamDetails()`; lineup_slots_2025.parquet symlinked into
public/data and registered in db.js.

> built
    - nflreadpy fetcher
    - sleeper fetcher (includes fetch_players() for Sleeper player registry)
    - nfl_sleeper join (left join, Sleeper-authoritative)
    - audit_join (resolves unknown-position remainders post-join)
    - front-end skeleton (React + Vite + DuckDB-WASM, reads live parquet) — Power Rankings panel
    - leaguelogs fetcher (daily market-value snapshots, all profiles) + launchd 4am-ET scheduler
    - sleeper teams fetch (fetch_teams → teams_2025.parquet) — real team names on Power Rankings cards
    - roster_positions fetch + derive_lineup_slots transform — declared starting-lineup config (lineup_slots_2025.parquet)
    - Power Rankings team drill-down drawer — all-play true record, lineup efficiency, weekly scoring, consistency + positional-shape spectrums
    - tab nav shell (League | Team) — App.jsx shell + LeaguePanel/TeamPanel split
    - Team tab foundation — your-team resolver (loadTeams + MY_USERNAME), team switcher, Overview/Players sub-tabs (stubbed)
    - Team Overview sub-view — vitals + "how this team is built": rate-based depth chart, league-relative star dependence, auto-surfaced lineup/hole signals; loadTeamRosters(), shared posColors.js [Overview lenses 1–2 of 4]

> not yet built
    >> backend
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - production front-end — React + DuckDB decided; Power Rankings panel built + deepened
          (team drill-down drawer with all-play, efficiency, weekly scoring, two spectrums).
          Remaining: more panels (per the Build Order below), deployment.

## V1 Definition (current build target)
Team overview, league standings, and matchup review. Powered by nflreadpy and Sleeper data already fetched. Target ship: NFL kickoff, mid-August 2026.

## Version Roadmap (subject to change)
- **V1** — Team overview, league standings, matchup review (frozen at Week 4 of the 2025 NFL season)
- **V1.5** — In-season scheduler: automates weekly data refresh and keeps the dashboard current during an NFL season
- **V2** — Waiver wire analysis (requires Sleeper full player database fetcher)
- **V3** — Start/sit recommendations (requires FantasyPros projections fetcher)
- **V4** — Trade analysis (LeagueLogs market value — data collection started 2026-05-31; features still V4)
- **V5** — AI-powered insights (major update, builds on complete data layer)
- **V6+** — More complex analytics (TBD)

## Known Scope Exclusions
→ Source of truth: **TECHNICAL_ARCHITECTURE.md § Known Scope Exclusions** (DST/K, waiver
wire / full player pool, IR roster overages, zero-stat rows). One product note kept here:
**Market value (V1)** is snapshotted daily now to bank the time-series, but the features
that consume it (trade analysis, value-aware rankings) are V4; any UI showing it must
carry the "Powered by LeagueLogs API" attribution.

## Next single highest-leverage move

The Team Overview now has **lenses 1–2** (roster construction/depth + star dependence)
plus an **auto-surfaced signals** layer (lineup calls + roster holes) and the vitals
strip. The design splits "how is this team built / how is it managed" into **4 lenses**;
two shipped this session. Next sessions, in order:

**Finish the Team Overview — the remaining 2 lenses** (deferred deliberately this
session; each its own slice, no new fetcher needed):
- **Lens 3 — Form / trajectory.** Reframe weekly scoring from *variance* (what the
  League drawer shows) to *direction*: is the team trending up or fading? Rolling form,
  last-3 vs. first-3. Same `season.parquet` per-week data; new shaping in queries.js.
- **Lens 4 — Where you leave points.** Decompose lineup inefficiency (the drawer's one
  "% / pts on bench" number) into an *actionable* read: which weeks, which slots are
  costing points. Builds on the optimal-lineup calc already in `loadTeamDetails()`.

  (Lens 1 = roster construction/depth and lens 2 = star dependence both shipped this
  session, plus the lineup/hole signals layer. The two above are what's left for the
  Overview.)

**Then the Players sub-view** (still a stub) — per-player real-world metrics from
season_2025.parquet (127 cols: passing/rushing/receiving yards, TDs, targets,
target_share, air_yards_share, wopr, EPA…) with visualizations that make the stats
*interpretable*, not a raw table. Needs a new queries.js function (e.g.
`loadTeamPlayers(rosterId)`). Bigger net-new lift (new query + viz design).

All Team-tab work should respect the team switcher already wired in.

## The step after (unconfirmed, subject to change)

Continue down the V1 Dashboard Build Order (standings with trajectory; manager dossiers;
positional strength vs. league average; head-to-head matchup breakdown).

## V1 Dashboard Build Order

Dashboard build structure:
Build first
    - Power rankings league overview
        What it shows: Composite team strength score with positional breakdown (QB/RB/WR/TE) as a detail layer.
        Data needed: nflreadpy weekly stats + Sleeper roster data + weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Points scored + consistency league overview
        What it shows: Average weekly points per team and a consistency signal — stable vs. high-variance output.
        Data needed: Sleeper matchup snapshots only. No join required.

Build second
    - Standings with trajectory lens league overview
        What it shows: Record + points for/against, past strength of schedule, remaining schedule difficulty, historical league baseline for wins needed to reach playoffs.
        Data needed: Sleeper matchup history + Sleeper league schedule + prior season backfill data.
    - Manager dossiers league overview
        What it shows: Static AI-generated profile per manager — waiver tendencies, trade behavior, roster construction patterns, positional preferences.
        Data needed: Sleeper transaction + waiver history. One-time AI synthesis pass per manager, output stored as static JSON or markdown.
    - Positional strength vs. league average team overview
        What it shows: Your team's output by position compared to league average. Identifies tradeable surplus and gaps to address.
        Data needed: weekly data from the season join (nfl_sleeper_weekly_joined transform → season_{season}.parquet).
    - Head-to-head position breakdown matchup overview
        What it shows: Your lineup vs. opponent's lineup by position — where's the edge, where's the risk.
        Data needed: Sleeper current roster + weekly data from the season join (season_{season}.parquet).

Build third
    - Production consistency per player team overview
        What it shows: Week-to-week variance per player. Who's reliable, who's boom/bust.
        Data needed: nflreadpy weekly stats.
    - Key player matchups + narrative read matchup overview
        What it shows: The 1-3 decisive spots in the matchup — who could swing the week, whether you're ahead or at risk.
        Data needed: Sleeper live scoring + nflreadpy historical context. Natural candidate for AI layer in V5.
