# Product Roadmap

> What's next, in what order, and what's deferred. Constitution document — refer here to find the current phase, the gates between phases, and the open decisions ahead.

**Last reviewed:** 2026-05-09

**Target ship:** NFL kickoff, early September 2026.

---

## Current Phase

**Phase 1 — Strategy Document via Interview**

The strategy doc has been the bottleneck. Earlier work attempted to synthesize it from curated YouTube transcripts (now frozen in `_deferred/synthesis_pipeline/`); v1 instead derives the strategy doc from a structured Claude-driven interview with the user.

**Active gate:** Strategy interview must produce `application/strategy/strategy_redraft.md` before advisor wiring can complete.

---

## V1 Phasing

### Phase 1 — Strategy Document (in progress)

Run a structured Claude interview covering every position (QB, RB, WR, TE, K, DEF) and every decision type (drafting, start/sit, waivers, trades, bye weeks, season-context calls). Output: `application/strategy/strategy_redraft.md`.

**Phase 1 exit criteria:** `strategy_redraft.md` exists, the user has read and edited it, and it covers every decision type the advisor is meant to handle.

### Phase 2 — Data Layer Hardening

The current fetchers (Sleeper, nfl_data_py, Odds API, FantasyPros, weather) work. What's missing for v1:

- **Time-series snapshots** for the data that supports the dashboard's trend views (LeagueLogs market values weekly, projection history, etc.) — currently fetchers overwrite their cache and lose history
- **Advisor output log** at `application/data/advisor_log/` — every advisor call writes `{timestamp, question, input_snapshot, response}` for retrospective review and dashboard surfacing
- **NWS forecast integration** stub or full implementation (decision below)

**Phase 2 entry gate:** Phase 1 complete (strategy doc exists).
**Phase 2 exit criteria:** Snapshots persist on the configured cadence; advisor log writes on every call; weather behavior is decided and either stubbed or implemented.

### Phase 3 — Advisor Wiring

Currently `application/advisor.py` does a context-dump-then-ask pattern with no strategy doc loaded. V1 changes:

1. Load the appropriate strategy doc via `application/shared/leagues.py` (already detects redraft / dynasty / salary_cap)
2. Implement at least one specialized advisor type — **start/sit** is the v1 minimum
3. Pre-filter context per the strategy doc's needs rather than dumping everything
4. Write to the advisor output log on every call
5. Return structured output (not just free-form text)

Waiver, trade, and ad hoc generator advisor types may follow if time allows but are NOT Phase 3 gates.

**Phase 3 exit criteria:** Start/sit advisor runs end-to-end against current week's matchup, references rules from the strategy doc by name in its output, logs the call.

### Phase 4 — Dashboard

Streamlit + Altair dashboard with at minimum:

- Roster status panel (starters, bench, injuries, depth chart positions)
- Last week's matchup result + win/loss
- Market value trend chart for roster players (uses the snapshots from Phase 2)
- Recent advisor outputs (uses the log from Phase 2)
- One analytical view that does its own work (candidates: waiver-target ranking, bye-week stack analysis, projected season trajectory)

The dashboard is a peer product to the advisor, not a viewer for it. At least one panel must surface analytics that don't depend on any advisor call.

**Phase 4 exit criteria:** All panels render with real data; one analytical panel works without invoking the advisor.

### Phase 5 — V1 Validation

Run the advisor against 3-5 historical scenarios from a prior season where the outcome is known. Document API cost per advisor call. Confirm V1 success criteria from `PROJECT_OVERVIEW.md`.

**Phase 5 exit criteria:** All six PROJECT_OVERVIEW V1 success criteria objectively true.

---

## V2 Roadmap

V2 begins with the start of next NFL regular season, when live signal becomes available.

- **Live feedback loop.** Log every advisor recommendation alongside the actual outcome. Surface patterns where advice was wrong.
- **Transcript synthesis pipeline.** Reactivate `_deferred/synthesis_pipeline/`. Run Pass 1 on one transcript first to validate the v2 prompt; then bulk extract; then Pass 2 + Merge + Pass 3. Diff against v1 interview-derived strategy doc; reconcile.
- **Token vocabulary contract.** Lock against `application/data/fetchers/*` after v1 fetchers stabilize.
- **Specialized advisor types** beyond start/sit: waiver, trade, ad hoc prompt generator.
- **NWS weather forecast integration** if not in v1.
- **Recommendation correctness scoring.** Once feedback exists, build a metric that grades the advisor against actual high scorers.

---

## V3+ Ideas

Tracked but not committed. Move to V2 only if they earn their place against more pressing work.

- **Monte Carlo simulations.** Lineup MC, playoff odds MC, trade impact MC. ~100-200 lines of numpy each. Great dashboard features.
- **PFF coverage data integration** if it becomes affordable.
- **Multi-league rollup view** in dashboard (user owns multiple leagues; v1 focuses on one).
- **Auction draft / salary cap format-specific advisors.**
- **Off-season trade evaluation tool** standalone for dynasty managers.
- **In-game live decision support.**

---

## Phase Gates Summary

| Gate | Required Before |
|---|---|
| Strategy doc exists | Phase 3 (advisor wiring) |
| Snapshots + advisor log | Phase 4 (dashboard) |
| Start/sit advisor end-to-end | Phase 5 (validation) |
| All panels render | V1 ship |

---

## Risks (Tracked)

1. **Strategy doc quality is the leverage point.** A vague doc produces a vague advisor. Mitigation: dedicated interview time, user reads + edits before it's considered done.
2. **Out-of-season validation is necessarily synthetic.** No live signal until next season. Mitigation: 3-5 historical test cases. Accept this as a real constraint, not a defect.
3. **Dashboard scope creep.** "One analytical view" can stretch to four. Mitigation: pick one and ship it before adding more.
4. **Advisor still using context-dump pattern past Phase 3.** Easy to leave the existing JSON-dump path in place. Mitigation: explicit Phase 3 exit criterion that pre-filtering happens.
5. **Code reorganization not yet executed.** Doc target structure (`application/ai/`, `application/dashboard/`, `application/data/fetchers/`, etc.) does not match the current flat layout in `application/`. Mitigation: structural reorg is a near-term task; treat docs as forward-pointing during the gap.

---

## Open Questions

These are the active decisions blocking forward progress.

### To resolve before Phase 2 starts

1. **Is NWS weather forecast integration in V1 scope or V2?** Currently the design says yes; the code has a placeholder. Decide: implement fully, stub-only, or strip from v1.
2. **What specific time-series cadences and retention windows are needed?** LeagueLogs market values every 6h kept for 12 weeks? Projections weekly kept indefinitely? Decide before snapshot code is written.
3. **Where does the strategy doc go for non-redraft formats?** v1 focuses on redraft, but `shared/leagues.py` already detects dynasty and salary_cap. Acceptable to ship v1 with only `strategy_redraft.md` and have the dynasty/salary_cap leagues fall through to a generic strategy or refuse to advise? Pick one.

### To resolve before Phase 3

4. **Beyond start/sit, which other advisor types ship in v1?** Default: only start/sit. Document anything that gets added.
5. **Structured output schema for the advisor.** What does start/sit return? Decision + confidence + rules invoked + data referenced? Define before implementation.

### To resolve before Phase 4

6. **Which one analytical view ships first?** Suggestion: market value trend chart for roster players (already implied by Phase 2 snapshots).
7. **How is the dashboard run?** Always-on local Streamlit? Manual launch? Cron-triggered cache refresh + manual UI launch?

### To resolve when convenient

8. **Code reorganization timing.** The proposed `application/{ai,dashboard,data/fetchers,strategy,shared}/` structure is documented but not executed. Schedule the import refactor.
9. **Secrets management beyond `config.py`.** Currently API keys in a gitignored config.py. Consider `.env` + python-dotenv if more keys accumulate.
