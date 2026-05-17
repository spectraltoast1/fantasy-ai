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

The nflreadpy fetcher is built and the 2025 season has been backfilled. application/data/fetchers/nfl_stats.py produces player-week parquet snapshots at application/data/snapshots/nflreadpy/ and a player ID mapping table at application/data/cache/player_id_map.parquet. The fetcher has two modes: backfill(year) for full season pulls and refresh() for weekly in-season updates. The player ID map connects nflreadpy's gsis_id to sleeperPlayerId, enabling joins to Sleeper roster data.

Data fetchers exist for Sleeper, The Odds API, and FantasyPros. They are untested and likely need editing, but the code exists as a starting point. A weather fetcher exists but needs to be rebuilt - the current data source is historical only and cannot support forecasting. Stadium location data in the current weather fetcher could be preserved, but isn't the only way to get it. A LeagueLogs fetcher does not exist yet.

No dashboard exists.

A deferred folder contains earlier work on transcript synthesis. This is intentionally parked.
A deprecated folder contains outdated and untested versions of fetchers for Sleeper, The Odds, FantasyPros and weather. It also contains an outdated and untested scheduler, AI advisor and context generator. The folder is a graveyard of scripts that would need more editing than it would take to rebuild. The folder is .gitignored

## V1 (the project segment we're currently working toward)

A working dashboard for redraft fantasy football that pulls from reliable data fetchers and visualizes relevant data to support better in-season decisions. No AI component. No other league formats.

## Next single highest-leverage move

Rebuild the Sleeper fetcher. It needs to provide the league context (rosters, matchups,
waiver pool, standings) that makes the nflreadpy data personally relevant.
The rebuilt fetcher should:

- Write current state to application/data/cache/sleeper/
- Use polars throughout
- Join on sleeperPlayerId as the canonical player key
- Cover: league settings, rosters, weekly matchups, standings, waiver pool
