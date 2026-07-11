# Daily snapshot schedulers (launchd)

Two version-controlled launchd jobs run the daily snapshot fetchers on the machine's local
time (DST-aware). If the Mac is asleep at the scheduled time, the job runs at next wake. Each
`.plist` here is the canonical copy; the live copy lives at `~/Library/LaunchAgents/<label>.plist`.

> **Caveat — powered-off ≠ asleep (2026-07-11 audit).** "Runs at next wake" only covers *sleep*.
> If the Mac is **powered off** across the scheduled time, launchd skips the run entirely (no
> catch-up), and both APIs serve only "now" (no historical endpoint) — so that day is lost for good.
> Over a 41-day leaguelogs window this cost ~8 days (coverage 63% complete / 71% any-data). An
> off-laptop host is the real fix (see `READ_BUILD_ORDER.md` → *Daily-collector reliability*); the
> interim mitigation is multiple fire times/day so the laptop only needs to be awake once.

| Job | Label | Runs | Time (America/New_York) |
|---|---|---|---|
| Market values | `com.fantasyai.leaguelogs-snapshot` | `-m application.data.fetchers.leaguelogs snapshot` | 04:00 |
| Player news | `com.fantasyai.news-snapshot` | `-m application.data.fetchers.news snapshot` | 05:00 |

(News is offset from leaguelogs so the two daily fetchers don't overlap. Daily to start —
the cadence is tunable; bump it more frequent in-season by editing `StartCalendarInterval`.)

## Install / update

```sh
LABEL=com.fantasyai.news-snapshot        # or com.fantasyai.leaguelogs-snapshot

cp application/data/fetchers/scheduler/$LABEL.plist ~/Library/LaunchAgents/

# (re)load it
launchctl bootout  gui/$(id -u)/$LABEL 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$LABEL.plist
```

## Operate

```sh
LABEL=com.fantasyai.news-snapshot

# run it now (test)
launchctl kickstart -p gui/$(id -u)/$LABEL

# status / next run
launchctl print gui/$(id -u)/$LABEL | grep -E 'state|runs|nextfire'

# logs (kept outside ~/Documents — launchd can't write into the TCC-protected Documents folder)
tail -n 40 ~/Library/Logs/fantasy-ai/news.out.log ~/Library/Logs/fantasy-ai/news.err.log

# uninstall
launchctl bootout gui/$(id -u)/$LABEL
rm ~/Library/LaunchAgents/$LABEL.plist
```

## Notes / gotchas

- **Absolute Python path** in the plist is required — launchd runs with no user `PATH`.
  Python is the python.org 3.13 build (has polars + requests + feedparser). If Python is
  reinstalled/moved, update `ProgramArguments[0]` and reload both jobs.
- Each job runs its fetcher as a **package module** (`-m application.data.fetchers.<name>`)
  with `WorkingDirectory` set to the **repo root** — `python -m` puts the cwd on `sys.path`,
  so the `application` package resolves without an editable install. If the repo moves, update
  `WorkingDirectory` (and reload); it is hardcoded to this machine's checkout (`/Users/willdaniel/...`).
- Logs are under `~/Library/Logs/fantasy-ai/` (outside the repo). Snapshots append to
  `snapshots/leaguelogs/market_values.parquet` and `snapshots/news/player_news.parquet` (gitignored).
- The **news** job needs `feedparser` installed in that Python (`pip install feedparser`); the
  collector is otherwise self-contained (public RSS, no API key).
