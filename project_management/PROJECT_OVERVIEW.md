## Fantasy Football Assistant - Product Overview

**Last reviewed:** 2026-05-15

## What This Is
A personal fantasy football decision support tool built around two components that share a common data layer: a visualization dashboard and an AI advisor.

The dashboard pulls from multiple data sources to surface relevant metrics in one place and computes analytical views on top of that data - trend lines, rate of change, correlations between participation metrics and fantasy output. The goal is to make consistent, data-driven decisions easier to execute without manual research across multiple sites.

The AI advisor applies a strategy document to generate recommendations against the same data the dashboard displays. The strategy document captures the user's fantasy football philosophy in a structured, reusable format. The advisor is a consultation, not automation - the user analyzes the same data, forms their own view, and makes the final call.

## Data Layer
Both components read from the same fetchers and cached data. Sources include Sleeper (league, roster, matchups), nfl_data_py (production stats, snap counts, target share, advanced metrics), The Odds API (Vegas lines, player props), FantasyPros (projections, news), and LeagueLogs (market values). Time-series snapshots enable trend views during the active season.

## Versioning
V1: Redraft only. Dashboard is the primary deliverable - working and useful before NFL kickoff September 2026. AI advisor is a stretch goal.

V2: AI advisor fully wired with strategy document. Live in-season feedback loop.

V3+: Monte Carlo simulations, multi-league support, deeper advanced metrics.