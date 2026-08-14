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
_TABLES = ["app_users", "signup_attempts", "user_leagues", "jobs"]

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

# Foreign keys that must exist AND cascade on delete (S2a audit F2, closed in S2c). Deleting an
# account has to take its grants with it; if the FK is missing or its delete action is anything
# but CASCADE, a deleted user's rows survive and `user_leagues` starts granting leagues to ids
# that no longer name anybody.
#
# S2b DELETED two accounts and counted zero leftover rows, which is a fine measurement and not an
# invariant: `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so a database that
# already had these tables in another shape keeps that shape and nothing notices — the same F2
# trap `_ALTERED_COLUMNS` exists for, one level down at the constraint instead of the column.
#
# P5/S4b NOTE, because the brief said this was inherited from `_TABLES` and it is not: the cascade
# assertion is driven by THIS list, `_verify_cascades` iterates it, and `_TABLES` drives only the
# column dump and the leaked-into-schema.sql check. Adding a table to `_TABLES` alone means its FK
# is never asserted. `jobs.requested_by` is here because attribution must not outlive an account
# either — a job row naming a deleted user is the same defect as a grant naming one.
_CASCADE_FKS = [("user_leagues", "user_id"), ("app_users", "id"), ("jobs", "requested_by")]

# `confdeltype` is the ON DELETE action: 'c' = CASCADE, 'a' = NO ACTION, 'r' = RESTRICT,
# 'n' = SET NULL, 'd' = SET DEFAULT. Reading pg_constraint directly because information_schema
# reports the action as prose that varies by server version.
_FK_SQL = """
SELECT c.conname, c.confdeltype, a.attname AS column_name
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
WHERE c.contype = 'f' AND c.conrelid = ('public.' || %(t)s)::regclass
"""

# `AND t.{column} IS NOT NULL` is load-bearing and was added in P5/S4b for `jobs.requested_by`, the
# first NULLABLE cascade FK here. A LEFT JOIN that finds no user reports u.id IS NULL for an
# unmatched row AND for a row that never named a user at all, so without this clause every job
# enqueued by hand — which is every job in S4b — would be counted as an orphan and `--verify` would
# fail on correct data. The two pre-existing entries were safe only because `user_leagues.user_id`
# is NOT NULL and `app_users.id` is a primary key.
_ORPHANS_SQL = """
SELECT count(*)::int AS n
FROM public.{table} t LEFT JOIN auth.users u ON u.id = t.{column}
WHERE u.id IS NULL AND t.{column} IS NOT NULL
"""


def _verify_cascades() -> bool:
    """Assert the constraint, not just the column — and then count what it is supposed to prevent."""
    ok = True
    for table, column in _CASCADE_FKS:
        try:
            fks = db.fetch_all(_FK_SQL, {"t": table})
        except Exception as exc:  # noqa: BLE001 — a missing table is reported by the loop below
            print(f"✗ could not read the foreign keys on public.{table}: {exc}")
            ok = False
            continue
        cascading = [f for f in fks
                     if f["column_name"] == column and f["confdeltype"] == "c"]
        present = [f for f in fks if f["column_name"] == column]
        if cascading:
            print(f"  ok  public.{table}.{column} → auth.users ON DELETE CASCADE "
                  f"({cascading[0]['conname']})")
        elif present:
            print(f"✗ public.{table}.{column} has a foreign key ({present[0]['conname']}) but its "
                  f"ON DELETE action is {present[0]['confdeltype']!r}, not 'c' (CASCADE) — "
                  "deleting an account would leave its rows behind")
            ok = False
        else:
            print(f"✗ public.{table}.{column} has NO foreign key to auth.users — nothing makes "
                  "a deleted account's rows go away")
            ok = False

        try:
            n = db.fetch_all(_ORPHANS_SQL.format(table=table, column=column))[0]["n"]
        except Exception as exc:  # noqa: BLE001 — the API role may not be able to read auth.users
            print(f"  ??  orphan count for public.{table} UNAVAILABLE ({exc}) — the cascade is "
                  "asserted above, but nothing counted what it prevents")
            continue
        if n == 0:
            print(f"  ok  public.{table}: 0 rows point at a user that no longer exists")
        else:
            print(f"✗ public.{table}: {n} ORPHAN row(s) — grants outliving their account")
            ok = False
    return ok


def verify() -> bool:
    ok = _verify_cascades()
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
