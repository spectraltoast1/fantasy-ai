# V1 · P5 · Session S2b — Scoping the reads — SKETCH

**Status: SKETCH — next to be fleshed out into a paste-block.** Written 2026-08-11 against what S2a
actually shipped, not against an assumed shape (that is how S1 went wrong).
**Prior:** `SESSION_P5_S2A_OWNERSHIP_AND_CATALOG.md` + `SESSION_P5_S2A_AUDIT.md` (its inbox).
**Project:** `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`.

> **What this session does:** S2a closed **discovery** — you can no longer *find* a league that is not
> yours. This closes **access** — you can no longer *read* one either. Today a caller who already knows
> a `league_id` can still pass it to `/api/players` and get data back. This is the only real security
> exposure on the live site, and it is why S2b runs before the hygiene work in S2c.

## Scope

- **Move `reads.visible` into `slice_params`**, the dependency every read already takes, so all eleven
  per-panel reads inherit the predicate from one place rather than eleven. S2a wrote `visible` to take
  everything it needs and nothing it doesn't, precisely so this is a move and not a rewrite.
- **Route the unauthorized case into the existing unknown-`league_id` 404.** An unowned league returns
  the *same* 404 as a nonexistent one — a 403 confirms existence, and Sleeper ids are guessable.
- **Validate `viewer_roster_id` against a visible slice.** Viewing your own league "as" another manager
  is a feature the dossiers depend on; reaching into a league you cannot see is the bug. Validate the
  slice, not the seat.
- **Move viewer identity from a *league* property to a *user × league* property.**
- **Separate `slice_exists` from the authorization boundary.** It is doing both jobs today by accident,
  because `demo_manifest` happens to contain only the demo set. That coincidence dies at S4.
- **Audit F4, first line of the first commit:** `visible()` converts the row's league id to text but not
  the members of `owned`. Normalise both sides *inside* the function. It is one line, it fails closed
  either way, and this session is exactly the event that makes it reachable — a dozen new call sites.

## Explicitly NOT this session

- **The season selector, and the catalog's lineage→seasons flattening — moved to S2d.** Audit F3: the
  demo *is* LoRP 2025, which shares a lineage with Will's league, so removing the season selector before
  the demo has its own identity makes the demo unreachable from his account. These were only ever
  bundled with S2b because both touch the catalog.
- Anything in S2c. No RLS policy build (settled: isolation is API-layer). No connect flow, jobs table or
  worker. No pipeline, transform, loader or engine constant. No corpus change; no corpus slice deleted.

## The deliverable is one artifact

A committed `application/api/check_isolation.py` running **every read endpoint × {signed-out, owner,
other user}** and asserting the matrix — the `check_signup` / `check_ownership` precedent, so isolation
gets a re-runnable gate rather than a one-off transcript. Two conditions:

1. **A prove-it-bites block.** Run every assertion against the *unscoped* behaviour and require every
   one to fail. An isolation check that has never failed has not been tested. (S2a's managed 8 of 8.)
2. **Name the endpoints explicitly and assert the list against the router's registered routes.** "All
   reads" in a report means "the ones the loop happened to reach"; a hard-coded list checked against the
   router cannot silently skip one.

## The 404 rate limit — SETTLED 2026-08-11 (Will). Count, don't cap.

**No in-app rate limit on the unowned-league 404.** Three reasons, in order of weight:

1. **It would stop the attack nobody would run and miss the one someone would.** Blind enumeration is
   implausible — Sleeper ids are 19-digit snowflakes and ~31 leagues exist on the platform. The realistic
   attacker already knows a specific `league_id` (a leaguemate, a shared URL) and needs **one** request.
   A rate limit never touches them.
2. **It fires at the most expensive possible moment** — after the machine has woken and everything except
   the last query has been paid for. Blocking belongs at the **edge** (Cloudflare, P6/S4), where a refusal
   costs nothing, and the cheaper move still is making the traffic cheap to serve (precompute, P6/S4).
3. **A cap points wherever its key points.** Keyed on something the caller supplies *about someone else*
   it becomes a weapon — that is exactly the S1b bug still open as S2c item 2, where five bad codes lock a
   real address out for an hour. The only safe key here is IP (the caller is unauthenticated by
   definition), and an IP cap is trivially rotated around. **Safe version useless, useful version
   dangerous** — not a trade to take inside the security session.

**Instead, two things that are close to free:**

- **Prove the two 404s are identical in body and headers, not just status code.** That is the claim the
  whole no-enumeration-oracle design rests on and nobody has checked it. **And make the work symmetric** —
  a nonexistent league costs one query, an existing-but-unowned league costs two, which is a timing side
  channel in principle. Impractical to exploit over the internet, but this session is writing that path
  anyway, so it is nearly free to make the uniformity true rather than approximately true.
- **Count unowned-league attempts without acting on them.** A counter has no direction and cannot be
  pointed at anybody. If it ever shows something, a cap can be designed against real numbers instead of
  guessed at — the project's own *report, don't tune* rule.

## Open, to settle when this is written up

- **S2b must mint its own test accounts** — S2a deleted both of its disposable `+tags` to demonstrate the
  cascade. Same pattern: two `+tags`, deleted at the end, Will's real account never in the matrix.
- **The `CURRENT_SEASON` question is S2c's** (see there). If S2c has not yet landed, S2b runs its matrix
  under the override exactly as S2a did — the corpus still tops out at 2025.
