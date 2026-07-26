# Session 2.5 — Corpus Finalization (make the manifest harvest-ready)

**Hand this file to Claude Code as the session brief.**

**Type:** corpus selection + substrate + flagging · **Commits:** 3
**Reads first:** `CLAUDE.md` · `LEAGUE_CORPUS.md` · `SESSION_0_5_CORPUS_SELECTION.md` · `S1_6_FINDING_roster_reproducibility.md`
**Blocks:** Session 3 (the harvest). **This is the last step before it** — the harvest pulls + computes against whatever this session finalizes.
**No re-crawl:** everything here reads the **persisted** `corpus_discovery.parquet`. Zero Sleeper API calls for selection.

---

## Why this exists

The harvest is blocked on three unfinished pieces of the corpus, all known and all cheap. Get them right
here so Session 3 is a clean "pull leagues + compute the spine + gate," not a session that keeps stopping
to make selection decisions.

### 1. The generalization stratum is season-collapsed (the Session-1 flagged defect, now due)

Verified on the live manifest:

| | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|
| matched | 9 | 15 | 24 | 53 | 60 | 60 |
| **generalization** | **0** | **0** | **0** | **20** | **35** | **0** |

**All 55 generalization leagues are in 2023–24. Zero in 2025 — the *test* season.** The generalization
stratum's whole job is to prove the any-league code (superflex, divisions, custom scoring, exotic sizes)
survives real shapes — and it **cannot run that check on the split you certify against** if 2025 is empty.

### 2. 31 distinct custom scoring keys in those 55 leagues (a compute multiplier)

`projection_consensus` is scoring-scoped. Grading generalization reads needs substrate for **31 keys × 6
seasons**. Session 2 built substrate for **matched only** (ppr + half). **Cap the distinct custom keys at
~12**, preferring leagues that **share** a key — the generalization set exists to exercise **code paths**,
not to be representative, so coverage of *shapes* matters and volume does not.

### 3. Two-way players need flagging (1.7's commit-3 finding, decision already made)

1.7 quantified it: **~4–6 material two-way players/season** (Travis Hunter is the archetype — rostered as
WR, `nfl_stats` scores his CB line). Decision recorded in STATUS: **FLAG, do not exclude.** Their answer-key
points are cross-position, so the **scorer** must be able to slice them out — but they stay in the roster
substrate (the pinned-registry fix already makes them deterministic).

---

## Commit 1 — Re-select the generalization stratum + gate it

- Re-run `corpus/select.py`'s generalization pass against persisted discovery, with two new constraints:
  - **Per-season spread:** the generalization stratum must be **non-empty in every season of the split**,
    including **2025**. Target a rough balance (e.g. ≥6/season across 2021–2025; 2020 may be thin — report
    it, don't force it).
  - **Distinct-custom-key cap ≈ 12:** when choosing among candidates, **prefer leagues that reuse an
    already-selected scoring key**, so substrate compute stays bounded. Maximize *shape* coverage
    (superflex / divisions / exotic sizes / TE-premium) within that key budget.
- **Determinism:** the re-select must be reproducible — stable sort with a unique tie-break
  (`sleeper_player_id`/`league_id`), the same lesson as the `in_calibrated_pool` tie-break. Two runs →
  identical manifest.
- **Gate it (the missing tooth):** add to `check_corpus.py` —
  - generalization is **non-empty in every train/dev/test season** (hard fail if a certified season is empty
    — the exact defect that shipped),
  - distinct custom scoring keys in generalization **≤ the cap**,
  - matched hard-floor + never_tune checks stay.
- Report the final shape matrix (scoring × QB × divisions × size) so coverage is **visible, not assumed.**

## Commit 2 — Backfill the generalization substrate

- Extend `build_substrate.py` to the **capped generalization custom keys × 2020–2025** (consensus + band).
- **Leak-free ADP curve applies here too:** the band reads `holdout_{season}` (Session 2's fix) — verify the
  custom-key path honors it, don't assume.
- **Report the compute cost** (key count × seasons × rows). If the cap still yields an uncomfortable number,
  say so — better to tighten the cap now than to discover it mid-harvest.
- **Matched substrate is already done — do not recompute it.** Verify byte-identical if touched.

## Commit 3 — Two-way flag + docs

- Produce a **`corpus_two_way_flags`** reference (the ~4–6/season cross-position players): a player is
  flagged when the pinned-registry skill position conflicts with the `nfl_stats` position while rostered as
  skill. This is **detectable from the conflict the 1.7 join already computes** — reuse it, don't rebuild.
- Carry the flag where it's cheap (a boolean on the roster substrate / read output). **Do NOT deep-wire
  exclusion logic** — the flag exists so the **scorer** can slice; wiring that is the scorer's session.
  FLAG, not exclude (the recorded decision).
- Docs: `LEAGUE_CORPUS.md` (final stratum shape + the two-way flag), `STATUS.md`, `READ_BUILD_ORDER.md`.
  Mark the corpus **FINAL / harvest-ready**.

---

## Acceptance gates

1. `check_corpus` exits 0, **with the new generalization season-spread + key-cap checks**, and it **fails**
   on a deliberately season-collapsed generalization set (prove the new tooth bites — the anchor/tie-break
   pattern).
2. Generalization is **non-empty in 2025** and every other certified season.
3. Distinct custom scoring keys in generalization **≤ cap**; their substrate exists for all 6 seasons.
4. Re-select is **deterministic** (twice-run identical manifest).
5. `corpus_two_way_flags` produced; count is ~4–6/season and matches 1.7's quantification.
6. Matched stratum + its substrate **unchanged** (byte-identical if touched).

---

## Out of scope
- **The harvest itself** — pulling league rosters/matchups/transactions, computing the league-scoped spine.
  That's Session 3, and it should be scoped as its own (likely multi-part) session — the read spine ×
  ~300 leagues, with a 10k-Monte-Carlo bracket sim per league per as-of week, is too big for one 3-commit
  session. **Flag that in the closedown; don't start it here.**
- Deep-wiring two-way exclusion (scorer's job).
- Re-tuning any constant; the ledger; the scorer.

---

## Definition of done
- Manifest is **final**: matched unchanged; generalization spread across seasons (2025 non-empty),
  distinct-key-capped, shape-diverse.
- Generalization substrate built for all 6 seasons; leak-free curve honored.
- `check_corpus` green **with the new season-spread + key-cap teeth**, and proven to fail when they're
  violated.
- Two-way flag reference produced (~4–6/season); FLAG not exclude.
- Corpus marked harvest-ready; Session 3 scoped (not started) in the closedown.

---

> ## Standing instructions
> 1. A suspiciously clean zero is a bug until proven otherwise. *(A season with zero generalization leagues
>    is exactly this — now gated.)*
> 2. A refactor that changes a number is a bug — prove equivalence (matched substrate is byte-identical).
> 3. If the fix wants to touch `queries.js` or a view component, the seam has leaked.
> 4. Report, don't tune.
> 5. Deleting dead code must not move a live number.
> 6. A plausible explanation is not a diagnosis — name the mechanism, or write UNKNOWN and escalate.
> 7. **NEW — "the artifact exists" and "the consumer uses it" are two different gates.** *(Session 2 built
>    the holdout curves; nothing checked the band read them — the silent-anchor bug. Gate the property, not
>    just the file.)*
