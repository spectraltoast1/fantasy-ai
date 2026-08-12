#!/usr/bin/env node
// Gate for the P5/S2e honesty pass: the League screen may not assert more certainty than the
// model has. Fixture-driven, zero dependencies — run it with `node application/frontend/
// check_league_copy.mjs` from the repo root. There is no test runner in this repo and adding
// one would write into main's symlinked node_modules, so this follows the `check_*.py` idiom
// the API already uses: a committed script that fails loudly.
//
// It gates the two pure functions in src/format.js. That is the whole point of them being pure:
// every string the five render sites can produce comes from here, so proving it here proves it
// for League, Teams and TeamDetail at once.

import { fmtOdds, magicLine } from './src/format.js';

let failures = 0;
let checks = 0;

function eq(what, got, want) {
  checks += 1;
  const ok = Object.is(got, want);
  if (!ok) failures += 1;
  console.log(`${ok ? '  ok  ' : '  FAIL'} ${what}${ok ? '' : `\n         got  ${JSON.stringify(got)}\n         want ${JSON.stringify(want)}`}`);
}

function ok(what, condition, detail = '') {
  checks += 1;
  if (!condition) failures += 1;
  console.log(`${condition ? '  ok  ' : '  FAIL'} ${what}${condition ? '' : `\n         ${detail}`}`);
}

// ---------------------------------------------------------------------------------------------
console.log('\nmagicLine — every branch, including the two nulls that used to collapse into one');
// Before S2e both null cases returned null, rendered '' on the team row (League.jsx:131) and '—'
// on the your-team panel (League.jsx:89): the same value, two treatments. They are now distinct
// facts with distinct sentences.
eq('null magic + known remaining -> the sentence it always deserved',
   magicLine(null, 10), 'Needs help to clinch');
eq('null remaining -> null (caller renders —); genuinely nothing known',
   magicLine(5, null), null);
eq('both null -> null', magicLine(null, null), null);
eq('magic 0 -> a likelihood, never a clinch', magicLine(0, 10), 'Likely a playoff team');
eq('magic negative -> same branch', magicLine(-2, 10), 'Likely a playoff team');
eq('magic == remaining -> has to win out', magicLine(10, 10), 'Has to win out');
eq('magic 1 of 1 remaining -> has to win out', magicLine(1, 1), 'Has to win out');
eq('0 < magic < remaining -> the proxy, hedged', magicLine(5, 10),
   '5 of the next 10 should clinch a spot');
eq('the singular case still reads', magicLine(1, 2), '1 of the next 2 should clinch a spot');
// Dead against today's producer (compute_bracket_sim bounds k at R), kept as the correct answer
// and driven here so it is tested rather than merely present.
eq('magic > remaining -> needs help (unreachable today, still correct)',
   magicLine(12, 10), 'Needs help to clinch');

console.log('\nmagicLine — the simulation never asserts a certainty, over the whole input domain');
// Exhaustive rather than a fixture list, so a branch added later is covered without anyone
// remembering to add a case. `magic_wins` is an integer count and `remaining_games` a week
// count, so this grid is the entire reachable domain with room either side.
const MAGIC_INPUTS = [null, ...Array.from({ length: 21 }, (_, i) => i - 5)];
const REMAINING_INPUTS = [null, ...Array.from({ length: 17 }, (_, i) => i)];
const everyLine = [];
for (const m of MAGIC_INPUTS) {
  for (const r of REMAINING_INPUTS) everyLine.push([m, r, magicLine(m, r)]);
}
// "clinch" lowercase survives on purpose — "should clinch a spot" and "Needs help to clinch"
// are hedged verbs. "Clinched" and "Clinch in" were the assertions, and they are what must never
// come back. Same for any elimination or guarantee claim, which only real bracket math may make.
for (const forbidden of ['Clinched', 'Clinch in', 'Eliminat', 'Guarantee', 'Certain']) {
  const hits = everyLine.filter(([, , s]) => s != null && s.includes(forbidden));
  ok(`no input in the domain produces "${forbidden}" (${everyLine.length} combinations)`,
     hits.length === 0, `produced: ${JSON.stringify(hits.slice(0, 5))}`);
}
eq('the domain yields exactly the five intended sentences',
   [...new Set(everyLine.map(([, , s]) => (s == null ? 'null'
     : s.replace(/^\d+ of the next \d+/, 'N of the next M'))))].sort().join(' | '),
   'Has to win out | Likely a playoff team | N of the next M should clinch a spot | Needs help to clinch | null');

// ---------------------------------------------------------------------------------------------
console.log('\nfmtOdds — the boundary table (Will, 2026-08-12)');
eq('null -> null (caller renders — or a styled span)', fmtOdds(null), null);
eq('undefined -> null', fmtOdds(undefined), null);
eq('a sim 0 is "did not occur in 10k tries", not elimination', fmtOdds(0), '<1%');
eq('0.3 — the live rank-9/10 value that used to print 0%', fmtOdds(0.3), '<1%');
eq('0.999', fmtOdds(0.999), '<1%');
eq('1 is the first integer', fmtOdds(1), '1%');
eq('50', fmtOdds(50), '50%');
eq('94.2 — the live rank-1 value', fmtOdds(94.2), '94%');
eq('99 is the last integer', fmtOdds(99), '99%');
eq('99.4 — used to round to 99, now hedged', fmtOdds(99.4), '>99%');
eq('99.6 — used to print 100%', fmtOdds(99.6), '>99%');
eq('100 is never stated as certainty', fmtOdds(100), '>99%');

console.log('\nfmtOdds — the domain scan: no input anywhere on [0,100] can print 0% or 100%');
// The served value is `round(playoff_odds, 3) * 100`, i.e. a tenth of a percentage point, so
// this scan covers every value the API can actually emit — and then a finer pass covers every
// value it could emit if that rounding ever changed.
const forbidden0 = [];
const forbidden100 = [];
const shapes = new Set();
for (let i = 0; i <= 100000; i += 1) {
  const p = i / 1000;               // 0.000 .. 100.000 in thousandths
  const s = fmtOdds(p);
  if (s === '0%') forbidden0.push(p);
  if (s === '100%') forbidden100.push(p);
  shapes.add(s === '<1%' || s === '>99%' ? s : 'integer');
}
ok('never "0%" across 100,001 values', forbidden0.length === 0,
   `first offenders: ${forbidden0.slice(0, 5)}`);
ok('never "100%" across 100,001 values', forbidden100.length === 0,
   `first offenders: ${forbidden100.slice(0, 5)}`);
eq('the scan produced exactly the three intended shapes', [...shapes].sort().join('|'),
   '<1%|>99%|integer');

// Every integer that CAN be printed sits in [1,99] — the ends are unreachable by construction,
// not by luck.
const ints = new Set();
for (let i = 0; i <= 100000; i += 1) {
  const s = fmtOdds(i / 1000);
  if (s !== '<1%' && s !== '>99%') ints.add(Number(s.slice(0, -1)));
}
eq('lowest printable integer', Math.min(...ints), 1);
eq('highest printable integer', Math.max(...ints), 99);

// ---------------------------------------------------------------------------------------------
console.log('\nthe live demo payload — every row renders a sentence and an honest number');
// The exact values /api/standings served for DEMO-2025 week 5 on 2026-08-12. Ranks 9 and 10 are
// the row this session exists for: both at 0.3%, one of them with a null magic number.
const LIVE = [
  { rank: 1, playoffPct: 94.19999999999999, magicWins: 5, remainingGames: 10 },
  { rank: 2, playoffPct: 93.2, magicWins: 5, remainingGames: 10 },
  { rank: 3, playoffPct: 92.0, magicWins: 6, remainingGames: 10 },
  { rank: 4, playoffPct: 79.0, magicWins: 6, remainingGames: 10 },
  { rank: 5, playoffPct: 19.9, magicWins: 8, remainingGames: 10 },
  { rank: 6, playoffPct: 10.4, magicWins: 8, remainingGames: 10 },
  { rank: 7, playoffPct: 6.2, magicWins: 7, remainingGames: 10 },
  { rank: 8, playoffPct: 4.5, magicWins: 8, remainingGames: 10 },
  { rank: 9, playoffPct: 0.3, magicWins: null, remainingGames: 10 },
  { rank: 10, playoffPct: 0.3, magicWins: 10, remainingGames: 10 },
];
const blanks = LIVE.filter((t) => magicLine(t.magicWins, t.remainingGames) == null);
ok('no row renders a blank magic line', blanks.length === 0,
   `blank at ranks: ${blanks.map((t) => t.rank)}`);
eq('rank 9 — was blank, now says what a null magic number means',
   magicLine(LIVE[8].magicWins, LIVE[8].remainingGames), 'Needs help to clinch');
eq('rank 9 — was "0%", which reads as eliminated', fmtOdds(LIVE[8].playoffPct), '<1%');
eq('rank 10 — was "Clinch in 10 of next 10"',
   magicLine(LIVE[9].magicWins, LIVE[9].remainingGames), 'Has to win out');
eq('rank 1 — the top of the table is still a number', fmtOdds(LIVE[0].playoffPct), '94%');
ok('no row prints 0% or 100%',
   LIVE.every((t) => !['0%', '100%'].includes(fmtOdds(t.playoffPct))));

// ---------------------------------------------------------------------------------------------
console.log(`\n${failures ? 'FAILED' : 'PASSED'} — ${checks - failures}/${checks} checks\n`);
process.exit(failures ? 1 : 0);
