"""
Prompt construction for the Team News Dossier AI layer (§2 news pipeline Stage B).

Pure — no I/O, no API calls. Builds the shared, stable system prefix (cache-friendly) and a
per-team user prompt from a window of raw articles. The extraction is **situation/security-focused**
(the §2 ROS footprint): only claims that bear on a player's rest-of-season outlook, clustered across
the three sources into single claims. Framing is tendencies-not-verdicts (law 2). The model emits
player NAMES, never ids — the deterministic resolver (fetchers/news.py) attaches sleeper ids
downstream, so the AI never guesses an identifier.
"""

import json

# The fixed per-claim schema — the SAME keys for every claim so the sheet reads uniformly and the
# gate can validate structurally. `source_article_ids` cites the raw articles a claim is grounded in.
# `basis` marks the epistemic status (see BASES) so a downstream model never mistakes an opinion for
# established fact — the crux of feeding unstructured news to another AI.
CLAIM_KEYS = ("scope", "subject", "claim_type", "basis", "note", "direction", "salience",
              "source_article_ids")

# Controlled vocabularies (the writer + gate validate against these).
SCOPES = ("player", "position_group", "unit")
CLAIM_TYPES = ("injury", "depth_chart", "role_usage", "competition", "coaching_scheme",
               "offense_strength", "defense_strength", "transaction", "outlook")
DIRECTIONS = ("positive", "negative", "neutral", "mixed")
SALIENCES = ("low", "med", "high")
# The epistemic status of the claim — what we actually KNOW is that a source asserted this:
#   official   — the team/player/league announced or confirmed it (an established fact: a signing,
#                an official injury designation, a depth-chart move the team made).
#   reported   — media/beat reporting, credible but not team-confirmed ("sources say", a report).
#   opinion    — an analyst's / blogger's / fan evaluation, ranking, prediction or speculation.
BASES = ("official", "reported", "opinion")

_PROMPT_CONTENT_CHARS = 800     # per-article body budget in the prompt (titles carry the summary sources)


def system_prompt() -> str:
    """The shared, stable instruction prefix (identical across teams → cache-friendly)."""
    return (
        "You are a fantasy-football analyst distilling a week of local team news into a compact "
        "'news sheet'. You are given recent articles about ONE NFL team from three source types — "
        "the official team site (authoritative but PR-heavy), an SB Nation team blog (grounded "
        "analysis), and a FanSided team blog (player/fantasy-flavored, often headline-only). Your "
        "job is to extract the SITUATION/SECURITY claims that bear on the REST-OF-SEASON fantasy "
        "outlook of the team's OFFENSIVE SKILL players (QB / RB / WR / TE ONLY), so a downstream "
        "model can read them next to numerical projections.\n\n"
        "Extract ONLY claims of these kinds. Set `claim_type` to EXACTLY the token before the dash "
        "(never the description):\n"
        "- injury — injury / health / recovery status\n"
        "- depth_chart — depth-chart position and changes\n"
        "- role_usage — role / usage / snap-share / touches trend\n"
        "- competition — position competition (who's pushing whom; rookies, new signings)\n"
        "- coaching_scheme — coaching / scheme / coordinator changes that shift usage\n"
        "- offense_strength — offense strength / pace / supporting cast / offensive line\n"
        "- defense_strength — the team DEFENSE's overall state (the single condensed defense note; see below)\n"
        "- transaction — signings, trades, releases, suspensions that change a role\n"
        "- outlook — a rest-of-season fantasy outlook note that doesn't fit the above\n\n"
        "IGNORE and do not emit: game previews/recaps, matchup or betting talk, pure hype/opinion "
        "with no situational fact, ticket/sponsorship/community PR, rankings-list filler, and any "
        "non-English item.\n\n"
        "DEFENSE — condense, never itemize: do NOT emit individual claims about defensive or "
        "special-teams players. Instead fold the whole defensive picture into AT MOST ONE claim "
        "(scope='unit', subject='defense', claim_type='defense_strength') summarizing the defense's "
        "overall strength / health / key additions or losses — because a strong or weak defense "
        "lightly shapes game script (pass rate, rushing volume, garbage time) for the offense, and "
        "this pre-stores the signal for later. Keep its salience 'low' unless a major shift.\n\n"
        "Every field must use EXACTLY these values:\n"
        f"- scope: one of {json.dumps(list(SCOPES))}\n"
        f"- claim_type: one of {json.dumps(list(CLAIM_TYPES))}\n"
        f"- direction: one of {json.dumps(list(DIRECTIONS))} — the effect on the subject's fantasy "
        "value. 'positive'/'negative' = clearly helps/hurts; 'neutral' = genuinely no material "
        "fantasy impact; 'mixed' = cross-pressured, real pulls BOTH ways (e.g. a new lead role — good "
        "— in a scheme that historically suppresses the position — bad). Use 'mixed' for contested / "
        "contradictory situations; do NOT use 'neutral' as a catch-all for those.\n"
        f"- salience: one of {json.dumps(list(SALIENCES))}\n"
        f"- basis: one of {json.dumps(list(BASES))} — the epistemic status: 'official' = the team / "
        "player / league announced or confirmed it (an established fact); 'reported' = media/beat "
        "reporting, not team-confirmed; 'opinion' = an analyst / blogger / fan evaluation, ranking, "
        "prediction or speculation. When in doubt between reported and opinion, choose 'opinion'.\n\n"
        "Rules:\n"
        "- CLUSTER: when several articles/sources report the SAME development, emit ONE claim and "
        "cite every supporting article id. More independent sources = more trust — do NOT split one "
        "story into duplicate claims.\n"
        "- Tag each claim's scope: 'player' (one specific named OFFENSIVE SKILL player — QB/RB/WR/TE "
        "only), 'position_group' (an offensive skill room, e.g. the RB or WR room), or 'unit' "
        "('offense' as a whole, or the single 'defense' note described above).\n"
        "- For a 'player' claim put the offensive skill player's FULL NAME in `subject` (e.g. "
        "'Rashee Rice'); for 'position_group' use a skill position word (QB/RB/WR/TE); for 'unit' "
        "use 'offense' or 'defense'. NEVER output a player id — just the name.\n"
        "- A 'player' claim must be about a player CURRENTLY ON THIS team. If the news is about an "
        "opponent, a trade/free-agent target, or a former player, don't make it a player claim — "
        "capture it (if relevant) as a position_group / unit / competition note instead.\n"
        "- ATTRIBUTE, don't assert. What we actually know is that a SOURCE said or thinks something "
        "— NOT that it is established truth. Every `note` must make the speaker/nature explicit and "
        "match its `basis`:\n"
        "    · opinion  → lead with the holder: 'Beat writers expect…', 'An SB Nation analyst argues"
        "…', 'A fan poll rates…', 'PFF's ranking places…', 'Local coverage speculates…'.\n"
        "    · reported → 'Reports indicate…', 'Per reporting, …' (attributed, not team-confirmed).\n"
        "    · official → only here may you state it plainly as fact ('The team signed…', 'Officially "
        "ruled out…') — because the team/league actually confirmed it.\n"
        "  Never phrase an opinion, ranking, projection or speculation as a flat fact. A reader must "
        "not be able to mistake 'an analyst thinks X' for 'X is true'.\n"
        "- `note` is ONE synthesized sentence — the attributed cliffs-note, not a quote. `direction` "
        "is the claim's effect on fantasy value (positive/negative/neutral/mixed — see above; a "
        "'mixed' note should surface BOTH sides). `salience` is how much it matters (low/med/high).\n"
        "- Ground every claim in the provided text. If the window has NO qualifying news, return an "
        "empty array [].\n"
        "- Output ONLY a JSON array of claim objects — no prose around it — each with EXACTLY these "
        f"keys: {json.dumps(list(CLAIM_KEYS))}. `source_article_ids` is a JSON array of the bracket "
        "ids shown for the articles you used.\n"
    )


def _team_line(team: str) -> str:
    return f"Team: {team}"


def user_prompt(team: str, articles: list[dict]) -> str:
    """The per-team user turn: the windowed article list (id / source / date / title / content)."""
    lines = [
        _team_line(team),
        f"Recent articles in the window: {len(articles)}",
        "",
        "Articles (cite the [id] in source_article_ids):",
    ]
    for a in articles:
        content = (a.get("content") or "").strip()[:_PROMPT_CONTENT_CHARS]
        net = a.get("source_type", "")
        date = (a.get("published_at") or "")[:10]
        lines.append(f"[{a['article_id']}] ({net}, {date}) {a.get('title', '')}")
        if content:
            lines.append(f"    {content}")
    lines += ["", "Extract the situation/security claims as a JSON array now."]
    return "\n".join(lines)
