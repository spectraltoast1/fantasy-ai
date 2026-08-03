# P5 — Signup model: word-of-mouth *discovery* vs *provisioning*

**Written:** 2026-08-02 · **Updated:** 2026-08-02 after Will's decisions · **By:** Code, as input to a PM
correction
**Status:** **Direction settled by Will — a shared access code.** Also settled: **Cohorts A and B collapse**
into word-of-mouth friends at the draft, and Will has already flipped `allow new users to sign up` to **ON**
in the project. What remains is the build (not yet done) and two things the PM must record — see
*Where this leaves us right now* and *Questions*.

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

**Root cause, per Will: the pilot doc is stale and was never kept current.** *"The pilot doc is a little bit
old and hasn't really been updated properly… that's also on me for not directly instructing my PM sessions
to update it as things have changed."* This matters beyond this decision. `pilot-2026.md` is an
**appendix**, and `CODING_BIBLE` §7's anti-bloat discipline is written for `STATUS`/`ARCHITECTURE` — it says
appendices are where depth *goes*, but nothing says who keeps them true. So an appendix can quietly drift
into fiction while still being cited as authority, which is exactly what happened: the cohort gates were
being reasoned from as current when they no longer reflected intent. **Fix the doc as part of this
correction, and give appendices an explicit owner-on-change rule** — otherwise the next session inherits the
same trap from a different file.

## Where this leaves us right now — read this bit

Will has already flipped the project setting. Verified live via `GET /auth/v1/settings`:
**`disable_signup: false`.** So of the two blocks S1 shipped, one is gone:

| block | status | note |
|---|---|---|
| `allow new users to sign up` = OFF | **removed by Will** | the platform now permits account creation |
| `shouldCreateUser: false` (`SignIn.jsx:30`) | **still in place** | the only remaining barrier |
| copy: *"Invite-only while in testing"* | still in place | now inaccurate; change with the build |

**The consequence is worth stating plainly, because it is the exact thing the brief argued against.** The
gate has moved from the platform (where there is no path around it) into **frontend code** (where there is).
The publishable key ships in the public JS bundle by design, so `POST /auth/v1/otp` with
`create_user: true` can be called directly, bypassing the SPA entirely. One line of client code is not a
gate; it is a speed bump with the instructions printed on it.

**How much does that matter today? Modestly, and it is bounded:**

- **Not a data exposure.** Every read is open anyway this session (that's S2's job), and the only thing an
  account currently buys is `/api/me` plus the demo that logged-out visitors already see.
- **No compute exposure yet.** There is no connect-a-league flow until S4, so nobody can queue work on the
  worker regardless.
- **The real exposure is the email budget** — and that is not hypothetical: S1 exhausted the free-tier
  sender with one real user, which locked Will out of his own product for the better part of an hour.
  Anyone able to mint accounts can consume it, and the result is a denial of sign-in for real users.

**So the access code is now load-bearing rather than nice-to-have, and its priority went up.** Until it
ships there is no enforceable gate at all. That is an acceptable interim position — the window is small,
the surface is thin, and nobody is being pointed at the site — but it should be a *known* interim position
rather than a discovered one.

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

**Will's revision (2026-08-02): collapse A and B into one cohort — word-of-mouth friends, onboarding at the
draft.** The access code is what holds C back, and forwarding is explicitly fine: *"If someone forwards it
to someone, it won't break things."* That is coherent, and it is a better fit for how this will actually go
than a two-stage cohort ramp.

**One thing the collapse quietly drops, which the PM should re-decide rather than inherit.** The staging
wasn't only about who — it was about *when*, and there was a gate between the stages:

> *"**Week 4** | Data quality: no scoring-key collision, no anchor-fusion bug, health ≥95%, every Cohort-A
> league resolving. | Fix before trusting any downstream number. **Cohort B stays closed.**"*

Cohort A existed to shake out data-quality bugs on Will's own leagues *before* anyone else saw a number.
Collapsing A into B means friends are looking at the product during exactly the weeks that gate was meant to
protect. That may well be the right trade — they're friends, expectations are calibrated by that, and the
engine's honesty work already withholds what a thin sample can't support (S4a: no posture chip, no clinch
magic number, no trend direction under three weeks). But it *is* a trade, and "we decided the week-4 gate
was worth skipping for friends" is a very different record from "the gate was quietly lost when the cohorts
merged."

**Recommendation:** keep the week-4 data-quality checks as a *checklist Will runs*, even without a cohort
boundary to enforce them. The gate's value was never the boundary — it was the list.

So the design question stands unchanged: **how does Will stop provisioning people without also opening the
door to everyone?**

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

**DECIDED (Will, 2026-08-02): Option 1 — the shared access code.** *"I like the shared access code, I didn't
know that would be an option… If someone forwards it to someone, it won't break things."* Option 2's
identity/entitlement split remains the right structure later, once there is a reason to let strangers hold
accounts.

### What building it involves

Small, and it should land before anyone is pointed at the site — it is currently the only gate there would
be:

- **Where the check goes.** At signup, in the API — *not* in the SPA. That is the whole lesson of the
  current interim state: a client-side check is bypassable because the publishable key is public. Concretely
  the SPA can't be the enforcement point, so either signup routes through an API endpoint that validates the
  code before calling Supabase, or the code gates the *connect* action server-side (Option 2's shape) while
  signup stays open.
- **Where the code lives.** `application/config.py` + a Fly secret is enough for one code — no table, no
  admin UI. A `codes` table only if per-code attribution ("who did this spread through?") is ever wanted.
- **Rotation is the response to a leak**, and should be one config change, not a migration.
- **Copy.** The overlay's *"Invite-only while in testing"* becomes a code field with honest wording.
- **`scripts/invite.py`** loses its reason to exist as an invite tool; keep `--list`, and it is the natural
  home for the `--ban` this model now needs.

**Sequencing note:** this is S1-shaped work arriving after S1 shipped. It is small enough to be a bounded
follow-on session rather than an S2 add-on, and it should not be folded into S2 — S2 is the isolation
session and its proof should stay about isolation.

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

## Settled by Will

1. **Mechanism:** a shared access code (Option 1).
2. **Cohorts:** A and B collapse into word-of-mouth friends at the draft. Forwarding the code is acceptable.
3. **Project setting:** `allow new users to sign up` is already ON.

## Still for the PM

1. **Update `pilot-2026.md` — it is the root cause, not a footnote.** The A/B collapse, the access code, and
   whatever survives of the Cohort-C line all need writing in. Right now the doc says *"Do not open Cohort
   C. Do not market"* alongside a project that permits open signup, and a future session reading it will
   reason from fiction. **Also worth a durable rule: appendices need an owner-on-change, the way STATUS and
   ARCHITECTURE do under CODING_BIBLE §7.** This miscommunication is what an unmaintained appendix costs.
2. **Does the week-4 data-quality gate survive the A/B collapse, as a checklist rather than a boundary?**
   (See the cohort section — recommended yes.)
3. **Correct the P5 brief.** Decision 1 and the S1 session row both encode the provisioning reading; leave
   them and a future session rebuilds the same gate.
4. **When does the access code get built?** It is currently the only gate that would exist, and one line of
   frontend code is standing in for it. Recommend a bounded follow-on session before anyone is pointed at
   the site — explicitly *not* folded into S2.
5. **Is custom SMTP in or out for Week 1?** Unchanged by these decisions and still open. A burst onboard at
   the draft against a free-tier sender is a launch dependency, not a nuisance — S1 exhausted that budget
   with a single user.
6. **What cohort size should the caps be sized for?** S0's caps were costed at 10 / 50 / 200 connected
   leagues; the collapsed cohort is far smaller, which changes how urgent S4's queue really is.
