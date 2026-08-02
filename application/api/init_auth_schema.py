"""Apply `auth_schema.sql` — the project's first hand-written DDL (P5/S1).

Every other table in this store is created by `build_db.py --emit`/`--load`, which regenerates
its schema file and DROPs what it names. `app_users` must outlive that, so it lives in its own
idempotent script instead. See auth_schema.sql's header for why that is a structural guarantee
rather than a convention.

    application/api/.venv/bin/python -m application.api.init_auth_schema
    application/api/.venv/bin/python -m application.api.init_auth_schema --verify
"""

from __future__ import annotations

import argparse
from pathlib import Path

from application.api import db

_SQL_PATH = Path(__file__).resolve().parent / "auth_schema.sql"

_VERIFY_SQL = """
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'app_users'
ORDER BY ordinal_position
"""


def apply() -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_PATH.read_text())
        conn.commit()
    print(f"applied {_SQL_PATH.name}")


def verify() -> bool:
    cols = db.fetch_all(_VERIFY_SQL)
    if not cols:
        print("✗ public.app_users does not exist")
        return False
    print("public.app_users:")
    for c in cols:
        print(f"  {c['column_name']:<12} {c['data_type']:<26} "
              f"{'NULL' if c['is_nullable'] == 'YES' else 'NOT NULL'}")
    # The whole point of this file is that a full loader run cannot touch the table, so prove
    # it isn't in the generated DDL rather than trusting the comment that says so.
    schema_sql = (_SQL_PATH.parents[1] / "data" / "serve" / "schema.sql")
    if schema_sql.exists() and "app_users" in schema_sql.read_text():
        print("✗ app_users appears in the GENERATED schema.sql — a --load would drop it")
        return False
    print("  ok  absent from the generated schema.sql (a full --load cannot drop it)")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify", action="store_true", help="inspect the table instead of applying")
    if ap.parse_args().verify:
        raise SystemExit(0 if verify() else 1)
    apply()
    raise SystemExit(0 if verify() else 1)
