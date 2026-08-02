#!/usr/bin/env python3
"""Invite someone to Gridiron (P5/S1) — the admin half of the invite gate.

    python3 scripts/invite.py someone@example.com
    python3 scripts/invite.py --list

**The gate itself is not this script.** It is the Supabase project setting "Allow new users to
sign up", turned OFF — so there is no signup path to bypass. This is only the sanctioned way
IN. An app-side allow-list table was deliberately not built: that is a line of code that can be
bypassed if any other signup path exists, whereas a project that refuses to create users has
no such path. Sharing stays word-of-mouth; the mouth just routes through Will, which is the
point — nobody consumes pipeline compute on the single worker without him knowing.

Lives in `scripts/` rather than `application/api/` on purpose: the Dockerfile copies the whole
api package into the image, and admin tooling that reads a service-role key has no business
being in the served image. The key comes from `application/config.py` (gitignored) or the
environment, and is never passed as an argument — shell history is a file too.

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


def _call(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    base, key = settings.supabase_url(), settings.supabase_service_role_key()
    if not base or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.\n"
            "Add them to application/config.py (the gitignored secret home) — the service-role\n"
            "key is admin-grade: never git, never the Docker image, never the SPA bundle."
        )
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or "{}")
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:400]
        raise SystemExit(f"Supabase returned {err.code}: {detail}") from err


def invite(email: str) -> None:
    user = _call("/invite", method="POST", body={"email": email})
    print(f"✓ invited {email}")
    print(f"  user id: {user.get('id')}")
    print("  They now have an account and a sign-in email. Anyone NOT invited this way cannot")
    print("  create one — public signup is off at the project level.")


def list_users() -> None:
    users = _call("/admin/users?per_page=200").get("users", [])
    if not users:
        print("No users yet — nobody has been invited.")
        return
    print(f"{len(users)} user(s):")
    for u in sorted(users, key=lambda x: x.get("created_at") or ""):
        seen = u.get("last_sign_in_at")
        print(f"  {u.get('email'):<40} created {(u.get('created_at') or '')[:10]}   "
              f"{'last in ' + seen[:10] if seen else 'never signed in'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("email", nargs="?", help="the address to invite")
    ap.add_argument("--list", action="store_true", help="show who currently has an account")
    a = ap.parse_args()
    if a.list:
        list_users()
    elif a.email:
        invite(a.email)
    else:
        ap.error("give an email to invite, or --list")
