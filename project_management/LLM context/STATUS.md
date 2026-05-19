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

## Today (the current status toward v1)

> most recent build
Rebuilt Sleeper fetcher from scratch. application/data/fetchers/sleeper.py writes weekly matchup and transaction snapshots to application/data/snapshots/sleeper/<year>/ and league state cache to application/data/cache/sleeper/. application/shared/league_resolver.py handles username → league ID resolution, keeping the fetcher decoupled from config. 2025 season backfilled.

> built
    - nflreadpy fetcher
    - sleeper fetcher

> not yet built
    >> backend
        - LeagueLogs fetcher
        - The Odds fetcher
        - FantasyPros fetcher
        - weather fetcher
    >> frontend
        - Dash dashboard

> helpful historical context
A deferred folder contains earlier work on transcript synthesis. This is intentionally parked.
A deprecated folder contains outdated and untested versions of fetchers for Sleeper, The Odds, FantasyPros and weather. It also contains an outdated and untested scheduler, AI advisor and context generator. The folder is a graveyard of scripts that would need more editing than it would take to rebuild, so they are not considered to be relevant to the project. The folder is .gitignored

## V1 (the project segment we're currently working toward)

A working dashboard for redraft fantasy football that pulls from reliable data fetchers and visualizes relevant data to support better in-season decisions. No AI component. No other league formats.

## Next single highest-leverage move

Build a transform script at application/data/transforms/weekly_joined.py that joins 2025 nflreadpy player stats with 2025 Sleeper matchup data for a single mid-season week. This is the clean data layer the dashboard will read from. Verify the join output before moving to the dashboard build.

## The step after (unconfirmed, subject to change)

Build a static Claude artifact that reads from the previous join. Goal is a working visualization to validate the data layer and begin visualization concepts before building the full dashboard.
