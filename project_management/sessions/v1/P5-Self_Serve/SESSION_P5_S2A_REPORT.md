# P5 · S2a — Ownership + the scoped catalog · session report

**Ran:** 2026-08-09 · **Brief:** `SESSION_P5_S2_OWNERSHIP_AND_ISOLATION.md` **+ its 2026-08-09 amendment**
(the amendment supersedes parts of the paste-block and kills gotcha #1) · **Commits:** 3 ·
**Merged:** yes · **Deployed:** yes, twice, by design.

> **What shipped:** leagues have owners, and `/api/leagues` — the one unscoped read — now answers per
> caller. Signed out returns exactly the demo; a signed-in user gets the demo plus their own
> current-season leagues, theirs first; a second account never sees the first's. The eleven per-panel
> reads are still open, deliberately: that is S2b.

---

## The finding that reshaped the session, before any code

The brief's proof steps 2 and 3 were **unprovable as written**, and the reason was in the data rather
than the design. Sleeper's `/v1/state/nfl` returns **2026** (fetched live). Every one of the 31 corpus
slices is **2020–2025**. So `visible = demo OR (owned AND season == current)` collapses, for every
caller, to `visible = demo` — there is no league in existence that can satisfy the owned term, and
gotcha #1's "grant user B a corpus league" contradicts the season term it sits beside.

Raised before building; Will's amendment settled it: a `CURRENT_SEASON` **process-env override**, with
the matrix run twice, and — the condition worth more than the override itself — **exercised against the
deployed app, then removed**. A test-only monkeypatch was rejected precisely because it would leave the
owned-league path never executing in production, and that path is the session.

## What was built

| | |
|---|---|
| `public.user_leagues` | `(user_id, league_id)`, cascading off `auth.users`. In `api/auth_schema.sql`, **not** the generated `serve/schema.sql`. No `season` column — a redraft `league_id` already pins one slice, and a denormalised copy would eventually disagree with `demo_manifest`. |
| `public.nfl_state_cache` | The persisted last-known-good season. A table rather than a module global because `min_machines_running = 0` erases in-process state on every scale-to-zero. |
| `settings.demo_league_id()` | Config, not a table. Repointing the demo stays one line. |
| `api/nfl_state.py` | Sleeper `/v1/state/nfl` over stdlib `urllib` (the real client imports polars + `data_layer`, which the image deliberately excludes). Fail-closed resolution. |
| `auth.optional_user` | No header → anonymous; bad token → 401; verifier down → 503. |
| `reads.visible` / `build_catalog` | The predicate and the catalog shaping, pure and importable, so the gate needs no live accounts. |
| `scripts/users.py --grant/--revoke` | Operator stand-in for S4's connect flow. |
| `api/check_ownership.py` | The committed gate, with `--live` and a prove-it-bites block. |
| `App.jsx` | +33/−10: the catalog waits for the session and follows identity changes. |

**DoD #1 cost one line.** `init_auth_schema._TABLES` already asserted both existence *and* absence from
the generated DDL over its list, so registering two tables inherited both checks:

```
public.user_leagues:  user_id uuid NOT NULL · league_id text NOT NULL · created_at timestamptz NOT NULL
public.nfl_state_cache: only_row boolean NOT NULL · season integer NOT NULL · fetched_at timestamptz NOT NULL
  ok  all 4 absent from the generated schema.sql (a full --load cannot drop them)
```

## The proofs

**The matrix, twice, over real HTTP with two real accounts** (sessions minted via admin
`generate_link` → `/auth/v1/verify` — the same exchange the browser performs when the link is clicked,
minus the mail hop):

| | `CURRENT_SEASON=2025` | unset → Sleeper says 2026 |
|---|---|---|
| signed out | demo only ✅ | demo only ✅ |
| user A | Trap 2025 **first**, then demo ✅ | demo only ✅ |
| user B | YPFL 2025 first, then demo ✅ | demo only ✅ |
| A's Trap **2024** | hidden ✅ | hidden ✅ |
| demo | visible ✅ | visible ✅ — **survives the season term** |

Cross-user: A cannot see B's league, B cannot see A's, signed-out sees neither. The
request-immunity probe — `?current_season=2025`, `?CURRENT_SEASON=2025`, an `X-Current-Season` header
and a `CURRENT_SEASON` cookie — moved nothing.

**Revoke bit an already-issued token.** Stronger than the brief asked: one access token minted for B,
then `--revoke`, then the *same* token re-queried. `['YPFL','demo'] → ['demo'] → ['YPFL','demo']` after
re-grant. Ownership is read per request, never carried in the JWT.

**Fail-closed, proven by simulated outage.** Sleeper unreachable with a cache → stale value served
(narrowing: the season only rolls forward, so stale can at worst hide a league that just became
current). Sleeper unreachable with **nothing** cached → `(None, 'unresolved')` → demo-only. It never
degrades to "no season filter".

**Prove-it-bites.** Every catalog and ordering assertion re-run against the pre-S2a unscoped builder:
**8 of 8 fail**, as they must. An isolation check that has never failed has not been tested.

**Parity — 18/18 value-identical** (not byte-identical; parsed JSON compared) against main's API running
on :8001 off the same database, for **both** the signed-out default and a signed-in user A, covering all
eleven reads plus `players/{id}`, `teams/{id}`, `managers/{id}`, `matchups/{id}` and `as_of_week`
variants. `/api/leagues` is the intentional exception.

**In the browser, no page reload:** signed out → the demo. `setSession` as A → the app switched to
**Trap** (12-tm · 4-1) with the switcher offering exactly `[Trap, League of Random People 2.0]`. Sign
out → catalog *and* selection reverted; the network trace shows requests moving from
`league_id=1207…&viewer_roster_id=1` back to `league_id=1182…&viewer_roster_id=8`. The selection was
cleared, not just the list.

## Amendment #4 — the claim that would have been true and worthless

`DEMO_LEAGUE_ID` (`1182101676608823296`) **is** `config.SLEEPER_LEAGUE_ID` **is** the `is_mine` league.
So "the signed-out default now resolves to the demo explicitly instead of falling through `MY_USERNAME`"
resolves to the *identical* league before and after the change. Reporting it as demonstrated would have
been accurate and would have proven nothing.

Proven by temporarily repointing `DEMO_LEAGUE_ID` at Trap 2025 and reading the signed-out default:

| | demo → Trap 2025 | demo → LoRP 2025 (config default) |
|---|---|---|
| `/api/league-meta` | `12-tm · PPR · 1QB`, `record: null`, `myOwner: null` | `10-tm · PPR · 1QB`, `record: 3-2`, `myOwner: spectraltoast1` |
| `/api/standings` | no `isMe` on any team | one `isMe: true` |
| catalog | `Trap` | `League of Random People 2.0` |

The default follows the **config**, not the username. Restored afterwards.

## Deployed — twice, and it ends with the override gone

`init_auth_schema` was applied to the (single, shared) Supabase database directly; `fly deploy` does not
run DDL and there is no migration mechanism.

1. **Deploy 1** — `CURRENT_SEASON = "2025"` in `fly.toml` `[env]`, plain rather than a secret. Full A/B
   matrix re-run against **https://surplusff.com/**, on deployed code.
2. **Deploy 2** — the override removed. Live confirmation that the resolved season is **2026, source
   `sleeper`**, and the signed-out catalog is exactly the demo.

## What this session did NOT do

- **The eleven per-panel reads are still open.** A caller who already knows a `league_id` can still pass
  it to `/api/players` and get data. Only the catalog is closed. That is S2b, and stating it plainly
  matters more than the green run above: S2a's proofs are about *discovery*, not *access*.
- No unowned-league 404, no `viewer_roster_id` validation, no season-selector removal, no RLS build, no
  `--emit` fix, no rate-limit reorder. No pipeline, transform, loader, engine constant or corpus change.
  No corpus slice deleted.

## For S2b

- `slice_exists` still does double duty — existence check *and*, by accident, the authorization boundary,
  because `demo_manifest` happens to hold only the demo set. S2a did not deepen the coupling; S2b separates it.
- `reads.visible` is the function to move into `slice_params`. It already takes everything it needs and
  nothing it doesn't.
- `check_ownership.py`'s fixture core is the shape `check_isolation.py` should extend: hard-code the
  endpoint list and assert it against the router's registered routes, so a loop cannot silently skip one.
- The two disposable accounts were **deleted at the end**, which is how the `ON DELETE CASCADE` was
  demonstrated. S2b will need to mint its own.
