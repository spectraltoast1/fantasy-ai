# STATUS

**What this is:** SurplusFF — a fantasy-football decision-support dashboard whose unit is the manager's
*decision*, not the player. Live, single-league, on the server stack.
**Live at:** https://surplusff.com/ (also https://fantasy-ai-api.fly.dev/) · **Updated:** 2026-08-14
**Name + domain:** the official name is **SurplusFF**, commonly shortened to **Surplus** (Will,
2026-08-05); "Gridiron" was a working name — retire it. **surplusff.com** is registered (SSL live), serves
the app (Fly cert + DNS), and is the **Resend sending domain** for auth email — Supabase's custom SMTP
sender, which is what makes a magic link reach anyone who is not a project team member. It is the
**canonical origin**: S1b removed S1's `emailRedirectTo`, so a magic link goes wherever Supabase's **Site
URL** points regardless of where the person signed up, and that is surplusff.com — so a sign-in started on
either host returns there (round trip observed 2026-08-04 →
`sessions/v1/P5-Self_Serve/SESSION_P5_S1B_AUDIT.md`). The UI still says **Gridiron**; moving it is an
undecided, cosmetic-but-broad change (SPA copy plus Supabase's redirect allow-list), not a launch
dependency.
**Read next:** `ARCHITECTURE.md` (how it's built) · `CODING_BIBLE.md` (rules for coding agents) ·
`ROADMAP.md` (where it's going) · `projects/v1/` (the active build).

---

## What's live today

- A deployed, mobile-responsive React SPA on **FastAPI + Supabase Postgres** (Fly.io, same-origin). Five
  surfaces: **Players, Teams, League, Matchups, Manager Dossier**.
- **Multi-league, and leagues now have owners — acquired by the people who own them (P5/S4c).** All **31 demo league-seasons (12 lineages)** are still in
  the production DB — they are engineering fixtures — but the **public catalog is one league**: the demo,
  plus whatever the signed-in caller owns. Every read is parameterized on
  `league_id`(+`season`+`viewer_roster_id`) and now defaults to `DEMO_LEAGUE_ID` explicitly. League + week
  selectors re-scope every surface, and the "you" highlight follows the selected league.
  → *`sessions/v1/P0-Multi_League/` + `sessions/v1/SESSION_B6_VERIFICATION_REPORT.md`.*
- **The app can now advance week by week (P2/S2).** The loader has a **per-league scoped reload** and a
  **weekly-refresh orchestrator** advances one league to the current week without rebuilding the DB —
  proven on prod by advancing the owner's 2025 league Week 4 → 5 (the un-freeze). Ready for live 2026 at
  kickoff. → *see below + `sessions/v1/P2-Go_Live_2026/`.*
- Fully migrated off in-browser DuckDB-WASM (Stage A complete); the client is now a thin API client.
- **Web analytics — GA4, installed 2026-08-10.** The gtag tag sits in the SPA's one `index.html` shell
  with `send_page_view:false`; `src/analytics.js` sends the virtual pageviews (no router → GA can't
  otherwise tell one surface from another) and five sign-in-funnel events. All eight surfaces proven,
  no hit for `/`, and no GA request carries an `@` or any id. Measurement only: no read, number or
  pixel changes. `signed_in` is the one event awaiting a real prod sign-in. → *see appendix: analytics.*

## The engine

- Built, measured, and deliberately made **honest** — i.e. tuned so its stated confidence is truthful rather
  than flattering (the shipped "8c" change: a lower center + a wider two-sided band). Reads it produces:
  production VOR, projection bands, playoff odds (Monte Carlo), positional depth, true rank, player signal,
  market VOR, the ROS bull/bear/situation outlook, and manager dossiers.
- **Current honesty state:** production VOR ranks rest-of-season value well but runs the *level* high (trust
  the order, not the total); the band was re-tuned to ~0.86 coverage; playoff odds and true rank are honest;
  four reads still carry no confidence signal. → *see appendix: engine-trust, engine-decision-reads.*
- **The thin-data window is honest (P2/S4a).** Every surface keys off **one** depth clock — weeks with real
  RESULTS, not weeks merely loaded, because a projections-only week joins with zero-filled points and would
  otherwise report "1 week of data" for a league that has played nothing. Below three weeks the app states
  the sample and **withholds the claims the sample can't support**: no posture chip, no clinch magic number,
  no posture map, no trend direction — while the numbers themselves (playoff %, VOR, bands) still show,
  flagged. Reachable today: pick Week 1 on the demo. Nothing changes at ≥3 weeks.
- **The honest band is wired end-to-end, and dark until 2026 (P2/S3b).** `ros_player_band` is now a loaded
  table, selected by `load_player_card` (pinned to `production_vor`'s week) and rendered as a **"Rest-of-season
  range"** panel — bear / center / bull in points, with the ±σ spread as the confidence read (no label: the
  width *is* the confidence, and the `ros_cv` that would have supplied one was measured INVERTED in S5 and
  retired in 8c). It sits **beside** the AI `ros_synthesis` panel — a different object, not a replacement.
  **It serves 0 rows today** and renders an honest absent-state: only seasons at or above
  `build_db.FIRST_HONEST_BAND_SEASON` (2026) may be served, and no 2026 league exists yet. It lights up by
  itself when one is onboarded.
- **Why the 2020–2025 band stays stale — a deliberate boundary, not an omission.** That parquet is also the
  frozen-corpus artifact the **immutable L2 ledger** was derived from, so rebuilding it at the honest
  constants would break the ledger's reproducibility; a corpus re-backfill is the **annual pipeline's** job.
  → *ARCHITECTURE, "The honest-band boundary".*
- **Still true of the weekly surfaces:** MatchupDetail's "Score Range · 25–75" is
  `projection_consensus.p25/p50/p75` under `BAND_Z`/`SKEW_GAIN`, which 8c deliberately **held**, and matchup
  μ/`proj` is `Σ center_ppr` straight from consensus, bypassing `CENTER_SHRINK`. Applying the shrink to the
  weekly serve path is an unmeasured engine change, so it stays a tuner question under propose-only.

## What's real vs. proof-of-concept (current caveats)

- **ROS bull/bear/situation shows an explicit "No rest-of-season outlook yet" empty state** — the read runs on
  live in-season news, which isn't wired yet; an honest empty state, not fabricated grades.
- **The market read is gated off everywhere (P2/S3).** `market_vor` prices *today's* market against a *past*
  season's rosters — `is_cross_time=true` — so all four market surfaces (Players MKT, team-detail MKT toggle,
  player-card market trend + BUY/SELL lean, League positional talent) render an honest "not a live read"
  state instead. The gate is the read's own flag, not a season constant: `panels.market` = the manifest's
  structural flag AND `NOT is_cross_time`, so a contemporaneous league (2026 production × 2026 prices) turns
  the panels back on by itself. `compute_market_vor` is proven contemporaneous-ready.
- **Rostered-only** — no free-agent / waiver value yet.
- **Data collection is hosted off-laptop and hardened (P1, ~done).** The two daily collectors run on **GitHub
  Actions → Supabase Storage** (S1, live), with fetch-timestamp sidecars, a same-day **catch-up retry**,
  flush-batched uploads, and a daily **coverage gate that emails on a missed/short day** (S2). The only thing
  left is the **rolling two-week soak proving ≥95%** coverage — **P1 closes when it clears.** → *see appendix:
  data-collection.*

## The active roadmap

**V1** = a working, **invite-gated self-serve** product for **Sleeper PPR / half-PPR redraft** (1QB and
superflex), running on **live 2026 data**, ready for the invited cohort by **Week 1** (Thu 10 Sept 2026).
Seven projects (P0 finish multi-league → P6 launch hardening); critical-path spine P0 → P2 → P5.

**P0–P2 done.** P2 delivered the un-freeze end to end: the 2026 preseason substrate (ppr+half, honest
constants, `check_forward_substrate` green), the per-league scoped loader + weekly-refresh orchestrator,
the honestly-retired cross-time market, the wired-but-dark ROS band, and the honest early-season window.
**Gate A's one blocker is cleared (2026-08-05):** `transforms/_matchup` is now the single rule the join
and the sim share — *a matchup is gradeable iff it has a `matchup_id`, exactly two rosters, and somebody
scored; else null, never fabricated.* A freshly drafted league had minted a full W/L slate by roster-id
sort order before a game was played; it now reads `0-0`. A genuine tie became a real outcome (`'T'` →
`2-1-1`), and the null-`matchup_id` playoff case was **not** merely latent — `weekly_refresh` joins
without `harvest`'s `playoff_week_start - 1` clamp. Nothing was re-joined or reloaded: only a *future*
join changes, reaching Postgres via `weekly_refresh`'s existing `reload_league`. Parity is exact — 80
read payloads byte-identical to main, and across all 271 corpus league-seasons exactly **4** groups
change verdict, all genuine ties outside the demo slate.
→ `sessions/v1/P2-Go_Live_2026/` (+ `SESSION_P2_MATCHUP_TIE_REPORT.md`).

**P5 (accounts + invite-gated self-serve onboarding) is the active block** — 7 sessions, S0–S6, the
critical-path long pole. Everything but S6 is buildable against the 2025 replay now, so the preseason
runway is for building and Gate A is for verifying.

**P5/S0 done — the cold-league latency spike, and it reshaped the connect UX.** A cold league is loadable
in a **measured 8.4–10.3s**, but the Manager Dossier's cross-league fan-out adds **80s / 248 Sleeper
calls** — so connect is **staged**: the four fast surfaces on a spinner, manager profiling as a separate
deferred job class. Network-bound, not compute-bound, which is what sized the S3 worker.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S0_REPORT.md` + its audit.

**P5/S1 done — the app has a front door, and it is live.** Supabase Auth, **magic link**. The API
verifies access tokens (ES256) against the project's JWKS and exposes **`/api/me`**, the only
*authenticated* endpoint; it 401s on a missing/forged/expired token and 503s when the verifier is
unreachable — denied either way, but an outage stays distinguishable from a bad credential.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S1_REPORT.md` + *appendix: auth*.

**P5/S1b done — the signup model corrected.** Signup is **self-serve behind a shared access code**,
enforced **server-side** at `POST /api/signup`: the API holds the secret key and does the admin create
itself, which is what makes platform-signup-OFF compatible with zero per-user work. The code is required
from everyone on every request, so *no valid code → no email ever sent*. The rate limiter lives in
Postgres, not memory — two Fly machines with scale-to-zero would otherwise let an attacker reset it by
waiting out the idle window. `scripts/users.py` (`--list`/`--ban`/`--unban`) exists because self-serve
creates the need to remove someone. **Custom SMTP is a hard dependency**: Supabase's built-in sender
refuses any address that isn't a project team member.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S1B_REPORT.md` + *appendix: auth*.

**P5/S2a + S2b done — per-user isolation is closed, discovery *and* access.** S2a gave leagues owners
(`public.user_leagues`) and scoped the **catalog**, so you cannot *find* someone else's league; S2b scoped
the **eleven per-panel reads**, so knowing a `league_id` is no longer enough to *read* one. Visibility is one
predicate in one function at one seam (`slice_params` → `reads.authorize_slice`), and an unowned league
returns bytes identical to a nonexistent one while a broken deploy raises 503 — mechanism in ARCHITECTURE.
Two fixture-driven gates with prove-it-bites blocks: `check_ownership.py` (8/8 fail pre-S2a) and
`check_isolation.py` (**82 assertions fail against the real pre-S2b binary**). Proven with two real accounts
over 165 live requests, 19/19 demo payloads value-identical. Honest caveat carried forward: `slice_params`
defaulting to the demo is **unobservable today** because `DEMO_LEAGUE_ID` *is* the is_mine league — S2a
proved it by temporarily repointing the config at Trap 2025.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2A_REPORT.md` + `SESSION_P5_S2B_REPORT.md`.

**P5/S2c done — the punch list, and audit F6 with it.** Nine loop-closers; no open security hole among
them. **The current season is now derived locally** (calendar year, or the year before it until **August 1**,
a boundary that deliberately *leads* Sleeper's flip). `nfl_state.py`, `nfl_state_cache`, the 5s timeout and
both fallback branches are **deleted** — they existed only to survive a Sleeper outage, which S2b had made
eleven endpoints wide, and removing the failure beat handling it. Sleeper is now an assertion in
`check_ownership`, not a dependency; **`/health` publishes the season + its source** (F7), still DB-free.
The rest — the signup limiter counting only valid-code requests, cascade/orphan assertions, a rejected
token that *says* the session was lost, a catalog error instead of a permanent "Loading…", and a tab
refocus that no longer resets league/week/drill-down — are in the report.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2C_REPORT.md` + *appendix: auth*.

**P5/S2d done — the demo is no longer Will's league.** It is now **`DEMO-2025` / "DEMO League"**: a
GENERATED, anonymised clone of LoRP 2025 at week 5 — invented names, no `is_mine`, no viewer seat, so no
"you" highlight and none of the ten real Sleeper handles that were on the landing page until today (swept:
**0 hits across 51.5KB of live payload**). Generated, not inserted, so `--load` re-materialises it rather
than it surviving only to the next schema change — the failure that cost `ros_player_band` its RLS; proven
by regenerate + re-publish, **14/14 tables value-identical**. `--emit` now emits RLS for all **15** served
tables and `--verify` asserts it. The catalog TABLE is now **`league_catalog`**; the parquet keeps its name
and its 31 frozen rows.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2D_REPORT.md`.

**P5/S2e done — the honesty pass on the League screen, and the season selector is gone.**
**Deployed 2026-08-13 (Fly v27); confirmed live** — `/api/standings` carries no `posture` key and
`/api/leagues` is flat. Four defects in one shape — *the UI asserting more certainty than the model
has* — stacked on one row of the landing page (rank 9 read "0%, no path"; the truth is "0.3%, needs
help"). Playoff odds are hedged at both ends (**`<1%` / `>99%`**: a sim 0 means "did not occur in
10,000 tries", not eliminated) across **five** render sites, not the three the brief named. A null
magic number now says **"Needs help to clinch"**; **"Clinched a spot" is retired** because
`MAGIC_ODDS` is 0.90 and the engine calls the value a *proxy* — Clinched/Eliminated may come only from
real bracket math, which is deferred. The **season selector is gone and the catalog is flat**; league
+ week switchers stay. `TeamDetail`/`MatchupDetail` no longer spin for ever on a legitimate
`200 null`. Gated by `check_league_copy.mjs` (39 checks, **26 fail against the pre-S2e code**);
parity 40 of 43 demo payloads byte-identical.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2E_REPORT.md` + `SESSION_P5_S2E_AUDIT.md`.

**`posture` is WITHHELD from the API — the metric is wrong, and fixing it is its own measured session.**
`gap = all_play_pct - playoff_odds_pct` subtracts two quantities that are not the same unit, so it tracks
the shape of the odds curve rather than luck: measured 2026-08-12, **every** team read *Riding luck* or
*Unlucky*, three of five labels were unreachable, and the best team by both measures was told to sell.
Inverted for every league, not just the demo. A correctness defect, not calibration, so retuning `BAND`
cannot fix it. One server line withholds it; the map kept its scatter and lost its interpretation.
**The fix:** compare like with like (all-play % vs actual **win %** — same unit, so the gap *is* luck;
rank-vs-rank is the fallback), then re-measure `BAND`/`LEVEL_CUT` on that scale. Cheaper than it was
sized — `derive_posture` has exactly one home (`api/calcs.py`); the `posture.js` mirror older notes
name went with the DuckDB-WASM client. → *appendix: engine-decision-reads §5, which specified posture as
adjacency and "not a computed label" all along.*

**P5/S3 done — the laptop is no longer the only machine that can build a league, and the store has a
boundary.** A **separate Fly app `fantasy-ai-worker`** (1 GB `shared-cpu-1x` + a 1 GB volume, ~$7/mo,
no HTTP service — a job box) runs the pipeline off a seeded volume. **Seeded and measured 2026-08-14:
37s end to end** (6s tar · 18s upload · 13s extract) for **244 MB → 248 MB on the volume, 28% full**.
That number *is* the recovery procedure — "reconstructible cache, lose the host and re-seed" had never
been tested — and it is in OPERATIONS with the exact commands. `derived/ledger` (145 MB) is excluded by
design. **`COPYFILE_DISABLE=1` is mandatory on macOS**: the first seed shipped **16,089** AppleDouble
`._` files, inflated the volume to 311 MB and made `*.parquet` globs raise on files that were never
parquet.

**The boundary is one predicate in one place.** The rule is **ONE WRITER — the authoring laptop —
everything else reads**, not "laptop vs worker": *three* machines run this pipeline (laptop, Fly
worker, GitHub Actions), so `STORE_ROLE=worker` is set on the worker and the GHA job. Enforced as an
**allow-list** in `data_layer` over **16** laptop-owned writers, so an unclassified destination or a
writer added later refuses by default; the ADR's three-row table is now **eleven**. Consolidating the
`frozen_writers` list was a **bug fix** — three rescore gates each carried a copy and all had drifted
(4/5/6 entries), so two would not have caught a `write_center_gap` call.

**The band could not simply raise, and that is the finding.** `weekly_refresh` rebuilds
`ros_player_band` *unconditionally* for `season >= 2026`, so a blanket refusal would have broken every
2026 refresh — and a 2025 replay proof would never have exposed it. On a worker the writer
**verifies** instead: identical → proceed (reported, not silent); different or missing → raise with
the operator step. **Value**-identical via `data_layer.canonical_rows` (moved from
`check_scoped_reload` — one home, same function). Proven live against the real 2026 ppr substrate:
identical → proceeds, one field perturbed → raises, restored → proceeds. `check_store_boundary.py`
gates it, **21/21 green, prove-bites failing all 10**. Worker **parity** proven the same way: the
spine was cleared on the volume so the run could not pass by skipping, and all **10** recomputed
league artifacts hash-match the laptop's canonical row multisets. The scoring key came from the
catalog, **not** `_resolve_scoring_key`'s owner-key fallback (S4 owns that).
**The worker has written production Postgres (2026-08-14)** — `build_db --reload-league` on
`fantasy-ai-worker` reloaded LoRP 2025, **14,624 rows across 12 tables**, per-table counts matching
the prior state exactly, every other league and `league_catalog` untouched; egress and the Supabase
**session** pooler both hold under a `COPY` inside a transaction. **That run also validated the
seed:** `--verify` runs from the *laptop* (laptop disk vs Postgres) against rows the *worker* wrote
from its own volume, so `VERIFY OK` is a **cross-machine parity proof** — the 244 MB seed is now
verified faithful, not merely measured, which is the first real evidence for the ADR's
*reconstructible cache* claim.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S3_REPORT.md` + `SESSION_P5_S3_AUDIT.md`.

**P5/S4a done — the store can accept a league it has never seen, and the worker created one.**
Nothing in this system had ever catalogued a league: `_catalog()` was the frozen 31-row corpus slate
plus the generated clone, and `load_league` refuses anything absent from it, so a real user's league
had nowhere to be written down. There is now a **third catalog artifact, `connected_catalog.parquet`
— 31 + 1 + N** — and `write_connected_league(df, league_id, season)` replaces exactly one row and
leaves the rest untouched. **That append shape is the whole reason a worker may hold this pen**; the
ADR's objection to `write_leagues` was its shape, not its owner. The classification goes **11 → 12**.
**`write_leagues` was NOT touched and the ADR's "S4 wall" was wrong**: every reader of
`leagues.parquet` filters `is_mine` first, so a stranger row would be read by nothing — the wall is
the *catalog*, not the *registry*. **`_resolve_scoring_key`'s owner-key fallback is fixed** (catalog
→ the league's own Sleeper settings → **raise**); the naive "always derive from settings" breaks
because `refresh_league` calls it before its fetch stage.
**Proven end to end on `fantasy-ai-worker`, 2026-08-14**: a real cold 2025 league (Rex Lumber, 12-team
1QB PPR, from the crawl leftovers — never in the corpus) went **cold → catalogued**, the worker
**COMMITTED 14,999 rows across 10 tables + 1 catalog row**, `league_catalog` 32 → 33, and **every
other league moved by exactly 0**. A re-onboard is a **clean no-op** (catalog value-identical, all 14
tables unchanged, no duplicate row). Signed-out prod still returns **exactly the demo**, and the
league 404s byte-for-byte identically to one that never existed.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S4A_REPORT.md`.

**One consequence carried forward:** a **2025** league takes the `season < FIRST_HONEST_BAND_SEASON`
branch and never reaches the band, and production's derived season is **2026**, so a 2025 connected
league is correctly invisible to its own owner on the deployed API. Both halves were proven —
positive against a `CURRENT_SEASON=2025` process on production Postgres, negative on live prod — and
the 2026 arm is pinned as a fixture in `check_ownership`/`check_isolation`. **What remains uncovered
is the combination: a *cold 2026* league whose scoring key's substrate must already be on the volume.
That is Gate A's to close.**

**P5/S4b — work reaches the worker without a human, and the laptop can no longer clobber the
catalog.** `Dockerfile.worker` was `CMD ["sleep","infinity"]`: always on, doing nothing, waiting for
somebody to `fly ssh` in. **The API physically cannot call it** — `api/requirements.txt` is
fastapi-only and the worker has no `[http_service]` — so the two machines can only meet in Postgres.
*That*, not latency, is why there is a queue. `public.jobs` lives in `api/auth_schema.sql` (a fourth
app-side table; `--load` DROPs everything in the generated schema), work is claimed with
`FOR UPDATE SKIP LOCKED`, and the worker waits on `LISTEN` with a 60s safety-net poll. **The lease
expires** (120s, renewed per stage), `attempts` caps retries, and a reaper turns the last one into a
terminal `failed` — so a killed worker never strands a league. **`rejected` is a refusal that will
never succeed; `failed` is retryable.** Mechanism in ARCHITECTURE + *appendix: store-boundary*.

**The guard S4a's audit assigned here shipped first.** The worker authors
`connected_catalog.parquet` and the laptop does not have it, so the laptop held the *stale* catalog —
measured live: laptop 32 ids, production 33. `assert_catalog_covers_postgres` compares the id **sets**
(`--verify` only ever compared counts, which is why it never caught this) and refuses before the
TRUNCATE and before the DROPs. **Consequence: the full `--load` has moved to the worker**, the second
artifact after `--verify` to change machines — copying the catalog parquet down is not enough,
because the loader is skip-if-absent and the laptop lacks the leagues' `derived/league` artifacts.
`_assert_columns_live` used to print `--emit && --load` on both machines, i.e. the codebase itself
instructed the operator into the loss; it is machine-aware now. → `OPERATIONS.md`.

**Two latent defects the queue made reachable, fixed in the same session.** (1) A crash inside the
~10s chain left the on-disk directories and no catalog row, and `assert_cold` then called the league
warm — so the first crash on a real user's league made it **permanently** un-onboardable, and under
the queue that is a terminal `rejected`. `classify()` now separates *recorded* warmth (a catalog row
— somebody decided) from *on-disk* warmth (wreckage) and returns `resume`. (2) `harvest._raw_present`
is true on config + teams + **week one**, while `_pull_raw` writes every week inside a loop — so a
fetch that died at week 6 of 14 read as complete and the league would reach `ready` **on a truncated
season**, the risk register's exact "half-built league that looks complete". The fetch stage now
verifies coverage against Sleeper's own completed-week count and repairs it.

**Deployed and proven live 2026-08-14, all five DoD clauses.** A hand-inserted row was leased **0.2s**
later (the NOTIFY, not the poll) and reached `ready` in **10.6s** — 14,999 rows, nobody touching
`fly ssh`. **The kill drill:** killed mid-`loading`, the lease dangled, Fly restarted the process by
itself, and the job was reclaimed at **attempt 2, 130s** after the kill — Postgres **identical on all
14 tables**, because `load_league` is one transaction and runs last. Reclaim latency is
`LEASE_SECONDS` + up to `IDLE_WAKE_SECONDS` (120 + ≤60). An idle day costs **~2,880 statements**, no
polling — but it is a **third** always-open connection against the free tier (P6's item, now worse).
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S4B_REPORT.md`.

**P5/S4c — the ownership row stopped being something Will types.** `api/routes.py:102` said ownership
was *"written by an operator rather than inferred from a sign-in"*; it is now inferred. A signed-in
person opens **"Manage Leagues"** from the league switcher, types a Sleeper handle (or a league id —
the input is dual-mode on the store's own 18-19-digit rule), sees their leagues with the unsupported
ones **greyed and labelled with the reason**, picks, and watches a banner while the worker builds.
**Proven end to end in a browser, no terminal, no `--grant`.**

**The enqueue seam had to move, and that is the session's shape.** The API image contains **no
`application/data/`** — `.dockerignore` excludes a bare `data`, the Dockerfile copies `api/` only — so
`job_queue.enqueue`'s own docstring ("S4c's `POST /api/connect` … call this") was wrong. The producer
now lives in **`api/jobs.py`** and `job_queue` re-exports it: **one INSERT, one NOTIFY**, asserted from
the AST so a second one cannot appear. Four routes, all requiring a token; a job that is not yours
returns the **byte-identical** 404 a nonexistent one does (proven live, two real accounts).

**THE OWNERSHIP ROW IS WRITTEN AT `ready`, IN THE SAME TRANSACTION AS IT** — the decision most likely
to be got wrong, and it fails silently both ways. Early, the user lands on their own league with every
panel empty for the whole build; separately, a crash leaves a terminal job over a league nobody owns.
**Measured live:** the grant did not exist in `queued`, `building` or `loading`, and appeared with
`ready`. Consequence, not a detail: the progress screen is driven by the **job**, not the catalog, so
`GET /api/connect` exists and a mid-build refresh recovers.

**No ownership verification, and no roster uniqueness — both decisions, not omissions** (Will,
2026-08-14). Anyone with a `league_id` can already read that league from `api.sleeper.app`, and Sleeper
offers no OAuth; combined with invite-gated signup that is the accepted risk. The seat is a **per-user
display property**, so two people in one league is the designed case — proven: two accounts own Rex
Lumber with seats **1 and 2**, each seeing themselves. **S4a finding F is closed by construction:**
`resolve_viewer`'s `MY_USERNAME` fallback now JOINs the catalog and requires `is_mine`, so it cannot
reach a linked league — 0 payload changes across all 33 catalog leagues, and it bites.

**The platform dimension exists; the second implementation does not** (the `kind` pattern again).
`jobs.platform`, discovery behind one platform-taking function, a `{platform, handle, league_id}`
contract, and a tab row where a second live platform is an addition. Deliberately deferred and stated
as decisions: no `platform` on `user_leagues`/`league_catalog`/the 14 data tables, no namespaced league
ids. → `projects/post-v1/other-platforms.md`.

**Two bugs the live proof caught that no gate would have.** (1) The lease's `RETURNING` never included
`requested_by`/`platform_user_id`, so the worker built the league, landed `ready` and **granted nobody
anything** — no error in the table, the logs or the screen. (2) `check_queue --live` was reporting two
FAILURES of a queue that was working: the live worker drains the same table the gate writes to and took
its throwaway rows (measured, leased **0.12s** after the INSERT). Those legs are now **UNEVALUATED**,
not failed — unknown is not pass, and it is not failure either.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S4C_REPORT.md`.

**Gate A is unblocked, and S4c narrowed what it still owns.** Loading the first real 2026 league at
Will's draft (~late Aug) is now a **job row** a user creates themselves. It data-proves S2's refresh,
S3b's band panel and S4a's regimes at once, and **must verify the ROS-range panel against real band
data**. **A supported 2026 league already exists on Sleeper and discovery marks it linkable** — what is
still untested is the combination Gate A owns: a *cold* 2026 league with **0 completed weeks**, whose
join/spine/schedule stages have never run against an empty season. (Market turn-on stays post-launch.)
→ `ROADMAP.md` + `projects/v1/BUILD_ORDER.md` + `projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md`.

## The demo, visibility, and what a signed-in user sees (decided 2026-08-05; **built in S2a + S2b**)

The model is now code — the mechanism lives in `ARCHITECTURE.md` and `appendices/auth.md`, not here.
Nothing from that decision is outstanding: the season selector was the last piece and went in S2e.

- **The 31 corpus slices stay in the database** — engineering fixtures for `compute_demo_slices`,
  `build_demo_manifest`, B6's 31/31 and `check_scoped_reload`'s parity oracle. Only the public catalog
  shrank. Nothing was deleted.

**The demo clone shipped in S2d** — real computed data everywhere it exists, identities fictional, and
`is_synthetic()` keeps it invisible to every producer (the concrete hazard being `weekly_refresh` trying to
fetch a league that does not exist on Sleeper). **Two pieces of the original clone brief did NOT ship and
are deliberate:** the rest-of-season band (the clone is season 2025, below `FIRST_HONEST_BAND_SEASON`, so
that panel is dark exactly as it was for the old demo) and the **synthetic AI outlook** — `ros_synthesis`
has no 2025 file, so the panel is empty by construction. **P4 stays ahead of P3** and retires that
placeholder for real.
→ `sessions/v1/P5-Self_Serve/SESSION_P5_S2D_REPORT.md` + `SESSION_P5_DEMO_LEAGUE_CLONE.md`.

## The frozen corpus was destroyed and rebuilt (2026-08-13)

A `check_store_boundary --prove-bites` run overwrote `corpus_manifest`, `corpus_discovery` and
`corpus_two_way_flags` with empty frames (0 rows **and** 0 columns) — three writers take only a
dataframe, so they had no throwaway target and hit the real and only copy. Nothing was tracked by git.
The rule this bought is `CODING_BIBLE` §5. **The L2 ledger, the raw harvest and both crawl JSONs were
untouched, and the live site was never affected.**

**Restored by offline reconstruction from surviving artifacts — zero Sleeper calls.** Nothing was
re-crawled or re-selected, so the manifest still names the population the immutable ledger was derived
from. `corpus_two_way_flags` is **EXACT** (10 rows). `corpus_manifest` is **CONSISTENT, not identical**:
271 rows, strata 221 matched / 48 generalization / 2 mine, verified against the ledger on all 270
shared league-seasons with **0 `scoring_key` mismatches**. Gates green — `check_corpus`, `check_harvest`,
`check_spine` (269 leagues), `check_matchup_result --full-corpus` (271 swept, 4 ties);
`check_predictions` keeps its **one known pre-existing red** (the is_mine 2024 slice), which is the
correct outcome — a green there would have meant the reconstruction dropped that row.

**Not recovered, and not faked:**
- **`corpus_discovery` is LOST and deliberately not reconstructed.** The crawl state is the frontier at
  save time, not a record of what was discovered (it misses 320 of the 427 judged leagues), so any
  rebuild would be *wrong*, not partial. **Corpus selection can no longer be re-run against the July
  universe; any future re-selection defines a NEW corpus, not a continuation of this one.**
  `corpus_crawl_state.json` + `corpus_filter_cache.json` are now its authoritative surviving record.
- **`league_format` is NULL on 36 of 271 rows** (all generalization). Sleeper's `settings.type` was
  never persisted, and absence on disk does **not** mean redraft — 7 known keeper/dynasty leagues also
  lack the key. No stratum, gate or partition depends on it. A 36-call targeted top-up would fill it.
- **`selected_at`** is wall-clock and lost for every row — this is why the verdict is CONSISTENT.
- The ~41 `excluded` rows were never harvested, so they are omitted rather than invented. **Consequence:
  `check_corpus`'s filter pass-rate line now reads `100.0% over 269` instead of `86.8% over 310` — that
  tooth is vacuous and is not evidence of anything.**

**`application/data/snapshots/corpus/` is now tracked in git** (a `.gitignore` carve-out; the blanket
exclusion stays) — ~281 KB of frozen provenance, closer to a lockfile than to runtime data. Note
`.git/info/exclude:9` is the operative local rule, and the data files can only be committed from `main`
(a worktree's `snapshots` is a symlink git will not descend).
→ `sessions/engine/SESSION_CORPUS_RECOVERY_REPORT.md`

**Still open, and this incident is the second time it has bitten:** irreplaceable laptop-owned state has
exactly one copy and nothing versioning it. A mirror would not have helped (a sync at 02:26 would have
pushed three empty files over three good ones) — the fix is **object versioning**, and it now covers
`derived/ledger` (145 MB, regenerable by nothing) and `derived/scoring`. Sits in P6; worth pulling
forward, and P5/S3 makes it worse by adding a second machine with write access.

## Deferred / parked (not blocking; each picked up in its project)

- **Deferred: let the join resolve a null position from the pinned registry.** `_apply_registry_eligibility`
  fires only on the *conflict* branch, so a rostered player with no `nflreadpy` row keeps a null position
  and falls to remainders — which is *why* `audit_join` synthesises repair rows at all. Coalescing the null
  retires that class, but it changes the corpus **row population** the L2 ledger grades against, and a
  refactor that changes a number is a bug until equivalence is proven. **Its own session; first deliverable
  is a corpus-wide count.** → `sessions/v1/P2-Go_Live_2026/SESSION_P2_AUDIT_JOIN_NULLS_REPORT.md`.

- **The ROS-range panel is unverified against real band data.** Everything around it is proven — the loader
  guard, the parity oracle across 14 tables, the pinned select, the absent-state — but the populated panel was
  only ever rendered from a synthetic payload stubbed into a local process. The session that loads the first
  2026 league should treat verifying it as part of its own DoD.
- **A corpus re-backfill would un-freeze 2020–2025** (annual pipeline, not a session): re-run the band under
  the live constants, re-derive the ledger's band claims as a **new-`code_version` parallel population** (the
  ledger is append-only-of-new and already supports this), then lower `FIRST_HONEST_BAND_SEASON`. Until then
  the replay seasons legitimately show no ROS range. Two known pre-existing reds live in that same corpus
  lane and are unrelated to serving: `check_predictions` (the is_mine **2024** slice is spined for the demo
  but was never backfilled into the ledger) and `backtest_ros_player_band --season 2025` (it grades the
  frozen pre-8c band, coverage 0.468 vs the 0.80 target).
- **`market_vor` has no cadence.** Nothing recomputes it — not the weekly refresh (that rebuilds the spine),
  not the collectors — yet `load_league` re-publishes it on every scoped reload. It currently trails the raw
  series by ~2 weeks and is priced against `as_of_week` 4 while the league sits at 5, so `check_market_vor`'s
  recompute-match verdict is red (it now says why). Fix when the live panel turns on.
- **Three things bite when the live 2026 market panel turns on** (S4/later): `MARKET_PROFILE` is hardcoded to
  `redraft-1qb-12t-ppr1` — deriving it from league shape is the fix for the parked **superflex QB-pool
  latent** (the feed already banks `redraft-2qb-12t-ppr1` and `ppr0_5` daily); the API hardcodes
  `max(snapshot_date)`, so the market won't replay with the week selector (cross-*week* replaces cross-*time*
  as the time-world bug); and LeagueLogs requires **"Powered by LeagueLogs API"** attribution on any UI that
  displays it — absent today, a launch blocker once the panel is ungated for real users.
- **Silent-reads confidence (the ENGINE half — post-V1).** A *native, measured* confidence column on
  `production_vor` / `player_signal` direction / `bracket_odds` wins+seed, proven monotone-honest against
  `CONF_MONO_MARGIN` and moved from `NO_CONFIDENCE_FAMILIES` into `CONF_SIGNALS`. S4a shipped the display
  half instead (state the sample, withhold what it can't support) — deliberately **not** a derived
  confidence tier, because asserting an unmeasured confidence is exactly how `ros_cv` shipped inverted.
  Note `bracket_odds.proj_wins` reaches **no client** today, so "playoff wins" has no surface to carry a
  signal until it does.
- **`matchup_win_probs` returns 50/50 whenever both σ are 0**, regardless of μ — a 30-point projected gap
  included. Pinned by `check_projections`, and it disagrees with the sim's own `_win_prob`, which returns
  1.0/0.0 there. Only reachable on a week with no projections at all.
- **`*_ppr` naming wart** — the `center_ppr` / `band_ppr` / … columns hold *league* points, not PPR; the
  rename is coupled to a frontend + schema change. → *see appendix: scoring-mechanism.*
- **Post-V1 features** — other scoring formats, dynasty, other platforms, owner-keyed dossiers, annual
  re-tune → `projects/post-v1/`.
