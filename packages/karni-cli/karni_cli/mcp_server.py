"""``karni mcp`` — Karni's agent surface as MCP tools (stdio).

Tools: ``context`` (the ``karni context`` inventory), ``rules`` (the
conventions, one rule in full, or a procedure), ``check`` (static
violations for one file), and, for debugging, ``why`` / ``why_empty`` (``karni
why``: an access decision explained by the code that makes it), ``trace``,
``replay`` and ``explain_failure`` (the development capture under ``.karni/``),
``explain_text`` (``karni explain -`` on a pasted traceback or log line) and
``queries`` (``karni queries``: one endpoint's queries grouped by cause). The tool functions are plain functions so they are
testable without a client; :func:`build_server` registers them on the
official MCP Python SDK server (``pip install 'karni-cli[mcp]'``): ``MCPServer``
in mcp 2.x, ``FastMCP`` in mcp 1.x.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from karni_cli import agent_data
from karni_cli import explain_text as explain_text_mod
from karni_cli.adapters import module_fragments
from karni_cli.commands.context import build_context_text
from karni_cli.commands.queries import queries_args, run_queries
from karni_cli.commands.rules import check_text
from karni_cli.project import CliError, find_project
from karni_cli.rules_render import render_explain, render_procedure, render_rules

INSTRUCTIONS = (
    "Karni project tools. Call `context` and `rules` before any work and follow what they "
    "return; call `check` on every file you write. When a row, field or action is "
    "unexpectedly missing or refused, call `why` (or `why_empty`) before reading the access "
    "layer."
)

_project_override: Path | None = None


def _project() -> Path | None:
    return _project_override or find_project()


def context_tool() -> str:
    """Live project inventory: apps, models, viewsets, UI components, hooks, pages, modules."""
    project = _project()
    if project is None:
        return "error: not inside a Karni project (no manage.py found)."
    try:
        return build_context_text(project)
    except CliError as exc:
        return f"error: {exc}"


def rules_tool(code: str = "", procedure: str = "") -> str:
    """Karni conventions. No arguments: every rule's code + summary. ``code``: one rule in
    full (why + fix). ``procedure``: steps for new-model, new-page, add-module or new-module."""
    project = _project()
    try:
        data = agent_data.load(project)
    except CliError as exc:
        return f"error: {exc}"
    if code:
        rule = data.rule(code)
        return render_explain(rule) if rule else f"error: no rule {code!r}"
    if procedure:
        found = data.procedure(procedure)
        return render_procedure(found) if found else f"error: no procedure {procedure!r}"
    return render_rules(data, module_fragments(project) if project else {})


def check_tool(path: str) -> str:
    """Static check of one file against Karni's rules; returns violations with fixes."""
    project = _project()
    target = Path(path)
    if not target.is_absolute() and project is not None:
        target = project / target
    try:
        text, _count = check_text([target], project)
    except CliError as exc:
        return f"error: {exc}"
    return text


TOOLS: dict[str, Any] = {"context": context_tool, "rules": rules_tool, "check": check_tool}


# --- debugging: karni why (access decisions) ----------------------------------


def _params(params: str) -> list[str]:
    return [part.strip() for part in params.replace("&", " ").split() if part.strip()]


def _why(args_for: Any) -> str:
    from karni_cli.commands.why import run_why

    project = _project()
    if project is None:
        return "error: not inside a Karni project (no manage.py found)."
    try:
        code, out, err = run_why(args_for(), project=project)
    except CliError as exc:
        return f"error: {exc}"
    if code != 0:
        return f"error: {(err or out).strip()}"
    return out.rstrip("\n")


def why_tool(
    target: str,
    user: str = "",
    action: str = "",
    method: str = "",
    params: str = "",
    as_json: bool = False,
) -> str:
    """Why an API row, field or action is refused or missing for a user — run this before
    reading the access layer. ``target``: ``<resource>/<id>`` (a row), ``<resource>.<field>``
    (a field), ``<resource>`` (its list), or ``"403 <request-id>"`` (a recorded request).
    ``user``: email, username, pk or ``anonymous``. ``action``: view (default), update,
    delete, create, list or an @action. ``params``: query parameters, ``k=v&k2=v2``.
    Returns the decision computed by the enforcing code, where it is made, and the fix."""
    from karni_cli.commands.why import why_args

    head, _, rest = target.strip().partition(" ")
    return _why(
        lambda: why_args(
            head,
            rest.strip() or None,
            user=user or None,
            action=action or None,
            method=method or None,
            params=_params(params),
            as_json=as_json,
        )
    )


def why_empty_tool(resource: str, user: str, params: str = "", as_json: bool = False) -> str:
    """Why a user's list of ``resource`` is empty: the rows each step of the read pipeline
    removes (table, soft delete, the viewset's queryset, access.read part by part, the
    filters in ``params`` as ``k=v&k2=v2``), the step that empties it, and the fix."""
    from karni_cli.commands.why import why_empty_args

    return _why(
        lambda: why_empty_args(resource, user=user or None, params=_params(params), as_json=as_json)
    )


TOOLS.update({"why": why_tool, "why_empty": why_empty_tool})


# --- debugging: the development capture under .karni/ (karni_cli.debugging) ---


def _debug(args: list[str], database: Any = "load") -> str:
    from karni_cli.debugging import run_debug_command

    project = _project()
    if project is None:
        return "error: not inside a Karni project (no manage.py found)."
    try:
        return run_debug_command(project, args, database=database)
    except CliError as exc:
        return f"error: {exc}"


def trace_tool(request_id: str = "last", as_json: bool = False) -> str:
    """Follow one captured request (development, DEBUG on) in order: the request, the Celery
    tasks it enqueued and their retries, email, webhooks and change-log entries, with timings.
    ``request_id`` is the X-Request-ID response header, or ``last``. Use it instead of
    correlating log timestamps."""
    return _debug(["karni_trace", request_id, *(["--json"] if as_json else [])])


def replay_tool(
    request_id: str = "last",
    as_user: str = "",
    sets: list[str] | None = None,
    drop_redacted: bool = False,
    commit: bool = False,
) -> str:
    """Re-run a captured request against the current code, in-process, as its user or
    ``as_user`` (email, username or pk); returns the status and what changed ("was 403, now
    200"). Writes are rolled back unless ``commit``. Redacted values: ``sets`` ["field=value",
    "query:name=value"] or ``drop_redacted``. Use it to confirm a permission or bug fix."""
    from karni_cli.debugging import replay_args

    try:
        args = replay_args(
            request_id,
            as_user=as_user or None,
            sets=list(sets or []),
            drop_redacted=drop_redacted,
            commit=commit,
        )
    except CliError as exc:
        return f"error: {exc}"
    return _debug(args, database="connect")


def explain_failure_tool(failure_id: str = "last") -> str:
    """A captured failure (unhandled exception, DEBUG on) as a brief: who requested what, where
    it failed with the frame's locals, the exception and Karni code, the SQL, next steps.
    ``failure_id``: a failure id, a failed request's id, or ``last``. Read this before a
    traceback."""
    return _debug(["karni_failure", failure_id])


TOOLS.update({"trace": trace_tool, "replay": replay_tool, "explain_failure": explain_failure_tool})


# debugging: explain_text (karni explain -) and queries (karni queries)


def explain_text_tool(text: str) -> str:
    """Name the Karni failure in a pasted traceback, test failure or log line: class, cause,
    where (file:line), fix and docs link. Says plainly when it is not a failure Karni knows.
    Call it before reading a traceback by hand."""
    try:
        return explain_text_mod.render(text, project=_project())
    except CliError as exc:
        return f"error: {exc}"


def queries_tool(
    endpoint: str, as_user: str = "", method: str = "GET", data: str = "", explain: bool = False
) -> str:
    """Run one endpoint in-process as a user (email, username or pk; empty = anonymous) and
    report every SQL query: count and time, repeated queries grouped by cause (serializer
    field, relation, why the optimiser did not fetch it) and the exact fix. endpoint:
    /api/events/, events, events/<id> or EventViewSet.list. Writes are rolled back. Call it
    before hunting an N+1 in serializers."""
    project = _project()
    if project is None:
        return "error: not inside a Karni project (no manage.py found)."
    args = queries_args(endpoint, as_user or None, method, data or None, False, explain, False)
    try:
        code, out, err = run_queries(project, args)
    except CliError as exc:
        return f"error: {exc}"
    return out.rstrip("\n") if code == 0 else f"error: {(err or out).strip()}"


TOOLS |= {"explain_text": explain_text_tool, "queries": queries_tool}


def _server_class() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[attr-defined,unused-ignore]

        return FastMCP
    except ImportError:
        raise CliError(
            "karni mcp needs the MCP SDK: pip install 'karni-cli[mcp]'", code="C006"
        ) from None


def build_server(project: Path | None = None) -> Any:
    """The configured (not yet running) MCP server."""
    global _project_override
    _project_override = project
    server = _server_class()(name="karni", instructions=INSTRUCTIONS)
    for name, function in TOOLS.items():
        server.tool(name=name, description=function.__doc__)(function)
    return server
