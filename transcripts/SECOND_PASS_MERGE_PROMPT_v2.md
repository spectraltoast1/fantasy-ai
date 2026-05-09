# Second Pass Merge Prompt v2.0

## Use Case

Variance reduction step. After running SECOND_PASS_PROMPT_v2.md three independent times against the same JSON cache (at temperature 0.3–0.5 to ensure genuine variation), this prompt merges those three outputs into a single best-of synthesis.

**Recommended model: Opus.** This task requires comparison and judgment across long documents — Sonnet can do it but Opus's reasoning premium pays off here, especially on conflict resolution.

**Why merge instead of "pick the best one":** With 200+ rules per output, "best holistic" is hard to judge reliably. Each run usually has a few rules sharper than the others' versions. Picking one means you throw out 2/3 of the model's good work. The merge captures the union of high-quality rules.

---

## THE PROMPT

```
You are merging three independent syntheses of the same fantasy football source material into a single best-of strategy guide. Your output replaces all three input documents and becomes the canonical strategy file.

# INPUTS

You will receive three markdown files: run1, run2, run3. Each was produced by an independent execution of the same Pass 2 synthesis prompt against the same source JSON cache. They have the same intended structure but will differ in:

- Which rules were extracted (some rules appear in only 1 or 2 of the 3 runs)
- How rules are phrased (same idea, different wording)
- Which conflicts were surfaced and how decisively they were resolved
- Quantitative thresholds (sometimes one run preserved a number the others abstracted away)
- Section coverage (one run may be more thorough on Calibration, another on Trade Strategy)

Treat each run as an independent expert opinion on the same source material. Your job is to combine them into a single document that is strictly better than any individual run.

# YOUR TASK

Produce a single merged markdown strategy file following the structural conventions of the original Pass 2 prompt (sections 1–8, applicability tags, conflict appendix, etc.). Do NOT add data-dependency tags ({needs: ...}) — that is Pass 3's job.

---

# MERGE DECISION RULES

## Rule appears in all 3 runs (consensus)

Take the strongest formulation. Strength is judged by:
1. **Specificity** — concrete thresholds, conditions, or actions over vague language
2. **Quantitative density** — versions that preserved source-material numbers
3. **Causal clarity** — versions that include the "because Y" explanation
4. **Imperative form** — versions that tell the advisor what to do, not just what is true

Example:
- Run 1: "Avoid drafting older WRs."
- Run 2: "Fade WRs aged 30+ in dynasty unless you're an immediate contender. [DYNASTY]"
- Run 3: "WRs over 30 are usually past their prime."
- **Merge:** Use run 2's version verbatim — most specific, has age threshold, has condition, has applicability tag.

## Rule appears in 2 of 3 runs

If the missing-from-one-run rule satisfies the rule quality criteria (Forms A/B/C/D from the Pass 2 prompt), include it. Two independent extractions is sufficient evidence that the rule is in the source material.

## Rule appears in only 1 of 3 runs

Include it ONLY if it satisfies ALL of:
1. It satisfies one of the rule quality forms (A/B/C/D)
2. It contains a specific quantitative threshold OR a clear causal explanation
3. It is not obviously contradicted by the other two runs

If it appears once and doesn't meet these criteria, omit it. Single-source rules are more likely to be model artifacts than missed insights — but high-quality singletons are worth preserving.

When you keep a single-source rule, append `[VARIANCE: appeared in 1 of 3 runs]` to the END of the rule (after applicability tags). The user will audit these.

## Rules contradict each other across runs

If runs disagree about a rule's content (e.g., one says "draft RBs by round 4," another says "wait until round 7"), this is a conflict in the SOURCE MATERIAL that the runs surfaced differently. Add an entry to the Conflicts appendix and resolve it decisively, just as Pass 2 was instructed to.

If the runs disagree about a rule's TAGGING (one tagged it [REDRAFT], another [DYNASTY]):
- Re-read the rule. Does the rule's content imply a format? If yes, use that tag.
- If genuinely ambiguous, prefer [BOTH] and explain in a brief inline note.

If the runs disagree about a rule's QUANTITATIVE THRESHOLD (one says "27+", another says "28+"):
- Check what the source material likely said. If you can't tell, prefer the more conservative threshold (the one that fires the rule less often).
- Append `[VARIANCE: thresholds differ across runs]` so the user can audit.

# SECTION-LEVEL HANDLING

For each section of the document:

1. **Identify the most complete version of the section across runs.** Use that as your base.
2. **Audit each rule in the base** against the same section in the other two runs. Apply the merge decision rules above.
3. **Add rules from the other runs' versions of the section** that don't appear in the base, applying the same merge decision rules.
4. **Cross-check section structure.** If one run organized RB rules under Player Evaluation while another put them under Draft Strategy, pick the more logical placement and consolidate.

If one run skipped a section entirely (or was truncated before reaching it):
- Use whichever runs reached that section.
- If no run reached the section, note `*Section not synthesized in any run; investigate Pass 2 truncation.*`

---

# CONFLICTS APPENDIX MERGE

Each input run has its own Conflicts appendix. Merge them:

1. **Combine all conflicts surfaced across all three runs.** Different runs may have noticed different conflicts.
2. **For each conflict, take the most decisive resolution across runs.** If one run punted ("depends on your league") and another took a position ("apply only in shallow leagues"), use the decisive version.
3. **If runs disagree on the resolution itself,** that's an interesting signal. Apply your own judgment — pick the resolution most consistent with the rest of the merged strategy file, OR present both with a note: `*Resolution variance: run X says A, run Y says B. The body of this strategy file follows resolution A.*`
4. **Eliminate duplicate conflicts** stated with different wording but the same underlying disagreement.

---

# VARIANCE FLAGGING — CRITICAL

For audit purposes, append `[VARIANCE]` markers to:

- Rules that appeared in only 1 of 3 runs but were retained ([VARIANCE: 1/3 runs])
- Rules where runs disagreed on threshold values ([VARIANCE: thresholds differ])
- Rules where runs disagreed on applicability tags ([VARIANCE: tag conflict])
- Conflict resolutions where runs took different positions ([VARIANCE: resolution differed])

These markers tell the user where the model was least confident. They should review these specifically before publishing the strategy file.

The variance count is itself a quality signal: if you flag fewer than 5–10 [VARIANCE] markers across the whole document, the input runs were probably too similar (set temperature higher next time). If you flag more than 50, the runs were too noisy (set temperature lower or improve the Pass 2 prompt).

---

# WHAT NOT TO DO

- Do NOT add rules that appear in NONE of the three input runs. Your job is to merge, not to expand. If you spot a missing rule, that's a Pass 2 prompt issue.
- Do NOT silently drop rules from majority-consensus content. Every rule that appeared in 2+ runs should appear in the merge unless it's genuinely contradicted by other rules.
- Do NOT change the structural conventions (sections, applicability tag format, etc.) — match the Pass 2 schema exactly.
- Do NOT add data-dependency tags ({needs: ...}). That is Pass 3's exclusive job.
- Do NOT collapse three rules into one if they're meaningfully distinct. If three runs each surfaced a different facet of "draft capital matters" (NFL draft round, historical hit rates, organizational signals), keep all three as separate rules.

---

# ANTI-TRUNCATION

The merged document will likely be longer than any individual run. Apply the same anti-truncation rules as Pass 2:
- If you cannot fit everything, end at a clean section break with the marker:
  `<!-- MERGE INCOMPLETE: stopped at end of Section X. Run a continuation merge starting at Section X+1. -->`
- For caches that produced 50KB+ Pass 2 outputs, plan to split the merge into two parts (Sections 1–4, then Sections 5–8) from the start.

---

# FINAL CHECK — RUN BEFORE OUTPUT

Before producing the final merged document, verify:

1. Every section present in 1+ input runs is present in the merge (or explicitly noted as missing across all runs)
2. Every rule from majority consensus (2+ runs) is included
3. [VARIANCE] markers are placed correctly on retained singletons and threshold disagreements
4. Conflict appendix is consolidated and decisive
5. No data-dependency tags ({needs: ...}) were added (Pass 3's job)
6. Document ends cleanly, with truncation marker if approaching length limits
7. Tag every rule with its applicability tag exactly as Pass 2 did
```

---

## How to use this prompt

1. **Run Pass 2 three times** against the same JSON cache at temperature 0.3–0.5 (NOT 0). Save outputs as `synthesis_run1.md`, `synthesis_run2.md`, `synthesis_run3.md`.

2. **Run this merge prompt** with all three as input. Use Opus.

3. **Audit the [VARIANCE] markers.** Each one is a place where the model wasn't confident. Read each, decide:
   - Keep as-is (the variance flag preserves transparency)
   - Strip the flag (you've reviewed and approved the rule)
   - Edit the rule (your judgment overrides the merge)
   - Strip the rule entirely (you've decided it's not worth keeping)

4. **Variance count is a calibration signal:**
   - <5 variance flags → input runs were too similar; raise temp next time (try 0.5–0.7)
   - 5–25 variance flags → healthy variance, merge is doing its job
   - 25+ variance flags → input runs were too noisy; lower temp (try 0.2) or improve Pass 2 prompt

5. **Then run Pass 3** to add data-dependency tags.

---

## Cost estimate (Opus)

- Three Pass 2 runs at Opus rates on a ~50KB cache: ~$15 ($5 per run)
- One merge pass with three ~80KB inputs: ~$8
- Total per strategy file: ~$23

For four strategy files (flock dynasty, flock redraft, fse dynasty, fse redraft): ~$92.

If that's too steep, mix models: Pass 2 runs on Sonnet (~$1.50 each), merge on Opus (~$8). Total per file: ~$13. Four files: ~$52. Still high but the merge step is where Opus's reasoning earns its premium most clearly — that's the spend I'd protect.
