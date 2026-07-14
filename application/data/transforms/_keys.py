"""Scope keys for the data layer — the Improvement-Loop L0 keying primitives.

Pure, leaf module: the single home for `scoring_key` / `shape_key`, so both `transforms/` and the
`corpus/` package import them without a `transforms`<->`corpus` cycle (`corpus/_corpus.py` re-exports
these, so the crawl/selection/gate keep importing them from `_corpus` unchanged). The profile-from-
settings convenience lazily borrows `_scoring.scoring_profile`, so importing this module stays free of
polars — `_corpus` can keep its "no I/O, no polars at import" property.

    scoring_key(profile, settings)      "ppr" | "half" | "std" | "cust-<8char>"  (profile already known)
    scoring_key_from_settings(scoring)  same, classifying the profile from a raw Sleeper scoring dict
    shape_key(num_teams, qb, format)    a compact roster-shape signature, e.g. "12t-1qb-redraft"
"""
import hashlib
import json


def scoring_key(scoring_profile: str, scoring_settings: dict | None) -> str:
    """`ppr`/`half`/`std` for canned profiles; `cust-<8-char hash of the normalised scoring dict>` for
    custom — so two identically-scored custom leagues share one key (keeps AI cost flat as L0 wires it)."""
    if scoring_profile in ("ppr", "half", "std"):
        return scoring_profile
    norm = json.dumps(scoring_settings or {}, sort_keys=True, separators=(",", ":"))
    return "cust-" + hashlib.sha1(norm.encode()).hexdigest()[:8]


def scoring_key_from_settings(scoring: dict) -> str:
    """`scoring_key` straight from a raw Sleeper `scoring_settings` dict (classifies the profile first).
    The convenience the registry builder / compute_projection_consensus reach for."""
    from application.data.transforms._scoring import scoring_profile  # lazy: keep this module polars-free
    return scoring_key(scoring_profile(scoring), scoring)


def shape_key(num_teams, qb_structure: str, league_format: str) -> str:
    """A compact roster-shape signature, e.g. `12t-1qb-redraft`."""
    n = f"{int(num_teams)}t" if num_teams is not None else "NAt"
    return f"{n}-{qb_structure}-{league_format}"
