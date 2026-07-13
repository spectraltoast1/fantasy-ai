"""
Prompt construction for the ROS Synthesis AI layer (§2 ROS Outcome Shape — the interpretation half).

Pure — no I/O, no API calls. Builds the shared, stable system prefix (cache-friendly) and a
per-player user prompt that fuses TWO inputs the quantitative skeleton (compute_ros_player_band +
compute_ros_league_view) deliberately left un-fused ("the AI narrative + 1-10 grade roll-up is Phase 6"):

  1. the QUANTITATIVE ANCHOR — the player's ROS anchor row (ros_player_band ⋈ ros_league_view: bull/bear
     point band, league-relative caliber, draft capital, security tier + trust axis). Sets the SCALE so grades aren't
     free-floating (DECISION_READS §2 guardrail: "anchor the AI to the structured inputs").
  2. the SITUATION NEWS — the player's inherited player_news_slice claims (scope-tagged, attributed,
     with a signal_tier thinness tripwire). Explains WHERE the range sits and WHICH WAY it breaks.

Output = the three §2 scores as 1-10 grades, EACH with its narrative note (law 4 — the grade is a
summary, not a replacement), consolidated headlines (the receipts, grounded in the cited claims), and
a confidence flag gated on data completeness (law 2 — qualitative + AI is the least-provable read).
Every field is a SEPARATE key (grade / note / headlines / confidence all extractable independently —
the app renders them apart, never as one block).

Grade convention — three 1-10 scores where 10 is always the best reading, but each measures a
DIFFERENT axis, so they are NOT ordered against each other (a safe-but-capped player can score a high
bear and a modest bull; a boom/bust the reverse):
  - bull_grade      — how HIGH the ceiling goes (the upside case). 10 = elite, league-winning upside.
  - bear_grade      — how SAFE the floor is. 10 = a rock-solid, dependable floor; 1 = the floor is
    near nothing (a real bust / irrelevance risk).
  - situation_grade — how SMOOTH the player's situation is. 10 = clean, settled, secure; 1 = messy,
    contested, unstable.

Notes are natural fantasy-manager prose — NO internal jargon or numbers (see the prose rules). The
substrata (a caliber bucket, role read, projection band) drive the GRADES; the manager never sees
them, so the prose translates them into plain language and leans on the (manager-legible) news with
attribution — an `opinion` claim is never laundered into fact.
"""

import json

# The fixed output schema — the SAME keys for every player. Each is independently extractable: three
# integer grades, three prose notes, the headline receipts, and a two-part confidence read.
SYNTHESIS_KEYS = ("bull_grade", "bull_note", "bear_grade", "bear_note",
                  "situation_grade", "situation_note", "headlines", "confidence", "confidence_note")
GRADE_KEYS = ("bull_grade", "bear_grade", "situation_grade")   # the integer 1-10 fields
NOTE_KEYS = ("bull_note", "bear_note", "situation_note", "confidence_note")

GRADE_MIN, GRADE_MAX = 1, 10
CONFIDENCE = ("low", "med", "high")

# Plain-language translations of the internal trust-axis labels, so the model reasons about role
# stability WITHOUT the raw jargon ever reaching (or leaking into) the manager-facing prose.
_SECURITY_PLAIN = {
    "stable": "his role looks locked-in",
    "questionable": "his role has some question marks",
    "depth_chart_risk": "he is facing real competition for his snaps",
    "flagged": "there is a notable risk to his role",
}
_DIRECTION_PLAIN = {
    "rising": "his recent workload had been trending up",
    "steady": "his recent workload had been steady",
    "fading": "his recent workload had been trending down",
}

# The player's league-relative standing at his position, bucketed to a WORD (never a number reaches
# the prompt) — the primary, hard anchor for bull_grade. (from ros_league_view.spectrum_pos, 0-1.)
_STANDING_BUCKETS = (
    (0.90, "elite"),          # -> bull 9-10
    (0.75, "high-end"),       # -> bull 8
    (0.55, "above-average"),  # -> bull 6-7
    (0.40, "middling"),       # -> bull 5
    (0.20, "low-end"),        # -> bull 3-4
    (0.00, "fringe"),         # -> bull 1-2
)


def system_prompt() -> str:
    """The shared, stable instruction prefix (identical across players → cache-friendly)."""
    return (
        "You are a fantasy-football analyst writing a compact REST-OF-SEASON outcome read for ONE "
        "offensive skill player (QB / RB / WR / TE). You are given two things: (1) a QUANTITATIVE "
        "ANCHOR — a projection range, a one-word CALIBER bucket for how he rates among others at his "
        "position, his draft capital, and a plain-language role read; and (2) recent SITUATION NEWS — "
        "attributed, scope-tagged claims distilled from local team coverage. Fuse them into three "
        "1-10 grades, each with a short natural-language note, plus the headlines that back the read.\n\n"
        "THE THREE GRADES — all 1-10 (10 is always best), each on a DIFFERENT axis, so do NOT force "
        "any ordering between them:\n"
        "- bull_grade: how HIGH the ceiling goes — the UPSIDE case, assuming things break right. "
        "Anchor it HARD to the caliber bucket: 'elite' => 9-10; 'high-end' => 8; 'above-average' => "
        "6-7; 'middling' => 5; 'low-end' => 3-4; 'fringe' => 1-2. Use the FULL range — an elite player "
        "scores 9-10, a fringe player 1-2; do NOT cluster everyone at 6-7. Draft capital may nudge it "
        "+/-1. CRITICAL: do NOT let a downward workload trend, competition, an injury, or negative "
        "analysis LOWER the bull — the ceiling is what he can do if it goes RIGHT, and that downside "
        "belongs in bear_grade / situation_grade instead. Only lower the bull if the player has "
        "fundamentally lost his role or opportunity (demoted, buried on the depth chart, likely out). "
        "If NO caliber bucket is given, judge the ceiling from his role + the news + your own "
        "knowledge of the player, and lower confidence.\n"
        "- bear_grade: how SAFE the floor is. 1 = the floor is near nothing — a real risk he busts, "
        "loses the job, or is fantasy-irrelevant; 10 = a rock-solid, dependable floor even in a bad "
        "case. This is where downside lives: role security, consistency, competition, health.\n"
        "- situation_grade: how SMOOTH his situation is. 1 = messy — contested role, injury cloud, "
        "scheme upheaval, unsettled job; 10 = clean, settled, secure. Seed it from the role read, then "
        "let the news raise or lower it (e.g. a 'locked-in' role but broadly negative scheme/"
        "competition news = a bumpier situation than the role read alone).\n"
        "  These three are INDEPENDENT: a steady possession player can be a high bear + modest bull; a "
        "boom/bust deep threat a high bull + low bear. Grade each on its own axis.\n\n"
        "PROSE RULES (critical) — the notes are read by a fantasy manager who CANNOT see any of the "
        "inputs, the grades, or this data. Write plain, descriptive prose about the PLAYER:\n"
        "- NEVER mention or cite any internal input, even paraphrased. BANNED: the caliber bucket "
        "words ('elite/high-end/above-average/middling/low-end/fringe' as a label), any 'standing' / "
        "'percentile' / 'Nth at his position', any 'projection' / 'projected points' / point totals, "
        "'anchor', 'prior-season projection', 'tier', 'trend flag', reliability or confidence scores, "
        "and meta words like 'ceiling grade' / 'floor grade'. (Phrases like 'his 93rd standing' or "
        "'his prior-season projection' are exactly what NOT to write.)\n"
        "- Translate the role read into ordinary language (a locked-in starter; facing competition; "
        "coming off a quieter stretch) — never the raw label. You MAY say a player is elite/talented/"
        "a backup in plain football terms; just never as a cited metric.\n"
        "- You MAY and SHOULD reference the NEWS naturally and WITH attribution, because that is "
        "manager-legible: 'PFF ranks him...', 'an analyst argues...', 'reports say the team hasn't "
        "extended him...', 'the team signed...'. Preserve each claim's basis — an opinion/ranking/"
        "prediction is never stated as established fact; only an 'official' item is a plain fact.\n"
        "- 'mixed' direction means real pulls BOTH ways — surface both sides.\n"
        "- Each note is 1-2 sentences of natural prose. Advisory, not imperative: describe the case "
        "and the cross-pressures the manager weighs; no buy/sell/start/bench commands.\n\n"
        "CONFIDENCE — how provable this read is (the least-provable read in the product): 'high' only "
        "with a present same-season projection AND player-specific news; 'med' with an older/loose "
        "read or only team-level news; 'low' when both are thin/absent. The confidence_note is ONE "
        "plain-language sentence about how current and player-specific your information is — WITHOUT "
        "naming any internal input. GOOD: 'We have a strong sense of his caliber but no fresh "
        "reporting specific to him this year, so treat this as a moderate-confidence read.' BAD: 'The "
        "prior-season anchor and his 55th standing...'.\n\n"
        "OUTPUT — ONLY a JSON object (no prose around it) with EXACTLY these keys: "
        f"{json.dumps(list(SYNTHESIS_KEYS))}.\n"
        "  - bull_grade / bear_grade / situation_grade: integers 1-10.\n"
        "  - bull_note / bear_note / situation_note: 1-2 sentences each, plain prose (no internal "
        "jargon or numbers).\n"
        "  - headlines: a JSON array of 2-5 objects, each {\"text\": <one consolidated headline "
        "sentence>, \"source_article_ids\": [<the article ids that back it>]}. Draw ONLY from the "
        "cited claims; every id must be one shown in the news below. A headline restating an official "
        "injury / roster fact from the roster block may use an empty id list. These are the receipts.\n"
        "  - confidence: one of " + json.dumps(list(CONFIDENCE)) + ".\n"
        "  - confidence_note: one plain-language sentence (see CONFIDENCE above).\n"
    )


def _fmt(v, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{digits}f}"


def _standing_bucket(v) -> str | None:
    if v is None:
        return None
    for thresh, word in _STANDING_BUCKETS:
        if v >= thresh:
            return word
    return "fringe"


def _anchor_block(a: dict | None, *, prior_season: bool, anchor_season) -> list[str]:
    """Render the quantitative anchor (or its explicit absence). Internal — the model reasons off this,
    the manager never sees it; the prose rules keep these out of the notes."""
    if not a:
        return ["Quantitative anchor: NONE available for this player — grade off the news + depth "
                "chart + your own knowledge, and lower confidence."]
    tag = (f"PRIOR SEASON {anchor_season} — a rough caliber reference, NOT a current-season "
           "projection" if prior_season else f"season {anchor_season}")
    role = []
    if a.get("security") in _SECURITY_PLAIN:
        role.append(_SECURITY_PLAIN[a["security"]])
    if a.get("direction") in _DIRECTION_PLAIN:
        role.append(_DIRECTION_PLAIN[a["direction"]])
    role_read = "; ".join(role) if role else "n/a"
    return [
        f"Quantitative anchor ({tag}) — for your reasoning only, do NOT quote any of this in the notes:",
        f"- caliber among players at his position: {_standing_bucket(a.get('spectrum_pos')) or 'n/a'} "
        "(this is the HARD anchor for bull_grade)",
        f"- projected rest-of-season points (cumulative TOTAL over the remaining {a.get('n_weeks')} "
        f"weeks, not per game): bear {_fmt(a.get('ros_bear'))} / center {_fmt(a.get('ros_center'))} / "
        f"bull {_fmt(a.get('ros_bull'))}",
        f"- draft capital (preseason ADP, lower = earlier): ecr {_fmt(a.get('adp_ecr'))} "
        f"(best {_fmt(a.get('adp_best'))} / worst {_fmt(a.get('adp_worst'))})",
        f"- role read (from last data): {role_read}",
    ]


def _facts_block(f: dict | None) -> list[str]:
    """Render the live Sleeper factual fields (injury / depth / practice)."""
    if not f:
        return ["Roster facts: none on file."]
    inj = f.get("injury_status") or "none listed"
    body = f.get("injury_body_part")
    inj = f"{inj} ({body})" if body else inj
    return [
        "Live roster facts (Sleeper):",
        f"- status: {f.get('status') or 'n/a'}; injury: {inj}; "
        f"practice: {f.get('practice_participation') or 'n/a'}",
        f"- depth chart: order {f.get('depth_chart_order')} at {f.get('depth_chart_position') or 'n/a'}",
    ]


def _news_block(claims: list[dict], signal_tier: str, team_news_volume) -> list[str]:
    """Render the player's inherited news-slice claims, tagged by inheritance/scope + basis."""
    if not claims:
        return [f"Situation news: NONE — no claims inherited (signal_tier={signal_tier}). Grade off "
                "the anchor and say the news is silent."]
    header = {
        "rich": "Situation news (includes player-SPECIFIC claims):",
        "thin": "Situation news (team/position-level only — NO player-specific claim; treat as context):",
        "none": "Situation news: none.",
    }.get(signal_tier, "Situation news:")
    lines = [f"{header}  (team news volume in window: {team_news_volume})"]
    for c in claims:
        ids = c.get("source_article_ids") or []
        tag = f"[{c.get('inheritance')}/{c.get('scope')}:{c.get('subject')}]"
        meta = f"({c.get('claim_type')}; basis={c.get('basis')}; dir={c.get('direction')}; sal={c.get('salience')})"
        lines.append(f"- {tag} {meta} ids={json.dumps(list(ids))}")
        lines.append(f"    {c.get('note')}")
    return lines


def user_prompt(ctx: dict) -> str:
    """The per-player user turn: identity + anchor + roster facts + news, then the ask.

    `ctx` is assembled by the writer:
      name / position / team / season / week,
      anchor (dict|None) + anchor_season + anchor_is_prior_season,
      facts (dict|None), claims (list of slice-claim dicts), signal_tier, team_news_volume.
    """
    lines = [
        f"Player: {ctx.get('player_name')} — {ctx.get('position')}, {ctx.get('team')}",
        f"Reading as of: season {ctx.get('season')}, week {ctx.get('week')} (current).",
        "",
    ]
    lines += _anchor_block(ctx.get("anchor"), prior_season=bool(ctx.get("anchor_is_prior_season")),
                           anchor_season=ctx.get("anchor_season"))
    lines += [""] + _facts_block(ctx.get("facts"))
    lines += [""] + _news_block(ctx.get("claims") or [], ctx.get("signal_tier"),
                                ctx.get("team_news_volume"))
    lines += ["", "Write the ROS outcome-shape JSON now."]
    return "\n".join(lines)


def zero_signal_synthesis() -> dict:
    """The hardcoded 'insufficient data' read for a player with NO anchor AND no news (AI skipped).

    Mirrors dossier_prompt.zero_signal_dossier: when there is nothing to fuse, we make an explicit
    no-read rather than let the model invent one. Same schema keys so it slots into the table.
    """
    msg = ("Not enough information is available on this player right now to make a rest-of-season "
           "read.")
    return {
        "bull_grade": None, "bull_note": msg,
        "bear_grade": None, "bear_note": msg,
        "situation_grade": None, "situation_note": msg,
        "headlines": [],
        "confidence": "low",
        "confidence_note": "No projection and no recent news were available for this player — no read.",
    }
