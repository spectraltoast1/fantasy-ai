# Appendix — Web analytics (GA4)

**Current as of:** 2026-08-10.
**Scope:** how Surplus measures usage. This is the **install brief Code executes** (one-off sidebar,
briefed 2026-08-10 by the PM session) and, once it lands, the standing description of the analytics
layer. Read it before touching `index.html`'s `<head>`, `src/analytics.js`, or any `track()` call.
**Status: INSTALLED 2026-08-10.** Everything below is live. Verification results and the corrections
the install turned up are in *What the install found*, near the bottom.

> **Deliberately outside the V1 project spine.** This is not P3/P4/P5 work and does not block or
> reorder anything. It touches no read, no transform, no number, and no rendered pixel. It is here
> so a future agent finds a third-party tag in the served HTML and knows why.

---

## Why this exists

Will registered a GA4 property for surplusff.com (measurement ID **`G-J1F0BE5ZW4`**) and pasted the
snippet Google hands you. The stated goal is not vanity traffic counting — it is **"which parts of
Surplus do people actually use,"** plus, implicitly during an invite-gated launch, **"where do people
fall out of onboarding."**

**The pasted snippet alone answers neither**, and that is the one thing worth understanding before
executing this brief. Surplus is a single-page app with **no router** — `SignIn.jsx` says so
explicitly, and `App.jsx` holds the active surface in `useState`, not in the URL. The URL is
`https://surplusff.com/` from arrival to departure. GA infers a "page" from the URL. So the raw
snippet records exactly **one pageview per visit**, and eight minutes spent in Matchups is
indistinguishable from a bounce.

The fix is the standard GA4 single-page-app pattern — a **virtual pageview**: the app tells GA the
path explicitly when the surface changes. Everything else in this brief follows from that.

---

## The change — three parts, four files

### 1. The tag — `application/frontend/index.html`

Insert **as the first children of `<head>`**, before the existing `<meta charset>`:

```html
    <!-- Google Analytics 4 (property G-J1F0BE5ZW4). Page views are sent by the app, not by this
         tag — see send_page_view below and appendices/analytics.md. -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-J1F0BE5ZW4"></script>
    <script>
      window.dataLayer = window.dataLayer || [];
      function gtag(){dataLayer.push(arguments);}
      gtag('js', new Date());

      gtag('config', 'G-J1F0BE5ZW4', { send_page_view: false });
    </script>
```

**This is Google's snippet verbatim with exactly one deviation, and the deviation is deliberate:**
`{ send_page_view: false }`. Without it the tag fires its own pageview for `/` the instant it loads,
and the app immediately fires a second one for `/league` — so every visit double-counts, and `/`
becomes the site's most-visited "page" while meaning nothing. With it, **every** pageview comes from
one place and carries a real path. The cost is honest and must be named: if the app-side hook ever
breaks, pageviews go to **zero** rather than degrading to a baseline. That is precisely what the
Definition of Done below exists to catch, and it is the better failure — silence is visible, a
plausible-but-wrong number is not.

**One tag, one page, structurally.** `application/frontend/index.html` is the **only** HTML shell in
the served app: `main.py` mounts `StaticFiles(directory=_STATIC_DIR, html=True)` **last, as the
catch-all**, so every URL that isn't `/api` or `/health` returns that same built file. One insertion
therefore *is* "every page," and a duplicate tag is not reachable by navigation — only by someone
adding a second block. The `branding/*.html` files are local concept mockups, are never deployed, and
**must not** be touched.

**On the insertion point.** "Immediately after `<head>`" is what Google documents and what Will asked
for, and it is safe here: the block pushes the charset declaration to roughly 420 bytes into the
document, well inside the **1024-byte window** the HTML spec requires for an encoding declaration.
Verify it rather than trusting the estimate — the DoD has the one-line check.

**The measurement ID is not a secret and must not be treated as one.** It ships in the response body
of every request by design (it is how the tag identifies the property). Do **not** make it a Vite env
var or a Fly build arg: it buys nothing and adds a deploy path that fails silently. Same reasoning as
the publishable Supabase key in the `Dockerfile`, opposite conclusion to the secret key.

### 2. The isolation module — `application/frontend/src/analytics.js` (new)

The only module in the codebase that knows Google exists. Views call `pageView` / `track` and stay
ignorant of the vendor — the same isolation `queries.js` gives data access, for the same reason.

```js
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
```

### 3. The call sites — `App.jsx` and `SignIn.jsx`

**Virtual pageviews (App.jsx).** `App` already owns both halves of what a "page" means here — `tab`
and the drill-down `stack` — so one effect covers all eight surfaces:

```js
const SURFACES = {
  league:   { path: '/league',   title: 'League' },
  matchups: { path: '/matchups', title: 'Matchups' },
  teams:    { path: '/teams',    title: 'Teams' },
  players:  { path: '/players',  title: 'Players' },
};
// Drill-downs are FLAT, not nested under the tab they were opened from: a player card opens from
// Players and from TeamDetail, a dossier from Teams and from TeamDetail. Nesting would split one
// thing's usage across several rows and make the ranking — the whole point — harder to read.
const DETAILS = {
  player:  { path: '/player-card',    title: 'Player card' },
  team:    { path: '/team-detail',    title: 'Team detail' },
  dossier: { path: '/dossier',        title: 'Manager dossier' },
  matchup: { path: '/matchup-detail', title: 'Matchup detail' },
};

const ready = !!slice;
useEffect(() => {
  if (!ready) return;   // don't count the pre-catalog "Loading…" state as a page
  const view = detail?.type ? DETAILS[detail.type] : SURFACES[tab];
  if (view) pageView(view.path, view.title);
}, [tab, detail?.type, ready]);
```

Two things in those deps are load-bearing:

- **`detail?.type`, never `detail.id`.** The id is a `sleeper_id` or a `roster_id` — high-cardinality,
  and in a 12-team league a roster id *names a person*. It must never leave the browser.
- **`slice.leagueId` is deliberately absent.** Switching league is not navigation; including it would
  re-fire a pageview for a surface the user never left.

**Sign-in funnel (App.jsx + SignIn.jsx).** Five parameterless events, so **no GA console setup is
required** — event names appear in Reports → Engagement → Events by themselves:

| Event | Where | Fires when |
| --- | --- | --- |
| `sign_in_opened` | `App.jsx`, the `onSignIn` handler on `<TopBar>` | the modal opens |
| `sign_in_submitted` | `SignIn.jsx`, in `submit()` after the guard, before the `await` | a real attempt is made |
| `sign_in_link_sent` | `SignIn.jsx`, on success (`setState('sent')`) | the API accepted the code |
| `sign_in_refused` | `SignIn.jsx`, in the `catch` | the API refused |
| `signed_in` | `App.jsx`, the `SIGNED_IN` branch of `onAuthStateChange` | the magic link completed |

`sign_in_refused` carries **no reason**: the server's refusal is deliberately uniform (it is not an
account-enumeration oracle), and leaking a finer-grained reason into a third-party analytics stream
would quietly undo that. Keep the honesty property; the count alone is the signal.

**`signed_in` must be verified, not assumed.** `onAuthStateChange` also emits on session restore, and
supabase-js has historically fired `SIGNED_IN` on ordinary page loads with a stored session — which
would make this event count *visits*, not sign-ins, and quietly inflate the last step of the funnel
above the step before it. **Prove it fires once per real sign-in and not on reload. If it over-fires,
delete it** and treat `sign_in_link_sent` as the terminal step. A funnel that lies is worse than a
funnel that stops one step early.

---

## Scope guardrails — what NOT to do

- **No `gtag` reference anywhere but `analytics.js` and `index.html`.** A view holding a third-party
  global is the same class of leak as a view holding a URL.
- **Never import `analytics.js` into `queries.js`, a transform, or anything server-side.** It is a
  browser-only, write-only side channel. It is **not** a third data seam and must not become one.
- **Never send an identifier.** Not an email, not the access code, not `league_id`, not
  `viewer_roster_id`, not a `sleeper_id`. This is both GA policy and the product's own posture.
- **Change no rendered output.** If a surface looks different afterwards, something is wrong.
- **Don't add a consent banner, a cookie notice, or a second vendor.** Out of scope — see *Known
  limits* for when consent stops being out of scope.
- **Don't touch `branding/*.html`.** Not the site.
- **Don't gate the tag on an env check** so it stays quiet in dev. A production-only code path is a
  path that is only ever exercised where you can't watch it. Dev traffic gets filtered **in GA**, not
  in code — see *Known limits*.

---

## Definition of done

1. `index.html` carries the block **once**, as the first children of `<head>`.
2. `src/analytics.js` exists and is the only file matching `gtag` under `src/`.
3. **Eight distinct virtual pageviews observed** in the network tab — one per tab, one per drill-down
   — each with the right path, and **no** hit for `/`.
4. **Four funnel events observed**; `signed_in` either demonstrated correct or removed with a note in
   this appendix saying it was.
5. **No console error and no broken render with `window.gtag` undefined** (the ad-blocker case).
6. **No visual change to any surface**, and `git diff --stat` shows only those four files.
7. **Verified on production after `fly deploy`**, not just locally.

## Verification — proof, not assertion

Per `CODING_BIBLE` §5 and the session guide: verify it yourself and show the artifact; don't ask Will
to check.

```bash
# exactly one tag; the ID appearing THREE times inside it (comment + src + config) is expected, not
# a duplicate. The tag count is the check that matters — the ID count is a weaker smoke test.
grep -c 'googletagmanager.com/gtag/js' application/frontend/index.html   # -> 1
grep -c 'G-J1F0BE5ZW4'                 application/frontend/index.html   # -> 3
# the charset declaration still lands inside the spec's 1024-byte window
head -c 1024 application/frontend/index.html | grep -c 'charset'          # -> 1
# nothing outside the module touches the vendor global
grep -rn 'gtag' application/frontend/src/                                 # -> analytics.js only
```

Then in the browser (`npm run dev`, DevTools Network filtered to `collect`, or the browser tools):

- Land, then walk all four tabs and open all four drill-downs. Each produces a
  `google-analytics.com/g/collect?…` hit carrying `tid=G-J1F0BE5ZW4`, `en=page_view`, and the
  expected path in `dl`. Capture the list — **eight rows is the artifact.**
- Open the sign-in modal and submit a **deliberately wrong access code**: expect `en=sign_in_opened`,
  `en=sign_in_submitted`, `en=sign_in_refused`, in that order.
- **The PII oracle — cheap and decisive:** assert that **no captured collect request contains an `@`**.
  That single check proves the email never left the browser, and it should be run against the full
  captured set, not a sample.
- In the console, set `window.gtag = undefined`, then switch tabs and open a card: **no error, no
  broken render.** That is the ad-blocker path, which is a large minority of real traffic.
- Reload the page while signed in and confirm `signed_in` does **not** fire (see above).

## Deploy + closedown

- **`fly deploy` is a separate gate from merge.** This touches `application/frontend/`, which is baked
  into the image at build time — merging to main changes nothing a visitor sees. A bare `fly deploy`
  from `application/` is correct (`fly.toml` carries the build args). Re-run the `grep` checks against
  the live HTML afterwards.
- **Closedown edits, and only these:** flip **Status** at the top of this appendix and re-stamp
  `Current as of`; flip the one **STATUS.md** bullet and the one **ARCHITECTURE.md** bullet from
  *briefed* to live, with the install date. Those two lines were pre-written by the PM session — edit
  them in place, **don't add a second note.**
- **No session doc.** A four-file measurement change does not earn a narrative in `sessions/`; this
  appendix is the record. One commit is enough — the 3-commit cap is a ceiling, not a target.

## What the install found (2026-08-10)

Verified against the dev server with a recorder over `sendBeacon`/`fetch`/`XHR`/`Image`, because GA4
**batches** several events into one POST — the request URL alone under-reports, and reading only
resource-timing entries would have shown three hits for eight pageviews.

**Proven.** Eight distinct virtual pageviews, right paths, **zero hits for `/`** — so
`send_page_view:false` does what it was chosen to do. All four funnel events in order
(`sign_in_opened` → `sign_in_submitted` → `sign_in_refused`, then `sign_in_link_sent`). The
**PII oracle passed decisively**: with `ga-install-test@example.com` typed into the form and rendered
on screen, **no captured request contained an `@`**, an id, or a `league_id`. With `window.gtag`
deleted, the player card rendered in full, zero sends, no console error — the ad-blocker path is
genuinely safe.

**Four corrections to the brief above.** They change the verification walk, not the design:

1. **The dossier has exactly one entry point** — `TeamDetail.jsx`'s Manager Dossier button. The brief
   said "from Teams and from TeamDetail"; `Teams.jsx` never receives `onOpenDossier`. The flat-`DETAILS`
   reasoning still holds, because the *player card* really does have two entry points.
2. **`/matchup-detail` is unreachable from the Matchups tab on desktop.** `Matchups.jsx` gates on
   `useIsMobile` (≤768px) and otherwise selects the two-pane's right side without touching the stack.
   Both real paths were verified: `TeamDetail`'s matchup button at desktop width, and a card tap at
   375px. Anyone re-running the eight-surface walk on a wide window will come up one short and it is
   not a bug.
3. **There is no `SIGNED_IN` branch** in `onAuthStateChange` — the real code is a combined
   `SIGNED_IN || SIGNED_OUT` branch that clears the slice. `signed_in` is a standalone line above it.
4. **The DoD's `grep -c 'G-J1F0BE5ZW4'` expected 2 but the brief's own comment carries the ID a third
   time.** Corrected to 3 above. `grep -c` on the tag URL is the check that actually means "one tag".

**Two additions.**

- **~~`pageView` dedupes on the last path sent.~~ REMOVED in P5/S2c.** The guard existed for one
  reason: supabase-js reports a tab *refocus* as `SIGNED_IN`, `App.jsx` treated that as an identity
  change, and nulling the slice re-fired the effect for a surface the user never left. S2c fixed
  that at the source — the identity epoch now bumps only when the user id actually changes — so the
  guard was suppressing a re-fire that no longer happens while quietly hiding any future one.
  Measured after the change: **five consecutive refocuses fire zero pageviews; three real tab clicks
  fire exactly three, all distinct.**
- **`sign_in_refused` is broader than its name.** `SignIn.jsx`'s `catch` swallows any throw, so a
  network failure or a cold Fly machine records it too. It means *"the attempt did not succeed"*, not
  *"the server said no"*. Still parameterless, so the no-enumeration-oracle property is intact.

**`signed_in` is installed but NOT yet proven, by construction.** S1b removed `emailRedirectTo`, so the
magic link always lands on Supabase's Site URL — a sign-in started on localhost completes on
**production**. The event is therefore unobservable in dev, and the brief's "reload while signed in"
test is also the wrong test: supabase-js 2.111.0 emits `INITIAL_SESSION` on a stored-session load, and
the live over-fire risk is **tab refocus**. Oracle needing no extra code: `SIGNED_IN` clears the slice
and bumps `identityEpoch`, firing a fresh `GET /api/leagues` and a "Loading…" flash. **On the next real
prod sign-in: blur the tab, wait ~15s, refocus. A second `/api/leagues` means it over-fires → delete
`signed_in` and make `sign_in_link_sent` terminal.** The pageview side of that is already absorbed by
the dedupe guard; the accompanying pop-out of an open drill-down is a pre-existing `App.jsx` bug,
unrelated to analytics.

**One thing GA does that this brief does not control.** Enhanced measurement is on for the property, so
GA4 sends its own `scroll` / outbound-click events — and they carry the **browser** URL (`/`), not the
virtual path, because they never pass through `analytics.js`. Harmless (the `page_view` stream is
clean), but "which surface was scrolled" is not a question this install can answer.

## Known limits — read before trusting a number

- **Ad blockers and Safari's tracking prevention will undercount**, plausibly 10–30% with a
  fantasy-football audience. Directional, never audit-grade, and it will never agree with server logs.
- **GA is not retroactive.** It sees nothing before the install date, and a parameter sees nothing
  before the day its custom dimension is registered.
- **Dev traffic counts.** `npm run dev` fires real hits into the live property. Fix it **in the GA
  console** — Admin → Data Streams → Configure tag settings → *Define internal traffic* (rule on
  localhost), then Data Settings → Data Filters → activate *Internal Traffic* — deliberately not in
  code.
- **Small-N thresholding.** With an invited cohort of tens, GA suppresses some breakdowns outright.
  Read this as "which surfaces are ignored entirely," not as precise ratios.
- **Consent.** GA4 sets first-party cookies and there is no consent UI. A US friends cohort is low
  risk; **an EU/UK user makes it a real obligation.** Not a blocker today — a **P6 launch-hardening
  checklist item** if the cohort widens beyond the invited group.
