# P5 · S2b — PM audit of the scoped-reads session

**Audited:** 2026-08-11 · **Report:** `SESSION_P5_S2B_REPORT.md` · **Brief:** `SESSION_P5_S2B_SCOPED_READS.md`
**Range:** `fe061a3..0c7c366` (2 commits + merge) · **Verdict: ENDORSED — merge stands, deploy stands.**

**The hole is closed, and I confirmed it from outside rather than from the report.** Four findings below,
all minor; none blocks. **This is the strongest session this project has run** — three of the four defects
it fixed were defects in *my* brief, caught before code was written.

## Verified independently (not read from the report)

1. **The exposure, live, from outside the repo.** `GET https://surplusff.com/api/standings?league_id=
   1207735666645946368` → **404**. Before this session it returned **200 with 4987 bytes** of Trap 2025
   including real managers' Sleeper handles. `…?league_id=9999999999999999999` → **404** as well. The two
   refusals are the same class; the pre-session before-shot is what makes it meaningful.
2. **Byte-identity is now achievable, which it was not under the brief as written.** `_UNKNOWN_LEAGUE`
   is a module constant reached by one `raise` site, and the `/api` middleware sets headers uniformly.
   The brief demanded a byte-identical 404 while the detail still echoed the caller's `league_id` —
   Code caught that, and that Will's own URL check would have visibly failed on it.
3. **The lazy season resolution is real, not claimed.** `current_season_fn()` is reachable *only* on the
   owned-and-exists branch of `authorize_slice`. A signed-out demo request never touches `nfl_state`, and
   **neither refusal branch does** — which is also what keeps the two refusals timing-identical. Correctly
   labelled as call ordering in new code rather than a fix for F6.
4. **The viewer-seat check runs strictly after the visibility decision** — so a bad `viewer_roster_id`
   cannot be used as a roster-existence oracle against a league you cannot see.
5. **The refusal counter increments identically on both branches**, so it is not the asymmetry the
   symmetry rule exists to prevent. (The brief's "count unowned attempts" would have built exactly that.)
6. **`Vary: Authorization` + `Cache-Control: private, no-store`** on every `/api` response — `main.py`.
7. **The eleven dead `settings.league_id()` fallbacks are gone.** The three remaining hits are
   `shared/league_resolver.py`, `data/serve/build_db.py` and a comment — different call sites, correctly
   untouched. This was the time bomb: harmless only while `DEMO_LEAGUE_ID == SLEEPER_LEAGUE_ID`, and S2d
   repoints the demo.
8. **`check_every_route_is_accounted_for` asserts the complement in both directions** — gated set equals
   the named list, *and* every ungated `/api` route is an explicit exemption. Stronger than the brief
   asked for: it catches a *new* unscoped route, not merely a skipped loop iteration.
9. **`check_store_agrees_with_itself`** converts the `teams` ↔ `demo_manifest` measurement into a standing
   gate, in both directions (disagreeing season, and catalogued-but-absent-from-`teams`). The S2a-audit F2
   lesson applied without being told.
10. **`_ALTERED_COLUMNS` in `init_auth_schema.verify()`** — `roster_id` is asserted present, because
    `CREATE TABLE IF NOT EXISTS` never adds a column to an existing table.
11. **`CURRENT_SEASON` is absent from `fly.toml`**, and STATUS records the F6 amplification as a dated,
    known regression rather than burying it.

## Findings

### A — `/api/me`'s docstring now actively misdescribes the security posture (low, but fix it)

`routes.py:92` still reads *"Every OTHER read stays open this session, deliberately… closing and scoping
the reads is one coherent change with one coherent proof, and that is S2."* True when S1 wrote it; **false
as of this merge.** A docstring on the auth endpoint telling the next reader that the reads are open is
the exact class of stale-doc failure `CODING_BIBLE` §7 exists for — and it is worse in code than in a
project doc, because whoever reads it is deciding whether something is protected. One-line fix, S2c.

### B — two commits, not the three the plan specified (low; note for future attribution)

The plan split them (1) seam (2) viewer seat + client (3) check + docs. Shipped as `af88368` + `9a406d7`.
Within the ≤3 rule, but the seam, the fifteen-site fallback removal, the middleware, the schema change and
the viewer seat are all in one commit — which is the attribution risk flagged before the session ran. Not
a defect. It means that if something regresses later, `check_isolation`'s per-check output is the tool,
not `git bisect` on commit boundaries.

### C — audit F2's standing FK assertion is still open; do not mark it done off this measurement

S2b measured the cascade properly (**3 grants → 0 rows, 0 orphans** — more than S2a did, which asserted it
without looking) and asserted the *column*. But nothing asserts the foreign key still carries
`ON DELETE CASCADE`. A measurement is not an invariant — the same lesson this session applied to
`teams`/`demo_manifest`. **Stays S2c #5.**

### D — the Cloudflare carve-out is now concrete, and should be written down while the reason is fresh

`Cache-Control: private, no-store` on **every** `/api` response is the correct default, and it is also
exactly what P6/S4's demo-precompute-plus-edge-cache plan has to undo — deliberately, for the demo only.
That carve-out is the one place a caching change could serve one caller's league to another, so it must be
tied to the same visibility boundary rather than done by path matching. Recorded in the P6/S4 sketch.

## What S2b deliberately did not close (accepted)

- **Audit F6 is now eleven endpoints wide** — an owned-league read during a >12h Sleeper outage still pays
  the 5s timeout. Narrowed (signed-out demo traffic never calls Sleeper) but not fixed, per Will's call.
  **S2c #7**, and the reason S2c should not slip behind S2d.
- No user-facing copy for a rejected token (the sign-out is silent) and no tab-refocus fix — **S2c #4, #9**.
- Two pre-existing client bugs found in passing (`TeamDetail`, `MatchupDetail` spin forever on a legitimate
  `200 null`) — **filed, not smuggled in.** Correct call.
