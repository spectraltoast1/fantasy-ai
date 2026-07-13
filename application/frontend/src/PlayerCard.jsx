import React, { useEffect, useState } from 'react';
import { loadPlayerCard } from './queries.js';
import { TrendLine, GradeBar } from './charts.jsx';
import { POS_COLORS } from './posColors.js';

// Player card (detail view). Consumes the assembled object from queries.loadPlayerCard;
// three sections mirror the prototype: Value·VOR (Production + Market trend + trade lean),
// Opportunity (the player_signal axes), and ROS Outcome Shape (ros_synthesis grades/notes).
// Gaps are honest first-class states — no fabricated values where a read doesn't exist.

const TRADE_COLOR = { BUY: 'var(--violet-light)', SELL: 'var(--ridingluck)', HOLD: 'var(--muted)' };

export default function PlayerCard({ sleeperId, asOfWeek }) {
  const [card, setCard] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setCard(null);
    setErr(null);
    loadPlayerCard(sleeperId, asOfWeek)
      .then((c) => live && setCard(c))
      .catch((e) => live && setErr(e));
    return () => {
      live = false;
    };
  }, [sleeperId, asOfWeek]);

  if (err) return <div className="gr-state error">Could not load player.<pre>{String(err.message ?? err)}</pre></div>;
  if (!card) return <div className="gr-state">Loading…</div>;
  if (card.missing) return <div className="gr-state">No data for this player.</div>;

  return (
    <div className="pc">
      <header className="pc-head">
        <div>
          <h1 className="pc-name">{card.name}</h1>
          <div className="pc-meta">
            <span className="pc-pos" style={{ color: POS_COLORS[card.pos] }}>{card.pos}</span>
            <span className="mono">{card.nflTeam ?? '—'}</span>
          </div>
        </div>
        <span className={`pc-status ${card.onYours ? 'mine' : ''}`}>{card.status}</span>
      </header>

      {/* Value·VOR — Production + Market trend + the trade lean. */}
      <section className="pc-section">
        <div className="pc-h3">Value · VOR</div>
        <div className="pc-vor">
          <TrendLine
            label="Production"
            values={card.prod.series}
            valueStr={fmt(card.prod.value)}
            deltaStr={card.prod.delta != null ? signed(card.prod.delta) : null}
            up={card.prod.up}
          />
          <TrendLine
            label="Market"
            values={card.mkt.series}
            valueStr={fmt(card.mkt.value)}
            deltaStr={card.mkt.delta != null ? signed(card.mkt.delta) : null}
            up={card.mkt.up}
            muted={card.mkt.crossTime}
          />
          {card.lean ? (
            <div className="pc-trade">
              <span className="pc-trade-call" style={{ color: TRADE_COLOR[card.lean.call] }}>
                {card.lean.call}
              </span>
              <span className="pc-trade-why">{card.lean.why}</span>
              {card.lean.crossTime ? (
                <span className="pc-poc">POC · cross-time (2026 market × 2025 roster) — not a live call</span>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {/* Opportunity — the three player_signal axes + points-vs-profile companion. */}
      <section className="pc-section">
        <div className="pc-h3">Opportunity</div>
        {card.opportunity ? (
          <>
            <div className="pc-axes">
              <Axis label="Quality" value={fmt2(card.opportunity.qualityRate)} sub="pts / opportunity" />
              <Axis label="Volume" value={pct(card.opportunity.volumePct)} sub="position rank" />
              <Axis
                label="Trust"
                value={cap(card.opportunity.trustDir) ?? '—'}
                arrow={arrowFor(card.opportunity.trustDir)}
                sub={card.opportunity.reliability != null ? `${pct(card.opportunity.reliability)} reliable` : null}
              />
            </div>
            <p className="pc-companion">
              Scoring <strong>{fmt1(card.opportunity.recentPpg)}</strong>/g vs{' '}
              <strong>{fmt1(card.opportunity.expectedPpg)}</strong>/g the profile expects
              {card.opportunity.read ? <> — <span className="pc-read">{card.opportunity.read}</span></> : null}
              {card.opportunity.lowSample ? <span className="pc-thin"> · thin sample</span> : null}
            </p>
          </>
        ) : (
          <div className="pc-empty">No opportunity signal for this player yet.</div>
        )}
      </section>

      {/* ROS Outcome Shape — the AI bull/bear/situation read (sparse). */}
      <section className="pc-section">
        <div className="pc-h3">ROS Outcome Shape</div>
        {card.ros ? (
          <>
            <div className="pc-grades">
              <Grade label="Bull" note={card.ros.bullNote} grade={card.ros.bull} />
              <Grade label="Bear" note={card.ros.bearNote} grade={card.ros.bear} />
              <Grade label="Situation" note={card.ros.situationNote} grade={card.ros.situation} />
            </div>
            <div className="pc-conf">
              <span className={`pc-conf-tag c-${card.ros.confidence}`}>{cap(card.ros.confidence)} confidence</span>
              {card.ros.confidenceNote ? <span className="pc-conf-note">{card.ros.confidenceNote}</span> : null}
              {card.ros.priorSeason ? <span className="pc-thin"> · anchor is prior-season</span> : null}
            </div>
          </>
        ) : (
          <div className="pc-empty">
            No ROS synthesis for this player yet — the AI read runs for a subset today.
          </div>
        )}
      </section>
    </div>
  );
}

function Axis({ label, value, sub, arrow }) {
  return (
    <div className="pc-axis">
      <span className="pc-axis-label gr-label">{label}</span>
      <span className="pc-axis-value">
        {arrow ? <span className="pc-axis-arrow">{arrow}</span> : null}
        {value}
      </span>
      {sub ? <span className="pc-axis-sub">{sub}</span> : null}
    </div>
  );
}

function Grade({ label, note, grade }) {
  return (
    <div className="pc-grade">
      <div className="pc-grade-top">
        <span className="pc-grade-label gr-label">{label}</span>
        <span className="pc-grade-num mono">{grade ?? '—'}<span className="pc-grade-den">/10</span></span>
      </div>
      <GradeBar grade={grade} color="var(--violet)" />
      {note ? <p className="pc-grade-note">{note}</p> : null}
    </div>
  );
}

const fmt = (v) => (v == null ? '—' : v.toFixed(1));
const fmt1 = (v) => (v == null ? '—' : v.toFixed(1));
const fmt2 = (v) => (v == null ? '—' : v.toFixed(2));
const signed = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : null);
const arrowFor = (dir) => (dir === 'rising' ? '↑' : dir === 'falling' ? '↓' : dir ? '→' : null);
