import React, { useState } from 'react';
import { supabase, authConfigured } from './supabase.js';

// The sign-in overlay (P5/S1). A modal sibling of <main>, not a gate around the app: the
// public demo stays browsable signed-out, so signing in ADDS your leagues rather than
// unlocking the product. That is also why this isn't a route — the SPA has no router, and
// auth is a piece of state, not a place.
//
// Magic link only. No password field, no reset flow, no "forgot password" support burden.
//
// Honesty note on the copy: account creation is gated at the Supabase project ("allow new
// users to sign up" is OFF), so an uninvited address gets a link that cannot sign it in. We
// deliberately do NOT tell the user which case they are in — "that address isn't invited" is
// an account-enumeration oracle, and Supabase's own response is intentionally identical
// either way. The message below is true for both.
export default function SignIn({ onClose }) {
  const [email, setEmail] = useState('');
  const [state, setState] = useState('idle');   // idle | sending | sent | error
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!email.trim() || state === 'sending') return;
    setState('sending');
    setError(null);
    const { error: err } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      // No `shouldCreateUser: true` — leaving it off means this call cannot mint an account
      // even if the project setting were ever flipped back on. Belt and braces on the gate.
      options: { shouldCreateUser: false, emailRedirectTo: window.location.origin },
    });
    if (err) {
      setError(err.message);
      setState('error');
    } else {
      setState('sent');
    }
  };

  return (
    <div className="gr-overlay" role="dialog" aria-modal="true" aria-labelledby="signin-title">
      <div className="gr-signin">
        <button className="gr-signin-x" onClick={onClose} aria-label="Close">×</button>
        <h2 className="gr-signin-title" id="signin-title">Sign in</h2>

        {!authConfigured ? (
          // An honest unavailable state rather than a form that silently does nothing. The
          // console carries the diagnosis (see supabase.js); the demo is unaffected.
          <>
            <p className="gr-signin-lede">
              Sign-in isn&rsquo;t available in this build.
            </p>
            <p className="gr-signin-note">
              Everything else works — keep browsing the demo. If you&rsquo;re expecting to sign
              in, the deploy is missing its Supabase configuration.
            </p>
          </>
        ) : state === 'sent' ? (
          <>
            <p className="gr-signin-lede">
              If <strong>{email}</strong> has an invite, a sign-in link is on its way. Open it on
              this device and you&rsquo;ll land back here signed in.
            </p>
            <p className="gr-signin-note">
              Gridiron is invite-only while it&rsquo;s in testing, so links only work for
              invited addresses.
            </p>
          </>
        ) : (
          <>
            <p className="gr-signin-lede">
              We&rsquo;ll email you a link — no password to remember.
            </p>
            <form onSubmit={submit}>
              <input
                className="gr-signin-input"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
              />
              <button className="gr-signin-go" type="submit" disabled={state === 'sending'}>
                {state === 'sending' ? 'Sending…' : 'Email me a link'}
              </button>
            </form>
            {error && <p className="gr-signin-err">{error}</p>}
            <p className="gr-signin-note">
              Invite-only while in testing. You can keep browsing the demo without signing in.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
