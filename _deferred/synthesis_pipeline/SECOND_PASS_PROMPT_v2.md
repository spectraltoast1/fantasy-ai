# Second Pass Synthesis Prompt v2.0

## Use Case
Drop-in replacement for the existing second-pass synthesis prompt. Takes the per-transcript JSON cache as input and produces the consolidated strategy markdown file.

---

## THE PROMPT

```
You are synthesizing a fantasy football strategy guide from a JSON cache of per-transcript learnings. The output of this synthesis will become the strategy-mind of an AI fantasy football advisor — every rule must be operationally useful to an LLM making real recommendations to a real fantasy football manager.

# INPUT FORMAT

A JSON object structured as:

{
  "Source Video Title.txt": "1. First rule extracted from this video.\n\n2. Second rule.\n\n3. Third rule.\n\n...",
  "Another Source Video.txt": "1. ...\n\n2. ...\n\n...",
  ...
}

Each KEY is the source transcript filename. Each VALUE is a numbered list of rules extracted from that single video, separated by \n\n. Expect 25–60 source videos per cache, with 5–20 rules per video, totaling 200–800 raw rules to synthesize.

# YOUR TASK

Produce a single comprehensive markdown strategy guide following the strict requirements below.

# USE SOURCE TITLES AS TAGGING SIGNALS

The source video titles carry meaningful context. Use them to inform applicability tagging when the rule itself is ambiguous:

- Title contains "Week N", "Waiver", "Start/Sit", "Buy Low", "Sell High" mid-season → likely [REDRAFT]
- Title contains "Dynasty", "Rookie Draft", "Startup", "Trade Targets" (offseason) → likely [DYNASTY]
- Title contains "Superflex" or "SF" → adds [SUPERFLEX]
- Title contains "TE Premium" or "TEP" → adds [TEP]
- Title contains "PPR" → adds [PPR]; "Standard" → adds [STANDARD]
- Title is generic ("How to Draft", "10 Sleepers") → use rule content alone to tag

When the rule's wording itself signals format (e.g., mentions trade calculator, rookie picks, age windows, multi-year horizons) that ALWAYS overrides title context.

---

# CRITICAL: ANTI-TRUNCATION

You MUST complete the entire document. If you sense you are running long:
- Do NOT abbreviate, summarize, or skip later sections to fit
- Do NOT end mid-sentence, mid-table, or mid-list
- If you cannot fit everything, STOP at a clean section break and end with a literal line:
  <!-- SYNTHESIS INCOMPLETE: stopped at end of Section X. Run a continuation pass starting at Section X+1. -->

This is more important than appearing complete. A clean stop with a marker is recoverable; a silent truncation is not.

If the input is large (40+ source videos), strongly consider producing the output in two parts:
- Part 1: Sections 1–4 (Draft Strategy, Player Evaluation, In-Season Management)
- Part 2: Sections 5–8 (Situational, League-Format, Calibration, Conflicts)
End Part 1 with the truncation marker so the second call can pick up cleanly.

---

# OUTPUT STRUCTURE

The document MUST follow this exact section structure (omit any sections with no source material rather than inventing content, but mark omissions explicitly):

1. **How to Use This Document** — explain tagging conventions
2. **Draft Strategy** (subsections per position: QB, RB, WR, TE, K, DEF as applicable)
3. **Player Evaluation** (rules for assessing individual players)
4. **In-Season Management**
   - 4a. Waiver Wire (per position)
   - 4b. Start/Sit Decisions (per position)
   - 4c. Trade Strategy — Buying
   - 4d. Trade Strategy — Selling
   - 4e. Bye Weeks & Playoff Scheduling
5. **Situational & Scheme Factors** (offense quality, OC/QB changes, weather, etc.)
6. **League-Format Adjustments** (PPR vs. standard, Superflex, TE-premium, deep leagues)
7. **Calibration & Confidence** (rules about WHEN to override defaults)
8. **Noted Conflicts** — appendix table of source disagreements with explicit resolutions

If a section has fewer than 3 rules from source material, note this with: *Sparse coverage: only N rules from N source(s)* rather than padding.

---

# TAGGING CONVENTIONS — MANDATORY AT THE RULE LEVEL

Every rule must be tagged inline based on applicability. Tags go at the END of the rule in this format:

- [REDRAFT] — applies to seasonal/redraft formats only
- [DYNASTY] — applies to dynasty/keeper formats only
- [BOTH] — applies to both formats (use sparingly; default to specific tags)
- [SUPERFLEX] — Superflex-specific
- [TEP] — TE-premium specific
- [PPR] — PPR scoring specific
- [STANDARD] — non-PPR specific

A rule may carry multiple tags: [REDRAFT][PPR]. Tag at the rule level, never just the section header. Untagged rules will be rejected as low quality.

**Note on data-dependency tagging:** A separate Third Pass will append data-dependency tags `{needs: ...}` to each rule, mapping rules to the specific data tokens the orchestrator must fetch. You do NOT need to add these in this pass. Focus on rule quality, applicability tagging, and conflict resolution.

---

# RULE QUALITY CRITERIA

Each rule must satisfy AT LEAST ONE of these forms. Rules that satisfy none should be excluded:

**Form A — Quantitative threshold rule:**
"When [metric] crosses [number], do [action]"
Example: "Start RBs whose team's implied total exceeds 24 points; fade those below 18. [REDRAFT]"

**Form B — Conditional decision rule:**
"If [condition X] AND [condition Y], do [action]; otherwise [alternative]"
Example: "Start rookie RBs in Week 1 only if they secured 80%+ snap rate AND have no meaningful committee competition. [REDRAFT]"

**Form C — Comparison heuristic:**
"Prefer [X] over [Y] because [causal reason]"
Example: "Prefer young RBs (22–26) on contending teams over aging RBs at the same tier — younger options retain re-trade value if your team falters mid-season. [DYNASTY]"

**Form D — Anti-pattern / red flag:**
"Avoid/discount [X] when [specific signal]"
Example: "Avoid drafting WRs under 185 lbs unless their college YPRR exceeds 3.0. [DYNASTY]"

**EXCLUDE these rule shapes:**
- Tautologies: "Draft good players over bad players"
- Vague philosophy without operationalization: "Trust the process"
- Pure platitudes: "Stay informed"
- Unfalsifiable claims: "Always be flexible"
- Rules with no actionable trigger condition

---

# OVERCLAIM MODERATION

When source material makes absolute claims (always, never, 100%, 0%, every time), apply this filter:

- If multiple independent sources confirm the same absolute claim → keep the strong language
- If only ONE source makes the absolute claim → soften to probabilistic language ("historically hits at very high rates" instead of "100% of the time")
- If the absolute claim is implausible on its face → soften AND attribute ("One source claims X; treat as a strong signal rather than a guarantee")

The LLM advisor downstream will repeat absolute language as fact. Be conservative.

---

# REDRAFT-SPECIFIC HANDLING (read this if synthesizing a redraft batch)

Source material from in-season redraft content is dominated by player-specific calls ("Start Brian Robinson Week 7"). The first pass should already have transmuted these into reasoning patterns. Your job is to verify, consolidate, and ensure data-grounded expression.

**Verify the first-pass transmutation worked.** If you see rules that still reference specific players as the *subject* of the rule (rather than as illustrative examples), strip the player name and keep the principle:

- BAD (player is the subject): "Brian Robinson is a strong start vs. zone-heavy defenses."
- GOOD (player removed, principle preserved): "Start RBs whose man/zone success splits favor the opposing defense's coverage tendency."

**Express rules in terms of measurable signals.** The downstream advisor will have access to live NFL data (play-by-play, snap counts, target share, defensive ranks, Vegas lines, weather, coverage tendencies, etc.). Rules should be phrased in terms of observable metrics where possible:

- "Tough matchup" → "Defense top-10 in DVOA at position OR top-10 in fantasy points allowed at position"
- "Stale offense" → "Vegas implied team total below 18 OR declining 3+ weeks"
- "Bad weather" → "Wind 15+ mph, precipitation, or temp below 35°F"
- "Beats man coverage" → "Above-average success rate vs. press-man coverage in nflverse / PFF data"

When source rules use vague qualitative language, sharpen to measurable signals during synthesis. If you cannot identify a measurable proxy, retain the qualitative term but flag it: `[needs metric definition]`.

**Reasoning patterns that survived transmutation are the most valuable rules in the redraft batch.** They are why redraft sources are worth synthesizing at all — they capture how analysts read matchups, weather, coaching tendencies, and game scripts. Treat them with at least as much weight as preseason draft rules.

**Still exclude:**
- Pure rankings recitations with no reasoning ("RB1 is X, RB2 is Y...")
- Player-of-the-week takes with no analytical content ("I love Bijan this week")
- Roster-specific advice that requires knowing who the user owns ("Trade your RB2 for...")

The test: would this rule be useful next season with different players AND can the agent look up the inputs the rule depends on? If yes to both, keep.

---

# QUANTITATIVE THRESHOLD PRESERVATION

This is the most valuable signal in source material. You MUST preserve all of:
- Age windows ("ages 22–26", "27+", "30+")
- Athletic thresholds (forty times, weight, height, RAS scores)
- Production thresholds (target share %, YPRR, snap %, yards per carry)
- Hit rate / probability stats ("86% hit rate", "26% top-24 chance")
- Round/draft capital cutoffs
- Vegas thresholds (implied team totals, spreads)
- Snap share / route participation thresholds

If source material gives a number, the synthesis must include that number. Do not abstract numbers into vague language.

---

# JARGON HANDLING

If a rule uses fantasy-football jargon, define the term inline on first use, parenthetically:

- "Konami-archetype QBs (dual-threat passers whose rushing volume provides a fantasy floor)"
- "Hero RB strategy (drafting one elite RB then loading WRs/TEs before drafting a second RB)"
- "Zero RB (avoiding RBs entirely in early rounds)"
- "Dead zone (mid-round positional ranges where hit rates collapse)"

Common terms that need definition: Konami QB, Hero RB, Zero RB, RB dead zone, Anchor TE, TE premium, Onesie position, Taxi squad, Cornerstone, Anchor player, ADP, FAB, Stacking, Bracket strategy.

---

# CONFLICT RESOLUTION — TAKE A POSITION

When sources disagree, you MUST adjudicate. Soft resolutions ("these are not mutually exclusive — depends on your league") are FORBIDDEN unless the conflict genuinely reduces to a format/league setting that the user explicitly controls.

For each conflict, produce:

| Topic | Source A position | Source B position | Resolution |
|---|---|---|---|
| [topic] | [A's claim with attribution] | [B's claim with attribution] | [Decisive resolution: which to follow, under what conditions, and why] |

Place the conflict table at the END of the document as Section 8. Reference it inline at the point of conflict with: [See Conflict #N].

If a conflict cannot be resolved without more information, state explicitly what information would resolve it.

---

# STALE EXAMPLES & PLAYER NAMES

When source material uses specific player names as examples:
- Replace with the underlying archetype where possible: "Travis Kelce" → "an aging future Hall-of-Fame TE"
- If the player name materially anchors the rule, retain the name BUT add [as of source date] qualifier
- Never present player-specific takes as ongoing truth

Player-specific takes go stale; archetype takes don't.

---

# CALIBRATION SECTION

Section 7 (Calibration & Confidence) is critical and often skipped in synthesis. Include rules of the shape:

- "Override [default rule] when [specific high-confidence signal] is present"
- "Trust the projection model unless [specific market signal] disagrees by more than [magnitude]"
- "When sources disagree by [N tiers], default to [conservative position]"

These rules tell the downstream LLM advisor when to bend its own rules. Without them, the advisor will be brittle.

---

# DEDUPLICATION

If two sources state the same rule with different phrasings:
- Keep one phrasing (prefer the more specific/quantitative version)
- Note source agreement implicitly by NOT flagging as conflict
- Do not list the same rule twice with different phrasings

If two rules are *adjacent in concept but not identical*, keep both and ensure their distinction is clear.

---

# SOURCE ATTRIBUTION

Within the body of the document, do not attribute individual rules to source files (it bloats the doc). EXCEPT:
- Conflict table (must attribute both sides by source filename)
- Rules where attribution materially affects how the LLM should weight the rule (e.g., when one source has unusually strong track record on a specific topic)

Otherwise, the synthesis presents rules as a unified voice.

---

# FINAL CHECK — RUN THESE BEFORE OUTPUT

Before producing the final document, verify:

1. Every section in the required structure is present (or explicitly marked as *Section omitted: no relevant source material*)
2. Every rule carries at least one applicability tag
3. No tautologies, no pure philosophy, no unfalsifiable claims
4. Every quantitative threshold from source material has been preserved
5. All conflicts have decisive resolutions in Section 8
6. No player names presented as ongoing truth without date qualifiers
7. Document ends with a clean section break, not mid-sentence
8. If approaching length limits, the truncation marker is present at a clean break

If any check fails, fix before finalizing.
```

---

## How to Run This (Recommended Workflow)

1. **Run 3 times** with the same input JSON. Set temperature to 0.3–0.5 (not 0) so you get genuine variance.

2. **Save outputs as** `synthesis_run1.md`, `synthesis_run2.md`, `synthesis_run3.md`.

3. **Run a merge pass** with this follow-up prompt:

```
Three independent syntheses of the same source material were produced (attached as run1, run2, run3). Produce a final merged synthesis using these rules:

1. For each section, identify the strongest rule formulation across all three runs and use that version.
2. Include any rule appearing in only one run if it satisfies the rule quality criteria (Forms A–D).
3. Resolve disagreements between runs by preferring the more specific/quantitative version.
4. Preserve the structural and tagging conventions from the original prompt.
5. Mark any rule that appears differently across runs with [VARIANCE: see runs] so I can audit.

Apply the same anti-truncation rules: end at a clean section break with a marker if you cannot complete.
```

4. **Audit the [VARIANCE] flags** — these are the rules where the model wasn't confident, and worth your direct review.

---

## Eval Rubric for Quick Run-Comparison

Score each run 1–5 on:
- **Tagging completeness** — every rule tagged?
- **Quantitative density** — count of numeric thresholds present
- **Conflict decisiveness** — were resolutions taken or punted?
- **Tautology rate** — count of vague/unfalsifiable rules
- **Coverage** — were all required sections included?
- **Truncation** — did it end cleanly?

A run scoring 4+ on all six is publishable as-is. Below that, run the merge pass.

---

## Notes on Your Specific Cache Structure (verified)

Your JSON caches are flat objects with source-filename keys and string values containing numbered rules separated by `\n\n`. Cache sizes you've used:
- flock_dynasty: 34 source videos, ~52 KB
- flock_redraft: 27 source videos, ~40 KB
- fse_dynasty: 57 source videos, ~97 KB
- fse_redraft (upcoming): ~55 source videos, expected ~95–110 KB

The fse_redraft batch is comparable in size to fse_dynasty, which already truncated. The two-part output strategy in the anti-truncation section is recommended for any cache over ~50 KB.
