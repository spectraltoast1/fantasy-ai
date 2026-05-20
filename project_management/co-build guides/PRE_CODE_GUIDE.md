# Pre-Code Session Guide

A repeatable workflow for preparing and executing a Claude Code build.
This guide assumes STATUS.md and TECHNICAL_ARCHITECTURE.md are current.

---

## The Workflow Model

Claude Chat is the Product Manager. Claude Code is the Engineer.
The user is the CEO - they own the decisions and supervise deliverables from Claude Chat and Claude Code.

Each session is intentionally fresh. LLMs work better without accumulated
context drift. The document layer (STATUS, TECHNICAL_ARCHITECTURE) is what
carries continuity across sessions, taking precedence over any conversation history.

```
Your journal (personal tracking)
    ↓
STATUS.md (project state for Claude Chat)
TECHNICAL_ARCHITECTURE.md (engineering context for Claude Code)
    ↓
Claude Chat session → refined build prompt
    ↓
Claude Code session → plan → execute
    ↓
Post-code review → merge → update docs
```

---

## Step 1: Read the current STATUS.md

Before opening Claude Chat, read STATUS.md yourself. Know the answer to:

- What is the current state of the project?
- What is the stated next move?
- Does the next move still feel right, or has something changed?

Don't skip this. Coming in cold and relying entirely on Claude Chat to
orient you is the pattern that leads to drift.

---

## Step 2: Open a fresh Claude Chat session

Start a new conversation. Paste in the contents of both:
- STATUS.md
- TECHNICAL_ARCHITECTURE.md

Give Claude Chat the context upfront. A prompt like:

> "Here are my current project docs. I'd like to work through the next
> build step and produce a Claude Code prompt to execute it."

Then have the conversation. This is the refinement phase - the next move
in STATUS.md is a starting point, not a final spec. Use Claude Chat to:

- Pressure-test the approach before building
- Identify edge cases or design decisions that need resolving
- Confirm the right metrics, schema, or architecture for the task
- Surface anything that would cause Claude Code to make a bad assumption

The quality of the Code prompt depends on the quality of this conversation.
Don't rush it.

---

## Step 3: Produce the Claude Code prompt

At the end of the Chat session, produce a written prompt for Claude Code.
It should include:

- **What to build** - specific file(s), specific behavior
- **Technical constraints** - stack decisions, polars not pandas, etc.
- **Schema or structure requirements** - non-negotiable design decisions
- **What not to touch** - deprecated files, existing files to leave alone
- **Verification steps** - how to confirm it worked

The prompt should be self-contained. Claude Code gets the prompt plus
TECHNICAL_ARCHITECTURE.md as context - nothing else. If something isn't
in one of those two places, Claude Code doesn't know it.

---

## Step 4: Prepare the Claude Code session

Before starting Claude Code:

- Confirm your terminal / Claude Code desktop is pointed at the project root
- Confirm you're on the right branch (usually main)
- Confirm worktree is on or off per your preference
- Have the prompt ready to paste

---

## Step 5: Run in plan mode first

Claude Code has a plan mode - use it. Paste the prompt and let it produce
a plan before writing any code.

Review the plan carefully:
- Did it understand the task correctly?
- Are the file paths right?
- Does it reference the correct libraries and functions?
- Did it discover anything about the actual API or schema that differs
  from the prompt's assumptions? (This is valuable - let it run)
- Is there anything missing or unexpected?

Push back on the plan if something is wrong. It is much cheaper to
correct a plan than to correct written code.

Only approve the plan when you're satisfied.

---

## Step 6: Execute

Approve the plan and let Claude Code build. Monitor but don't interrupt
unless something goes clearly wrong.

When it finishes, review the after-action report before doing anything else:
- What did it actually build?
- Did anything get omitted or changed from the plan?
- Are the null rates and row counts sensible?
- Did it flag any API discoveries that differ from your assumptions?

Note anything that should feed back into TECHNICAL_ARCHITECTURE.md -
actual function names, schema details, join coverage rates. These are
institutional knowledge worth preserving.

---

## After this session

Follow the Post-Code Session Guide to review, merge, and update docs.

The final step of every session is updating STATUS.md with:
- What was just built (move it to "Today" section)
- The new next move

A stale STATUS.md is the fastest way to lose continuity across sessions.
