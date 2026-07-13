import React, { useEffect, useState } from 'react';
import { loadManagerDossier } from './queries.js';
import { IconShieldCheck } from './icons.jsx';

// Manager Dossier (drill-down from team detail). The cleanest 1:1 map in the app — the
// manager_dossiers row rendered as headline + five tendency fields + a signal-depth footer.
// Copy is tendencies-not-verdicts, confidence gated on signal depth (guardrails enforced
// backend-side). A zero-signal manager shows the honest "no intel" state (the AI is skipped).

// depth_tier → the signal-depth badge (contract §4.8).
const DEPTH_BADGE = { deep: 'HIGH', moderate: 'MED', thin: 'THIN' };

const FIELDS = [
  ['Waiver / FAAB', 'waiverFaab'],
  ['Trade Tendency', 'tradeTendency'],
  ['Positional Lean', 'positionalLean'],
  ['Roster Construction', 'rosterConstruction'],
  ['Edge / Blind Spot', 'edgeOrBlindspot'],
];

export default function Dossier({ rosterId }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setD(null);
    setErr(null);
    loadManagerDossier(rosterId)
      .then((x) => live && setD(x))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [rosterId]);

  if (err) return <div className="gr-state error">Could not load dossier.<pre>{String(err.message ?? err)}</pre></div>;
  if (!d) return <div className="gr-state">Loading…</div>;
  if (d.missing) return <div className="gr-state">No dossier for this manager.</div>;

  const badge = DEPTH_BADGE[d.depthTier] ?? d.depthTier?.toUpperCase() ?? '—';

  return (
    <div className="dos">
      <header className="dos-head">
        <span className="dos-glyph"><IconShieldCheck size={18} /></span>
        <div>
          <div className="dos-kicker gr-label">Manager Dossier</div>
          <h1 className="dos-name">{d.teamName}</h1>
        </div>
      </header>

      {d.isZeroSignal ? (
        <div className="dos-zero">
          <span className="dos-zero-tag">No intel</span>
          <p>No transaction history for this manager yet — nothing to read tendencies off. The AI read is skipped until there's signal.</p>
        </div>
      ) : (
        <>
          <p className="dos-headline">{d.headline}</p>

          <div className="dos-fields">
            {FIELDS.map(([label, key]) => (
              <div className="dos-field" key={key}>
                <span className="dos-field-label gr-label">{label}</span>
                <p className="dos-field-text">{d.tendencies[key] ?? '—'}</p>
              </div>
            ))}
          </div>

          <footer className="dos-footer">
            <div className="dos-depth">
              <span className={`dos-badge tier-${d.depthTier}`}>{badge} signal</span>
              <span className="dos-counts mono">
                {d.nLeagues} league{d.nLeagues === 1 ? '' : 's'} · {d.nSeasons} season
                {d.nSeasons === 1 ? '' : 's'} · {d.nTransactions} moves
              </span>
            </div>
            {d.confidenceNote ? <p className="dos-note">{d.confidenceNote}</p> : null}
            <p className="dos-prov mono">{d.model}{d.generatedAt ? ` · ${String(d.generatedAt).slice(0, 10)}` : ''}</p>
          </footer>
        </>
      )}
    </div>
  );
}
