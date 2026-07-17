"""tuner.py — the L4 Tuner (Improvement-Loop Session 6): the first thing that re-fits a constant, honestly.

The one split-aware sweep harness. Given a `Tunable` from the dials registry (`transforms/_constants.py`)
it sweeps the dial's grid, **fits on TRAIN (2020–2023), certifies on a HELD-OUT season (DEV 2024), and
seals TEST (2025)** — then writes a *proposal*, never a code change. Auto-tune, human promotes.

Why the split is the whole point: a constant that only helps on the data it was fit to is overfit and must
not ship. So the fit code is handed a `SplitReader` that RAISES on any read of a sealed season/stratum —
peeking is not gated after the fact, it is *unrepresentable* (acceptance gate 2). A fit that reaches for
2025, or certifies on TRAIN instead of the holdout, fails a gate.

What it reads:
  * the FROZEN backtests' `objective(season, consts, *, reader)` — the per-read fit objective (the same
    answer-key metric the read's verdict uses; the harness just drives it on a split). One uniform driver
    resolves the callable from `Tunable.gate` via importlib — no bespoke per-constant path (gate 3).
  * the corpus manifest (`stratum` / `never_tune`) — the league-wise seal.
  * (Session 6b, guardrails) the frozen L3 scorecard + `inputs_ok` — for aiming, entanglement evidence,
    and the fit-window integrity guardrail. The scorecard is never re-scored at a candidate (it is frozen).

What it writes: `proposals/{asof}-{constant}.md` + a machine row (see the proposal artifact, added with the
guardrails) — nothing else. It edits no transform and promotes nothing.

Two holdout axes exist in the corpus; ONE binds this session. Season-wise (TRAIN/DEV/TEST) is the operative
out-of-sample test for all five Session-6 dials. League-wise (hold out the 48 `never_tune` generalization
leagues) is built and prove-bitten here but N/A-by-construction for these five — their objectives don't fit
a per-league value — and becomes load-bearing from Session 7's genuinely league-scoped reads.

Run: python3 -m application.data.corpus.tuner
"""
import argparse
import importlib

from application.data import data_layer
from application.data.transforms import _constants

# The season split (STATUS 2026-07-16 is authoritative: TRAIN 2020–23 · DEV 2024 · TEST 2025).
TRAIN_SEASONS = (2020, 2021, 2022, 2023)
DEV_SEASONS = (2024,)
TEST_SEASONS = (2025,)
# The tuning cohort (fit population). The 48 `never_tune` generalization leagues are the league-wise
# holdout — sealed here for every fit/certify so the seal is real (prove-bite below), though N/A for the
# five scoring/nfl/player-level objectives this session.
FIT_STRATA = frozenset({"matched"})


class ForbiddenPartition(RuntimeError):
    """Raised when fit/certify code reaches for a sealed season or stratum. The structural teeth of the
    split: a peeking fit cannot silently succeed — it can only raise."""


class SplitReader:
    """A `data_layer` proxy that guards every `read_*` by season (and, for a league-scoped read, by the
    league's manifest stratum): a read outside the allowed partition RAISES `ForbiddenPartition`. The
    objective functions take this in place of `data_layer`, so a fit literally cannot see a held-out
    partition. Non-`read_*` attributes pass straight through."""

    def __init__(self, allow_seasons, *, allow_strata=None, manifest=None, base=data_layer, role="fit"):
        self._allow_seasons = frozenset(allow_seasons)
        self._allow_strata = frozenset(allow_strata) if allow_strata is not None else None
        self._base = base
        self._role = role
        self._stratum = {}
        if manifest is not None and allow_strata is not None:
            for r in manifest.select("league_id", "stratum").unique().iter_rows(named=True):
                self._stratum[r["league_id"]] = r["stratum"]

    @staticmethod
    def _season_of(args, kw):
        if "season" in kw:
            return kw["season"]
        for a in args:
            if isinstance(a, int) and 1900 < a < 2100:
                return a
        return None

    def __getattr__(self, name):
        # Only invoked for attributes not found normally; never for the _-prefixed instance state above.
        if name.startswith("_"):
            raise AttributeError(name)
        target = getattr(self._base, name)
        if not name.startswith("read_"):
            return target

        def guarded(*args, **kw):
            season = self._season_of(args, kw)
            if season is not None and season not in self._allow_seasons:
                raise ForbiddenPartition(
                    f"{self._role}: season {season} is sealed (allowed {sorted(self._allow_seasons)})")
            lid = kw.get("league_id")
            if lid is not None and self._allow_strata is not None:
                st = self._stratum.get(lid)
                if st is not None and st not in self._allow_strata:
                    raise ForbiddenPartition(
                        f"{self._role}: league {lid} (stratum {st!r}) is sealed "
                        f"(allowed strata {sorted(self._allow_strata)})")
            return target(*args, **kw)

        return guarded


def objective_fn(tunable):
    """Resolve the read's fit objective `objective(season, consts, *, reader)` from `Tunable.gate` — the
    single dispatch that makes one driver re-fit ANY dial (no per-constant branch, gate 3)."""
    mod = importlib.import_module(f"application.data.transforms.{tunable.gate}")
    return mod.objective


def manifest():
    return data_layer.read_corpus_manifest()


def _reader(seasons, mani, role):
    return SplitReader(seasons, allow_strata=FIT_STRATA, manifest=mani, role=role)


def _score_over(fn, seasons, consts, reader):
    """Mean objective over the seasons the objective is COMPUTABLE on (LOWER is better for every dial).
    A season whose objective can't be built (e.g. the is_mine-scoped ROS band pre-2024) is an absent fit
    point, not a zero — returns (mean|None, n_seasons_computed). A `ForbiddenPartition` is a harness bug
    (the reader was asked for a season it should allow) and is left to propagate."""
    vals = []
    for s in seasons:
        try:
            vals.append(fn(s, consts, reader=reader))
        except (FileNotFoundError, ValueError):
            continue
    return (sum(vals) / len(vals) if vals else None), len(vals)


def fit_on_train(tunable, mani):
    """Sweep the dial's grid on TRAIN (matched cohort only, structurally). Returns a list of
    {value, train_metric, n_seasons} — train_metric is None where the objective was not computable."""
    fn = objective_fn(tunable)
    reader = _reader(TRAIN_SEASONS, mani, "fit")
    out = []
    for val in tunable.grid:
        metric, n = _score_over(fn, TRAIN_SEASONS, {tunable.name: val}, reader)
        out.append({"value": val, "train_metric": metric, "n_seasons": n})
    return out


def certify(tunable, value, mani, seasons=DEV_SEASONS, role="certify"):
    """Evaluate one candidate value on a HELD-OUT partition (DEV 2024 by default). Returns
    (metric|None, n_seasons). Reuses the same objective — only the allowed partition differs."""
    fn = objective_fn(tunable)
    reader = _reader(seasons, mani, role)
    return _score_over(fn, seasons, {tunable.name: value}, reader)


def best_of(train_scored):
    """The grid value with the lowest computable TRAIN metric (None if the objective had no TRAIN window)."""
    computable = [r for r in train_scored if r["train_metric"] is not None]
    if not computable:
        return None
    return min(computable, key=lambda r: r["train_metric"])


# --- Structural-split prove-bites (used by check_tuner; runnable standalone) ------------------------

def prove_test_sealed(tunable=None):
    """A fit that reaches for TEST 2025 through the FIT reader must RAISE. Returns True iff it bites."""
    tunable = tunable or _constants.REGISTRY["OPP_HALF_LIFE_WK"]
    fn = objective_fn(tunable)
    reader = _reader(TRAIN_SEASONS, manifest(), "fit")
    try:
        fn(TEST_SEASONS[0], {tunable.name: tunable.current}, reader=reader)
        return False
    except ForbiddenPartition:
        return True


def prove_generalization_sealed():
    """A fit that reaches for a `never_tune` generalization league must RAISE. Returns True iff it bites.
    Uses a league-scoped read (production_vor) with a real generalization league_id from the manifest."""
    mani = manifest()
    import polars as pl
    gen = mani.filter((pl.col("stratum") != "matched") & (pl.col("season").is_in(TRAIN_SEASONS)))
    if gen.height == 0:
        return False
    lid = gen["league_id"][0]
    season = int(gen["season"][0])
    reader = _reader(TRAIN_SEASONS, mani, "fit")
    try:
        reader.read_production_vor(season, league_id=lid, as_of_week="all")
        return False
    except ForbiddenPartition:
        return True


def prove_certify_not_train():
    """The certify reader must seal TRAIN: certifying a candidate on a TRAIN season (peeking at the fit
    data as if it were holdout) must RAISE. Guards guardrail (a)'s 'holdout, not train' honesty."""
    tunable = _constants.REGISTRY["OPP_HALF_LIFE_WK"]
    fn = objective_fn(tunable)
    dev_reader = _reader(DEV_SEASONS, manifest(), "certify")
    try:
        fn(TRAIN_SEASONS[0], {tunable.name: tunable.current}, reader=dev_reader)
        return False
    except ForbiddenPartition:
        return True


def _print_sweep(tunable, mani):
    """C1 smoke view: the TRAIN sweep + the DEV certification of TRAIN's pick and of the current value."""
    scored = fit_on_train(tunable, mani)
    best = best_of(scored)
    print(f"\n=== sweep {tunable.name} ({tunable.module}) — objective: {tunable.objective} — LOWER better ===")
    print(f"  {'value':>10}{'TRAIN metric':>16}{'n_seasons':>11}")
    for r in scored:
        mark = " ←train-best" if best and r["value"] == best["value"] else ""
        m = "  n/a (no train window)" if r["train_metric"] is None else f"{r['train_metric']:>16.4f}"
        print(f"  {str(r['value']):>10}{m}{r['n_seasons']:>11}{mark}")
    if best is None:
        print("  → no TRAIN window: objective not computable on 2020–2023 (e.g. is_mine-scoped) — HOLD.")
        return
    cur = tunable.current
    best_dev, ndev = certify(tunable, best["value"], mani)
    cur_dev, _ = certify(tunable, cur, mani)
    print(f"  current = {cur!r} (train {dict((r['value'], r['train_metric']) for r in scored).get(cur)})")
    print(f"  TRAIN-best = {best['value']!r}")
    print(f"  DEV 2024 certify (n={ndev}):  current -> {cur_dev}   train-best -> {best_dev}")


def main():
    ap = argparse.ArgumentParser(description="L4 Tuner — split-aware constant sweep (Session 6).")
    ap.add_argument("--tunable", default=None, help="one dial by name (default: all registered dials)")
    a = ap.parse_args()
    mani = manifest()
    dials = ([_constants.REGISTRY[a.tunable]] if a.tunable else list(_constants.tunables()))
    print("split-bite self-check:",
          f"test-sealed={prove_test_sealed()}",
          f"generalization-sealed={prove_generalization_sealed()}",
          f"certify-not-train={prove_certify_not_train()}")
    for t in dials:
        _print_sweep(t, mani)


if __name__ == "__main__":
    main()
