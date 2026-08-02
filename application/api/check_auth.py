"""Prove the auth gate has teeth (P5/S1). DB-free, network-free, no Supabase project needed.

A gate nobody watched fail is not a gate. This mints real ES256 tokens against a throwaway
keypair and feeds the verifier the ways a token can be wrong — bad signature, expired, wrong
audience, wrong issuer, missing claims, malformed header — then checks each is REJECTED, and
that a correct token is accepted. The JWKS lookup is stubbed, so this proves the verification
logic rather than the network.

Companion to the live curl transcript in the session report: this proves the verifier;
that proves the wiring.

    application/api/.venv/bin/python -m application.api.check_auth
"""

from __future__ import annotations

import datetime as dt

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from application.api import auth

_URL = "https://project.supabase.co"
_ISS = f"{_URL}/auth/v1"
_SUB = "11111111-2222-3333-4444-555555555555"

_REAL_KEY = ec.generate_private_key(ec.SECP256R1())
_OTHER_KEY = ec.generate_private_key(ec.SECP256R1())   # a validly-signed token from the WRONG issuer

_failures: list[str] = []


class _StubSigningKey:
    def __init__(self, key):
        self.key = key


class _StubJWKSClient:
    """Stands in for the network: always returns the one public key we signed the good token with."""

    def get_signing_key_from_jwt(self, _token):
        return _StubSigningKey(_REAL_KEY.public_key())


def _claims(**over) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    base = {"sub": _SUB, "email": "someone@example.com", "aud": "authenticated", "iss": _ISS,
            "iat": now, "exp": now + dt.timedelta(hours=1)}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def _mint(key=None, **over) -> str:
    return jwt.encode(_claims(**over), key or _REAL_KEY, algorithm="ES256")


def _ok(msg: str) -> None:
    print(f"  ok  {msg}")


def _fail(msg: str) -> None:
    _failures.append(msg)
    print(f"  ✗   {msg}")


def _rejects(label: str, token: str) -> None:
    """The gate must refuse this token."""
    try:
        auth.verify_token(token, supabase_url=_URL)
    except Exception as exc:                      # noqa: BLE001 — any rejection is a pass
        _ok(f"rejects {label} ({type(exc).__name__})")
    else:
        _fail(f"ACCEPTED {label} — the gate does not bite")


def check_accepts_a_valid_token() -> None:
    print("\nthe happy path (so the rejections below mean something)")
    claims = auth.verify_token(_mint(), supabase_url=_URL)
    assert claims["sub"] == _SUB, f"sub round-trip: {claims.get('sub')}"
    assert claims["email"] == "someone@example.com", f"email round-trip: {claims.get('email')}"
    _ok("accepts a correctly-signed, unexpired, right-audience token")


def check_rejects_bad_tokens() -> None:
    print("\nthe ways a token can be wrong")
    _rejects("a token signed by the WRONG key (forged)", _mint(key=_OTHER_KEY))
    _rejects("an EXPIRED token",
             _mint(exp=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)))
    _rejects("a token with no `sub`", _mint(sub=None))
    _rejects("a token with no `exp`", _mint(exp=None))
    _rejects("a token for the WRONG audience", _mint(aud="anon"))
    _rejects("a token from the WRONG issuer", _mint(iss="https://evil.example.com/auth/v1"))
    _rejects("structural garbage", "not-a-jwt")
    _rejects("an `alg: none` token (the classic JWT bypass)",
             jwt.encode(_claims(), key=None, algorithm="none"))


class _Req:
    """The one thing `bearer_token` touches, without dragging in a Starlette scope."""

    def __init__(self, header=None):
        self.headers = {"authorization": header} if header else {}


def check_header_parsing() -> None:
    print("\nheader parsing")
    cases = {"no Authorization header at all": None, "an empty Bearer": "Bearer ",
             "the wrong scheme": "Basic abc123", "a bare token with no scheme": "abc123"}
    for label, header in cases.items():
        if auth.bearer_token(_Req(header)) is None:
            _ok(f"no token from {label}")
        else:
            _fail(f"extracted a token from {label}")
    if auth.bearer_token(_Req("Bearer abc.def.ghi")) == "abc.def.ghi":
        _ok("extracts the token from a well-formed header")
    else:
        _fail("failed to extract a well-formed bearer token")


def main() -> int:
    print("=== check_auth: does the token gate actually bite? ===")
    auth._jwks_client = lambda _url: _StubJWKSClient()   # stub the network, keep the logic
    check_accepts_a_valid_token()
    check_rejects_bad_tokens()
    check_header_parsing()
    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — every malformed, forged, expired and mis-scoped token was rejected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
