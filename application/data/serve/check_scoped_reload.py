"""
Parity oracle for the per-league SCOPED RELOAD (P2/S2) — the safety net for the single riskiest V1
change (build_db.py's loader). Proves that ``build_db.load_league`` (delete + re-COPY one league in one
transaction) produces **exactly** what the whole-DB DROP+CREATE ``load()`` produces for that league, on
its already-loaded weeks — the B3 discipline applied to the loader.

**Non-destructive on prod (the default).** The deployed DB is already the output of a full ``--load``, so
its current rows for a league ARE the full-load baseline. So we don't rebuild: snapshot the anchor
league's rows → scoped-reload it → snapshot again → compare. No DROP+CREATE touches prod, and only the
anchor league is written (atomically). ``--full-baseline`` (a destructive full ``--load`` first) exists
only for a throwaway/local DB and refuses a prod host unless ``--allow-prod``.

Verdicts (exit 0 iff all pass), for the is_mine anchor league:

  1. **Parity**       — per table, scoped-reload rows == the pre-reload (full-load) rows (value-equal).
  2. **Idempotency**  — a second scoped reload reproduces the same rows (no drift, no dup).
  3. **Isolation**    — a second, untouched league's rows are byte-for-byte identical across the reload.
  Plus ``--prove-bites``: a deleted / perturbed row must fail the comparator (the gate has teeth).

Value equality, not byte: COPY row order is nondeterministic, so we compare a **canonical row multiset**
(``json.dumps(row, sort_keys=True, default=str)`` sorted) — order-insensitive and JSONB/empty-safe
(polars ``.sort(cols)`` can't order the ``ros_synthesis.headlines`` JSONB or a height-0 table).

Usage (prod, non-destructive):
    application/venv/bin/python -m application.data.serve.check_scoped_reload --prove-bites
"""

import argparse
import json
import sys

from application.api import db
from application.data.serve import build_db as B


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _snapshot(lid: str) -> dict[str, list[dict]]:
    """Every data table's rows for one league, read back from Postgres (SELECT * → DDL column order)."""
    return {ds.table: db.fetch_all(f'SELECT * FROM "{ds.table}" WHERE league_id = %(lid)s', {"lid": lid})
            for ds in B.DATASETS}


def _canon(rows: list[dict]) -> list[str]:
    """Order-insensitive canonical form of a row set — a sorted multiset of JSON-encoded rows. JSONB
    columns arrive as Python objects; dates/Decimals fall back to str. Robust to COPY's row-order
    nondeterminism and to empty tables (which polars sort-by-all-columns cannot handle)."""
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def _rows_eq(a: list[dict], b: list[dict]) -> bool:
    return _canon(a) == _canon(b)


def _tables_eq(before: dict, after: dict, label: str, results: list) -> None:
    for ds in B.DATASETS:
        t = ds.table
        eq = _rows_eq(before.get(t, []), after.get(t, []))
        if not eq:
            _fail(f"{label}: {t} differs (before={len(before.get(t, []))} after={len(after.get(t, []))})")
        results.append(eq)


def _other_league() -> str:
    for lid, _s, _sk in B._slices():
        if lid != B.LEAGUE_ID:
            return lid
    raise SystemExit("no second league to test isolation against")


def _host() -> str:
    url = db.database_url()
    return url.split("@")[-1].split("/")[0] if "@" in url else url


def check(*, full_baseline: bool = False, allow_prod: bool = False) -> bool:
    anchor = B.LEAGUE_ID
    other = _other_league()
    print(f"  target DB host: {_host()}")
    print(f"  anchor (is_mine) league: {anchor} · isolation league: {other}")
    results: list = []

    if full_baseline:
        if ("supabase" in _host() or "pooler" in _host()) and not allow_prod:
            raise SystemExit("--full-baseline runs a destructive full --load; refusing a prod host "
                             "without --allow-prod. Point DATABASE_URL at a throwaway DB.")
        print("  [--full-baseline] running a full DROP+CREATE --load as the baseline...")
        B.load()

    # Baseline = the current (full-load) state of the anchor + the isolation league.
    before = _snapshot(anchor)
    other_before = _snapshot(other)

    # Scoped reload of the anchor only.
    print(f"  scoped-reloading {anchor}...")
    B.reload_league(anchor)
    after = _snapshot(anchor)
    other_after = _snapshot(other)

    # 1. Parity — scoped == full-load, per table.
    print("\n  [1] parity: scoped reload == full-load rows (per table)")
    _tables_eq(before, after, "parity", results)
    if all(results):
        _ok(f"parity holds across all {len(B.DATASETS)} tables")

    # 3. Isolation — the other league is untouched by the anchor's scoped reload.
    print("  [3] isolation: a second league is untouched")
    iso: list = []
    _tables_eq(other_before, other_after, "isolation", iso)
    _ok(f"league {other} unchanged across the reload") if all(iso) else None
    results += iso

    # 2. Idempotency — a second scoped reload reproduces the same rows.
    print("  [2] idempotency: a second scoped reload is a no-op")
    B.reload_league(anchor)
    again = _snapshot(anchor)
    idem: list = []
    _tables_eq(after, again, "idempotency", idem)
    _ok("second scoped reload reproduced identical rows") if all(idem) else None
    results += idem

    return all(results)


def _bites() -> bool:
    """Prove the comparator has teeth: a deleted or perturbed row must fail _rows_eq."""
    print("\n  [prove-bites]")
    rows = db.fetch_all('SELECT * FROM "production_vor" WHERE league_id = %(l)s', {"l": B.LEAGUE_ID})
    results: list = []

    drop_bites = not _rows_eq(rows, rows[:-1])
    (_ok if drop_bites else _fail)("a dropped row fails _rows_eq")
    results.append(drop_bites)

    if rows:
        k = next(c for c, v in rows[0].items() if isinstance(v, (int, float)) and c != "season")
        perturbed = [{**rows[0], k: (rows[0][k] or 0) + 1}, *rows[1:]]
        perturb_bites = not _rows_eq(rows, perturbed)
        (_ok if perturb_bites else _fail)(f"a perturbed {k} fails _rows_eq")
        results.append(perturb_bites)

    return all(results)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parity oracle for the per-league scoped reload.")
    ap.add_argument("--full-baseline", action="store_true",
                    help="run a destructive full --load as the baseline (throwaway DB only)")
    ap.add_argument("--allow-prod", action="store_true", help="permit --full-baseline against a prod host")
    ap.add_argument("--prove-bites", action="store_true", help="also demonstrate the comparator's teeth")
    args = ap.parse_args()
    print("=== check_scoped_reload ===")
    ok = check(full_baseline=args.full_baseline, allow_prod=args.allow_prod)
    if args.prove_bites:
        ok = _bites() and ok
    print("\nPASS" if ok else "\nFAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
