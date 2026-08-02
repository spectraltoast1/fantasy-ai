// The Supabase client (P5/S1) — the app's only auth dependency.
//
// Config arrives at BUILD time: Vite inlines `import.meta.env.VITE_*` into the bundle. It
// cannot come from a .env file here — application/.dockerignore strips every .env from the
// build context, so one would work perfectly in local dev and then silently ship a bundle
// with `undefined` config. Fly *secrets* don't work either: they reach the running machine,
// not the builder. Docker build args are the only route; see the Dockerfile's web stage and
// fly.toml's [build.args].
//
// A bundle built without these produces a sign-in button that does nothing — a symptom
// indistinguishable from a stale bundle, a paused Supabase project, or a Fly cold start. So it
// has to fail LOUDLY. But it must not fail FATALLY: throwing here would take down the whole
// SPA, and a logged-out visitor keeping full access to the public demo is a settled product
// requirement, not a nice-to-have. Breaking the demo because *auth* is misconfigured would be
// the misconfiguration causing strictly more damage than the thing it broke.
//
// So: `supabase` is null when unconfigured, the console says exactly what is missing and where
// it comes from, and the sign-in UI renders an honest unavailable state instead of a dead
// form. The demo survives; the failure is still one console line rather than four hours of
// guessing.
//
// The anon key is publishable by design: it ships in this bundle either way, and this
// project's Data API is disabled with RLS deny-by-default, so it opens nothing. The
// service-role key is a different animal and lives only in application/config.py.

import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// `REPLACE_ME` is fly.toml's placeholder. Treating it as configured would be worse than
// treating it as missing: the app would look fine and only sign-in would quietly fail.
const PLACEHOLDER = 'REPLACE_ME';
export const authConfigured = Boolean(url && anonKey) && url !== PLACEHOLDER && anonKey !== PLACEHOLDER;

if (!authConfigured) {
  console.error(
    '[auth] Supabase config missing from this build — sign-in is disabled; the rest of the app ' +
    'is unaffected.\n' +
    `  VITE_SUPABASE_URL:      ${url || '(unset)'}\n` +
    `  VITE_SUPABASE_ANON_KEY: ${anonKey ? '(set)' : '(unset)'}\n` +
    '  These are Docker BUILD ARGS (Dockerfile web stage + fly.toml [build.args]) — not Fly ' +
    'secrets, which reach the running machine but not the builder, and not a .env file, which ' +
    '.dockerignore strips from the build context. Locally: export them before `npm run dev`.',
  );
}

export const supabase = !authConfigured ? null : createClient(url, anonKey, {
  auth: {
    // Persist the session and refresh it in the background. Deliberately supabase-js's own
    // storage rather than anything hand-rolled: magic-link auth that authenticates but does
    // not persist emails the user a link on every single visit, which reads as broken.
    persistSession: true,
    autoRefreshToken: true,
    // The magic link comes back as a URL fragment; let the client consume it on load.
    detectSessionInUrl: true,
  },
});
