// The one module that knows Google Analytics exists (GA4, property G-J1F0BE5ZW4; the tag itself
// lives in index.html). Views call pageView/track and never touch window.gtag.
//
// NOT a data seam — it returns nothing to the app. It is write-only telemetry, and the app must
// render identically when every call here is a no-op. That is the COMMON case, not the edge one:
// ad blockers and Safari's tracking prevention stop the tag from ever defining window.gtag. Hence
// the guard on every path, and hence nothing here may throw — a blocked tracker turning every tab
// switch into a console error would be a real bug caused by a fake feature.
const send = (...args) => {
  if (typeof window === 'undefined' || typeof window.gtag !== 'function') return;
  try { window.gtag(...args); } catch { /* telemetry never breaks a render */ }
};

// The last path sent, so a repeat is dropped. Not defensive clutter: App.jsx's pageview effect
// keys off `slice`, and supabase-js can report a tab REFOCUS as SIGNED_IN, which nulls the slice
// and re-fires the effect for a surface the user never left. No legitimate in-app transition
// repeats a path consecutively (drill-downs are one level deep and no detail type can open
// itself), so this only ever suppresses a spurious re-fire.
let lastPath = null;

// A virtual pageview. The SPA has no router, so GA cannot see navigation and is told the path
// explicitly. page_location must be ABSOLUTE — GA derives its page dimensions from it, and a
// relative value leaves the real (unchanging) URL in the report.
export function pageView(path, title) {
  if (path === lastPath) return;
  lastPath = path;
  send('event', 'page_view', {
    page_location: window.location.origin + path,
    page_title: title,
  });
}

// A named interaction. Parameterless at every call site today, and that is a decision, not an
// oversight: GA4 lists event NAMES with no admin setup, while a parameter needs a custom dimension
// registered by hand in the GA console and is NOT retroactive. If a parameter is ever added here,
// register it the same day or that data is unrecoverable.
export function track(name) {
  send('event', name);
}
