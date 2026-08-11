# V1 · P5 · Session S2c — Punch list — SKETCH

**Status: SKETCH.** Runs **after S2b**. Written 2026-08-11.
**Sources:** the S1b audit (items 1–3) and `SESSION_P5_S2A_AUDIT.md` (items 4–8).

> **What this session does:** closes the loops. Nothing here is a security hole — it is the set of
> places where a rule is written down but not enforced, proven but not re-provable, or handled but not
> observable. Cheap individually; they are batched because they share a shape.

## The list

1. **`--emit` must emit `ALTER TABLE … ENABLE ROW LEVEL SECURITY`** for every table it names, so an
   out-of-band property stops being destroyed by the next full load; `ros_player_band` then regains RLS.
   *Prove it bites: drop RLS by hand, re-run `--emit`/`--load`, show it comes back.*
2. **Reorder the signup rate limit** — validate the access code **before** the email counter, so five
   garbage-code attempts against a known address cannot lock a real person out of sign-in for an hour.
   Keep counting failures by email and IP; never let a *correct* code be refused by the email counter.
3. **Confirmed accounts with nobody behind them** — `signup.py` creates with `email_confirm: true` before
   the link is known to send, so a mailer failure leaves a confirmed account. Decide whether the
   ownership model cares; if it does not, write down that it does not.
4. **(Audit F1 — the TOKEN half moved to S2b 2026-08-11; what remains here is the COPY.)** S2b puts
   `optional_user` on `slice_params`, so *every* read can 401 on a bad token, not just the catalog —
   S2b therefore carries the mechanical fix (`apiGet` clears the token and retries once anonymously).
   **Left here:** the user-facing error state. `/api/leagues` can now 401 or 503, and
   `App.jsx` only `console.error`s — leaving a permanent "Loading…" for signed-in users on an expired
   token, a deleted account, or a Supabase outage. On 401/503: **drop the token, retry once anonymously,
   show the demo, and flash an error** — "We couldn't restore your session — showing the public demo",
   plus a sign-in prompt. **Only when a token was actually present and rejected**; a visitor who was
   never signed in is in a normal state, not an error state. Give the surfaces a real error state
   instead of an infinite "Loading…".
5. **(Audit F2) Prove the cascade, and prove the constraint took.** `init_auth_schema.verify()` checks
   column names, types and nullability — not constraints — and `CREATE TABLE IF NOT EXISTS` means a
   table that already existed in another shape keeps its old ones silently. Add: assert the FK on
   `user_leagues.user_id` exists with `ON DELETE CASCADE`, and count orphans. S2a's cascade claim rested
   on deleting two accounts and never looking afterwards.
6. **(Audit F5) A refusal alone proves nothing.** `check_anonymous_is_not_denied` passes on 401 **or**
   503, so on a machine with no Supabase config it goes green having never verified a token. Record
   which code came back; make the `--live` run require 401 specifically.
7. **(Audit F6 — SETTLED 2026-08-11, Will. ELEVEN TIMES BIGGER since S2b — this is why S2c must not
   slip behind S2d.)** `slice_params` now resolves the season on every *owned* read, so a >12h Sleeper
   outage costs 5s per read instead of one. S2b narrowed it (signed-out demo traffic and both refusal
   branches never call Sleeper) but did not fix it. On one 256mb machine the real risk is **worker
   exhaustion**, not slow pages — blocked workers are shared across visitors, so it can take the public
   demo down. Stopgap until this lands: set `CURRENT_SEASON` in `fly.toml` (`context/OPERATIONS.md`).
   **Own the current season; take Sleeper out of the request path.** Derive it locally — *season = year, or year − 1 before August 1* — and delete
   `nfl_state_cache`, the 5s timeout, the stale-value path and the fail-closed branch, none of which
   have anything to do left once the network call is gone. **Sleeper moves to a check**, not the hot
   path: `check_ownership` asks once and fails loudly if the derived value disagrees.
   - **Why local, not a hardcoded constant refreshed annually:** a constant that gets forgotten silently
     hides every user's newly-onboarded league during preseason — the worst week for that failure.
   - **Why August 1, deliberately a few days earlier than Sleeper's actual flip:** the error directions
     are not symmetric. Flipping early drops last season's league from a catalog slightly sooner than
     necessary, which nobody notices in August. Flipping late hides the league they *just connected*.
     Lead, don't lag.
   - **The `CURRENT_SEASON` override stays**, and is promoted from a temporary proof hack to the
     permanent manual lever — which is most of what F7 was worried about.
8. **(Audit F7) Make the resolved season observable.** Publish season + source on the existing
   unauthenticated health endpoint. Sleeper publishes the season publicly, so this leaks nothing, and it
   turns a startup log line read once into a property anyone can check at any time.

9. **(PM, 2026-08-11) A tab refocus resets the user's place.** `supabase-js` reports a tab REFOCUS as
   `SIGNED_IN`, and S2a treats `SIGNED_IN` as an identity change — so it clears the slice and refetches
   the catalog. Switch tabs and come back and your league, week and drill-down are reset to the default.
   Found in the analytics module's own comments, where the GA session worked around the *symptom* (a
   duplicate pageview) rather than the cause. **Fix: bump `identityEpoch` only when the user id actually
   changes**, not on every `SIGNED_IN` event — which also retires the pageview de-dupe. Same file and
   same effect as item 4; do them together. Invisible today only because almost nobody is signed in.

10. **(S2b audit A) `/api/me`'s docstring misdescribes the security posture.** `routes.py:92` still says
   "Every OTHER read stays open this session, deliberately" — true when S1 wrote it, **false since S2b
   merged**. A docstring on the auth endpoint telling the next reader the reads are open is worse than the
   same drift in a project doc, because whoever reads it is deciding whether something is protected.

## Scope guard

No read scoping (S2b). No catalog shape or season-selector change (S2d). No engine, transform, loader or
corpus change. Items 1–3 and 5–8 are independent of each other; item 4 is frontend-only.
