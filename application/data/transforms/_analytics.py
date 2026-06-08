"""Shared pure helpers for the derived-analytics transforms.

Small, dependency-free numeric utilities used by more than one transform, so each
rule (rounding, central tendency, league-relative spectrum normalisation) has a
single home rather than being copy-pasted per transform. These are pure functions —
no I/O, no config globals — so they compose into any transform and test in isolation.
"""


def round1(n: float) -> float:
    return round(n, 1)


def mean(xs) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def median(xs) -> float:
    """Median of a numeric list (avg of the two middle values when even)."""
    s = sorted(xs)
    m = len(s)
    if not m:
        return 0.0
    return s[(m - 1) // 2] if m % 2 else (s[m // 2 - 1] + s[m // 2]) / 2


def spectrum_positions(values):
    """League-relative 0–1 position for each value, in input order (min→0, max→1).

    A flat field (zero span) collapses everyone to the 0.5 midpoint. Mirrors the
    front-end attachSpectrumPos, so a marker reads "where this team sits in the
    league" rather than against an abstract threshold. The normalisation rule lives
    here once; transforms call it rather than re-deriving min/max/span inline.
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    return [(v - lo) / span if span else 0.5 for v in values]
