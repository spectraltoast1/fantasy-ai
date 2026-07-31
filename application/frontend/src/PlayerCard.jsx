import React, { useEffect, useState } from 'react';
import { loadPlayerCard } from './queries.js';
import { TrendLine, GradeBar, RangeGauge } from './charts.jsx';
import { MARKET_OFF_NOTE, marketOn, hasShape } from './readiness.jsx';
import { POS_COLORS } from './posColors.js';

// Player card (detail view). Consumes the assembled object from queries.loadPlayerCard;
// three sections mirror the prototype: Value·VOR (Production + Market trend + trade lean),
// Opportunity (the player_signal axes), and ROS Outcome Shape (ros_synthesis grades/notes).
// Gaps are honest first-class states — no fabricated values where a read doesn't exist.

const TRADE_COLOR = { BUY: 'var(--violet-light)', SELL: 'var(--ridingluck)', HOLD: 'var(--muted)' };

// player_signal's categorical `read`, in words. The engine emits `too_early` on a thin sample, which is
// exactly the early-season case — leaking the raw enum there reads as a bug rather than as a state.
const READ_LABEL = { too_early: 'too early to read', spike: 'spiking', sticky: 'sticky', mixed: 'mixed' };

export default function PlayerCard({ sleeperId, asOfWeek, weeks, panels }) {
  const [card, setCard] = useState(null);
  const [err, setErr] = useState(null);
  const showMkt = marketOn(panels);

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

      {/* Value·VOR — Production, plus the Market trend + trade lean when the market read is live.
          Both of those are the Production−Market gap wearing two coats, so they gate together: a
          cross-time gap is a POC number, and a BUY/SELL call off one would be the least honest thing
          on the card. Production stands alone — it's this league's own season, not the market's. */}
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
          {showMkt ? (
            <>
              <TrendLine
                label="Market"
                values={card.mkt.series}
                valueStr={fmt(card.mkt.value)}
                deltaStr={card.mkt.delta != null ? signed(card.mkt.delta) : null}
                up={card.mkt.up}
              />
              {card.lean ? (
                <div className="pc-trade">
                  <span className="pc-trade-call" style={{ color: TRADE_COLOR[card.lean.call] }}>
                    {card.lean.call}
                  </span>
                  <span className="pc-trade-why">{card.lean.why}</span>
                </div>
              ) : null}
            </>
          ) : (
            <div className="pc-empty">{MARKET_OFF_NOTE}</div>
          )}
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
              {card.opportunity.read ? <> — <span className="pc-read">{READ_LABEL[card.opportunity.read] ?? card.opportunity.read}</span></> : null}
              {card.opportunity.games != null ? (
                <span className="pc-thin">
                  {' · '}{card.opportunity.games} game{card.opportunity.games === 1 ? '' : 's'}
                  {card.opportunity.lowSample ? ' — too thin to read a trend' : ''}
                </span>
              ) : null}
            </p>
          </>
        ) : (
          <div className="pc-empty">No opportunity signal for this player yet.</div>
        )}
      </section>

      {/* Rest-of-season range — the DETERMINISTIC calibrated band (ros_player_band), in points. Sits
          beside the AI outlook below and is a different object: this one is measured, always available
          where the season's band is honest, and needs no news. Deliberately no confidence chip — the
          width IS the confidence (law 2), and the percentage that would have supplied a label (ros_cv)
          was measured inverted and retired. Skewed low on purpose: bear is centre − 2.5σ while bull is
          only centre + 0.52σ, so the tick sitting high in the track is the honest shape, not a bug. */}
      <section className="pc-section">
        <div className="pc-h3">Rest-of-season range</div>
        {card.rosRange ? (
          <>
            <div className="pc-axes">
              <Axis label="Bear" value={fmt1(card.rosRange.bear)} sub="downside" />
              <Axis label="Center" value={fmt1(card.rosRange.center)} sub="projected points" />
              <Axis label="Bull" value={fmt1(card.rosRange.bull)} sub="upside" />
            </div>
            <div className="pc-range-bar">
              {/* Domain starts at 0 because 0 is a real floor — a season's realised production can't be
                  negative, and the bear is floored there. So the tick's height reads as "how much of the
                  range is downside". */}
              <RangeGauge
                lo={card.rosRange.bear}
                md={card.rosRange.center}
                hi={card.rosRange.bull}
                min={0}
                max={card.rosRange.bull || 1}
                height={14}
              />
            </div>
            <p className="pc-companion">
              ±<strong>{fmt1(card.rosRange.sigma)}</strong> pts over{' '}
              <strong>{card.rosRange.weeks ?? '—'}</strong> remaining week
              {card.rosRange.weeks === 1 ? '' : 's'} — the spread is the confidence: wider means less
              certain.
              {card.rosRange.calibrated === false ? (
                <span className="pc-thin"> · outside the calibrated pool</span>
              ) : null}
              {!hasShape(weeks) ? (
                <span className="pc-thin"> · early season: leaning on the positional baseline</span>
              ) : null}
            </p>
          </>
        ) : (
          <div className="pc-empty">
            No calibrated range for this season — it's served from the current engine build, and these
            replay seasons are kept frozen at the constants they were certified under.
          </div>
        )}
      </section>

      {/* ROS Outcome Shape — the bull/bear/situation read. It runs on live in-season news; until a
          year-matched live-news read exists it shows an honest empty state (matches the dossier
          "no intel" pattern) rather than fabricated grades. */}
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
            </div>
          </>
        ) : (
          <div className="pc-empty">
            No rest-of-season outlook yet — the bull / bear / situation read runs on live in-season
            news, arriving with live data.
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
