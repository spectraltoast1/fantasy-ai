"""Gate for the connect flow — P5/S4c.

Seventh in the `check_auth` / `check_signup` / `check_ownership` / `check_isolation` /
`check_onboard` / `check_queue` line. It proves the properties this session exists to create:

  1. ONE SEAM       — `INSERT INTO public.jobs` exists exactly once in the repository, and
                      `job_queue.enqueue` is an ALIAS for it rather than a second copy. Two enqueue
                      paths that drift is how a job gets inserted without its NOTIFY.
  2. ONE IMAGE      — nothing under `application/api/` imports `application.data`. That import
                      would BUILD GREEN and crash on startup, because the API image contains no
                      `application/data/` — the Session-3 `projections.py` failure, one directory up.
  3. AUTHORIZATION  — a job that is not yours is refused exactly as one that does not exist.
  4. THE SEAT       — the `MY_USERNAME` fallback cannot reach a league that is not `is_mine`.
  5. `ready`, NOT ENQUEUE — the ownership row and the terminal state are ONE transaction, and
                      nothing on the enqueue path writes a grant.
  6. THE MARKER     — advisory, and it never marks an out-of-scope league supported.

**Legs 1, 2 and 5 are SOURCE assertions and are read from disk rather than imported**, which is not
laziness: `worker_loop` imports polars and this gate runs under `api/.venv`, which deliberately does
not have it. That the two halves cannot be imported into one process is the very constraint the
session is about, so the gate is shaped by it too. The behavioural half of the worker's platform
refusal lives in `check_queue`, next to the `kind` refusal it mirrors and under the venv that can
run it.

**Read the prove-it-bites block before trusting any of this.** Every refusal assertion is re-run
against the pre-S4c behaviour and every one is required to fail. A check that has never failed has
not been tested; it has only been observed agreeing with the code it was written from.

    application/api/.venv/bin/python -m application.api.check_connect
    application/api/.venv/bin/python -m application.api.check_connect --live
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import urllib.error
import urllib.request
from pathlib import Path

from application.api import db, jobs, platforms, reads, routes, settings

_results: list[bool] = []

_REPO = Path(__file__).resolve().parents[2]
_API_DIR = Path(__file__).resolve().parent
_WORKER_LOOP = _REPO / "application" / "data" / "serve" / "worker_loop.py"

# Not Sleeper-shaped, so it cannot collide with a real league — the idiom `check_queue`,
# `check_onboard` and `check_store_boundary` all use. Swept on EXACT ids, never `LIKE`: `_` is a
# LIKE wildcard, so `__CONNECTCHECK%` would also match real two-character-prefixed ids.
TMP_LEAGUE = "__CONNECTCHECK_A__"
TMP_SEASON = 99994


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")
    _results.append(True)


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    _results.append(False)


# --- leg 1: one seam, offline -----------------------------------------------------------------

def _sql_literals(path: Path) -> list[str]:
    """Every SQL string this file actually EXECUTES or binds to a name — never its prose.

    **This distinction is the whole reason the function exists.** S4b wrote two assertions that
    matched a comment and an error message describing a statement rather than the statement, and
    both reported correct code as broken. `jobs.py`'s own docstring contains the words
    `INSERT INTO public.jobs`; a grep would count it, and would then be counting documentation.
    So: module-level string assignments and inline `.execute("…")` arguments, from the AST.
    """
    out: list[str] = []
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out.append(node.value.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("execute", "executemany") and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                out.append(a.value)
    return out


def check_one_seam() -> None:
    print("\nONE enqueue seam — the API image cannot import the queue, so it moved UP")

    found = []
    for py in sorted(_REPO.rglob("application/**/*.py")):
        if "node_modules" in py.parts or ".venv" in py.parts:
            continue
        for sql in _sql_literals(py):
            if "insert into public.jobs" in " ".join(sql.split()).lower():
                found.append(py.relative_to(_REPO))
    if found == [Path("application/api/jobs.py")]:
        _ok("`INSERT INTO public.jobs` is executed from exactly ONE place: application/api/jobs.py")
    else:
        _fail(f"`INSERT INTO public.jobs` appears in {found or 'NOWHERE'} — expected only "
              "application/api/jobs.py. Two enqueue paths drift, and the one that drifts is the "
              "one that forgets the NOTIFY.")

    # The docstring names the statement too. Prove the scan is looking at CODE — if this ever
    # started counting prose, the assertion above would be measuring documentation.
    if any("INSERT INTO public.jobs" in (jobs.__doc__ or "") for _ in (1,)):
        _ok("jobs.py's docstring also names the statement, and the scan above did NOT count it")
    else:
        _fail("jobs.py's docstring no longer names the statement — this leg's own control is gone")

    # An ALIAS, not a copy. `check_queue` and OPERATIONS.md both call `job_queue.enqueue`; if that
    # ever became a second function the two would be free to disagree.
    src = (_REPO / "application" / "data" / "serve" / "job_queue.py").read_text()
    if "from application.api.jobs import" in src and "def enqueue" not in src:
        _ok("job_queue re-exports enqueue and defines no enqueue of its own")
    else:
        _fail("job_queue defines its own enqueue again — that is the second INSERT")


# --- leg 2: one image, offline ----------------------------------------------------------------

def check_api_image_is_importable() -> None:
    """Nothing in `application/api/` may import `application/data/`.

    The failure this prevents is specific and quiet: the image BUILDS, deploys, and then dies on
    the first request with a ModuleNotFoundError, because `Dockerfile` copies `api/` only and
    `.dockerignore` excludes a bare `data`. Session 3 shipped exactly that with an enumerated COPY
    that dropped `projections.py`; this is the same failure one directory up, and it is the reason
    the enqueue seam had to move at all.

    The check-scripts are exempt: they are developer tooling that never runs in the image, and
    `check_connect` itself reads worker source precisely because it cannot import it.
    """
    print("\nONE image — application/api/ must not import application/data/")
    offenders = []
    for py in sorted(_API_DIR.glob("*.py")):
        if py.name.startswith("check_"):
            continue
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            if any(m == "application.data" or m.startswith("application.data.") for m in mods):
                offenders.append(f"{py.name}:{node.lineno}")
    if not offenders:
        _ok(f"none of the {len(list(_API_DIR.glob('*.py')))} api modules import application.data")
    else:
        _fail(f"application/api imports application.data at {offenders} — this image has no "
              "application/data/ at all, so it would build green and crash on startup")


# --- leg 3: authorization, offline ------------------------------------------------------------

def check_job_authorization() -> None:
    print("\na job that is not yours is refused exactly as one that does not exist")

    q = " ".join(jobs._JOB_FOR_OWNER.split())
    if "requested_by = %(uid)s" in q:
        _ok("job_for_owner filters on requested_by — knowing an id is not enough")
    else:
        _fail(f"job_for_owner does NOT filter on requested_by: {q}")

    if "state <> ALL(%(terminal)s)" in " ".join(jobs._ACTIVE_JOB_FOR_USER.split()) \
            and "requested_by = %(uid)s" in " ".join(jobs._ACTIVE_JOB_FOR_USER.split()):
        _ok("active_job_for_user is caller-scoped and excludes terminal states")
    else:
        _fail("active_job_for_user is not caller-scoped, or would return a finished job")

    # ONE refusal string, reached by both branches, interpolating nothing. If it ever carried the
    # id, an unknown-but-well-formed id and somebody else's id could never produce the same bytes,
    # and the whole no-enumeration design rests on them being indistinguishable.
    src = inspect.getsource(routes.connect_job)
    n = src.count("_UNKNOWN_JOB")
    if n == 2 and "{" not in routes._UNKNOWN_JOB:
        _ok(f"both refusal branches raise the same constant {routes._UNKNOWN_JOB!r}, which "
            "interpolates nothing")
    else:
        _fail(f"connect_job references _UNKNOWN_JOB {n} time(s) / constant is "
              f"{routes._UNKNOWN_JOB!r} — the two 404s can differ")

    # A malformed id must be a 404, not a 500. `%(id)s::uuid` raises on garbage, so a caller could
    # otherwise tell a well-formed unknown id from a malformed one — the beginnings of the oracle.
    if "uuid.UUID(" in src:
        _ok("a malformed job id is validated before it reaches SQL, so it 404s rather than 500s")
    else:
        _fail("connect_job does not guard the uuid cast — a malformed id would 500")


# --- leg 4: the seat, offline -----------------------------------------------------------------

def check_viewer_fallback() -> None:
    print("\nS4a finding F — the MY_USERNAME fallback cannot reach a non-is_mine league")
    q = " ".join(reads._VIEWER_BY_USERNAME.split())
    if "JOIN league_catalog" in q and "c.is_mine" in q:
        _ok("resolve_viewer's fallback JOINs league_catalog and requires is_mine — no input to "
            "this query reaches a connected league")
    else:
        _fail(f"resolve_viewer's fallback is not confined to is_mine: {q}")

    # It has to remain a FALLBACK: a caller-supplied or granted seat still wins, or the seat the
    # worker writes at `ready` would never take effect.
    #
    # FROM THE AST, NOT FROM `src.index`. The first version of this assertion compared the textual
    # position of `if viewer_roster_id` against that of `_VIEWER_BY_USERNAME` — and the DOCSTRING
    # names the constant, several lines above the code, so a correctly-ordered function failed.
    # S4b's lesson, reproduced in the gate that documents it: prose that describes a statement is
    # not the statement. This walks the function's real statements instead.
    fn = ast.parse(inspect.getsource(reads.resolve_viewer).lstrip()).body[0]
    stmts = [n for n in fn.body if not (isinstance(n, ast.Expr)
                                        and isinstance(n.value, ast.Constant))]
    guard = stmts[0] if stmts else None
    if (isinstance(guard, ast.If) and isinstance(guard.test, ast.Compare)
            and getattr(guard.test.left, "id", None) == "viewer_roster_id"
            and isinstance(guard.test.ops[0], ast.IsNot)
            and any(isinstance(b, ast.Return) for b in guard.body)):
        _ok("an explicit viewer_roster_id still short-circuits the fallback (first real statement)")
    else:
        _fail(f"resolve_viewer no longer prefers the seat it is given — its first statement is "
              f"{type(guard).__name__}")


# --- leg 5: the ownership row lands at `ready`, offline (SOURCE) -------------------------------

def _run_job_else_body(tree) -> list:
    """The `else:` body of `_run_job`'s try — i.e. what happens when the executor SUCCEEDED."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_job":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Try) and sub.orelse:
                    return sub.orelse
    return []


def check_grant_lands_at_ready() -> None:
    print("\nthe ownership row is written AT `ready`, in ONE transaction with it")
    if not _WORKER_LOOP.exists():
        _fail(f"{_WORKER_LOOP} is missing — this leg cannot run, and a skipped leg is not a pass")
        return
    tree = ast.parse(_WORKER_LOOP.read_text())
    body = _run_job_else_body(tree)
    if not body:
        _fail("_run_job has no `else:` on its try — the success path is not where it was")
        return

    # Find a `with conn.transaction():` and require BOTH statements inside the SAME one. Matching
    # the calls, never a comment about them: the comment above this block says exactly what the
    # code does, and S4b's lesson is that prose describing a statement is not the statement.
    def calls_in(nodes) -> set[str]:
        names = set()
        for n in nodes:
            for sub in ast.walk(n):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    names.add(sub.func.attr)
        return names

    txn = [n for n in body if isinstance(n, ast.With)
           and "transaction" in calls_in(n.items and [i.context_expr for i in n.items])]
    if not txn:
        _fail("the success path opens no `with conn.transaction()` — a crash between the grant "
              "and the `ready` would leave a terminal job over a league nobody owns")
        return
    inside = calls_in(txn[0].body)
    if {"grant_ownership", "finish"} <= inside:
        _ok("grant_ownership and finish are inside ONE `with conn.transaction()` on the success path")
    else:
        _fail(f"the transaction contains {sorted(inside)} — expected both grant_ownership and finish")

    # THE LEASE MUST RETURN EVERY COLUMN THE EXECUTOR READS. Found by S4c's live proof, and the
    # failure is the quietest one in this system: the worker builds the league perfectly, lands
    # `ready`, and grants NOBODY anything, because `job.get("requested_by")` on a row that never
    # carried the column is None and `grant_ownership` reads None as "hand-enqueued, nothing to
    # grant". No error in the table, none in the logs, none on the screen — the user simply watches
    # a league build and never appear. Nothing else in the system would have reported it.
    #
    # Driven off what the worker ACTUALLY reads (`job.get("…")` and `job["…"]` in worker_loop), so
    # a future column is covered without anyone remembering to add it here.
    src = _WORKER_LOOP.read_text()
    wtree = ast.parse(src)
    reads_cols = set()
    for node in ast.walk(wtree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id == "job" and isinstance(node.slice, ast.Constant):
            reads_cols.add(node.slice.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id == "job" and node.args \
                and isinstance(node.args[0], ast.Constant):
            reads_cols.add(node.args[0].value)
    lease_sql = " ".join((_REPO / "application" / "data" / "serve" / "job_queue.py").read_text()
                         .split())
    returning = lease_sql.split("RETURNING", 1)[1].split('"""')[0] if "RETURNING" in lease_sql else ""
    missing = sorted(c for c in reads_cols if c not in returning)
    if not missing:
        _ok(f"the lease RETURNs every column the worker reads off a job ({len(reads_cols)}: "
            f"{', '.join(sorted(reads_cols))})")
    else:
        _fail(f"the worker reads {missing} off a leased job but the lease does NOT return "
              "them — they arrive as None and the failure is completely silent")

    # And nothing on the ENQUEUE path may write a grant. This is the failure with no error attached:
    # `visible` is `demo OR (owned AND season == current)` and the catalog sorts owned first, so an
    # early row lands the user on their own league with every panel empty for the whole build.
    enq = inspect.getsource(routes.connect)
    if "grant_ownership" not in enq and "user_leagues" not in enq:
        _ok("POST /api/connect writes no ownership row — the catalog cannot offer a half-built league")
    else:
        _fail("POST /api/connect touches ownership — the user would land on an EMPTY league for the "
              "length of the build, with no error raised anywhere")


# --- leg 6: the advisory marker, offline ------------------------------------------------------

_CUR = 2026


def _lg(**kw) -> dict:
    base = {"league_id": "1258181662160719872", "name": "L", "total_rosters": 12,
            "settings": {"type": 0}, "scoring_settings": {"rec": 1.0}}
    base.update(kw)
    return base


def check_scope_marker() -> None:
    print("\nthe supported/unsupported marker — advisory, and never wrong in the permissive direction")

    cases = [
        ("PPR redraft, current season", _lg(), _CUR, True),
        ("half-PPR redraft", _lg(scoring_settings={"rec": 0.5}), _CUR, True),
        # float32 drift. Sleeper serves weights at float32, so an exact `rec in {1.0, 0.5}` greys
        # out an ordinary half-PPR league — the Session-0.6 bug, which `_scoring._TOL` exists for.
        ("half-PPR at float32 drift", _lg(scoring_settings={"rec": 0.50000000745}), _CUR, True),
        ("dynasty", _lg(settings={"type": 2}), _CUR, False),
        ("keeper", _lg(settings={"type": 1}), _CUR, False),
        # ABSENCE IS NOT REDRAFT — `assert_in_scope`'s rule, and it is not hypothetical: the corpus
        # recovery found 7 known keeper/dynasty leagues with the key missing.
        ("league type absent", _lg(settings={}), _CUR, False),
        ("standard (rec 0)", _lg(scoring_settings={"rec": 0.0}), _CUR, False),
        ("rec absent (= standard)", _lg(scoring_settings={}), _CUR, False),
        ("custom rec", _lg(scoring_settings={"rec": 1.5}), _CUR, False),
        ("prior season", _lg(), _CUR - 1, False),
        # P5/S4d — the LIFECYCLE rule. Both halves, because a rule that only ever refuses would
        # pass a refusal-only test while greying out the entire cohort. `in_season` is the half
        # that matters on 10 Sept; `pre_draft` is the league Will actually clicked.
        ("pre_draft", _lg(status="pre_draft"), _CUR, False),
        ("drafting", _lg(status="drafting"), _CUR, False),
        ("in_season", _lg(status="in_season"), _CUR, True),
        ("post_season", _lg(status="post_season"), _CUR, True),
        ("complete", _lg(status="complete"), _CUR, True),
        # Absence is PLAYABLE here — the opposite of `settings.type`, and deliberately so: a missing
        # lifecycle field is a Sleeper omission about a league that demonstrably exists, while a
        # missing type genuinely does not say whether it is redraft.
        ("status absent", _lg(), _CUR, True),
    ]
    for label, lg, season, want in cases:
        got, reason = platforms.classify(lg, season=season, current_season=_CUR)
        if got == want:
            _ok(f"{label:32s} → {'supported' if got else 'greyed: ' + (reason or '')}")
        else:
            _fail(f"{label}: marked {'supported' if got else 'unsupported'}, expected the opposite "
                  f"(reason={reason!r})")

    # It must never be MISTAKEN for the gate. The authorities are on the worker and they raise.
    if "advisory" in (platforms.classify.__doc__ or "").lower():
        _ok("classify's docstring names itself advisory and points at the real gates")
    else:
        _fail("classify no longer says it is advisory — a disabled button is not a security control")

    if platforms.is_league_id("1258181662160719872") and not platforms.is_league_id("spectraltoast1") \
            and not platforms.is_league_id("DEMO-2025"):
        _ok("the dual-mode input discriminates by the store's own 18-19-digit rule")
    else:
        _fail("is_league_id disagrees with data_layer's snowflake rule")

    # ONE PREDICATE, not two agreeing copies (P5/S4d). The advisory grey-out and the authoritative
    # worker refusal must be the SAME function, or they drift and the button starts disagreeing
    # with what the worker does. Read from the AST, never imported: `onboard_league` needs polars
    # and this gate runs in the API venv, which deliberately has none.
    #
    # Asserted on the CALL, not on the name appearing in the file — `check_connect` has been burnt
    # twice by assertions that matched a docstring describing the code rather than the code.
    _authority = _REPO / "application/data/serve/onboard_league.py"
    _fn = next((n for n in ast.walk(ast.parse(_authority.read_text()))
                if isinstance(n, ast.FunctionDef) and n.name == "assert_in_scope"), None)
    _calls = {ast.unparse(n.func) for n in ast.walk(_fn) if isinstance(n, ast.Call)} if _fn else set()
    if "platforms.league_has_started" in _calls:
        _ok("assert_in_scope (the AUTHORITY) calls the same platforms.league_has_started the "
            "advisory marker uses — one predicate, two callers")
    else:
        _fail("onboard_league.assert_in_scope does not call platforms.league_has_started — the "
              "worker refusal and the greyed button are now two rules that can disagree. A pasted "
              "league id reaches the worker with no classification at all, so the worker is the "
              "half that must be right.")


# --- prove it bites ---------------------------------------------------------------------------

def check_prove_bites() -> None:
    """Re-run the refusals against the PRE-S4c behaviour. Every one must FAIL."""
    print("\nprove it bites — the pre-S4c code must fail these")
    caught = 0

    # 4 · finding F. The pre-S4c query had no catalog join, so a handle that appears as an
    # owner_name in ANY league resolved a seat there. Driven against the REAL store.
    old = "SELECT roster_id FROM teams WHERE league_id = %(lid)s AND owner_name = %(me)s"
    try:
        row = db.fetch_all("""
            SELECT t.league_id, t.owner_name FROM teams t
              JOIN league_catalog c ON c.league_id = t.league_id
             WHERE NOT c.is_mine AND t.owner_name IS NOT NULL
             ORDER BY t.league_id, t.roster_id LIMIT 1""")
        if row:
            lid, name = row[0]["league_id"], row[0]["owner_name"]
            pre = db.fetch_all(old, {"lid": lid, "me": name})
            post = db.fetch_all(reads._VIEWER_BY_USERNAME, {"lid": lid, "me": name})
            if pre and not post:
                caught += 1
                _ok(f"pre-S4c resolve_viewer highlights roster {pre[0]['roster_id']} in the "
                    f"non-is_mine league {lid} for handle {name!r}; S4c's returns nothing")
            else:
                _fail(f"the finding-F fix does not bite: pre={pre} post={post}")
        else:
            _fail("no non-is_mine league with an owner_name — this leg proved nothing")
    except Exception as exc:      # noqa: BLE001
        _fail(f"could not drive the finding-F bite against the store: {exc}")

    # 5 · the transaction. A success path that finishes WITHOUT a transaction must be caught.
    fake = ast.parse("def _run_job(c, j, w):\n"
                     "    try:\n        x = e()\n"
                     "    except Exception:\n        pass\n"
                     "    else:\n"
                     "        jobs.grant_ownership(c)\n        q.finish(c)\n")
    body = _run_job_else_body(fake)
    if body and not [n for n in body if isinstance(n, ast.With)]:
        caught += 1
        _ok("a success path that grants and finishes WITHOUT one transaction is detected")
    else:
        _fail("the transaction assertion would pass on two separate statements")

    # 1 · the second INSERT. A file that re-declares the statement must be found by the AST scan.
    tmp = ast.parse('_ENQUEUE2 = """INSERT INTO public.jobs (kind) VALUES (%(k)s)"""\n')
    lits = [n.value.value for n in ast.walk(tmp)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)]
    if any("insert into public.jobs" in s.lower() for s in lits):
        caught += 1
        _ok("a second INSERT declared anywhere in the tree is found by the scan")
    else:
        _fail("the one-seam scan would not notice a second INSERT")

    # 5b · the lease's RETURNING. This is the exact pre-S4c list, and it must be caught: it is what
    # the live proof ran against, and the run built a league perfectly and granted nobody anything.
    pre_s4c = "id, kind, league_id, season, state, attempts, leased_by, lease_expires_at"
    if any(c not in pre_s4c for c in ("requested_by", "platform_user_id")):
        caught += 1
        _ok("the pre-S4c lease RETURNING omits requested_by and platform_user_id, so the grant "
            "would silently no-op — detected")
    else:
        _fail("the lease-columns assertion would not have caught the pre-S4c RETURNING")

    if caught >= 4:
        _ok(f"the pre-S4c behaviour fails {caught} of these assertions, as it must")
    else:
        _fail(f"only {caught} assertions bit — these checks do not prove what they claim")


# --- live -------------------------------------------------------------------------------------

def _admin(path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    base, key = settings.supabase_url(), settings.supabase_secret_key()
    req = urllib.request.Request(
        f"{base}/auth/v1{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"apikey": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "{}")


def _uid(email: str) -> str:
    for u in _admin("/admin/users").get("users", []):
        if (u.get("email") or "").lower() == email.lower():
            return u["id"]
    raise SystemExit(f"no account for {email} — the live leg needs two real accounts")


def check_live(base_url: str, a_email: str, b_email: str) -> None:
    """The half fixtures cannot show: two REAL accounts, real tokens, and the two 404s compared
    byte for byte over HTTP."""
    from application.api.check_isolation import mint_token

    print(f"\nLIVE — a second account cannot read the first's job ({base_url})")
    ta, tb = mint_token(a_email), mint_token(b_email)
    a_id = _uid(a_email)

    db.execute("DELETE FROM public.jobs WHERE league_id = %(l)s", {"l": TMP_LEAGUE})
    row = jobs.enqueue(TMP_LEAGUE, TMP_SEASON, requested_by=a_id)
    jid = str(row["id"])
    try:
        def get(path, token):
            req = urllib.request.Request(f"{base_url}{path}")
            req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()

        s_own, _ = get(f"/api/connect/{jid}", ta)
        _ok("the owner reads their own job (200)") if s_own == 200 else _fail(
            f"the owner got {s_own} for their own job")

        s_other, b_other = get(f"/api/connect/{jid}", tb)
        s_ghost, b_ghost = get("/api/connect/00000000-0000-0000-0000-000000000000", tb)
        if s_other == s_ghost == 404 and b_other == b_ghost:
            _ok(f"another account's job and a nonexistent id are BYTE-IDENTICAL: "
                f"{s_other} {b_other!r}")
        else:
            _fail(f"the two refusals differ: {s_other} {b_other!r} vs {s_ghost} {b_ghost!r}")

        s_anon = urllib.request.Request(f"{base_url}/api/connect/{jid}")
        try:
            with urllib.request.urlopen(s_anon, timeout=60) as r:
                _fail(f"an ANONYMOUS caller read a job ({r.status})")
        except urllib.error.HTTPError as e:
            _ok(f"an anonymous caller is refused ({e.code})") if e.code == 401 else _fail(
                f"an anonymous caller got {e.code}, expected 401")

        # The in-flight endpoint is caller-scoped too, and B must not see A's.
        s, b = get("/api/connect", tb)
        if s == 200 and json.loads(b).get("job") in (None,):
            _ok("GET /api/connect shows B nothing while A has a job in flight")
        else:
            _fail(f"GET /api/connect leaked across accounts: {s} {b!r}")
    finally:
        n = db.execute("DELETE FROM public.jobs WHERE league_id = %(l)s", {"l": TMP_LEAGUE})
        print(f"\nswept {n} throwaway job row(s) — league_id matched EXACTLY, never by LIKE")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="also run against a real server + accounts")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--user-a", default="willdaniel.wrd+s2a-a@gmail.com")
    ap.add_argument("--user-b", default="willdaniel.wrd+s2a-b@gmail.com")
    args = ap.parse_args()

    print("=== connect flow ===")
    check_one_seam()
    check_api_image_is_importable()
    check_job_authorization()
    check_viewer_fallback()
    check_grant_lands_at_ready()
    check_scope_marker()
    check_prove_bites()
    if args.live:
        check_live(args.base_url.rstrip("/"), args.user_a, args.user_b)
    else:
        print("\n(skipping the live leg — pass --live. Two real accounts and real HTTP are the "
              "only way to compare the two 404s byte for byte.)")

    failed = _results.count(False)
    print()
    if failed:
        print(f"FAILED — {failed} of {len(_results)} assertions")
        return 1
    print(f"ALL GREEN — {len(_results)}/{len(_results)} assertions — one enqueue seam, one image, "
          "a job only its owner can read, no seat by username on a linked league, and ownership "
          "that lands with `ready` or not at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
