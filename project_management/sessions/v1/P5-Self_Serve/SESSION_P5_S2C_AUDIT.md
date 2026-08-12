# P5 · S2c — PM audit of the punch-list session

**Audited:** 2026-08-11 · **Report:** the S2c session report · **Brief:** `SESSION_P5_S2C_PUNCH_LIST.md`
(+ its 2026-08-11 amendment) · **Range:** `fe061a3..bfd3781` (3 commits + merge) ·
**Verdict: ENDORSED.** One finding, one correction to a PM error, one item for P6.

## Verified independently (not read from the report)

1. **Live, from outside the repo:** `GET https://surplusff.com/health` →
   `{"status":"ok","season":2026,"season_source":"derived"}`. One line confirms three things: the
   derivation shipped, it is deployed, and **no `CURRENT_SEASON` override is set in production**. This is
   F7's whole point paying off — F6's fix was checkable without the repo, by anyone, at any time.
2. **`nfl_state.py` is gone, and *staying* gone is now a gate.** `check_ownership` asserts both that the
   file does not exist and — via `ast`, after Code caught its own grep version failing on a comment — that
   nothing imports it. The remaining `nfl_state` hits in `application/ai/*` are `fetchers/news._nfl_state`,
   an unrelated function in the collection path.
3. **The `visible()` None branch survived with its *reason* replaced, which was the actual ask.** The
   comment now states the contract — total for every input, deny is the safe direction, "unreachable is a
   claim about every caller", and `int(None)` raising *inside an authorization predicate* is a 500 rather
   than a clean error. No mention of Sleeper, caches or outages; none of them exist any more.
4. **`/api/me`'s docstring is fixed, and better than asked.** It now carries a forward pointer — *"if you
   are reading this to decide whether something is protected, the answer lives in
   `reads.authorize_slice`, not here"* — which is what stops the same drift recurring.
5. **The cascade is asserted, not measured.** `pg_constraint.confdeltype = 'c'` read directly (with a
   comment on why not `information_schema`), plus an orphan count that reports **UNAVAILABLE** rather than
   passing silently when it cannot run. That closes S2a-audit F2 properly.
6. **The 401 check is split correctly** — offline accepts 401 *or* 503 because the config may genuinely be
   absent; `--live`, where it cannot be, requires **401** specifically.
7. **Item 9 is decided in both places with its tripwire** — `appendices/auth.md` and the `email_confirm:
   true` call site in `signup.py`, each carrying "revisit at S4 if an account can ever claim a league by
   itself". A decision with an expiry condition, which is what stops it coming back as a surprise.
8. **`/health` is DB-free by construction now** — `os.environ` plus the calendar, no I/O — so the runbook's
   diagnostic (health up + app broken = Supabase; health down = Fly) is stronger than it was.

## Finding — the refusal counter is per-machine, and nothing says so

`reads._denied_reads` is a module global. Its comment explains *why* it is in-process (no DB write on an
unauthenticated path; both refusal branches increment identically so it cannot rebuild the timing oracle)
— all still correct. What it does not say is that **there are two machines**, so `denied_reads()` is a
**floor, roughly half the real count**, and which half depends on routing.

That was my design call in the S2b brief and it stays right — a shared counter would mean a database write
on an unauthenticated path. But the number has to be read as a floor, and the only place that can say so is
the comment. One line. **Fold into the next session that touches `reads.py`.**

## Where the PM was wrong — the machine count

`context/OPERATIONS.md` said **one** Fly machine, and reasoned from it that the bill was structurally
capped because "there is nothing to scale into". That was the PM's, written from `fly.toml` declaring no
count plus Will's recollection. **Neither of us measured it. `fly scale show` says two.**

The conclusion survives — two is a *fixed* count, not a scaling ceiling, so the bound holds at roughly
double a very small number, and a free-tier Supabase still cannot bill at all. The reasoning does not, and
a **runbook is the worst place for an unverified number**, because the person reading it is under stress
and will not re-derive it. Both docs now carry the measurement *and its date*, which is the right shape.

**The pattern worth naming:** this is the second time a documented figure here turned out never to have
been measured — the S1b audit caught the *citation* being wrong and nobody checked the *number* it cited.
Correcting a citation is not verifying a fact.

## For P6

**Two machines means two connection pools against a free-tier Postgres**, which has a modest connection
cap. Probably fine at default pool sizes, but Supabase refusing connections is the one failure mode that
does not self-heal, so it belongs on P6's list rather than nowhere. → `P6_LAUNCH_HARDENING.md` S3.

## Loose ends

- `scripts/users.py` has no `--delete`, so removing a test account needs the Supabase dashboard (Will did
  it manually). The capability exists in the check scripts but not the operator tool. **Belongs with S4**,
  which owns account lifecycle.
- `.git/_stale_locks` holds ~22 quarantined files. Safe to `rm -rf`; the sweep is now a closedown step.
