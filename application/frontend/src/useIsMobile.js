import { useState, useEffect } from 'react';

// True when the viewport is at the mobile breakpoint (≤768px — the same cutoff styles.css uses).
// Drives the few cases where the mobile layout differs by more than CSS can express — notably
// Matchups (web two-pane vs. mobile tap-through). Updates live on resize / orientation change.
const MOBILE_QUERY = '(max-width: 768px)';

export default function useIsMobile() {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches,
  );

  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY);
    const onChange = (e) => setIsMobile(e.matches);
    mq.addEventListener('change', onChange);
    setIsMobile(mq.matches);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return isMobile;
}
