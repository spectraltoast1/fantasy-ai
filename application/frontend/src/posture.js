// Posture derivation — the DATA_CONTRACT §5 rule, in one shared home.
//
// There is no `posture` column; posture is the synthesis a manager reads off the
// adjacency of two values it already has: standing (playoff odds) and true record
// (all-play %). This helper is the single source of that rule so the Teams chips and
// the (later) League posture map render identically. Purely presentational — no data
// access (that stays in queries.js).

// Locked constants (contract §5, user-tuned 2026-07). Candidates for the future
// league/user config seed, so they live as named constants.
export const BAND = 9; // pts: how far off the diagonal counts as lucky/unlucky
export const LEVEL_CUT = 60; // %: contender/rebuild threshold on the diagonal band

// Posture label → the reserved posture CSS variable (styles.css). Chips tint at low
// alpha; the map (later) uses the solid tone. Kept here so both read one mapping.
export const POSTURE_TONE = {
  Contender: 'var(--contender)',
  Unlucky: 'var(--unlucky)',
  'On pace': 'var(--onpace)',
  'Riding luck': 'var(--ridingluck)',
  Rebuild: 'var(--rebuild)',
};

/**
 * The posture read for one team. Both inputs are 0–100 (playoff_odds is a fraction in
 * the parquet — multiply by 100 before calling). Matches the prototype rule exactly.
 * @param {number} playoffOddsPct standing — how you're actually doing (0–100)
 * @param {number} allPlayPct true record — luck-neutral performance (0–100)
 * @returns {{label: string, tone: string}}
 */
export function derivePosture(playoffOddsPct, allPlayPct) {
  const gap = allPlayPct - playoffOddsPct; // + = performing above standing (buy window)
  const level = (playoffOddsPct + allPlayPct) / 2;

  let label;
  if (gap > BAND) label = 'Unlucky';
  else if (gap < -BAND) label = 'Riding luck';
  else if (level >= LEVEL_CUT) label = 'Contender';
  else if (level <= 100 - LEVEL_CUT) label = 'Rebuild';
  else label = 'On pace';

  return { label, tone: POSTURE_TONE[label] };
}
