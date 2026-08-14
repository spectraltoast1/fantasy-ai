"""The ``/api`` read endpoints (store-migration Session 3; parameterized on league_id in B4).

Thin HTTP layer over ``reads.py`` — each route returns its ``queries.js`` loader's shape
verbatim (plain dicts/lists, FastAPI auto-JSON; no Pydantic models so nothing coerces or
reorders the payload). Week-scoped routes take ``?as_of_week=N`` and default to the latest.

Stage-B B4: every read route also accepts an OPTIONAL ``?league_id=`` (+ ``?season=``) via the
``slice_params`` dependency. Passing a corpus ``league_id`` scopes the read to that slice; an
unknown ``league_id`` 404s.

P5/S2a scoped ``/api/leagues`` — the catalog — so a caller could not *discover* someone else's
league, and made an omitted ``league_id`` resolve to ``DEMO_LEAGUE_ID`` explicitly instead of
falling through ``MY_USERNAME`` to the is_mine slice.

**P5/S2b closes access.** ``slice_params`` now takes the caller's identity and applies the
visibility predicate, so all eleven per-panel reads inherit it from one place. Knowing a
``league_id`` is no longer enough to read it; an unowned league answers with exactly the 404 a
nonexistent one does.

**P5/S4c adds the connect flow** — the first routes here that are neither a read nor an auth call.
``POST /api/connect`` enqueues onto S4b's job queue (through ``api/jobs.py``, which is where the
enqueue seam lives *because this image cannot import ``application/data/``*), and three companions
answer "which leagues could I link", "what is my job doing", and "do I have one in flight". They
are the reason ``user_leagues`` is no longer a table only an operator writes.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from application.api import (auth, db, jobs, platforms, rate_limit, reads, settings,
                             signup)

_LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ONE refusal string, reached by both branches, interpolating nothing. It used to echo the
# league_id back — which meant an unowned league and a nonexistent one could never produce the same
# bytes, and the whole no-enumeration design rests on them being indistinguishable. The caller's own
# input tells them nothing they didn't already know, but a body that varies with it is a body an
# attacker can measure, and it also stopped the two responses being comparable at all.
_UNKNOWN_LEAGUE = "unknown league_id"


def slice_params(league_id: str | None = None, season: int | None = None,
                 viewer_roster_id: int | None = None,
                 user: dict | None = Depends(auth.optional_user)) -> dict:
    """The slice selector shared by every read route — and, as of P5/S2b, **the one authorization
    seam**. Every one of the eleven per-panel reads inherits it; none repeats the check.

    S2a scoped the catalog, so you could not *discover* someone else's league. This closes *access*:
    until now a caller who already knew a ``league_id`` could pass it here and read the league.

    A thin adapter on purpose. The decision lives in ``reads.authorize_slice``, which is pure and
    injectable so ``check_isolation`` can drive the whole matrix from fixtures — an isolation gate
    that can only run against two live accounts is one that stops being run. This function's only
    job is turning its two exceptions into HTTP:

    - ``SliceRefused`` → **404**, the same status *and the same body* a nonexistent league gets.
      A 403 would confirm the league exists; Sleeper ids are guessable, so a refusal that varies by
      case is an enumeration oracle.
    - ``SliceUnavailable`` → **503**. A broken demo config or a league with two seasons in the store
      is a deploy problem, and dressing it as "unknown league_id" would hide an outage behind an
      authorization message.

    ``season`` is still carried, never a SQL filter (a redraft ``league_id`` already pins one
    ``(league, season)`` slice). The returned dict is built explicitly, with exactly the three keys
    the loaders accept — ``user`` is a dependency, not a slice field, and one stray key would make
    ``**slice`` a 500 on all eleven routes at once.
    """
    try:
        return reads.authorize_slice(
            league_id, season, viewer_roster_id,
            user_id=(user or {}).get("id"),
            demo_league_id=settings.demo_league_id(),
        )
    except reads.SliceRefused:
        raise HTTPException(status_code=404, detail=_UNKNOWN_LEAGUE) from None
    except reads.SliceUnavailable as exc:
        _LOG.error("slice unavailable — this is a deploy/data problem, not a caller problem: %s",
                   exc)
        raise HTTPException(status_code=503, detail="this league cannot be served") from exc


_UPSERT_APP_USER = """
INSERT INTO public.app_users (id, email) VALUES (%(id)s, %(email)s)
ON CONFLICT (id) DO NOTHING
"""


@router.get("/me")
def me(user: dict = Depends(auth.current_user)) -> dict:
    """The authenticated caller's identity — the one endpoint that REQUIRES a token.

    Not the only protected one. Every read is scoped as of S2a/S2b: the catalog shows you only
    the demo plus what you own, and all eleven per-panel reads authorize at ``slice_params``. What
    is different here is the failure mode — the reads take ``optional_user`` and serve the public
    demo to an anonymous caller, while this one takes ``current_user`` and 401s. If you are
    reading this to decide whether something is protected, the answer lives in
    ``reads.authorize_slice``, not here.

    Recording the profile row here — rather than in a database trigger on ``auth.users`` — keeps
    the behavior in reviewable code instead of invisible DDL, and costs one no-op INSERT per
    call. Deliberately narrow: id and email only. Ownership is a separate table
    (``public.user_leagues``, S2a).

    **That table stopped being an operator's to write in P5/S4c.** This docstring used to end
    "written by an operator rather than inferred from a sign-in", which was the line the connect
    flow existed to delete: a row now appears because somebody linked their own league and the
    worker's job reached ``ready``, with no ``scripts/users.py --grant`` in the loop. ``--grant``
    survives as operator tooling, not as the mechanism.
    """
    db.execute(_UPSERT_APP_USER, {"id": user["id"], "email": user["email"]})
    return {"id": user["id"], "email": user["email"]}


@router.post("/signup")
def signup_request(request: Request, body: dict = Body(...)) -> dict:
    """Request a sign-in link. The API's first write endpoint, and its only unauthenticated one.

    Takes ``{email, code}``. The access code is required on every request from everyone — see
    ``signup.py`` for why that is the property worth having rather than a friction to remove.

    Deliberately NOT taking ``slice_params``: this has nothing to do with which league you are
    looking at, and merging the slice into it would put a ``league_id`` on an auth call.

    The response is the same whether or not the address already had an account, so it can't be
    used to enumerate who is registered.

    **The order of the checks below is the fix S1b's audit asked for, and it is a rule rather than
    a reordering: the email counter only ever counts requests that presented a VALID access code.**
    Until S2c the email limit was applied first, keyed on a caller-supplied address — so five
    requests carrying somebody's address and any garbage code locked that person out of sign-in
    for an hour. The limiter was handing out the exact harm it exists to prevent, and it needed no
    access code to do it.

    So: IP first (it is keyed on the caller's own address, cannot be aimed at anyone else, and is
    what actually bounds brute-forcing the code), then the code, then the email counter. A wrong
    code is recorded against the IP alone. A stranger can no longer spend a real person's
    allowance; mailbox-flood protection survives for people who do hold the code.
    """
    email = str(body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    # An unconfigured server must say so rather than refusing everyone as a bad code.
    signup.ensure_configured()

    # One query, two enforcement points — so both numbers describe the same instant and the
    # ordering below costs no extra round trip.
    counted = rate_limit.counts(request, email)
    rate_limit.enforce_ip(counted)

    if not signup.code_matches(body.get("code")):
        # IP budget only. Recording nothing at all would leave brute-forcing unbounded; recording
        # it against the email is what created the targeted lockout.
        rate_limit.record(request, None, ok=False)
        raise HTTPException(status_code=403, detail=signup.REFUSED)

    rate_limit.enforce_email(counted)
    try:
        signup.request_link(email, body.get("code"))
    except Exception:
        rate_limit.record(request, email, ok=False)
        raise
    rate_limit.record(request, email, ok=True)
    return {"sent": True}


# --- The connect flow (P5/S4c) ----------------------------------------------------------------
# The line above `routes.me`'s docstring — ownership "written by an operator rather than inferred
# from a sign-in" — stops being true here. These four routes are how it gets inferred.

# The same shape `_UNKNOWN_LEAGUE` has and for the same reason: ONE refusal string, reached by both
# branches, interpolating nothing. A job that is not yours and a job that never existed must be
# byte-identical, or the pair is an oracle for how many leagues have connected and how fast — which
# is exactly what `jobs.id` being a uuid rather than a bigserial was chosen to prevent.
_UNKNOWN_JOB = "unknown job id"


@router.get("/platforms/{platform}/leagues")
def platform_leagues(platform: str, handle: str,
                     user: dict = Depends(auth.current_user)) -> dict:
    """Which leagues a handle plays in — the interactive half of identity acquisition.

    **Authenticated**, unlike `/signup`: this spends our Sleeper call budget, so the caller has to
    be somebody. Rate-limited per USER (see `rate_limit`), because the resource at risk is our
    egress IP and getting throttled by Sleeper stops onboarding for everyone.

    **Not under `/connect/`, deliberately.** `/api/connect/discover` would sit next to
    `/api/connect/{job_id}` and depend on FastAPI's declaration order to not be shadowed by it —
    correct today, and one reordered function from being wrong. There is no ordering to get wrong
    here.

    A handle the platform has never heard of is a 200 with an empty list, not a 404: it is an
    ordinary answer to an ordinary question (people mistype), and the SPA says so in words. A
    platform we cannot REACH is a 502 — the caller did nothing wrong and retrying may work.
    """
    rate_limit.enforce_discovery(user["id"])
    rate_limit.record_discovery(user["id"])
    try:
        return platforms.discover(platform, handle,
                                  current_season=settings.current_season())
    except platforms.PlatformUnsupported:
        raise HTTPException(status_code=404, detail="unknown platform") from None
    except platforms.LookupFailed as exc:
        _LOG.warning("platform lookup failed (platform=%s): %s", platform, exc)
        raise HTTPException(
            status_code=502,
            detail="Couldn't reach Sleeper just now. Try again in a moment.") from exc


@router.post("/connect")
def connect(body: dict = Body(...), user: dict = Depends(auth.current_user)) -> dict:
    """Link a league: enqueue a job and return its id. **It builds nothing.**

    Takes `{platform, handle, league_id}` — platform-generic on purpose, so a second source is a
    new value rather than a breaking client change. `handle` is optional: the dual-mode input
    accepts a league id directly, and that path resolves no seat, which renders as no "you"
    highlight. **That is a supported outcome, not a degraded one** (settled with Will,
    2026-08-14).

    **THE SEASON IS SERVER-DERIVED, NEVER TAKEN FROM THE BODY.** `settings.current_season()` is the
    same value `reads.visible` applies to the owned term, so a job can never be enqueued for a
    season whose league the catalog would then refuse to show. A client-supplied season would make
    that reachable, and the symptom — a league that builds perfectly and is then invisible to the
    person who linked it — carries no error anywhere.

    **NO OWNERSHIP VERIFICATION, and this is a decision rather than an omission** (Will,
    2026-08-14). We do not check that the caller holds a seat in the league they name. Anyone with
    a `league_id` can already read that league's rosters, owners and matchups directly from
    api.sleeper.app — the id is the secret and we are not the weak link — and Sleeper offers no
    OAuth and no verification primitive, so there is nothing stronger available. Combined with
    invite-gated signup that is the accepted risk. Do not "fix" this later without revisiting the
    reasoning. See `jobs._GRANT` for the matching decision on roster uniqueness.

    A second job for a league already building is refused by `jobs_active_league_idx`, not by a
    check here — a unique index is the only version of that rule two machines cannot race.
    """
    platform = str(body.get("platform") or platforms.IMPLEMENTED[0]).strip().lower()
    raw = str(body.get("league_id") or "").strip()
    handle = (str(body.get("handle") or "").strip() or None)

    if not platforms.is_league_id(raw):
        # The SPA sends a league_id it got from discovery, or one the user typed that already
        # passed the same test client-side. Reaching here means neither, so say what is wrong
        # rather than enqueueing a job that can only ever be `rejected`.
        raise HTTPException(status_code=400,
                            detail="That doesn't look like a Sleeper league ID.")
    if platform not in platforms.IMPLEMENTED:
        raise HTTPException(status_code=400, detail=f"{platform} isn't supported yet.")

    rate_limit.enforce_connect(user["id"])

    # Resolve the handle HERE rather than trusting one the client echoes back from discovery. It is
    # not an authorization field — see above — but one GET buys "every id on a job row was resolved
    # by this server", which is one fewer thing the worker has to be suspicious of.
    platform_user_id = None
    if handle:
        try:
            platform_user_id = platforms.resolve_user_id(platform, handle)
        except platforms.LookupFailed as exc:
            raise HTTPException(
                status_code=502,
                detail="Couldn't reach Sleeper just now. Try again in a moment.") from exc
        if platform_user_id is None:
            raise HTTPException(status_code=404,
                                detail=f"Sleeper has no user called “{handle}”.")

    try:
        row = jobs.enqueue(raw, settings.current_season(), platform=platform,
                           requested_by=user["id"], handle=handle,
                           platform_user_id=platform_user_id)
    except Exception as exc:      # noqa: BLE001 — the unique index is the expected failure here
        if "jobs_active_league_idx" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="That league is already being linked. Give it a moment.") from exc
        raise
    _LOG.info("connect enqueued job=%s league=%s season=%s platform=%s seat_id=%s",
              row["id"], row["league_id"], row["season"], platform, bool(platform_user_id))
    return _job_payload(row)


@router.get("/connect")
def active_connect(user: dict = Depends(auth.current_user)) -> dict:
    """The caller's job still in flight, or `{"job": null}`. **This is what survives a refresh.**

    Required rather than convenient. The ownership row is written when the job reaches `ready`, so
    the progress screen cannot be driven by the catalog — it is driven by the job, and a signed-in
    user who reloads mid-build would otherwise have no way to find their own job again. An id held
    in browser memory does not survive a reload; this does.
    """
    row = jobs.active_job_for_user(user["id"])
    return {"job": _job_payload(row) if row else None}


@router.get("/connect/{job_id}")
def connect_job(job_id: str, user: dict = Depends(auth.current_user)) -> dict:
    """One job's state, **for its owner** — and for nobody else.

    Scoped to `requested_by`, and a job that is not yours returns the SAME 404, with the same body,
    as one that never existed. The uuid PK makes enumeration impractical; that is not a reason to
    skip the check. S2b established that principle for leagues and it applies to every object.

    The uuid cast is guarded rather than caught downstream: `%(id)s::uuid` raises on garbage, and a
    500 on a malformed id is both a worse answer and a different one — a caller could tell a
    well-formed unknown id from a malformed one, which is the beginnings of the oracle this is
    built to avoid.
    """
    try:
        uuid.UUID(job_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail=_UNKNOWN_JOB) from None
    row = jobs.job_for_owner(job_id, user["id"])
    if row is None:
        raise HTTPException(status_code=404, detail=_UNKNOWN_JOB)
    return _job_payload(row)


def _job_payload(row: dict) -> dict:
    """One job as the client sees it. Timestamps as ISO strings; everything else verbatim.

    `error` is passed through UNCHANGED, and that is the reject path reaching a human. S5 owns the
    graceful preflight and the polished copy — this must not invent any — but a job that ended must
    not leave somebody on a spinner that never resolves either. Whatever words the refusal already
    carries are better than silence. Honest, not polished: the same standing rule the empty panels
    follow.
    """
    out = dict(row)
    for k in ("created_at", "started_at", "finished_at", "updated_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    out["id"] = str(out["id"])
    return out


@router.get("/weeks")
def weeks(slice: dict = Depends(slice_params)) -> dict:
    return reads.load_weeks(**slice)


@router.get("/league-meta")
def league_meta(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_league_meta(as_of_week, **slice)


@router.get("/players")
def players(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> list[dict]:
    return reads.load_players(as_of_week, **slice)


@router.get("/players/{sleeper_id}")
def player_card(sleeper_id: str, as_of_week: int | None = None,
                slice: dict = Depends(slice_params)) -> dict:
    return reads.load_player_card(sleeper_id, as_of_week, **slice)


@router.get("/standings")
def standings(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> list[dict]:
    return reads.load_standings(as_of_week, **slice)


@router.get("/teams/{roster_id}")
def team_detail(roster_id: int, as_of_week: int | None = None,
                slice: dict = Depends(slice_params)):
    # Returns null (200) for an unknown roster, matching loadTeamDetail's shape.
    return reads.load_team_detail(roster_id, as_of_week, **slice)


@router.get("/managers/{roster_id}")
def manager_dossier(roster_id: int, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_manager_dossier(roster_id, **slice)


@router.get("/league")
def league(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_league(as_of_week, **slice)


@router.get("/positional-talent")
def positional_talent(slice: dict = Depends(slice_params)) -> dict:
    return reads.load_positional_talent(**slice)


@router.get("/matchups")
def matchups(as_of_week: int | None = None, slice: dict = Depends(slice_params)) -> dict:
    return reads.load_matchups(as_of_week, **slice)


@router.get("/matchups/{matchup_id}")
def matchup_detail(matchup_id: int, as_of_week: int | None = None,
                   slice: dict = Depends(slice_params)):
    # Returns null (200) when the game/week doesn't resolve, matching loadMatchupDetail.
    return reads.load_matchup_detail(matchup_id, as_of_week, **slice)


@router.get("/leagues")
def leagues(user: dict | None = Depends(auth.optional_user)) -> dict:
    """The lineage catalog (Stage-B B3), scoped to the caller as of P5/S2a.

    Signed out → the demo alone. Signed in → the demo plus your own current-season leagues, yours
    first. This was the ONE unscoped read, and it is the catalog, so it is the right first thing
    to close: every other surface is navigated from this list.

    Two properties the SPA depends on, both easy to break and neither loud when broken:
    it must never 401 (``loadLeagues()`` only console.errors, leaving a permanent "Loading…"),
    and it must never return zero leagues (``if (lgs.length)`` guards the only slice selection).
    The demo term is what guarantees the second — see ``reads.build_catalog``.
    """
    return reads.load_leagues(user_id=(user or {}).get("id"))
