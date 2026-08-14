#!/usr/bin/env python3
"""Operator tooling for Gridiron accounts and league ownership (P5/S1b, extended S2a).

    python3 scripts/users.py --ban someone@example.com
    python3 scripts/users.py --unban someone@example.com

    application/api/.venv/bin/python scripts/users.py --delete someone@example.com

    application/api/.venv/bin/python scripts/users.py --list
    application/api/.venv/bin/python scripts/users.py --grant  someone@example.com 1207735666645946368
    application/api/.venv/bin/python scripts/users.py --revoke someone@example.com 1207735666645946368

**Two interpreters, and the split is deliberate.** `--ban`/`--unban` are the emergency path — the
thing you run when a code has spread further than intended — so they stay stdlib-only and run
under any interpreter, exactly as S1b built them. The S2a ownership commands write to Postgres,
which means `psycopg` + `python-dotenv`, so they need one of the project venvs. The import is
therefore LAZY (see `_db`): needing a venv to grant a league must not cost you the ability to
throw someone out from a bare shell.

**What a grant means, and what it does not.** `--grant` is operator tooling standing in for the
S4 connect flow, so S2a has data to prove isolation against without waiting on S4. It asserts
that a league belongs to an account; it asserts nothing about the human behind that account —
S1b creates accounts confirmed BEFORE the magic link is known to have sent, so an address nobody
controls can hold one. Grant deliberately, not on request.

**Was `invite.py`, and the rename is the point.** S1 built an invite tool because the brief read
"word of mouth" as Will provisioning each person by hand. He meant only that he wouldn't promote
the site — people sign themselves up. So signup is now self-serve behind a shared access code
(`application/api/signup.py`), nobody is invited, and the invite command has no reason to exist.

What self-serve *does* create is the need to throw someone out, which an invite-only system never
has: with a gate, you simply never let them in. Hence `--ban`. The code is the front door; this is
the lock after the fact, and it's also the response to a code that has spread further than
intended (ban the accounts, rotate the code — one config change, no migration).

**`--delete` is the other half, added in P5/S4c**, and the two are not interchangeable: a ban keeps
the account and everything hanging off it, which is right for "this person must not get back in"
and wrong for "this account should never have existed". One GoTrue call removes the row and every
app-side table cascades — which is safe only because `auth_schema.sql` declares `ON DELETE CASCADE`
on all four and `init_auth_schema --verify` asserts the constraint rather than assuming it.

**What a grant means changed in P5/S4c.** `--grant` was operator tooling standing in for the connect
flow; that flow now exists, so a row in `user_leagues` usually appears because somebody linked their
own league and the worker's job reached `ready`. These commands remain the operator's override, not
the mechanism.

Lives in `scripts/` rather than `application/api/` on purpose: the Dockerfile copies the whole api
package into the image, and admin tooling has no business being in the served image. (The API
*itself* now holds the secret key too, as of S1b's signup endpoint — but this file still isn't
something to ship.)

Uses Supabase's CURRENT secret key (`sb_secret_…`), which replaced the legacy `service_role` JWT.
Because the new keys are opaque strings rather than JWTs they belong in the `apikey` header and
NOT in `Authorization`; verified against the live project — `apikey` alone 200, `Authorization`
alone 401.

Uses stdlib urllib: no dependency, so it runs under any of the project's interpreters.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from application.api import settings  # noqa: E402

# GoTrue has no "banned forever" flag — a ban is a duration. 100 years is the idiom.
_FOREVER = "876000h"


def _call(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    base, key = settings.supabase_url(), settings.supabase_secret_key()
    if not base or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set.\n"
            "Add them to application/config.py (the gitignored secret home) — the secret key is\n"
            "admin-grade: never git, never the SPA bundle."
        )
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        # `apikey` only — the secret key is not a JWT, and relying on the matching-values
        # compatibility path would be borrowing against a deprecation.
        headers={"apikey": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:400]
        raise SystemExit(f"Supabase returned {err.code}: {detail}") from err


def _find(email: str) -> dict:
    """The user record for an address. Exits if there isn't one — nothing here should guess."""
    for u in _call("/admin/users?per_page=200").get("users", []):
        if (u.get("email") or "").lower() == email.lower():
            return u
    raise SystemExit(f"No account for {email}. `--list` shows who exists.")


def _db():
    """The API's Postgres seam, imported lazily. See the module docstring for why it is lazy."""
    from application.api import db
    return db


_OWNED = """
SELECT ul.user_id::text AS user_id, ul.league_id, ul.roster_id, dm.season, dm.name
FROM public.user_leagues ul
LEFT JOIN league_catalog dm ON dm.league_id = ul.league_id
ORDER BY ul.created_at
"""

_GRANT = """
INSERT INTO public.user_leagues (user_id, league_id, roster_id)
VALUES (%(uid)s, %(lid)s, %(rid)s)
ON CONFLICT (user_id, league_id) DO NOTHING
"""

# A re-grant that CORRECTS the seat has to update, not no-op. With plain DO NOTHING, fixing a wrong
# roster_id would print "already owned" and change nothing — the failure mode being silent is what
# makes it worth a second statement. Only runs when a seat was actually supplied, so a bare
# re-grant still never clobbers a seat that is already right.
_GRANT_SEAT = """
INSERT INTO public.user_leagues (user_id, league_id, roster_id)
VALUES (%(uid)s, %(lid)s, %(rid)s)
ON CONFLICT (user_id, league_id) DO UPDATE SET roster_id = EXCLUDED.roster_id
"""

_REVOKE = "DELETE FROM public.user_leagues WHERE user_id = %(uid)s AND league_id = %(lid)s"

_IN_CATALOG = "SELECT season, name FROM league_catalog WHERE league_id = %(lid)s"


def _owned_by_user() -> dict[str, list[dict]]:
    """`{user_id: [grant, …]}`. Returns {} rather than raising if Postgres is unreachable."""
    try:
        rows = _db().fetch_all(_OWNED)
    except Exception as exc:  # noqa: BLE001 — listing accounts must survive a DB problem
        print(f"  (could not read league ownership: {exc})")
        return {}
    owned: dict[str, list[dict]] = {}
    for r in rows:
        owned.setdefault(r["user_id"], []).append(r)
    return owned


def _season_line() -> str:
    """The resolved season + its source, so a CURRENT_SEASON left set cannot hide behind a list."""
    try:
        from application.api import settings
        return settings.describe_season()
    except Exception as exc:  # noqa: BLE001
        return f"current NFL season: UNRESOLVED ({exc})"


def list_users() -> None:
    users = _call("/admin/users?per_page=200").get("users", [])
    print(_season_line())
    print(f"demo league (world-readable): {_settings_demo() or 'UNSET'}\n")
    if not users:
        print("No accounts yet — nobody has signed up.")
        return
    owned = _owned_by_user()
    print(f"{len(users)} account(s):")
    for u in sorted(users, key=lambda x: x.get("created_at") or ""):
        seen = u.get("last_sign_in_at")
        flag = "  ⛔ BANNED" if u.get("banned_until") else ""
        print(f"  {u.get('email'):<40} created {(u.get('created_at') or '')[:10]}   "
              f"{('last in ' + seen[:10]) if seen else 'never signed in':<22}{flag}")
        grants = owned.get(u.get("id") or "", [])
        if not grants:
            print("      owns nothing — sees the demo only")
        for g in grants:
            label = f"{g['name']} {g['season']}" if g["name"] else "NOT IN THE CATALOG"
            seat = f"  seat: roster {g['roster_id']}" if g["roster_id"] is not None else ""
            print(f"      owns {g['league_id']}  {label}{seat}")


def _settings_demo() -> str | None:
    return settings.demo_league_id()


def grant(email: str, league_id: str, roster_id: str | None = None) -> None:
    """Give an account a league, optionally with the seat that is "them" in it (P5/S2b).

    Idempotent — re-granting is a no-op and says so. Supplying a roster_id UPDATES it, because a
    correction that silently does nothing is worse than an error.

    The seat is what makes viewer identity a user × league property: two people in the same league
    need different "you" highlights, and until S2b that was a property of the league. Omit it and
    the caller falls back to MY_USERNAME, which is exactly the demo's existing behaviour.
    """
    user = _find(email)
    rid = int(roster_id) if roster_id is not None else None
    sql = _GRANT_SEAT if rid is not None else _GRANT
    n = _db().execute(sql, {"uid": user["id"], "lid": str(league_id), "rid": rid})
    seat = f" (seat: roster {rid})" if rid is not None else ""
    if n:
        print(f"✓ granted {league_id} to {email}{seat}")
    else:
        print(f"= {email} already owned {league_id} — nothing changed")

    # A league the catalog doesn't know about is a legitimate state (S4 catalogs a user's real
    # league when they connect it), but it will not APPEAR for them until then. Warn, don't block:
    # refusing here would make this tool useless the moment it is needed for a real user.
    rows = _db().fetch_all(_IN_CATALOG, {"lid": str(league_id)})
    if not rows:
        print(f"  ⚠ {league_id} is not in league_catalog, so it cannot surface in the catalog yet.")
        print("    The grant is recorded and will take effect once the league is catalogued (S4).")
    else:
        print(f"  in the catalog as {rows[0]['name']} {rows[0]['season']}")


def revoke(email: str, league_id: str) -> None:
    """Take a league away. A revoke of something never granted is a clean no-op, not an error."""
    user = _find(email)
    n = _db().execute(_REVOKE, {"uid": user["id"], "lid": str(league_id)})
    if n:
        print(f"✓ revoked {league_id} from {email}")
        print("  They lose it on their next catalog read. An access token already issued does NOT")
        print("  carry the grant — ownership is read per request, not baked into the token.")
    else:
        print(f"= {email} did not own {league_id} — nothing to revoke")


_COUNT_ROWS = """
SELECT (SELECT count(*) FROM public.user_leagues     WHERE user_id = %(uid)s::uuid)::int AS leagues,
       (SELECT count(*) FROM public.jobs             WHERE requested_by = %(uid)s::uuid)::int AS jobs,
       (SELECT count(*) FROM public.connect_attempts WHERE user_id = %(uid)s::uuid)::int AS lookups,
       (SELECT count(*) FROM public.app_users        WHERE id = %(uid)s::uuid)::int AS profile
"""


def delete(email: str, *, yes: bool = False) -> None:
    """Remove an account and everything hanging off it (P5/S4c).

    **Why this exists now and not in S1b.** `--ban` was the answer while a code could spread further
    than intended: with an invite gate you never let somebody in, so the only need was to throw them
    out. Self-serve signup created the other need — an account that should not exist at all, an
    address entered by mistake, somebody asking to be removed — and a ban leaves the row, the
    profile, the grants and the job history in place.

    **The delete itself is one GoTrue call, and everything else goes by CASCADE.** Every app-side
    table that names a user declares `ON DELETE CASCADE` (`auth_schema.sql`), and
    `init_auth_schema --verify` asserts that constraint rather than assuming it — which is what
    makes one call safe. The counts below are printed BEFORE and verified AFTER, because a cascade
    that silently did not fire looks exactly like a cascade that did.

    Deliberately interactive by default: this is the one irreversible command in this file.
    """
    user = _find(email)
    uid = user["id"]
    try:
        before = _db().fetch_all(_COUNT_ROWS, {"uid": uid})[0]
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Could not read what {email} owns ({exc}).\n"
            "Refusing to delete: this command reports what it removed, and it cannot do that "
            "without counting first.") from exc

    print(f"About to DELETE {email} ({uid}) and, by cascade:")
    print(f"  {before['profile']} profile row · {before['leagues']} league grant(s) · "
          f"{before['jobs']} job(s) · {before['lookups']} lookup record(s)")
    if not yes:
        if input("Type the address again to confirm: ").strip().lower() != email.lower():
            raise SystemExit("Not deleted.")

    _call(f"/admin/users/{uid}", method="DELETE")

    after = _db().fetch_all(_COUNT_ROWS, {"uid": uid})[0]
    left = {k: v for k, v in after.items() if v}
    if left:
        # The cascade is asserted by init_auth_schema, so this should be unreachable — which is
        # exactly why it is worth saying loudly rather than trusting.
        print(f"⚠ the account is gone but rows REMAIN: {left}")
        print("  A foreign key is missing or is not ON DELETE CASCADE. Run "
              "`init_auth_schema --verify`.")
        raise SystemExit(1)
    print(f"✓ deleted {email} — profile, grants, jobs and lookups all cascaded away (0 rows left)")
    print("  Their current access token stays valid until it expires (about an hour), exactly as")
    print("  with --ban; but it now names a user that no longer exists, so every scoped read")
    print("  refuses and the catalog falls back to the public demo.")


def set_ban(email: str, *, banned: bool) -> None:
    user = _find(email)
    _call(f"/admin/users/{user['id']}", method="PUT",
          body={"ban_duration": _FOREVER if banned else "none"})
    if banned:
        print(f"⛔ banned {email}")
        print("  They can no longer sign in. Existing sessions are NOT revoked instantly — their")
        print("  current access token stays valid until it expires (about an hour).")
    else:
        print(f"✓ unbanned {email} — they can sign in again (with the access code, as before)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="show every account and what it owns")
    ap.add_argument("--ban", metavar="EMAIL", help="block an account from signing in")
    ap.add_argument("--unban", metavar="EMAIL", help="restore a banned account")
    ap.add_argument("--grant", nargs="+", metavar="EMAIL LEAGUE_ID [ROSTER_ID]",
                    help="give an account a league, optionally with its viewer seat (idempotent)")
    ap.add_argument("--revoke", nargs=2, metavar=("EMAIL", "LEAGUE_ID"),
                    help="take a league away from an account")
    ap.add_argument("--delete", metavar="EMAIL",
                    help="remove an account entirely (profile, grants, jobs — all by cascade)")
    ap.add_argument("--yes", action="store_true",
                    help="skip --delete's confirmation prompt (for scripted runs)")
    a = ap.parse_args()
    if a.delete:
        delete(a.delete, yes=a.yes)
    elif a.ban:
        set_ban(a.ban, banned=True)
    elif a.unban:
        set_ban(a.unban, banned=False)
    elif a.grant:
        if not 2 <= len(a.grant) <= 3:
            ap.error("--grant takes EMAIL LEAGUE_ID [ROSTER_ID]")
        grant(*a.grant)
    elif a.revoke:
        revoke(*a.revoke)
    elif a.list:
        list_users()
    else:
        ap.error("one of --list, --ban EMAIL, --unban EMAIL, --delete EMAIL, "
                 "--grant EMAIL LEAGUE_ID, --revoke EMAIL LEAGUE_ID")
