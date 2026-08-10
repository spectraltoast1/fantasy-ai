import React, { useState } from 'react';
import { authConfigured } from './supabase.js';
import { requestSignInLink } from './queries.js';
import { track } from './analytics.js';

// The sign-in overlay (P5/S1, re-pointed in S1b). A modal sibling of <main>, not a gate around
// the app: the public demo stays browsable signed-out, so signing in ADDS your leagues rather
// than unlocking the product. That is also why this isn't a route — the SPA has no router, and
// auth is a piece of state, not a place.
//
// Magic link only. No password field, no reset flow, no "forgot password" support burden.
//
// S1b: this no longer calls Supabase directly. It posts email + access code to our own API,
// which validates the code SERVER-side and only then creates the account and sends the link.
// The client cannot be the gate — the publishable key ships in this bundle by design, so
// anything checked here is bypassable by calling Supabase directly. Going through the
// queries.js seam also means the form doesn't know where data lives, like every other view.
//
// Honesty note on the copy, unchanged in spirit from S1: the refusal is deliberately uniform.
// We never say whether the address already has an account — that's an enumeration oracle — and
// never how close a wrong code was. The server sends one message for every refusal it can
// attribute to the caller; this just shows it.
export default function SignIn({ onClose }) {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [state, setState] = useState('idle');   // idle | sending | sent | error
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!email.trim() || !code.trim() || state === 'sending') return;
    // The sign-in funnel (appendices/analytics.md). Parameterless by design — no reason, no
    // address. The server's refusal is deliberately uniform (it is not an enumeration oracle),
    // and a finer-grained reason in a third-party stream would quietly undo that.
    track('sign_in_submitted');
    setState('sending');
    setError(null);
    try {
      await requestSignInLink(email.trim(), code.trim());
      track('sign_in_link_sent');
      setState('sent');
    } catch (err) {
      // Any throw: a refused code, but also a network failure or a cold API machine. The event
      // means "the attempt did not succeed", not "the server said no".
      track('sign_in_refused');
      setError(err.message);
      setState('error');
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
              A sign-in link is on its way to <strong>{email}</strong>. Open it on this device and
              you&rsquo;ll land back here signed in.
            </p>
            <p className="gr-signin-note">
              Didn&rsquo;t arrive? Check spam, then try again in a few minutes.
            </p>
          </>
        ) : (
          <>
            <p className="gr-signin-lede">
              We&rsquo;ll email you a link — no password to remember. Gridiron is in private
              testing, so you&rsquo;ll need the access code too.
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
              <input
                className="gr-signin-input"
                type="text"
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck="false"
                placeholder="access code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
              <button className="gr-signin-go" type="submit" disabled={state === 'sending'}>
                {state === 'sending' ? 'Sending…' : 'Email me a link'}
              </button>
            </form>
            {error && <p className="gr-signin-err">{error}</p>}
            <p className="gr-signin-note">
              The code comes from whoever told you about Gridiron. You can keep browsing the demo
              without signing in.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
