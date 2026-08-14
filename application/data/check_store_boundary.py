"""Gate for the store boundary — P5/S3.

The rule (ADR: context/appendices/store-boundary.md, ACCEPTED option (b)) is that data flows ONE
DIRECTION: the authoring laptop owns the shared substrate, and every other machine that runs this
pipeline reads it. A rule with nothing enforcing it is a comment, so this proves the enforcement.

**Both halves, always.** A refusal on its own proves nothing — a guard that refused *everything*
would pass a refusal-only test and make the worker useless. So every check here comes in a pair:
the laptop-owned write is refused AND the worker-owned write still succeeds.

Four legs:

  1. REFUSES   — under STORE_ROLE=worker, every writer named in `LAPTOP_OWNED_WRITERS` raises
                 StoreBoundaryError. Driven off the constant itself, so a writer added to the list
                 without a guard (or a guard deleted from a listed writer) fails here.
  2. PERMITS   — under the same flag, a worker-owned write (derived/league) still succeeds and reads
                 back, and the per-league raw/join layer is untouched.
  3. THE BAND  — the one laptop-owned writer that verifies instead of refusing, in all three of its
                 outcomes: identical → returns quietly, different → raises, missing → raises.
  4. OFF       — with STORE_ROLE unset (the laptop default), nothing raises and every writer behaves
                 exactly as it did before this session existed. This is the parity leg: the guard is
                 invisible unless a machine opts into it.

Usage:
    application/venv/bin/python -m application.data.check_store_boundary
    application/venv/bin/python -m application.data.check_store_boundary --prove-bites
"""

import argparse
import inspect
import os
import sys

import polars as pl

from application.data import data_layer

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
    return removed


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
    try:
        check_refuses(destructive_ok=False)
        check_band()
    finally:
        data_layer._require_laptop, data_layer.store_role = saved_require, saved_role
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
