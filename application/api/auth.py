"""Who is asking — token verification for the API (P5/S1).

The app has never been able to answer that question. This module is the answer: it verifies
the Supabase-issued JWT on the ``Authorization: Bearer`` header and hands routes a caller
identity. It is the *identity* half only — deciding what an identity may SEE is per-user
scoping, which is S2 and lives in the read layer, not here.

**Asymmetric, not the legacy shared secret.** Tokens are verified against the project's
published JWKS (``/auth/v1/.well-known/jwks.json``) using ES256. Supabase's current guidance
is that the shared HS256 secret is legacy; the asymmetric path means keys rotate without a
redeploy, and this API only ever holds material that can *check* a token, never *mint* one.

**Fail closed, and mean it.** No token, a bad signature, a wrong audience or issuer, or an
expired token all deny the request. So does an unreachable JWKS endpoint — a verifier that
cannot verify must not wave callers through. The one distinction worth drawing is the status
code: a token we checked and rejected is **401**; an endpoint we *couldn't* check against is
**503**, because silently 401-ing every user during a JWKS outage looks like a fleet of bad
passwords instead of an outage. Both deny access; only one is diagnosable.

**Nothing here runs at import.** Fly is scale-to-zero, so the first request after a cold start
is the one that fetches the JWKS. That fetch belongs inside the dependency, wrapped, so a
failure rejects a *request* rather than crashing the *process* and taking the public demo down
with it.
"""

from __future__ import annotations

import functools

import jwt
from fastapi import HTTPException, Request

from application.api import settings

# The JWKS is cached in-process for this long. Long enough that a warm machine isn't
# re-fetching per request; short enough that a key rotation is picked up without a redeploy,
# which is the whole reason for using JWKS over a pinned secret.
_JWKS_TTL_S = 600
_JWKS_TIMEOUT_S = 10

_ALGORITHMS = ["ES256"]
_AUDIENCE = "authenticated"   # what Supabase stamps on a signed-in user's access token


@functools.lru_cache(maxsize=2)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """The cached JWKS client for one URL.

    Constructing it does no network I/O — the fetch happens on first key lookup — so this is
    safe to build lazily on a request. ``lru_cache`` is what makes the key cache survive
    between requests; it does not cache exceptions, so a failed run is retried rather than
    poisoning the process.
    """
    return jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=_JWKS_TTL_S,
                           timeout=_JWKS_TIMEOUT_S)


def bearer_token(request: Request) -> str | None:
    """The bearer token on the request, or None if there isn't a well-formed one."""
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def verify_token(token: str, *, supabase_url: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Raises ``jwt`` exceptions on a bad token and ``PyJWKClientConnectionError`` when the JWKS
    can't be fetched — the caller maps those to 401 and 503 respectively. ``require`` is
    explicit so a token that simply *omits* a claim is rejected rather than skipping the
    check for it, which is the classic way a JWT gate turns out to have no teeth.
    """
    base = supabase_url.rstrip("/")
    signing_key = _jwks_client(f"{base}/auth/v1/.well-known/jwks.json").get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_ALGORITHMS,
        audience=_AUDIENCE,
        issuer=f"{base}/auth/v1",
        options={"require": ["exp", "sub", "aud", "iss"]},
    )


def current_user(request: Request) -> dict:
    """FastAPI dependency: the verified caller, or an HTTPException.

    Mirrors ``routes.slice_params`` — a plain sync function returning a dict the route
    consumes. Returns ``{"id", "email", "claims"}``; ``id`` is the Supabase user id (``sub``),
    which is the key S2's ownership model will hang off.
    """
    base = settings.supabase_url()
    if not base:
        # A deploy problem, not a caller problem. Loud on purpose: the alternative is every
        # request 401-ing and looking like an auth bug for as long as nobody checks the env.
        raise HTTPException(status_code=503,
                            detail="auth is not configured (SUPABASE_URL unset)")

    token = bearer_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail="missing bearer token")

    try:
        claims = verify_token(token, supabase_url=base)
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(status_code=503, detail="cannot reach the token verifier") from exc
    except Exception as exc:      # noqa: BLE001 — every other failure is a rejected token
        raise HTTPException(status_code=401, detail="invalid token") from exc

    return {"id": claims["sub"], "email": claims.get("email"), "claims": claims}


def optional_user(request: Request) -> dict | None:
    """FastAPI dependency: the verified caller, or ``None`` when nobody is signed in (P5/S2a).

    The catalog has to answer both audiences from one route — the public demo must stay browsable
    signed out, and a signed-in caller must additionally see their own leagues — so it needs a
    dependency that can say "anonymous" without saying "denied".

    The distinction that matters, and it is a security one:

    - **No ``Authorization`` header at all → anonymous.** A visitor is not an error.
    - **A header that is present but invalid, expired or forged → 401**, exactly as
      ``current_user``. Degrading a bad token to "anonymous" would be strictly friendlier and
      strictly worse: it turns a broken verifier, a botched key rotation and an attacker probing
      with a forged token into the same silent "here is the demo" response. A gate whose failures
      are indistinguishable from its successes cannot be observed to be working.
    - **Verifier unreachable → 503**, likewise inherited. Denied, but still distinguishable from a
      bad credential — the S1 rule. Anonymous callers are unaffected, since nothing is verified
      for them, so a Supabase outage does not take the public demo down.
    """
    if bearer_token(request) is None:
        return None
    return current_user(request)
