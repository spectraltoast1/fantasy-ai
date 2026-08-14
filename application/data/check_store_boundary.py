"""Gate for the store boundary — P5/S3.

The rule (ADR: context/appendices/store-boundary.md, ACCEPTED option (b)) is that data flows ONE
DIRECTION: the authoring laptop owns the shared substrate, and every other machine that runs this
pipeline reads it. A rule with nothing enforcing it is a comment, so this proves the enforcement.

**Both halves, always.** A refusal on its own proves nothing — a guard that refused *everything*
would pass a refusal-only test and make the worker useless. So every check here comes in a pair:
the laptop-owned write is refused AND the worker-owned write still succeeds.

Five legs (the fifth added by P5/S4b):

  1. REFUSES   — under STORE_ROLE=worker, every writer named in `LAPTOP_OWNED_WRITERS` raises
                 StoreBoundaryError. Driven off the constant itself, so a writer added to the list
                 without a guard (or a guard deleted from a listed writer) fails here.
  2. PERMITS   — under the same flag, a worker-owned write (derived/league) still succeeds and reads
                 back, and the per-league raw/join layer is untouched. P5/S4a added the twelfth
                 destination here: `write_connected_league`, the append-shaped catalog writer, which
                 a worker MAY call precisely because it replaces one row instead of the whole file.
  3. THE BAND  — the one laptop-owned writer that verifies instead of refusing, in all three of its
                 outcomes: identical → returns quietly, different → raises, missing → raises.
  4. OFF       — with STORE_ROLE unset (the laptop default), nothing raises and every writer behaves
                 exactly as it did before this session existed. This is the parity leg: the guard is
                 invisible unless a machine opts into it.
  5. DRIFT     — `build_db.assert_catalog_covers_postgres`, which points the OTHER way (P5/S4b).
                 Legs 1–4 stop a stale WORKER writing what the laptop owns. Since P5/S4a the worker
                 AUTHORS `connected_catalog.parquet` and the laptop does not have it, so the laptop
                 is the machine with the stale catalog and `--reload-manifest`/`--load` there would
                 delete connected leagues. Refuses on drift, PERMITS on agreement, and asserts the
                 guard is called BEFORE the TRUNCATE/DROP rather than merely existing.

Usage:
    application/venv/bin/python -m application.data.check_store_boundary
    application/venv/bin/python -m application.data.check_store_boundary --prove-bites
"""

import argparse
import ast
import inspect
import os
import sys
import textwrap

import polars as pl

from application.data import data_layer
from application.data.serve import build_db

# A season number no real artifact uses, so every write here lands beside the real store and is
# removed again. Same idiom as check_predictions' throwaway season.
TMP_SEASON = 99998
TMP_LEAGUE = "__STOREBOUNDARY__"

_results: list[bool] = []


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")
    _results.append(True)


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    _results.append(False)


class _Role:
    """Set STORE_ROLE for a block and restore whatever was there before.

    `store_role()` reads the env per call and is deliberately NOT memoised, so this takes effect
    mid-process — which is the whole reason it was written that way. If someone later adds caching,
    this gate fails rather than silently proving nothing.
    """

    def __init__(self, role: str | None):
        self.role, self.prev = role, None

    def __enter__(self):
        self.prev = os.environ.get("STORE_ROLE")
        if self.role is None:
            os.environ.pop("STORE_ROLE", None)
        else:
            os.environ["STORE_ROLE"] = self.role
        return self

    def __exit__(self, *exc):
        if self.prev is None:
            os.environ.pop("STORE_ROLE", None)
        else:
            os.environ["STORE_ROLE"] = self.prev
        return False


def _sweep() -> int:
    """Remove every artifact this gate can create, wherever it landed.

    Not optional housekeeping. `--prove-bites` neuters the guard, so the writers it drives really do
    write — and the store is SHARED (a worktree's snapshots/ and cache/ are symlinks into main), so
    an uncleaned run leaves throwaway rows in the real store for the next session to trip over. Two
    files escaped the first run of this gate; this function is why they cannot again.
    """
    removed = 0
    for base in (data_layer._SNAPSHOT_DIR, data_layer._CACHE_DIR):
        if not base.exists():
            continue
        for p in base.rglob(f"*{TMP_SEASON}*"):
            p.unlink(missing_ok=True)
            removed += 1
        for p in base.rglob(f"*{TMP_LEAGUE}*"):
            if p.is_file():
                p.unlink(missing_ok=True)
                removed += 1
    for d in (data_layer._league_dir(TMP_LEAGUE),):
        if d.exists() and not any(d.iterdir()):
            d.rmdir()
    removed += _sweep_connected_catalog_rows()
    return removed


def _sweep_connected_catalog_rows() -> int:
    """The one artifact this gate can dirty that a filename sweep cannot reach (P5/S4a).

    Every other throwaway write lands at a PATH containing TMP_SEASON or TMP_LEAGUE, so the rglob
    above finds it. `connected_catalog.parquet` is a single shared file — the throwaway is a ROW
    inside it, and its name matches nothing. A row left behind is worse than a stray file, too: it
    joins `build_db._catalog()`, so `_slices()` grows a league that does not exist and the next
    `--load` fails on it. Purge by value, and delete the file only if it was left with nothing in it
    (i.e. this gate created it).
    """
    path = data_layer._connected_catalog_path()
    if not path.exists():
        return 0
    df = pl.read_parquet(path)
    keep = df.filter(~((pl.col("league_id").cast(str) == TMP_LEAGUE)
                       | (pl.col("season") == TMP_SEASON)))
    if keep.height == df.height:
        return 0
    if keep.height == 0:
        path.unlink()
    else:
        keep.write_parquet(path)
    return df.height - keep.height


def _dummy_args(fn) -> list:
    """Positional stand-ins for a writer's required parameters.

    The guard is the first statement in every writer it protects, so these values are never read —
    which is the point: if a writer touches its arguments before refusing, this raises the wrong
    exception type and the leg fails loudly instead of passing by accident.
    """
    args = []
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.KEYWORD_ONLY, p.VAR_KEYWORD, p.VAR_POSITIONAL) or p.default is not p.empty:
            continue
        args.append(pl.DataFrame() if name == "df" else TMP_SEASON)
    return args


# --- leg 1 + 2: refuses the laptop's artifacts, permits the worker's -------------------------

# The band is excluded from the generic sweep and gets leg 3 instead: it VERIFIES rather than
# refusing, and it resolves a scoring key before the check, so a dummy season would raise the wrong
# error here for the right reason.
_VERIFY_NOT_REFUSE = {"write_ros_player_band"}

# ⚠ UNSCOPED WRITERS — these take only `df`. There is no season, league or id argument, so there is
# no throwaway path to aim them at: their target IS the real, only copy.
#
# That is safe in the REFUSAL leg, where the guard fires before any write. It is NOT safe under
# `--prove-bites`, which deliberately neuters the guard and lets the writers really run. The first
# version of this gate did drive them, and overwrote the frozen 271-league corpus manifest, its
# discovery table and its two-way flags with an empty frame. Nothing recovered them: the corpus
# tree is gitignored and has no backup.
#
# The three that survived that run did so by accident, not design — `write_leagues`,
# `write_demo_manifest` and `write_synthetic_catalog` raise ColumnNotFoundError on an empty frame
# because they `.select(...)` a fixed schema first, and the ledger appenders are saved by their
# dedup key. Accident is not a safeguard, so the rule here is by SHAPE, not by which ones happened
# to survive: if a writer cannot be aimed somewhere throwaway, the destructive leg does not drive it.
_UNSCOPED = {"write_corpus_discovery", "write_corpus_manifest", "write_corpus_two_way_flags",
             "write_leagues", "write_demo_manifest", "write_synthetic_catalog",
             "write_tune_proposals", "write_center_gap"}


def check_refuses(*, destructive_ok: bool = True) -> None:
    label = "" if destructive_ok else "  (unscoped writers skipped — see _UNSCOPED)"
    print(f"\nSTORE_ROLE=worker — the laptop's artifacts are refused{label}")
    with _Role("worker"):
        for name in data_layer.LAPTOP_OWNED_WRITERS:
            if name in _VERIFY_NOT_REFUSE:
                continue
            if not destructive_ok and name in _UNSCOPED:
                continue
            fn = getattr(data_layer, name, None)
            if fn is None:
                _fail(f"{name} is in LAPTOP_OWNED_WRITERS but does not exist on data_layer")
                continue
            try:
                fn(*_dummy_args(fn))
            except data_layer.StoreBoundaryError as e:
                msg = str(e)
                if "Remedy:" in msg and name in msg:
                    _ok(f"{name} refused, and the message names itself and a remedy")
                else:
                    _fail(f"{name} raised but the message is not actionable: {msg[:90]}")
            except Exception as e:   # noqa: BLE001 — any other error means the guard did not fire first
                _fail(f"{name} raised {type(e).__name__}, not StoreBoundaryError: {str(e)[:90]}")
            else:
                _fail(f"{name} WROTE under STORE_ROLE=worker — the boundary does not hold")


def check_permits() -> None:
    """The other half. A guard that refuses everything is not a boundary, it is an outage."""
    print("\nSTORE_ROLE=worker — the worker's own artifacts still write")
    df = pl.DataFrame({"league_id": [TMP_LEAGUE], "season": [TMP_SEASON], "roster_id": [1],
                       "as_of_week": [1], "player_id": ["x"], "vor": [1.5]})
    path = data_layer._league_dir(TMP_LEAGUE) / f"production_vor_{TMP_SEASON}.parquet"
    try:
        with _Role("worker"):
            data_layer.write_production_vor(df, TMP_SEASON, league_id=TMP_LEAGUE)
        if path.exists() and pl.read_parquet(path).height == 1:
            _ok("write_production_vor (derived/league) succeeds and reads back — the worker can work")
        else:
            _fail("write_production_vor produced no readable file under STORE_ROLE=worker")
    except Exception as e:   # noqa: BLE001
        _fail(f"write_production_vor raised under STORE_ROLE=worker: {type(e).__name__}: {e}")
    finally:
        path.unlink(missing_ok=True)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()

    _check_permits_connected_catalog()


def _check_permits_connected_catalog() -> None:
    """P5/S4a's twelfth destination — the ONE catalog a worker may write, and the append shape is why.

    This case is structurally different from every other one in this file and the difference is the
    hazard. Every other throwaway write lands at a path CONTAINING `TMP_SEASON`/`TMP_LEAGUE`, so
    `_sweep()` finds it by name. `connected_catalog.parquet` is a SINGLE SHARED FILE whose name
    contains neither — the throwaway is a *row*, not a file. Left behind, that row flows into
    `build_db._catalog()` → `_slices()`, and the next `--load` would try to load a league that does
    not exist. So this restores the file's exact BYTES (or its absence), and `_sweep` purges the row
    as a second line of defence.

    It also asserts what the append shape is FOR: a pre-existing row must survive the throwaway
    write untouched. A whole-file writer would pass "the worker can write" and still be wrong.
    """
    path = data_layer._connected_catalog_path()
    before = path.read_bytes() if path.exists() else None
    row = data_layer.read_demo_manifest().head(1).with_columns(
        league_id=pl.lit(TMP_LEAGUE), season=pl.lit(TMP_SEASON, dtype=pl.Int64),
        lineage_id=pl.lit(TMP_LEAGUE), is_mine=pl.lit(False))
    try:
        with _Role("worker"):
            data_layer.write_connected_league(row, TMP_LEAGUE, TMP_SEASON)
        back = data_layer.read_connected_catalog()
        mine = back.filter(pl.col("league_id") == TMP_LEAGUE)
        if mine.height == 1:
            _ok("write_connected_league (the connected catalog) succeeds under STORE_ROLE=worker")
        else:
            _fail(f"write_connected_league wrote {mine.height} rows for the throwaway league, expected 1")

        # Idempotency, which is the property that earns a worker the pen at all.
        with _Role("worker"):
            data_layer.write_connected_league(row, TMP_LEAGUE, TMP_SEASON)
        again = data_layer.read_connected_catalog()
        if data_layer.rows_equal(back.to_dicts(), again.to_dicts()):
            _ok("re-writing the same (league_id, season) is a no-op — no duplicate, no reorder")
        else:
            _fail("re-writing the same (league_id, season) CHANGED the catalog — the writer is not idempotent")

        # The append shape: pre-existing rows must be byte-untouched.
        if before is not None:
            kept = again.filter(pl.col("league_id") != TMP_LEAGUE)
            if data_layer.rows_equal(kept.to_dicts(), _rows_from_bytes(before)):
                _ok("every OTHER connected row survived the write untouched — the append shape holds")
            else:
                _fail("the append writer disturbed rows it does not own")
        else:
            _ok("connected catalog did not exist before — created with exactly the one row")
    except Exception as e:   # noqa: BLE001
        _fail(f"write_connected_league raised under STORE_ROLE=worker: {type(e).__name__}: {e}")
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)


def _rows_from_bytes(blob: bytes) -> list[dict]:
    """The rows a parquet blob held, without leaving a file behind."""
    import io
    return pl.read_parquet(io.BytesIO(blob)).to_dicts()


# --- leg 3: the band verifies, in all three outcomes ------------------------------------------

def check_band() -> None:
    print("\nSTORE_ROLE=worker — the band VERIFIES rather than refusing (its three outcomes)")
    key = "ppr"
    path = data_layer._ros_player_band_path(TMP_SEASON, key)
    band = pl.DataFrame({"as_of_week": [1, 1], "player_id": ["a", "b"],
                         "ros_center": [10.0, 20.0], "ros_sigma": [1.0, 2.0]})
    try:
        # Author it as the laptop first — that is the only machine allowed to.
        with _Role(None):
            data_layer.write_ros_player_band(band, TMP_SEASON, scoring_key=key)
        if not path.exists():
            _fail("could not stage a band as the laptop — the rest of this leg cannot run")
            return

        # (a) identical → returns quietly AND does not touch the file. Row order is reversed and
        #     columns reordered, which does double duty: it proves the comparison is VALUE-equality
        #     rather than byte- or layout-equality, AND it makes "verified" distinguishable from
        #     "wrote" — a plain "did not raise" assertion passes even with no guard at all, which is
        #     exactly what --prove-bites caught the first time this gate was written.
        shuffled = band.reverse().select(["ros_sigma", "player_id", "ros_center", "as_of_week"])
        before = path.read_bytes()
        try:
            with _Role("worker"):
                data_layer.write_ros_player_band(shuffled, TMP_SEASON, scoring_key=key)
            if path.read_bytes() == before:
                _ok("identical band (rows reversed, columns reordered) → verified, file untouched")
            else:
                _fail("identical band did not raise, but the file CHANGED — it wrote instead of "
                      "verifying, so the worker is authoring the shared substrate")
        except data_layer.StoreBoundaryError as e:
            _fail(f"identical band raised — value-equality is not holding: {str(e)[:120]}")

        # (b) different → raises. One number moved: the smallest real staleness.
        stale = band.with_columns((pl.col("ros_center") + 0.5).alias("ros_center"))
        try:
            with _Role("worker"):
                data_layer.write_ros_player_band(stale, TMP_SEASON, scoring_key=key)
            _fail("a CHANGED band did not raise — the worker would silently use a stale substrate")
        except data_layer.StoreBoundaryError as e:
            if "STALE" in str(e) and "Remedy:" in str(e):
                _ok("changed band → raises, names the staleness and the operator step")
            else:
                _fail(f"changed band raised, but not actionably: {str(e)[:120]}")

        # (c) missing → raises. This is the un-seeded volume.
        path.unlink(missing_ok=True)
        try:
            with _Role("worker"):
                data_layer.write_ros_player_band(band, TMP_SEASON, scoring_key=key)
            _fail("a MISSING band did not raise — an un-seeded volume would author its own")
        except data_layer.StoreBoundaryError as e:
            if "MISSING" in str(e):
                _ok("missing band → raises (the un-seeded volume case)")
            else:
                _fail(f"missing band raised the wrong message: {str(e)[:120]}")
    finally:
        path.unlink(missing_ok=True)


# --- leg 5: the catalog-drift guard, which points the OTHER way (P5/S4b) -----------------------

def _line_of(fn, call: str, *, literal: str | None = None) -> int | None:
    """Line of the first CALL to `call` in `fn` (optionally: whose arguments contain `literal`).

    Matching a CALL, not text, and it took two goes to get here — both failures are the same
    mistake, so the rule is worth stating: **prose that describes a statement is not the statement.**

      1. A raw substring search over `inspect.getsource` matched the COMMENT above the guard
         (`# BEFORE the TRUNCATE`) and the DOCSTRING (`It TRUNCATEs league_catalog…`), and reported
         correctly-placed code as broken. Comments are absent from the AST entirely; the docstring
         is dropped explicitly below.
      2. Matching any string CONSTANT then matched `reload_manifest`'s *existing* STORE_ROLE error
         message, which also says "TRUNCATEs" — and that message sits ABOVE the guard, so the
         assertion still fired. Hence `literal` now refines a call rather than standing alone:
         the thing that does the damage is `cur.execute('TRUNCATE …')`, not the sentence about it.
    """
    fdef = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    body = fdef.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    hits: list[int] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            if (getattr(node.func, "id", None) or getattr(node.func, "attr", None)) != call:
                continue
            if literal is None or any(literal in ast.unparse(a) for a in node.args):
                hits.append(node.lineno)
    return min(hits) if hits else None

def check_catalog_drift(*, only_refusals: bool = False) -> None:
    """`build_db.assert_catalog_covers_postgres` — both halves, without a database.

    Leg 1 stops a stale WORKER publishing over the laptop. This is the mirror: after P5/S4a the
    worker authors `connected_catalog.parquet` and the LAPTOP does not have it, so the laptop is the
    machine with the stale catalog (measured 2026-08-14: local 32 rows, production 33).

    `pg_ids` is injected, so this runs on any checkout with no accounts, no secrets and no live
    database — the `check_onboard` standard. The live half (the real 33-vs-32) is a read-only SELECT
    and belongs in the session report, the way `check_signup` reports its live half.

    `only_refusals=True` is for --prove-bites, and both exclusions are deliberate. The PERMITS
    assertions pass against a neutered guard *by definition* — a no-op never raises — and the wiring
    assertions read the SOURCE, which still names the call. Re-running either in that leg would
    report the gate as weak for a reason that has nothing to do with whether it bites.
    """
    print("\ncatalog drift — a store that is missing connected leagues may not rewrite the catalog")
    local = {str(v) for v in build_db._catalog()["league_id"].to_list()}

    # (a) REFUSES. One id Postgres knows and this store does not — the real 33-vs-32 in miniature.
    try:
        build_db.assert_catalog_covers_postgres(pg_ids=local | {TMP_LEAGUE})
        _fail("a league_catalog holding an unknown league did NOT raise — a laptop --load would "
              "silently delete every connected league")
    except data_layer.StoreBoundaryError as e:
        msg = str(e)
        checks = {"names the orphaned league": TMP_LEAGUE in msg,
                  "names trap 1 (--emit && --load IS the failure)": "TRAP 1" in msg,
                  "names trap 2 (VERIFY FAILED is already explained away)": "TRAP 2" in msg,
                  "gives a runnable remedy": "Remedy:" in msg}
        for label, held in checks.items():
            _ok(f"refuses, and {label}") if held else _fail(f"refuses, but never {label}: {msg[:90]}")

    if only_refusals:
        return

    # (b) PERMITS — the half a refusal-only test would miss entirely. A guard that refused every
    #     load would pass (a) and make the catalog unmaintainable on any machine.
    try:
        build_db.assert_catalog_covers_postgres(pg_ids=set(local))
        _ok(f"permits when the sets agree ({len(local)} ids) — the guard is not a blanket refusal")
    except data_layer.StoreBoundaryError as e:
        _fail(f"refused an IDENTICAL catalog — nothing could ever be loaded again: {str(e)[:90]}")

    # (c) PERMITS a Postgres that knows FEWER leagues. That direction is a load which ADDS rows, not
    #     a clobber, and it is the normal state after onboarding a league locally.
    try:
        build_db.assert_catalog_covers_postgres(pg_ids=set(sorted(local)[:1]))
        _ok("permits when Postgres knows FEWER leagues — that direction adds rows, it does not clobber")
    except data_layer.StoreBoundaryError as e:
        _fail(f"refused a subset — a first load into an empty database would be impossible: {str(e)[:90]}")

    # (d) WIRED IN, and wired in BEFORE the destructive statement. A perfect guard nothing calls is
    #     the failure mode this whole file exists to catch, one level up.
    for fn, harm_call, harm_lit, what in (
            (build_db.load, "_run_sql_script", None, "the DROP TABLE ... CASCADE"),
            (build_db.reload_manifest, "execute", "TRUNCATE", "the TRUNCATE")):
        call_at = _line_of(fn, "assert_catalog_covers_postgres")
        harm_at = _line_of(fn, harm_call, literal=harm_lit)
        if call_at is None:
            _fail(f"{fn.__name__} never calls the guard — it is unreachable from the CLI")
        elif harm_at is None:
            _fail(f"{fn.__name__}: could not locate {what} — this assertion has stopped measuring")
        elif call_at < harm_at:
            _ok(f"{fn.__name__} calls the guard before {what} (line {call_at} < {harm_at})")
        else:
            _fail(f"{fn.__name__} calls the guard AFTER {what} — the damage is already done")


# --- leg 4: off by default — the parity leg ----------------------------------------------------

def check_off() -> None:
    print("\nSTORE_ROLE unset (the laptop default) — nothing changes")
    if data_layer.store_role() != "laptop":
        _fail(f"default store_role() is {data_layer.store_role()!r}, not 'laptop'")
        return
    _ok("store_role() defaults to 'laptop' — a machine must OPT IN to being a worker")

    with _Role(None):
        staged = []
        try:
            for name, writer, args, kwargs in (
                ("write_predictions", data_layer.write_predictions,
                 (pl.DataFrame({"prediction_id": ["p1"], "v": [1]}), TMP_SEASON), {}),
                ("write_ros_player_band", data_layer.write_ros_player_band,
                 (pl.DataFrame({"as_of_week": [1], "ros_center": [1.0]}), TMP_SEASON),
                 {"scoring_key": "ppr"}),
            ):
                writer(*args, **kwargs)
                staged.append(name)
            if len(staged) == 2:
                _ok("laptop-owned writers still write with the flag off (predictions + band)")
            else:
                _fail(f"only {staged} wrote with the flag off")
        except Exception as e:   # noqa: BLE001
            _fail(f"a laptop-owned writer raised with the flag OFF: {type(e).__name__}: {e}")
        finally:
            data_layer._predictions_path(TMP_SEASON).unlink(missing_ok=True)
            data_layer._ros_player_band_path(TMP_SEASON, "ppr").unlink(missing_ok=True)


# --- prove it bites ----------------------------------------------------------------------------

def prove_bites() -> bool:
    """Neuter the guard and re-run leg 1 — every refusal must turn into a failure.

    Without this the suite could pass because the writers happen to raise for some unrelated reason.

    **This leg really writes.** With the guard neutered the writers do what they were built to do,
    so it drives only the writers that can be aimed at a throwaway path (`destructive_ok=False`
    skips `_UNSCOPED`). Thirteen writers prove the point conclusively; the three that cannot be
    aimed anywhere safe are not worth the frozen corpus.
    """
    print("\nprove-it-bites — the SAME assertions with the guard neutered")
    saved_require, saved_role = data_layer._require_laptop, data_layer.store_role
    data_layer._require_laptop = lambda *a, **k: None
    data_layer.store_role = lambda: "laptop"          # the band's verify path goes with it
    before = len(_results)
    saved_drift = build_db.assert_catalog_covers_postgres
    build_db.assert_catalog_covers_postgres = lambda *a, **k: None
    try:
        check_refuses(destructive_ok=False)
        check_band()
        # wiring=False: those assertions read the SOURCE, which still names the call, so they would
        # pass against the neutered guard and report the gate as weak for the wrong reason.
        check_catalog_drift(only_refusals=True)
    finally:
        data_layer._require_laptop, data_layer.store_role = saved_require, saved_role
        build_db.assert_catalog_covers_postgres = saved_drift
    leg = _results[before:]
    del _results[before:]
    failed = leg.count(False)
    if failed and not any(leg):
        print(f"  ✓ the unguarded code fails all {failed} of these assertions, as it must")
        return True
    print(f"  ✗ the unguarded code still passed {leg.count(True)} assertion(s) — the gate is weak")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate the P5/S3 store boundary.")
    ap.add_argument("--prove-bites", action="store_true",
                    help="also run the assertions against a neutered guard")
    args = ap.parse_args()

    print(f"=== store boundary — {len(data_layer.LAPTOP_OWNED_WRITERS)} laptop-owned writers ===")
    try:
        check_refuses()
        check_permits()
        check_band()
        check_catalog_drift()
        check_off()
        bites = prove_bites() if args.prove_bites else True
    finally:
        swept = _sweep()
        print(f"\nswept {swept} throwaway artifact(s) from the shared store")
    ok = all(_results) and bites
    print(f"\n{'ALL GREEN' if ok else 'FAILED'} — {_results.count(True)}/{len(_results)} assertions"
          + (" — the laptop authors the shared substrate, the worker reads it, and with the flag off "
             "nothing moves." if ok else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
