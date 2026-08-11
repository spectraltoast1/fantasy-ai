# V1 · P5 · Session S2d — The demo clone, then the season selector — SKETCH

**Status: SKETCH.** Runs **after S2b**; may run alongside S2c. Written 2026-08-11.
**Companion:** `SESSION_P5_DEMO_LEAGUE_CLONE.md` — the original clone brief, **no longer deferred**.
It holds the anonymization detail; this sketch adds the ordering and the catalog change.

> **Why this exists as its own session:** audit F3. The catalog groups a league's seasons into one
> lineage entry. **The demo IS LoRP 2025, and LoRP is Will's own lineage** — so when his 2026 league is
> onboarded at Gate A the two fuse into a single switcher entry, and the moment the season selector is
> removed the demo becomes unreachable from his account. Two individually-correct decisions colliding.
> Giving the demo its own identity dissolves it, and has to happen first.

## Part 1 — clone the demo away from Will's league

A **full data clone** of LoRP 2025 at week 5, under its **own `league_id` and its own `lineage_id`**, so
the demo stops being a season of a real, continuing league. Then `DEMO_LEAGUE_ID` repoints at it — one
config value, which is why S2a made it config rather than a table.

- **A catalog row alone is not enough.** The switcher entry comes from `demo_manifest`, but every screen
  reads the underlying data keyed by `league_id`. A row with no data behind it puts a demo in the list
  that renders empty for every visitor — worse than no demo.
- **Hard-exclude it from every engine component, and from the fixture counts.** `compute_demo_slices`,
  `build_demo_manifest`, B6's 31/31 verification and `check_scoped_reload`'s parity oracle all assert
  the 31-slice corpus. A 32nd slice that is not excluded breaks them. This is the part that makes this a
  real session rather than a copy.
- **Deferrable to the clone brief proper:** anonymizing manager names, the synthetic AI outlook (derived
  from real numbers, deleted when P4 ships), and presentation polish. **Re-key now, anonymize later.**
- **A side benefit worth stating:** today every anonymous visitor to surplusff.com is looking at Will's
  real league, with his real Sleeper handle as the highlighted "you". This ends that.

## Part 2 — remove the season selector, flatten the catalog

Only after Part 1. Prior seasons are corpus, not product — there is no user value in browsing last year,
and `season` is **not a SQL filter anywhere** in the read layer (verified: zero hits; a redraft
`league_id` already pins one `(league, season)` slice), so this is a frontend + catalog change that
touches no data path. The **league** and **week** switchers stay.

## Scope guard

No read scoping (S2b). No punch-list items (S2c). **The 31 corpus slices stay in the database** as
engineering fixtures — the clone is a 32nd, not a replacement, and nothing is deleted.

## Open

- Does the clone get its own lineage *name*, or does it read as "League of Random People 2.0" still?
  A demo that looks like somebody's real league is either charming or confusing — Will's call.
- Gate A (Will's 2026 draft, ~late Aug) is the deadline for Part 1, not a nice-to-have.
