# STATUS

**Last updated:** 2026-05-09
**Target ship:** NFL kickoff, early September 2026

---

## Today (what works)

The `application/` folder has a working prototype advisor (`advisor.py`) that pulls Sleeper league + roster + matchup context, dumps it as JSON to a Sonnet API call, and returns a free-form recommendation. Data fetchers exist for Sleeper, nfl_data_py, The Odds API, FantasyPros, and stadium location (with NWS forecast as a stub). A scheduler refreshes them on a configured cadence. League type detection (redraft / dynasty / salary cap) is implemented. League config including Sleeper IDs and API keys is in `application/config.py` (gitignored).

## V1 (what's missing)

1. **Strategy document** — `application/strategy/strategy_redraft.md` does not yet exist. Will be produced via a Claude-driven interview with the user.
2. **Strategy doc not wired into advisor** — `advisor.py` ignores `leagues.py`'s `load_strategy_doc()`. Phase 3 fixes this.
3. **Pre-filtered context** — current advisor dumps full JSON. Phase 3 changes this to a per-question pre-filter.
4. **Specialized advisor types** — start/sit is the v1 minimum. Others (waiver, trade, ad hoc generator) are nice-to-haves.
5. **Time-series snapshots** — fetchers currently overwrite caches; no historical persistence. Phase 2 adds this for the dashboard's trend views.
6. **Advisor output log** — `advisor.py` prints to stdout. Phase 2 adds JSONL logging at `application/data/advisor_log/` for retrospective review and dashboard surfacing.
7. **Dashboard** — Streamlit + Altair, peer product to the AI. Phase 4. Five panels minimum, at least one analytical view that runs without the advisor.
8. **NWS forecast integration** — currently a stub in `weather.py`. Decide V1 vs V2 in Phase 2.
9. **Code reorganization** — target layout is `application/{ai,dashboard,data/fetchers,strategy,shared}/`; current layout is flat. Reorg pending; until done, docs forward-reference the target layout.

## Deferred to V2

- **Transcript synthesis pipeline** — frozen at `_deferred/synthesis_pipeline/`. The four pass prompts, the token vocabulary contract, the raw transcripts, and the v1 truncated strategy MDs are all preserved there. See that folder's `README.md` for resume instructions.
- **Live in-season feedback loop, recommendation correctness scoring, multi-league rollup, Monte Carlo views** — all V2+ per `PRODUCT_ROADMAP.md`.

## Next single highest-leverage move

Run the strategy interview. Block off a weekend. Output: `application/strategy/strategy_redraft.md`. This is the bottleneck for Phase 3 advisor wiring.

## Reading order for new sessions

1. This file
2. `project_management/PROJECT_OVERVIEW.md`
3. `project_management/PRODUCT_ROADMAP.md`
4. `project_management/TECHNICAL_ARCHITECTURE.md`
5. The two most recent entries in `project_management/journal/`
