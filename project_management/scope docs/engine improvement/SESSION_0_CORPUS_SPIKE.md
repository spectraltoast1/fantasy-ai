# Session 0 — Corpus Spike (throwaway)

**Hand this file to Claude Code as the session brief.**

**Type:** de-risking spike · **Merges:** one markdown findings doc, **zero code**
**Time box:** one session · **Commits:** 1 (the findings doc only)
**Context to read first:** `CLAUDE.md`, `project_management/scope docs/LEAGUE_CORPUS.md`

---

## Why this exists (read this before writing any code)

The League Corpus plan proposes harvesting **completed Sleeper league-SEASONS** as an offline answer key,
then refactoring the entire data layer (`league_id` + `scoring_key` keying, partitioning, splitting
`ros_outcome_shape`) to hold it.

> **Note the unit — it matters.** The corpus row is a **(league_id, season) pair**, *not* a league with a
> long history. Leagues churn; five-season continuous leagues are uncommon and you should not go looking
> for them. **A league that existed only in 2023 is a perfectly good corpus row.** Nothing downstream
> needs continuity, and §7 explicitly *wants* different leagues. **Managers are the durable entity — crawl
> them, not leagues** (probe D).

**That refactor is large and hard to unwind. The corpus plan rests on assumptions that have not been
verified.** Exactly one has been checked (Sleeper serves 2021 weekly projections — confirmed, a full
populated `pts_ppr` board).

**If any of the probes below comes back negative, the plan changes — and you would have refactored the
data layer for a corpus that doesn't exist.**

This session's only job is to answer the open questions with real API responses. **It produces
findings, not features.**

---

## Hard rules

1. **No `data_layer` involvement.** Do NOT route this through `data_layer.py`, do NOT add entities, do
   NOT add fetchers. The CLAUDE.md "all I/O through data_layer" rule is suspended *because this code is
   deleted at the end of the session.* Don't be a good citizen here; be a fast one.
2. **Not part of the `application` package.** Standalone script(s) in a scratch dir (e.g. `spike/`),
   plain `requests` + `json`, write raw findings to a temp dir.
3. **Nothing is refactored. Nothing is optimised. No transform is touched.**
4. **The branch is deleted at the end.** The ONLY thing that merges is
   `project_management/LLM context/SPIKE_CORPUS_FINDINGS.md`.
5. **Be polite to Sleeper.** Sleep ~100ms between calls; this is a read-only crawl of public endpoints.
   Count every call.
6. **Report what you found, not what you hoped.** A negative result here is a *success* — it saves a
   week of misdirected refactor. Do not paper over a gap.

---

## Endpoints

```
league object      GET https://api.sleeper.app/v1/league/{league_id}
                       → scoring_settings, roster_positions, settings{num_teams, divisions,
                         playoff_week_start, type, ...}, previous_league_id, season
rosters            GET https://api.sleeper.app/v1/league/{league_id}/rosters      → owner_id, players[]
users              GET https://api.sleeper.app/v1/league/{league_id}/users
matchups           GET https://api.sleeper.app/v1/league/{league_id}/matchups/{week}
transactions       GET https://api.sleeper.app/v1/league/{league_id}/transactions/{week}
a user's leagues   GET https://api.sleeper.app/v1/user/{user_id}/leagues/nfl/{season}
projections        GET https://api.sleeper.com/projections/nfl/{season}/{week}
                       ?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE
                       &order_by=pts_ppr
```

Seed: `config.SLEEPER_LEAGUE_ID` (your 2025 league).

---

## The probes

Run them in this order. **The three that can kill or resize the plan are D (supply + shape), F (old player
IDs), and H (abandonment filter). Do not skip them, and do not soften a negative result.**

### A — How far back do projections go?
For **each season 2019…2025**, fetch week 5 projections.
**Record:** row count, count with a non-null `pts_ppr`, top-3 names+values, HTTP status.
**Decides:** the corpus window. 2020 available ⇒ six seasons and a perfect match to your existing
`nfl_stats` backfill (2020–2024 + 2025).

### B — Do historical **transactions** come back?
For **one league-season per available NFL year** (they need not be the same league), fetch transactions
for weeks 1–17.
**Record, per season:** total rows; counts by `type` (`waiver` / `free_agent` / `trade`); how many
waiver rows carry a **FAAB bid** (`settings.waiver_bid`); how many carry `status: complete`.
**Decides: whether §7 has a corpus at all.** `compute_manager_features` needs completed waivers with
bids. If 2021–2023 transactions are empty or bid-less, **§7's corpus story dies** and the manager
dossiers stay a forward-only, thin read.

### C — `previous_league_id`: **measure it, don't depend on it**
*(Demoted. Leagues churn; multi-season chains are known to be uncommon. This is now a nice-to-have, not
the harvest spine — see D.)*

From the seed league, follow `previous_league_id` as far as it goes.
**Record:** the chain of `(season, league_id)`; where it terminates; whether `settings` /
`scoring_settings` are intact on the old objects. Then, across every league found in probe D, report
**what fraction have a `previous_league_id` at all**, and the distribution of chain lengths.
**Decides:** nothing load-bearing. It quantifies how much *free* multi-season depth exists. **Expect it
to be low. That's fine.**

### D — ⚠️ **THE HARVEST MECHANIC: crawl MANAGERS, not leagues**

> **The unit of the corpus is the league-SEASON, not the league.** A league that existed only in 2023 is
> a perfectly good corpus row. Nothing downstream needs continuity — and **§7 explicitly *wants*
> different leagues.** Leagues churn; **managers persist.** The manager is the durable entity, and
> `_manager_leagues()` already returns exactly the right thing.

BFS from the seed to **depth 2**, keyed on managers:

```
seed league → /rosters → owner_id[]
  → _manager_leagues(owner_id, season=2025, seasons_back=4|5)   ← already built; returns per-SEASON
  → every (league_id, season) pair found is a CORPUS CANDIDATE
  → classify_league() each one                                   ← already built; free, no extra call
  → dedupe on (league_id, season) → recurse once on new managers
```

Use the **existing** `_manager.classify_league()` — the `/user/.../leagues` payload carries
`scoring_settings` + `roster_positions` + `settings`, so classification costs **zero extra API calls**.

**Record — two tables.**

**(1) Supply by NFL season** *(the independence axis that actually matters)*

| NFL season | distinct league-seasons found | distinct managers |
|---|---|---|
| 2021 | | |
| 2022 | | |
| … | | |
| 2025 | | |

**(2) Shape matrix** (counts of league-seasons)

| | 1QB | superflex |
|---|---|---|
| **PPR** | | |
| **half** | | |
| **std** | | |
| **custom / TE-premium** | | |

Plus: `num_teams` distribution · how many have `settings.divisions` set · redraft vs keeper vs dynasty ·
totals.

**Decides two things:**
- **Supply.** Can you reach ~10 *usable* league-seasons **per NFL season** for 2021–2025? (Expect the
  crawl to be *abundant* — depth-1 alone is likely 100+ league-seasons. **Discovery is probably not the
  constraint; probe H is.**) **Expect a recency skew** — Sleeper adoption grew over the window, so
  2021–22 will be thinner and deader than 2024–25. Report the skew, don't hide it.
- **Shape coverage.** Does your neighbourhood contain the shapes that would actually *test* the
  any-league code (`position_pools` superflex, `_seed_table` divisions, `_scoring` custom) — all of which
  are **currently gated on synthetic configs only**? If depth-2 is 100% full-PPR 1QB 10-team, the "corpus
  tests the any-league work" claim in `LEAGUE_CORPUS.md` is **false** and must be struck.

### E — Are old **matchups** complete?
For one **foreign** league-season (not yours) at the oldest year you can find, fetch matchups for
weeks 1–17.
**Record:** rows/week; presence and non-emptiness of `matchup_id`, `starters`, `starters_points`,
`players_points`, `points`.
**Decides:** whether §5 (bracket odds, true rank) and `compute_team_leakage` have a historical answer
key. `optimal_lineup` needs `starters` + per-player points.

### F — **⚠️ THE BIG ONE: do old player IDs still resolve?**
The corpus joins **Sleeper rosters (e.g. 2021)** to **nflreadpy stats (2021)** through
`cache/player_id_map.parquet` and the Sleeper player registry — both of which are built from
**current-state** data.

**A player who retired in 2022 may not resolve.** If a meaningful share of 2021 rosters can't be mapped
to a position or a `gsis_id`, `join_nfl_sleeper_weekly` will dump them into `remainders` and **every
league-scoped read silently loses roster mass** — VOR pools, optimal lineups, true rank, depth. This
would not throw an error. It would just be quietly wrong.

**Do:** take every `player_id` on the rosters of the **oldest foreign league-season you can find**.
Resolve each against (a) the current Sleeper registry (`/players/nfl` — or the existing cached parquet)
and (b) the existing `player_id_map`.
**Record:** total players; % resolving to a **position**; % resolving to a **gsis_id**; and **list the
unresolved ones by name** if the registry has a name for them.
**Decides:** whether the corpus needs a historical-ID reconciliation step **before** any of it is
trustworthy. This is the assumption most likely to be false and the one that breaks things silently.

### G — Cost
Instrument every probe. **Record:** total API calls and wall-clock to fully harvest **one league-season**
(league object + rosters + 17 wks matchups + 17 wks transactions). Extrapolate to 50 and 100
league-seasons.
**Decides:** whether the harvest is minutes, hours, or overnight — and whether throttling needs real
thought.

### H — ⚠️ **THE ABANDONMENT FILTER: what fraction of league-seasons are actually USABLE?**

> **Dead leagues are the *best* corpus material** — fully resolved, no ambiguity, nobody using them.
> **Half-dead ones will silently poison it.** Leagues die *mid-season*: managers stop setting lineups,
> teams go inactive, the commissioner bails in week 9. A team fielding an empty lineup in week 10 wrecks
> `optimal_lineup`, wrecks the matchup outcome, wrecks true rank and leakage — **and throws no error.**
> Same silent-failure class as probe F.

**Take a random sample of ~15 league-seasons from probe D** (spread across NFL seasons, including some
from defunct leagues). For each, apply a draft inclusion filter and record pass/fail **with the reason**:

| Check | Fails if |
|---|---|
| **Season complete** | any regular-season week missing matchups, or all-zero points |
| **No abandonment** | any team with ≥3 weeks of empty/zero `starters` after week 2 |
| **Roster integrity** | `len(rosters) != settings.num_teams`, or teams with far-under-full rosters |
| **Transactions present** | zero transactions all season *(⇒ exclude from §7 only, not from §5/§6)* |
| **ID resolution** | skill-player resolution below the probe-F threshold |

**Record:** the **pass rate**, and a breakdown of *why* the failures failed. Tune the thresholds if the
data says they're wrong — and say so.

**Decides: THE SIZE OF THE CORPUS.** This is now the binding constraint, not discovery. If the crawl
finds 150 league-seasons and only 40% survive the filter, the corpus is ~60 — still transformative.
If it's 10%, the plan needs rethinking. **Nobody currently knows this number, and everything downstream
is sized by it.**

---

## Deliverable

**`project_management/LLM context/SPIKE_CORPUS_FINDINGS.md`** — the only file that merges.

Structure it as:

1. **Verdict up front** — one of:
   - ✅ *Corpus viable as specced* — proceed to the L0 keying sessions.
   - ⚠️ *Viable with a caveat* — name it, and name what changes in `LEAGUE_CORPUS.md`.
   - ❌ *Not viable* — name the blocking probe and what the corpus becomes instead.
2. **THE SIZING NUMBER** — the single most important output of this session:
   > *"Depth-2 crawl found **N** league-seasons across NFL seasons 20XX–2025. **M** (**P%**) pass the
   > inclusion filter. Usable corpus ≈ **M** league-seasons ≈ **T** team-seasons and **X** matchups —
   > versus **10** and **75** today."*
3. **Probe-by-probe findings** — A–H, with **real numbers and real API responses**, not prose summaries.
   Paste the actual counts.
4. **What this changes in `LEAGUE_CORPUS.md`** — a specific, itemised diff of claims that are now
   confirmed, wrong, or need caveating. Do **not** edit that doc in this session; just list the deltas.
5. **Surprises** — anything the probes didn't ask about that you noticed and matters.

---

## Explicitly out of scope

- `league_id` / `scoring_key` keying — that's Session 1, and it depends on this
- Any change to `data_layer`, any transform, any fetcher, any gate
- Building an actual harvester
- Any parquet written anywhere the project will keep
- Editing `LEAGUE_CORPUS.md`, `IMPROVEMENT_LOOP.md`, `PILOT_2026.md` or `STATUS.md`
  *(the findings doc drives those edits later, in the PM loop, not here)*

---

## Definition of done

- All **eight** probes (A–H) run against the live API, with recorded numbers.
- **The sizing number is stated** (how many usable league-seasons the crawl actually yields).
- `SPIKE_CORPUS_FINDINGS.md` written, verdict stated, `LEAGUE_CORPUS.md` deltas itemised.
- **The spike code is deleted and the branch is not merged** — only the findings doc lands.
