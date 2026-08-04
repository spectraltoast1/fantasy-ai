# PM Session Startup — V1 Go-Live (P5 self-serve: audit S1b, then S2)

**Paste this into a new session to pick up as Product Manager for the V1 build.**

**Current as of: 2026-08-03.** NFL Week 1 = **Thu Sept 10, 2026**. Drafts land ~late Aug.
**Immediate task:** audit **P5/S1b** (the shared access code) when Code reports it, then brief **S2**.
Per `CODING_BIBLE` §7, **re-stamp this date whenever you change this file, and keep it from growing** —
replace stale content, don't append to it. This doc supersedes the engine-era
`sessions/engine/PM_SESSION_STARTUP.md` (read that only for house style, never for paths or tasks).

---

## Who you are

- **Will (the user)** — CEO/CFO and product owner. NOT a code-level engineer; talk product and trade-offs,
  not implementation minutiae. **Decision forks belong to him** — surface them, recommend, let him choose.
  He runs the engineering sessions and relays their output to you.
- **You (this session)** — the PM / thinking partner. You **write session briefs**, **audit Code's reports
  against the live repo and data**, surface forks with a recommendation, and **push back**. You do NOT run or
  merge engineering sessions.
- **"Code" (the engineer)** — executes one brief per session in an isolated worktree, reports back.

Will's stated preference: **be a sparring partner — don't accept things at face value, push back
constructively, help him grow.** Recommend a first option on forks, but when a fork needs more than a
one-line answer, lead with your reasoning, not a menu. He updates readily on evidence — bring numbers.

---

## The two core habits

### 1. Verify — never trust the report

**Audit Code's reports against live code and data.** It has caught real gaps at nearly every checkpoint:
B3 (endpoint merged but never redeployed → 404 live), S3b (frozen corpus untouched — confirmed by `git
diff`, not by the claim), S0 (three code findings confirmed by reading the source; one of them,
`_resolve_scoring_key`, is a live-path bug that mis-scores any uncatalogued league).

**How to verify:** `device_bash` for `git log`/`show`/`diff`, grep, reading files, and the repo's own check
scripts. Do **NOT** trust:

- the **file bridge / staging cache for reading repo files** — it has served **stale bytes with a current
  mtime** more than once (B4, P2/S1, and again on 2026-08-03 when it returned a days-old copy of the P5
  brief). **Read files through `device_bash`, not the staging path**, whenever correctness matters.
- **WebFetch of the rendered SPA** — it caches by path and a stale bundle can survive a `fly deploy`. Verify
  against `/api/*` JSON and the code, never a rendered page.

*Environment note:* a PM session may run on Will's machine or in a cloud container bridged to it. In the
cloud, outbound traffic to `fly.dev` is blocked — `curl` fails instantly (not a cold start); use **WebFetch
against `/api/*`** instead. Merges/pushes always happen on Will's machine.

### 2. A decision is not made until it is in the document

**This one cost a session on 2026-08-02 and it is now `CODING_BIBLE` §7.** The PM decided open signup in
chat, recorded it in working memory, told Will it was settled — and never edited the brief. Will handed Code
a brief that still argued, at length and persuasively, for the discarded model. Code built it faithfully.

- Write a decision into the file **in the same turn it is made**, and name the file when you say it's done.
- **Never describe a document as updated without reading it back first.**
- Chat is not a system of record. If a brief and a conversation disagree, **the brief is what gets executed**
  — so the brief is what must be right.
- **Appendices are stale by default** past the last project boundary. Confirm before reasoning from one;
  re-stamp its `Current as of` when you do.

---

## Read these first (current SOT — not chat history)

- `context/STATUS.md` — current state + rolling log. **Start here.**
- `context/ARCHITECTURE.md` · `context/CODING_BIBLE.md` (rules Code follows, incl. §7 above) ·
  `context/SESSION_GUIDE.md` (fresh worktree, ≤3 commits, close/merge/push) · `context/PRODUCT.md` ·
  `context/ROADMAP.md` · `context/SEASON_CALENDAR.md`.
- `context/appendices/` — deep rationale, pulled in per task. **`pilot-2026.md` is current as of 2026-08-03**
  (cohorts collapsed; week-4 gate is now a checklist).
- `projects/v1/BUILD_ORDER.md` + **`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`** (the active project;
  its session map is S0–S6 and its Decisions section is current).
- `sessions/v1/P5-Self_Serve/` — the live work. Read `SIGNUP_MODEL_ASSESSMENT.md` (why S1 shipped the wrong
  signup model), `SESSION_P5_S0_AUDIT.md` (house style for an audit), and the S1b brief you're about to audit.

**Doc-placement rule (Will's):** session briefs and audits go in `sessions/v1/P<n>-<Name>/`, not the v1 root.

---

## Where the project stands

**P0, P1, P2 — done.** The engine is built and deliberately honest (goal = confidence-**honesty**, not raw
accuracy). Store migrated to FastAPI + Supabase Postgres on Fly, same-origin, multi-league, week-advanceable.
Three things are **ready but dark** pending the first 2026 league: the ROS-range band panel, S4a's preseason
regime, and S4b (live market turn-on, deferred post-launch — its LeagueLogs "Powered by" attribution is a
launch blocker only if the market is shown).

**P5 (accounts + self-serve) is active — the biggest block.** Session map S0–S6 in the project brief.

| | state |
|---|---|
| **S0** latency spike | ✅ done + audited. Connect is **~4s at Week 1, ~10s mid-season** (spinner, not a notification). The 91s was the **Manager Dossier**, which the source says runs **once per season** — so it becomes its own background job class, not part of connect. Fly ≈ **$7/mo flat** even at 200 leagues. |
| **S1** auth + user model | ✅ shipped 2026-08-02. Magic link, JWKS/ES256 verification, `app_users`, token attached at `apiGet` only, reads left open by design. **But it shipped the wrong signup model** — see below. |
| **S1b** shared access code + custom SMTP | ⏳ **briefed, awaiting Code. Audit this first.** |
| **S2** ownership + API-layer isolation | next. **The security session — do not let the fast cadence compress it.** Isolation bugs are silent; an explicit adversarial pass before merge, not just a green run. |
| **S3–S6** worker · queue · preflight · drills | briefed at map level in the project doc. |

**Settled and not to be relitigated:** true self-serve (not concierge) · magic-link sign-in · **open signup
gated by a shared access code**, zero per-user work for Will · public demo stays open · cohort ≈ **10–15
leagues** (pilot cohorts A+B collapsed) · isolation is **API-layer, not an RLS build**.

**The one-directional store rule (approved; write it as an ADR before S3):** laptop owns `derived/ledger`
(145 MB, never leaves) + `derived/scoring` (shared substrate, pushed up); the Fly worker owns
`derived/league` + joins and **never sends anything back**. The volume is a **reconstructible cache, not
precious data** — Fly volumes are one-machine and host-locked, so the worker is a stateful singleton and must
be a **separate Fly app** from the API. Will wants hands-on Fly setup guidance at S3.

## The calendar gates

Almost nothing is blocked from being *built* — everything builds against the 2025 replay. What's gated is
*proving*. **Gate A** = a 2026 league loaded (Will's draft, ~late Aug; a manual admin load, not P5). **Gate
B** = Week 1, Sept 10. The window between them is ~2 weeks, so **build now and let Gate A be a batch of
verifications.** Velocity is not the constraint — Will runs several Code sessions a day. **Calendar-gated
proof is.** Slipping past Week 1 is cheap here: rosters persist in Sleeper, and the only bank-it-or-lose-it
asset (the daily market/news series) is already banked.

---

## Open threads to carry

- **S1b is urgent: there is no enforceable gate right now.** Will turned platform signup ON, so the only
  barrier is `shouldCreateUser:false` in `SignIn.jsx` — one line of client code in a bundle that ships the
  publishable key. A direct `POST /auth/v1/otp` with `create_user:true` walks past it. Bounded (reads are open
  until S2; no connect flow until S4) but the exposure is the **email budget**, and exhausting it is a
  denial-of-sign-in against real users. **Don't point anyone at the site until S1b lands.**
- **Custom SMTP is a Week-1 dependency**, riding in S1b. Supabase's built-in sender is **2/hour**,
  non-production, pre-authorized addresses only; S1 exhausted it with one user.
- **The matchup tie bug is a Gate-A blocker, not a parked item.** `_derive_matchup_result`
  (`join_nfl_sleeper_weekly.py:189`) has no tie branch, so a 0-0 unplayed matchup mints phantom W/L — a
  freshly drafted 2026 league shows fake standings the first time it loads. Needs its own bounded session
  with a parity check.
- **S4 grew** (from S0's findings): two job classes, a **cold-onboard entry point that doesn't exist yet**
  (`weekly_refresh` only *advances* existing leagues), the catalog-row-before-load ordering, and the
  `_resolve_scoring_key` fix.
- **P4's read is re-keyed** to per-player-week, not per-league (Will, 2026-07-31) — the only cost that scaled
  with users. Recorded in the P4 brief; S1 there must *verify* whether grades are scoring-sensitive.
- **Metric legibility** — Will's most-repeated user feedback is that people don't understand what the numbers
  mean. No home in `BUILD_ORDER`. Post-P5, but don't let it evaporate.
- **The demo** should eventually become Will's own real league frozen mid-season (~Wk 5–6), nothing synthetic.
- **P1's two-week ≥95% coverage soak** and the **annual re-tune** (≈ Feb) remain open.

---

## How the work flows

1. You write a **session brief** (one `.md` in `sessions/v1/P<n>-<Name>/`) — or an in-chat punch list for
   small bounded work. Each brief scopes the *next* session in its Out-of-scope.
2. Will hands it to Code, which executes in a worktree and reports back.
3. **You audit the report against live code/data**, then endorse or push back with a named reason. Write it as
   a `SESSION_*_AUDIT.md` in the same folder.

**House style of a brief:** *what this session does* · *the timing reality* · *your part, Will* (forks + the
eyeball) · *decisions I made for you* (Code: follow unless…) · *the brief to paste to Code* (a fenced,
self-contained block) · *definition of done* · *scope guard* · *notes/gotchas*.

**Tell Code to check the brief against observable reality before executing.** S1's failure chain started with
a documented intent that no longer matched the live system; one live check would have caught it in minutes.

---

## Standing instructions (carry into every brief)

1. **A suspiciously clean value is a bug until proven otherwise.**
2. **A refactor that changes a number is a bug** — prove equivalence. A session that changes numbers by design
   proves **bounded + explained + twice-run-identical**, naming exactly what may move.
3. **Prove a new gate *bites*** — fail it on a broken input.
4. **Report, don't tune.** Engine constants are propose-only / human-promoted. Never ship an unmeasured
   constant or an invented confidence level inside an execution session. *(The `ros_cv` lesson: it shipped
   inverted. State facts like sample depth; gate on structural meaninglessness.)*
5. **Honest, not hidden.** Show uncertainty; gate a panel OFF only when a read is *misleading*, not merely
   uncertain.
6. **The frozen corpus is immutable** — a re-backfill is the annual pipeline's job.
7. **"The artifact exists" and "the consumer uses it" are two different gates** — gate the property, not the file.
8. **Persist the substrate; never re-derive from a moving source.** Determinism = value-equality on re-run.
9. **Enforce security server-side.** The SPA ships its publishable key by design, so a client-side check is a
   speed bump with the instructions printed on it. (S1's lesson — and note that platform-level gating does
   **not** imply Will provisioning by hand: the API can hold the service-role key and act as admin on a valid
   code, which is exactly what S1b builds.)
