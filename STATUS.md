# STATUS

**Last updated:** 2026-05-15
**Target ship:** NFL kickoff, mid August 2026

---

## Project Overview (what are we working toward)

A challenge with managing a fantasy football team is making consistent, data-driven decisions. I often make decisions that are based on emotion or viral consensus, and will make decisions that are inconsistent with a unified strategy. This project aims to gather, package, analyze, and visualize relevant, curated data from reliable sources, so consistent, data-driven decisions are easier to execute.

The project will do this in two ways: a dashboard for user-driven insight and an AI layer for interpretation and decision suggestions. The AI layer is not meant to run the team - it's a consultation, putting data-driven suggestions alongside the user's own analysis to produce better decisions.

## Today (the current status)

Data fetchers exist for Sleeper, nfl_data_py, The Odds API, and FantasyPros. They are untested and likely need editing, but the code exists as a starting point. A weather fetcher exists but needs to be rebuilt - the current data source is historical only and cannot support forecasting. Stadium location data in the current weather fetcher could be preserved, but isn't the only way to get it. A LeagueLogs fetcher does not exist yet.

Everything else - a scheduler, a context compiler, and a prototype advisor - exists as extremely rough, barely-started code. These are not considered active work. The fetchers are the only scripts being carried forward as a foundation.

No dashboard exists.

A deferred folder contains earlier work on transcript synthesis. This is intentionally parked.

## V1 (the project segment we're currently working toward)

A working dashboard for redraft fantasy football that pulls from reliable data fetchers and visualizes relevant data to support better in-season decisions. No AI component. No other league formats.

## Next single highest-leverage move

Pull 2025 season data from nfl_data_py (no API keys required, fully historical) and explore it to identify which metrics are worth tracking and visualizing. This is the foundation for building dashboard panels before live fetchers are needed.
