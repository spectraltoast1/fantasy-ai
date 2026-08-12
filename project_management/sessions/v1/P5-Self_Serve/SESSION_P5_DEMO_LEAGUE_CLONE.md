# V1 · The demo league — an anonymized clone — a brief for Code

**2026-08-11 — NO LONGER DEFERRED.** Runs as **S2d** (`SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md`), which owns the ordering and the reason: audit
F3 — the demo shares a lineage with Will's own league, so it needs its own identity **before**
the season selector is removed. Deadline is Gate A. **Part 1 (re-key the data under a new
`league_id` + `lineage_id`) is what S2d needs; the anonymization below can follow.**

**Last reviewed:** 2026-08-05 · **Status:** ready, **DEFERRED by Will 2026-08-05** — S2 goes first ·
**Owner:** Code drives; Will approves the team names and the look. **The LEAGUE name is settled: literally `DEMO League`** (Will, 2026-08-11) — team/manager names stay realistic-invented per below, but the league itself says what it is, so nobody has to wonder whose it is. See S2d.
**Related:** `SESSION_P5_S2_OWNERSHIP_AND_ISOLATION.md` (which consumes `DEMO_LEAGUE_ID`).

> **What this session does:** builds the one league the public can see. It is a clone of LoRP 2025 at
> week 5 with the identities anonymized, carrying real computed data everywhere it exists, under a
> dedicated league id that is **hard-excluded from every engine component**.

> **Why it is not a blocker.** `DEMO_LEAGUE_ID` is a config value. It points at the real LoRP 2025 slice
> today; when this session lands, it gets repointed at the clone. One line. S2 does not wait on this, and
> this does not wait on S2.

> **Deferred deliberately (2026-08-05).** S2 (ownership + isolation) runs first: it is the critical path
> — nobody can be invited until per-user isolation exists — while shipping this clone late costs nothing,
> because the public demo is already LoRP 2025 and `DEMO_LEAGUE_ID` makes the swap a one-line change.
> **S2a owns `DEMO_LEAGUE_ID`.** If this session lands first, report the new id rather than wiring it; if
> S2a lands first, this session does the one-line repoint.
>
> **One thing worth spiking early, separately from the rest:** writing a demo-scoped band file and loading
> it stamped to a single league. It is the only genuinely unproven step here, and it is the one nobody
> wants to discover is hard in September. ~30 minutes retires the risk without spending a session.

## Why a clone at all

Three reasons, in order of weight:

1. **Will is playing to win.** The demo shouldn't be his live team, and the alternative — letting the demo
   roll forward to his 2026 league — exposes exactly the roster he'd rather not publish.
2. **The real LoRP 2025 slice is load-bearing for the engine.** It is in the corpus, the ledger grades
   against it, and `audit_join` repair rows in it are already the subject of their own fix. A demo that
   needs cosmetic freedom must not be a league the engine is measured on.
3. **The demo is the landing page** until Will writes a real one. It has to look finished.

## The settled shape (decided with Will, 2026-08-05 — do not re-derive)

- **Source:** LoRP 2025 (`1182101676608823296`) as it stands at **week 5**.
- **Identity:** a dedicated league id, hardcoded, that cannot be confused with a real Sleeper league.
  **Non-numeric preferred** (e.g. `DEMO-LORP-2025`). Evidence for it being safe: nothing in the Python
  casts `league_id` to `int` (grepped: zero hits), the column is `TEXT` in `schema.sql`, and the frontend
  carries it as an opaque value. **Confirm with a full sweep before committing** — and note the argument
  *for* non-numeric: if something ever does try to cast it, a non-numeric id fails loudly and immediately,
  where a numeric sentinel like `0000` would silently normalise into something else.
- **Anonymised:** team names and owner names rewritten. **Realistic fantasy team names, not "Team 1"** —
  if the demo reads like a mock-up, it answers the trust question the wrong way. Player names stay real;
  they must.
- **Real data everywhere it exists.** Clone the raw Sleeper snapshots under the new id, rewrite names, and
  run the **existing pipeline**. Join, spine, production VOR, true rank, positional depth, playoff odds,
  market, dossiers are all league-keyed and compute themselves. *These are genuine engine outputs on real
  2025 player performance — only the identities are fictional.*
- **The rest-of-season RANGE band: computed honestly, into a demo-only file.** In Postgres
  `ros_player_band` rows carry `league_id` and the read filters on it, so the demo can hold its own band
  rows without touching another league. On disk the band is keyed `(season, scoring_key)` — so
  **compute the 2025 band at today's live constants and write it to a demo-scoped path. NEVER to
  `_ros_player_band_path(2025, ppr)`.** That canonical file is the frozen-corpus artifact the L2 ledger
  was derived from; overwriting it breaks ledger reproducibility. Writing a different file breaks nothing,
  and the numbers are a real output of the real method.
- **The AI outlook panel is populated SYNTHETICALLY.** Will's call, and the reasoning is recorded: P4 is
  scheduled before Week 1 (and has been moved ahead of P3 for this reason), so the demo represents the
  Week-1 product rather than today's. The synthetic grade is **derived, not hand-assigned** — computed
  from the player's own real band centre and VOR rank, so it cannot contradict the honest panel beside it.
  `ros_synthesis` runs on live in-season news that cannot be reconstructed for 2025, so an AI call would
  not produce a real read even if one were paid for; this is an availability fact, not a cost decision.
- **Removal trigger:** when P4 ships, the demo's outlook regenerates for real and the synthetic path is
  **deleted**. Written down here so it does not live forever by default.

## The invariant that makes all of this safe

**The demo league id is hard-excluded from every engine component**, and the exclusion is *gated, not
remembered*. Two halves of one rule:

1. **Synthetic outlook rows may exist ONLY where `league_id == DEMO_LEAGUE_ID`.**
2. **`DEMO_LEAGUE_ID` appears in ZERO engine-side artifacts** — no ledger row, no backtest target, no
   corpus target list, no `check_*` sweep, no re-tune input.

This replaces a per-row "synthetic" marker, deliberately: a marker would live in a loader-generated table
and this project has already lost an out-of-band property that way (`ros_player_band`'s RLS). An identity
boundary lives in config and gate logic, which survives every reload.

**Prove the gate bites.** Add the demo id to a corpus target list on purpose and show the check fail; write
a synthetic row against a real league id and show it refused. A boundary nothing enforces is a convention,
and conventions erode.

## The brief to paste to Code

```
Goal: build the public demo league — an anonymized clone of LoRP 2025 (1182101676608823296) at week 5,
under a dedicated league id excluded from every engine component. Read
sessions/v1/P5-Self_Serve/SESSION_P5_DEMO_LEAGUE_CLONE.md first; the settled shape there is not up for
re-derivation. Also read context/CODING_BIBLE.md and SESSION_GUIDE.md.

1. Pick the demo league id. Non-numeric preferred (e.g. DEMO-LORP-2025). VERIFY IT IS SAFE before
   committing: sweep for any int() cast, numeric comparison, or truthiness check on league_id across
   application/ and the frontend. Report what you found; if anything casts, say so and propose the
   alternative rather than working around it silently.
2. Clone the raw Sleeper snapshots for that league through week 5 under the new id, rewriting team and
   owner names to realistic fantasy team names (Will approves the list). Player ids and points untouched.
3. Run the EXISTING pipeline for the clone — join, spine, market, load. No new transform. Everything
   league-keyed computes itself; nothing about the engine changes.
4. The rest-of-season RANGE band: compute the 2025 band at today's live constants and write it to a
   DEMO-SCOPED path. Do NOT write _ros_player_band_path(2025, <scoring_key>) — that is the frozen-corpus
   artifact the L2 ledger was derived from. Load those rows stamped with the demo league id only. Assert
   afterwards that the canonical 2025 band file is byte-unchanged.
5. The AI outlook: populate synthetically, DERIVED from the player's own real band centre and VOR rank so
   it cannot contradict the honest panel beside it. No AI call. No hand-assigned numbers.
6. The invariant, gated both ways:
   - synthetic outlook rows may exist only where league_id == the demo id;
   - the demo id appears in ZERO engine artifacts — ledger, backtests, corpus target lists, check_*
     sweeps, re-tune inputs.
   Add a check that asserts both. PROVE IT BITES: put the demo id in a corpus target list and show the
   check fail; write a synthetic row against a real league and show it refused.
7. demo_manifest row for the clone with the right panel flags, and set DEMO_LEAGUE_ID to the new id.

Prove it:
1. The demo renders end to end at week 5 with no empty panels other than ones that are empty in
   production for every league.
2. The canonical 2025 band parquet is byte-unchanged; the ledger is untouched; no corpus artifact moved.
3. The 31 corpus slices are still present and still load — nothing was deleted or displaced.
4. The exclusion gate bites, both directions, demonstrated.
5. check_harvest / check_spine / the corpus gates are no more red than they were before this session
   (record the before/after counts, don't assert "green").

Scope guard — does NOT: touch the real LoRP 2025 slice, the frozen corpus, the ledger, or any engine
constant; delete any existing slice; change the visibility predicate (that is S2); build a landing page.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md, close/merge/push. If it touches
application/api/* or the frontend, REDEPLOY and confirm on https://surplusff.com/.
```

## Definition of done

1. The demo league exists under its own id and renders end to end at week 5.
2. Names are anonymized and look real.
3. Every panel that can carry real computed data does — including the rest-of-season range band.
4. The AI outlook is populated, derived from real numbers, and confined to the demo by a gate that bites.
5. The canonical 2025 band, the frozen corpus, and the ledger are provably untouched.
6. The 31 corpus slices are undisturbed.
7. `DEMO_LEAGUE_ID` points at the clone, and repointing it remains one config change.

## Notes / gotchas

- **`compute_demo_slices` and B6's verification assume the 31-slice corpus set.** The demo league must be
  explicitly *outside* that set, or you will get gate failures that look like bugs.
- **Cloning to a synthetic league id is an established pattern here** — `check_harvest` and
  `check_matchup_result` both run the real pipeline against throwaway ids (`_TMP_LEAGUE`). This is not exotic.
- **Advancing the demo past week 5 is a separate, later question.** All 18 raw weeks are banked and
  `weekly_refresh --week N` is proven on prod, so it is operational rather than engineering. Will's stated
  preference is eventually end-of-regular-season (week 14, since the join stops at `playoff_week_start - 1`)
  — but note the default landing view should be **mid-season**, where the playoff race is live and the
  start/sit calls still matter. A demo where every decision is already settled undersells decision support.
