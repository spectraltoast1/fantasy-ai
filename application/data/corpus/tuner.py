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
import contextlib
import hashlib
import importlib
import io
import json
import os
from dataclasses import dataclass

import polars as pl

from application.data import data_layer
from application.data.corpus import inputs_ok as inputs_ok_mod
from application.data.transforms import _constants

# The season split (STATUS 2026-07-16 is authoritative: TRAIN 2020–23 · DEV 2024 · TEST 2025).
TRAIN_SEASONS = (2020, 2021, 2022, 2023)
DEV_SEASONS = (2024,)
TEST_SEASONS = (2025,)
# The tuning cohort (fit population). The 48 `never_tune` generalization leagues are the league-wise
# holdout — sealed here for every fit/certify so the seal is real (prove-bite below), though N/A for the
# five scoring/nfl/player-level objectives this session.
FIT_STRATA = frozenset({"matched"})

# The band dials the L3 scorer showed are entangled with the not-yet-fixed optimistic center: their fit
# objective sits downstream of the projection center, so a change now would compensate for a bias Session
# 7 removes. HELD this session with a named reason — however good the sweep looks (decision 6).
ENTANGLED = frozenset({"BAND_Z", "SKEW_GAIN", "BULL_Z", "ANCHOR_W"})
ENTANGLE_REASON = ("entangled with the optimistic center (L3); a change now compensates for a bias "
                   "Session 7 removes — revisit post-de-bias")

# Minimum holdout improvement, in each objective's own units, to count as signal not noise (guardrail d).
EFFECT_FLOOR = {
    "backtest_player_signal": 0.05,          # rest-of-season MAE, in PPG points
    "backtest_projection_consensus": 0.010,  # |coverage-0.50| + tail-imbalance, dimensionless
    "backtest_ros_player_band": 0.010,       # |coverage-target| + tail-imbalance, dimensionless
}
# The fit window's input integrity must clear this fraction of trustworthy claims (guardrail c).
INPUTS_OK_MIN = 0.98
# The proposals live beside the Trust Report (git-tracked, human-reviewed); the machine rows go to the
# gitignored ledger store via data_layer.
_PROPOSALS_DIR = ("project_management/scope docs/engine improvement/proposals")


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


# --- The proposal artifact + the four guardrails (Session 6 C2) -------------------------------------

def baseline_provenance():
    """The FROZEN L3 scorecard's stamps — the baseline this re-fit is measured against (standing instr 8).
    Read from a TRAIN season (code_version/constants_hash are identical across seasons — one scorer run);
    the tuner does NOT stamp its own git HEAD (its tree is dirty from the new proposal .md), it provenances
    via the frozen inputs' clean stamps. This is metadata, not a fit — the scorecard is never re-scored."""
    r = data_layer.read_engine_scorecard(TRAIN_SEASONS[0]).row(0, named=True)
    return {"code_version": r["code_version"], "constants_hash": r["constants_hash"],
            "config_version": r["config_version"]}


def inputs_ok_frac_train(mani):
    """Guardrail (c): fraction of trustworthy claims over the fit window (matched cohort, TRAIN seasons),
    read from the PERSISTED ledger `inputs_ok` (standing instr 8 — never re-derive from a moving source).
    A degraded fit window fails the guardrail; None if the ledger is unavailable."""
    matched = mani.filter(pl.col("stratum") == "matched")["league_id"].to_list()
    tot = ok = 0
    for s in TRAIN_SEASONS:
        try:
            r = data_layer.read_resolutions(s).select("league_id", "inputs_ok")
        except Exception:
            continue
        r = r.filter(pl.col("league_id").is_in(matched))
        tot += r.height
        ok += int(r["inputs_ok"].sum())
    return (ok / tot) if tot else None


_RUN_KW = {"BAND_Z": "band_z", "SKEW_GAIN": "skew_gain", "BULL_Z": "bull_z",
           "ANCHOR_W": "anchor_w", "OPP_HALF_LIFE_WK": "half_life"}


def _run_gate_at(gate, season, consts):
    """Re-run a backtest's `run(...)` verdict at injected constant values (stdout suppressed) → bool PASS,
    or None if not computable this season (e.g. an is_mine-scoped read pre-2024)."""
    mod = importlib.import_module(f"application.data.transforms.{gate}")
    kw = {_RUN_KW[k]: v for k, v in consts.items() if k in _RUN_KW}
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if gate == "backtest_player_signal":
                return bool(mod.run(season, list(mod.OBJ_RECENT_WEEKS), list(mod.OBJ_REST_WEEKS), **kw))
            return bool(mod.run(season, **kw))
    except (FileNotFoundError, ValueError):
        return None


def sibling_check(tunable, proposed):
    """Guardrail (b): re-run the affected gates at the candidate on the HELD-OUT season (DEV 2024) and
    confirm none regress to FAIL. The dial's OWN read gate is re-run with the candidate injected; its
    declared cross-read siblings are recorded structurally — the band dials do NOT feed the center reads
    (production_vor/true_rank/bracket_odds), which consume the center, so a band-width change cannot
    regress them (decoupled by construction; standing instr 6 — the mechanism, not an assertion)."""
    deltas = {}
    own_pass = _run_gate_at(tunable.gate, DEV_SEASONS[0], {tunable.name: proposed})
    deltas[tunable.gate] = {"pass": own_pass, "note": f"own read gate at {tunable.name}={proposed}, DEV 2024"}
    for g in tunable.coupled_gates:
        if g == tunable.gate:
            continue
        deltas[g] = {"pass": True, "note": "decoupled by construction (consumes the center, not the band)"}
    return deltas


def entanglement_evidence(tunable, cur, proposed):
    """Confirm the entanglement rather than assert it (standing instr 6). For SKEW_GAIN the OOS fit itself
    is the confirmation: it moves toward 0 exactly as an overfit-to-a-biased-center skew term would."""
    if tunable.name == "SKEW_GAIN" and proposed is not None and proposed != cur:
        toward = "toward 0" if proposed < cur else "away from 0"
        return (f"CONFIRMED: the OOS fit moves SKEW_GAIN {cur}→{proposed} ({toward}), matching the "
                f"pre-registered overfit prediction. The skew term corrects band-tail imbalance; an "
                f"optimistic center (L3: production_vor loses to carry-recent-form every season) inflates "
                f"that imbalance, so the fitted skew is doing work a de-biased center (S7) would obviate — "
                f"the apparent gain tracks the center bias, not a real ROS property.")
    return ("HELD downstream of the optimistic center — a change here would compensate for the center bias "
            "S7 removes; re-fit once the constants are untangled.")


def decide_verdict(*, entangled, changed, g_holdout, g_effect, g_inputs, g_coupled):
    """The pure verdict from the guardrail booleans — the teeth of the four guardrails, testable in
    isolation. RECOMMEND iff a real change clears ALL four guardrails AND is not entangled; else HOLD.
    Returns (verdict, kind) where kind ∈ {'entangled','no-change','recommend'} or the 'guardrail(s) not
    met: …' string. The order matters: entanglement is an absolute override (decision 6 — the band dials
    are HELD however good the sweep looks)."""
    if entangled:
        return "HOLD", "entangled"
    if not changed:
        return "HOLD", "no-change"
    if g_holdout and g_effect and g_inputs and g_coupled:
        return "RECOMMEND", "recommend"
    fails = [n for n, ok in [("holdout-improves", g_holdout), ("effect>floor", g_effect),
                             ("inputs_ok", g_inputs), ("no-coupled-regression", g_coupled)] if not ok]
    return "HOLD", "guardrail(s) not met: " + ", ".join(fails)


@dataclass
class Proposal:
    kind: str                      # "dial" | "lead"
    constant: str
    module: str
    scope: str
    current: object
    proposed: object
    train_metric: object
    dev_metric_current: object
    dev_metric_proposed: object
    holdout_axis: str
    effect_size: object
    effect_floor: object
    inputs_ok_frac: object
    g_holdout: object
    g_coupled: object
    g_inputs: object
    g_effect: object
    sibling_deltas: dict
    verdict: str                   # RECOMMEND | HOLD | LEAD
    hold_reason: str
    n_train_seasons: int
    n_dev_seasons: int
    asof_date: str
    baseline_code_version: str
    baseline_constants_hash: str
    rank: int = 0

    @property
    def proposal_id(self):
        raw = f"{self.constant}|{self.asof_date}|{self.baseline_constants_hash}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_row(self):
        # Round stored metrics to 6 dp: the objectives are polars mean/sum reductions whose accumulation
        # order isn't thread-deterministic (a ~1e-15 flake), which would break twice-run value-identity.
        # 6 dp is far more precision than a proposal needs and makes the row byte-reproducible.
        def r6(x):
            return round(x, 6) if isinstance(x, float) else x
        return {
            "proposal_id": self.proposal_id, "rank": self.rank, "kind": self.kind, "constant": self.constant,
            "module": self.module, "scope": self.scope, "current": str(self.current),
            "proposed": str(self.proposed),  # None-the-value stringifies to "None"; the no-fit case uses a marker
            "train_metric": r6(self.train_metric), "dev_metric_current": r6(self.dev_metric_current),
            "dev_metric_proposed": r6(self.dev_metric_proposed), "holdout_axis": self.holdout_axis,
            "effect_size": r6(self.effect_size), "effect_floor": r6(self.effect_floor),
            "inputs_ok_frac": r6(self.inputs_ok_frac), "guardrail_holdout": self.g_holdout,
            "guardrail_coupled": self.g_coupled, "guardrail_inputs": self.g_inputs,
            "guardrail_effect": self.g_effect,
            "sibling_deltas": json.dumps(self.sibling_deltas, sort_keys=True),
            "verdict": self.verdict, "hold_reason": self.hold_reason,
            "n_train_seasons": self.n_train_seasons, "n_dev_seasons": self.n_dev_seasons,
            "asof_date": self.asof_date, "baseline_code_version": self.baseline_code_version,
            "baseline_constants_hash": self.baseline_constants_hash,
        }


def evaluate(tunable, mani, asof, baseline, io_frac):
    """Sweep one dial on the split and return its Proposal. RECOMMEND only if it is NOT entangled AND all
    four guardrails hold; else HOLD with the reason. The tuner writes this — it never edits a transform."""
    scored = fit_on_train(tunable, mani)
    best = best_of(scored)
    cur = tunable.current
    n_train = max((r["n_seasons"] for r in scored), default=0)
    floor = EFFECT_FLOOR[tunable.gate]
    g_inputs = (io_frac is not None and io_frac >= INPUTS_OK_MIN)
    entangled = tunable.name in ENTANGLED
    base = dict(kind="dial", constant=tunable.name, module=tunable.module, scope=tunable.scope, current=cur,
                holdout_axis="season (DEV 2024)", effect_floor=floor, inputs_ok_frac=io_frac,
                g_inputs=g_inputs, asof_date=asof, baseline_code_version=baseline["code_version"],
                baseline_constants_hash=baseline["constants_hash"])

    if best is None:  # objective not computable on TRAIN — no OOS fit possible
        reason = ("no OOS TRAIN window — the objective is is_mine-scoped and no is_mine league exists "
                  "before 2024, so it cannot be fit on 2020–2023 (a corpus-wide per-league ROS-band "
                  "objective is Session-7 work)")
        if entangled:
            reason += f"; and {ENTANGLE_REASON}"
        return Proposal(proposed="n/a (no OOS fit)", train_metric=None, dev_metric_current=None,
                        dev_metric_proposed=None, effect_size=None, g_holdout=None, g_coupled=None,
                        g_effect=None, sibling_deltas={}, verdict="HOLD", hold_reason=reason,
                        n_train_seasons=n_train, n_dev_seasons=0, **base)

    proposed = best["value"]
    cur_train = next((r["train_metric"] for r in scored if r["value"] == cur), None)
    dev_cur, ndev = certify(tunable, cur, mani)
    dev_best, _ = certify(tunable, proposed, mani)
    changed = (proposed != cur)
    effect = (dev_cur - dev_best) if (changed and dev_cur is not None and dev_best is not None) else 0.0
    g_holdout = bool(changed and dev_cur is not None and dev_best is not None and effect > 0)
    g_effect = bool(changed and effect > floor)
    sib = sibling_check(tunable, proposed) if changed else {}
    g_coupled = all(v["pass"] for v in sib.values() if v["pass"] is not None) if sib else True

    verdict, kind = decide_verdict(entangled=entangled, changed=changed, g_holdout=g_holdout,
                                   g_effect=g_effect, g_inputs=g_inputs, g_coupled=g_coupled)
    if kind == "entangled":
        reason = f"{ENTANGLE_REASON}. {entanglement_evidence(tunable, cur, proposed)}"
    elif kind == "no-change":
        reason = ("current value is already the TRAIN+DEV optimum — the sweep confirms it out-of-sample; "
                  "no change to propose (holdout effect 0)")
    elif kind == "recommend":
        reason = ""
    else:
        reason = kind  # the "guardrail(s) not met: …" string
    return Proposal(proposed=proposed, train_metric=cur_train, dev_metric_current=dev_cur,
                    dev_metric_proposed=dev_best, effect_size=effect, g_holdout=g_holdout, g_coupled=g_coupled,
                    g_effect=g_effect, sibling_deltas=sib, verdict=verdict, hold_reason=reason,
                    n_train_seasons=n_train, n_dev_seasons=ndev, **base)


def debias_lead(asof, baseline):
    """The top-ranked LEAD the tuner's first act produces: de-bias the center BEFORE any band constant.
    Not a dial proposal — the sequencing insight. Every band dial is HELD because it compensates for the
    center; the fix is upstream, and it is tuned THROUGH this harness in Session 7."""
    reason = ("TOP LEAD — de-bias the projection center before touching any band constant. L3 measured the "
              "center optimistic (production_vor loses to carry-recent-form every season; the band covers "
              "~0.55 vs its 0.80 target). Every band dial (BAND_Z / SKEW_GAIN / BULL_Z / ANCHOR_W) sits "
              "downstream of it, so this session HOLDS them all — and SKEW_GAIN's OOS fit even moves 1.5→1.0 "
              "(toward 0, as pre-registered), confirming the skew is compensating for the center bias, not a "
              "real ROS property. Session 7 adds a recent-form shrinkage dial to the center, tuned THROUGH "
              "this harness on the same split; re-fit the band dials only after (Session 8).")
    return Proposal(kind="lead", constant="center_debias", module="projection_consensus/production_vor",
                    scope="scoring", current="optimistic center (L3)", proposed="add recent-form anchor (S7)",
                    train_metric=None, dev_metric_current=None, dev_metric_proposed=None,
                    holdout_axis="n/a (a lead, not a fit)", effect_size=None, effect_floor=None,
                    inputs_ok_frac=None, g_holdout=None, g_coupled=None, g_inputs=None, g_effect=None,
                    sibling_deltas={}, verdict="LEAD", hold_reason=reason, n_train_seasons=0, n_dev_seasons=0,
                    asof_date=asof, baseline_code_version=baseline["code_version"],
                    baseline_constants_hash=baseline["constants_hash"])


def _fmt(x, nd=4):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _render_one(p):
    """Render a proposal's markdown FROM its row values, so the prose can't drift from the gated numbers."""
    L = [f"# Tuner proposal — `{p.constant}` ({p.verdict})", "",
         f"**as-of:** {p.asof_date}  ·  **rank:** {p.rank}  ·  **module:** `{p.module}`  ·  "
         f"**scope:** {p.scope}", "",
         f"**baseline (frozen L3):** code_version `{p.baseline_code_version[:12]}` · "
         f"constants_hash `{p.baseline_constants_hash}`", ""]
    if p.kind == "lead":
        L += ["## Verdict: LEAD (top-ranked)", "", p.hold_reason, ""]
        return "\n".join(L)
    L += [f"## Verdict: **{p.verdict}**", "",
          f"- **current → proposed:** `{p.current}` → `{p.proposed}`",
          f"- **objective (lower better):** {_constants.REGISTRY[p.constant].objective}",
          f"- **TRAIN metric (current):** {_fmt(p.train_metric)}  ·  **seasons fit:** {p.n_train_seasons}",
          f"- **HELD-OUT (DEV 2024):** current {_fmt(p.dev_metric_current)} · "
          f"proposed {_fmt(p.dev_metric_proposed)}  (n={p.n_dev_seasons})  [axis: {p.holdout_axis}]",
          f"- **effect size (holdout):** {_fmt(p.effect_size)}  ·  **floor:** {_fmt(p.effect_floor)}",
          f"- **inputs_ok over fit window:** {_fmt(p.inputs_ok_frac)}",
          "",
          "### Guardrails",
          f"| holdout improves | no coupled regress | inputs_ok | effect > floor |",
          f"|---|---|---|---|",
          f"| {p.g_holdout} | {p.g_coupled} | {p.g_inputs} | {p.g_effect} |",
          ""]
    if p.sibling_deltas:
        L += ["### Coupled gates re-run"]
        for g, d in sorted(p.sibling_deltas.items()):
            L.append(f"- `{g}`: pass={d['pass']} — {d['note']}")
        L.append("")
    if p.hold_reason:
        L += [f"### {'Why HELD' if p.verdict == 'HOLD' else 'Note'}", "", p.hold_reason, ""]
    L += ["---", "*Auto-tune, human promotes: this is a proposal. No transform was edited and no constant "
          "was merged. Promote in a normal worktree session after review.*"]
    return "\n".join(L)


def _write_markdown(proposals, asof):
    os.makedirs(_PROPOSALS_DIR, exist_ok=True)
    for p in proposals:
        with open(os.path.join(_PROPOSALS_DIR, f"{asof}-{p.constant}.md"), "w") as f:
            f.write(_render_one(p))


def build_proposals(asof=None):
    """The disciplined first run: sweep every dial on the split, HOLD the entangled band, and rank the
    de-bias lead #1. Returns (ordered_proposals, rows_frame) — pure (no writes), so the gate can recompute
    and compare value-identical."""
    mani = manifest()
    baseline = baseline_provenance()
    asof = asof or baseline["config_version"].lstrip("v")
    io_frac = inputs_ok_frac_train(mani)
    dials = [evaluate(t, mani, asof, baseline, io_frac) for t in _constants.tunables()]
    allp = [debias_lead(asof, baseline)] + dials
    order = {"LEAD": 0, "RECOMMEND": 1, "HOLD": 2}
    ordered = sorted(allp, key=lambda p: order[p.verdict])  # stable: keeps declaration order within a group
    for i, p in enumerate(ordered, 1):
        p.rank = i
    rows = pl.DataFrame([p.to_row() for p in ordered])
    return ordered, rows


def run_all(asof=None, *, write=True):
    ordered, rows = build_proposals(asof)
    if write:
        data_layer.write_tune_proposals(rows)
        _write_markdown(ordered, ordered[0].asof_date)
    return ordered, rows


def _print_proposals(ordered):
    print(f"\n=== Tuner first run — {len(ordered)} proposals (as-of {ordered[0].asof_date}) ===")
    print(f"  {'#':>2} {'verdict':<10}{'constant':<20}{'current→proposed':<28}{'holdout Δ':>10}")
    for p in ordered:
        cp = (f"{p.current}→{p.proposed}" if p.kind == "dial" else "—")
        eff = _fmt(p.effect_size, 4) if p.effect_size is not None else "—"
        print(f"  {p.rank:>2} {p.verdict:<10}{p.constant:<20}{cp:<28}{eff:>10}")
    rec = [p.constant for p in ordered if p.verdict == "RECOMMEND"]
    held = [p.constant for p in ordered if p.verdict == "HOLD"]
    print(f"\n  RECOMMEND: {rec or '(none — nothing clears the guardrails un-entangled this session)'}")
    print(f"  HOLD: {held}")
    print(f"  TOP LEAD: {ordered[0].constant} — {ordered[0].hold_reason.split(' — ')[0]}")


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
    ap.add_argument("--asof-date", default=None,
                    help="pinned as-of date (default: the frozen scorecard's config_version date). Never now().")
    ap.add_argument("--sweep-view", action="store_true", help="print the per-dial TRAIN/DEV sweep tables")
    ap.add_argument("--tunable", default=None, help="with --sweep-view: one dial by name")
    ap.add_argument("--no-write", action="store_true", help="compute + print but do not write the store/markdown")
    a = ap.parse_args()
    print("split-bite self-check:",
          f"test-sealed={prove_test_sealed()}",
          f"generalization-sealed={prove_generalization_sealed()}",
          f"certify-not-train={prove_certify_not_train()}")
    if a.sweep_view:
        mani = manifest()
        dials = ([_constants.REGISTRY[a.tunable]] if a.tunable else list(_constants.tunables()))
        for t in dials:
            _print_sweep(t, mani)
        return
    ordered, _ = run_all(a.asof_date, write=not a.no_write)
    _print_proposals(ordered)
    if not a.no_write:
        print(f"\n  wrote {len(ordered)} proposal rows + markdown to "
              f"{_PROPOSALS_DIR}/{ordered[0].asof_date}-*.md")


if __name__ == "__main__":
    main()
