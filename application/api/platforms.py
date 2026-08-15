"""Platform discovery — turning a handle into a list of leagues somebody can link (P5/S4c).

**The seam, and why it is a seam before it needs to be.** Will's direction is multiple platform
sources post-V1, so S4c was told to *build the dimension, not the second implementation* — the same
pattern that gave `jobs.kind` its column before a second executor existed. So discovery is one
function taking a `platform` argument with exactly one implementation behind it, and the natural
adapter interface is three calls: **`discover(handle) → [league summaries]`**,
**`summary(league_id)`**, **`fetch_raw(league_id, season)`**. The first two are here; the third is
already on the worker (`harvest._pull_raw`), and everything downstream of it operates on our
normalised shapes and does not care where the league came from.
→ `projects/post-v1/other-platforms.md`.

**Why discovery is on the API and not the worker.** The two halves of identity acquisition live on
different machines and conflating them forces a bad architecture. Discovery is *interactive* — a
person is waiting, and it is the difference between picking a league and pasting an 18-digit id —
so it has to be a request-time call. Seat resolution is *not*: the worker does it from data it
already has, after the fetch stage.

**stdlib `urllib`, no HTTP client.** The precedent is `scripts/users.py`, which talks to Supabase
that way precisely so it needs no dependency. `api/requirements.txt` stays fastapi + psycopg + pyjwt
for three GETs.

**This module must never import `application.data`.** `data/fetchers/sleeper.py` is the one fetcher
for this source (CODING_BIBLE §1) and it is *unreachable from here* — it imports polars and
`data_layer`, and the API image contains no `application/data/` at all. That is a real duplication
of two URL templates, and it is the constraint's price rather than an oversight; `check_connect`
asserts the two agree on the base URL so they cannot drift apart silently.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from application.api import settings

_LOG = logging.getLogger(__name__)

_TIMEOUT_S = 10

# The platform this module can actually do. The COLUMN on `jobs` is the dimension; this tuple is
# what makes an unimplemented one a clean refusal rather than a confusing empty list. The SPA shows
# a wider row of tabs (ESPN, Yahoo, MFL, FFPC) with only this one active — cosmetic there, decided
# here, and a mismatch surfaces as this module's own refusal rather than as a silent nothing.
IMPLEMENTED = ("sleeper",)

_SLEEPER_BASE = "https://api.sleeper.app/v1"

# A Sleeper league_id is an 18-19 digit snowflake — the rule the codebase already states, at
# `data_layer.SYNTHETIC_LEAGUE_IDS`, where the synthetic ids are deliberately NOT this shape so that
# anything mistaking `DEMO-2025` for a real league fails loudly. Reused here so the dual-mode input
# ("Username or League ID…") discriminates by the same rule the store does, rather than by a second
# one that could disagree with it.
_LEAGUE_ID_RE = re.compile(r"^\d{18,19}$")

# Sleeper's `settings.type`: 0 redraft / 1 keeper / 2 dynasty. Mirrors `sleeper._LEAGUE_TYPE`.
_LEAGUE_TYPE = {0: "redraft", 1: "keeper", 2: "dynasty"}

# The reception tiers V1 has a 2026 substrate for. `std` (rec = 0) is deliberately absent: the
# forward substrate was built for {ppr, half} only, so a standard league would be the first on its
# scoring key and the worker would refuse it — see `run_chain`'s substrate assertion.
_SUPPORTED_REC = {1.0: "PPR", 0.5: "half-PPR"}

# Real-world weight-precision guard, and it is not theoretical — `transforms/_scoring.py` carries
# the same constant for the same reason after Session 0.6 shipped an exact comparison: Sleeper
# serves scoring weights at float32, so a "0.5" can arrive as 0.50000000745, and `rec in {1.0, 0.5}`
# would classify a perfectly ordinary half-PPR league as custom and grey it out with no appeal.
# 1e-6 sits above that drift (~1.5e-9) and far below the smallest REAL deviation (0.01).
_REC_TOL = 1e-6


# Sleeper's league `status`: the lifecycle, not the format. `pre_draft` and `drafting` mean NO
# ROSTERS EXIST YET; `in_season` / `post_season` / `complete` all mean the league is playable.
# Absence is treated as playable rather than refused — unlike `settings.type`, where absence is
# refused — because a missing lifecycle field is a Sleeper-side omission about a league that
# demonstrably exists, while a missing type genuinely does not tell us whether it is redraft.
_NOT_STARTED = {"pre_draft": "the draft hasn't happened yet",
                "drafting": "the draft is still in progress"}


def league_has_started(league: dict) -> tuple[bool, str | None]:
    """``(started, reason)`` — has this league drafted, i.e. do rosters exist? (P5/S4d)

    **ONE predicate, two callers, deliberately.** It lives here, beside `classify`, because
    `application/api/` is the half BOTH images have: the API serves it, and the worker imports it
    (`worker_loop.py` already does `from application.api import jobs, platforms`, and reads
    `platforms.IMPLEMENTED` for exactly this kind of scope refusal). The reverse import is
    forbidden and gated — `check_connect`'s ONE IMAGE leg fails on any `application.data` import
    under `api/` — so a shared rule has to travel in this direction. Same move as `jobs.enqueue`.

    - On the **API** it is advisory: `classify` greys the league out with the reason.
    - On the **WORKER** it is authoritative: `onboard_league.assert_in_scope` refuses. That is the
      one that has to be right, because `POST /api/connect` with a pasted league id runs no
      classification at all.

    **It costs nothing to call.** `sleeper.league_summary()` already returns `status` and `onboard()`
    already calls it immediately before `assert_in_scope`, so the worker is reading a key on a dict
    it is holding. Discovery likewise gets it in the same response that carries `scoring_settings`.

    **Do NOT confuse this with "zero completed weeks."** Before Week 1 every league has zero
    completed weeks, so refusing on that would refuse the entire cohort; a DRAFTED preseason league
    is the designed path (rosters + projections, actuals zero-filled). This asks only whether
    rosters exist at all — see `onboard_league.run_chain`'s zero-week refusal for the other question.

    **P5/S4f replaces the BRANCH, not this predicate**: it holds a not-yet-started league as
    `pending` instead of refusing it. Keep this pure so that swap stays a one-line change.
    """
    reason = _NOT_STARTED.get((league.get("status") or "").strip().lower())
    return (reason is None), reason


class PlatformUnsupported(Exception):
    """Asked for a platform with no implementation behind it."""


class LookupFailed(Exception):
    """The platform could not be reached, or does not know this handle."""


def is_league_id(text: str) -> bool:
    """True when this input is a league id rather than a handle — the dual-mode input's rule."""
    return bool(_LEAGUE_ID_RE.match((text or "").strip()))


def _get(url: str):
    """One GET, decoded. Returns None on 404 so "no such user" is a value rather than an exception."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise LookupFailed(f"{url} → HTTP {err.code}") from err
    except Exception as exc:      # noqa: BLE001 — DNS, TLS, timeout: all one thing to the caller
        raise LookupFailed(f"{url} → {type(exc).__name__}: {exc}") from exc


def _require_implemented(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p not in IMPLEMENTED:
        raise PlatformUnsupported(p or "(none)")
    return p


def resolve_user_id(platform: str, handle: str) -> str | None:
    """A handle → that platform's user id, or None when the platform has never heard of it.

    Called twice in the flow and that is intentional: once by discovery, and again at enqueue, so
    the id stored on the job is always one this server resolved rather than one a client echoed
    back. It is not an authorization field — see `jobs._GRANT` on why no ownership verification
    exists — but a server-resolved value costs one GET and removes a whole class of "the client
    sent something odd" question from the worker's end.
    """
    _require_implemented(platform)
    user = _get(f"{_SLEEPER_BASE}/user/{urllib.parse.quote(str(handle).strip(), safe='')}")
    return str(user["user_id"]) if user and user.get("user_id") else None


def classify(league: dict, *, season: int, current_season: int) -> tuple[bool, str | None]:
    """``(supported, reason)`` for one league — **advisory, and that word is load-bearing.**

    **This is not the gate, and it must never be treated as one** (a disabled button in a React app
    is a suggestion). The authorities are `onboard_league.assert_in_scope` and `run_chain`'s
    substrate assertion, both on the worker, both of which raise `SystemExit` and land the job in
    `rejected`; S5 owns the authoritative preflight and the rejection copy that goes with it. What
    this does is stop the reject path from becoming the COMMON path: a blind bulk import of every
    league a handle plays in would enqueue a pile of jobs most of which are refused, and a product
    whose usual outcome is a refusal has taught the user to distrust it.

    So it only reports what it can POSITIVELY rule out, and every rule mirrors a real downstream
    gate rather than inventing a policy:

    - **not redraft** → exactly `assert_in_scope`, including its rule that ABSENCE IS NOT REDRAFT
      (the corpus recovery found 7 known keeper/dynasty leagues with the key missing, so an unknown
      type is refused rather than guessed).
    - **reception tier** → the {ppr, half} 2026 substrate that exists. Anything else is the first
      league on its scoring key and `run_chain` refuses it in as many words.
    - **not the current season** → `reads.visible`'s owned term. A prior-season league would build
      and then be invisible to the person who linked it, which is the worst kind of success.
    - **not drafted yet** → `league_has_started`, the SAME function `assert_in_scope` refuses on.
      Checked LAST, because it is the only one of the four that is temporary: a `pre_draft` league
      becomes linkable on its own, while a dynasty league never does, and the more durable reason
      is the more useful one to show. (P5/S4f turns this branch into a *pending* hold.)

    **Deliberately NOT judged here: roster shape.** 1QB and superflex are both in scope, K/DEF/IDP
    slots are ignored by a skill-positions-only engine rather than fatal to it, and greying out a
    league the worker would happily build is a false refusal with no appeal — strictly worse than
    letting the real gate speak. `roster_positions` arrives in the same response for free; it is
    read by nothing here on purpose.
    """
    if int(season) != int(current_season):
        return False, f"{season} season — only {current_season} leagues can be linked"

    raw_type = (league.get("settings") or {}).get("type")
    kind = _LEAGUE_TYPE.get(raw_type) if raw_type is not None else None
    if kind != "redraft":
        return False, f"{kind or 'unknown'} league — this build supports redraft only"

    rec = (league.get("scoring_settings") or {}).get("rec")
    try:
        # Absence means no points per reception, i.e. standard — not "unknown". That is the
        # opposite of how `settings.type` is treated above, and both are right: a missing `rec` has
        # a well-defined meaning (zero), while a missing league type does not.
        rec_val = float(rec) if rec is not None else 0.0
    except (TypeError, ValueError):
        rec_val = None
    if rec_val is None or not any(abs(rec_val - v) < _REC_TOL for v in _SUPPORTED_REC):
        label = "standard scoring (no PPR)" if rec_val == 0.0 else "custom scoring"
        return False, f"{label} — this build supports PPR and half-PPR"

    started, why = league_has_started(league)
    if not started:
        return False, f"{why} — link it once your season is under way"
    return True, None


def _shape(league: dict, season: int, current_season: int) -> dict:
    supported, reason = classify(league, season=season, current_season=current_season)
    return {
        "league_id": str(league.get("league_id")),
        "name": league.get("name") or f"League {league.get('league_id')}",
        "season": int(season),
        "total_rosters": league.get("total_rosters"),
        "supported": supported,
        "reason": reason,
    }


def discover(platform: str, handle: str, *, current_season: int) -> dict:
    """Every league this handle plays in that is worth showing, marked supported/unsupported.

    **Two seasons, not one, and it costs one extra GET.** Offering only the current season is the
    rule (V1 is redraft, so a prior season has no product value and `visible` would hide it anyway)
    — but *showing nothing at all* is the wrong way to say so in preseason, when somebody's 2026
    league may not exist yet while their 2025 one plainly does. Returning last season's leagues
    greyed, with the reason, turns a mystifying empty list into an explanation. That is also what
    makes the season rule in `classify` do real work rather than being vacuous.

    **The season boundary is `settings.current_season()`, passed in, never a literal.** It is the
    same value `reads.visible` applies to the owned term, so the list cannot offer a league the
    catalog would then refuse to show — and a hardcoded year would rot in January, silently, after
    S2c deliberately replaced the season-override machinery with a local derivation.

    Raises `LookupFailed` if the platform is unreachable; returns `user_id: None` and no leagues
    when it simply does not know the handle. The two are different and the route says so.
    """
    _require_implemented(platform)
    user_id = resolve_user_id(platform, handle)
    if user_id is None:
        return {"platform": platform, "handle": handle, "platform_user_id": None, "leagues": []}

    out: list[dict] = []
    for season in (int(current_season), int(current_season) - 1):
        for lg in (_get(f"{_SLEEPER_BASE}/user/{user_id}/leagues/nfl/{season}") or []):
            if lg.get("league_id"):
                out.append(_shape(lg, season, current_season))

    # Supported first, then newest, then by name — the SPA renders this order verbatim, and the
    # thing a person came to do belongs at the top rather than mixed in with what they cannot have.
    out.sort(key=lambda l: (not l["supported"], -l["season"], (l["name"] or "").lower()))
    return {"platform": platform, "handle": handle, "platform_user_id": user_id, "leagues": out}
