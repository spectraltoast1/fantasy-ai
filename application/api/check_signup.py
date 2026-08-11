"""Prove the access-code check bites (P5/S1b, extended S2c). DB-free, network-free, no Supabase.

Companion to `check_auth.py`. That one proves a token can't be forged; this one proves a code
can't be guessed, mistyped past, or slipped around. The live half — that a direct
`POST /auth/v1/otp` with `create_user: true` is refused by the platform — is in the session
report, because it can only be shown against the real project.

**P5/S2c adds the ORDER of the checks**, which S1b's audit found was the limiter's own worst bug:
the email limit ran before the access code was validated and was keyed on a caller-supplied
address, so five garbage-code attempts locked a real person out of sign-in for an hour. Both
halves are asserted here — a bad code cannot spend somebody else's budget, and the IP limit still
bounds brute force — because a refusal alone proves nothing.

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
    msg = signup.REFUSED
    leaky = [w for w in ("close", "almost", "length", "character", "exists", "registered",
                         "unknown", "not found") if w in msg.lower()]
    if leaky:
        _fail(f"refusal message leaks {leaky}: {msg!r}")
    else:
        _ok(f"one uniform refusal, nothing about why: {msg!r}")


# --- the ORDER of the checks, which is a rule and not a detail (P5/S2c, S1b audit) ----------
#
# Driven entirely from fixtures: a fake attempt log, a fake request, and the real route function.
# No database, no server, no email. That matters more here than anywhere else in this file — the
# bug being fixed is an ORDERING bug, and an ordering you can only exercise against a live
# Supabase is one nobody re-checks after the session that wrote it.

VICTIM = "someone@example.com"
ATTACKER_IP = "203.0.113.9"


class _FakeRequest:
    """Enough of a Request for `rate_limit.client_ip`."""

    def __init__(self, ip: str = ATTACKER_IP):
        self.headers = {"fly-client-ip": ip}
        self.client = None


class _FakeLog:
    """The `signup_attempts` table, in a list — including its NULL-email semantics.

    The whole mechanism turns on a NULL email being invisible to the per-email count while the
    per-IP count still sees it, so the fake reproduces exactly that rather than approximating it.
    """

    def __init__(self):
        self.rows: list[tuple[str | None, str | None]] = []

    def counts(self, params):
        return {"by_email": sum(1 for e, _ in self.rows if e is not None and e == params["email"]),
                "by_ip": sum(1 for _, i in self.rows if i is not None and i == params["ip"])}

    def record(self, request, email, *, ok):
        from application.api import rate_limit
        self.rows.append((email, rate_limit.client_ip(request)))


def _attempt(log: _FakeLog, email: str, code: str | None, *, legacy: bool = False) -> int:
    """Run one POST /api/signup against the fake log. Returns the HTTP status it would produce.

    `legacy=True` reproduces the PRE-S2c ordering — email limit first, wrong codes charged to the
    address — which is what the prove-it-bites block needs.
    """
    from fastapi import HTTPException

    from application.api import rate_limit, routes, signup

    request = _FakeRequest()
    saved_counts, saved_record = rate_limit.counts, rate_limit.record
    rate_limit.counts = lambda req, em, **_: log.counts(
        {"email": em, "ip": rate_limit.client_ip(req)})
    rate_limit.record = log.record
    # Stop at the send: everything after the code check is a network call to Supabase, and this
    # gate proves the ORDER of the checks in front of it.
    saved_link, saved_cfg = signup.request_link, signup.ensure_configured
    signup.request_link = lambda *_a, **_k: None
    signup.ensure_configured = lambda: ("https://example.test", "key")
    try:
        if legacy:
            counted = log.counts({"email": email, "ip": rate_limit.client_ip(request)})
            if counted["by_email"] >= rate_limit._MAX_PER_EMAIL: return 429
            if counted["by_ip"] >= rate_limit._MAX_PER_IP: return 429
            ok = signup.code_matches(code)
            log.record(request, email, ok=ok)      # the bug: charged to the ADDRESS either way
            return 200 if ok else 403
        routes.signup_request(request, {"email": email, "code": code})
        return 200
    except HTTPException as exc:
        return exc.status_code
    finally:
        rate_limit.counts, rate_limit.record = saved_counts, saved_record
        signup.request_link, signup.ensure_configured = saved_link, saved_cfg


def check_bad_codes_cannot_lock_an_address_out(*, legacy: bool = False) -> None:
    print("\nfive bad codes must NOT stop that address signing in with the right one")
    log = _FakeLog()
    codes = [_attempt(log, VICTIM, "hunter2", legacy=legacy) for _ in range(5)]
    if codes == [403] * 5:
        _ok("five wrong codes → 403 each, no email sent")
    else:
        _fail(f"five wrong codes produced {codes}, expected five 403s")

    charged = log.counts({"email": VICTIM, "ip": ATTACKER_IP})
    if charged["by_email"] == 0:
        _ok("the victim's email budget is UNTOUCHED by attempts that had no valid code")
    else:
        _fail(f"{charged['by_email']} bad-code attempts were charged to the address — "
              "a stranger can spend a real person's allowance")
    if charged["by_ip"] == 5:
        _ok("all five are charged to the attacker's own IP instead")
    else:
        _fail(f"the IP budget shows {charged['by_ip']} of 5 — brute-forcing is not bounded")

    status = _attempt(log, VICTIM, CODE, legacy=legacy)
    if status == 200:
        _ok("…and the victim then signs in with the CORRECT code — the lockout is gone")
    else:
        _fail(f"the victim was refused ({status}) despite holding the right code — LOCKED OUT")


def check_the_ip_limit_still_bites(*, legacy: bool = False) -> None:
    print("\nthe IP counter must still bite — and bite a caller who knows the code")
    log = _FakeLog()
    from application.api import rate_limit
    seen = [_attempt(log, f"x{i}@example.com", "hunter2", legacy=legacy)
            for i in range(rate_limit._MAX_PER_IP)]
    if all(s == 403 for s in seen):
        _ok(f"the first {rate_limit._MAX_PER_IP} wrong codes are refused as wrong codes")
    else:
        _fail(f"unexpected statuses below the IP limit: {sorted(set(seen))}")

    if _attempt(log, "x99@example.com", "hunter2", legacy=legacy) == 429:
        _ok(f"attempt {rate_limit._MAX_PER_IP + 1} from that IP is rate-limited (429)")
    else:
        _fail("the IP limit did not bite — the access code can be brute-forced")

    if _attempt(log, VICTIM, CODE, legacy=legacy) == 429:
        _ok("and a CORRECT code from that IP is refused too — knowing the code is not a bypass")
    else:
        _fail("a correct code walked past the IP limit — the limit is advisory, not a limit")


def check_prove_bites() -> None:
    print("\nprove-it-bites — the SAME assertions against the PRE-S2c ordering")
    before = len(_failures)
    check_bad_codes_cannot_lock_an_address_out(legacy=True)
    check_the_ip_limit_still_bites(legacy=True)
    caught = len(_failures) - before
    del _failures[before:]          # those failures are the expected result, not real ones
    if caught:
        print(f"  ok  the pre-S2c ordering fails {caught} of these assertions, as it must")
    else:
        _fail("the OLD ordering passed every one of these — the checks prove nothing")


def main() -> int:
    print("=== check_signup: does the access-code gate actually bite? ===")
    os.environ["ACCESS_CODE"] = CODE
    try:
        check_accepts_the_right_code()
        check_rejects_wrong_codes()
        check_fails_closed_without_config()
        check_constant_time_compare()
        check_refusal_is_uniform()
        check_bad_codes_cannot_lock_an_address_out()
        check_the_ip_limit_still_bites()
        check_prove_bites()
    finally:
        os.environ.pop("ACCESS_CODE", None)
    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — wrong, near-miss, empty, absent and mis-cased codes all refused, an "
          "unconfigured server refuses everyone, a bad code cannot spend somebody else's email "
          "budget, the IP limit still bounds brute force even for a caller holding the code, and "
          "the pre-S2c ordering fails these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
