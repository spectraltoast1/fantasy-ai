"""Rate limiting for the signup endpoint (P5/S1b).

**What it is actually defending.** The access code is chosen to be sayable out loud — Will texts
it — so it is low-entropy by construction. This limiter is what makes that safe: brute-force
resistance first, protection of the email send budget second. Custom SMTP raises Supabase's own
ceiling to 30 messages/hour, and exhausting that is a denial-of-sign-in against real users, so
both jobs matter.

**Why the state is in Postgres and not a dict.** `fly.toml` runs TWO machines with
`min_machines_running = 0` and `auto_stop_machines = "stop"`. In-process state would be split
across both (an attacker gets ~double the budget, and the count is nondeterministic, which also
makes "the limit bites" flaky to demonstrate) and, worse, ERASED whenever a machine stops — so
the limiter could be reset by waiting out the idle window. A limiter you defeat by being patient
is not a limiter. One extra round-trip on a rare endpoint is a cheap price for one that works.

**Fail open, deliberately, and only here.** If the attempt log is unreachable the request is
allowed rather than refused: this is a *nuisance* control, not an authorization control, and the
access code is what actually decides admission. Failing closed would turn a database hiccup into
"nobody can sign in", which is a worse outcome than a brief unmetered window. That reasoning does
NOT extend to the code check in `signup.py`, which fails closed.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from application.api import db

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


def check(request: Request, email: str) -> None:
    """Raise 429 if this email or IP has attempted too often. Silent when under the limit."""
    ip = client_ip(request)
    try:
        row = db.fetch_all(_COUNTS, {"email": email, "ip": ip, "mins": _WINDOW_MINUTES})[0]
    except Exception:      # noqa: BLE001 — see the module docstring: fail OPEN here, only here
        return
    over_email = (row["by_email"] or 0) >= _MAX_PER_EMAIL
    over_ip = (row["by_ip"] or 0) >= _MAX_PER_IP
    if over_email or over_ip:
        # The same message either way: which limit was hit is itself a signal about what else
        # has been tried from this address.
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again in an hour.",
            headers={"Retry-After": str(_WINDOW_MINUTES * 60)},
        )


def record(request: Request, email: str, *, ok: bool) -> None:
    """Log an attempt. Never raises — a failure to record must not fail the request."""
    try:
        db.execute(_RECORD, {"email": email, "ip": client_ip(request), "ok": ok})
    except Exception:      # noqa: BLE001
        pass
