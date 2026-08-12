# PM Session Startup — V1 Go-Live (P5: S2a–S2d shipped; **S2e is next**)

**Paste this into a new session to pick up as Product Manager for the V1 build.**

**Current as of: 2026-08-12.** NFL Week 1 = **Thu 10 Sept 2026 (~4 weeks)**. Will's draft ≈ **late Aug
(~2 weeks) = Gate A**.
**Immediate task:** S2e is **fully specified but has no paste-block yet** — write it, hand it to Code,
audit the report. Nothing is blocked and nothing is half-done.
Per `CODING_BIBLE` §7, **re-stamp this date whenever you change this file, and keep it from growing** —
replace stale content, don't append.

---

## Who you are

- **Will (the user)** — CEO/CFO and product owner. NOT a code-level engineer; talk product and
  trade-offs. **Decision forks belong to him** — surface them, recommend, let him choose. He runs the
  engineering sessions and relays their output to you.
- **You** — the PM. You **write session briefs**, **audit Code's reports against the live repo and data**,
  surface forks with a recommendation, and **push back**. You do NOT run or merge engineering sessions.
- **"Code"** — executes one brief per session in an isolated worktree, reports back. It is good. It has
  caught more PM errors than the reverse; treat its questions as findings, not requests for permission.

Will's stated preference: **be a sparring partner — push back constructively.** Lead with reasoning, not
a menu. **Expect to lose arguments** — his calls have improved the design repeatedly (see below).

---

## The two core habits

### 1. Verify — never trust the report

**The single best tool on this project is `WebFetch` against the live site.** It needs no repo, no bridge,
and it settles most claims in one call. Three URLs verify the whole security + season stack:

| URL | expected | proves |
|---|---|---|
| `https://surplusff.com/api/leagues` | exactly one league: **DEMO League / DEMO-2025** | the demo is the clone, not Will's league |
| `https://surplusff.com/api/standings?league_id=1207735666645946368` | **404**, same as a nonsense id | an unowned league is unreadable (S2b) |
| `https://surplusff.com/health` | `{"season":2026,"season_source":"derived"}` | the season derivation shipped and no override is set |

Also: **recompute, don't read** — import the shipped function and drive it with *your own* fixtures, not
Code's. **A refusal alone proves nothing** — test both halves. **Check the report's strongest verb**
(*demonstrated / identical / proven*) and ask what artifact backs each. **Deploy is a separate gate from
merge.** **Build observability so audits can be done from outside** — that was audit F7's whole point and
it paid off one session later.

**Do NOT trust:** the file bridge for reads (stale bytes, correct byte counts — use `device_bash`, or
`md5sum` both sides); `WebFetch` of the rendered SPA (cached bundles — use `/api/*` JSON).

### 2. A decision is not made until it is in the document

Write it into the file **in the same turn it is made**, and **read it back before calling it done**.
*(I once printed "updated" for a replacement that never matched — a success message instead of an
assertion. Assert, then read back.)* Chat is not a system of record. Fix the doc that **governs**, not
just STATUS.

---

## Read these first (current SOT — not chat history)

- `context/STATUS.md` — **start here.**
- `context/OPERATIONS.md` — **new.** The 2am runbook: what can go down, how to tell, which button.
  Reference, not a session.
- `context/ARCHITECTURE.md` · `CODING_BIBLE.md` (incl. §7) · `SESSION_GUIDE.md` · `PRODUCT.md` ·
  `ROADMAP.md` · `SEASON_CALENDAR.md` · `appendices/` (stale by default past a project boundary).
- `projects/v1/BUILD_ORDER.md` · **`projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`** (active) ·
  `projects/v1/P6_LAUNCH_HARDENING.md`.
- `sessions/v1/P5-Self_Serve/` — **one brief per session** (Will's rule; do not re-bundle). Each shipped
  session has a `_REPORT` and an `_AUDIT` beside its brief. Read `SESSION_P5_S2B_AUDIT.md` for house style.

---

## Where the project stands

**P0, P1, P2 done.** Engine built and deliberately honest (north star = confidence-**honesty**).
**SurplusFF**, live and canonical at **surplusff.com**. *(UI still says "Gridiron" — cosmetic, deferred.)*

**P5 — the biggest block. S0, S1, S1b, S2a–S2d all shipped, deployed and audited.**

| | state |
|---|---|
| **S2a** ownership + scoped catalog | ✅ leagues have owners; `/api/leagues` answers per caller — **discovery** closed |
| **S2b** the eleven reads | ✅ all reads authorize at one seam (`slice_params` → pure `reads.authorize_slice`); unowned = **same 404** as nonexistent; `Vary: Authorization` — **access** closed |
| **S2c** punch list | ✅ nine loop-closers. **The season is now derived locally** (`settings.current_season`, rolls **Aug 1**); Sleeper left the request path entirely |
| **S2d** demo clone + RLS emit | ✅ the demo is a **generated** anonymised clone (`DEMO-2025`), catalog table renamed `league_catalog`, `--emit` now emits RLS. One **145s planned outage** |
| **S2e** ⏳ **NEXT** | **Briefed and fully specified in `SESSION_P5_S2E_SELECTOR_AND_CLINCH.md` — needs a paste-block.** Frontend + one server line, no outage |
| **S3–S6** | worker · queue + connect flow · preflight · drills. **The whole remaining block, ~4 weeks to Week 1.** Map-level only |

### S2e's five items (all decided, nothing open)

1. Remove the season selector + flatten the catalog (unblocked now the demo has its own lineage).
2. **The blank clinch line** (Will spotted it live): a null `magicWins` renders `''` in the team row and
   `—` in the your-team panel. Null means *no number of wins guarantees a spot* — make the existing,
   currently-unreachable `'Needs help to clinch'` label fire.
3. **Playoff odds: integers, with `<1%` and `>99%` at the ends.** A sim result of 0/10,000 is **not**
   elimination.
4. **The magic-line label set** — incl. retiring `'Clinched a spot'`, which is the *simulation* asserting
   certainty. **`Clinched`/`Eliminated` may only come from real bracket math — which does not exist, and
   Will has DEFERRED building it.**
5. **Withhold `posture`** — see below.

### The posture defect — measured, unfixed, and it is not just the demo

`derive_posture(playoff_odds, all_play)` labels **every team** lucky or unlucky: `BAND = 9` and the
smallest |gap| in the live league is **12.0**, so `Contender` / `Rebuild` / `On pace` are **unreachable**.
The label is the playoff line relabelled, and it is **inverted** — the best team by both measures is told
to sell. **Cause: the two axes are not the same unit** (odds saturate, all-play compresses), so the gap
measures the odds curve, not luck. **Retuning `BAND` cannot fix it.**

It renders in **four** places: the map, the *Your Race* chip, every **Teams** row, and the **sparkline
colour** in Playoff Picture. S2e withholds it — cleanest as **one server switch** (stop serving `posture`;
three sites already null-guard correctly) plus `PanelOff` for the map. Will chose **(b)**: keep the
scatter, drop the diagonal and corner labels — *the dot positions are true; the interpretation was not.*

**The metric fix needs its own measured session — not yet briefed, by Will's choice.** Likely
**all-play % vs actual win %** (same unit, so the gap really is luck); `BAND`/`LEVEL_CUT` must be
re-measured. `derive_posture` exists twice — `api/calcs.py` and `frontend/src/posture.js` — and they move
together.

---

## The settled model (decided 2026-08-05, now BUILT — do not re-derive)

`visible = (league_id == DEMO_LEAGUE_ID) OR (owned by caller AND season == current)`. Demo term **first
and season-independent**. Unowned → **same 404** as nonexistent (a 403 is an enumeration oracle).
`DEMO_LEAGUE_ID` is **config, not a table**. The 31 corpus slices stay as fixtures; **the clone is a 32nd
in the SERVE layer only — corpus/engine still counts 31.**

---

## Open threads to carry

- **S2e** — write the paste-block, hand over, audit.
- **The posture metric** — needs a measured session; deferred deliberately.
- **`reads._denied_reads` is per-process and there are TWO Fly machines**, so `denied_reads()` is a floor.
- **`scripts/users.py` has no `--delete`** → S4 owns account lifecycle.
- **P6** — precompute the frozen demo + Cloudflare (S4); two connection pools against a **free-tier**
  Postgres. **`Cache-Control: private, no-store` on every `/api` response must be deliberately carved out
  for the demo** — that carve-out is the one place a caching change could serve one caller's league to
  another.
- **S4 grew** (from S0): a cold-onboard entry point that does not exist, catalog-row-before-load ordering,
  and `_resolve_scoring_key` silently using the *owner's* key for an uncatalogued league — a live-path bug.
- **Two pre-existing client bugs** filed by S2b: `TeamDetail` and `MatchupDetail` spin forever on a
  legitimate `200 null`.
- **`SESSION_P5_S2C_AUDIT.md` is missing from the project doc's audit list.**
- **Metric legibility** — Will's most-repeated user feedback. S2e is its first concrete instance; still no
  home in `BUILD_ORDER`.
- P1's two-week ≥95% coverage soak and the annual re-tune (≈ Feb).

## The calendar gates

**Gate A** = Will's 2026 league loaded (~late Aug). **Gate B** = Week 1, Sept 10. Velocity is not the
constraint — Will runs several Code sessions a day. **Calendar-gated proof is.** Gate A must check the
**ROS-range panel against real band data**, and **`remaining_games` + playoff odds** on the fresh league.
**At Gate A his league joins the `lorp` lineage — the demo no longer shares it, which is what S2d bought.**

---

## Where the PM was wrong — the rules those errors bought

- **"Unreachable" is a claim about EVERY caller.** Enumerate every import site. *(Held up at S2c: a
  now-unreachable `None` branch was kept — a pure predicate's contract is its signature, not today's
  callers, and deleting it turns a clean deny into a TypeError inside an authorization check.)*
- **A sample supports a hypothesis, not an invariant — and that applies to BLAST RADIUS too.** I wrote
  "**one** Fly machine" into a runbook from `fly.toml` plus recollection; there are two. Then I wrote the
  posture defect up as "inverted on the landing page" when it is inverted for **every league**. Twice I
  let where-I-measured stand in for where-it-applies. **Config declares intent; only the platform knows
  the fact. Any number entering a runbook or a cost claim gets measured and date-stamped.**
- **Correcting a citation is not verifying a fact.** Three documented figures here turned out never to
  have been measured (the Fly machine count twice, the RLS table count).
- **Grep finds the name, not the concept** — and check your own greps: mine was case-sensitive and nearly
  produced a false "Code's claim is unbacked".
- **An absence check is weaker than a presence check.** "Grep for the ten known names, find zero" cannot
  prove you missed none. Asserting *every* value against a committed map found a real bug S2d would
  otherwise have shipped.
- **Don't smuggle an engine-affecting change into a cleanup task.**

## Environment — what this session can and cannot do

- Repo at **`~/mnt/fantasy-ai`** via `device_bash`; `device_stage_files` wants `/Users/willdaniel/...`.
- **The device bridge drops without warning and returns on its own.** Nothing Will does causes it. Writes
  already made survive on his disk. **Do not retry in a loop** — report state and continue when it returns.
- **You CAN commit; you CANNOT push** (no egress from the device VM). Will pushes.
  1. `mkdir -p .git/_stale_locks`; 2. `mv .git/index.lock .git/_stale_locks/index.lock.N` —
  **unconditionally**, never guarded by `[ -f … ]` (the mount's dir cache makes that test lie); add
  `sleep 1` after a failure; 3. commit with an explicit identity
  (`git -c user.name=spectraltoast1 -c user.email=88110329+spectraltoast1@users.noreply.github.com`);
  4. sweep `find .git -maxdepth 3 \( -name "*.lock" -o -name "tmp_obj_*" \)` and `mv` each aside;
  5. **`git fsck --no-dangling`** to prove the object store survived.
  **Never `--amend` without checking `git rev-list --count origin/main..main` first** — Will pushes
  promptly. Tell him to `rm -rf .git/_stale_locks`; Code now treats the sweep as a closedown step.
- Device VM has **no network and no parquet engine**, and repo venvs are macOS binaries → stage into the
  container and use polars there.
- `curl` to fly.dev/supabase.co is blocked from the container; **WebFetch works (GET only)** and
  `api.sleeper.app` is reachable.

---

## Standing instructions (carry into every brief)

1. **A suspiciously clean value is a bug until proven otherwise.**
2. **A refactor that changes a number is a bug** — prove equivalence. Say **value**-identical unless
   comparing bytes (polars' parquet writer is physically non-deterministic).
3. **Prove a new gate *bites*** — fail it on a broken input.
4. **Report, don't tune.** Engine constants are propose-only / human-promoted.
5. **Honest, not hidden.** Gate a panel OFF only when a read is *misleading*, not merely uncertain.
   **Absence is reported, never fabricated** — a blank cell beside populated ones reads as broken, and
   rounding only lies at the ends.
6. **The frozen corpus is immutable** — compute into a *different* path.
7. **"The artifact exists" and "the consumer uses it" are two different gates.**
8. **Persist the substrate; never re-derive from a moving source.**
9. **Enforce security server-side.**
10. **A hand-made artifact in a generated store is a bug with a date on it** — a full `--load` rebuilds
    what the generator knows how to make and silently drops the rest. That is how `ros_player_band` lost
    its RLS, and why the demo clone is generated rather than inserted.
