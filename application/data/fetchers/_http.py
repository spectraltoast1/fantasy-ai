"""
Shared HTTP resilience layer — the ONE path every fetcher's network I/O routes through.

Separation of concerns: retry / backoff / throttle / per-item isolation live here, once, so every
collector gets a consistent, resilient fetch process instead of each re-implementing (or omitting) it.
Ported from `sleeper._get_json` (the fullest of the three prior impls); `news`/`leaguelogs` migrate onto
it. It does NOT decide *when* a collection runs — that meter stays external (launchd now, GitHub Actions
at deployment). It only makes each call robust.

- `get()` / `get_json()` — a GET with a bounded timeout, exponential-backoff-with-jitter retry on
  TRANSIENT failures (timeouts, connection errors, 5xx), and immediate raise on a 4xx (a client error
  like a 404 is meaningful, not transient — e.g. Sleeper's "manager never played that season").
- `set_throttle()` — a process-wide min-gap between calls (the manager-activity fan-out raises it to be
  polite across hundreds of requests); default 0 = off, so single-shot callers are unaffected.
- `isolate()` — run a per-item unit (fetch + persist) for each item, catching + logging + continuing on
  failure, so one dead feed/profile can't abort a whole run. Returns the failures (the resilience floor).
"""

import random
import time

import requests

# Defaults (a general-purpose JSON API); callers override per source.
TIMEOUT = 15.0     # seconds per request
RETRIES = 4        # total attempts before giving up
BACKOFF = 0.5      # base backoff seconds (grows exponentially, plus jitter)

_throttle_seconds = 0.0   # min gap between calls; set_throttle() raises it for a fan-out
_last_call = 0.0


def set_throttle(seconds: float) -> None:
    """Set the minimum gap enforced between calls across this process (0 disables)."""
    global _throttle_seconds
    _throttle_seconds = max(0.0, seconds)


def get(url: str, *, params=None, headers=None, timeout: float = TIMEOUT,
        retries: int = RETRIES, backoff: float = BACKOFF, throttle: bool = True) -> requests.Response:
    """GET `url`, returning the `requests.Response`, with throttle + timeout + retry/backoff.

    Retries TRANSIENT failures (request timeouts, connection errors, and 5xx responses) with
    exponential backoff + jitter, raising the last error after `retries` attempts. A 4xx raises
    immediately and is NOT retried. Returns the Response so the caller chooses `.json()` (JSON APIs)
    or `feedparser.parse(resp.content)` (RSS). Honors the process throttle unless `throttle=False`.
    """
    global _last_call
    last_exc = None
    for attempt in range(retries):
        if throttle and _throttle_seconds:
            gap = time.monotonic() - _last_call
            if gap < _throttle_seconds:
                time.sleep(_throttle_seconds - gap)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc                       # transient network failure -> retry
        else:
            _last_call = time.monotonic()
            if 400 <= resp.status_code < 500:
                resp.raise_for_status()          # client error -> raise now, not transient
            if resp.status_code < 400:
                return resp                      # success
            last_exc = requests.HTTPError(       # 5xx -> transient, retry
                f"{resp.status_code} Server Error for url: {url}", response=resp)
        if attempt < retries - 1:
            time.sleep(backoff * (2 ** attempt) + random.uniform(0.0, backoff))
    raise last_exc


def get_json(url: str, *, params=None, headers=None, timeout: float = TIMEOUT,
             retries: int = RETRIES, backoff: float = BACKOFF, throttle: bool = True):
    """`get()` + `.json()` — the convenience path for JSON APIs (sleeper, leaguelogs)."""
    return get(url, params=params, headers=headers, timeout=timeout, retries=retries,
               backoff=backoff, throttle=throttle).json()


def isolate(items, do_item, *, label: str = "item", describe=str) -> list[tuple]:
    """Run `do_item(item)` for each item, isolating failures so one can't abort the whole run.

    `do_item` performs the FULL per-item unit (fetch + persist + stats) — its exceptions are caught,
    logged, and the loop continues to the next item. Returns the list of `(item, exception)` failures
    so the caller can report the resilience floor (e.g. "N/M feeds ok"). Persist inside `do_item` (not
    after) so an isolated failure never discards items already collected this run. `describe(item)`
    formats the item for the failure log (default `str`).
    """
    failures = []
    for it in items:
        try:
            do_item(it)
        except Exception as exc:   # noqa: BLE001 — isolation is the whole point: never abort the run
            failures.append((it, exc))
            print(f"  [{label}] FAILED {describe(it)}: {type(exc).__name__} — {exc}")
    return failures
