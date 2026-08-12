"""Pure calculations ported from the front-end seam (``queries.js`` + the retired ``posture.js``).

Byte-for-byte behavioural mirrors of the JavaScript, so each endpoint returns the same
numbers the browser produces today. No data access — the reads live in ``reads.py``.

``posture.js`` no longer exists — it was deleted with the DuckDB-WASM client, which makes this
module the **single** home of the posture derivation rather than one of two mirrors. The
references to it below are kept only as provenance for the constants.
"""

from __future__ import annotations

import math

# Trade-lean threshold (VOR units) on the Production-Market gap. queries.js l.110.
TRADE_GAP_T = 0.25

# Posture derivation constants (posture.js — DATA_CONTRACT §5, user-tuned 2026-07).
BAND = 9  # pts off the diagonal that counts as lucky/unlucky
LEVEL_CUT = 60  # % contender/rebuild threshold on the diagonal band

# Posture label -> the reserved posture CSS variable (returned verbatim so the chip tints
# identically to the DuckDB path).
POSTURE_TONE = {
    "Contender": "var(--contender)",
    "Unlucky": "var(--unlucky)",
    "On pace": "var(--onpace)",
    "Riding luck": "var(--ridingluck)",
    "Rebuild": "var(--rebuild)",
}

# positional_depth `shape` -> the display chip. queries.js l.435.
SHAPE_LABEL = {"surplus": "SURPLUS", "adequate": "EVEN", "gap": "GAP"}


def derive_posture(playoff_odds_pct: float, all_play_pct: float) -> dict:
    """The posture read for one team. Both inputs 0-100.

    **No callers as of P5/S2e — the read is withheld, not deleted.** ``reads.load_standings``
    stopped serving it because ``gap`` subtracts two quantities that are not the same unit, which
    made the label inverted for every league (the full measurement is in the note at that call
    site). Held here because the session that fixes the metric starts from this function, and
    ``BAND``/``LEVEL_CUT`` must be re-measured on whatever the new scale turns out to be — nine
    points is meaningless against odds and plausible against win%.
    """
    gap = all_play_pct - playoff_odds_pct  # + = performing above standing (buy window)
    level = (playoff_odds_pct + all_play_pct) / 2

    if gap > BAND:
        label = "Unlucky"
    elif gap < -BAND:
        label = "Riding luck"
    elif level >= LEVEL_CUT:
        label = "Contender"
    elif level <= 100 - LEVEL_CUT:
        label = "Rebuild"
    else:
        label = "On pace"

    return {"label": label, "tone": POSTURE_TONE[label]}


def series_read(series: list[float]) -> dict:
    """Summarize a value series -> current value, delta (last - first), direction. l.616."""
    if not series:
        return {"series": [], "value": None, "delta": None, "up": True}
    value = series[-1]
    delta = value - series[0]
    return {"series": series, "value": value, "delta": delta, "up": delta >= 0}


def num(v):
    """`v == null ? null : Number(v)` — coerce to float, preserving null. l.623."""
    return None if v is None else float(v)


def js_round(x: float) -> int:
    """JS ``Math.round(x)`` — round half *up* (toward +inf). NOT Python's ``round()``.

    Used for the standings/team-detail ``avg_seed`` (Math.round). Seeds are positive.
    """
    return math.floor(x + 0.5)


def round1(n: float) -> float:
    """JS ``Math.round(n * 10) / 10`` — round half *up*.

    Deliberately NOT Python's ``round()`` (which is round-half-to-even) so points/week match
    the DuckDB path. Points are non-negative, so ``floor(x + 0.5)`` reproduces Math.round. l.625.
    """
    return math.floor(n * 10 + 0.5) / 10


def format_record(w, l, t=0) -> str:
    """A team's record: ``"W-L"``, or ``"W-L-T"`` once a tie exists. queries.js printed ``"W-L"``.

    The ties term is ADDITIVE: at ``t == 0`` this is byte-identical to what shipped, so every league
    currently served (zero ties across the 31 demo slices) renders exactly as before — the CODING_BIBLE
    §5 parity guard satisfied by construction rather than by inspection. The third segment appears only
    when it carries information.

    One home for the four inline ``f"{w}-{l}"`` copies this replaced, so a tie cannot reach one surface
    and not another.
    """
    return f"{int(w)}-{int(l)}-{int(t)}" if t else f"{int(w)}-{int(l)}"
