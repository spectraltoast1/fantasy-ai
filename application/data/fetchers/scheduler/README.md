# LeagueLogs daily snapshot scheduler (launchd)

Runs `python -m application.data.fetchers.leaguelogs snapshot` once a day at
**04:00 America/New_York** (DST-aware, since launchd uses the machine's local time).
If the Mac is asleep at 04:00, the job runs at next wake.

`com.fantasyai.leaguelogs-snapshot.plist` is the canonical copy (version-controlled).
The live copy lives at `~/Library/LaunchAgents/com.fantasyai.leaguelogs-snapshot.plist`.

## Install / update

```sh
cp application/data/fetchers/scheduler/com.fantasyai.leaguelogs-snapshot.plist \
   ~/Library/LaunchAgents/

# (re)load it
launchctl bootout  gui/$(id -u)/com.fantasyai.leaguelogs-snapshot 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fantasyai.leaguelogs-snapshot.plist
```

## Operate

```sh
# run it now (test)
launchctl kickstart -p gui/$(id -u)/com.fantasyai.leaguelogs-snapshot

# status / next run
launchctl print gui/$(id -u)/com.fantasyai.leaguelogs-snapshot | grep -E 'state|runs|nextfire'

# logs (kept outside ~/Documents — launchd can't write into the TCC-protected Documents folder)
tail -n 40 ~/Library/Logs/fantasy-ai/leaguelogs.out.log ~/Library/Logs/fantasy-ai/leaguelogs.err.log

# uninstall
launchctl bootout gui/$(id -u)/com.fantasyai.leaguelogs-snapshot
rm ~/Library/LaunchAgents/com.fantasyai.leaguelogs-snapshot.plist
```

## Notes / gotchas

- **Absolute Python path** in the plist is required — launchd runs with no user `PATH`.
  Python is the python.org 3.13 build (has polars + requests). If Python is
  reinstalled/moved, update `ProgramArguments[0]` and reload.
- The job runs the fetcher as a **package module** (`-m application.data.fetchers.leaguelogs`)
  with `WorkingDirectory` set to the **repo root** — `python -m` puts the cwd on `sys.path`,
  so the `application` package resolves without an editable install. If the repo moves, update
  `WorkingDirectory` (and reload); it is hardcoded to this machine's checkout (`/Users/willdaniel/...`).
- Logs are under `logs/` (gitignored). Snapshots append to
  `snapshots/leaguelogs/market_values.parquet` (gitignored).
