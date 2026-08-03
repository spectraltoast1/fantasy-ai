# P5 — Signup model: word-of-mouth *discovery* vs *provisioning*

**Written:** 2026-08-02 · **By:** Code, at Will's request, as input to a PM correction
**Status:** Assessment + recommendation. **Nothing has been changed.** S1 is shipped and live as built.

---

## The miscommunication, precisely

**What the brief encoded (S1 decision 1):** word of mouth means *Will provisions each person*. "A person
asks Will, Will runs one command; word-of-mouth still works, the mouth just routes through him, and nobody
can consume pipeline compute without his knowledge." Public signup off; `scripts/invite.py` the only way in.

**What Will actually meant:** word of mouth describes **discovery** — *"I won't be trying to drive unknown
people to my corner of the internet"* — not provisioning. *"I don't plan to be manually adding people as
users, I plan for them to self-serve signing up."*

Same three words, two different systems. The brief's version puts Will in the loop per user; Will's version
puts him in the loop for *promotion* only.

**Will's reason, stated:** *"to limit the touching I have to do to onboard users."* That is the operative
constraint, and it is worth stating as a design criterion rather than a preference: **per-user manual work
must be zero.** Note what it does *not* say — it isn't a wish for the door to be open to everyone, it's a
refusal to be the bottleneck. Those come apart, and the gap between them is where the workable answer lives.

## What is built, and exactly what blocks the intent

Self-serve signup is blocked in two independent places, both deliberate, both trivial to reverse:

| block | location | measured effect |
|---|---|---|
| `allow new users to sign up` = OFF | Supabase project setting | new address → **422 `otp_disabled`** |
| `shouldCreateUser: false` | `frontend/src/SignIn.jsx:30` | the SPA cannot mint an account even if the project allowed it |

Plus one line of copy: *"Invite-only while in testing"* in the sign-in overlay.

**Nothing else in S1 is affected.** Token verification, `/api/me`, `app_users`, the `apiGet` token seam, the
build plumbing, the parity guarantee — all independent of signup policy. **This is a policy correction, not
rework.** Whichever option below is chosen, the auth mechanism stands.

---

## The conflict this surfaces — and it is the important part

`context/appendices/pilot-2026.md` defines a **staged cohort plan with hard gates**:

- **Cohort A** — Will's own leagues, 2–3, onboard at the draft
- **Cohort B** — *"friendly humans"*, ~4–6 people, **week 4+, gated**
- **Cohort C** — **strangers — "held back"**, and only after the Week-8 engine gate:
  *"**Do not open Cohort C. Do not market.** The gate exists to be obeyed."*

**Fully open signup opens Cohort C on day one** — not by intent, but by mechanism. The invite gate is
currently the thing that makes "held back" *enforceable* rather than aspirational.

The honest nuance: if Will only ever tells people he knows, the people who arrive *are* Cohort B, and
nothing bad happens. The risk isn't Will's behaviour — it's that an open door has **no failure mode**. One
forwarded link, one screenshot, one search-indexed URL, and strangers are in a product whose own pilot plan
says they must not be, during the weeks the engine is still being certified.

So the question is not *"open or gated?"* It is: **how does Will stop provisioning people without also
opening the door to everyone?**

---

## Three options

Scored against both constraints — Will's (**zero per-user touch**) and the pilot plan's (**Cohort C stays
closed**):

| | per-user touch | Cohort C held back | build cost |
|---|---|---|---|
| **1 · shared access code** | **zero** | **yes** | small |
| 2 · open signup, entitlement to connect | zero *if* auto-granted; provisioning if not | no | medium |
| 3 · fully open | zero | **no** | none |

Only Option 1 satisfies both. Options 1 and 3 tie on Will's constraint — so the code costs him **nothing he
was trying to avoid**, and buys back the gate for free.

### Option 1 — A shared access code (RECOMMENDED)

Signup is self-serve; completing it requires a code Will hands out **verbally, by text, however he's already
talking to the person**. He never touches a keyboard per user.

- ✅ **Matches the stated model literally** — the thing passed *by mouth* is the code.
- ✅ **Cohort C stays closed.** A stranger who finds the URL cannot get in; the pilot gate stays obeyed.
- ✅ **No per-user work.** One code serves everyone he tells.
- ✅ **Forwardable — and that's fine.** A friend passing it to a league-mate *is* word of mouth. If it
  spreads further than intended, rotate it; that's a one-line change, not a cleanup.
- ✅ **Revocable and observable** — a leak has a response, which "open" does not.
- ⚠️ Small build: a code check at signup. Cheapest form is a single value in config + a check in the
  connect/signup path; a `codes` table only if you want per-code attribution later.

The brief actually considered this — *"(b) invite codes … the natural upgrade when being in the loop stops
being cheap"* — and deferred it. Given what Will actually meant, **it isn't an upgrade, it's the correct
starting point.**

### Option 2 — Open signup, gate the expensive action instead

Anyone can create an account and browse. **Connecting a league** — the thing that costs compute — is gated
on a per-user entitlement.

- ✅ Zero signup friction; discovery is genuinely open.
- ✅ **`app_users.cohort` already exists** for exactly this (shipped in S1, nullable, no policy yet).
- ✅ Cleanly separates *identity* from *entitlement*, which is the right long-term shape.
- ❌ **Doesn't satisfy the pilot gate**: strangers are in the product, seeing the demo, with accounts. Cohort
  C is open in every sense that matters for "do not market."
- ❌ Junk accounts accumulate with no natural bound.
- ⚠️ If the entitlement is granted by Will per user, this is provisioning again in a different coat.

### Option 3 — Fully open

Flip both switches, rely entirely on caps and preflight.

- ✅ Two-line change; nothing to build.
- ❌ **Directly violates the pilot plan's stated gate**, during the certification window.
- ❌ The email budget becomes an abuse surface: exhausting the free-tier sender is a denial-of-sign-in
  against real users, and costs an attacker nothing.
- ❌ The connect endpoint hits **Sleeper** per request; abuse risks the project's standing with a free API
  the entire product depends on.
- ❌ Removes the compute protection with nothing yet built to replace it (S0's caps and S5's preflight are
  designed but not implemented).

**Recommendation: Option 1 now, Option 2's shape later.** The code satisfies Will's model and the pilot plan
simultaneously, today, with the least building. Option 2's identity/entitlement split is the right structure
once there's a reason to let strangers hold accounts — which by the pilot's own schedule is after the Week-8
gate.

---

## What must move regardless of the option chosen

Even Option 1 changes the risk profile, because Will is no longer personally aware of every user:

1. **S0's compute caps stop being prudence.** The per-user connected-league cap and the daily global job
   ceiling become the only thing bounding a single volume-pinned worker. They must ship *with* S4's queue,
   not after it.
2. **S5's preflight becomes the first line of defence**, not a politeness feature — it is what stops junk
   leagues before they consume a job slot.
3. **S2's adversarial pass becomes non-negotiable.** "Another user's league" stops meaning "someone Will
   personally admitted."
4. **Email deliverability becomes user-facing.** Today a failed magic link is a friend Will can text. Under
   self-serve it is a silently lost user with no support channel. Combined with `BUILD_ORDER`'s plan that
   *"everyone onboards around kickoff rather than trickling in"*, **custom SMTP moves from "log it" to a
   Week-1 dependency.** S1 exhausted the free-tier budget with one real user in the system.
5. **A kill switch.** With any self-serve path, Will needs to disable an account. `scripts/invite.py`'s
   `--list` is the seed; a `--ban` is small and belongs with whichever option ships.

## What does NOT change

The whole S1 mechanism: ES256/JWKS verification, `/api/me`, `app_users`, the single-seam token attach, the
build-arg plumbing, byte-parity on the twelve reads. Also unaffected: the public demo staying open to
logged-out visitors, which is orthogonal and already settled.

One thing that *disappears* under any self-serve option: the **invited-but-unconfirmed** gotcha (an invited
account reads as a signup to GoTrue until the invite is accepted once). That's a wrinkle of the invite flow
specifically, and it caused the dead end Will hit while testing.

## Questions the PM should settle

1. **Does self-serve signup override the pilot plan's Cohort-C gate, or must it coexist with it?** This is
   the actual fork; everything else follows from it. If the gate stands, Option 1. If Will judges the gate
   obsolete, that is a deliberate revision to `pilot-2026.md` and should be recorded as one — not absorbed
   silently by a config change.
2. **What is the intended cohort size at Week 1?** The caps in S0's report were sized against 10 / 50 / 200
   connected leagues; the pilot plan says ~5 people. Those imply very different urgency for S4's queue.
3. **Is custom SMTP in or out for Week 1?** Self-serve plus a burst onboard makes the free-tier sender a
   launch dependency rather than a nuisance.
4. **Who owns the correction to the P5 brief?** Decision 1 and the S1 row both encode the provisioning
   reading and should be rewritten so a future session doesn't rebuild the same gate.
