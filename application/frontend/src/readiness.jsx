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
 * Wrap a panel's content. When the data is too thin for the panel's regime, renders
 * the "too early" fallback slot instead (a custom `fallback` node if given — the hook
 * for preseason/qualitative content later — else a default message). When the read is
 * usable but still firming up, renders the content with a subtle low-confidence note.
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
