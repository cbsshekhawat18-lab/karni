"""``karni make site <app>``: a public, server-rendered website as a Django app.

The site is a plain app: function views in ``views.py``, ``urls.py`` with
``app_name`` and a ``# karni:urls`` marker, the site's own HTML under
``templates/<app>/`` (plus a ``templates/404.html``) and its CSS under
``static/<app>/``. ``config/urls.py`` includes it at ``""`` through its
own ``# karni:urls`` marker, so the home page replaces Karni's welcome
page. ``karni make view`` adds pages (rule K309, docs/public-site.md).

A new app gets the ``karni make app`` skeleton as well. An existing local
app gets only the site files, and nothing it already has is truncated:
``views.py`` and ``urls.py`` are extended in place.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from karni_cli.generators import app as app_gen
from karni_cli.generators.core import (
    DRY_RUN_OPTION,
    App,
    Workspace,
    local_apps,
    project_workspace,
)
from karni_cli.generators.naming import humanize, require_snake
from karni_cli.generators.pysource import (
    Import,
    call,
    docstring,
    ensure_imports,
    pystr,
    replace_or_append,
)
from karni_cli.project import CliError
from karni_cli.urls_edit import URLS_MARKER, add_route, routes

NAME = "site"
SUMMARY = 'Create a public site app (Django views, urls, templates, static) mounted at "/".'

CONFIG_URLS = Path("config") / "urls.py"
_APP_NAME = re.compile(r"""^app_name\s*=\s*["']([^"']+)["']""", re.MULTILINE)
#: What every page view needs.
VIEW_IMPORTS = [
    Import("django.http", "HttpRequest"),
    Import("django.http", "HttpResponse"),
    Import("django.shortcuts", "render"),
]


# paths


def base_template(app: App) -> Path:
    return app.file("templates", app.label, "base.html")


def page_template(app: App, name: str) -> Path:
    return app.file("templates", app.label, f"{name}.html")


# rendering


def view_block(name: str, template: str, params: list[tuple[str, str]], line_length: int) -> str:
    """A function view rendering ``template``. ``params`` are URL captures ``(name, type)``."""
    args = ["request: HttpRequest", *(f"{param}: {kind}" for param, kind in params)]
    head = f"def {name}({', '.join(args)}) -> HttpResponse:"
    if len(head) > line_length:
        head = f"def {name}(\n" + "".join(f"    {arg},\n" for arg in args) + ") -> HttpResponse:"
    render_args = ["request", pystr(template)]
    if params:
        render_args.append("{" + ", ".join(f"{pystr(param)}: {param}" for param, _ in params) + "}")
    return head + "\n" + call("return render", render_args, "    ", line_length) + "\n"


def views_header(app: App, line_length: int) -> str:
    return (
        docstring(
            f"{app.label}: the public website's pages, rendered from templates/{app.label}/ "
            "(`karni make view <name>`). Read content through each model's default manager "
            "(`Model.objects`), so model scopes apply, and filter drafts here. A public form "
            "posts to a BaseViewSet declared create=Public().",
            "",
            line_length,
        )
        + "\n"
    )


def urls_source(app: App, line_length: int) -> str:
    return (
        docstring(
            f'{app.label}: the public website\'s URLs, included at "" in config/urls.py.',
            "",
            line_length,
        )
        + "\n\n"
        "from django.urls import path\n\n"
        f"from {app.module} import views\n\n"
        f"app_name = {pystr(app.label)}\n\n"
        "urlpatterns = [\n"
        '    path("", views.home, name="home"),\n'
        f"    {URLS_MARKER}\n"
        "]\n"
    )


def base_source(app: App) -> str:
    title = humanize(app.label)
    return (
        "{% load static %}<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  {{# The site's name: here and in the header link below. #}}\n"
        f"  <title>{{% block title %}}{title}{{% endblock %}}</title>\n"
        '  <meta name="description" content="{% block description %}{% endblock %}">\n'
        "  {# The page's address without its query string, so ?utm_ links do not count twice. #}\n"
        '  <link rel="canonical" href="{{ request.scheme }}://{{ request.get_host }}{{ request.path }}">\n'
        f'  <link rel="stylesheet" href="{{% static \'{app.label}/site.css\' %}}">\n'
        "  {% block head %}{% endblock %}\n"
        "</head>\n"
        "<body>\n"
        "  <header>\n"
        f"    <a href=\"{{% url '{app.label}:home' %}}\">{title}</a>\n"
        '    <nav aria-label="Main">\n'
        f"      <a href=\"{{% url '{app.label}:home' %}}\">Home</a>\n"
        "    </nav>\n"
        "  </header>\n"
        "  <main>\n"
        "    {% block content %}{% endblock %}\n"
        "  </main>\n"
        "  <footer>\n"
        f'    <p>&copy; {{% now "Y" %}} {title}</p>\n'
        "  </footer>\n"
        "</body>\n"
        "</html>\n"
    )


def page_source(app: App, title: str, description: str, body: str) -> str:
    return (
        f'{{% extends "{app.label}/base.html" %}}\n'
        f"{{% block title %}}{title}{{% endblock %}}\n"
        f"{{% block description %}}{description}{{% endblock %}}\n"
        "{% block content %}\n"
        f"{body}"
        "{% endblock %}\n"
    )


def home_source(app: App) -> str:
    title = humanize(app.label)
    return page_source(
        app,
        "Home",
        "One sentence that search engines show under this page's title.",
        f"  <h1>{title}</h1>\n"
        "  <p>This page is rendered by Django from "
        f"{app.label}/templates/{app.label}/home.html. Replace it with the site's own "
        f"markup. Its stylesheet is {app.label}/static/{app.label}/site.css.</p>\n",
    )


def not_found_source(app: App) -> str:
    return page_source(
        app,
        "Page not found",
        "The page you were looking for is not here.",
        "  <h1>Page not found</h1>\n"
        "  <p>The page you were looking for has moved or no longer exists.</p>\n"
        f"  <p><a href=\"{{% url '{app.label}:home' %}}\">Back to the home page</a></p>\n",
    )


def css_source(app: App) -> str:
    return (
        f"/* {app.label}/static/{app.label}/site.css: the site's own stylesheet, served by\n"
        "   Django's staticfiles (collectstatic in production). Hand-written CSS belongs\n"
        "   here: the @karni/ui token rule (K206) applies to app screens only. */\n"
    )


def tests_source() -> str:
    return (
        '"""The public website renders."""\n\n'
        "import pytest\n\n\n"
        "@pytest.mark.django_db\n"
        "def test_home_renders(client):\n"
        '    response = client.get("/")\n'
        "    assert response.status_code == 200\n"
    )


# planning


def resolve_site_app(ws: Workspace, name: str) -> tuple[App, bool]:
    """The app ``name``: an existing local app, else a new one. Returns ``(app, created)``."""
    for app in local_apps(ws):
        if name in (app.label, app.module):
            return app, False
    app_gen.plan(ws, name, next_step=False)
    return App(name, name, ws.path(name)), True


def add_view(
    ws: Workspace,
    app: App,
    name: str,
    template: str,
    params: list[tuple[str, str]],
    *,
    header: str = "",
) -> None:
    """Add (or, with ``--force``, replace) the view ``name`` in ``<app>/views.py``."""
    path = app.file("views.py")
    rel = ws.rel(path)
    text = ws.read(path)
    if text is None:
        text = header
    imports = list(VIEW_IMPORTS)
    if any(kind == "uuid.UUID" for _, kind in params):
        imports.append(Import("uuid"))
    text = ensure_imports(ws, rel, text, imports)
    block = view_block(name, template, params, ws.line_length)
    ws.write(path, replace_or_append(ws, rel, text, name, block))


def register_route(ws: Workspace, app: App, route: str, name: str) -> None:
    """Insert ``path(route, views.name, name=name)`` at the marker of ``<app>/urls.py``."""
    path = app.file("urls.py")
    rel = ws.rel(path)
    entry = f"path({pystr(route)}, views.{name}, name={pystr(name)}),"
    text = ws.read(path)
    if text is None:
        ws.create(path, urls_source(app, ws.line_length))
        if name == "home" and route == "":
            return
        text = ws.read(path) or ""
    manual = f"Add `{entry}` to its urlpatterns yourself and re-run with --no-route."
    for existing_route, existing_name, _ in routes(text):
        if existing_route == route and existing_name == name:
            continue
        if existing_route == route or existing_name == name:
            raise CliError(
                f"{rel} already routes {route!r} (name {existing_name!r}). Choose another --path "
                "or view name, or remove the existing route.",
                code="C107",
            )
    declared = _APP_NAME.search(text)
    if declared is None or declared.group(1) != app.label:
        raise CliError(
            f"{rel} has no `app_name = {pystr(app.label)}`, and the site's templates reverse "
            f"`{app.label}:<name>`. Add that line and a `{URLS_MARKER}` line inside its "
            f"urlpatterns, then re-run. {manual}",
            code="C108",
        )
    updated = add_route(text, entry, filename=rel, manual=manual)
    if updated is not None:
        ws.write(path, updated)


def wire_config_urls(ws: Workspace, app: App) -> None:
    """Include the site at ``""`` in config/urls.py, before ``*welcome_urls()``."""
    rel = CONFIG_URLS.as_posix()
    entry = f'path("", include({pystr(app.module + ".urls")})),'
    text = ws.read(CONFIG_URLS)
    if text is None:
        raise CliError(f"{rel} not found. Run inside a Karni project.", code="C001")
    for route, _, include in routes(text):
        if route == "" and include not in (None, f"{app.module}.urls"):
            raise CliError(
                f'{rel} already includes {include!r} at "". One app answers the root. Remove '
                "that include, or add the site's pages to that app instead.",
                code="C107",
            )
    manual = (
        f"Add `{entry}` to urlpatterns in {rel} before `*welcome_urls()` yourself and re-run "
        "with --no-route, or run `karni upgrade` to add the marker."
    )
    text = ensure_imports(ws, rel, text, [Import("django.urls", "include")])
    updated = add_route(text, entry, filename=rel, manual=manual)
    if updated is not None:
        ws.write(CONFIG_URLS, updated)


def plan(ws: Workspace, name: str, *, register: bool = True) -> App:
    """Plan the site app ``name`` (created, or an existing local app)."""
    require_snake(name, "App name")
    app, _created = resolve_site_app(ws, name)
    ws.create_skeleton(
        {
            base_template(app): base_source(app),
            page_template(app, "home"): home_source(app),
            app.file("templates", "404.html"): not_found_source(app),
            app.file("static", app.label, "site.css"): css_source(app),
            app.file("tests", "test_pages.py"): tests_source(),
        }
    )
    if not ws.exists(app.file("tests", "__init__.py")):
        ws.create(app.file("tests", "__init__.py"), "")
    add_view(
        ws, app, "home", f"{app.label}/home.html", [], header=views_header(app, ws.line_length)
    )
    register_route(ws, app, "", "home")
    if register:
        wire_config_urls(ws, app)
    else:
        ws.note(
            f'route not registered (--no-route): add path("", include("{app.module}.urls")) '
            f"to urlpatterns in {CONFIG_URLS.as_posix()} before *welcome_urls() yourself."
        )
    ws.note(
        f"site: / -> {app.module}.views.home ({app.label}:home), templates in "
        f"{ws.rel(app.file('templates', app.label))}/, CSS in "
        f"{ws.rel(app.file('static', app.label))}/. It replaces the welcome page at /."
    )
    ws.note(f"next: karni make view <name> --app {app.label} [--path /about/]")
    return app


def command(
    name: str = typer.Argument(..., help="App label, snake_case (e.g. website)."),
    no_route: bool = typer.Option(
        False, "--no-route", help='Do not include the site at "" in config/urls.py.'
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Replace the home view and create only the missing files (existing ones are kept).",
    ),
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Create a public, server-rendered site app NAME and mount it at "/".

    Writes NAME/views.py (a home view), NAME/urls.py (app_name NAME, a
    `# karni:urls` marker), NAME/templates/NAME/base.html and home.html,
    NAME/templates/404.html, NAME/static/NAME/site.css and a page test, then
    inserts `path("", include("NAME.urls"))` at the `# karni:urls` marker of
    config/urls.py, so the home page replaces the welcome page. A new app
    also gets the `karni make app` skeleton and the `# karni:apps` entry. An
    existing app keeps every file it has. Add pages with `karni make view`.
    """
    ws = project_workspace(force)
    plan(ws, name, register=not no_route)
    ws.commit(dry_run=dry_run)
