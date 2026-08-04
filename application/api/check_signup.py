"""Prove the access-code check bites (P5/S1b). DB-free, network-free, no Supabase needed.

Companion to `check_auth.py`. That one proves a token can't be forged; this one proves a code
can't be guessed, mistyped past, or slipped around. The live half — that a direct
`POST /auth/v1/otp` with `create_user: true` is refused by the platform — is in the session
report, because it can only be shown against the real project.

    application/api/.venv/bin/python -m application.api.check_signup
"""

from __future__ import annotations

import os

from application.api import signup

_failures: list[str] = []
CODE = "correct-horse-battery"


def _ok(msg: str) -> None:
    print(f"  ok  {msg}")


def _fail(msg: str) -> None:
    _failures.append(msg)
    print(f"  ✗   {msg}")


def _rejects(label: str, supplied) -> None:
    if signup.code_matches(supplied):
        _fail(f"ACCEPTED {label} — the gate does not bite")
    else:
        _ok(f"rejects {label}")


def check_accepts_the_right_code() -> None:
    print("\nthe happy path (so the rejections below mean something)")
    if signup.code_matches(CODE):
        _ok("accepts the configured code")
    else:
        _fail("REJECTED the configured code — the gate is broken shut")
    if signup.code_matches(f"  {CODE}  "):
        _ok("tolerates surrounding whitespace (people paste from a text message)")
    else:
        _fail("rejected the code with whitespace — a paste from Messages would fail")


def check_rejects_wrong_codes() -> None:
    print("\nthe ways a code can be wrong")
    _rejects("a completely wrong code", "hunter2")
    _rejects("an empty string", "")
    _rejects("None (field omitted entirely)", None)
    _rejects("a near miss — one character off", CODE[:-1] + "z")
    _rejects("a prefix of the real code", CODE[:-1])
    _rejects("the real code plus a character", CODE + "z")
    _rejects("wrong case", CODE.upper())
    _rejects("the code with an inner space", CODE.replace("-", " ", 1))


def check_fails_closed_without_config() -> None:
    print("\nabsent config must not mean 'everyone is welcome'")
    saved = os.environ.pop("ACCESS_CODE", None)
    try:
        # Neutralise the config.py fallback too, so this tests the genuinely-unset case.
        original = signup.settings._config_attr
        signup.settings._config_attr = lambda _name: None
        try:
            for label, supplied in (("the right code", CODE), ("any code", "anything"),
                                    ("an empty code", "")):
                if signup.code_matches(supplied):
                    _fail(f"ACCEPTED {label} with NO code configured — fails OPEN")
                else:
                    _ok(f"refuses {label} when no code is configured")
        finally:
            signup.settings._config_attr = original
    finally:
        if saved is not None:
            os.environ["ACCESS_CODE"] = saved


def check_constant_time_compare() -> None:
    print("\ntiming")
    import inspect
    src = inspect.getsource(signup.code_matches)
    if "compare_digest" in src:
        _ok("uses hmac.compare_digest (no early-exit on the first wrong character)")
    else:
        _fail("does NOT use a constant-time compare — a near miss is distinguishable by timing")


def check_refusal_is_uniform() -> None:
    print("\nthe refusal message")
    msg = signup._REFUSED
    leaky = [w for w in ("close", "almost", "length", "character", "exists", "registered",
                         "unknown", "not found") if w in msg.lower()]
    if leaky:
        _fail(f"refusal message leaks {leaky}: {msg!r}")
    else:
        _ok(f"one uniform refusal, nothing about why: {msg!r}")


def main() -> int:
    print("=== check_signup: does the access-code gate actually bite? ===")
    os.environ["ACCESS_CODE"] = CODE
    try:
        check_accepts_the_right_code()
        check_rejects_wrong_codes()
        check_fails_closed_without_config()
        check_constant_time_compare()
        check_refusal_is_uniform()
    finally:
        os.environ.pop("ACCESS_CODE", None)
    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — wrong, near-miss, empty, absent and mis-cased codes all refused, and an "
          "unconfigured server refuses everyone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
