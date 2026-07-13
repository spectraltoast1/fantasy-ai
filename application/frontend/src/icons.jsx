import React from 'react';

// Gridiron glyph set — inline SVG, line style (stroke 1.7, currentColor, no fill), 24×24.
// One per surface (trophy/swords/clipboard/helmet) + shield-check (dossier) + chevron (back).
// Presentational only; color comes from the parent via currentColor, size via `size` prop.

function Svg({ size = 20, children, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

// League — trophy.
export function IconTrophy(props) {
  return (
    <Svg {...props}>
      <path d="M7 4h10v4a5 5 0 0 1-10 0V4z" />
      <path d="M7 6H4.5v1.5A3 3 0 0 0 7 10.4" />
      <path d="M17 6h2.5v1.5A3 3 0 0 1 17 10.4" />
      <path d="M12 13v3" />
      <path d="M9 20h6" />
      <path d="M10 16h4l.5 4h-5z" />
    </Svg>
  );
}

// Matchups — crossed swords.
export function IconSwords(props) {
  return (
    <Svg {...props}>
      <path d="M4 4h3l9 9-3 3-9-9V4z" />
      <path d="M13.5 13.5 20 20" />
      <path d="M20 4h-3l-9 9 3 3 9-9V4z" />
      <path d="M10.5 13.5 4 20" />
    </Svg>
  );
}

// Teams — clipboard.
export function IconClipboard(props) {
  return (
    <Svg {...props}>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 4a3 3 0 0 1 6 0" />
      <path d="M8.5 11h7" />
      <path d="M8.5 15h5" />
    </Svg>
  );
}

// Players — football helmet.
export function IconHelmet(props) {
  return (
    <Svg {...props}>
      <path d="M4 13c0-5 3.5-8 8.5-8 4 0 6.5 2.3 7 6l-1.5 3H10" />
      <path d="M4 13c.3 3 2.2 5 5 5h4l1-3" />
      <path d="M13.5 15H19" />
    </Svg>
  );
}

// Manager Dossier — shield-check.
export function IconShieldCheck(props) {
  return (
    <Svg {...props}>
      <path d="M12 3l7 3v5c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </Svg>
  );
}

// Back affordance — chevron-left.
export function IconChevronLeft(props) {
  return (
    <Svg {...props}>
      <path d="M15 5l-7 7 7 7" />
    </Svg>
  );
}

export const TAB_ICONS = {
  league: IconTrophy,
  matchups: IconSwords,
  teams: IconClipboard,
  players: IconHelmet,
};
