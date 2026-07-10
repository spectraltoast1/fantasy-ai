"""
Prompt construction for the Manager Dossiers AI layer (DECISION_READS.md §7 Phase B).

Pure — no I/O, no API calls. Builds the shared, stable system prefix (cache-friendly) and a
per-manager user prompt from the deterministic `manager_features` row. Framing is
tendencies-not-verdicts (laws 2+4), and blindspot for the primary user / exploitable-edge for
opponents. The zero-signal hardcoded dossier (AI skipped) also lives here so all content is one place.
"""

import json

# The fixed dossier schema — the SAME keys for every manager so dossiers read side by side.
DOSSIER_KEYS = ("headline", "waiver_faab", "trade_tendency", "positional_lean",
                "roster_construction", "edge_or_blindspot", "confidence_note")


def system_prompt() -> str:
    """The shared, stable instruction prefix (identical across managers → cache-friendly)."""
    return (
        "You are a fantasy-football scouting analyst writing a short behavioral dossier on a league "
        "manager, from pre-computed statistics about how they manage their teams across their "
        "comparable other leagues.\n\n"
        "Rules:\n"
        "- Describe TENDENCIES, never verdicts or predictions. This manager is a person, not a type — "
        "hedge (\"leans\", \"tends to\", \"has shown\") and never state a certainty the numbers don't "
        "support.\n"
        "- Be qualitative and readable. Reference the numbers as evidence; don't just restate them.\n"
        "- Gate your confidence on the signal depth you're given (leagues / seasons / transactions). "
        "Thin history = explicitly tentative language.\n"
        "- Keep each field to 1-2 sentences.\n"
        "- Output ONLY a JSON object — no prose around it — with EXACTLY these keys, all string "
        f"values: {json.dumps(list(DOSSIER_KEYS))}\n"
        "  - headline: one sentence capturing this manager's style.\n"
        "  - waiver_faab: their waiver / FAAB-bidding tendency.\n"
        "  - trade_tendency: how much they trade and what it implies.\n"
        "  - positional_lean: which positions they chase on the wire.\n"
        "  - roster_construction: churn / activity level and what it implies.\n"
        "  - edge_or_blindspot: framed per the manager instruction below.\n"
        "  - confidence_note: one sentence stating the signal depth (n_leagues / n_seasons / "
        "n_transactions) and how much to trust this read.\n"
    )


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.0f}%"


def _num(v, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def user_prompt(row: dict) -> str:
    """The per-manager user turn: framing + signal depth + the behavioral features as evidence."""
    is_primary = bool(row.get("is_primary"))
    name = row.get("owner_name") or row.get("team_name") or f"roster {row.get('roster_id')}"
    framing = (
        "This is the PRIMARY USER (you). Frame `edge_or_blindspot` as a BLINDSPOT: where these "
        "tendencies could be exploited by opponents — i.e. how the user is exposed."
        if is_primary else
        "This is an OPPONENT. Frame `edge_or_blindspot` as an EXPLOITABLE EDGE: how the primary user "
        "could use these tendencies against them (trade targeting, waiver competition)."
    )
    lines = [
        f"Manager: {name}",
        framing,
        "",
        "Signal depth (how much history this read draws on):",
        f"- comparable leagues: {row.get('n_leagues')}",
        f"- seasons: {row.get('n_seasons')}",
        f"- transactions analyzed: {row.get('n_transactions')}  (depth tier: {row.get('depth_tier')})",
        "",
        "Behavioral features (across comparable leagues):",
        f"- waivers / free-agents / trades: {row.get('n_waivers')} / {row.get('n_free_agents')} / {row.get('n_trades')}",
        f"- waiver share of adds: {_pct(row.get('waiver_share'))}",
        f"- waiver success rate: {_pct(row.get('waiver_success_rate'))}",
        f"- avg / max FAAB bid (fraction of budget): {_pct(row.get('avg_bid_frac'))} / {_pct(row.get('max_bid_frac'))}",
        f"- FAAB budget spent (fraction): {_pct(row.get('budget_spent_frac'))}",
        f"- trades per league-season: {_num(row.get('trades_per_league'))}",
        f"- moves per league-season: {_num(row.get('moves_per_league'))}",
        "- positional lean of adds (QB/RB/WR/TE): "
        f"{_pct(row.get('add_qb_share'))} / {_pct(row.get('add_rb_share'))} / "
        f"{_pct(row.get('add_wr_share'))} / {_pct(row.get('add_te_share'))}",
        "",
        "Write the dossier JSON now.",
    ]
    return "\n".join(lines)


def zero_signal_dossier() -> dict:
    """The hardcoded 'no intel' dossier for a manager with no comparable-league signal.

    The AI is skipped entirely (DECISION_READS §7) — thin history stereotypes people, so a manager
    with zero comparable leagues gets an explicit no-read rather than a fabricated profile. Same
    schema keys so it slots into the same table.
    """
    msg = ("No intel available — no comparable leagues were found for this manager, so no behavioral "
           "read can be made.")
    return {
        "headline": "No intel available.",
        "waiver_faab": msg,
        "trade_tendency": msg,
        "positional_lean": msg,
        "roster_construction": msg,
        "edge_or_blindspot": msg,
        "confidence_note": "Signal depth: 0 comparable leagues / 0 seasons / 0 transactions — no read.",
    }
