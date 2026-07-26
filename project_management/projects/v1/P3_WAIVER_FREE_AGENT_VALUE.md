# Project 3 — Waiver / Free-Agent Value

**Created:** 2026-07-26 · **Status:** Not started · **Track:** Can-be-late (**#1 in the late bucket — target Week 1**) · **Depends on:** P0 (keyed reads), P2 (live rosters) · **Est:** 2–3 sessions

> **What this project does:** give the tool an answer to the most frequent in-season question — **"who
> should I pick up?"** Today the app is **rostered-only**: it values the players on teams, but there is **no
> free-agent pool entity**, so the Players "Available" filter and the League "Waiver Wire strip" were
> deferred. This builds the missing entity and surfaces it. It's the one net-new *functionality* in V1
> (everything else is productizing what exists), which is why it earns a project rather than the backlog.

---

## Context — what exists and what's missing

- The **value engine already exists** (`production_vor` = value over the waiver line). It's computed for
  *rostered* players. The math to value an available player is the same math against the same pool line —
  the gap is that there's **no dataset of available players** to run it over.
- The app deliberately excludes DST/K and the full player pool ("Rostered-only… no free-agent VOR entity").
  DST/K stay out (V1 scope). The full skill-position pool minus rostered players **is** the free-agent pool.
- This depends on **P2's live rosters**: "available" only means something once we know who is currently
  rostered in the live 2026 league.

## The one design question (settle in Session 1)

**How is the "available pool" defined?** Two workable definitions:

- **(a) Complement of rostered** — all NFL skill players (from the join/registry) minus everyone rostered in
  the league. Complete, but large and full of long-tail zero-value names.
- **(b) Sleeper's trending/available list** — lean on Sleeper's own available/trending-adds signal to bound
  the pool to relevant names.

**Recommend (a) as the source of truth, ranked and truncated by value** (show the top-N available by
free-agent VOR), optionally enriched with Sleeper's trending signal as a secondary sort. Confirm with Will —
it affects perf and the surface.

Second question: **rank by what?** Pure `production_vor` is the honest default; a blend with opportunity
(`player_signal`) or market is a nice-to-have. Recommend shipping V1 on `production_vor` + sample-size
gating, and treating any blend as a later refinement.

## Session map

| Session | Goal | Scope | Definition of done |
|---|---|---|---|
| **S1 — Free-agent value entity** | Value the available pool per league/week | New transform (e.g. `compute_free_agent_value.py`) that derives the available pool (decision above) and runs the value engine over it, keyed `league_id` + `as_of_week`; a read endpoint mirroring the Players read | A `free_agent_value` derived dataset + `/api/…` endpoint returns top available players by value for a league/week, sample-size gated |
| **S2 — Surface it** | Make it usable in the UI | Add the **"Available" filter** to the Players tab; add the **Waiver Wire strip** to the League tab; reuse the existing player-row + card components | A manager can see and sort the top available players for their league/week; the strip highlights the best pickups; empty/early-season states degrade cleanly |
| **S3 *(optional)* — Refinement** | Sharper ranking | Blend opportunity/market into the ranking if S1's pure-VOR ranking under-serves; FAAB/waiver-priority context if easy | Only if S1/S2 leave an obvious gap — otherwise fold into post-V1 |

## Risks / notes

- **Pool size / perf** — the full skill pool is large; truncate to top-N by value at the query layer, don't
  ship thousands of rows to the client.
- **Zero-stat / inactive players** — the pool is full of them; the existing "no signal" handling applies,
  and value gating keeps them out of the top of the list.
- **Honesty** — early season, waiver value is noisy; keep the same sample-size language gates the other
  reads use. Don't turn a Week-2 hot pickup into an imperative.
- **DST/K stay out** — don't let the free-agent pool reintroduce them.

## Critical files

New `transforms/compute_free_agent_value.py`; `data/serve/build_db.py` (load the new dataset);
`api/reads.py` + `routes.py` (the endpoint); `frontend/src/Players.jsx` (Available filter) +
`League.jsx` (waiver strip); `queries.js` (a `loadAvailable` seam fn).

## Definition of done (project)

A manager can answer "who should I add?" for their live 2026 league — the top available players by value,
for the current week, gated honestly on sample size — via an Available filter on Players and a waiver strip
on League. **Late-plan:** target Week 1; if the spine is tight this is the safest single thing to slip to
~Week 2, because a user can draft and set lineups without it.
