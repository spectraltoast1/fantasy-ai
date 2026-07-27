# Session 1 — Hosting + Database Setup (a runbook for Will)

**Last reviewed:** 2026-07-24 · **Status:** Ready to run · **Owner:** Will (this session is mostly *you*, not Code)

> **What this session does:** stand up your two rented cloud services — a **Fly.io** app host and a
> **Supabase** Postgres database — and prove an empty skeleton deploys and connects. Nothing about the
> app changes; this is pure plumbing. Auth, multi-league, and new scoring formats are all deliberately
> *later*. This is Session 1 of the store migration in
> `MULTI_LEAGUE_STORE_MIGRATION.md` (Stage A).
>
> **The split:** **Part A** is you alone in a browser (create accounts, grab credentials). **Part B** is a
> short Code session where Code builds and deploys the skeleton while you approve one login and hand over
> the credentials you saved. Budget **~1 hour total.**

---

## Decisions I made for you (override any of these if you want)

- **Names:** Supabase project = `fantasy-ai`. The Fly app name is chosen by Code during deploy — you don't pick it.
- **Region:** **US-East** for both — Supabase "East US (North Virginia)" and Fly `iad` (Ashburn, VA). Closest to you in NY, and it keeps the two services fast talking to each other.
- **Which database connection to use:** the **Session Pooler** string (it works from anywhere; the "Direct" option needs newer networking that can silently fail). Code will use this one.

---

## Part A — Your solo setup (browser only, ~30 min, no code)

### A1 · Create the Supabase project
- [ ] Go to **supabase.com**, sign up (GitHub or email is fine), create an organization (free) if it asks.
- [ ] **New project** → Name it `fantasy-ai` → Region **East US (North Virginia)** → let it **generate a database password**.
- [ ] **Save that password in your password manager right now.** Supabase does not show it again, and you'll need it. (It's resettable later, but save yourself the hassle.)
- [ ] Wait ~2 minutes for it to finish setting up.

✅ **Done when:** the project dashboard loads and shows the project as healthy.

### A2 · Grab the connection string
- [ ] In the project, click the **Connect** button at the top of the dashboard.
- [ ] Find the **Session pooler** option and copy its connection string. It looks like:
      `postgresql://postgres.[ref]:[YOUR-PASSWORD]@aws-...pooler.supabase.com:5432/postgres`
- [ ] Save that string next to the password in your password manager. (It contains a `[YOUR-PASSWORD]` placeholder — that's where the password you saved goes; Code will slot it in.)
- [ ] *Optional, while you're already here* (saves a trip when auth comes later): from **Project Settings → API**, also copy the **Project URL**, the **anon** key, and the **service_role** key, and save them. Not used this session.

✅ **Done when:** you have the Session-pooler string **and** the password saved somewhere safe.

### A3 · Create the Fly.io account
- [ ] Go to **fly.io** and sign up.
- [ ] **Add a payment card when asked.** Fly requires a card at signup even though your real usage is a few dollars a month — it's their anti-abuse measure, not an upfront charge.
- [ ] Stop there — don't create an app. Code does that in Part B.

✅ **Done when:** you can log into the Fly dashboard.

> **Safety note:** your `.gitignore` already ignores `.env` and `config.py`, so these secrets can't get committed by accident. Keep the password and keys in your password manager for now; don't paste them into any chat window. In Part B they go into a local `.env` file that never leaves your machine.

---

## Part B — The Code build session (~30 min; Code drives, you approve one thing)

Run this as a normal session per your `SESSION_GUIDE`: fresh worktree → `scripts/worktree-setup.sh` → work → update `STATUS.md` → `scripts/worktree-close.sh --merge` → push.

**Kick it off by pasting Code the brief in the next section.** Here's what Code will do, so you can follow along:

1. Install the Fly command-line tool (`flyctl`).
2. Run `fly auth login` — **your browser opens; you click approve.** *This is the one moment Code needs you mid-session.*
3. Scaffold a tiny FastAPI app under `application/api/` with a single `/health` endpoint.
4. Create a local `.env` — you paste in the Supabase connection string + password you saved.
5. Confirm the app runs locally and can reach the Supabase database (a trivial test query).
6. `fly launch` + deploy the skeleton to Fly (region `iad`), storing the database URL as a Fly secret.
7. Open the live URL, confirm `/health` responds and that it can connect to Supabase.
8. Update `STATUS.md`, merge, push.

✅ **Session 1 is DONE when:** there's a **live Fly URL** returning a healthy `/health` check, connected to your (still-empty) **Supabase** database; your secrets are saved and wired; and `STATUS.md` records it. That's the foundation Sessions 2–6 build on.

---

## The brief to paste to Code (Part B)

```
Goal: Session 1 of the store migration (see project_management/scope docs/future work/
MULTI_LEAGUE_STORE_MIGRATION.md, Stage A). Stand up the hosting + database FOUNDATION only —
no app features, no auth, no multi-league. This is a skeleton whose only job is to prove the
Fly <-> Supabase path works.

Context I've already done: created a Supabase Postgres project (region US-East / N. Virginia) and
a Fly.io account (card added). I have the Supabase SESSION-POOLER connection string and DB password
saved and will paste them when you ask. Target region for both is US-East (Fly: iad).

Follow our SESSION_GUIDE (fresh worktree, scripts/worktree-setup.sh, 3-commit cap, update STATUS.md,
scripts/worktree-close.sh --merge, push). Steps:
1. Install flyctl; run `fly auth login` (I'll approve in the browser).
2. Scaffold a minimal FastAPI app at application/api/ with a /health endpoint and a small db module
   that connects to Postgres via an env var DATABASE_URL. Load it from a gitignored .env — never
   hardcode secrets.
3. Ask me to paste the Supabase session-pooler connection string (with my password) into .env.
   Confirm the app runs locally and can open a Supabase connection (a `SELECT 1` is enough).
4. `fly launch` (pick an app name; region iad), set DATABASE_URL as a Fly secret, deploy.
5. Verify the live URL's /health returns OK and the app can reach Supabase from Fly. Show me the URL
   and the check result.
6. Update STATUS.md with what shipped and the next move (Session 2: define Postgres tables + build the
   parquet->Postgres loader), then close/merge.

Do NOT touch the existing frontend or data pipeline. Keep it minimal.
```

---

## Notes / what might trip you up

- **The Fly card is expected, not a scam.** A few dollars a month at your scale; the free-ish usage still wants a card on file.
- **Supabase won't show the password twice** — that's why A1 says save it immediately. Lost it? Reset it under Project Settings → Database and re-save.
- **Use the Session-pooler string, not Direct.** Direct needs IPv6 and can fail from some hosts; the pooler just works.
- **Free Supabase projects pause after ~a week idle.** If the health check mysteriously fails weeks from now, un-pause the project in the dashboard.
- **The frontend does NOT go live this session.** This is only the plumbing skeleton — your real app keeps running the old way until Session 5. Don't expect to see anything that looks like your dashboard yet.
