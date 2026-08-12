// Display formatting for the two reads that were asserting more certainty than the model has
// (P5/S2e, the honesty pass). Pure functions, no React import, so `check_league_copy.mjs` can
// drive every branch from fixtures under plain `node` — this repo has no test runner, and adding
// one would mean writing into main's symlinked node_modules.
//
// Both live here rather than in the view because two views render each of them, and a rule that
// exists twice is a rule that drifts.

/**
 * Playoff odds, 0-100, as a display string. The engine's own number is a Monte-Carlo estimate,
 * so the ends of the scale are hedged rather than stated:
 *
 *   0 < p < 1  ->  "<1%"        1 <= p <= 99  ->  the integer        p > 99  ->  ">99%"
 *
 * A sim result of exactly 0 takes "<1%" too. 0 of 10,000 runs means "did not occur in ten
 * thousand tries" — below roughly 0.03% — NOT mathematically eliminated, and "0%" is read as
 * elimination. The same argument mirrors at the top: 10,000 of 10,000 is not a guarantee.
 * `compute_bracket_sim` persists `round(odds, 3)`, so a true 0.04% is already stored as 0.0
 * before it reaches here; this rule is what stops that becoming a false claim on screen.
 *
 * Never returns "0%" or "100%" for any input. Returns null for null — callers keep their own
 * absent-state treatment ('—', or a styled span).
 */
export function fmtOdds(pct) {
  if (pct == null) return null;
  if (pct < 1) return '<1%';
  if (pct > 99) return '>99%';
  return `${Math.round(pct)}%`;
}

/**
 * The magic-number line, from `bracket_odds`' magic_wins + remaining_games.
 *
 * `magic_wins` is a **proxy**, not a clinch: `MAGIC_ODDS = 0.90`, so it is the fewest additional
 * wins k after which the team made the playoffs in >=90% of the sims that hit exactly k. The
 * engine names it a proxy; the UI used to drop the hedge and say "Clinched a spot" / "Clinch in
 * N". Clinched and Eliminated may only ever come from real bracket math, which does not exist
 * (deferred, Will 2026-08-12) — so nothing here asserts either.
 *
 * A null `magic_wins` with a known `remaining_games` is not missing data: it is the producer's
 * only way of saying "no number of wins guarantees a spot" (compute_bracket_sim:291 leaves m at
 * None when even winning out misses the threshold). It gets the sentence it always deserved.
 * `—` is for when we genuinely know nothing, i.e. no bracket_odds row at all.
 */
export function magicLine(magicWins, remainingGames) {
  if (remainingGames == null) return null;
  if (magicWins == null) return 'Needs help to clinch';
  if (magicWins <= 0) return 'Likely a playoff team';
  // Unreachable from today's producer — `for k in range(R + 1)` bounds magic_wins at
  // remaining_games, so "cannot clinch by winning out" arrives as null (handled above) and never
  // as an over-large number. Kept because it is the correct answer if that ever changes, and
  // covered by a fixture so it is no longer a condition that has never run.
  if (magicWins > remainingGames) return 'Needs help to clinch';
  if (magicWins === remainingGames) return 'Has to win out';
  return `${magicWins} of the next ${remainingGames} should clinch a spot`;
}
