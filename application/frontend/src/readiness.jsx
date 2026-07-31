import React from 'react';

// Per-panel readiness gate (Phase 1 part 4). A single home for one rule: "does this
// panel have enough data to be meaningful yet?" — so trend reads degrade cleanly
// early in a season and language calibrates to the sample, rather than every panel
// hard-coding its own week check. Pure logic + the wrapper/fallback live together
// because they're one cohesive concern (presentational, not data access — so it
// stays out of queries.js).
//
// Every panel keys off ONE clock: `weeksOfData` below. It counts weeks that actually
// have results, not weeks that happen to be loaded — those diverge exactly when it
// matters, because a projections-only week is joined with zero-filled points and would
// otherwise report "1 week of data" for a league that has played nothing.

export const REGIME = {
  // ready at roster lock — about who's on the team, not accumulated performance
  STRUCTURAL: 'structural',
  // usable from week 1, confidence grows with weeks (a point estimate that firms up)
  POINT_IN_TIME: 'point-in-time',
  // needs a few weeks of shape before it means anything (slopes, trends)
  TREND: 'trend',
};

/**
 * The one "how early are we" number: how many weeks of REAL RESULTS this league has,
 * as of the week being viewed. Every surface keys off this rather than inventing its
 * own threshold, and nothing keys off the selected week ordinal — travelling back to
 * Week 1 of a finished season is genuinely a 1-week-of-data view, which is what makes
 * the replay a faithful rehearsal of live Week 1.
 *
 * `played` comes from the server (weeks where somebody actually scored). Absent it we
 * return 0 rather than guessing: unknown depth is shallow depth, never deep.
 */
export function weeksOfData(played, asOfWeek) {
  if (!Array.isArray(played)) return 0;
  const cut = Number.isFinite(asOfWeek) ? asOfWeek : Infinity;
  return played.filter((w) => w <= cut).length;
}

// Weeks of data at which each regime starts being usable (`building`) and becomes
// fully trustworthy (`ready`). Below `building` it's "too early" and the panel hands
// off to its fallback slot. Deliberately conservative on trend — a half-life-2wk
// slope over one or two games is noise. These are the league's weeks-of-results clock,
// not per-player games (the player signal does its own per-player sample gating).
const BANDS = {
  [REGIME.STRUCTURAL]: { building: 0, ready: 0 },
  [REGIME.POINT_IN_TIME]: { building: 1, ready: 2 },
  [REGIME.TREND]: { building: 3, ready: 4 },
};

/**
 * The readiness verdict for a panel, given its regime and weeks of data elapsed.
 * Pure and side-effect-free so it's trivially testable and has one home.
 * @returns {{state: 'ready'|'building'|'tooEarly', weeks: number, needed: number}}
 */
export function assessReadiness(regime, weeks) {
  const band = BANDS[regime] ?? BANDS[REGIME.POINT_IN_TIME];
  const w = Number.isFinite(weeks) ? weeks : 0;
  if (w >= band.ready) return { state: 'ready', weeks: w, needed: band.building };
  if (w >= band.building) return { state: 'building', weeks: w, needed: band.building };
  return { state: 'tooEarly', weeks: w, needed: band.building };
}

/**
 * Wrap a panel's content in the READINESS gate: too thin for its regime → the "too early" fallback
 * slot; usable-but-early → the content with a subtle low-confidence note above it.
 *
 * Readiness only. Catalog gating ("is this read meaningful for THIS league") lives in `marketOn` +
 * `MarketOff`/`PanelOff`, because it turns out to be per-ELEMENT, not per-block — it hides a table
 * column, one half of a toggle, a sparkline — which a wrap-children component can't express. `Gate`
 * used to carry a `panel`/`panels` arm for it; no call site ever passed them (S3's commit message
 * claimed otherwise and was wrong), so it's removed rather than left as a third idiom.
 */
export function Gate({ regime, weeks, label, fallback, children }) {
  const r = assessReadiness(regime, weeks);
  if (r.state === 'tooEarly') {
    return <TooEarly label={label} weeks={r.weeks} needed={r.needed}>{fallback}</TooEarly>;
  }
  return (
    <>
      {r.state === 'building' && <BuildingNote weeks={r.weeks} />}
      {children}
    </>
  );
}

// The slot a panel shows when the catalog says it isn't available for the selected league (e.g.
// market isn't computed outside the live slice). Honest "not here" rather than an empty chart.
// `note` overrides the default sentence when a panel is off for a reason worth naming.
export function PanelOff({ label, note, children }) {
  if (children) return <div className="ready-slot">{children}</div>;
  return (
    <div className="ready-toosoon">
      <span className="ready-toosoon-tag">Not available</span>
      <span className="ready-toosoon-text">
        {note ?? `${label ?? 'This read'} isn’t available for this league.`}
      </span>
    </div>
  );
}

// The market read's own off-slot, and the single home for why it's off — four surfaces show it
// (Players, team detail, player card, positional talent), and they must say the same thing.
//
// The catalog turns `panels.market` off whenever the read is CROSS-TIME: the LeagueLogs market only
// ever serves "now" and can't be backdated, so pricing a past season's rosters at today's market is a
// POC, not a live trade call. The locked policy is never to render that as if it were live. When a
// league's production and the market share a season the flag flips by itself and these panels return.
export const MARKET_OFF_NOTE =
  'The market read isn’t live for this league — today’s market prices a past season’s rosters, ' +
  'so it’s held back rather than shown as a live call.';

export function MarketOff({ label = 'Market VOR' }) {
  return <PanelOff label={label} note={MARKET_OFF_NOTE} />;
}

// Whether the market surfaces may render for the active slice. Absent `panels` (a view that isn't
// threaded one) means "don't know" -> render, preserving today's behaviour; only an explicit false gates.
export const marketOn = (panels) => !(panels && panels.market === false);

// The fallback slot a panel shows before it has enough data. Defaults to an honest
// "not yet" message; a panel can pass custom `children` (e.g. preseason content) to
// fill the same slot without any change to the gate.
function TooEarly({ label, weeks, needed, children }) {
  if (children) return <div className="ready-slot">{children}</div>;
  return (
    <div className="ready-toosoon">
      <span className="ready-toosoon-tag">Too early</span>
      <span className="ready-toosoon-text">
        {label ?? 'This read'} needs about {needed} week{needed === 1 ? '' : 's'} of games
        to mean anything — {weeks} so far. It turns on as the season builds.
      </span>
    </div>
  );
}

// Shown above a usable-but-early read so the manager weights it accordingly, rather
// than the panel speaking with full confidence off a thin sample (design law 2).
function BuildingNote({ weeks }) {
  return (
    <div className="ready-building" title="Confidence grows as more weeks are played">
      Early read — {weeks} week{weeks === 1 ? '' : 's'} of data so far; weight it lightly.
    </div>
  );
}
