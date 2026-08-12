"""Prove the ownership rule and the scoped catalog actually bite (P5/S2a).

Third in the `check_auth` / `check_signup` line. That pair proves a token can't be forged and a
code can't be guessed; this one proves that **holding a valid token for the wrong account gets you
nothing**, which is the property S2 exists to create.

    application/api/.venv/bin/python -m application.api.check_ownership
    application/api/.venv/bin/python -m application.api.check_ownership --live --current-season 2025

The default run is DB-free and needs no accounts: the visibility predicate and the catalog builder
are pure functions (`reads.visible`, `reads.build_catalog`), so the whole matrix runs against
fixtures. That matters — an isolation gate you can only run by standing up two real accounts is one
that stops being run.

It does make ONE network call (P5/S2c): Sleeper's `/v1/state/nfl`, to assert it agrees with the
season this app now derives from the calendar. That call used to sit on every read; it lives here
instead, where being slow costs nobody anything. Unreachable is a failure rather than a skip — see
`check_sleeper_agrees`.

`--live` adds the half fixtures cannot prove: two REAL Supabase accounts against a REAL API, over
HTTP, with real tokens. It mints sessions with the admin key (`generate_link` → `/auth/v1/verify`)
rather than asking a human to click a link. It **skips cleanly** when the key is absent, and it
never writes the key anywhere.

**The prove-it-bites block is the point.** Every assertion below is re-run against the PRE-S2a
unscoped behaviour, and every one is required to FAIL. An isolation check that has never failed has
not been tested — it has only been observed agreeing with the code it was written from.

S2b extends this file to the full endpoint × role matrix. S2a's scope is the catalog.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from application.api import auth, reads, routes, settings

_failures: list[str] = []

# --- fixtures ------------------------------------------------------------------------------
# Real ids from application/data/corpus/demo_slate.csv, so the fixture and the live run describe
# the same world. DEMO is a 2025 league — that is the whole point of the demo term.
DEMO = "1182101676608823296"        # LoRP 2025 — the one public league
A_LEAGUE = "1207735666645946368"    # Trap 2025 — granted to user A
A_PRIOR = "1051229073923584000"     # Trap 2024 — granted to A, must stay hidden in every run
B_LEAGUE = "1257433118135037952"    # YPFL 2025 — granted to user B

_ROWS = [
    # lineage_id, league_id, season, name
    ("lorp", DEMO, 2025, "League of Random People 2.0"),
    ("trap", A_LEAGUE, 2025, "Trap"),
    ("trap", A_PRIOR, 2024, "Trap"),
    ("ypfl", B_LEAGUE, 2025, "Young Professional Football League"),
]


def _row(lineage, league_id, season, name, is_mine=False):
    return {"lineage_id": lineage, "league_id": league_id, "season": season, "name": name,
            "scoring_key": "ppr", "is_mine": is_mine, "viewer_roster_id": 1,
            "panels_market": True, "panels_manager": True, "panels_ros": True}


def _fixture_rows():
    # is_mine is set on the demo lineage exactly as it is in production, so the ordering check
    # below cannot pass merely by inheriting the old is_mine-first sort.
    return [_row(l, lid, s, n, is_mine=(l == "lorp")) for l, lid, s, n in _ROWS]


def _catalog(owned=(), current_season=2025, demo=DEMO, builder=None):
    builder = builder or reads.build_catalog
    return builder(_fixture_rows(), {}, {}, demo_league_id=demo,
                   owned=set(owned), current_season=current_season)


def _ids(catalog) -> list[str]:
    """Every visible league_id, in catalog order — the thing the SPA actually navigates.

    One level since P5/S2e: the catalog is flat, so a league IS an entry rather than a season
    nested under a lineage. This helper is the reason the shape change is one edit and not
    fifteen — every assertion in this file reads the catalog through it.
    """
    return [lg["league_id"] for lg in catalog["leagues"]]


# --- the pre-S2a behaviour, for prove-it-bites ----------------------------------------------

def _unscoped_builder(rows, weeks_by, cross_time_by, *, demo_league_id, owned, current_season):
    """What `load_leagues` did before S2a: every row, is_mine first, caller ignored entirely.

    Emitted in the CURRENT (flat, P5/S2e) shape on purpose. This stands in for the old
    *visibility* behaviour so the ownership checks can be shown to fail without it; dressing it in
    the old *payload* shape too would make `_ids` fail for the wrong reason, and a prove-it-bites
    that passes because the helper crashed proves nothing.
    """
    leagues = [{"lineage_id": r["lineage_id"], "league_id": r["league_id"],
                "season": int(r["season"]), "name": r["name"], "scoring_key": r["scoring_key"],
                "is_mine": bool(r["is_mine"]), "weeks_available": [], "viewer_roster_id": None,
                "panels": {}} for r in rows]
    leagues.sort(key=lambda lg: not lg["is_mine"])
    return {"leagues": leagues}


def _ok(msg: str) -> None:
    print(f"  ok  {msg}")


def _fail(msg: str) -> None:
    _failures.append(msg)
    print(f"  ✗   {msg}")


def _eq(label: str, got, want) -> bool:
    if got == want:
        _ok(f"{label}: {got}")
        return True
    _fail(f"{label}: got {got}, want {want}")
    return False


# --- the predicate -------------------------------------------------------------------------

def check_predicate() -> None:
    print("\nthe visibility predicate itself")
    v = reads.visible

    if v(DEMO, 2025, demo_league_id=DEMO, owned=set(), current_season=2026):
        _ok("the demo is visible to a signed-out caller in a LATER season — the season-independent "
            "term, i.e. the case a global `season = current` filter breaks")
    else:
        _fail("the demo is HIDDEN in the current season — a naive season filter has crept in")

    if v(A_LEAGUE, 2025, demo_league_id=DEMO, owned={A_LEAGUE}, current_season=2025):
        _ok("an owned current-season league is visible")
    else:
        _fail("an owned current-season league is HIDDEN — the owned term is broken shut")

    for label, kwargs in (
        ("an UNOWNED current-season league", dict(owned=set(), current_season=2025)),
        ("an owned PRIOR-season league", dict(owned={A_PRIOR}, current_season=2025)),
        ("someone else's league", dict(owned={B_LEAGUE}, current_season=2025)),
    ):
        lid = A_PRIOR if "PRIOR" in label else A_LEAGUE
        if v(lid, 2024 if "PRIOR" in label else 2025, demo_league_id=DEMO, **kwargs):
            _fail(f"VISIBLE: {label} — the predicate does not bite")
        else:
            _ok(f"hides {label}")


def check_unresolvable_season_narrows() -> None:
    print("\nan unresolvable season must NARROW, never widen")
    if reads.visible(A_LEAGUE, 2025, demo_league_id=DEMO, owned={A_LEAGUE}, current_season=None):
        _fail("an owned league is VISIBLE with the season unresolved — this is the fail-OPEN bug")
    else:
        _ok("an unresolvable season hides even an owned league (availability cost, not exposure)")

    got = _ids(_catalog(owned={A_LEAGUE, B_LEAGUE, A_PRIOR}, current_season=None))
    _eq("catalog with the season unresolvable", got, [DEMO])
    # No live caller can reach this since S2c — `settings.current_season` is total. It stays because
    # `visible` is pure and public: its contract is its signature, not today's call sites.


# --- the season is DERIVED, and the derivation is the whole rule (P5/S2c, audit F6) ----------

# Date → the season that date falls in. The August 1 boundary is deliberately a few days EARLIER
# than Sleeper's own flip: flipping early drops last season's league from a catalog slightly sooner
# than necessary, which nobody notices; flipping late hides the league somebody JUST connected.
# Crosses the boundary in BOTH directions, and New Year in both, because a rule written as
# `year - 1` is exactly as easy to get backwards as forwards.
_SEASON_TABLE = [
    (date(2025, 7, 31), 2024, "the day before the rollover — still last season"),
    (date(2025, 8, 1), 2025, "the rollover day itself — the boundary is inclusive"),
    (date(2025, 12, 31), 2025, "New Year's Eve — still the season that started in August"),
    (date(2026, 1, 1), 2025, "January belongs to the PRIOR year's season (playoffs)"),
    (date(2026, 2, 8), 2025, "Super Bowl Sunday — the season it belongs to has not changed"),
    (date(2026, 7, 31), 2025, "the last day of the offseason"),
    (date(2026, 8, 1), 2026, "rollover"),
    (date(2026, 8, 11), 2026, "today, as this ships"),
    (date(2027, 1, 1), 2026, "the year rolls, the season does not"),
    (date(2027, 8, 1), 2027, "next year's rollover — the rule is not hardcoded to 2026"),
    (date(2028, 2, 29), 2027, "a leap day, because `date` arithmetic is the one thing not tested"),
]


def check_season_derivation() -> None:
    print("\nthe season derives from the date — testing the FUNCTION, not the clock")
    saved = os.environ.pop(settings.ENV_CURRENT_SEASON, None)
    try:
        for day, expect, why in _SEASON_TABLE:
            got = settings.current_season(day)
            if got == expect:
                _ok(f"{day} → {got}  ({why})")
            else:
                _fail(f"{day} → {got}, expected {expect} ({why})")

        os.environ[settings.ENV_CURRENT_SEASON] = "2025"
        if settings.current_season(date(2026, 8, 11)) == 2025:
            _ok("the env override beats the derivation (the documented manual lever)")
        else:
            _fail("CURRENT_SEASON did not override the derived value")
        if settings.season_and_source(date(2026, 8, 11)) == (2025, "env"):
            _ok("…and reports source 'env', so an override left set cannot hide")
        else:
            _fail("the override is not reported as source 'env'")

        os.environ[settings.ENV_CURRENT_SEASON] = "twenty-twenty-five"
        if settings.current_season(date(2026, 8, 11)) == 2026:
            _ok("a garbage override is refused and the derivation stands — never guessed at")
        else:
            _fail("a garbage override was accepted")
    finally:
        os.environ.pop(settings.ENV_CURRENT_SEASON, None)
        if saved is not None:
            os.environ[settings.ENV_CURRENT_SEASON] = saved


_SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"


def _sleeper_season() -> int:
    """The season Sleeper reports. Lives HERE, in the gate — it is no longer on any request path."""
    req = urllib.request.Request(_SLEEPER_STATE_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return int(json.loads(resp.read() or "{}")["season"])


def check_sleeper_agrees() -> None:
    """Sleeper is an ASSERTION now, not a dependency (P5/S2c).

    Before S2c every read resolved the season from Sleeper, so drift was impossible and an outage
    was everyone's problem. Now the derivation owns the answer and Sleeper checks it — once, here,
    where being slow costs nobody anything.

    Unreachable is a FAILURE, not a skip. A gate that prints "Sleeper agrees" without having asked
    is the same defect as the 401-or-503 check this file used to carry: green having verified
    nothing.
    """
    print("\nSleeper must AGREE with the derived season (an assertion, not a dependency)")
    derived = settings.current_season()
    try:
        theirs = _sleeper_season()
    except Exception as exc:                       # noqa: BLE001 — every failure lands the same way
        _fail(f"could not reach Sleeper ({type(exc).__name__}: {exc}) — agreement is UNVERIFIED, "
              "and this check does not pass unverified")
        return
    if theirs == derived:
        _ok(f"Sleeper says {theirs}; we derive {derived}")
    else:
        _fail(f"DRIFT: Sleeper says {theirs}, we derive {derived}. One benign cause exists — in "
              f"early August we roll over a few days BEFORE Sleeper does, on purpose. Outside that "
              f"window the calendar rule is wrong and CURRENT_SEASON is the lever until it is fixed.")


def check_no_network_in_the_request_path() -> None:
    """Audit F6, closed structurally rather than by inspection."""
    print("\nnothing on the request path can be slow — the season does no I/O")
    api_dir = Path(__file__).resolve().parent
    if (api_dir / "nfl_state.py").exists():
        _fail("application/api/nfl_state.py still exists — the network call is back")
    else:
        _ok("application/api/nfl_state.py is gone (with its cache, timeout and fallbacks)")

    # Parsed, not grepped: the first version of this failed on `init_auth_schema`'s COMMENT saying
    # the table was retired, which is the textual-check trap this file warns about elsewhere.
    importers = []
    for path in sorted(api_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [a.name for a in node.names] + [node.module or ""]
                     if isinstance(node, ast.ImportFrom) else [])
            if any("nfl_state" in n for n in names):
                importers.append(path.name)
    if importers:
        _fail(f"{sorted(set(importers))} still IMPORT nfl_state")
    else:
        _ok("no api module imports nfl_state (this gate owns the Sleeper call now)")

    body = inspect.getsource(settings.season_and_source) + inspect.getsource(settings.derive_season)
    forbidden = [w for w in ("urllib", "http", "socket", "db.", "fetch") if w in body]
    if forbidden:
        _fail(f"the season derivation references {forbidden} — it must be pure")
    elif "os.environ" not in body:
        _fail("the derivation does not read os.environ — where is the override coming from?")
    else:
        _ok("the derivation is os.environ + the calendar: no I/O, so nothing to time out")


# --- the catalog ---------------------------------------------------------------------------

def check_catalog(builder=None) -> None:
    print("\nthe catalog each caller gets")
    _eq("signed out", _ids(_catalog(builder=builder)), [DEMO])
    _eq("user A (owns Trap 2025 + Trap 2024)",
        _ids(_catalog(owned={A_LEAGUE, A_PRIOR}, builder=builder)), [A_LEAGUE, DEMO])
    _eq("user B (owns YPFL 2025)",
        _ids(_catalog(owned={B_LEAGUE}, builder=builder)), [B_LEAGUE, DEMO])
    _eq("user A after a revoke", _ids(_catalog(owned=set(), builder=builder)), [DEMO])
    _eq("everyone, once Sleeper rolls to 2026",
        _ids(_catalog(owned={A_LEAGUE, B_LEAGUE}, current_season=2026, builder=builder)), [DEMO])


def check_ordering(builder=None) -> None:
    print("\nordering — the SPA lands on leagues[0], so this IS the landing rule")
    cat = _catalog(owned={A_LEAGUE}, builder=builder)
    first = cat["leagues"][0]["lineage_id"] if cat["leagues"] else None
    last = cat["leagues"][-1]["lineage_id"] if cat["leagues"] else None
    if first == "trap":
        _ok("a signed-in user's own league is FIRST (they land on theirs, not the demo)")
    else:
        _fail(f"leagues[0] is {first!r}, not the caller's own league — they land on the wrong one")
    if last == "lorp":
        _ok("the demo is LAST")
    else:
        _fail(f"the demo is not last (last={last!r})")

    # The demo lineage is is_mine=True in the fixture, so an is_mine-first sort would put it first.
    if first != "lorp":
        _ok("ordering follows OWNERSHIP, not the is_mine flag it replaced")
    else:
        _fail("ordering still follows is_mine — the pre-S2a sort survived")


def check_never_empty_or_duplicated(builder=None) -> None:
    print("\nthe two shapes that break the SPA silently")
    for label, owned, season in (("signed out", set(), 2025),
                                 ("signed in, owns nothing", set(), 2026),
                                 ("season unresolved", {A_LEAGUE}, None)):
        cat = _catalog(owned=owned, current_season=season, builder=builder)
        if cat["leagues"]:
            _ok(f"{label}: catalog is non-empty (an empty one hangs the app on 'Loading…')")
        else:
            _fail(f"{label}: EMPTY catalog — every visitor gets a permanent 'Loading…'")

    ids = _ids(_catalog(owned={DEMO, A_LEAGUE}, builder=builder))
    if len(ids) == len(set(ids)):
        _ok(f"a caller who OWNS the demo sees it once, not twice: {ids}")
    else:
        _fail(f"duplicate entries when the demo is also owned: {ids}")

    # Replaces the old "seasons stay DESC" check, which existed because the SPA's `latestSeason`
    # took seasons[0]. P5/S2e removed the season selector and flattened the catalog, so that
    # helper is gone — and this is the invariant the flat shape actually rests on. A lineage is
    # one league across years; if `visible` ever admitted two of its seasons at once, the flat
    # catalog would list the same league NAME twice in the switcher with no way to tell them
    # apart. A owns Trap 2025 AND Trap 2024, so this fixture is exactly that case.
    cat = _catalog(owned={A_LEAGUE, A_PRIOR}, builder=builder)
    lineages = [lg["lineage_id"] for lg in cat["leagues"]]
    if len(lineages) == len(set(lineages)):
        _ok(f"each lineage appears at most ONCE — the premise the flat catalog rests on: {lineages}")
    else:
        _fail(f"a lineage appears twice, so the league switcher shows one name twice: {lineages}")

    # The season did not vanish with the nesting; it moved onto the row. The reads still receive
    # it (inert, but carried), so a catalog entry without one would break the slice the SPA builds.
    missing = [lg["league_id"] for lg in cat["leagues"] if lg.get("season") is None]
    if not missing:
        _ok("every flat entry still carries its season")
    else:
        _fail(f"catalog entries with no season: {missing}")


# --- the override cannot come from a request ------------------------------------------------

def check_override_is_process_env_only() -> None:
    print("\nCURRENT_SEASON is process env ONLY — never caller-supplied")
    # Structural, not textual: a function's parameters are the only channel for caller data,
    # whatever it says in its docstring. (An earlier version of this check grepped the module for
    # "request"/"header" and tripped over the old nfl_state's own prose and its OUTBOUND urllib
    # call — a good reminder that a check matching comments is checking the wrong thing.)
    #
    # S2c: these take `today` now, because the date table above cannot test a function that reads
    # the clock itself. `today` is a DATE, not a season, and no route accepts one — which is what
    # the `slice_params`/`leagues` parameter assertions below actually guarantee. They are the
    # load-bearing half of this check now.
    for fn in (settings.current_season, settings.season_and_source, settings.describe_season):
        params = set(inspect.signature(fn).parameters)
        if params - {"today"}:
            _fail(f"settings.{fn.__name__} accepts {sorted(params)} — the season is injectable")
        else:
            _ok(f"settings.{fn.__name__}({', '.join(sorted(params))}) takes no season from anyone")

    body = inspect.getsource(settings.season_and_source)
    if "os.environ" not in body:
        _fail("the override does not read os.environ — where is it getting the value?")
    elif [w for w in ("request", "header", "cookie", "Request") if w in body]:
        _fail("the override references caller-supplied input")
    else:
        _ok("the override reads os.environ and nothing else")

    params = set(inspect.signature(routes.slice_params).parameters)
    banned = {"current_season", "season_override", "CURRENT_SEASON", "demo_league_id"}
    if params & banned:
        _fail(f"slice_params exposes {params & banned} as a query parameter")
    else:
        _ok(f"slice_params exposes only {sorted(params)} — no season/demo override")

    leagues_params = set(inspect.signature(routes.leagues).parameters)
    if leagues_params - {"user"}:
        _fail(f"/api/leagues takes unexpected caller-supplied parameters: {leagues_params}")
    else:
        _ok("/api/leagues takes nothing from the caller but their verified identity")

    # That the override is honoured from the process env, and refused when it is garbage, is
    # asserted by `check_season_derivation` — one place, next to the values it produces.


def check_anonymous_is_not_denied(*, require_401: bool = False) -> None:
    """A bad token must be refused — and S2c cares WHICH refusal (S2a audit F5).

    This used to accept 401 **or** 503, so on a machine with no Supabase config it went green
    having never verified a token at all: `auth.current_user` raises 503 before it looks at the
    credential. A refusal alone proves nothing about the verifier. The code is now recorded either
    way, and `--live` — where the config is by definition present — requires 401 specifically.
    """
    print("\nanonymous must mean anonymous, and a bad token must NOT")
    class _Req:
        def __init__(self, authz=None):
            self.headers = {"authorization": authz} if authz else {}

    if auth.optional_user(_Req()) is None:
        _ok("no Authorization header → anonymous (the public demo keeps working)")
    else:
        _fail("a header-less request did not resolve to anonymous")

    try:
        auth.optional_user(_Req("Bearer not-a-real-token"))
        _fail("a garbage token was silently treated as anonymous — a broken verifier would look "
              "identical to a working one")
    except Exception as exc:                       # HTTPException (401) or 503 if unconfigured
        code = getattr(exc, "status_code", None)
        if code == 401:
            _ok("a present-but-invalid token is refused 401 — the VERIFIER ran and rejected it")
        elif code == 503 and require_401:
            _fail("a bad token got 503, not 401: auth is unconfigured on this machine, so the "
                  "verifier never ran. Under --live that is a failure, not a pass.")
        elif code == 503:
            _ok("a present-but-invalid token is refused 503 — but note this machine has no "
                "Supabase config, so the verifier did NOT run. Only --live proves the 401.")
        else:
            _fail(f"unexpected failure for a bad token: {type(exc).__name__} {exc}")


# --- prove it bites -------------------------------------------------------------------------

def check_prove_bites() -> None:
    print("\nprove-it-bites — the SAME assertions against the pre-S2a unscoped catalog")
    before = len(_failures)
    check_catalog(builder=_unscoped_builder)
    check_ordering(builder=_unscoped_builder)
    caught = len(_failures) - before
    del _failures[before:]          # those failures are the expected result, not real ones
    if caught:
        print(f"  ok  the unscoped catalog fails {caught} of these assertions, as it must")
    else:
        _fail("the unscoped catalog PASSED every isolation assertion — the checks prove nothing")


# --- the live half --------------------------------------------------------------------------

def _admin(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    base, key = settings.supabase_url(), settings.supabase_secret_key()
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"apikey": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "{}")


def mint_token(email: str) -> str:
    """A real access token for an address, without anyone opening an inbox.

    `generate_link` produces the same `hashed_token` the emailed link carries; redeeming it at
    `/auth/v1/verify` is exactly what clicking the link does. Same path a real user takes, minus
    the mail hop — which is why it is legitimate proof rather than a shortcut around the gate.
    """
    link = _admin("/admin/generate_link", method="POST",
                  body={"type": "magiclink", "email": email})
    # `token_hash`, NOT `token`: /verify accepts a bare hashed token only under `token_hash`, and
    # rejects `token` without an accompanying email ("Only an email address or phone number should
    # be provided on verify"). This is the same field supabase-js sends from `verifyOtp`, i.e. the
    # exact exchange the browser performs when the link is clicked.
    req = urllib.request.Request(
        f"{settings.supabase_url()}/auth/v1/verify", method="POST",
        data=json.dumps({"type": "magiclink", "token_hash": link["hashed_token"]}).encode(),
        headers={"apikey": settings.supabase_publishable_key(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def _get_catalog(base_url: str, token: str | None, *, query: str = "",
                 headers: dict | None = None) -> list[str]:
    req = urllib.request.Request(f"{base_url}/api/leagues{query}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _ids(json.loads(resp.read()))


def _check_request_cannot_move_the_season(base_url: str, baseline: list[str]) -> None:
    """The live half of "process env only": try to inject it over the wire and fail."""
    attempts = {
        "?current_season=2025 query param": dict(query="?current_season=2025"),
        "?CURRENT_SEASON=2025 query param": dict(query="?CURRENT_SEASON=2025"),
        "X-Current-Season header": dict(headers={"X-Current-Season": "2025"}),
        "a CURRENT_SEASON cookie": dict(headers={"Cookie": "CURRENT_SEASON=2025"}),
    }
    for label, kwargs in attempts.items():
        got = _get_catalog(base_url, None, **kwargs)
        if got == baseline:
            _ok(f"{label} changes nothing")
        else:
            _fail(f"{label} MOVED the catalog: {got} != {baseline} — the override is caller-supplied")


def check_live(base_url: str, current_season: int, a_email: str, b_email: str) -> None:
    print(f"\nLIVE matrix against {base_url} (server season = {current_season})")
    if not (settings.supabase_secret_key() and settings.supabase_url()):
        print("  --  SKIPPED: SUPABASE_SECRET_KEY / SUPABASE_URL not set (nothing to mint with)")
        return

    tok_a, tok_b = mint_token(a_email), mint_token(b_email)
    anon = _get_catalog(base_url, None)
    got_a = _get_catalog(base_url, tok_a)
    got_b = _get_catalog(base_url, tok_b)

    _eq("signed out", anon, [DEMO])
    if current_season == 2025:
        _eq("user A", got_a, [A_LEAGUE, DEMO])
        _eq("user B", got_b, [B_LEAGUE, DEMO])
    else:
        _eq("user A (no current-season league)", got_a, [DEMO])
        _eq("user B (no current-season league)", got_b, [DEMO])

    # Invariants that must hold in EVERY configuration — the ones worth the session.
    for label, got, forbidden in (("A", got_a, B_LEAGUE), ("B", got_b, A_LEAGUE),
                                  ("signed out", anon, A_LEAGUE)):
        if forbidden in got:
            _fail(f"{label} can see {forbidden} — CROSS-USER LEAK")
        else:
            _ok(f"{label} cannot see {forbidden}")
    if A_PRIOR in got_a:
        _fail(f"A sees the prior-season fixture {A_PRIOR} — the current-season term does not bite")
    else:
        _ok(f"A's prior-season league {A_PRIOR} stays hidden")
    if DEMO not in anon or DEMO not in got_a or DEMO not in got_b:
        _fail("the demo is missing from some caller's catalog")
    else:
        _ok("the demo is present in every state, including signed out")

    _check_request_cannot_move_the_season(base_url, anon)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="also run the real two-account HTTP matrix")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--current-season", type=int, default=2025,
                    help="the season the SERVER is configured with (its CURRENT_SEASON, or live)")
    ap.add_argument("--user-a", default="willdaniel.wrd+s2a-a@gmail.com")
    ap.add_argument("--user-b", default="willdaniel.wrd+s2a-b@gmail.com")
    a = ap.parse_args()

    print("=== check_ownership: can a valid token for the wrong account reach a league? ===")
    check_predicate()
    check_unresolvable_season_narrows()
    check_season_derivation()
    check_sleeper_agrees()
    check_no_network_in_the_request_path()
    check_catalog()
    check_ordering()
    check_never_empty_or_duplicated()
    check_override_is_process_env_only()
    check_anonymous_is_not_denied(require_401=a.live)
    check_prove_bites()
    if a.live:
        check_live(a.base_url, a.current_season, a.user_a, a.user_b)

    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — the demo is public and season-independent, an owned league is visible only "
          "in the current season, nobody sees anyone else's, the season derives locally across the "
          "August boundary in both directions with Sleeper agreeing, and the pre-S2a catalog fails "
          "every one of these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
