"""Rate limiting for the signup endpoint (P5/S1b) and the connect flow (P5/S4c).

**What it is actually defending.** The access code is chosen to be sayable out loud — Will texts
it — so it is low-entropy by construction. This limiter is what makes that safe: brute-force
resistance first, protection of the email send budget second. Custom SMTP raises Supabase's own
ceiling to 30 messages/hour, and exhausting that is a denial-of-sign-in against real users, so
both jobs matter.

**Why the state is in Postgres and not a dict.** `fly.toml` sets `min_machines_running = 0` and
`auto_stop_machines = "stop"`, so in-process state is ERASED whenever the machine stops — the
limiter could be reset by simply waiting out the idle window, and a limiter you defeat by being
patient is not a limiter. Any machine count above one splits the budget on top of that, and the
count is a deploy-time property (`fly scale show`) rather than something this file declares — the
scale-to-zero argument alone is what decides it. One extra round-trip on a rare endpoint is a
cheap price for a limiter that works.

**Fail open, deliberately, and only here.** If the attempt log is unreachable the request is
allowed rather than refused: this is a *nuisance* control, not an authorization control, and the
access code is what actually decides admission. Failing closed would turn a database hiccup into
"nobody can sign in", which is a worse outcome than a brief unmetered window. That reasoning does
NOT extend to the code check in `signup.py`, which fails closed.

**P5/S4c adds two more budgets, and they are a DIFFERENT SHAPE — say why rather than copying.**
The signup limits key on an address and an IP because the caller is anonymous. The connect limits
key on the **authenticated user**, which the caller cannot choose at all, so none of S1b's careful
reasoning about a stranger spending somebody else's allowance applies. And what they defend is not
an email budget:

- **Connect** protects **worker minutes** — one job is ~10s of a stateful singleton that every
  other user's league is queued behind. Counted from `public.jobs` itself, because the job row IS
  the thing being limited and a counter kept beside it could drift from it.
- **Discovery** protects **our egress IP**. Each lookup is two GETs against api.sleeper.app, and
  getting throttled there stops onboarding for EVERYONE, not just the abuser — a shared-fate
  resource, which is what earns a limit on an endpoint that already requires a token. It has no
  natural record of its own, so `connect_attempts` is that record.

Both stay Postgres-backed for the scale-to-zero reason above, and both fail OPEN for the reason
above: they are nuisance controls, and the token is what decides admission.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from application.api import db, jobs

# Per identity, per window. Deliberately generous for humans and useless for a brute-forcer:
# a person mistypes a code two or three times, nobody legitimately submits fifteen in an hour.
_WINDOW_MINUTES = 60
_MAX_PER_EMAIL = 5
_MAX_PER_IP = 15          # higher than per-email: a household or office shares one address

_RECORD = """
INSERT INTO public.signup_attempts (email, ip, ok) VALUES (%(email)s, %(ip)s, %(ok)s)
"""

_COUNTS = """
SELECT
  count(*) FILTER (WHERE email = %(email)s) AS by_email,
  count(*) FILTER (WHERE ip = %(ip)s AND %(ip)s IS NOT NULL) AS by_ip
FROM public.signup_attempts
WHERE at > now() - (%(mins)s || ' minutes')::interval
"""


def client_ip(request: Request) -> str | None:
    """The caller's IP as seen from outside Fly's proxy.

    `request.client.host` is the proxy, identical for every caller, so limiting on it would
    throttle all users as one. Fly sets `Fly-Client-IP`; `X-Forwarded-For` is the fallback for
    local runs and any other front end. Both are client-supplied headers in principle — good
    enough for a nuisance control, and not load-bearing for admission.
    """
    hdr = request.headers
    ip = hdr.get("fly-client-ip") or (hdr.get("x-forwarded-for") or "").split(",")[0].strip()
    return ip or (request.client.host if request.client else None)


def counts(request: Request, email: str, *, counts_fn=None) -> dict:
    """Both counts for this caller, from ONE query, read at the same instant.

    Split from enforcement in P5/S2c because the two limits are now applied at different points
    in the request — the IP limit before the access code is validated, the email limit only after
    (see `routes.signup_request`). Counting once and enforcing twice keeps that ordering without
    paying a second round trip, and means both numbers describe the same moment.

    `counts_fn` is injectable so `check_signup` can drive the whole ordering from fixtures — the
    same reason `reads.authorize_slice` takes its `lookup`. A limiter you can only exercise
    against a live database is one whose ordering nobody re-checks.

    Fails OPEN: an unreachable attempt log returns zero counts, so nothing is refused. See the
    module docstring — this is a nuisance control, not an authorization control.
    """
    fn = counts_fn or (lambda params: db.fetch_all(_COUNTS, params)[0])
    try:
        row = fn({"email": email, "ip": client_ip(request), "mins": _WINDOW_MINUTES})
    except Exception:      # noqa: BLE001 — see the module docstring: fail OPEN here, only here
        return {"by_email": 0, "by_ip": 0}
    return {"by_email": row["by_email"] or 0, "by_ip": row["by_ip"] or 0}


def _too_many() -> HTTPException:
    # The same message either way: which limit was hit is itself a signal about what else has
    # been tried from this address.
    return HTTPException(
        status_code=429,
        detail="Too many sign-in attempts. Try again in an hour.",
        headers={"Retry-After": str(_WINDOW_MINUTES * 60)},
    )


def enforce_ip(counted: dict) -> None:
    """Raise 429 if this IP has attempted too often.

    Applied FIRST, and safe there: it is keyed on the caller's own address rather than on anything
    they can name, so it cannot be aimed at somebody else. It is also the limit that actually stops
    the access code being brute-forced, which is why it must not sit behind the code check.
    """
    if counted["by_ip"] >= _MAX_PER_IP:
        raise _too_many()


def enforce_email(counted: dict) -> None:
    """Raise 429 if this address has attempted too often — applied ONLY after a valid access code.

    **The rule this endpoint is built on: the email counter only ever counts requests that
    presented a valid code** (S1b audit). The email is caller-supplied, so counting bad-code
    attempts against it let a stranger who knew nothing but somebody's address spend that person's
    allowance and lock them out of sign-in for an hour — the limiter handing out the exact harm it
    was built to prevent. Mailbox-flood protection survives for people who do hold the code.
    """
    if counted["by_email"] >= _MAX_PER_EMAIL:
        raise _too_many()


def record(request: Request, email: str | None, *, ok: bool) -> None:
    """Log an attempt. Never raises — a failure to record must not fail the request.

    `email=None` is the bad-code case, and is the whole mechanism behind the rule above: a NULL
    email is invisible to `count(*) FILTER (WHERE email = …)` while the IP filter still counts it.
    So a wrong code costs the caller their own IP budget and costs the address nothing.
    """
    try:
        db.execute(_RECORD, {"email": email, "ip": client_ip(request), "ok": ok})
    except Exception:      # noqa: BLE001
        pass


# --- The connect flow (P5/S4c) ----------------------------------------------------------------
# Deliberately generous for humans and useless for a script. A person links one to four leagues,
# and each link is preceded by one or two lookups; nobody legitimately asks for ten builds or
# thirty lookups in an hour. Both windows match the signup window so there is one number to
# remember when somebody reports being locked out.
_CONNECT_WINDOW_MINUTES = 60
_MAX_CONNECTS_PER_USER = 10        # ~100s of a stateful-singleton worker, at S0's measured 10s
_MAX_DISCOVERIES_PER_USER = 30     # = 60 Sleeper GETs/hour/account

_RECORD_DISCOVERY = "INSERT INTO public.connect_attempts (user_id) VALUES (%(uid)s::uuid)"

_DISCOVERY_COUNT = """
SELECT count(*)::int AS n FROM public.connect_attempts
 WHERE user_id = %(uid)s::uuid AND at > now() - (%(mins)s || ' minutes')::interval
"""


def _too_many_connects(what: str, mins: int) -> HTTPException:
    """Unlike `_too_many`, this one SAYS which limit was hit — and the difference is not an
    inconsistency. The signup message is uniform because *which* limit an anonymous caller tripped
    is itself a signal about what else has been tried from that address. Here the caller is
    authenticated and is being told about their own budget, so there is nothing to leak and a
    person who cannot tell "too many lookups" from "too many links" cannot act on either."""
    return HTTPException(status_code=429, detail=f"Too many {what}. Try again in an hour.",
                         headers={"Retry-After": str(mins * 60)})


def enforce_connect(user_id) -> None:
    """Raise 429 if this account has asked for too many builds. Counted from `public.jobs`.

    Fails OPEN, like everything else in this module: an unreachable database means the enqueue
    that follows is about to fail anyway, and refusing here would replace a clear error with a
    misleading one.
    """
    try:
        n = jobs.recent_job_count(user_id, minutes=_CONNECT_WINDOW_MINUTES)
    except Exception:      # noqa: BLE001 — fail OPEN; see the module docstring
        return
    if n >= _MAX_CONNECTS_PER_USER:
        raise _too_many_connects("leagues linked recently", _CONNECT_WINDOW_MINUTES)


def enforce_discovery(user_id) -> None:
    """Raise 429 if this account has run too many platform lookups. Counted from `connect_attempts`."""
    try:
        n = db.fetch_all(_DISCOVERY_COUNT,
                         {"uid": str(user_id), "mins": _CONNECT_WINDOW_MINUTES})[0]["n"] or 0
    except Exception:      # noqa: BLE001 — fail OPEN
        return
    if n >= _MAX_DISCOVERIES_PER_USER:
        raise _too_many_connects("league lookups", _CONNECT_WINDOW_MINUTES)


def record_discovery(user_id) -> None:
    """Log a lookup. Never raises — a failure to record must not fail the request.

    Recorded BEFORE the Sleeper calls, not after: the cost this is metering is the outbound call
    itself, so a lookup that times out must still spend its budget. Recording on success only would
    make the slowest, most expensive lookups the free ones.
    """
    try:
        db.execute(_RECORD_DISCOVERY, {"uid": str(user_id)})
    except Exception:      # noqa: BLE001
        pass
