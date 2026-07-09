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


def pearson(xs, ys) -> float | None:
    """Pearson correlation coefficient between two equal-length series.

    Returns None (not 0.0) when undefined — fewer than 2 points, or either series has
    zero variance — so callers can distinguish "no signal" from "measured, no
    correlation," which matters for a sample-gated read (design law 2).
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0.0 or dy == 0.0:
        return None
    return num / (dx * dy)


def stdev(xs) -> float | None:
    """Population standard deviation of a numeric series.

    Returns None (not 0.0) when undefined — fewer than 2 points — mirroring pearson's
    convention, so a caller can distinguish "no spread estimate" (fall back to a prior)
    from "measured, zero spread." Population form (divide by n, not n−1): the thin
    per-player samples this feeds get pooled with a positional prior anyway, so the more
    stable /n estimate is the right choice over the less-biased-but-noisier /(n−1).
    """
    n = len(xs)
    if n < 2:
        return None
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / n) ** 0.5


def skewness(xs) -> float | None:
    """Population skewness (third standardised moment) of a numeric series.

    Returns None (not 0.0) when undefined — fewer than 3 points (a third moment needs
    at least three), or zero spread — mirroring stdev's convention so a caller can fall
    back to a prior rather than treating "no estimate" as "measured, symmetric." Same
    population form (divide by n) as stdev: the per-player residual samples this feeds
    are thin and get pooled with a positional prior, so the stable /n estimate beats a
    less-biased-but-noisier bias-corrected one. Positive = long right tail.
    """
    n = len(xs)
    if n < 3:
        return None
    m = mean(xs)
    s = (sum((x - m) ** 2 for x in xs) / n) ** 0.5
    if s == 0.0:
        return None
    return sum(((x - m) / s) ** 3 for x in xs) / n


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
