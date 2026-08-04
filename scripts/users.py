#!/usr/bin/env python3
"""Operator tooling for Gridiron accounts (P5/S1b).

    python3 scripts/users.py --list
    python3 scripts/users.py --ban someone@example.com
    python3 scripts/users.py --unban someone@example.com

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


def list_users() -> None:
    users = _call("/admin/users?per_page=200").get("users", [])
    if not users:
        print("No accounts yet — nobody has signed up.")
        return
    print(f"{len(users)} account(s):")
    for u in sorted(users, key=lambda x: x.get("created_at") or ""):
        seen = u.get("last_sign_in_at")
        flag = "  ⛔ BANNED" if u.get("banned_until") else ""
        print(f"  {u.get('email'):<40} created {(u.get('created_at') or '')[:10]}   "
              f"{('last in ' + seen[:10]) if seen else 'never signed in':<22}{flag}")


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
    ap.add_argument("--list", action="store_true", help="show every account")
    ap.add_argument("--ban", metavar="EMAIL", help="block an account from signing in")
    ap.add_argument("--unban", metavar="EMAIL", help="restore a banned account")
    a = ap.parse_args()
    if a.ban:
        set_ban(a.ban, banned=True)
    elif a.unban:
        set_ban(a.unban, banned=False)
    elif a.list:
        list_users()
    else:
        ap.error("one of --list, --ban EMAIL, --unban EMAIL")
