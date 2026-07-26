# PRODUCT — What Gridiron Is

**Updated:** 2026-07-26

## The one-line thesis

**The unit of this product is the manager's *decision*, not the player.** Every other fantasy tool answers
"who's good?"; Gridiron answers "what should *you* do in *your* league, right now — or should you do
nothing?" Players are inputs to that decision.

## What it is

A season-long decision coach that knows your league and (over time) knows you. It sits on **commodity data**
— borrowed projections, usage stats, and your league context — runs a thin layer of shared engines that
judge decisions, and gets more personal the longer you use it. It starts as a **critic** of decisions (where
there's an answer key) and grows into a forward **advisor**.

Two components share one data layer:

- **The dashboard** — surfaces the relevant metrics and analytical views (value, projection bands, playoff
  odds, roster shape, opponent tendencies) in one place, so a manager can act on league-winning signal
  instead of anxiety and noise.
- **The AI advisor** — applies the strategy in plain language on top of the same data. It's a consultation,
  not automation: the manager sees the evidence and makes the call.

## The north star (do not lose this)

The goal is **confidence-honesty, not crystal-ball accuracy.** Fantasy weeks are near-random, so the win is
not "predict the score" — it's *knowing which advice to trust* and *showing uncertainty truthfully*. A read
that says "this is a coin-flip" when it is one is worth more than a confident wrong one. This is why the
engine is tuned to be honest (wider/lower) rather than to look impressive, and why the three design laws in
`CODING_BIBLE.md` are treated as correctness, not style.

## Scope

Redraft, skill positions (QB/RB/WR/TE), PPR and half-PPR. Everything else — other scoring, dynasty, other
platforms, DST/K — is deliberately out of the current scope and lives in `projects/post-v1/`.
