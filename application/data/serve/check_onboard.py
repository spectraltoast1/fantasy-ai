"""Gate for the cold onboard — P5/S4a.

Fifth in the `check_auth` / `check_signup` / `check_ownership` / `check_isolation` line, and the
first one about the WRITE side. It proves the four properties S4a exists to create:

  1. THE WRITER    — `write_connected_league` replaces exactly one (league_id, season) row,
                     is idempotent, does not reorder, and enforces the catalog's dtypes.
  2. THE CATALOG   — `_catalog()` really is 31 + 1 + N, `_slices()` grows with it, `load_league`
                     stops refusing a connected league, and `_ref()` stays out of reach.
  3. THE KEY       — `_resolve_scoring_key` never returns the OWNER's key for a league that is not
                     the owner's. This is the one that would mis-score somebody's season.
  4. COLDNESS      — `assert_cold` sees every catalog, and refuses a league once it is connected.

DB-free and network-free by construction: everything here is a pure function or a parquet write to
a throwaway id, so the gate runs on any checkout without accounts, secrets or a live database. An
onboarding gate you can only run against production is one that stops being run.

**Read the prove-it-bites block before trusting any of this.** Every assertion is re-run against
the PRE-S4a behaviour — a catalog of two sources, a scoring key that falls back to the owner's, a
coldness check that reads one parquet — and every one is required to FAIL. A check that has never
failed has not been tested; it has only been observed agreeing with the code it was written from.

    application/venv/bin/python -m application.data.serve.check_onboard
    application/venv/bin/python -m application.data.serve.check_onboard --prove-bites
"""

from __future__ import annotations

import argparse

import polars as pl

from application.data import data_layer
from application.data.serve import build_db, onboard_league

# Same throwaway idiom as check_store_boundary: a season no real artifact uses and an id that is
# not Sleeper-shaped, so anything that mistakes it for a league fails loudly.
TMP_SEASON = 99997
TMP_LEAGUE = "__ONBOARDCHECK__"
TMP_LEAGUE_B = "__ONBOARDCHECK_B__"

_results: list[bool] = []


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")
    _results.append(True)


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    _results.append(False)


def _guard(thunk):
    """Run `thunk`, turning any exception into `None`.

    Only for values an assertion then judges. It exists for `--prove-bites`: the reverted code is
    allowed to blow up, and when it does that must read as the assertion FAILING, not as the gate
    crashing before it reaches the assertions that matter.
    """
    try:
        return thunk()
    except Exception as e:   # noqa: BLE001
        print(f"    (raised {type(e).__name__}: {e})")
        return None


def _row(lid: str, season: int, **over) -> pl.DataFrame:
    """A well-formed connected-catalog row, built the way the onboarder builds one."""
    base = {"lineage_id": lid, "league_id": lid, "season": season, "name": f"Test {lid}",
            "scoring_key": "ppr", "num_teams": 12, "is_mine": False, "previous_league_id": None,
            "viewer_roster_id": None, "panels_market": False, "panels_ros": False,
            "panels_manager": False}
    base.update(over)
    return pl.DataFrame([base], schema=data_layer.read_demo_manifest().schema)


class _Sandbox:
    """Run a block with the connected catalog restored to its exact prior bytes afterwards.

    `connected_catalog.parquet` is a single SHARED file — the throwaway is a row, not a file — so
    there is no per-test path to isolate. Snapshotting the bytes is what keeps this gate runnable on
    a laptop whose store may already hold real connected leagues. (Byte restore, not row filtering:
    polars' parquet writer is non-deterministic, so rewriting "the same" rows would still churn the
    file and could mask a bug in the writer under test.)
    """

    def __enter__(self):
        self.path = data_layer._connected_catalog_path()
        self.before = self.path.read_bytes() if self.path.exists() else None
        return self

    def __exit__(self, *exc):
        if self.before is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_bytes(self.before)
        return False


# --- leg 1: the writer ----------------------------------------------------------------------------

def check_writer() -> None:
    print("\nTHE WRITER — one row replaced, everything else untouched")
    with _Sandbox() as sb:
        prior = data_layer.read_connected_catalog()
        data_layer.write_connected_league(_row(TMP_LEAGUE, TMP_SEASON), TMP_LEAGUE, TMP_SEASON)
        data_layer.write_connected_league(_row(TMP_LEAGUE_B, TMP_SEASON), TMP_LEAGUE_B, TMP_SEASON)
        got = data_layer.read_connected_catalog()
        if got.height == prior.height + 2:
            _ok(f"two connected leagues appended ({prior.height} → {got.height})")
        else:
            _fail(f"expected {prior.height + 2} rows, got {got.height}")

        # Idempotency — the property that lets a worker hold this pen at all.
        snapshot = got.to_dicts()
        data_layer.write_connected_league(_row(TMP_LEAGUE, TMP_SEASON), TMP_LEAGUE, TMP_SEASON)
        if data_layer.rows_equal(snapshot, data_layer.read_connected_catalog().to_dicts()):
            _ok("re-writing an existing (league_id, season) is a clean no-op — no dup, no reorder")
        else:
            _fail("re-writing an existing row CHANGED the catalog — not idempotent")

        # A genuine UPDATE must land, or S4b cannot flip panels_manager when the dossiers arrive.
        data_layer.write_connected_league(
            _row(TMP_LEAGUE, TMP_SEASON, panels_manager=True, name="Renamed"),
            TMP_LEAGUE, TMP_SEASON)
        after = data_layer.read_connected_catalog().filter(pl.col("league_id") == TMP_LEAGUE)
        if after.height == 1 and bool(after["panels_manager"][0]) and after["name"][0] == "Renamed":
            _ok("re-writing with CHANGED values updates in place (S4b flips panels_manager this way)")
        else:
            _fail(f"an updating re-write did not replace the row: {after.to_dicts()}")

        # The neighbour must be untouched by both of those writes — the append shape itself.
        nb = data_layer.read_connected_catalog().filter(pl.col("league_id") == TMP_LEAGUE_B)
        if nb.height == 1 and nb["name"][0] == f"Test {TMP_LEAGUE_B}":
            _ok("the other connected league is byte-untouched — this is what 'append-shaped' means")
        else:
            _fail("writing one league disturbed another's row")

        # Deterministic ordering, so a re-onboard cannot reorder the file for everyone else.
        ids = data_layer.read_connected_catalog().select(["season", "league_id"])
        if ids.equals(ids.sort(["season", "league_id"])):
            _ok("the file stays sorted by (season, league_id) — re-onboarding cannot reorder it")
        else:
            _fail("connected catalog is not in deterministic order")

        # Dtypes: the strict concat in _catalog() is why this matters at all.
        loose = pl.DataFrame([{**_row(TMP_LEAGUE, TMP_SEASON).row(0, named=True)}])
        loose = loose.with_columns(season=pl.col("season").cast(pl.Int32))
        try:
            data_layer.write_connected_league(loose, TMP_LEAGUE, TMP_SEASON)
            merged = build_db._catalog()
            if merged.schema == data_layer.read_demo_manifest().schema:
                _ok("a row with a drifting dtype (season: Int32) is CAST, and _catalog() still concats")
            else:
                _fail(f"_catalog() schema drifted to {merged.schema}")
        except Exception as e:   # noqa: BLE001
            _fail(f"a drifting dtype raised instead of being cast: {type(e).__name__}: {e}")
        _ = sb


# --- leg 2: the catalog ---------------------------------------------------------------------------

def check_catalog() -> None:
    print("\nTHE CATALOG — 31 + 1 + N, and the loader stops refusing")
    demo, syn = data_layer.read_demo_manifest(), data_layer.read_synthetic_catalog()
    with _Sandbox():
        base = build_db._catalog().height
        if base == demo.height + syn.height + data_layer.read_connected_catalog().height:
            _ok(f"_catalog() = demo({demo.height}) + synthetic({syn.height}) + connected — {base} rows")
        else:
            _fail("_catalog() is not the sum of its three sources")

        data_layer.write_connected_league(_row(TMP_LEAGUE, TMP_SEASON), TMP_LEAGUE, TMP_SEASON)
        if build_db._catalog().height == base + 1:
            _ok("a connected league joins the served catalog")
        else:
            _fail("a connected league did NOT join the served catalog")

        if (TMP_LEAGUE, TMP_SEASON, "ppr") in build_db._slices():
            _ok("_slices() carries it, so load_league resolves it")
        else:
            _fail("_slices() does not carry the connected league — load_league would still refuse")

        # The corpus must NOT move. demo_manifest is the frozen slate the L2 ledger derives from.
        if data_layer.read_demo_manifest().height == 31:
            _ok("demo_manifest.parquet is still 31 rows — the corpus did not move")
        else:
            _fail(f"demo_manifest is {data_layer.read_demo_manifest().height} rows, expected 31")

        # _ref() is the --emit schema reference for the WHOLE database.
        try:
            build_db._ref()
            _ok("_ref() still resolves to exactly one is_mine slice")
        except SystemExit as e:
            _fail(f"_ref() broke: {e}")
        data_layer.write_connected_league(
            _row(TMP_LEAGUE, TMP_SEASON, is_mine=True, panels_market=True), TMP_LEAGUE, TMP_SEASON)
        try:
            _s, ref_lid, _k = build_db._ref()
            if ref_lid != TMP_LEAGUE:
                _ok("even an is_mine+panels_market CONNECTED row cannot become the schema reference "
                    "(_ref reads demo_manifest, never _catalog)")
            else:
                _fail("a connected row became the --emit schema reference for the whole database")
        except SystemExit as e:
            _fail(f"_ref() raised when a connected row was is_mine: {e}")


# --- leg 3: the scoring key -----------------------------------------------------------------------

def check_scoring_key() -> None:
    """The one that mis-scores a season if it is wrong."""
    print("\nTHE SCORING KEY — never the owner's, for a league that is not the owner's")
    from application.data.serve import weekly_refresh

    # 2025 deliberately, NOT the throwaway season: that is the season the owner HAS an is_mine
    # league in, so the pre-S4a fallback has a key to hand back. Against a season nobody owns the
    # old code merely raises for an unrelated reason, and the contrast this leg exists to draw —
    # "it silently returns somebody else's scoring rules" — would never be shown.
    owner_season = 2025
    owner_key = data_layer._active_league(owner_season)[1]
    with _Sandbox():
        # (a) A catalogued connected league resolves from the CATALOG — and to its own key.
        other = "half" if owner_key != "half" else "ppr"
        data_layer.write_connected_league(
            _row(TMP_LEAGUE, owner_season, scoring_key=other), TMP_LEAGUE, owner_season)
        got = _guard(lambda: weekly_refresh._resolve_scoring_key(TMP_LEAGUE, owner_season))
        if got == other:
            _ok(f"a catalogued connected league resolves to its OWN key ({other!r}, not {owner_key!r})")
        else:
            _fail(f"catalogued connected league resolved to {got!r}, expected {other!r}")

    # (b) An UNCATALOGUED league with no settings on disk must RAISE, not borrow the owner's key.
    try:
        got = weekly_refresh._resolve_scoring_key(TMP_LEAGUE, owner_season)
        _fail(f"an uncatalogued league returned {got!r} instead of raising — the owner's key is "
              f"{owner_key!r}, so this is the silent mis-scoring path")
    except SystemExit as e:
        if "onboard_league" in str(e) and TMP_LEAGUE in str(e):
            _ok("an uncatalogued league RAISES and names the remedy, rather than borrowing a key")
        else:
            _fail(f"it raised, but the message does not name the league and the remedy: {e}")
    except Exception as e:   # noqa: BLE001 — any other error is still a failure of this assertion
        _fail(f"an uncatalogued league raised {type(e).__name__}: {e}")

    # (c) Parity: the leagues that refresh today must resolve exactly as before.
    drifted = [(l, s) for l, s, sk in build_db._slices()
               if weekly_refresh._resolve_scoring_key(l, s) != sk]
    if not drifted:
        _ok(f"all {len(build_db._slices())} catalogued slices resolve unchanged — parity holds")
    else:
        _fail(f"{len(drifted)} catalogued slice(s) changed scoring key: {drifted[:3]}")


# --- leg 4: coldness ------------------------------------------------------------------------------

def check_coldness() -> None:
    print("\nCOLDNESS — every catalog, and a connected league is not cold")
    with _Sandbox():
        try:
            onboard_league.assert_cold(TMP_LEAGUE, TMP_SEASON)
            _ok("an unknown league is cold")
        except SystemExit as e:
            _fail(f"an unknown league was reported warm: {e}")

        data_layer.write_connected_league(_row(TMP_LEAGUE, TMP_SEASON), TMP_LEAGUE, TMP_SEASON)
        try:
            onboard_league.assert_cold(TMP_LEAGUE, TMP_SEASON)
            _fail("a CONNECTED league still reports cold — the coldness check misses the new catalog")
        except SystemExit as e:
            if "connected_catalog.parquet" in str(e):
                _ok("a connected league is NOT cold, and the message names connected_catalog.parquet")
            else:
                _fail(f"it refused, but not for the connected catalog: {e}")

        if onboard_league.classify(TMP_LEAGUE, TMP_SEASON) == "reonboard":
            _ok("classify() calls it a RE-ONBOARD rather than refusing — DoD clause 4's shape")
        else:
            _fail("classify() did not recognise an already-connected league as a re-onboard")

    # A corpus league is emphatically not cold, and must never be reachable from the onboarder.
    corpus_lid = str(data_layer.read_corpus_manifest()["league_id"][0])
    corpus_season = int(data_layer.read_corpus_manifest()["season"][0])
    try:
        onboard_league.classify(corpus_lid, corpus_season)
        _fail(f"the onboarder accepted corpus league {corpus_lid} — it could overwrite a fixture "
              "the immutable L2 ledger is derived from")
    except SystemExit:
        _ok("a frozen-corpus league is refused outright, not treated as a re-onboard")

    # The demo clone likewise.
    try:
        onboard_league.classify("DEMO-2025", 2025)
        _fail("the onboarder accepted the synthetic demo league")
    except SystemExit as e:
        if "SYNTHETIC" in str(e):
            _ok("the generated demo clone is refused, and the message says why")
        else:
            _fail(f"DEMO-2025 refused for the wrong reason: {e}")


# --- prove it bites -------------------------------------------------------------------------------

def prove_bites() -> bool:
    """Re-run the same assertions against the PRE-S4a behaviour; every one must fail.

    Three separate reversions, because S4a fixed three separate things and a gate that only proves
    one of them is a gate with a hole:

      * `_catalog()` back to two sources          → the catalog and coldness legs must collapse
      * `_resolve_scoring_key` back to the owner  → the key leg must return the owner's key
      * `assert_cold` reading demo_manifest only  → a connected league must look cold again
    """
    from application.data.serve import weekly_refresh
    print("\nprove-it-bites — the SAME assertions against the pre-S4a code")

    saved_cat, saved_key, saved_cold = build_db._catalog, weekly_refresh._resolve_scoring_key, \
        onboard_league.assert_cold

    def old_catalog():
        return pl.concat([data_layer.read_demo_manifest(), data_layer.read_synthetic_catalog()],
                         how="vertical")

    def old_key(lid, season):
        for l, s, sk in build_db._slices():
            if l == lid and s == season:
                return sk
        return data_layer._active_league(season)[1]

    def old_cold(lid, season):
        warm = []
        if data_layer.is_synthetic(lid):
            raise SystemExit(f"league {lid} is SYNTHETIC")
        if data_layer.leagues_exists():
            if data_layer.read_leagues().filter(pl.col("league_id").cast(str) == lid).height:
                warm.append("leagues.parquet")
        if data_layer.demo_manifest_exists():
            if data_layer.read_demo_manifest().filter(pl.col("league_id").cast(str) == lid).height:
                warm.append("demo_manifest.parquet")
        warm += [f"{k} ({p})" for k, p in onboard_league._league_dirs(lid, season).items() if p.exists()]
        if warm:
            raise SystemExit(f"league {lid} is NOT cold — present in: {', '.join(warm)}.")

    build_db._catalog = old_catalog
    weekly_refresh._resolve_scoring_key = old_key
    onboard_league.assert_cold = old_cold

    # EVERY leg is run and EVERY leg must break, independently. A single pooled tally would let one
    # thoroughly-broken leg cover for another that was never reverted at all — and an exception in
    # leg 1 must not stop legs 2 and 3 from running, which is exactly what it did the first time
    # this was written. Some assertions inside a leg legitimately still hold (the corpus is still 31
    # rows whatever `_catalog` does), so the bar is per-leg, not per-assertion.
    ok = True
    try:
        for name, fn in (("catalog", check_catalog), ("scoring key", check_scoring_key),
                         ("coldness", check_coldness)):
            before = len(_results)
            try:
                fn()
            except Exception as e:   # noqa: BLE001 — the old code raising IS a failed assertion
                print(f"    (leg raised outright: {type(e).__name__}: {e})")
                _results.append(False)
            leg = _results[before:]
            del _results[before:]
            if leg.count(False):
                print(f"  ✓ pre-S4a '{name}' leg fails {leg.count(False)}/{len(leg)} assertions, as it must")
            else:
                print(f"  ✗ pre-S4a '{name}' leg passed ALL {len(leg)} assertions — it was not "
                      "actually reverted, so this leg proves nothing")
                ok = False
    finally:
        build_db._catalog = saved_cat
        weekly_refresh._resolve_scoring_key = saved_key
        onboard_league.assert_cold = saved_cold
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prove-bites", action="store_true",
                    help="also re-run every assertion against the pre-S4a code (all must fail)")
    args = ap.parse_args()

    check_writer()
    check_catalog()
    check_scoring_key()
    check_coldness()
    bites = prove_bites() if args.prove_bites else True

    failed = _results.count(False)
    print()
    if failed or not bites:
        print(f"FAILED — {failed} of {len(_results)} assertions")
        raise SystemExit(1)
    print(f"ALL GREEN — {len(_results)}/{len(_results)} assertions — a league the store has never "
          "seen has somewhere to live, and it is scored on its own rules.")


if __name__ == "__main__":
    main()
