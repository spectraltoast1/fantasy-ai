# Season Operating Calendar

**What this is:** the recurring yearly rhythm that keeps Gridiron current with the live NFL season — what
happens, in what order, and on what trigger, once the underlying machinery exists. It is deliberately
**high-level and evergreen**: it names the recurring jobs and when they fire, not the one-time work of
building them. Timing is anchored to **season events** (the offseason, the first game, each game week), never
to fixed calendar dates, so it holds year to year.

> This describes the **steady-state annual cadence**. The first-time work of standing each piece up is a
> separate effort and may not match this rhythm — see *Where the mechanics live* at the end. This doc is the
> *when and what*; the *how* lives with the machinery.

---

## The yearly loop

Freshness rests on three recurring jobs spaced across the year. They form a loop: each hands off to the next,
and the season's end feeds the following offseason.

### 1 · Offseason — re-tune the engine
**Trigger:** an offseason month, once the prior season has fully resolved and its stats have settled —
**target: February.** (By then the championship is played, the season's data is final and stable, and there
are months of lead time before the next season.)

Recalibrate the engine's constants against the season that just finished: ingest the resolved season, re-score
the engine against it, roll the evaluation window forward a year, and review what the data now favors. The
output is a **recommendation with options** that a person reviews and promotes. Some years this changes
constants; some years it confirms the current ones still hold. Either way, the calibration that will govern
the coming season is settled here — well before anything is built forward for the new year.

### 2 · Preseason — build and freeze the baseline
**Trigger:** the final days **before the season's first game.**

As the new season's draft market matures, collect the preseason inputs (average draft position and
projections) and build the engine's forward-looking basis — projection centers and confidence bands — for the
coming season, under the constants set in the offseason. Then **freeze a snapshot** of that basis. The frozen
snapshot is the season's official **preseason indicator**: the "where every player stood entering the year"
baseline the product reasons from until real games start generating signal.

Anchoring the freeze to the first game is deliberate — it's the last honest preseason moment: drafts are done
(the draft market is final), projections are current, and no in-season results have arrived to contaminate a
*preseason* reading. Freeze earlier and you miss late-camp and injury movement; freeze later and it is no
longer preseason.

### 3 · In-season — weekly refresh
**Trigger:** each game week, through the season.

A weekly job advances every connected league to the current week — pulling current rosters, matchups, and
results, running them through the engine, and moving the "as-of week" forward. Week by week, accumulating real
results sharpen the picture the frozen preseason baseline started from.

**Close of the loop:** when the season ends, its now-complete data becomes the input to the *next* offseason
re-tune, and the cycle repeats.

---

## At a glance

| Phase | Trigger (event-anchored) | What it produces |
|---|---|---|
| **Re-tune** | Offseason, after the season resolves — *target February* | The constants that govern the coming season (reviewed + promoted by a person) |
| **Preseason freeze** | The final days before the first NFL game | The frozen preseason baseline — the season's preseason indicator |
| **Weekly refresh** | Each in-season game week | Current-week reality, per league |

---

## What stays a human call

Two moments in the loop are judgment, not mechanics, and stay with a person: **promoting** any engine change
the offseason re-tune recommends, and **interpreting surprises** when the data does something unexpected. The
rest is operational — fire on the trigger, verify, move on.

## Where the mechanics live

This doc is the *when and what*, kept independent of any single build. The *how* is documented with the
machinery, and these are **references, not dependencies**:

- Offseason re-tune — the calibration pipeline and proposal digest: `projects/post-v1/annual-retune.md`.
- Preseason build + in-season weekly refresh — the substrate build and the refresh pipeline: the Project 2
  work under `projects/v1/`.

The cadence above is the steady-state ritual; it may differ from the one-time work of first standing each
piece up.
