import React from 'react';
import { TAB_ICONS } from './icons.jsx';

// The "coming soon" slot for surfaces not yet wired (League / Matchups / Teams during
// the Gridiron migration). Deliberately quiet — it borrows the readiness "too early"
// idiom so the app reads as intentionally in-progress, not broken. Each of these
// surfaces has a real backend entity waiting behind it (per DATA_CONTRACT §7 build order).

const COPY = {
  league: {
    title: 'League',
    line: 'Your Race, Playoff Picture, Posture Map, and Positional Talent land here — powered by bracket odds and true rank.',
  },
  matchups: {
    title: 'Matchups',
    line: "The week's slate with win probabilities and score-range bands, from the bracket sim and projection consensus.",
  },
  teams: {
    title: 'Teams',
    line: 'Standings with true record and posture, plus team detail: positional depth, roster VOR, and the manager dossier.',
  },
};

export default function Placeholder({ tab }) {
  const copy = COPY[tab] ?? { title: 'Coming soon', line: 'This surface is being built.' };
  const Icon = TAB_ICONS[tab];
  return (
    <div className="gr-placeholder">
      {Icon && (
        <span className="gr-placeholder-glyph">
          <Icon size={26} />
        </span>
      )}
      <div className="gr-placeholder-title">{copy.title}</div>
      <span className="gr-placeholder-tag">Coming soon</span>
      <p className="gr-placeholder-line">{copy.line}</p>
    </div>
  );
}
