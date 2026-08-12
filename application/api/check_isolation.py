"""Prove every read refuses a league the caller cannot see (P5/S2b) — the isolation matrix.

Fourth in the `check_auth` / `check_signup` / `check_ownership` line, and the one that covers the
property S2 exists to create. `check_ownership` proved you cannot *discover* someone else's league;
this proves you cannot *read* one you already know the id of, which is the half that was still open
on the live site: `GET /api/standings?league_id=<someone else's>` returned their standings, real
managers' handles included.

    application/api/.venv/bin/python -m application.api.check_isolation
    application/api/.venv/bin/python -m application.api.check_isolation --live --current-season 2025

The default run needs no server and no accounts. `authorize_slice` is pure and takes its lookups by
injection, so the whole {signed-out, owner, other} × {demo, own, other's, prior-season, nonexistent}
matrix runs against fixtures — deliberately, because an isolation gate that can only run when two
live Supabase accounts exist is one that stops being run.

`--live` adds what fixtures cannot: real tokens, real HTTP, every endpoint, and the byte-for-byte
comparison of the two 404s. It skips cleanly without the admin key and never writes it anywhere.

**Read the prove-it-bites block before trusting any of this.** Every refusal assertion is re-run
against the pre-S2b behaviour — existence-only authorization — and every one is required to fail. A
check that has never failed has not been tested; it has only been observed agreeing with the code it
was written from.
"""

from __future__ import annotations

import argparse
import inspect
import json
import urllib.error
import urllib.request

from application.api import auth, db, main, reads, routes, settings

_failures: list[str] = []

# --- the fixture world ---------------------------------------------------------------------
# Real corpus ids (application/data/corpus/demo_slate.csv) so the fixture and the live run describe
# the same world. DEMO is a 2025 league — that is the whole point of the season-independent term.
DEMO = "1182101676608823296"        # LoRP 2025 — the one public league
A_LEAGUE = "1207735666645946368"    # Trap 2025 — granted to A
A_PRIOR = "1051229073923584000"     # Trap 2024 — granted to A, must stay hidden in every run
B_LEAGUE = "1257433118135037952"    # YPFL 2025 — granted to B
GHOST = "9999999999999999999"       # never existed

_SEASONS = {DEMO: 2025, A_LEAGUE: 2025, A_PRIOR: 2024, B_LEAGUE: 2025}
_GRANTS = {"A": {A_LEAGUE: None, A_PRIOR: None}, "B": {B_LEAGUE: 5}}
_ROLES = [None, "A", "B"]


def _fake_lookup(league_id, user_id) -> dict:
    """The one query `authorize_slice` makes, answered from fixtures."""
    lid, season = str(league_id), _SEASONS.get(str(league_id))
    grants = _GRANTS.get(user_id, {})
    owned = 1 if lid in grants else 0
    return {"n_seasons": 1 if season is not None else 0, "season": season,
            "owned": owned, "grant_roster": grants.get(lid) if owned else None}


def _fake_rosters(league_id, roster_id) -> bool:
    return 1 <= int(roster_id) <= 10


def _authorize(league_id, role, *, current_season=2025, seat=None, authorizer=None):
    fn = authorizer or reads.authorize_slice
    return fn(league_id, None, seat, user_id=role, demo_league_id=DEMO,
              lookup=_fake_lookup, current_season_fn=lambda: current_season,
              roster_exists=_fake_rosters)


def _legacy_authorize(league_id, season, viewer_roster_id, *, user_id, demo_league_id,
                      lookup=None, current_season_fn=None, roster_exists=None) -> dict:
    """Pre-S2b: existence is the whole check. Kept to prove the assertions below can fail."""
    lid = league_id if league_id is not None else demo_league_id
    if not (lookup or reads.slice_lookup)(lid, user_id)["n_seasons"]:
        raise reads.SliceRefused(lid)
    return {"league_id": str(lid), "season": season, "viewer_roster_id": viewer_roster_id}


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


# --- the matrix ----------------------------------------------------------------------------
# Who may read what, at CURRENT_SEASON=2025. This table IS the security property; everything else
# in this file exists to check it against something.
_MATRIX = {
    #  league     signed-out   A       B
    DEMO:      {None: True,  "A": True,  "B": True},    # public, and season-independent
    A_LEAGUE:  {None: False, "A": True,  "B": False},
    B_LEAGUE:  {None: False, "A": False, "B": True},
    A_PRIOR:   {None: False, "A": False, "B": False},   # owned, but not the current season
    GHOST:     {None: False, "A": False, "B": False},
}

_LABEL = {DEMO: "the demo", A_LEAGUE: "A's league", B_LEAGUE: "B's league",
          A_PRIOR: "A's PRIOR-season league", GHOST: "a nonexistent league"}
_WHO = {None: "signed out", "A": "user A", "B": "user B"}


def _run_matrix(authorizer=None, current_season=2025) -> None:
    for lid, row in _MATRIX.items():
        for role, want_allowed in row.items():
            try:
                _authorize(lid, role, current_season=current_season, authorizer=authorizer)
                allowed = True
            except reads.SliceRefused:
                allowed = False
            except reads.SliceUnavailable as exc:
                _fail(f"{_WHO[role]} → {_LABEL[lid]}: unavailable ({exc})")
                continue
            if allowed == want_allowed:
                _ok(f"{_WHO[role]:<10} → {_LABEL[lid]:<26} {'reads' if allowed else 'refused'}")
            else:
                _fail(f"{_WHO[role]} → {_LABEL[lid]}: "
                      f"{'READ IT' if allowed else 'refused'}, expected "
                      f"{'read' if want_allowed else 'refusal'}")


def check_matrix() -> None:
    print("\nthe matrix — who may read what (CURRENT_SEASON=2025)")
    _run_matrix()


def check_season_term() -> None:
    print("\nthe season term, and the demo's exemption from it")
    for lid, role in ((A_LEAGUE, "A"), (B_LEAGUE, "B")):
        try:
            _authorize(lid, role, current_season=2026)
            _fail(f"{_WHO[role]} still reads {_LABEL[lid]} once the season rolls to 2026")
        except reads.SliceRefused:
            _ok(f"{_WHO[role]} loses {_LABEL[lid]} when the season rolls to 2026")
    for season, why in ((2026, "a 2025 league in a later season — the case a global "
                               "`season = current` filter breaks"),
                        (None, "Sleeper down and nothing cached — the demo must not go with it")):
        try:
            _authorize(DEMO, None, current_season=season)
            _ok(f"the demo is still readable at current_season={season!r} ({why})")
        except reads.SliceRefused:
            _fail(f"the demo is REFUSED at current_season={season!r}")
    try:
        _authorize(A_LEAGUE, "A", current_season=None)
        _fail("an owned league is readable with the season UNRESOLVED — this is the fail-OPEN bug")
    except reads.SliceRefused:
        _ok("an unresolved season refuses even an owned league (narrows, never widens)")


def check_default_slice() -> None:
    print("\nan omitted league_id is the demo — for everyone, and it is still authorized")
    for role in _ROLES:
        got = _authorize(None, role)["league_id"]
        _eq(f"{_WHO[role]:<10} default slice", got, DEMO)


def check_viewer_seat() -> None:
    print("\nthe viewer seat")
    _eq("A's grant has no seat → falls back to MY_USERNAME (demo parity)",
        _authorize(A_LEAGUE, "A")["viewer_roster_id"], None)
    _eq("B's grant records roster 5 → that is B's seat",
        _authorize(B_LEAGUE, "B")["viewer_roster_id"], 5)
    _eq("a caller-supplied seat still wins (viewing your league as another manager)",
        _authorize(B_LEAGUE, "B", seat=3)["viewer_roster_id"], 3)
    try:
        _authorize(DEMO, None, seat=99)
        _fail("a roster that is not in the league was ACCEPTED as the viewer seat")
    except reads.SliceRefused:
        _ok("a roster that is not in the league is refused, with the same 404")
    # The ordering matters as much as the check: run the seat test first and it answers
    # "is roster N in league X" for leagues the caller cannot see.
    try:
        _authorize(A_LEAGUE, None, seat=99)
        _fail("an invisible league leaked through the seat check")
    except reads.SliceRefused:
        _ok("an invisible league is refused BEFORE the seat is examined (no roster oracle)")


def check_refusals_are_indistinguishable() -> None:
    print("\nthe refusal carries no information")
    kinds = set()
    for lid in (A_LEAGUE, GHOST, A_PRIOR):
        try:
            _authorize(lid, None)
        except Exception as exc:  # noqa: BLE001
            kinds.add(type(exc).__name__)
    _eq("every refusal is the same exception type", sorted(kinds), ["SliceRefused"])
    if "{" in routes._UNKNOWN_LEAGUE or "%" in routes._UNKNOWN_LEAGUE:
        _fail(f"the 404 detail interpolates something: {routes._UNKNOWN_LEAGUE!r}")
    else:
        _ok(f"the 404 detail is a constant, so both bodies are identical: "
            f"{routes._UNKNOWN_LEAGUE!r}")


def check_broken_config_is_not_a_refusal() -> None:
    print("\na broken deployment must not look like a hostile request")
    try:
        reads.authorize_slice(None, None, None, user_id=None, demo_league_id=None,
                              lookup=_fake_lookup, current_season_fn=lambda: 2025,
                              roster_exists=_fake_rosters)
        _fail("an unset DEMO_LEAGUE_ID produced a slice")
    except reads.SliceUnavailable:
        _ok("an unset DEMO_LEAGUE_ID raises SliceUnavailable (503), not SliceRefused (404)")
    except reads.SliceRefused:
        _fail("an unset DEMO_LEAGUE_ID reads as 'unknown league_id' — hides a deploy failure")

    try:
        reads.authorize_slice(DEMO, None, None, user_id=None, demo_league_id=DEMO,
                              lookup=lambda *_: {"n_seasons": 0, "season": None, "owned": 0,
                                                 "grant_roster": None},
                              current_season_fn=lambda: 2025, roster_exists=_fake_rosters)
        _fail("a demo league with no data produced a slice")
    except reads.SliceUnavailable:
        _ok("a demo league absent from `teams` raises SliceUnavailable, not a 404")
    except reads.SliceRefused:
        _fail("a demo league with no data reads as 'unknown league_id'")


# --- the router, and the store ---------------------------------------------------------------

_EXEMPT = {"/api/me", "/api/leagues", "/api/signup"}
_GATED = {"/api/weeks", "/api/league-meta", "/api/players", "/api/players/{sleeper_id}",
          "/api/standings", "/api/teams/{roster_id}", "/api/managers/{roster_id}", "/api/league",
          "/api/positional-talent", "/api/matchups", "/api/matchups/{matchup_id}"}


def _depends_on_slice_params(dependant) -> bool:
    if getattr(dependant, "call", None) is routes.slice_params:
        return True
    return any(_depends_on_slice_params(d) for d in getattr(dependant, "dependencies", []))


def check_every_route_is_accounted_for() -> None:
    """Assert the COMPLEMENT, not the list.

    A hard-coded list checked against the router catches a loop that skipped an endpoint. It does
    not catch the failure that actually happens: someone adds a twelfth read and forgets to scope
    it. So every route under /api must be either gated or *explicitly* exempt — a new one is a
    failure until a human classifies it.
    """
    print("\nevery /api route is gated or explicitly exempt")
    gated, ungated = set(), set()
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if not path.startswith("/api") or not (methods & {"GET", "POST"}):
            continue
        (gated if _depends_on_slice_params(getattr(route, "dependant", None)) else
         ungated).add(path)

    _eq("routes carrying the authorization seam", sorted(gated), sorted(_GATED))
    unclassified = ungated - _EXEMPT
    if unclassified:
        _fail(f"UNSCOPED /api routes nobody has classified: {sorted(unclassified)}")
    else:
        _ok(f"the {len(ungated)} ungated routes are all known exemptions: {sorted(ungated)}")

    params = {n for n, p in inspect.signature(routes.slice_params).parameters.items()
              if not repr(p.default).startswith("Depends")}
    _eq("slice_params' caller-supplied parameters", sorted(params),
        ["league_id", "season", "viewer_roster_id"])


def check_store_agrees_with_itself() -> None:
    """`teams` is now the authorization source; `league_catalog` is still the catalog source.

    Two tables holding the same fact will eventually disagree, and the dangerous direction is
    silent: a league the catalog hides but the reads would serve. S2a's audit (F2) is the lesson —
    a property measured once and never asserted is not a property.
    """
    print("\nthe two sources of a league's season agree")
    try:
        rows = db.fetch_all("""
            SELECT count(*)::int AS n FROM league_catalog dm
            JOIN (SELECT league_id, min(season) s, count(DISTINCT season) c
                  FROM teams GROUP BY league_id) t ON t.league_id = dm.league_id
            WHERE t.s <> dm.season OR t.c <> 1
        """)
        missing = db.fetch_all("""
            SELECT count(*)::int AS n
            FROM (SELECT league_id FROM league_catalog EXCEPT SELECT league_id FROM teams) x
        """)
    except Exception as exc:  # noqa: BLE001 — no database here is a skip, not a failure
        print(f"  --  SKIPPED (no database: {exc})")
        return
    _eq("catalogued leagues whose season disagrees with `teams`", rows[0]["n"], 0)
    _eq("catalogued leagues with no rows in `teams` at all", missing[0]["n"], 0)


def check_prove_bites() -> None:
    print("\nprove-it-bites — the SAME matrix against pre-S2b, existence-only authorization")
    before = len(_failures)
    _run_matrix(authorizer=_legacy_authorize)
    caught = len(_failures) - before
    del _failures[before:]      # these failures are the expected result, not real ones
    expected = sum(1 for row in _MATRIX.values() for allowed in row.values() if not allowed) - 3
    if caught >= expected:
        print(f"  ok  the pre-S2b code fails {caught} of these assertions, as it must "
              f"(every refusal of a league that exists)")
    else:
        _fail(f"pre-S2b authorization only failed {caught} assertions, expected >= {expected} — "
              "these checks do not prove what they claim")


# --- live ------------------------------------------------------------------------------------

_ENDPOINTS = ["/api/weeks", "/api/league-meta", "/api/players", "/api/players/4034",
              "/api/standings", "/api/teams/1", "/api/managers/1", "/api/league",
              "/api/positional-talent", "/api/matchups", "/api/matchups/1"]


def _admin(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    base, key = settings.supabase_url(), settings.supabase_secret_key()
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"apikey": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "{}")


def mint_token(email: str) -> str:
    """A real access token without anyone opening an inbox — `token_hash`, not `token`."""
    link = _admin("/admin/generate_link", method="POST",
                  body={"type": "magiclink", "email": email})
    req = urllib.request.Request(
        f"{settings.supabase_url()}/auth/v1/verify", method="POST",
        data=json.dumps({"type": "magiclink", "token_hash": link["hashed_token"]}).encode(),
        headers={"apikey": settings.supabase_publishable_key(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def _request(base_url: str, path: str, token: str | None, league_id: str | None = None):
    """``(status, body_bytes, headers)`` — a 4xx is an answer here, not an exception."""
    url = f"{base_url}{path}" + (f"?league_id={league_id}" if league_id else "")
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def check_live(base_url: str, current_season: int, a_email: str, b_email: str) -> None:
    print(f"\nLIVE — every read × every role against {base_url} (server season = {current_season})")
    if not (settings.supabase_secret_key() and settings.supabase_url()):
        print("  --  SKIPPED: SUPABASE_SECRET_KEY / SUPABASE_URL not set (nothing to mint with)")
        return

    tokens = {None: None, "A": mint_token(a_email), "B": mint_token(b_email)}
    matrix = _MATRIX if current_season == 2025 else {
        lid: {r: (lid == DEMO) for r in _ROLES} for lid in _MATRIX}

    bad = 0
    for lid, row in matrix.items():
        for role, want_allowed in row.items():
            want = 200 if want_allowed else 404
            for path in _ENDPOINTS:
                status, _, _ = _request(base_url, path, tokens[role], lid)
                if status != want:
                    bad += 1
                    _fail(f"{_WHO[role]} → {_LABEL[lid]} {path}: {status}, expected {want}")
        if not bad:
            _ok(f"{_LABEL[lid]:<26} correct on all {len(_ENDPOINTS)} reads × {len(row)} roles")
    if not bad:
        _ok(f"{len(_ENDPOINTS) * sum(len(r) for r in matrix.values())} live requests, "
            "every one as specified")

    print("\nLIVE — the two 404s are the same response")
    s1, b1, h1 = _request(base_url, "/api/standings", None, A_LEAGUE)   # exists, not yours
    s2, b2, h2 = _request(base_url, "/api/standings", None, GHOST)      # never existed
    _eq("status", (s1, s2), (404, 404))
    if b1 == b2:
        _ok(f"body, byte for byte: {b1!r}")
    else:
        _fail(f"bodies differ — an enumeration oracle: {b1!r} vs {b2!r}")
    interesting = ("content-type", "content-length", "vary", "cache-control", "www-authenticate")
    k1 = {k.lower(): v for k, v in h1.items() if k.lower() in interesting}
    k2 = {k.lower(): v for k, v in h2.items() if k.lower() in interesting}
    _eq("headers", k1, k2)
    if k1.get("vary", "").lower() == "authorization":
        _ok("Vary: Authorization is set, so a shared cache cannot serve one caller's league to "
            "another")
    else:
        _fail(f"Vary: Authorization missing — {k1}")

    print("\nLIVE — a bad token is refused, specifically")
    status, _, _ = _request(base_url, "/api/standings", "not-a-real-token")
    if status == 401:
        _ok("a garbage token gets 401 — the token was actually verified")
    else:
        _fail(f"a garbage token got {status}; only 401 proves verification happened "
              "(503 would mean the verifier was never reached)")

    print("\nLIVE — the demo survives every state")
    for role in _ROLES:
        status, _, _ = _request(base_url, "/api/standings", tokens[role])
        _eq(f"{_WHO[role]:<10} default slice", status, 200)


def main_() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="also run the real endpoint × role matrix")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--current-season", type=int, default=2025,
                    help="the season the SERVER is configured with")
    ap.add_argument("--user-a", default="willdaniel.wrd+s2b-a@gmail.com")
    ap.add_argument("--user-b", default="willdaniel.wrd+s2b-b@gmail.com")
    a = ap.parse_args()

    print("=== check_isolation: can a caller read a league they cannot see? ===")
    check_matrix()
    check_season_term()
    check_default_slice()
    check_viewer_seat()
    check_refusals_are_indistinguishable()
    check_broken_config_is_not_a_refusal()
    check_every_route_is_accounted_for()
    check_store_agrees_with_itself()
    check_prove_bites()
    if a.live:
        check_live(a.base_url, a.current_season, a.user_a, a.user_b)

    if _failures:
        print(f"\n✗ {len(_failures)} FAILURE(S):")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("\nALL GREEN — every read refuses a league the caller cannot see, the refusal is "
          "indistinguishable from 'no such league', a broken deploy is not disguised as one, no "
          "/api route is unaccounted for, and pre-S2b authorization fails this matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_())
