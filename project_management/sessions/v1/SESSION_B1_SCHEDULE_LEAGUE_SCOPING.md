# Stage B — Session B1: League-scope the schedule (+ keyability sweep) — a brief for Code

**Last reviewed:** 2026-07-25 · **Status:** Ready to run · **Owner:** Code (Will operates + eyeballs)

> **What this session does:** fix a real multi-league correctness bug before any multi-league data lands. The
> `schedule` derived dataset is stored **league-agnostically** but holds **league-specific** `roster_id` /
> `matchup_id` — so two leagues in the same season **collide** (one overwrites the other). This session
> league-scopes the schedule (mirroring how the other derived data is already keyed), then sweeps the remaining
> derived datasets to confirm each is **league-keyable** so the B3 multi-slice loader can attribute every row to
> the right league. Store-agnostic; runs in parallel with B0. Stage B of `MULTI_LEAGUE_STORE_MIGRATION.md` (B1).
>
> **Confirmed bug (verified against the live store):** `snapshots/derived/schedule_2025.parquet` sits at the
> **league-agnostic** `derived/` root (not under `derived/league/<id>/` like the other reads) and its columns are
> just `week, roster_id, matchup_id` — **no `league_id`.** `export_schedule.py` writes `schedule_<season>.parquet`
> per season; a second same-season league would clobber it.

## Your part, Will (~5 minutes)
Kick off the brief below. At the end, glance at Code's check: two same-season leagues now produce **separate**
schedules that don't overwrite each other, and your existing (`is_mine`) schedule still resolves to the same
pairings as before. That's your "looks right." Nothing a user sees changes.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **Mirror the existing league-scoping.** The other derived reads live at `derived/league/<league_id>/…`; the
   schedule should join that pattern — write **`derived/league/<league_id>/schedule_<season>.parquet`** *and*
   carry a **`league_id` column** on the rows (path + column, matching how the loader keys everything else). Route
   the read/write through `data_layer.py` (add/adjust `read_schedule`/`write_schedule` so nothing constructs the
   path by hand — the non-negotiable I/O rule).
2. **Parity guard — don't break the live app.** The deployed Stage-A app runs off the Postgres DB, which was
   loaded from the *published* `frontend/public/data/schedule_2025.parquet`. This session changes where the
   **pipeline writes** the schedule; it must **not** change what the live app serves. Regenerate the `is_mine`
   schedule in the new league-scoped location and **prove it's identical** (same `week → matchup_id → roster_id`
   pairings) to today's. Do **not** reload the production DB here (B3 owns the multi-slice reload).
3. **Keyability sweep (the second half of B1).** Confirm **every** derived dataset the B3 loader will ingest is
   attributable to a league — either it lives under `derived/league/<id>/` **or** it carries a `league_id` column
   (scoring-keyed substrate like `projection_consensus` is keyed by `scoring_key`×`season`, which is fine — note
   it as scoring-scoped, not a bug). Produce a short table: dataset → how it's keyed (league-path / league_id col /
   scoring-key) → OK or needs-fix. Fix any that are neither (schedule is the known one; flag any others rather
   than silently fixing beyond scope).
4. **No compute, no new leagues, no frontend.** This is a keying/correctness fix on the pipeline, not a data
   backfill (that's B2) and not a loader/endpoint change (B3+).

## The brief to paste to Code

```
Goal: Stage B, Session B1 (MULTI_LEAGUE_STORE_MIGRATION.md B1) — league-scope the schedule so multi-league data
can't collide, then verify every derived dataset is league-keyable for the B3 loader. Store-agnostic; parallel
with B0. Do NOT backfill new leagues (B2) or touch the loader/endpoints/frontend (B3+).

Confirmed bug: snapshots/derived/schedule_<season>.parquet is league-AGNOSTIC (sits at derived/ root, columns
week/roster_id/matchup_id, no league_id) but holds league-specific roster_id/matchup_id — two same-season
leagues overwrite each other. Everything else lives at derived/league/<league_id>/.

Do:
1. Fix export_schedule.py to write derived/league/<league_id>/schedule_<season>.parquet AND add a league_id
   column to the rows. Route it through data_layer.py (read_schedule/write_schedule — no hand-built paths; the
   I/O-through-data_layer rule). Keep season in the filename as today.
2. Regenerate the is_mine schedule in the new location and PROVE it matches today's pairings exactly (same
   week→matchup_id→roster_id set). Do NOT reload the production Postgres DB (B3 owns the multi-slice reload) —
   the live app must be unaffected this session.
3. Keyability sweep: for every derived dataset the B3 loader will ingest, confirm it's attributable to a league
   (under derived/league/<id>/, or carries league_id, or is legitimately scoring-keyed by scoring_key×season).
   Output a table: dataset → keying → OK/needs-fix. Fix only the schedule (the known bug); FLAG anything else
   that's neither league- nor scoring-keyed rather than fixing out of scope.

Follow SESSION_GUIDE: fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md, close/merge,
push. Verify: (a) export_schedule for two same-season leagues writes two separate files that don't collide;
(b) the is_mine schedule is byte-for-byte equivalent pairings to before; (c) the keyability table shows every
loader-ingested dataset is attributable. Show me the two-league no-collision proof and the keyability table.

Close: update STATUS.md (B1 done: schedule league-scoped + keyability confirmed; next = B2 compute, which needs
B0's slate + this fix). Merge/push.
```

## Definition of done
✅ `schedule` is written league-scoped (`derived/league/<id>/schedule_<season>.parquet` + `league_id` column) via
`data_layer`; two same-season leagues no longer collide (proven); the `is_mine` schedule reproduces today's exact
pairings and the **live app is untouched** (no DB reload); a keyability table confirms every derived dataset the
B3 loader ingests is league- or scoring-attributable (schedule fixed, any other gaps flagged); `STATUS.md`
updated. No backfill, no loader/endpoint/frontend changes.

## Notes / gotchas
- **The whole point is B2/B3 safety** — once ~29 slices (some sharing a season) get computed and loaded, a
  league-agnostic schedule would silently mix pairings between leagues. Fixing it now, before the data exists, is
  cheap; after, it's a corruption hunt.
- **Parity is the guard rail** — the `is_mine` schedule must come out identical. If regeneration moves a single
  pairing, stop and diff; the fix is a relocation + a stamped column, not a recompute of the pairings.
- **Coordinate the handoff to B3** — B1 changes where the schedule lives; the B3 loader must read it from the new
  league-scoped path. Note that explicitly in STATUS so B3 doesn't look in the old spot.
- **Don't over-reach in the sweep** — if a dataset other than schedule turns out un-keyable, FLAG it for its own
  fix; don't expand this session into a broad re-keying (keeps the 3-commit cap honest).
