# Owner-Keyed Manager Profiles — deferred refinement (scope doc)

**Last reviewed:** 2026-07-25 · **Status:** **Future work — deferred** (postponed from Stage B; do after the
multi-league demo is standing). Not a ready-to-run runbook yet; this captures the problem, the design, and the
ripple so a future session brief can be built from it cleanly.

> **In one line:** make a manager dossier a property of the **manager (a person)**, computed once per
> `(owner_id, season)`, and *attached* to whatever team that person holds in a given league — instead of being
> re-synthesized per team-slot. Plus: make the **positional-lean** sub-read scoring-aware.

## Why (the motivation)
A dossier describes a *manager's* tendencies — FAAB aggression, trade frequency, waiver churn, positional lean,
roster construction. Those are properties of the person, not of a team-slot in one league. Today the same person
appearing in more than one league (or being read across leagues) can get **separate write-ups from the same
underlying signal**, which is redundant and can read inconsistently (the AI wording differs per slot).

## What's already true (so we don't overstate the change)
The current pipeline is **already half-way there** — this is a finish-the-thought refinement, not a rebuild:
- `compute_manager_features.py` reads a **cross-league** activity feed and **groups by `owner_id`** — so the
  deterministic features (the signal the AI writes from) are **person-scoped**, pooled across every league the
  manager is in that season, with `n_leagues`/`n_seasons`/`n_transactions` depth counts.
- It's computed **per season**, which is **leakage-safe** for the season-replay: a manager's 2022 dossier is built
  from 2022 activity only, never their future behavior. **Keep this** — per-season is correct, not a limitation.
- `is_primary` today just flags "this is you" (`owner_name == config.SLEEPER_USERNAME`), not a canonical-owner
  marker.

**The one real gap:** the *storage/entity* grain. `write_manager_dossiers.py` emits one dossier **per (season,
league, roster)** and calls the AI **per row** — so the person-scoped signal gets re-synthesized and stored per
team-slot rather than once per person.

## Target design
1. **One profile per `(owner_id, season)`.** Compute the qualitative dossier **once per person per season** (from
   their pooled cross-league features), keyed on `owner_id`. The AI (Haiku) is called **once per owner×season**,
   not once per roster — dedupe + guaranteed consistency.
2. **Attach, don't duplicate.** A league's Teams view resolves `roster_id → owner_id` (the `teams` table already
   carries `owner_id`) → the owner's profile. The dossier is *joined in*, not stored per roster.
3. **Scoring-aware positional lean (endorsed).** Keep the **core** tendencies (aggressive/passive, trader/holder,
   waiver behavior) **pooled across scoring formats** — pooling gives more signal and rescues thin managers from
   "no intel." Make **only the positional-lean sub-read scoring-aware** (RB-weighted in standard, WR-weighted in
   PPR), since that's the read that genuinely shifts with format. **Do not** key the whole dossier on
   `scoring_key` — that fragments the sample for little benefit.
4. **Preserve leakage-safety + the `is_zero_signal` graceful-degrade.** Per-season stays; thin managers still
   self-gate to the "no intel" state.

## The ripple (why it's deferred, not trivial)
This touches three layers, which is exactly why it shouldn't be jammed into the heavy B2 compute:
- **Compute** — `write_manager_dossiers.py` keys output on `(owner_id, season)`, dedupes the AI call per owner;
  the positional-lean feature in `_manager.py` becomes scoring-aware.
- **Schema / load (B3)** — the `manager_dossiers` (or a new `manager_profiles`) table keys on `owner_id` + season;
  the app resolves roster→owner. **Prerequisite already teed up:** B3's schema should carry `owner_id` as a
  first-class key from the start, so this refinement is a small read-swap later, **not a data migration**.
- **Frontend read (B5+)** — `loadManagerDossier(rosterId)` / the `/api/managers/{rosterId}` endpoint resolves the
  roster to its owner and returns the owner's profile. Small change behind the existing `queries.js` seam; views
  untouched.

## Prerequisite to protect now (don't wait for this session)
When **B3** builds the load + schema, **carry `owner_id` as a first-class key on the dossier data** (it's already
in the manifest/teams). That single choice keeps this refinement a small future step. Flagged so B3 doesn't lock
in roster-only keying.

## Non-goals / decisions held
- **Not** keying the whole dossier by `scoring_key` (only the positional sub-read is scoring-aware).
- **Not** changing the per-season, leakage-safe cadence (a manager's profile is still as-of the season being
  viewed — no cross-season lookahead).
- **Not** a demo blocker — the demo's corpus managers are almost all in a single league each, so per-team and
  per-owner come out nearly identical there; the win is product-grade (a real user with many leagues gets **one**
  coherent manager profile, not per-league fragments).

## Eventual session shape (when picked up)
Roughly a one-worktree session: (1) `write_manager_dossiers` → owner×season keying + per-owner AI dedupe +
scoring-aware positional lean in `_manager`; (2) the read side (endpoint resolves roster→owner→profile; schema
keyed on `owner_id`); (3) verify against the demo (a manager in >1 slice shows one consistent profile; thin
managers still degrade gracefully; per-season/leakage-safety intact) + STATUS. Best done **after** the multi-league
demo is live so it can be validated against real multi-league manager overlap.
