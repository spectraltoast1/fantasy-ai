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

// A virtual pageview. The SPA has no router, so GA cannot see navigation and is told the path
// explicitly. page_location must be ABSOLUTE — GA derives its page dimensions from it, and a
// relative value leaves the real (unchanging) URL in the report.
//
// P5/S2c removed a `lastPath` de-dupe from here. It existed for one reason: supabase-js reports a
// tab REFOCUS as SIGNED_IN, App.jsx treated that as an identity change, and nulling the slice
// re-fired the pageview effect for a surface the user never left. S2c fixed that at the source —
// the identity epoch now bumps only when the user id actually changes — so the guard was
// suppressing a re-fire that no longer happens, while quietly hiding any future one.
export function pageView(path, title) {
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
