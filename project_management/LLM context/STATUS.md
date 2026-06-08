# STATUS

**Last updated:** 2026-06-07 (Team Overview — all 4 lenses complete)
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
**Team Overview — Lens 4 (Where you leave points).** Completes the Overview's 4
lenses. New section turning the League drawer's single "% / pts on bench" number
into an *actionable* manager-skill read. Leads with the season cost (**points left
on the bench** + **lineup efficiency %**, on a league-relative **Leaky↔Optimal**
spectrum — Tet Lasso's 86% *looks* fine but ranks 7th of 10 in raw points left, which
the spectrum exposes), then a **per-week leak chart** (amber columns = points left
each week; a short one = a week you nailed the lineup) and the **biggest specific
misses** (e.g. "W2 started Travis Hunter 5.2 over Rome Odunze 31.8 at WR, −26.6").
Misses are paired within **swap-eligibility classes** (a QB can only displace a QB;
RB/WR/TE are interchangeable via FLEX, labeled FLEX when cross-position) so every
call shown is a *legal* start/sit — the naïve best-gem↔worst-dud pairing produced
nonsense like starting a QB "over" an RB. Pairing stays sum-exact (totals optimal −
actual). "All set" path exists but no team is clean over 4 weeks (lowest leak ~54 pts).

Per the seam decision, the greedy optimal-lineup calc was **extracted to shared
helpers** (`optimalLineup()` returning total + chosen picks, and `expandSlots()`) that
both `loadTeamDetails()` (League drawer) and `loadTeamRosters()` (Team Overview) call —
no duplicated calc, seams stay separate. New shaping: `computeLeakage()` in the Team
seam; `SQL_PLAYER_WEEK` now carries the player name. Verified live across the spread
(Cousin 'Chilling 127 left/75%/Leaky end; Bourne Again 54/87%/Optimal end; Tet Lasso
82.1/86%) — every points-left total, efficiency %, per-week leak, and named miss
reconciles exactly with a polars prototype. **All 4 Overview lenses now shipped.**

> earlier build
**Team Overview — Lens 3 (Form / trajectory).** New **Form** section under the
construction block. Reframes weekly scoring from *variance* (the League drawer's
read) to *direction*: is the team trending up or fading? **Honest with the 4-week
freeze** — STATUS's planned "last-3 vs first-3" would overlap windows, so the split
is **last-half vs first-half** (at 4 weeks: last-2 vs first-2, non-overlapping; the
middle week drops when odd; widens automatically as V1.5 appends weeks). Three
pieces: a **direction headline** (Heating up / Cooling off / Holding steady — the
"steady" threshold is ±6% of the team's *own* avg so a wobble isn't called a surge)
with the recent-half scoring swing (`±pts/wk`) and recent record; a **league-relative
Fading↔Surging spectrum** (marker by the swing vs the league's actual spread); and a
**weekly column chart** — the 4 scores, green = beat the league median that week /
grey = below, recent window shaded so the comparison the delta describes is visible.
The read deliberately separates *direction* from *results*: e.g. Saquarles is steady
on scoring but 0–2 (unlucky), which the copy surfaces rather than hides.

New shaping in queries.js `loadTeamRosters()` only (no new fetcher, no new seam):
`SQL_TEAM_TRAJECTORY` per-week team points + `computeForm()` + `median()`/`mean()`
helpers; the existing `attachSpectrumPos()` places the Fading↔Surging marker. Verified
live across all three states (Team SCOOP surging +46.7/2–0; Saquarles steady/0–2; Tet
Lasso fading −14.1) — every delta, direction, record, and spectrum position reconciles
with a polars prototype. This is **3 of the 4 planned Overview lenses** (construction +
reliance + form); only **Lens 4 (where you leave points)** remains.

> earlier build
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
    - Team Overview — Form / trajectory lens: direction headline (heating up/cooling off/steady), league-relative Fading↔Surging spectrum, weekly column chart (beat/below median); last-half vs first-half scoring swing in loadTeamRosters() [Overview lens 3 of 4]
    - Team Overview — Where-you-leave-points lens: season points-left + efficiency % on a league-relative Leaky↔Optimal spectrum, per-week leak chart, biggest specific start/sit misses (eligibility-aware pairing); shared optimalLineup()/expandSlots() helpers + computeLeakage() [Overview lens 4 of 4 — Overview complete]

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

The Team Overview is **complete — all 4 lenses shipped**: roster construction/depth,
star dependence, form/trajectory, and where-you-leave-points, plus the auto-surfaced
signals layer (lineup calls + roster holes) and the vitals strip. The whole "how is
this team built / how is it managed" view is done. Next:

**The Players sub-view** (still a stub) — per-player real-world metrics from
season_2025.parquet (127 cols: passing/rushing/receiving yards, TDs, targets,
target_share, air_yards_share, wopr, EPA…) with visualizations that make the stats
*interpretable*, not a raw table. Needs a new queries.js function (e.g.
`loadTeamPlayers(rosterId)`). Bigger net-new lift (new query + viz design).

All Team-tab work should respect the team switcher already wired in.

## Refinement backlog — Team Overview (deferred, not blocking)

These refine shipped lenses; pick up alongside or after the Players sub-view.

1. **Reframe Lens 4 (where you leave points) from retrospective → improvement.** Lead
   with process-soundness (lineup efficiency, league-relative). Split season points-left
   into **coachable** (a benched player whose *season rate* beats the starter — reuse the
   Lens-1 lineup-signal logic; a repeatable "start X over Y going forward" tendency) vs
   **variance** (a one-off bench spike, not the manager's fault). Demote the raw
   points-left total to supporting evidence. **Direction only — no predictive/weekly
   start-sit calls** (those depend on projections, V3). Framing target, per the project
   mission ("fewer decisions driven by anxiety or noise"): *"your process is sound; ~N of
   the points left were unpredictable variance; here's the one repeatable fix."*

2. **Switch the Form lens to an EWMA.** Replace the last-half-vs-first-half scoring split
   with an exponentially-weighted moving average (half-life ~2 weeks) for the trend read.
   Works from 2 weeks of data, uses all weeks, no window discontinuity.

3. **Per-panel readiness gate (build the seam now; flip panels on later).** Give every
   panel a self-declared **readiness check** that decides whether it has enough data to
   turn on, else renders a **"too early"** state. Regimes: **structural** (ready at roster
   lock), **point-in-time** (ready week 1, confidence grows with weeks), **trend** (ready
   ~week 3–4). We are frozen at week 4, so all panels currently turn on — the point is to
   build the gate + a designated fallback slot now so trend panels can degrade cleanly and
   **preseason/qualitative content can drop into the "too early" slot later with no rework.**
   Do **not** use backward-looking prior-season carryover as a prior (biased by age/injury/
   scheme/surrounding-talent changes). Early-season value is a forward-looking problem —
   current-year projections/ADP/odds (FantasyPros V3, The Odds unbuilt) or AI (V5);
   preseason content is undesigned, deferred. Cross-cutting: compute early, but calibrate
   the language to the sample size.

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
