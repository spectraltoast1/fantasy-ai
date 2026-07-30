import React from 'react';

// Per-panel readiness gate (Phase 1 part 4). A single home for one rule: "does this
// panel have enough data to be meaningful yet?" — so trend reads degrade cleanly
// early in a season and language calibrates to the sample, rather than every panel
// hard-coding its own week check. Pure logic + the wrapper/fallback live together
// because they're one cohesive concern (presentational, not data access — so it
// stays out of queries.js).
//
// We are frozen at week 4, so every panel reads "ready" today. The point is the seam:
// the bands below + the fallback slot exist NOW, so a live season degrades gracefully
// and preseason/qualitative content can drop into the "too early" slot with no rework.

export const REGIME = {
  // ready at roster lock — about who's on the team, not accumulated performance
  STRUCTURAL: 'structural',
  // usable from week 1, confidence grows with weeks (a point estimate that firms up)
  POINT_IN_TIME: 'point-in-time',
  // needs a few weeks of shape before it means anything (slopes, trends)
  TREND: 'trend',
};

// Weeks of data at which each regime starts being usable (`building`) and becomes
// fully trustworthy (`ready`). Below `building` it's "too early" and the panel hands
// off to its fallback slot. Deliberately conservative on trend — a half-life-2wk
// slope over one or two games is noise. These are the league's weeks-elapsed clock,
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
 * Wrap a panel's content. Two gates, in order:
 *   1. Catalog gate (Stage-B B5) — when `panel` is given and the active slice's `panels` map marks
 *      it off (`panels[panel] === false`), the panel isn't meaningful for THIS league, so render the
 *      "not for this league" slot (a custom `fallback` if given, else a default note). Optional and
 *      backward-compatible: callers that pass no `panel` skip it entirely.
 *   2. Readiness gate — when the data is too thin for the panel's regime, render the "too early"
 *      fallback slot; when usable-but-early, render with a subtle low-confidence note.
 * Catalog = "is this panel meaningful for this slice"; readiness = "is there enough data yet".
 */
export function Gate({ regime, weeks, label, fallback, panel, panels, children }) {
  if (panel && panels && panels[panel] === false) {
    return <PanelOff label={label}>{fallback}</PanelOff>;
  }
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
