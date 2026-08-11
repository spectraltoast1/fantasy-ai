"""Access-code signup (P5/S1b) — the gate that S1 got wrong.

**The design point, because it is not obvious.** S1's brief argued for gating at the platform
("a project that refuses to create users has no path around it") and that was right about the
mechanism and wrong about who pulls the lever — it assumed platform-signup-OFF meant Will
provisions each person by hand. It doesn't. Turn platform signup OFF and let *the API* perform
the admin action automatically when a valid code is presented. Zero human in the loop, and no
public path to account creation except through this check.

**Why not gate in the SPA.** The publishable key ships in the public bundle by design, so a
client-side check is bypassed by calling `POST /auth/v1/otp` with `create_user: true` directly.
That was the live state this session exists to fix; a line of client code is a speed bump with
the instructions printed on it.

**The code is required on every request, from everyone** — not just at account creation. That
buys a property worth more than the convenience it costs: *no valid code, no email is ever sent,
to anyone.* It also keeps one uniform path, so there is no "does this account exist?" branch to
leak whether an address is registered. Nothing is lost long-term: when signup opens to the
public, `signInWithOtp` handles create-or-send natively and this module gets deleted rather than
promoted.

**This module fails CLOSED.** Missing config, unreachable Supabase, anything unexpected — the
request is refused. (`rate_limit.py` deliberately fails open; that reasoning does not extend
here.)
"""

from __future__ import annotations

import hmac
import json
import urllib.error
import urllib.request

from fastapi import HTTPException

from application.api import settings

_TIMEOUT_S = 20

# One message for every refusal a caller can cause. A distinct "that code is wrong" would confirm
# a guess was structurally right, and a distinct "unknown address" would confirm registration —
# the enumeration oracle S1 deliberately avoided. Same words, whatever happened.
# Public since S2c: the route raises this refusal itself now, because whether the code was valid
# decides which rate-limit budget the attempt is charged to.
REFUSED = "That access code isn't right."


def _post(path: str, body: dict, *, key: str, base: str) -> tuple[int, dict]:
    """POST to GoTrue with the given key in `apikey`.

    Supabase's current keys are opaque strings rather than JWTs, so they belong in `apikey` and
    NOT `Authorization` — measured against this project: `apikey` alone 200, `Authorization`
    alone 401. Sending both only works via a compatibility path worth not depending on.
    """
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method="POST", data=json.dumps(body).encode(),
        headers={"apikey": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or "{}")
        except Exception:      # noqa: BLE001 — a non-JSON error body is still just a failure
            return err.code, {}


def code_matches(supplied: str | None) -> bool:
    """Constant-time comparison against the configured code.

    `hmac.compare_digest` rather than `==` so the comparison doesn't leak how many leading
    characters were right through timing. Returns False when no code is configured — absent
    config must never mean "everyone is welcome".
    """
    expected = settings.access_code()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied.strip(), expected.strip())


def ensure_configured() -> tuple[str, str]:
    """``(base, secret)``, or 503. Called by the route before anything else (P5/S2c).

    A deploy problem, not a caller problem — loud and distinct, because the alternative is every
    signup silently reading as a bad code for as long as nobody checks the env. It runs first so
    that an unconfigured server still says so rather than returning 403 to everyone, which is
    what the pre-S2c ordering did by having this check live inside `request_link`.
    """
    base = settings.supabase_url()
    secret = settings.supabase_secret_key()
    if not base or not secret:
        raise HTTPException(status_code=503,
                            detail="signup is not configured on this server")
    return base, secret


def request_link(email: str, code: str | None) -> None:
    """Validate the code, ensure the account exists, and send a magic link. Raises on refusal.

    The ordering matters: the code is checked *before* anything is created or sent, so an
    invalid attempt costs nothing but a row in the attempt log.

    The route validates the code before calling this — it has to, because whether the code was
    valid decides which rate-limit budget the attempt is charged to. This keeps its OWN check
    anyway: a duplicated `compare_digest` is free, and it means this function can never be
    called without one.
    """
    base, secret = ensure_configured()

    if not code_matches(code):
        raise HTTPException(status_code=403, detail=REFUSED)

    # Create the account if it isn't there. This is the admin call that makes platform-signup-OFF
    # workable without a human: it bypasses `disable_signup`, which a public `/otp` cannot.
    # `email_confirm: true` matters — an unconfirmed account still reads as a *signup* to GoTrue,
    # so a later magic link would be refused while signups are off. That exact dead end cost an
    # hour during S1.
    #
    # This creates a CONFIRMED account before the link is known to have sent, so a mailer failure
    # can leave one behind for an address nobody controls. DECIDED, P5/S2c: the ownership model
    # does not care, and nothing is built for it. An account confers nothing on its own —
    # visibility needs a grant, a grant is an operator act about a league, and signing up never
    # creates one, so an orphan account reads exactly what a signed-out visitor reads. This stops
    # being true the moment an account can claim a league BY ITSELF: if S4's connect flow ever
    # grants ownership without an operator in the loop, "confirmed" starts to carry weight and
    # this ordering becomes a real defect. Revisit at S4. → context/appendices/auth.md.
    status, body = _post("/admin/users", {"email": email, "email_confirm": True},
                         key=secret, base=base)
    already = status == 422 and "already" in json.dumps(body).lower()
    if status >= 300 and not already:
        # Includes Supabase's own address validation, which rejects e.g. example.com.
        raise HTTPException(status_code=400,
                            detail=str(body.get("msg") or "That address was rejected."))

    # Now the magic link. Uses the publishable key, exactly as the browser would: this is an
    # ordinary sign-in for an account that now definitely exists.
    pub = settings.supabase_publishable_key()
    status, body = _post("/otp", {"email": email, "create_user": False},
                         key=pub or secret, base=base)
    if status >= 300:
        if status == 429:
            raise HTTPException(
                status_code=429,
                detail="Too many emails have been sent recently. Try again shortly.")
        raise HTTPException(status_code=502,
                            detail="Could not send the sign-in email. Try again shortly.")
