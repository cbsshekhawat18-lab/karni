"""``karni make view <name> --app <site app> [--path /about/]``: a page of the public site.

Adds a function view to ``<app>/views.py``, a template under
``<app>/templates/<app>/`` that extends the site's ``base.html``, the URL at
the ``# karni:urls`` marker of ``<app>/urls.py``, and the URL at the
``# karni:pages`` marker of ``<app>/tests/test_pages.py``, so the page test
checks the new page. A path capture such as ``/services/<slug:slug>/``
becomes a view parameter and a template variable. Such a page is left out
of the test with a note, because only the project knows a real URL for it.
The app must be a site app (``karni make site``).

A view with a capture usually replaces the per-page views of one folder (a
model's detail pages becoming one view). A ``{% ifactive %}`` that names
those views (``"website:services_web"``, ``"website:services_*"``) would mark
nothing once they are gone, so the command rewrites it to the folder's
path pattern (``"/services/*"``), which covers the new view's pages and the
old ones alike, and says where. ``karni check`` (``SITE002``) names any
``{% ifactive %}`` left naming a view that no longer exists.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from fnmatch import fnmatchcase

import typer

from karni_cli.generators import site as site_gen
from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.naming import humanize, require_snake
from karni_cli.project import CliError
from karni_cli.urls_edit import routes

NAME = "view"
SUMMARY = "Add a page to a site app: a function view, its template and its URL."

_SEGMENT = r"(?:[A-Za-z0-9_.\-]+|<(?:[a-z]+:)?[A-Za-z_][A-Za-z0-9_]*>)"
_PATH = re.compile(rf"^/(?:{_SEGMENT}(?:/{_SEGMENT})*/?)?$")
_CAPTURE = re.compile(r"<(?:([a-z]+):)?([A-Za-z_][A-Za-z0-9_]*)>")
#: Django path converter -> the view parameter's annotation.
_PARAM_TYPES = {"int": "int", "uuid": "uuid.UUID"}
#: Names the views module already uses.
_RESERVED = frozenset({"render", "request", "views", "urlpatterns", "app_name"})
_IFACTIVE = re.compile(r"\{%-?\s*ifactive\s+(?P<args>.*?)\s*-?%\}", re.DOTALL)
_ARG = re.compile(r"\"([^\"]*)\"|'([^']*)'|(\S+)")


def route_for(name: str, path: str | None) -> tuple[str, list[tuple[str, str]]]:
    """``(route, params)``: the ``path()`` route (no leading slash) and its captures."""
    text = path if path is not None else f"/{name}/"
    if not _PATH.match(text):
        raise CliError(
            f"--path {text!r} must look like /about/ or /services/<slug:slug>/.", code="C106"
        )
    route = text.strip("/")
    if route:
        route += "/"
    params = [
        (param, _PARAM_TYPES.get(kind or "str", "str")) for kind, param in _CAPTURE.findall(route)
    ]
    if len({param for param, _ in params}) != len(params):
        raise CliError(f"--path {text!r} captures one name twice.", code="C106")
    return route, params


def plan(
    ws: Workspace, app: App, name: str, *, path: str | None = None, register: bool = True
) -> str:
    """Plan the view ``name`` in ``app``. Returns its URL, with the leading slash."""
    require_snake(name, "View name")
    if name in _RESERVED:
        raise CliError(f"View name {name!r} is taken in views.py. Choose another.", code="C103")
    base = site_gen.base_template(app)
    if not ws.exists(base):
        raise CliError(
            f"{app.label} is not a site app ({ws.rel(base)} is missing). Run "
            f"`karni make site {app.label}` first.",
            code="C105",
        )
    route, params = route_for(name, path)
    template = f"{app.label}/{name}.html"
    site_gen.add_view(
        ws, app, name, template, params, header=site_gen.views_header(app, ws.line_length)
    )
    title = humanize(name)
    body = f"  <h1>{title}</h1>\n"
    for param, _ in params:
        body += f"  <p>{param}: {{{{ {param} }}}}</p>\n"
    ws.create(
        site_gen.page_template(app, name),
        site_gen.page_source(app, title, site_gen.PLACEHOLDER_DESCRIPTION, body),
    )
    if register:
        site_gen.register_route(ws, app, route, name)
        site_gen.add_page_to_test(ws, app, f"/{route}")
        keep_current_marking(ws, app, route)
    else:
        ws.note(
            f"route not registered (--no-route): add path({route!r}, views.{name}, "
            f"name={name!r}) to urlpatterns in {ws.rel(app.file('urls.py'))} yourself, and "
            f"its URL to PAGES in {ws.rel(site_gen.pages_test(app))}."
        )
    ws.note(f"view: /{route} -> {app.module}.views.{name} ({app.label}:{name})")
    return f"/{route}"


def _folder(route: str) -> str:
    """``services/`` for ``services/<slug:slug>/``: the static part before the first capture."""
    if "<" not in route:
        return ""
    head = route.split("<", 1)[0]
    return head if head.endswith("/") and head != "/" else ""


def keep_current_marking(ws: Workspace, app: App, route: str) -> None:
    """Rewrite ``{% ifactive %}`` names of the views a capture view replaces to its folder.

    The replaced views are the app's routes inside the new route's folder
    without a capture (``services/web/`` for ``services/<slug:slug>/``). A
    name of one of them, or a wildcard that matches only them, becomes the
    folder's path pattern ``"/services/*"``. Every template of the app is
    read, the menus' seed templates too.
    """
    folder = _folder(route)
    if not folder:
        return
    found = routes(ws.read(app.file("urls.py")) or "")
    names = {f"{app.label}:{n}" for _r, n, include in found if n and include is None}
    replaced = {
        f"{app.label}:{n}"
        for r, n, include in found
        if n and include is None and r.startswith(folder) and r != folder and "<" not in r
    }
    if not replaced:
        return
    pattern = f"/{folder}*"

    def stale(value: str) -> bool:
        if value in replaced:
            return True
        if any(char in value for char in "*?["):
            hits = {candidate for candidate in names if fnmatchcase(candidate, value)}
            return bool(hits) and hits <= replaced
        return False

    templates = app.file("templates")
    for path in sorted(templates.rglob("*.html")) if templates.is_dir() else []:
        text = ws.read(path)
        if text is None or "ifactive" not in text:
            continue
        updated, dropped = _rewrite_markers(text, stale, pattern)
        if updated != text:
            ws.write(path, updated)
            ws.note(
                f"current page: {{% ifactive %}} in {ws.rel(path)} named "
                f"{', '.join(sorted(set(dropped)))}, the pages /{route} replaces: now "
                f'"{pattern}", which marks them all. Delete those views and karni check '
                "(SITE002) names any {% ifactive %} still naming them."
            )


def _rewrite_markers(
    text: str, stale: Callable[[str], bool], pattern: str
) -> tuple[str, list[str]]:
    """``text`` with each stale pattern of its ``{% ifactive %}`` tags replaced by ``pattern``."""
    dropped: list[str] = []

    def rewrite(match: re.Match[str]) -> str:
        bits = list(_ARG.finditer(match.group("args")))
        values = [next(g for g in b.groups() if g is not None) for b in bits]
        gone = [value for value in values if stale(value)]
        if not gone:
            return match.group(0)
        dropped.extend(gone)
        kept = [b.group(0) for b, value in zip(bits, values, strict=True) if not stale(value)]
        if pattern not in values:
            kept.append(f'"{pattern}"')
        return "{% ifactive " + " ".join(kept) + " %}"

    return _IFACTIVE.sub(rewrite, text), dropped


def command(
    name: str = typer.Argument(..., help="View name, snake_case (e.g. about)."),
    app: str | None = APP_OPTION,
    path: str | None = typer.Option(
        None,
        "--path",
        help="URL path (default /<name>/). Captures such as /services/<slug:slug>/ become "
        "view parameters.",
    ),
    no_route: bool = typer.Option(
        False, "--no-route", help="Do not register the URL in <app>/urls.py."
    ),
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a page NAME to the site app APP: a view, its template and its URL.

    Writes `def NAME(request)` in APP/views.py, APP/templates/APP/NAME.html
    extending the site's base.html, and `path(..., views.NAME, name="NAME")`
    at the `# karni:urls` marker of APP/urls.py. The URL also goes into
    PAGES at the `# karni:pages` marker of APP/tests/test_pages.py, so
    assert_pages checks the page (a path with a capture needs a real URL
    there, which the command asks for). The app must come from `karni make
    site`.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name, path=path, register=not no_route)
    ws.commit(dry_run=dry_run)
