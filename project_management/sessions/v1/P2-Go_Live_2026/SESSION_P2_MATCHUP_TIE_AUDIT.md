# P2 · Matchup tie / unplayed slate — AUDIT

**Reviewed:** 2026-08-05 · **By:** PM, against the branch `claude/fantasy-ai-matchup-tie-gate-5b1016`
(`5951910`, `741296f`, `b1e8dc0`) — **not yet merged into `main`** — plus an independent recomputation
over the persisted corpus. **Report:** `SESSION_P2_MATCHUP_TIE_REPORT.md` ·
**Finding:** `FINDING_matchup_tie_gate_a.md`.

**Bottom line: endorse, merge, and deploy before the draft.** This is the strongest session the project
has produced. Everything load-bearing reproduces independently: the four corpus ties are real to the
cent, and the served database provably does not move. Two things to fix before this is closed — a
parity claim stated more strongly than its evidence, and **a missing deploy step** that this project
has already been bitten by once. Neither touches the correctness of the fix.

## Verified independently (recomputed, not read)

- **The served DB does not move — confirmed by recomputation, not by trusting the gate.** I re-derived
  the shipped rule (`_matchup.result_expr`, windowed on `["week","matchup_id"]`) against the on-disk
  `matchup_result` for **all 31 demo slices** (plus 6 extra corpus leagues): **5,810 roster-weeks,
  2,905 matchup groups, 0 verdict changes.** Also 0 genuine ties, 0 all-zero groups, 0 null
  `matchup_id`. The claim "none of the four ties is in the demo slate" holds.
- **All four allowlisted corpus ties are real.** Each named group has two rosters at *identical*
  totals matching the allowlist to the cent (141.70 / 142.32 / 165.48 / 144.36), each is the **only**
  tie in its league-season, and each currently sits on disk as a fabricated `W`/`L` — i.e. the bug's
  four real historical victims, correctly identified.
- **`weekly_refresh` has no playoff clamp.** Confirmed by direct inspection: `target_week` comes from
  Sleeper's live `leg` or `--week`, and nothing clamps it to `playoff_week_start - 1`. Code's
  correction stands (see "Where the finding was wrong").
- **The fixtures are built so the old bug cannot pass them.** `_SHAPES["normal"]` deliberately puts the
  higher total on the higher `roster_id`, because the shipped bug degenerated to "lowest roster_id
  wins" and an id-ordered fixture would have passed under it. That is how a gate should be built, and
  it is worth naming as a pattern to repeat.
- **Scope guard held.** 9 code files + 2 docs. No re-join, no corpus rewrite, no Postgres reload, no
  DDL. The `EMPTY_RECORD` mutation guard in `check_projections` (asserting the tally didn't alias the
  shared default) is the kind of detail that says the author was actually thinking.

## Two things to fix before this closes

1. **The read-layer parity claim is overstated, and it is the one proof with no committed artifact.**
   The report says the record-bearing payloads of all five reads across 4 slices × 4 cutoffs
   (80 entries) "diff **byte-identical** between `main` and this branch." That cannot be literally
   true: `load_standings` **gained two keys** — `ties` and `record` — by design, and `Teams.jsx` now
   consumes `record`. The payload contract changed. Separately, `check_matchup_result.py` contains no
   API-payload comparison at all, so unlike every other proof here this one **cannot be re-run by
   anyone**. Restate it as *"record-bearing values identical; the standings payload gains `ties` and
   `record`"*, and either fold a small payload check into the gate or mark it explicitly as a one-off.
   *(Ironic given the session's own care: `_frame_eq` correctly refuses to say "byte-identical" about
   parquet.)*
2. **The handoff never says `fly deploy`.** The change touches `api/reads.py`, `api/calcs.py`,
   `api/projections.py` and `frontend/Teams.jsx` — all served artifacts. The report's Handoff section
   covers only how the *data* reaches Postgres ("no extra step, no operator action"), which is true of
   the join and false of the app. **This project has already shipped a merged-but-undeployed change
   (P0/B3)**, and S1b's brief called that out by name. Merge, push, **deploy**, then confirm on the
   live URL.

## Where the finding was wrong — my errors, and what they cost

Code corrected three things in my finding. All three corrections are right, and one of them mattered.

1. **"Latent" was wrong, and it is the error worth learning from.** I wrote that the null-`matchup_id`
   case was unreachable because `harvest._build_join` clamps to `playoff_week_start - 1`. I verified
   the clamp in the caller I happened to be reading and never enumerated the others. **`weekly_refresh`
   — the live in-season path, the one that actually runs during the season — has no clamp.** Had Code
   deferred it on my say-so, a fabricated result for every non-playing roster would have shipped into
   the season. **Rule: "unreachable" is a claim about every caller. Enumerate them.**
2. **The parity oracle I proposed would have false-failed a correct fix.** I measured 7 league-seasons,
   found zero ties, and wrote that "any diff in a 2020–2025 league is a defect in the fix." At full
   scale there are 4 genuine ties. A blanket-identity gate would have rejected correct behaviour and
   sent someone hunting a bug that wasn't there. **Rule: a sample supports a hypothesis, not an
   invariant. An oracle drawn from a sample is an allowlist, and it carries its sample size.**
3. **"Two consumers" was a grep, not an analysis.** I searched for the string `matchup_result` and
   found two SQL sites. The real surface was three tally bodies across four sites — plus a client-side
   record built in `Teams.jsx`, which never mentions the string at all. **Rule: grep finds the name,
   not the concept.**

Code's fourth correction — that "byte-identical" had to become **value**-identical because polars'
parquet writer is physically non-deterministic (~8% hash flake) — is also right, and is now reusable
knowledge in `_frame_eq`.

## The risk worth naming (not a defect, not a blocker)

**The sim-window change is the largest behavioural surface in this session, and its proof is
structurally weaker than the rest.** `_compute_as_of` now starts the simulated window after the last
week actually *played* rather than after `N`. On the corpus those are the same week for every league —
which is exactly why the 271-league identity proof passes, and also why **it does not exercise the new
behaviour at all.** The first genuinely novel run of that path will be Will's own 2026 league.

That is a reason to look, not a reason to hold. **Add to the Gate-A checklist: on the fresh league,
check `remaining_games` and the playoff odds, not just the standings string.** A wrong window would
show up as a season that is short or long by a week, which is legible on sight.

Separately, the **accepted limitation is honest and correctly bounded**: a real matchup where *both*
rosters score exactly 0.0 reads as ungraded, because `_parse_sleeper_matchups` collapses a null to 0.0.
Zero occurrences in 21,642 corpus groups, and silence is the direction Law 2 asks for.

## Next

1. **Merge → push → `fly deploy` → confirm live.** The missing step above.
2. **Brief the spun-out `audit_join._build_zero_stat_row` task** — 2 repair rows carrying a null
   `matchup_result` and a wrong `is_two_way`, pre-existing, harmless to the served record, and the
   cause of the one standing `check_harvest` FAIL. Small and bounded; worth clearing so the corpus
   gates read all-green before the season.
3. **Then P5/S2** (ownership + per-user isolation), unchanged. Its inbox already carries the S1b
   findings: the targeted-lockout reordering, confirmed-accounts-without-a-human, and the
   `ros_player_band` RLS drift at source.
