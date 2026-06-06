# STATUS

**Last updated:** 2026-05-31
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

IMPORTANT TECH NOTE: The python library nflreadpy is the core data source for this project. It returns polars DataFrames - it is not based on pandas. Any LLM coding instructions working with nflreadpy need to explicitly call out the polars DataFrames so we don't end up with mixed polars/pandas data manipulation syntax.

IMPORTANT TECH NOTE: All data I/O goes through application/data/data_layer.py. Transform scripts and dashboard components read and write via data_layer.py functions only — no script owns its own file paths or parquet logic.

## Today (the current status toward v1)

> most recent build
Built the LeagueLogs market-value fetcher (application/data/fetchers/leaguelogs.py) + a launchd scheduler that snapshots all 5 published profiles (3 redraft, 2 dynasty) daily at 4am ET. Market value is keyed on sleeperPlayerId, so it joins the pipeline with no id mapping; QB/RB/WR/TE only (matches scope). The API serves only "now," so daily snapshots are the only way to build the value time-series — collection started now even though the consuming features (trade analysis) are V4, because history can't be backfilled. Appends to snapshots/leaguelogs/market_values.parquet via data_layer (idempotent dedup on snapshot_date), ~11 MB/year. First snapshot verified (3,409 rows); scheduler tested via launchd (exit 0).

> prior build
Built the first skeleton of the production front-end at application/frontend/ (React + Vite + DuckDB-WASM). It runs SQL directly against season_2025.parquet in the browser (no export step) — the same DuckDB-over-parquet approach that carries to production. First panel: Power Rankings — teams ranked by PPG with a QB/RB/WR/TE positional-strength breakdown, record, consistency badge, and a 0–100 power score. Started as a "design playground" to choose a stack; building in the real stack proved easier than a chat artifact, so React is now the decided front-end and this is its first real slice (not throwaway). (Note: required installing Node via Homebrew.)

> built
    - nflreadpy fetcher
    - sleeper fetcher (includes fetch_players() for Sleeper player registry)
    - nfl_sleeper join (left join, Sleeper-authoritative)
    - audit_join (resolves unknown-position remainders post-join)
    - front-end skeleton (React + Vite + DuckDB-WASM, reads live parquet) — Power Rankings panel
    - leaguelogs fetcher (daily market-value snapshots, all profiles) + launchd 4am-ET scheduler

> not yet built
    >> backend
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - production front-end — React + DuckDB decided; first skeleton built (Power Rankings).
          Remaining: more panels, data-delivery model (client-side DuckDB-WASM vs a Python API), deployment

> helpful historical context
A deferred folder contains earlier work on transcript synthesis. This is intentionally parked.
A deprecated folder contains outdated and untested versions of fetchers for Sleeper, The Odds, FantasyPros and weather. It also contains an outdated and untested scheduler, AI advisor and context generator. The folder is a graveyard of scripts that would need more editing than it would take to rebuild, so they are not considered to be relevant to the project. The folder is .gitignored

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
**DST/K (V1):** DST and kicker positional data is excluded from V1. DSTs are stripped at join time by detecting team abbreviations in the Sleeper matchup data. Kickers are filtered out via the SKILL_POSITIONS filter applied after the join. All V1 transform and dashboard work assumes skill positions only (QB, RB, WR, TE).

**Market value (V1):** LeagueLogs market value is being snapshotted daily now to bank the time-series, but the features that consume it (trade analysis, value-aware rankings) are V4. Any UI that displays it must show the required "Powered by LeagueLogs API" attribution.

**Waiver wire (V1):** Full waiver wire analysis requires querying the full available player pool, not just rostered players. The Sleeper player registry (fetch_players() in sleeper.py, cached at cache/sleeper/players.parquet) now exists and is used by the auditor to resolve unknown-position players at join time. Full waiver wire analysis against the complete available player pool is still V2 scope.

**IR roster overages:** Fantasy managers can use IR slots to carry more than the standard 17 roster spots. This is accurate data — the join reconciliation report handles it correctly and counts whatever Sleeper reports. Expect to see 18-player rosters from 1–2 teams per week during the season, particularly early when injury-stashing is common.

**Zero-stat row context:** Rostered players who did not play in a given week (injured, suspended, inactive, not yet activated) appear in the join output with all stat columns at 0.0. The join correctly includes them, but provides no signal for why they scored 0. Injury status and roster status context would require a separate fetch from Sleeper's injury/status endpoint. This is a known gap — treat 0-stat rows as "rostered, did not contribute" without assuming a specific reason.

## Next single highest-leverage move

Build out the React front-end (application/frontend/): add panels beyond Power Rankings, and add real team names (Sleeper users/rosters fetch). Data-delivery model is decided for V1 — client-side DuckDB-WASM, no server (a server/API was deferred, not ruled out; the src/queries.js data-access layer is the seam to switch later).

## The step after (unconfirmed, subject to change)

Use joins from 2025 season to create power rankings and points consistency analysis

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
