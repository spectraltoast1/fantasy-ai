import React from 'react';

// Shared inline-SVG chart primitives. Pure presentational, viewBox/pixel based, colored
// via props (posture palette for trend up/down, violet for value). Built here once so
// every surface (Players card now; Matchups/Team later) draws the same marks.

// A minimal trend polyline. `values` is a numeric series (oldest → newest).
export function Sparkline({ values, width = 92, height = 28, color = 'var(--violet)', strokeWidth = 1.6 }) {
  if (!values || values.length < 2) {
    return <svg width={width} height={height} className="spark" aria-hidden="true" />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 2;
  const pts = values
    .map((v, i) => {
      const x = pad + (i / (values.length - 1)) * (width - pad * 2);
      const y = height - pad - ((v - min) / span) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg width={width} height={height} className="spark" aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// A trend read: sparkline + current value + signed delta, colored by direction. Trend
// up/down uses the reserved posture green/amber (README color roles).
export function TrendLine({ label, values, valueStr, deltaStr, up, muted }) {
  const color = muted ? 'var(--muted)' : up ? 'var(--contender)' : 'var(--ridingluck)';
  return (
    <div className="trendline">
      {label ? <span className="trendline-label gr-label">{label}</span> : null}
      <Sparkline values={values} color={muted ? 'var(--faint-2)' : 'var(--violet)'} />
      <div className="trendline-vals">
        <span className="trendline-value mono">{valueStr}</span>
        {deltaStr != null ? (
          <span className="trendline-delta mono" style={{ color }}>
            {up ? '↑' : '↓'} {deltaStr}
          </span>
        ) : null}
      </div>
    </div>
  );
}

// A 0-10 grade bar (bull/bear/situation). Fill width = grade*10%.
export function GradeBar({ grade, color = 'var(--violet)' }) {
  const w = grade == null ? 0 : Math.max(0, Math.min(10, grade)) * 10;
  return (
    <div className="grade-bar">
      <div className="grade-bar-fill" style={{ width: `${w}%`, background: color }} />
    </div>
  );
}

// A median tick inside a 25–75 band on a shared scale. Not consumed yet — built ahead
// of the Matchups slice (per-starter range gauges), kept here so the mark is shared.
export function RangeGauge({ lo, md, hi, min, max, height = 12, color = 'var(--violet)' }) {
  const span = (max - min) || 1;
  const pct = (v) => ((v - min) / span) * 100;
  const left = pct(lo);
  const width = Math.max(2, pct(hi) - pct(lo));
  const medLeft = pct(md);
  return (
    <div className="range-gauge" style={{ height }}>
      <div className="range-gauge-band" style={{ left: `${left}%`, width: `${width}%`, background: color }} />
      <div className="range-gauge-tick" style={{ left: `${medLeft}%` }} />
    </div>
  );
}
