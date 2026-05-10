# First Pass Extraction Prompt v2.0

## Use Case
Drop-in replacement for the existing first-pass extraction prompt. Takes a single transcript `.txt` file as input and produces the numbered-list-of-rules string that becomes one entry in the JSON cache consumed by Second Pass v2.

The first pass is the more important of the two. The second pass can only preserve quality that the first pass extracted. Numbers lost here are lost forever. Player-specific takes that slip through here will pollute the strategy doc downstream. Treat this pass as the quality bottleneck.

---

## THE PROMPT

```
You are extracting strategy rules from a single fantasy football YouTube video transcript. The output of this extraction will be one entry in a JSON cache that downstream gets synthesized into a strategy guide for an AI fantasy football advisor.

Your output must be a numbered list of rules. Each rule must be a single self-contained sentence (or short paragraph) that an LLM advisor could later apply to a real fantasy football decision.

# INPUT

You will receive:
1. The video filename (often informative — may include creator, week number, topic, format)
2. The full transcript text (often a NoteGPT auto-transcript: no punctuation in places, run-on sentences, occasional mishearings, filler words, sometimes multiple speakers blended together)

Treat the transcript as messy text and read for meaning, not surface form.

# OUTPUT FORMAT

A single string containing a numbered list of rules, each separated by exactly two newlines (`\n\n`). Like this:

1. First rule sentence here.

2. Second rule sentence here.

3. Third rule sentence here.

No preamble, no postscript, no headers, no source attribution within the output, no explanations. Just the numbered list.

Target 5–20 rules per video depending on rule density. Quality over quantity — better to extract 6 sharp rules than 20 mushy ones.

---

# WHAT TO EXTRACT

A rule qualifies for extraction if it satisfies AT LEAST ONE of these forms:

**Form A — Quantitative threshold:**
"When [metric] crosses [number], do [action]"
Example: "Start RBs whose team's implied total exceeds 24 points; fade those below 18."

**Form B — Conditional decision:**
"If [condition X] AND [condition Y], do [action]; otherwise [alternative]"
Example: "Only start rookie RBs in Week 1 if they secured 80%+ snap rate AND have no meaningful committee competition."

**Form C — Comparison heuristic:**
"Prefer [X] over [Y] because [causal reason]"
Example: "Prefer young RBs (22–26) on contending teams over aging RBs at the same tier — younger options retain re-trade value if the team falters mid-season."

**Form D — Anti-pattern / red flag:**
"Avoid/discount [X] when [specific signal]"
Example: "Avoid drafting WRs under 185 lbs unless their college YPRR exceeds 3.0."

The rule must be transferable across seasons and players. Test: would this rule still apply next year with different player names? If yes, extract. If no, skip.

---

# WHAT TO EXCLUDE

Do not extract:

1. **Player-specific takes that hide a transferable reasoning pattern — DO NOT SKIP, TRANSMUTE.**
   This is the single most important extraction skill for this project. Most week-to-week fantasy content is *framed* as "should you start Player X this week?" but the *reasoning* the analyst gives almost always reveals a transferable principle. Your job is to extract the principle, discarding the player.

   **Examples of transmutation:**
   - Source: "Start Romeo Doubs this week — he beats man coverage but the Vikings run mostly zone, so he's a risky play."
   - Bad extraction (loses the rule): "Doubs is a risky start vs. Minnesota."
   - Bad extraction (skips the rule entirely): [no rule extracted]
   - **Good extraction:** "When evaluating WRs in matchup-driven decisions, weight the WR's man-vs-zone success splits against the opposing defense's coverage frequency; downgrade WRs whose strengths don't match the defensive scheme they'll face."

   - Source: "I don't like De'Von Achane this week — bad weather forecast and the Dolphins offense doesn't function in cold."
   - **Good extraction:** "Downgrade speed-dependent skill players when game weather forecasts include cold, wind, or precipitation, especially on offenses with documented poor-weather track records."

   - Source: "Garrett Wilson is a buy-low — Aaron Rodgers is back from injury and his targets will normalize."
   - **Good extraction:** "Buy WRs whose target volume was suppressed by their QB's injury or absence once the starting QB returns to full health, before the market re-prices the receiver."

   The extracted rule should NOT name the player. The player is the example; the rule is the principle.

   **Only skip player-specific content when no transferable reasoning is offered.**
   - SKIP: "I love Saquon Barkley this week" (no reasoning given)
   - SKIP: "Trade Tony Pollard, he's washed" (no analytical content)
   - SKIP rankings recitations: "RB1 is McCaffrey, RB2 is Saquon, RB3 is..." (no reasoning, just rankings)

2. **Tautologies and platitudes.**
   - SKIP: "Draft the best players"
   - SKIP: "Stay informed"
   - SKIP: "Trust your instincts"
   - SKIP: "Be flexible"

3. **Pure summaries of news without an actionable principle.**
   - SKIP: "The Bengals signed a new offensive coordinator"
   - KEEP: "Adjust WR rankings upward when teams hire offensive coordinators with pass-heavy track records" (the underlying principle)

4. **Hedged speculation the speaker explicitly flagged as low-confidence.**
   - SKIP: "I could be wrong, but maybe..."
   - SKIP: "Just spitballing here..."
   - KEEP: rules the speaker stated with conviction or repeated.

5. **Devil's-advocate framings the speaker raised then rejected.**
   If the speaker says "Some people say X, but I disagree because Y," extract Y, not X.

6. **Hot takes presented as entertainment, not strategy.**
   "This pick is BUFFOONERY" → ignore the framing, see if there's a real principle underneath.

7. **Rules with no actionable trigger condition.**
   - SKIP: "Always think long-term in dynasty" (no trigger, no action)
   - KEEP: "When evaluating players in startup drafts, prioritize players under 26 over similarly-ranked players over 28"

---

# DATA-AWARE RULE EXPRESSION

The downstream agent operates on a Python-orchestrated data stack including: nflverse (play-by-play, snap counts, target share, NGS separation, EPA, advanced stats, schedules, rosters, historical injuries), LeagueLogs / Sleeper (real-time NFL state, depth charts, transactions), Vegas lines, weather feeds, and current injury reports. Coverage-type data (man vs zone tendencies) may or may not be available depending on whether a paid data source like PFF is included.

Express extracted rules in terms of the **measurable signals** the agent can actually look up. Replace vague qualitative language with the closest-equivalent observable metric:

- "Tough run defense" → "Defenses ranked top-10 in fantasy points allowed to RBs OR allowing under Y rushing yards per game"
- "Stale offense" → "Offenses with declining Vegas implied team totals (3+ week trend) or below-average EPA per play"
- "Bad weather" → "Game-day forecast of winds 15+ mph, precipitation, or temperature below 35°F"
- "Crowded backfield" → "Backfields where two or more RBs share 35%+ of snaps each"
- "Bad matchup at WR" → "Defense ranks top-10 in fantasy points allowed to WRs OR holds opposing WR1s under their season-average target share"

When the original rule depends on coverage-type data (man vs zone) that may not be in the stack, express it both ways:
- Use the closest free-data proxy (NGS separation, target rate vs. defensive front, success rate vs. position)
- Note that coverage-type data would sharpen the rule if available

You do not need to know the *exact* metric name. The aim is to anchor the rule in something measurable, not vibes. The second pass will refine metric names and tag each rule with the specific data it requires; your job is to keep the rule grounded in observable phenomena.

**This rule applies even when the source itself is vague.** If a video says "watch out for tough matchups," the extracted rule should specify what makes a matchup tough in measurable terms.

---

# QUANTITATIVE THRESHOLDS — PRESERVE EVERY NUMBER

If the speaker mentions a specific number, the extracted rule must include that number. Numbers are the most valuable signal in fantasy content because they convert vibes into decisions.

Numbers to preserve include:
- Age windows (22–26, 27+, 30+)
- Athletic metrics (4.45 forty, 220 lbs, 6'0", RAS 6.5)
- Production thresholds (25% target share, 3.0 YPRR, 60% snaps, 7+ YPC)
- Hit rates / probabilities (86%, 26%, 75%)
- Round/pick cutoffs (round 3, 1.05–1.10, late-second)
- Vegas thresholds (implied total > 24, spread of 7+)
- Time windows (years 1–2, age-26 season, 5-week return timeline)
- Volume thresholds (3+ pre-draft visits, 81% of teams, 8+ targets)

Do NOT abstract numbers into vague language. "Sub-4.63 forty AND under 214 lbs = virtually zero relevance" is a great extracted rule. "Slow small RBs are bad" is a useless one.

If the speaker gives a number that sounds wrong or implausible, extract it anyway with the speaker's exact phrasing. The second pass will moderate overclaims; the first pass should not.

---

# JARGON HANDLING

Keep fantasy-football jargon when used. Do NOT define jargon at this stage — the second pass handles definitions. Common terms to preserve as-is:

Konami QB, Hero RB, Zero RB, RB dead zone, Anchor TE, TE premium, Onesie, Taxi squad, Cornerstone, Anchor player, Stacking, Bracket, ADP, FAB, RPO, YPRR, YAC, ATD, MTF, EPA, target share, route participation, dominator rating, prospect grade, draft capital, landing spot, handcuff.

If the speaker uses a niche term not on this list, preserve it as-is and let the second pass decide whether to define or strip it.

---

# FORMAT TAGGING (OPTIONAL HELPFUL OUTPUT)

If the rule is unambiguously format-specific based on either the filename or its own content, you MAY append a tag at the end of the rule in brackets:

- [REDRAFT] — applies to seasonal/redraft formats only
- [DYNASTY] — applies to dynasty/keeper formats only
- [SUPERFLEX] — Superflex-specific
- [TEP] — TE-premium specific
- [PPR] — PPR scoring specific

Use these signals to tag:
- Filename mentions "Week N", "Waiver", "Start/Sit", "This Week" → likely [REDRAFT]
- Filename mentions "Dynasty", "Rookie Draft", "Startup", "Long-term" → likely [DYNASTY]
- Rule mentions "rookie picks", "future picks", "age windows of 5+ years", "trade calculator" → [DYNASTY]
- Rule mentions "this week", "FAB", "weekly streaming", "Week N matchup" → [REDRAFT]

If you can't confidently tag, leave the rule untagged. The second pass will apply tags based on broader context. Wrong tags are worse than missing tags.

---

# DEDUPLICATION WITHIN A SINGLE VIDEO

If the speaker states essentially the same rule twice (e.g., once in setup and once in summary), extract it ONCE using the more specific or more quantitatively anchored version. The second pass dedupes across videos; you only dedupe within this video.

If the speaker states two related-but-distinct rules (e.g., "draft RBs early in standard" AND "draft WRs early in PPR"), extract both as separate rules.

---

# MESSY TRANSCRIPT HANDLING

NoteGPT auto-transcripts are imperfect:
- Missing punctuation in stretches → infer sentence boundaries from meaning
- Misheard words ("Tetereo" might be "Tetairoa", "Bayou" might be "Baio") → use context to interpret
- Run-on speaker streams → break into discrete claims
- Multiple speakers blended without attribution → extract any rule stated, regardless of which speaker
- Mid-sentence subject changes → take the most coherent claim available

If a passage is genuinely incoherent and you can't extract a clean rule, skip it rather than guess.

---

# RULE WRITING STANDARDS

Each extracted rule must be:

- **Self-contained** — readable without reference to other rules or to the source video
- **Imperative** — tells the advisor what to do, not just what is true
- **Specific** — names positions, conditions, thresholds, not generic "players"
- **Concise** — one sentence preferred, two if needed for a clean conditional. Never a paragraph.
- **Free of hedge words** unless the hedge is the rule's content. "Possibly target X" → "Target X when [condition]" or skip.
- **Free of speaker-presence** — never write "the speaker says..." or "the host believes..." Extract the underlying claim.

---

# FINAL CHECK

Before producing output, verify:

1. Output is a numbered list, each rule separated by `\n\n`, no preamble/postscript
2. Every rule satisfies at least one of Form A/B/C/D
3. No tautologies, platitudes, or pure player-of-the-week takes
4. All numerical thresholds from the source are preserved
5. Rules are imperative and self-contained
6. Player names appear only as illustrative examples for transferable rules, not as standalone takes
7. If you tagged any rules, the tags are confident and based on filename or rule content

If any check fails, fix before finalizing.
```

---

## Notes on Implementation

**Pass the filename as part of the input.** Looking at your existing JSON, you've been keying by filename — confirm your first-pass call passes the filename to the model alongside the transcript body. The tagging signals depend on the model seeing it.

**Keep input compact.** NoteGPT transcripts can be 10K–30K tokens of repetitive speech. The model doesn't need the whole stream verbatim — but if you pre-clean (strip filler, dedupe phrasing) you risk losing real signal. Better to send the raw transcript and let the model filter.

**Re-running cost is modest.** All 173 transcripts (34 + 27 + 57 + 55) at maybe 5K input tokens each = ~865K input tokens. Output ~150K tokens (rules). At Sonnet pricing that's ~$2.60 input + $2.25 output ≈ $5 for full re-extraction. At Haiku ~$0.40. Either is well within the budget you indicated.

---

## What This Fixes vs. v1

Looking at the existing JSON outputs, the first-pass v1 prompt is doing fine on basic extraction but letting through:

1. **Vague rules.** Examples I saw: "Track first-half vs. second-half performance trends" — what's the trigger? What's the action? v2's Form A/B/C/D requirement kills these.
2. **Player-of-the-week takes that won't generalize.** v2 has an explicit redraft filter.
3. **No format pre-tagging.** v2 lets the first pass do the easy tagging where filename + content make it obvious, reducing second-pass workload.
4. **Repetition within a single video.** v2 mandates within-video dedup.

It does NOT change much for high-quality videos that were already producing sharp output. The improvement is mostly at the floor, not the ceiling.

---

## Workflow Recommendation for the FSE Redraft Batch

1. **Use FIRST_PASS_PROMPT_v2 for the 55 FSE redraft transcripts.** This is the largest batch and where prompt quality compounds the most.

2. **Decide whether to re-extract the existing 3 batches.** Worth doing if:
   - You see meaningful junk in the existing JSONs (we already saw some)
   - You want consistent rule quality across all 4 strategy mind files
   - The cost (~$5) is acceptable

3. **Run SECOND_PASS_PROMPT_v2 against each cache 3x** at temperature 0.3–0.5, then run the merge pass.

4. **For fse_dynasty specifically,** plan for the two-part output split since that one has already truncated.
