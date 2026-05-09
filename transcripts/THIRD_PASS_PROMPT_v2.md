# Third Pass Data-Tagging Prompt v2.0

## Use Case
Third pass in the synthesis pipeline. Takes the unified strategy markdown produced by Pass 2 and appends data-dependency tags to every rule. The tagged output becomes the "strategy mind" that the Python orchestrator uses to decide what data to fetch for each advisor query.

**Recommended model: Sonnet.** This is a structured tagging task — Opus is overkill. If using Haiku, expect more inconsistent token assignment.

---

## THE PROMPT

```
You are tagging fantasy football strategy rules with the data dependencies required to evaluate them. The output of this pass becomes a contract between the strategy file and the Python orchestrator: when a rule is invoked, Python parses the data tags to know which fetcher functions to call.

# INPUT

You will receive:
1. The full unified strategy markdown file (output of Pass 2)
2. The data token vocabulary (defined separately as a contract — see DATA_TOKEN_VOCABULARY.md)
3. The data stack scope (which tokens are computable from the user's actual data sources, which require paywalled sources, which are unavailable)

# OUTPUT FORMAT

Return the SAME markdown file, unchanged in structure and content, with one addition: a `{needs: ...}` block appended to each rule that depends on observable data.

Format:
- Original rule: `- Start RBs whose team's implied total exceeds 24 points; fade those below 18. [REDRAFT]`
- Tagged rule: `- Start RBs whose team's implied total exceeds 24 points; fade those below 18. [REDRAFT] {needs: vegas_implied_total, depth_chart_position, injury_status}`

The `{needs: ...}` block:
- Goes at the very end of the rule, after applicability tags
- Lists data tokens in snake_case, comma-separated
- Uses ONLY tokens defined in the vocabulary (see input #2)
- Tokens may be appended with `[paywalled]` if they require a paid data source flagged in the stack scope
- Tokens may be appended with `[unavailable]` if the data is not in the stack and has no acceptable proxy
- For rules with no data dependencies (pure principle), append `{needs: none}` rather than omitting the tag

---

# TAGGING DECISION LOGIC

For each rule, ask: **"What data would the advisor LLM need to evaluate whether this rule applies in a given situation?"**

Walk through the rule and list every observable signal it references:

**Example 1 — quantitative threshold rule:**
Rule: "Start RBs whose team's implied total exceeds 24 points; fade those below 18."
Signals referenced: implied team total (Vegas data), starter status (depth chart), health (injury status).
Tag: `{needs: vegas_implied_total, depth_chart_position, injury_status}`

**Example 2 — comparison heuristic with weather:**
Rule: "Downgrade speed-dependent skill players when wind exceeds 15 mph or temperature drops below 35°F."
Signals: weather forecast (wind, temp), player profile (speed-dependence is a derived classification — flag if no token exists).
Tag: `{needs: weather_wind_mph, weather_temp_f, player_speed_score}`

**Example 3 — coverage-dependent rule (paywalled signal):**
Rule: "Favor WRs with strong man-coverage success rates against defenses that run 50%+ man-coverage snaps."
Signals: WR's man-coverage success rate (PFF), defensive coverage tendency (PFF).
Tag: `{needs: wr_man_success_rate [paywalled], def_coverage_man_pct [paywalled], ngs_separation [proxy]}`

The `[proxy]` flag indicates the rule could be partially evaluated with the available signal but would lose accuracy.

**Example 4 — pure principle, no data:**
Rule: "Send fair initial offers (10–20% in your favor) rather than fleece offers — this encourages counter-offers and builds trade relationships."
Signals: none — this is process advice, not a data-driven decision.
Tag: `{needs: none}`

**Example 5 — historical / static data:**
Rule: "Avoid drafting WRs under 185 lbs unless their college YPRR exceeded 3.0."
Signals: player measurables (height/weight), college production stats.
Tag: `{needs: player_height_weight, college_yprr [historical]}`

The `[historical]` flag indicates static data fetched once, not weekly.

---

# UNAVAILABLE DATA HANDLING

If a rule depends on data tokens that are NOT in the data stack scope:

1. Tag the token with `[paywalled]` if the token exists in the vocabulary but the user's stack doesn't include it.
2. Tag the token with `[unavailable]` if no acceptable token exists at all.
3. If at least one available token can serve as a partial proxy, list it and tag with `[proxy]`.
4. Add an inline note to rules where data limitations significantly reduce evaluability: `> *Note: This rule requires [paywalled] coverage data. Without it, the advisor should hedge confidence when applying.*`

Do NOT silently drop rules with unavailable data. Tag them honestly so the Python orchestrator can decide whether to:
- Skip the rule entirely (if no proxy works)
- Apply the rule with a confidence penalty (if proxy is decent)
- Retain the rule pending future data acquisition (if user plans to add the source)

---

# RULES WITH AMBIGUOUS DATA NEEDS

If a rule references something that COULD be evaluated multiple ways, list the most direct token and add the alternatives in parentheses:

Rule: "Buy WRs whose target volume was suppressed by their QB's injury or absence once the starting QB returns to full health."
Tag: `{needs: target_share (last_4_weeks vs season_avg), qb_status, qb_status_history}`

Rule: "Avoid drafting WRs in bottom-five offenses."
Tag: `{needs: team_implied_total (or team_offensive_dvoa or team_epa_per_play)}`

This signals to the orchestrator that any of these tokens would suffice to evaluate the rule.

---

# AGGREGATION OF DATA NEEDS

After processing the full document, append a summary section at the END of the file titled **`## Data Coverage Summary`** with:

1. **Most-referenced tokens** (top 10 by frequency) — these are the tokens your orchestrator should optimize for caching
2. **Fully unavailable rules** — list the rules that cannot be evaluated at all with the current stack
3. **Paywalled-only rules** — list rules that require paid data sources
4. **Tokens used but not in vocabulary** — flag any tokens you had to invent because the vocabulary didn't cover them; the user should add these to the vocabulary

This summary lets the user audit data gaps and decide whether to acquire additional sources.

---

# WHAT NOT TO DO

- Do NOT modify rule content. Tagging only.
- Do NOT remove rules even if they have no available data. Tag them as `[unavailable]` and let downstream decide.
- Do NOT invent data tokens that aren't in the vocabulary unless absolutely necessary — and when you do, flag them in the Data Coverage Summary so the user can add them.
- Do NOT change applicability tags ([REDRAFT], [DYNASTY], etc.). Those were Pass 2's job.
- Do NOT collapse multiple rules. Tag each one individually.

---

# FINAL CHECK

Before producing output, verify:

1. Every rule in the input has a `{needs: ...}` block (use `{needs: none}` for pure principles)
2. All tokens used appear in the vocabulary, OR are flagged as new in the summary
3. Paywalled and unavailable tokens are flagged correctly
4. The Data Coverage Summary is appended
5. Rule content and applicability tags are unchanged
6. Document ends cleanly without truncation
```

---

## Workflow

1. **Lock the data token vocabulary first** — see `DATA_TOKEN_VOCABULARY_TEMPLATE.md`. Don't run Pass 3 against an undefined vocabulary; the model will invent tokens that don't match your fetcher functions.

2. **Run Pass 3 against the Pass 2 output** for each strategy file (one per league format). At Sonnet rates, this is ~$0.50 per strategy file.

3. **Audit the Data Coverage Summary first.** This tells you:
   - Which tokens to prioritize in your fetcher implementation
   - Which rules can never be evaluated (cut or replace)
   - Which tokens you forgot to define in the vocabulary

4. **Iterate the vocabulary** based on what Pass 3 surfaced, then re-run if necessary.

---

## Why this is a separate pass

Pass 2 (synthesis) is a creative-judgment task: deciding what's a rule, resolving conflicts, applying calibration logic. It benefits from Opus.

Pass 3 (tagging) is a structured-mapping task: read a rule, list its data dependencies, look up tokens. Sonnet handles it well at much lower cost.

Splitting them also means: when you update your data stack (add coverage data, swap out one fetcher, etc.), you re-run only Pass 3, not Pass 2. The strategy file's intellectual content stays stable while the data layer evolves.
