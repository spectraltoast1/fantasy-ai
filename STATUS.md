# STATUS

**Last updated:** 2026-05-17
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

A challenge with managing a fantasy football team is making consistent, data-driven decisions. I often make decisions that are based on emotion or viral consensus, and will make decisions that are inconsistent with a unified strategy. This project aims to gather, package, analyze, and visualize relevant, curated data from reliable sources, so consistent, data-driven decisions are easier to execute.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

IMPORTANT TECH NOTE: The python library nflreadpy is the core data source for this project. It returns polars DataFrames - it is not based on pandas. Any LLM coding instructions working with nflreadpy need to explicitly call out the polars DataFrames so we don't end up with mixed polars/pandas data manipulation syntax.

## Today (the current status)

Data fetchers exist for Sleeper, The Odds API, and FantasyPros. They are untested and likely need editing, but the code exists as a starting point. A weather fetcher exists but needs to be rebuilt - the current data source is historical only and cannot support forecasting. Stadium location data in the current weather fetcher could be preserved, but isn't the only way to get it. A LeagueLogs fetcher does not exist yet.

A data fetcher exists for nfl_data_py, but further research shows that library has been deprecated. The updated and active library is nflreadpy which is polars based. A new fetcher will need to be built for nflreadpy and the nfl_data_py fetcher can be abandoned.

Everything else - a scheduler, a context compiler, and a prototype advisor - exists as extremely rough, barely-started code. These are not considered active work. The fetchers are the only scripts being carried forward.

No dashboard exists.

A deferred folder contains earlier work on transcript synthesis. This is intentionally parked.

## V1 (the project segment we're currently working toward)

A working dashboard for redraft fantasy football that pulls from reliable data fetchers and visualizes relevant data to support better in-season decisions. No AI component. No other league formats.

## Next single highest-leverage move

Begin building the nflreadpy data layer using 2025 season data. 
The metrics worth tracking have been pre-researched:

Core opportunity metrics (priority):
  - snap_pct, target_share, air_yards_share, route_participation
  - wopr (pre-calculated by nflreadpy)
  - redzone_targets, redzone_carries

Contextual metrics:
  - adot, racr, yac_sh
  - epa_per_play (note: noisy week-to-week, more reliable as rolling average)
  - team_pass_rate, team_rush_rate

Schema requirement: store as player-week rows, not current snapshots.
Trend visualization over rolling 4-6 week windows is the core dashboard 
use case, so longitudinal structure is non-negotiable from the start.

Join key: map nflreadpy gsis_id to sleeperPlayerId via import_ids() 
to connect this data to the Sleeper roster layer.

Skip exploratory investigation - go straight to building the fetch, 
store, and weekly snapshot pipeline.
