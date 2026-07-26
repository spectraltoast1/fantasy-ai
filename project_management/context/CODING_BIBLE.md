# The Coding Bible — Rules for Coding Agents

**What this is:** the non-negotiable rules any coding agent (Claude Code or otherwise) must follow when
writing code on fantasy-ai. Read this *before* writing code. If a change would break a rule here, stop and
raise it — don't work around it. These are stable; they change only by an explicit decision recorded in
`STATUS.md`.

*(Draft — distilled from the Technical Principles, the three design laws, and the client/server seam
invariants. Edit down to the set you want to enforce.)*

---

## 1. The data seams are sacred

- **Every Python read/write goes through `data_layer.py`.** It is the only code that knows where data
  lives. No transform, no endpoint, no script reads a file path or a table directly.
- **Every client read goes through `queries.js`.** It is the single client-side data seam (now an API
  client). View components (`Players.jsx`, `Teams.jsx`, …) never fetch, never hold a URL, never do data
  access — they receive shaped data and render it. If a view knows where data comes from, the seam has
  leaked.
- **One fetcher per source.** No combined fetchers. Each external source (Sleeper, nflreadpy, LeagueLogs,
  news) has exactly one fetcher.
- **One data layer, no parallel paths.** The dashboard and any AI/advisor read the same store. Never build a
  second way to get the same fact.

## 2. Build with SOLID and purity

- **Transforms are pure functions with injected constants.** No hidden state, no global reads inside a
  transform. `compute()` is the composition root that wires them.
- **Single source of truth per fact.** A number is defined and computed in one place. No duplicating a
  calculation across docs or modules.
- **polars only — no pandas.** All dataframe work is polars.
- **Pre-filter before any AI call.** Never send raw logs or full tables to a model; select and shape first.
  Cost and honesty both depend on this.

## 3. The three design laws (the product's integrity)

These are *why* the product can be trusted. Violating one is a correctness bug, not a style choice.

- **Law 1 — Grade process, not outcome.** Never grade a read against what actually happened at decision
  time. A good decision that got a bad result is not an error. Structurally: no grade/verdict/resolution
  column exists in a prediction at the time it's made.
- **Law 2 — Speak only when confident.** The confidence signal must be honest — e.g. a band's width *is* its
  confidence, and a missing signal is reported as null, never fabricated as 0. Surface uncertainty truthfully;
  when a read is a coin-flip, say so.
- **Law 3 — Borrow the substrate, don't build a projection model.** Ingest commodity projections, rankings,
  and stats. We build only the thin decision layer (VOR, bands, ranks) on top. We never build our own points
  projection.

## 4. Scope guardrails

- **Skill positions only** (QB / RB / WR / TE). DST and K are out.
- **V1 scope is redraft, PPR/half, 1QB or superflex.** Anything out of scope (dynasty, un-scoreable custom
  scoring, exotic shapes) must be **declined gracefully**, never silently mis-handled.
- **Never silently mis-score.** If the engine can't faithfully score something, it raises — it does not guess.

## 5. Change safety

- **One architectural change at a time.** The discipline that keeps every change a swap, not a rewrite.
- **Parity guard on production-touching changes.** A change to a shared/production path must preserve
  existing behavior byte-for-byte unless it is *intentionally* changing what's shown — and then the change is
  explicit and verified.
- **Verify numbers, don't trust "it runs."** Especially across SQL dialects — reproduce the values, don't
  assume equivalence.
- **Stay auth-ready.** Don't bake in assumptions like "no auth," "single league," or "the whole dataset fits
  in the browser."

## 6. Auditability & session hygiene

- **Rules and strategy live in auditable markdown**, not vector-embedded — a human must be able to read and
  check them.
- **Update `STATUS.md` at the end of a session.** State is reloaded from docs, not chat history.
- **Follow the session lifecycle** (`SESSION_GUIDE.md`): fresh worktree → setup → 3-commit cap → update
  STATUS → close/merge. One brief per session.
- **Keep the seams clean.** If a fix wants to sprawl a view into data access, or a transform into I/O, stop
  and reconsider — that's the signal something's wrong.

## 7. Keeping STATUS & ARCHITECTURE current (the anti-bloat rule)

These two docs describe **now** — not the journey to now. They grew to ~1,900 / ~1,200 lines by append-only
accretion; this rule exists to prevent that permanently. STATUS is a snapshot, not a logbook; ARCHITECTURE
describes the system as it is today. To update either, you *replace* what changed and remove what's no longer
true — you never append a dated entry on top of stale state.

**When you remove something from the SOT, it's one of three moves — know which one:**

- **Condense** — the state is still true but stated at length → rewrite it tighter. The fact stays in the SOT,
  just shorter. (The default for still-current content.)
- **Delete** — the content is no longer true, is superseded, or is the blow-by-blow of *how* today's state was
  reached → remove it outright. History is not current state; the session doc under `sessions/<project>/`
  already holds that record.
- **Move to an appendix** — the content is still *necessary* but too deep for the load-first SOT → cut it from
  STATUS/ARCHITECTURE and put it in a scoped appendix under `context/appendices/`, linked by name
  (`→ see appendix: X`).

**The test that decides delete vs. appendix:** *"Can I remove this without losing information a future agent
would actually need?"*

- **Yes → delete it.** It was history, redundancy, or dead state.
- **No → it goes to an appendix.** The appendix is the safety net: nothing necessary is ever lost, and nothing
  non-essential is left cluttering the SOT. **If you can't cleanly delete it, that is the signal it belongs in
  an appendix — not that it stays in STATUS.**

**Appendices are scoped.** An appendix is almost always *about* one project or one scope/feature — the scoring
mechanism, the ledger, the onboarding flow, a specific engine read. Name it for what it's about, keep it
self-contained, and let the SOT link to it, so an agent pulls exactly the context its task needs and nothing
more. **Pushing content out can mean either folding it into an existing scoped appendix or creating a new
one** — whichever keeps the set coherent; don't duplicate a topic across two appendices.

**Keep the SOT skimmable.** A new agent should orient from STATUS + ARCHITECTURE in ~2 minutes. Length is a
smell: past a few hundred lines, condense and push detail out — before it accretes, not after.

**Net effect of a session on the SOT:** STATUS reflects the new current state; the session's narrative + audit
live in `sessions/<project>/`; durable-but-deep rationale lands in a scoped appendix. STATUS and ARCHITECTURE
do **not** grow as a side effect of doing work. **A session that leaves STATUS longer than it found it,
without deleting something, did it wrong.**
