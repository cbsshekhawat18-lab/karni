"""``karni make view <name> --app <site app> [--path /about/]``: a page of the public site.

Adds a function view to ``<app>/views.py``, a template under
``<app>/templates/<app>/`` that extends the site's ``base.html``, and the
URL at the ``# karni:urls`` marker of ``<app>/urls.py``. A path capture such
as ``/services/<slug:slug>/`` becomes a view parameter and a template
variable. The app must be a site app (``karni make site``).
"""

from __future__ import annotations

import re

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

NAME = "view"
SUMMARY = "Add a page to a site app: a function view, its template and its URL."

_SEGMENT = r"(?:[A-Za-z0-9_.\-]+|<(?:[a-z]+:)?[A-Za-z_][A-Za-z0-9_]*>)"
_PATH = re.compile(rf"^/(?:{_SEGMENT}(?:/{_SEGMENT})*/?)?$")
_CAPTURE = re.compile(r"<(?:([a-z]+):)?([A-Za-z_][A-Za-z0-9_]*)>")
#: Django path converter -> the view parameter's annotation.
_PARAM_TYPES = {"int": "int", "uuid": "uuid.UUID"}
#: Names the views module already uses.
_RESERVED = frozenset({"render", "request", "views", "urlpatterns", "app_name"})


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
        site_gen.page_source(
            app, title, "One sentence that search engines show under this page's title.", body
        ),
    )
    if register:
        site_gen.register_route(ws, app, route, name)
    else:
        ws.note(
            f"route not registered (--no-route): add path({route!r}, views.{name}, "
            f"name={name!r}) to urlpatterns in {ws.rel(app.file('urls.py'))} yourself."
        )
    ws.note(f"view: /{route} -> {app.module}.views.{name} ({app.label}:{name})")
    return f"/{route}"


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
    at the `# karni:urls` marker of APP/urls.py. The app must come from
    `karni make site`.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), name, path=path, register=not no_route)
    ws.commit(dry_run=dry_run)
