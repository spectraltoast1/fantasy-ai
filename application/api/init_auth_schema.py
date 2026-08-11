"""Apply `auth_schema.sql` — the hand-written DDL the loader can't reach (P5/S1, extended S1b, S2a).

Every other table in this store is created by `build_db.py --emit`/`--load`, which regenerates
its schema file and DROPs what it names. These tables must outlive that, so they live in their
own idempotent script instead. See auth_schema.sql's header for why that is a structural
guarantee rather than a convention.

    application/api/.venv/bin/python -m application.api.init_auth_schema
    application/api/.venv/bin/python -m application.api.init_auth_schema --verify
"""

from __future__ import annotations

import argparse
from pathlib import Path

from application.api import db

_SQL_PATH = Path(__file__).resolve().parent / "auth_schema.sql"

# Every table this file owns. S1 hardcoded `app_users` in three places; S1b needed a second
# table, so the name lives here once instead — adding a third is now one list entry. S2a added
# two and that is exactly what it cost: two list entries, with the column dump and the
# absent-from-generated-DDL assertion inherited for free. S2c removed one of them again
# (`nfl_state_cache`, retired with the Sleeper call it cached) — one list entry, same seam.
_TABLES = ["app_users", "signup_attempts", "user_leagues"]

_COLUMNS_SQL = """
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %(t)s
ORDER BY ordinal_position
"""


def apply() -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL_PATH.read_text())
        conn.commit()
    print(f"applied {_SQL_PATH.name}")


# Columns this file adds by ALTER rather than by CREATE, and which therefore have to be checked
# rather than assumed. `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so a column
# declared inside it never appears in a database that already has the table — the S2a-audit F2 trap,
# one level up. Listing them here means the assertion is inherited the same way the table list is.
_ALTERED_COLUMNS = [("user_leagues", "roster_id")]


def verify() -> bool:
    ok = True
    for table, column in _ALTERED_COLUMNS:
        cols = {c["column_name"] for c in db.fetch_all(_COLUMNS_SQL, {"t": table})}
        if column in cols:
            print(f"  ok  public.{table}.{column} present (added by ALTER, so it is checked)")
        else:
            print(f"✗ public.{table}.{column} is MISSING — the ALTER never ran on this database")
            ok = False

    for table in _TABLES:
        cols = db.fetch_all(_COLUMNS_SQL, {"t": table})
        if not cols:
            print(f"✗ public.{table} does not exist")
            ok = False
            continue
        print(f"public.{table}:")
        for c in cols:
            print(f"  {c['column_name']:<12} {c['data_type']:<26} "
                  f"{'NULL' if c['is_nullable'] == 'YES' else 'NOT NULL'}")

    # The whole point of this file is that a full loader run cannot touch these tables, so prove
    # they aren't in the generated DDL rather than trusting the comment that says so.
    schema_sql = _SQL_PATH.parents[1] / "data" / "serve" / "schema.sql"
    if schema_sql.exists():
        generated = schema_sql.read_text()
        leaked = [t for t in _TABLES if t in generated]
        if leaked:
            print(f"✗ {leaked} appear in the GENERATED schema.sql — a --load would drop them")
            ok = False
        else:
            print(f"  ok  all {len(_TABLES)} absent from the generated schema.sql "
                  "(a full --load cannot drop them)")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify", action="store_true", help="inspect the tables instead of applying")
    if ap.parse_args().verify:
        raise SystemExit(0 if verify() else 1)
    apply()
    raise SystemExit(0 if verify() else 1)
