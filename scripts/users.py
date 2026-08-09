#!/usr/bin/env python3
"""Operator tooling for Gridiron accounts and league ownership (P5/S1b, extended S2a).

    python3 scripts/users.py --ban someone@example.com
    python3 scripts/users.py --unban someone@example.com

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
SELECT ul.user_id::text AS user_id, ul.league_id, dm.season, dm.name
FROM public.user_leagues ul
LEFT JOIN demo_manifest dm ON dm.league_id = ul.league_id
ORDER BY ul.created_at
"""

_GRANT = """
INSERT INTO public.user_leagues (user_id, league_id) VALUES (%(uid)s, %(lid)s)
ON CONFLICT (user_id, league_id) DO NOTHING
"""

_REVOKE = "DELETE FROM public.user_leagues WHERE user_id = %(uid)s AND league_id = %(lid)s"

_IN_CATALOG = "SELECT season, name FROM demo_manifest WHERE league_id = %(lid)s"


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
        from application.api import nfl_state
        return nfl_state.describe()
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
            print(f"      owns {g['league_id']}  {label}")


def _settings_demo() -> str | None:
    return settings.demo_league_id()


def grant(email: str, league_id: str) -> None:
    """Give an account a league. Idempotent — re-granting is a no-op, and says so."""
    user = _find(email)
    n = _db().execute(_GRANT, {"uid": user["id"], "lid": str(league_id)})
    if n:
        print(f"✓ granted {league_id} to {email}")
    else:
        print(f"= {email} already owned {league_id} — nothing changed")

    # A league the catalog doesn't know about is a legitimate state (S4 catalogs a user's real
    # league when they connect it), but it will not APPEAR for them until then. Warn, don't block:
    # refusing here would make this tool useless the moment it is needed for a real user.
    rows = _db().fetch_all(_IN_CATALOG, {"lid": str(league_id)})
    if not rows:
        print(f"  ⚠ {league_id} is not in demo_manifest, so it cannot surface in the catalog yet.")
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
    ap.add_argument("--grant", nargs=2, metavar=("EMAIL", "LEAGUE_ID"),
                    help="give an account a league (idempotent)")
    ap.add_argument("--revoke", nargs=2, metavar=("EMAIL", "LEAGUE_ID"),
                    help="take a league away from an account")
    a = ap.parse_args()
    if a.ban:
        set_ban(a.ban, banned=True)
    elif a.unban:
        set_ban(a.unban, banned=False)
    elif a.grant:
        grant(*a.grant)
    elif a.revoke:
        revoke(*a.revoke)
    elif a.list:
        list_users()
    else:
        ap.error("one of --list, --ban EMAIL, --unban EMAIL, --grant EMAIL LEAGUE_ID, "
                 "--revoke EMAIL LEAGUE_ID")
