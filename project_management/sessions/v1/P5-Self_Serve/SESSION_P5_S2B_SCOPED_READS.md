# V1 · P5 · Session S2b — Scoping the eleven reads — a brief for Code

**Written 2026-08-11** against what S2a actually shipped, not an assumed shape (that is how S1 went wrong).
**Status:** ready to run · **Owner:** Code drives; Will does one before/after check by URL.
**Prior:** `SESSION_P5_S2A_OWNERSHIP_AND_CATALOG.md` + `SESSION_P5_S2A_AUDIT.md` (its inbox).
**Next:** `SESSION_P5_S2C_PUNCH_LIST.md` · `SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md`.

> **What this session does:** S2a closed **discovery** — you can no longer *find* a league that is not
> yours. This closes **access**. Today a caller who already knows a `league_id` can pass it to
> `/api/players` and get the data back. This is the only real security exposure on the live site.

## The timing reality

Drafts land ~late Aug (**Gate A**, ~2 weeks); Week 1 is **Thu 10 Sept**. Velocity is not the constraint —
Will runs several Code sessions a day. **This session's constraint is proof, not speed.** The standing
instruction stands: *do not let a fast cadence compress the security work; isolation bugs fail silently.*
S2d has the nearer hard deadline (Gate A) but S2b runs first, because the hole gets harder to close as
more is built on top of it.

## The eleven reads — named, because "all reads" means "the ones the loop reached"

`/api/weeks` · `/api/league-meta` · `/api/players` · `/api/players/{sleeper_id}` · `/api/standings` ·
`/api/teams/{roster_id}` · `/api/managers/{roster_id}` · `/api/league` · `/api/positional-talent` ·
`/api/matchups` · `/api/matchups/{matchup_id}`

All eleven take `Depends(slice_params)` and none of them takes an identity today. `/api/leagues` was
closed by S2a. `/api/me` (S1) and `POST /api/signup` (S1b) are not slice reads and are out of scope.

## Your part, Will — spelled out

**Before it starts — nothing. CONFIRMED by Will 2026-08-11:** Code uses two disposable accounts,
`willdaniel.wrd+s2b-a@gmail.com` and `willdaniel.wrd+s2b-b@gmail.com`, minted via admin `generate_link`
and **deleted at the end**. (S2a deleted its pair to prove the cascade, so it cannot reuse them.) Will's
real account is **not** in the matrix — it stays the clean baseline.

**Right now, before Code starts — see the bug exist (30 seconds).** Open this in your browser:

> `https://surplusff.com/api/standings?league_id=1207735666645946368`

That is **Trap 2025 — a league you do not own**, and today it returns its standings as JSON. That is the
hole. Take a screenshot, or just note that data came back.

**After Code deploys — see it gone (2 minutes, all in the address bar).** This is the eyeball, and it is
the API rather than the UI on purpose: the app not *offering* you a league proves nothing about whether
the server would *serve* it.

1. **Signed out** (private window), open the same URL. → **404**, and the message must be the *same*
   "unknown league_id" you get for a league that does not exist. Compare it against
   `https://surplusff.com/api/standings?league_id=9999999999999999999` — the two responses should be
   indistinguishable.
2. **Signed in as yourself**, same URL again. → still **404**. Being logged in is not ownership.
3. **Signed in as yourself**, the demo: `https://surplusff.com/api/standings` (no `league_id`). → **data**.
   The public demo still works, and this is the half a refusal alone cannot prove.
4. **Load `https://surplusff.com/` normally** and click through League → Matchups → Teams → Players. →
   everything renders. If any panel shows "Loading…" forever, stop and tell me — that is the failure mode
   this session is most likely to introduce (see note 1 below).

If step 1 or 2 returns data, the session failed regardless of what the report says.

## Decisions I made for you (Code: follow unless you hit a reason not to)

1. **`slice_params` gains the identity and becomes the one authorization seam.** It already 404s an
   unknown `league_id`; it now also takes `Depends(auth.optional_user)` and applies `reads.visible`.
   One function, one place to get it wrong, one place to test.
2. **An unowned league returns the SAME 404 as a nonexistent one** — same status, **same body, same
   headers**. A 403 confirms existence, and Sleeper ids are guessable. Assert the byte-equality; this is
   the claim the whole no-enumeration design rests on and nobody has checked it.
3. **Make the work symmetric.** A nonexistent league costs one query; an existing-but-unowned league
   costs two. Run both lookups before deciding, so the response time does not leak what the status code
   does not. Impractical to exploit over the internet — but this session is writing the path anyway.
4. **No rate limit on the 404.** Settled with Will 2026-08-11. Blind enumeration is implausible (19-digit
   ids, ~31 leagues); the realistic attacker knows one id and needs one request, so a cap misses them.
   It also fires after everything but the last query is paid for — blocking belongs at the edge
   (Cloudflare, P6/S4). And a cap keyed on caller-supplied input is the S1b bug, still open as S2c #2.
   **Count unowned attempts, act on nothing.** A counter has no direction and can't be pointed at anyone.
5. **F4 first, before the function moves.** `visible()` converts the row's `league_id` to text but not the
   members of `owned`, so an int-typed set silently matches nothing. One line inside the function
   (`owned = {str(x) for x in owned}`) — do it before adding eleven new call sites, not after.
6. **`viewer_roster_id` is validated against the visible slice, not trusted.** `resolve_viewer` currently
   does `int(viewer_roster_id)` on whatever it is handed. Check the roster exists in that league's
   `teams`; reject with the same 404 if not. Validate the slice, not the seat.
7. **The viewer seat becomes a user × league property** — `user_leagues` gains a **nullable `roster_id`**,
   `--grant` takes an optional third argument, and `resolve_viewer` prefers it when present, falling back
   to `MY_USERNAME` (which preserves demo parity exactly). **`CREATE TABLE IF NOT EXISTS` will NOT add a
   column to the existing table** — this needs an explicit `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, and
   that is precisely the S2a-audit F2 trap. S4's connect flow writes the same column from the other side.
8. **Fix the client's token handling here, not in S2c.** See note 1 — S2b is what makes it severe, so
   S2b carries the mitigation.

## The brief to paste to Code — S2b

```
Goal: V1 Project 5, Session S2b (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — close ACCESS.
S2a scoped the catalog so you cannot DISCOVER someone else's league; today you can still READ one by
passing its league_id to any of the eleven per-panel reads. This session makes every read inherit the
visibility predicate, and spends its whole proof budget on an adversarial matrix.

Read first: sessions/v1/P5-Self_Serve/SESSION_P5_S2B_SCOPED_READS.md (this brief),
SESSION_P5_S2A_AUDIT.md (its 7 findings are this session's inbox), SESSION_P5_S2A_OWNERSHIP_AND_CATALOG.md
(the settled model at the top is not up for re-derivation), context/CODING_BIBLE.md, SESSION_GUIDE.md.
Check the brief against observable reality before executing — S1's failure chain started with a
documented intent that no longer matched the live system.

Build:
- FIRST, one line: reads.visible() must normalise BOTH sides of the ownership test (owned = {str(x) for
  x in owned}). It stringifies the row's league_id but not the set; an int-typed set silently matches
  nothing. Do this before adding call sites, not after.
- slice_params takes Depends(auth.optional_user) and applies reads.visible to a caller-supplied
  league_id. It is the ONE authorization seam — do not repeat the check per route.
- An unowned league returns the SAME 404 as a nonexistent one: same status, same body, same headers.
  Assert the equality in the check, do not eyeball it.
- Symmetric work: run both the existence lookup and the ownership lookup before deciding, so timing does
  not leak what the status code does not.
- Separate slice_exists from the authorization boundary. It is doing both jobs today only because
  demo_manifest happens to hold the demo set; a real user's league is not in that manifest until S4.
- Validate viewer_roster_id against the visible slice (resolve_viewer currently int()s whatever it gets).
  Same 404 on a roster that is not in that league.
- user_leagues gains a NULLABLE roster_id; scripts/users.py --grant takes an optional third arg;
  resolve_viewer prefers it and falls back to MY_USERNAME (demo parity unchanged). NOTE: CREATE TABLE IF
  NOT EXISTS will NOT add a column to the existing table — use an explicit ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS, and add a verify() assertion that the column is actually present.
- Count unowned-league attempts (a counter, no cap, no blocking). Do NOT add a rate limit — see the brief.
- CLIENT: apiGet throws on every non-2xx and the app-shell loaders only console.error, so after this
  change an expired or revoked token turns EVERY read into a permanent "Loading…", not just the catalog.
  In queries.js's apiGet: on 401/503, clear the token and retry the request ONCE anonymously. Only when a
  token was actually present. This is S2a-audit F1, pulled forward into S2b because S2b is what multiplies
  it by eleven. The error COPY and the tab-refocus fix stay in S2c.

Prove it (demonstrated, not asserted) — the deliverable is ONE committed artifact:
application/api/check_isolation.py, running EVERY read endpoint x {signed-out, owner, other user} and
asserting the matrix. Conditions:
1. Hard-code the endpoint list and ASSERT IT against the router's registered routes, so a loop cannot
   silently skip one. "All reads" in a report means "the ones the loop happened to reach".
2. A prove-it-bites block: run every assertion against the PRE-S2b behaviour and require every one to
   fail. An isolation check that has never failed has not been tested. (S2a's managed 8 of 8.)
3. Two real accounts (willdaniel.wrd+s2b-a@ / +s2b-b@, minted via admin generate_link ->
   /auth/v1/verify, deleted at the end). Grant A Trap 2025 (1207735666645946368), B YPFL 2025
   (1257433118135037952). The corpus still tops out at 2025 and S2c has not landed, so run under
   CURRENT_SEASON=2025 exactly as S2a did — set it on prod, run, then REMOVE it and redeploy.
4. Assert the unowned 404 and the nonexistent 404 are byte-identical, including headers.
5. The demo must remain readable in every state including signed-out — the half a refusal cannot prove.
6. Parity: the demo's payloads are value-identical (parsed JSON, not bytes) to main's for signed-out.

Scope guard — does NOT: remove the season selector or flatten the catalog's lineage->seasons grouping
(S2d — the demo shares a lineage with Will's league and needs its own identity first); touch any S2C
punch-list item beyond the apiGet retry named above; build RLS policies (settled: isolation is
API-layer); touch the connect flow, jobs table or worker; touch any pipeline, transform, loader or engine
constant; touch the frozen corpus; DELETE any of the 31 corpus slices — they stay as fixtures.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md, then
close/merge/push. This touches application/api/* AND application/frontend/* — so it needs a REDEPLOY and
a live confirmation on https://surplusff.com/. A merged-but-undeployed change has bitten this project
(P0/B3) and a session forgot the deploy line as recently as 2026-08-05.
```

## Definition of done

1. All eleven reads refuse an unowned `league_id` with the **same 404** a nonexistent one gets — same
   status, body and headers, asserted rather than eyeballed.
2. `check_isolation.py` is committed, runs every endpoint × {signed-out, owner, other}, asserts its
   endpoint list against the router, and its prove-it-bites block fails **every** assertion pre-S2b.
3. Cross-user separation demonstrated with two real accounts over real HTTP; both deleted afterwards.
4. `viewer_roster_id` cannot reach a slice the caller cannot see.
5. `user_leagues.roster_id` exists (asserted, not assumed — `IF NOT EXISTS` does not add columns).
6. The demo is readable in every state including signed-out, and its payloads are value-identical.
7. An expired token degrades to the public demo instead of a permanent "Loading…".
8. `CURRENT_SEASON` is set for the matrix run and **absent from the final deploy**, demonstrated.
9. Merged, **redeployed**, confirmed live — and Will's four URL checks pass.

## Notes / gotchas

1. **This session multiplies audit-F1 by eleven, which is why F1's token half moved here.** Today only
   `/api/leagues` can 401, because it is the only read taking an identity. Once `slice_params` takes
   `optional_user`, *every* read can 401 on a bad token — and `queries.js`'s `apiGet` throws on any
   non-2xx while the app-shell loaders only `console.error`. `apiGet`'s own comment says "every read
   endpoint's error is a developer problem the user never sees", which was true when reads could not fail
   for auth reasons. **S2b makes it false.** One fix at the `apiGet` seam covers all twelve.
2. **`slice_exists` is the accidental boundary.** It is both the existence check and, by coincidence of
   `demo_manifest` holding only demo slices, the authorization boundary. That coincidence dies at S4 when
   a real user's league is catalogued. Separate them here.
3. **The demo default is not authorization.** `slice_params` resolves an omitted `league_id` to
   `DEMO_LEAGUE_ID`; that is default *resolution*. The predicate still has to run on it.
4. **Do not let the fast cadence compress this.** An isolation bug does not announce itself — the app
   looks perfect while showing the wrong person's data. The matrix is the deliverable, not a formality
   around it.
