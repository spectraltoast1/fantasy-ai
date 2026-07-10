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


def quantile(xs, q: float) -> float | None:
    """The q-th quantile (q ∈ [0,1]) of a numeric series by linear interpolation between order
    statistics — the same rule numpy's default uses. Returns None for an empty series (mirroring
    mean/stdev's "undefined, not 0.0" convention) so a caller can fall back rather than treat an
    empty bin as a real 0. Used to fit the ADP rank→realized-points floor/center/ceiling (P10/P50/P90).
    """
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    pos = q * (len(s) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 < len(s):
        return s[lo] + frac * (s[lo + 1] - s[lo])
    return float(s[lo])


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


def expand_slots(slot_rows):
    """One entry per physical starting slot (a FLEX count of 2 → two slots), most-constrained
    first so dedicated slots claim their position's stars before flex slots draw from the pool.

    `slot_rows` are the lineup_slots dicts (slot, count, eligible-CSV). Pure and points-agnostic:
    the shared optimal-lineup engine for any per-player value (weekly points in leakage, ROS
    value in true rank). Lifted here so the greedy rule has one home across transforms.
    """
    slots = []
    for s in slot_rows:
        eligible = str(s["eligible"]).split(",")
        for _ in range(int(s["count"])):
            slots.append({"slot": s["slot"], "eligible": eligible})
    slots.sort(key=lambda s: len(s["eligible"]))
    return slots


def optimal_lineup(players, slots):
    """Greedy optimal lineup: fill the most-constrained slots first with the top-`pts` eligible
    player still available. Each player carries a stable `_i` so usage is tracked across slots;
    `pts` is whatever value is being maximised (realized points, ROS value…). Returns the total
    and the chosen picks (each tagged with its filled slot) so callers can score and diff.
    """
    used = set()
    picks = []
    total = 0.0
    for slot in slots:
        candidates = [
            p for p in players if p["_i"] not in used and p["position"] in slot["eligible"]
        ]
        if not candidates:
            continue
        pick = max(candidates, key=lambda p: p["pts"])
        total += pick["pts"]
        used.add(pick["_i"])
        picks.append({**pick, "slot": slot["slot"]})
    return {"total": total, "picks": picks}


def position_pools(slot_rows):
    """position → pool key, derived from the league's declared lineup slots (not hard-coded).

    Positions that can occupy a common **multi-position** starting slot (FLEX, SUPER_FLEX, …) share
    one pool; a position that only ever fills dedicated single-position slots is its own pool. This is
    the swap-eligibility / replacement-pool structure, used by Production VOR (one waiver line per
    pool) and lineup-leakage (legal swap classes) so both generalize to any lineup shape instead of
    hard-coding QB-vs-FLEX. Examples: standard 1QB → {QB:'QB', RB/WR/TE:'FLEX'}; superflex →
    {QB/RB/WR/TE:'SUPER_FLEX'}; 2QB (two dedicated QB slots, no superflex) → {QB:'QB', ...}.

    Pool key = the name of the **broadest** multi-position slot inducing the pool (so the label is
    meaningful, e.g. 'SUPER_FLEX'); a singleton pool is keyed by its position. `slot_rows` are the raw
    lineup_slots dicts (slot, count, eligible-CSV). Pure. NB: for the standard config this reproduces
    the old QB/'FLEX' partition **and labels** exactly, so consumers see byte-identical output.
    """
    positions = []
    for s in slot_rows:
        for p in str(s["eligible"]).split(","):
            if p and p not in positions:
                positions.append(p)

    parent = {p: p for p in positions}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    multi = []  # (slot_name, eligible-list) for every multi-position slot
    for s in slot_rows:
        elig = [p for p in str(s["eligible"]).split(",") if p]
        if len(elig) > 1:
            multi.append((s["slot"], elig))
            for p in elig[1:]:
                parent[find(p)] = find(elig[0])

    # Name each merged component after the broadest slot touching it (ascending sort → widest wins).
    comp_name = {}
    for slot_name, elig in sorted(multi, key=lambda t: (len(t[1]), str(t[0]))):
        comp_name[find(elig[0])] = slot_name

    return {p: comp_name.get(find(p), p) for p in positions}


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
