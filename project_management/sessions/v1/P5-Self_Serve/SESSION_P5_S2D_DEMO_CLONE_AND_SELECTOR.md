# V1 · P5 · Session S2d — The demo clone, the RLS emit fix, then the season selector — a brief for Code

**Written 2026-08-11**, after S2a/S2b/S2c shipped and were audited. **Status:** ready to run ·
**Owner:** Code drives; Will makes one product call and picks the outage window.
**Companion:** `SESSION_P5_DEMO_LEAGUE_CLONE.md` (the original clone brief — no longer deferred; it holds
the anonymisation detail). **Prior:** `SESSION_P5_S2C_AUDIT.md`.

> **What this session does:** gives the demo its own identity so it stops being Will's real league, then
> takes the season selector out. It also carries the `--emit` RLS fix, because that needs a full `--load`
> and this is the other store-touching session — one planned outage instead of two.

## Why it cannot wait

**Gate A is ~2 weeks out.** The catalog groups a league's seasons into one lineage entry, and **the demo
IS LoRP 2025, which is Will's own lineage.** The moment his 2026 league is onboarded the two fuse into a
single switcher entry — and once Part 2 removes the season selector, the demo becomes unreachable from his
account entirely. Two individually-correct decisions colliding (S2b audit, F3).

Second reason, and it is about other people: **every anonymous visitor to surplusff.com is currently
looking at Will's real league, with ten real managers' Sleeper handles on a public page.** None of them
signed up for anything.

---

## The decision this session turns on — SETTLED, do not re-derive

**The clone is GENERATED, and it is a SERVE-LAYER artifact, not a corpus member.**

Three options were on the table and two are wrong:

- **Inserted into the database** — a script copies rows under a new id. **Wrong**, doubly so here:
  `--load` DROPs and rebuilds every table it names, so the clone survives exactly until the next full load
  and then the demo silently renders blank for every visitor. **Part 3 of this very session runs a
  `--load`.** This is `ros_player_band`'s lost RLS in a new costume — a hand-made artifact in a generated
  store.
- **Added to the corpus and regenerated** — a 32nd row in the demo slate, corpus rebuilt. **Also wrong.**
  The frozen corpus is what the **immutable L2 ledger** was derived from; regenerating it breaks the
  ledger's reproducibility, and standing instruction #6 says compute into a *different* path rather than
  overwrite a frozen one.
- **✅ A dedicated, deterministic generator** that **reads** the frozen LoRP 2025 slice and **writes a new
  artifact under its own path**, wired into the load so `--load` reproduces it. The frozen corpus is read,
  never rewritten. The clone is a new artifact beside it.

### The layer split — and `demo_manifest` is the trap

**The earlier note that "the corpus becomes 32 slices in every place that counts 31" overstated it. That
was the PM's; the layer distinction corrects it and makes this session smaller.**

| layer | count | sites |
|---|---|---|
| **corpus / engine — stays 31** | 31 | `demo_slate.csv` · **`demo_manifest.parquet`** · `compute_demo_slices.py` · `check_matchup_result.py` ("the 31 demo slices contain no tie") · the L2 ledger · B6's 31/31 |
| **serve — becomes 32** | 32 | the **`demo_manifest` TABLE** · `teams` / `season` / `standings` / `matchups` rows · `build_db.py`'s load span · `serve/MANIFEST.md`'s row count · the catalog |

**`demo_manifest` is a parquet AND a table, and they now hold different counts.** That name collision is
the single most likely place to get this wrong. The corpus parquet stays at 31 rows; `build_db` loads
those 31 **plus one row from the clone's own artifact** → 32 in the table. Do not append the clone to
`demo_manifest.parquet`.

`check_scoped_reload` compares parquet to DB: the clone has its own parquet from its own generator, so
parity holds for it exactly as it does for a corpus slice. `check_isolation`'s store-agreement check
compares `teams` ↔ the `demo_manifest` table — both serve-layer, both gain the 32nd consistently.

**Enumerate the count sites before changing any of them, and say in the report which layer each belongs
to.** A grep for "31" is a starting point, not the answer.

### Anonymise now — reversing "re-key now, anonymise later"

The earlier split said re-key here and anonymise later. **That was wrong: the privacy benefit is the
entire point and it does not land until the names change.** Deferring keeps ten real people's handles on
the public landing page for however long the deferral runs, and "we'll anonymise later" has a poor track
record. A deterministic name map is a dict inside a generator that is already being written.

**What genuinely stays deferred:** the **synthetic AI outlook** (`ros_synthesis` derived from real numbers
until P4 ships). That is real work, and **P4 retires it anyway** — which is why P4 moved ahead of P3.

---

## Order of work — the single `--load` has to serve both proofs

1. **Part 1 — the generator.** Deterministic; reads the frozen slice, writes the clone under its own path
   with its own `league_id` and `lineage_id`, anonymised. Hard-excluded from every engine component.
2. **Part 3 — the `--emit` RLS fix.** `--emit` emits `ALTER TABLE … ENABLE ROW LEVEL SECURITY` for every
   table it names, so an out-of-band property stops being destroyed by the next full load.
3. **The `--load`, once, with the generator already in place.** That single load proves **both**: RLS comes
   back after being dropped by hand, *and* the clone comes back from its generator rather than anyone's
   hand. **Loading before the generator exists proves nothing about reproducibility** — the ordering is the
   proof, not a preference.
4. **Part 2 — the season selector.** Frontend + catalog only, and only after the demo has its own lineage.
   `season` is not a SQL filter anywhere in the read layer. **League and week switchers stay.**
5. `DEMO_LEAGUE_ID` repoints at the clone — one value in `fly.toml`, which is why S2a made it config.

---

## Your part, Will

1. **One product call, before Code starts:** does the clone keep the name "League of Random People 2.0"
   and its team names, or get invented ones? It is the public landing page until you write a real one, so
   this is brand rather than plumbing. **Recommendation: invented, and boring** — a demo that looks like a
   specific real person's league invites "whose is this?", which is the question this session exists to
   stop. Manager names change either way; the *league* name is the open bit.
2. **Pick the outage window.** The `--load` DROPs and recreates the store, so **surplusff.com is down for
   its duration** — the first planned outage this project has taken. Short, and nobody is on the site, but
   pick a time rather than discover it.
3. **After the deploy, two checks.** Signed out, https://surplusff.com/ shows the demo and it is **not your
   league** — different name, different managers, no "you" highlight. And `/api/leagues` still returns
   exactly one league.

---

## The brief to paste to Code — S2d

```
Goal: V1 Project 5, Session S2d (projects/v1/P5_ACCOUNTS_SELF_SERVE_ONBOARDING.md) — give the demo its
own identity, fix the --emit RLS loss, then remove the season selector. Deadline is Gate A (~2 weeks):
the demo IS LoRP 2025, which shares a lineage with Will's real league, so once his 2026 league lands they
fuse into one switcher entry and removing the selector makes the demo unreachable from his account.

Read first: sessions/v1/P5-Self_Serve/SESSION_P5_S2D_DEMO_CLONE_AND_SELECTOR.md (this brief — the
generated-not-inserted decision at the top is not up for re-derivation), SESSION_P5_DEMO_LEAGUE_CLONE.md
(anonymisation detail), SESSION_P5_S2B_AUDIT.md (F3 is why this exists), context/CODING_BIBLE.md,
SESSION_GUIDE.md. Check the brief against observable reality before executing.

Build, IN THIS ORDER — the ordering is the proof, not a preference:

1. A deterministic GENERATOR for the clone. It READS the frozen LoRP 2025 slice and WRITES a new artifact
   under its OWN path — never rewriting the frozen corpus, which is what the immutable L2 ledger was
   derived from (standing instruction #6). New league_id, new lineage_id, anonymised manager and team
   names via a DETERMINISTIC map. Same week-5 freeze. Wired into the load so a --load REPRODUCES it.
   - SERVE-layer artifact, not a corpus member. corpus/engine stays 31 (demo_slate.csv,
     demo_manifest.PARQUET, compute_demo_slices, check_matchup_result, the L2 ledger, B6's 31/31); serve
     becomes 32 (the demo_manifest TABLE, teams/season/standings/matchups, build_db's load span,
     serve/MANIFEST.md, the catalog).
   - demo_manifest is BOTH a parquet and a table and they now hold different counts. Do NOT append the
     clone to demo_manifest.parquet; build_db loads the corpus's 31 PLUS one row from the clone's own
     artifact. That name collision is the most likely place to get this wrong.
   - ENUMERATE the count sites before changing any, and say in the report which layer each belongs to.
   - Hard-exclude the clone from every engine component.
   - Do NOT populate the AI outlook synthetically — deferred, and P4 retires it.

2. --emit must emit ALTER TABLE ... ENABLE ROW LEVEL SECURITY for every table it names, so an out-of-band
   property stops being destroyed by the next full load; ros_player_band then regains RLS.

3. Run --load ONCE, with the generator already in place, and take BOTH proofs off it: RLS comes back after
   being dropped by hand, AND the clone comes back from its generator. Loading before the generator exists
   proves nothing about reproducibility. THIS IS A PLANNED OUTAGE — the site is down while it runs; Will
   picks the window. Report how long it was down.

4. Repoint DEMO_LEAGUE_ID at the clone in fly.toml [env]. One value, per S2a's design.

5. ONLY THEN: remove the season selector from the frontend and flatten the catalog's lineage->seasons
   grouping. `season` is not a SQL filter anywhere in the read layer, so this is frontend + catalog and
   touches no data path. The league and week switchers STAY.

Prove it:
- A second --load reproduces the clone VALUE-identically (not byte-identically: polars' parquet writer is
  physically non-deterministic).
- The clone carries no real manager name, no real team name, no "you" highlight. Grep the served payloads
  for MY_USERNAME and for every real owner_name in LoRP 2025 — zero hits.
- RLS: drop it by hand, re-run --emit/--load, show it comes back. Prove it bites.
- Engine components still see 31; serve sees 32. Name which check covers which.
- check_isolation, check_ownership, check_harvest, check_weekly_refresh, check_scoped_reload all green
  after the load, and check_scoped_reload's parquet<->DB parity holds for the clone too.
- Signed out, /api/leagues returns exactly one league and it is the clone.

Scope guard — does NOT: touch the frozen corpus parquet or the L2 ledger; delete any of the 31 corpus
slices; populate the AI outlook; touch the connect flow, jobs table or worker; touch any engine constant;
change any read scoping (done, S2a/S2b). One exception, one line: while you are in reads.py, note that
_denied_reads is per-process and there are TWO Fly machines, so denied_reads() is a floor.

Follow SESSION_GUIDE.md: fresh worktree, <=3 commits, update STATUS.md + ARCHITECTURE.md + appendices per
§7 (replace, don't append), then close/merge/push. Touches application/api/* and application/frontend/* —
REDEPLOY and confirm live. Sweep .git for stale lock files at closedown.
```

## Definition of done

1. The clone exists with its own `league_id` and `lineage_id`, and **a second `--load` reproduces it
   value-identically** — generated, not inserted.
2. The frozen corpus parquet and the L2 ledger are untouched, demonstrated.
3. No real manager name, team name or "you" highlight survives in any served payload — grepped, not
   eyeballed.
4. RLS comes back after being dropped by hand, and the check bites.
5. Engine sees **31**, serve sees **32**, and the report names which check covers which.
6. `DEMO_LEAGUE_ID` points at the clone; signed-out `/api/leagues` returns exactly it.
7. The season selector is gone; league and week switchers remain; no data path changed.
8. Every existing check green after the load, including `check_scoped_reload` parity for the clone.
9. Merged, **redeployed**, confirmed live — and Will's two checks pass.

## Notes / gotchas

- **The `--load` is the first planned outage this project has taken.** Treat it as an event: Will picks the
  window, `context/OPERATIONS.md` gets a line about it, and the report says how long the site was down.
- **Part 2 must not start before Part 1 lands.** Removing the season selector while the demo still shares
  Will's lineage is exactly the bug this session exists to prevent, and it would stay invisible until his
  2026 league arrives.
- **The anonymisation map must be deterministic**, or a re-load produces different fake names and the
  value-identical proof fails for a reason that has nothing to do with the clone being correct.
