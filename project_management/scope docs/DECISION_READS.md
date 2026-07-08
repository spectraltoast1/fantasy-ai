# Decision Reads — Build Spec

A spec for the signals the tool surfaces: **what I'm building, what's needed, how to make it.**
Four player reads (§1–4) and three league reads (§5–7). Each read frames a decision; the user
synthesizes — nothing is fused into a single "ultimate number." See "The full read set" at the end
for how they interlock.

---

## 1. Opportunity Read

**What it is:** a read on the chances a player has been given — shown as three separate axes
plus one companion metric, so the user synthesizes rather than trusts one fused number.

**Design principle:** don't collapse the axes. The *divergence* between them is the signal.
Worked example — a 3rd-down/goal-line RB: **high quality, low volume, steady trust, WAR ≈ 0.**
Illegible as one score ("replacement-level, move on"); legible as a profile (a TD-dependent
ceiling piece). The user decides if it fits their need.

| Component (what I'm building) | Data needed | How to make it | Notes / availability |
|---|---|---|---|
| **Quality** — how valuable the chances were | Play-by-play tagged with: target depth (air yards / aDOT), field position (red-zone, inside-10, end zone), carry yard line (goal-line / inside-5), down & distance. **Plus** a large historical PBP sample to set the weights. | Give each chance-type an expected-value weight = the historical average fantasy points that chance-type produces; sum a player's chances in value units. | Standard / clean in play-by-play. Weights are **empirical** (derived from history), not chosen by taste; re-derived under the league's scoring. |
| **Volume** — how many chances, as a share | Targets, carries, snap counts; **routes run**; team totals (plays, pass attempts, carries). | Raw counts, then convert to shares (target share, carry share, snap share). | Targets / carries / snaps are clean. **Routes run is the hard one** — coverage gaps in free data / behind paid charting. Fallback: snap share (cruder). |
| **Trust** — will the opportunity continue? | The **weekly time series** of Quality + Volume (no new stats). **Plus** roster / depth-chart status + injury/return news (for security). | Recency-weight the weekly series (decay rate tuned empirically); slope = direction (rising / steady / falling); variance = reliability; steady-vs-spiky ≈ security. | Decay rate tuned against "did the opportunity actually continue" — not taste. A **known upcoming** roster change (starter back from IR) is the one thing usage can't see — needs the injury/news feed. |
| **Point correlation** — *(companion metric, kept separate)* — do the chances become points? | Actual weekly fantasy points (box score, scored under league settings) + the Quality output (expected points). | Compare actual vs. expected over the weekly series. **Read against Quality:** low correlation + high quality = unlucky (bounce-back); low correlation + low quality = correctly cheap. | Box score is standard. Requires league scoring settings. Doubles as the validation that opportunity is worth trusting. |

**Cross-cutting input — league scoring settings:** feeds two places — it changes the Quality
weights (a target is worth more in PPR) and it's required to compute actual points for the
correlation. A config input, not a stats source.

**Data footprint (summary):** Quality + Volume come from play-by-play + participation data;
Trust is a weekly time-series transform of those *plus* a roster/injury feed; point correlation
adds actual scoring under the league's rules.

---

## 2. ROS Outcome Shape *(primary)*

**What it is:** three scores — **bull season, bear season, situation/security** — that **shift week
to week** as the season resolves. **Qualitative by nature** (unlike opportunity / WAR / weekly
spread, which are statistical). The user reads the combination; most players are a dial on all three.

**Design notes:**
- **Bull / bear** = the range of rest-of-season outcomes (good season / bad season), anchored to
  realistic **preseason limits** (a benchwarmer's bull case isn't an MVP season).
- **Situation / security** = how solid the ground under the bet is (health/recovery, competition +
  *its draft capital*, coaching/scheme change, surrounding talent, offense strength). **Absorbs
  "risk."** It is the **forward face of the Opportunity "Trust" axis**, and it explains *where the
  bull/bear range sits and which way it will break* — not a re-report of the gap. It's a fragility
  read, **not** a predicted catastrophe probability.
- **Show the reasoning with the score.** A 1-10 alone implies more precision than a qualitative
  judgment supports; the narrative "why" must ride alongside it (the grade is a summary, not a
  replacement — law 4).

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **Bull season** (upside) | Preseason: draft capital / ADP, high end of projection range, role path. In-season: opportunity trend (read #1), borrowed ROS projection, news. | Anchor a realistic preseason ceiling; update weekly toward the realized trajectory; decay the *unrealized* portion as weeks remaining shrink. |
| **Bear season** (downside) | Same sources, low end. | Anchor a realistic preseason floor; same weekly update + time decay. |
| **Situation / security** | Draft capital of the competition, depth chart, injury/recovery status, coaching & scheme changes, offseason personnel moves, offense strength. | Assess fragility of the bet from context; lower the risk as feared events fail to materialize (evidence = opportunity trend + news). Qualitative/contextual, not an event probability. |

**How the scores move (the dynamic):** preseason baseline = the prior; each week updates it via
(1) **evidence** — opportunity trend + news resolve the uncertainty — and (2) **time decay** — less
remaining season = less room for the preseason range to materialize, so it compresses toward the
realized path. Early season = wide, prior-driven; late season = narrow, evidence-driven.

**Where AI fits (+ guardrails):** three jobs — (1) interpret unstructured news/context into
structured situation signals; (2) write the short bull/bear narrative (the "why"); (3) roll the
narrative + signals into the 1-10 grades. Guardrails: **anchor the AI to the structured inputs**
(opportunity trend, draft capital, projection range) so grades aren't free-floating; **always show
the narrative with the grade**; **flag confidence** (qualitative + AI = least provable read — law 2).
This is the product's **AI-interpretation layer** — architecturally distinct from the polars/stats
transforms, dependent on the quantitative reads as anchors, so it likely lands **later** in the order.

**Data footprint:** mostly news, depth charts, draft data, roster/coaching moves — much set
preseason, updated occasionally; the messy/unstructured feed (which is exactly why AI is the right
tool). The quantitative anchor comes from the opportunity read.

---

## 3. Weekly Projection Spread *(secondary)*

**What it is:** a percentile band around a **borrowed** weekly projection — e.g., projected 10 →
**6 (25th) / 10 (50th) / 17 (75th)**. Quantitative/statistical. Displayed as breakpoints, not a bell
curve. "The projection is the center; we build the spread."

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **Center** | Borrowed weekly projection (consensus). | Use as the 50th percentile. |
| **Spread width** | Player's historical weekly variance; cross-source disagreement. | Wider band for volatile players / high source disagreement; tighter for steady ones. |
| **Skew** | Player archetype from opportunity (volume vs. big-play dependence). | Right-skew — bounded near 0, explosive upside; more skew for boom/bust deep threats, less for steady possession players. |

**Notes:** center is borrowed (law 3); you build only the band. **Validate by calibration** — over a
season, does the actual score land inside the 25–75 band ~50% of the time? Requires league scoring
settings for the actuals.

---

## 4. Value / VOR *(roster-management + trade read)*

**What it is:** two parallel "value over replacement" scores — **Production VOR** and **Market
VOR** — each anchored so the **waiver line = 0** and scaled by the pool spread, so both land on one
comparable, unit-free scale. Deliberately **Value, not true WAR** — no wins-conversion model.
Production VOR runs the add/drop layer; the **gap between the two** runs the trade layer.

**Core definitions:**
- **Replacement = the waiver line** — the best *actually available* (unrostered) player,
  league-specific. **Volatile by design:** if someone drops a stud, the line jumps and every score
  at that position moves. That's a feature, not a bug.
- **Production Value = rest-of-season production** (borrowed projection, per law 3) — *not* raw
  current points, and *not* fused with upside. Keeps VOR an honest production/floor read.
- **Upside/optionality is kept OUT of VOR** — it lives in the Outcome-Shape read (§2). A handcuff
  = ~0 Production VOR + high ROS-bull; you hold him on a free-roll bench spot, you don't let VOR tell
  you to drop him. **Bonus:** because upside is excluded from Production VOR, the Production-vs-Market
  gap *isolates* it — the market prices upside/hype, production doesn't, so the gap = the speculation
  premium.

**Normalization (settled):** anchor at waiver line = 0, divide by the **pool spread** (top rosterable
player − waiver line), *not* by the waiver line itself. Why: the waiver-line denominator collapses
toward 0 exactly where it matters (superflex QB with an empty cupboard; marginal players' market
value → 0), which blows up a divide-by-waiver ratio. Dividing by spread stays stable, degrades
gracefully (a tiny spread = a real "no separation at this position" signal, not an artifact), keeps
waiver = 0 and negative = dead weight, and puts Production and Market on the same comparable scale.
Cost: loses the literal "1.7× a replacement player" phrasing.

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **Production VOR** | Borrowed ROS projection (production value); roster / available status (to find the waiver line); league scoring & roster settings. | Value each player in ROS production; find the position/pool waiver line (best available); score = (player − waiver) / (top − waiver). Waiver = 0; negative = dead weight. |
| **Market VOR** | LeagueLogs market value (**redraft / format-matched profile**); roster / available status. | Same shape on market value: (player − market waiver) / (market top − market waiver). |
| **The gap** *(trade signal)* | Both VORs above, on the shared scale. | Market VOR ≫ Production VOR → market overvalues → **sell**. Production ≫ Market → undervalued → **buy / hold**. Size of the gap ≈ his upside / speculation premium. |

**Flex / superflex — reconciling positions:** projected points (under your scoring) is the common
currency that puts all positions on one ruler. Fill dedicated slots first, then fill flex slots with
the best remaining *flex-eligible* players by that shared scale; the flex-eligible positions then
share **one pooled waiver line** (best available flex-eligible player). **Superflex** drops QB into
that pool — and because every startable QB gets rostered, the free-agent QB is near-worthless, so
owning any real QB scores far above replacement (why QBs are gold in SF). Waiver-based replacement
produces this directly.

**Decision homes:** Production VOR → adds / drops (dead weight, upgrade targets, ~0-VOR free-roll
spots). The Production-vs-Market gap → trades (buy-low / sell-high). Start/sit is **not** here —
that's the weekly projection spread (§3).

**Open flag:** confirm the LeagueLogs profile is **redraft / format-matched**, not dynasty asset
value (dynasty bakes in age + multi-year outlook — noise for a redraft call).

---

## 5. Posture Evidence *(league read — the risk-appetite lens)*

**What it is:** two displayable proxies — **true rank** (roster strength) and **bracket math**
(standings + playoff odds + magic number) — shown **adjacent** so the user infers **posture +
urgency**. Posture itself is *not* computed or labeled; it's the synthesis the user reads off the
tension. This read is the **lens** that sets the risk appetite for how Outcome-Shape (§2) and VOR
(§4) get interpreted.

**Design notes:**
- **True rank = the team-level aggregation of the Value read (§4).** Sum the ROS production value of
  each team's *optimal lineup* (lineup-slot-aware). Record-independent — it measures how good the
  roster *is*, not how lucky it's been. No new engine; it rides on player Value + lineup rules.
- **The read is adjacency, not a label.** Strong roster + bad record → "buy, you're better than your
  record and time's short" (urgency). Weak roster + good record → "fragile, sell/hold." The manager
  synthesizes; you just place the two side by side.
- **Dynamic / time-sensitive** (like ROS): early season the odds are wide and low-confidence (hedge
  the language); late season they sharpen and urgency climbs. Same readiness treatment.
- **Integration point.** The dependency chain converges here: player Value → aggregates to true rank
  → feeds matchup win probs → drives the bracket sim → produces posture → flows *back down* as the
  risk-appetite lens on §2 and §4. Simple to display; sits on top of everything else.

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **True rank** | Player Value (ROS, §4); lineup-slot rules; rosters. | Sum each team's optimal-lineup ROS value; rank teams. Record-independent. |
| **Bracket math** *(Monte Carlo — chosen)* | Standings; remaining schedule (who plays whom); team **score distributions** (mean from starter value / true rank, spread from the team-level version of the weekly-spread read, §3); playoff structure + tiebreakers. | Per-matchup win probability from the score distributions; simulate the remaining season ~10k×; count playoff appearances → odds + "need X of next Y." Variance is essential — a stronger team still loses often; a deterministic favorite overstates the odds. |
| **Posture read** | True rank + bracket math, adjacent. | Display the tension; the user infers posture + urgency. *Not* a computed label. |

**Chosen:** Monte Carlo over expected-wins — it yields honest probabilities and captures variance
(the law-2 confidence signal), at the cost of being the deepest computation in the spec.

---

## 6. Positional Depth *(league read — the VOR read, re-sliced)*

**What it is:** your roster's strength **by position**, stacked against the league — surplus and
gaps. It's the Value/VOR read (§4) re-aggregated per position, not a new engine.

**Design notes:**
- **Measure relative to starting requirements, not raw totals.** Four startable-quality WRs when you
  start two-plus-flex = *tradeable surplus*; a replacement-level starter at a slot = a *gap*.
- **It's your VOR read, re-cut:** your ~0 and negative-VOR spots *are* your positional gaps; your
  high-VOR clusters *are* your trade capital. Compounds directly on §4.
- Benchmark choice: "vs. league average" is fine for the general read; for trade *targeting* you
  eventually want which *specific* managers hold the surplus you need — the handoff to §7.

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **Positional strength vs. league** | Player Value / VOR (§4); rosters; league starting requirements. | Aggregate rostered value by position, net of starting need + bench buffer; compare each position to the league distribution → surplus / gap. |

**Decision homes:** trade shape (what to deal from / target) and waiver / FAAB priorities.

---

## 7. Manager Dossiers *(league read — opponent modeling)*

**What it is:** a per-opponent **behavioral profile** — waiver/FAAB aggression, trade behavior,
positional lean, roster-construction habits. The only read about *other people*, and the **second
home for the AI-interpretation pattern** from ROS situation (§2).

**Design notes:**
- **Built from transaction history** (Sleeper: waivers, FAAB, trades, adds/drops, lineup moves),
  synthesized by AI into a short profile.
- **Confidence-gate hard** — thin history stereotypes people (three RB adds = a tendency, or just
  circumstance?). Frame as **tendencies, not verdicts** (laws 2 + 4).
- **Updates slowly** — behavior accumulates over a season, unlike the fast player reads.
- **Doubles as the "model of YOU" infrastructure** — the same engine pointed inward later. Building
  it well is quietly building the endgame.

| Component (what I'm building) | Data needed | How to make it |
|---|---|---|
| **Manager behavioral profile** | Sleeper transaction history (waivers, FAAB, trades, adds/drops, lineup decisions); time span for confidence. | AI synthesis over the transaction record → short profile of tendencies; gate language on sample size; describe patterns, don't box people in. |

**Decision homes:** trade targeting & negotiation (what a manager values → what they'll accept/offer)
and waiver competition (who else is likely bidding on your target).

---

## The full read set — how they fit together

**Player reads (per player):**
1. **Opportunity** — quality / volume / trust of the chances he's getting (+ point-correlation companion). *Descriptive, backward, owned.*
2. **ROS Outcome Shape** — bull / bear / situation, dynamic, qualitative, AI-assisted. *Forward; borrow the center, build the spread.*
3. **Weekly Projection Spread** — percentile band around a borrowed weekly projection. *Quantitative.*
4. **Value / VOR** — production VOR + market VOR over the waiver line; the gap = trade signal. *Forward; borrows the projection.*

**League reads (per team / league):**
5. **Posture Evidence** — true rank + bracket-math (Monte Carlo) shown adjacent → posture + urgency. *The risk-appetite lens.*
6. **Positional Depth** — the VOR read re-sliced by position vs. league.
7. **Manager Dossiers** — AI behavioral profiles of opponents.

**The spine:** opportunity is the descriptive base you can build with no projections. The **borrowed
projection substrate** (law 3) is the hinge that unlocks outcome shape, weekly spread, value/VOR, and
the bracket sim. **Posture** is the integration point — player Value aggregates up into it, and it
flows back down as the lens that sets risk appetite on every other read. **AI** shows up in exactly
two places (ROS situation, manager dossiers) — the qualitative reads — always confidence-gated, always
showing its reasoning, never fused into a single number.

*Open flags carried forward:* ROS dynamic-update model + 1-10 precision display (§2); redraft/
format-matched market source (§4).*
