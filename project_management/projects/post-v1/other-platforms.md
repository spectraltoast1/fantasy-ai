# Post-V1 — Other platforms: importing leagues from more than Sleeper

**Created:** 2026-08-14 · **Status:** Not started — planning only · **Depends on:** P5/S4c (which
establishes the import affordance and the adapter seam) · **Est:** not sized; see "What this actually
costs" · **Related:** `standard-scoring.md`, `custom-scoring.md`, `dynasty.md`

> **What this project does:** lets somebody import a league from a platform that is not Sleeper —
> Yahoo, ESPN, or whatever else earns its place — without rebuilding the engine underneath.

---

## The product shape (Will, 2026-08-14)

Somebody creates an account. **The "Import a league" option is permanently available** — not a
first-run wizard, not a one-time onboarding step. They can import as many leagues as they want,
whenever they want, including mid-season. They pick a platform; each platform has its own import
route. For Sleeper that route is *"drop your username, we list your leagues, the ones we can't
support are greyed out."* Yahoo would be its own route behind the same button.

**This is the standard shape across fantasy tools, and it is worth matching rather than inventing.**
The button is the constant; the route behind it is the variable.

## Why this is post-V1 — and why V1 must not make it expensive

Nothing about V1 needs a second platform. But V1 is where the trench gets dug or avoided, so P5/S4c
was told to **build the dimension, not the second implementation** — the same pattern that gave the
jobs table its `kind` column before a second job class existed.

**What S4c establishes (and what a second platform plugs into):**

- A platform-generic endpoint contract — `POST /api/connect {platform, handle, league_id}`, not
  `{sleeper_username}`.
- A `platform` column on `jobs`, defaulting to `'sleeper'`.
- Discovery behind one function taking a platform argument, with exactly one implementation behind it.

The natural adapter interface is three calls: **`discover(handle) → [league summaries]`**,
**`summary(league_id)`**, **`fetch_raw(league_id, season)`**. Everything downstream of `fetch_raw` —
the join, the spine, the engine reads, the loader, the API's authorization seam — already operates on
our normalised shapes and does not care where the league came from.

## The two real trenches

Most of the system is more platform-agnostic than it looks. Two things are not, and they are the
project.

### 1 · `sleeper_player_id` is the player key in six served tables

`season`, `player_signal`, `production_vor`, `market_vor`, `ros_synthesis` and
`projection_consensus` all key on it, and it reaches `reads.py`, the API payloads and the frontend.
Every platform has its own player ids, so this is the deepest coupling in the system.

**But the platform-neutral key already exists.** `cache/player_id_map.parquet` maps
**`gsis_id → sleeperPlayerId`** and is refreshed on every nflreadpy fetch run. `gsis_id` is the NFL's
own identifier — it is the natural neutral spine, and the join to it is already built and already
exercised weekly. **Sleeper's id did not win on merit; it won by being the only platform when the
columns were named.**

So the work is not "invent a mapping layer." It is:

- add `platform_player_id → gsis_id` for the new platform (the same shape as the existing map), and
- **rename the column** across six tables, the API and the client.

**That rename is a real project on its own** — `CODING_BIBLE` §5: a refactor that changes a number is
a bug until equivalence is proven, and this one changes a column name in every served payload.

**Do it once, with the other naming debt.** STATUS already parks the `*_ppr` wart — `center_ppr` /
`band_ppr` hold *league* points, not PPR — as *"coupled to a frontend + schema change."* Same class of
problem (**the name outlived the assumption**), same blast radius, same parity proof. Two renames in
one session is barely more expensive than one; two sessions is nearly double.

### 2 · The scope gate is shaped like a Sleeper payload

`transforms/_keys.scoring_key_from_settings(scoring: dict)` takes, in its own words, *"a raw Sleeper
`scoring_settings` dict."* That function decides the `scoring_key`, which decides which shared
substrate a league reads and therefore whether the league is scoreable at all. `onboard_league.
assert_in_scope` reads Sleeper's `settings.type` (0/1/2) for redraft-vs-keeper-vs-dynasty.

A second platform needs its settings **translated into our profile**, not a parallel scoring path.
`CODING_BIBLE` §2 — *single source of truth per fact* — so the adapter normalises into whatever
`scoring_profile` already consumes, and the key derivation stays in one place.

**The good news, and it is the load-bearing economics:** `projection_consensus` and `ros_player_band`
are keyed on `(scoring_key, season, week, player)`. They are about **players and scoring rules, not
leagues or platforms.** So a Yahoo half-PPR league reads **exactly the same substrate** a Sleeper
half-PPR league does, once its players are mapped and its scoring is translated. **The shared-substrate
cost model survives multi-platform intact** — which is the thing that made per-user onboarding cheap in
the first place (P4's keying decision, S0's sizing).

### The shallow ones, for completeness

`MY_USERNAME` / `LEAGUE_ID` in config, `shared/league_resolver.py`, the single `fetchers/sleeper.py`
(the CODING_BIBLE already says *one fetcher per source*, so a second is additive not disruptive), and
`previous_league_id` lineage — Sleeper's chain concept, which other platforms express differently.

## The thing that actually dominates this project: every other platform needs per-user auth

**Sleeper's API is the exception, not the norm.** It is public, unauthenticated, read-only, no app
registration, no key — which is exactly why *"just type your username"* works and why Sleeper is
first.

- **Yahoo** publishes a formal Fantasy Sports API but requires a **registered application and OAuth**
  — there is an access-application step, and every user authorises individually.
- **ESPN** has no official public fantasy API. The community libraries read private leagues using the
  user's own **`espn_s2` and `SWID` session cookies**, which means asking a person to paste browser
  cookies into our product.

**This changes the import UX per platform, and it is a product decision before it is an engineering
one:**

| platform | what we ask the user for | what it implies |
|---|---|---|
| Sleeper | a username | trivial; no account linking; no stored credential |
| Yahoo | "authorise Surplus" | OAuth app registration, token storage + refresh, revocation handling |
| ESPN | two session cookies | poor UX, brittle, and **we would be storing a credential that grants broad account access** — a decision to take deliberately or decline |

**So the platform picker is not cosmetic.** Behind it sit three different trust models, and the
account-linking story — storing, refreshing and revoking third-party tokens — is a bigger project than
the data mapping. **Sleeper being easy is an accident of Sleeper being open.**

*(Verified at the shape level 2026-08-14; re-check the specifics when this starts — API terms and auth
models change, and this doc will be months old.)*

## Decisions deliberately deferred in V1 — recorded so they read as choices

Both were considered during P5/S4c and **declined for now**, not overlooked:

- **No `platform` column on `user_leagues`, `league_catalog` or the 14 data tables.** That is a
  migration across the loader and every served table, and it buys nothing until a second platform
  exists. `jobs.platform` alone carries the dimension today.
- **No namespaced league ids** (e.g. `yahoo:nfl.l.12345`). It would touch the frozen corpus,
  `demo_manifest` and every data table. A half-applied namespacing is worse than none.

**When a second platform becomes real, one of these two has to happen.** The column is the smaller
change; the namespace is the more honest one. Decide then, with a real second platform in hand rather
than a hypothetical.

## Interactions worth knowing before starting

- **Current-season-only.** V1 is redraft, so the import flow offers **only the current season** —
  expressed as `season == settings.current_season`, never a literal year, so the import gate and the
  visibility predicate cannot drift. **`dynasty.md` breaks this assumption**, because a dynasty league
  is a continuing entity across seasons. Whichever of these two lands first sets the shape for the
  other.
- **Scoring scope.** `standard-scoring.md` and `custom-scoring.md` widen *which* leagues are
  scoreable; this project widens *where they come from*. They multiply: a new platform × a new scoring
  format is two translation problems, not one.
- **The import button is the natural home for the platform picker.** Because S4c makes it a
  permanent, always-available affordance rather than a first-run step, adding a platform is a change
  *inside* an existing flow rather than a new entry point.

## What this actually costs — a shape, not an estimate

Roughly three separable pieces, and they are **not** equally hard:

1. **The adapter** — discovery, summary, raw fetch, settings translation for one platform. Bounded,
   and S4c's seam is where it plugs in.
2. **The player-key rename** — six served tables, the API, the client, with a parity proof. **Do it
   with the `*_ppr` rename.** Independent of any platform; could be done at any time and would make
   this project smaller whenever it happens.
3. **Account linking** — OAuth app registration, token storage, refresh, revocation. **The big one,
   and it is entirely new surface area** with no existing analogue in the codebase. Sleeper needed none
   of it.

**Sequencing note:** (2) is the only one that can be done *before* a decision about which platform is
next, and doing it early makes (1) meaningfully cheaper. If this project ever feels blocked on "which
platform first", (2) is the useful thing to do while deciding.

## Open questions for Will

1. **Which platform second, and why?** Yahoo has a real API and real OAuth cost. ESPN has more users
   and a worse mechanism. The answer probably comes from the invited cohort rather than from the APIs.
2. **Is storing a user's ESPN session cookies acceptable at all?** That is a trust decision, and
   declining ESPN is a legitimate answer.
3. **Does a person get one account with many linked platforms, or is a platform link per league?** The
   first is the better product and the more work.
