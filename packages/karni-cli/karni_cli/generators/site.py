"""``karni make site <app>``: a public, server-rendered website as a Django app.

The site is a plain app: function views in ``views.py``, ``urls.py`` with
``app_name`` and a ``# karni:urls`` marker, the site's own HTML under
``templates/<app>/`` (plus ``templates/404.html`` and ``500.html``) and its
CSS under ``static/<app>/``. ``config/urls.py`` includes it at ``""``
through its own ``# karni:urls`` marker, so the home page replaces Karni's
welcome page. ``karni make view`` adds pages and ``karni import design``
fills the app from a designer's files (rule K309, docs/public-site.md).

The runtime a site needs comes from the ``karni-site`` module, never from
project code: ``{% ifactive %}`` for the current menu item, ``{% csp_hash %}``
for a design's inline scripts, and the error views that render the site's
own 404 and 500 pages with the request. The generator wires the module the
way ``karni add site`` does (the dependency, the ``# karni:apps`` entry)
when the project lacks it, and sets ``handler404`` and ``handler500`` in
config/urls.py.

``tests/test_pages.py`` passes a ``PAGES`` list to
``karni.testing.assert_pages``. ``karni make view`` adds each new URL above
its ``# karni:pages`` marker. A list, not routes read from ``urls.py``: a
site's urls.py also routes robots.txt, a sitemap, redirects and pages whose
path has a capture, and only the project knows a real URL for those.

A new app gets the ``karni make app`` skeleton as well. An existing local
app gets only the site files, and nothing it already has is truncated:
``views.py`` and ``urls.py`` are extended in place.
"""

from __future__ import annotations

import re
from pathlib import Path

import typer

from karni_cli import kinds
from karni_cli.commands.add import add_dependency_text, record_guidance
from karni_cli.generators import app as app_gen
from karni_cli.generators.core import (
    DRY_RUN_OPTION,
    SETTINGS,
    App,
    Workspace,
    local_apps,
    project_workspace,
)
from karni_cli.generators.naming import humanize, require_snake
from karni_cli.generators.pysource import (
    Import,
    append,
    call,
    comment,
    docstring,
    ensure_imports,
    parse,
    pystr,
    replace_or_append,
    top_level,
)
from karni_cli.project import CliError
from karni_cli.settings_edit import (
    MARKER,
    add_entry,
    block_entries,
    processors_block,
    wire_entries,
)
from karni_cli.urls_edit import URLS_MARKER, add_route, marker_line, routes

NAME = "site"
SUMMARY = 'Create a public site app (Django views, urls, templates, static) mounted at "/".'

CONFIG_URLS = Path("config") / "urls.py"
PYPROJECT = Path("pyproject.toml")
#: The module every site app loads its runtime from.
SITE_MODULE = "site"
SITE_APP = "karni_site"
SITE_DISTRIBUTION = "karni-site"
#: What pyproject.toml lists: the images extra (Pillow) makes the copies of uploaded images.
SITE_REQUIREMENT = "karni-site[images]"
#: The error views karni_site ships, set as Django's handlers in config/urls.py.
HANDLERS = (
    ("handler404", "karni_site.views.page_not_found"),
    ("handler500", "karni_site.views.server_error"),
)
#: The middleware that answers the redirects a client adds in the admin.
REDIRECT_MIDDLEWARE = "karni_site.middleware.RedirectMiddleware"
#: The context processor that puts the site's details (`site`) in every template.
SITE_PROCESSOR = "karni_site.context_processors.site"
#: What karni-site's manifest (karni_site/karni.module.toml) says each one is for.
REDIRECT_WHY = "the admin's redirects"
PROCESSOR_WHY = "`site`, the site's details, in every template"
PROCESSORS_HEADING = "# --- Public site (karni-site)"
PROCESSORS_BLOCK = processors_block(SITE_PROCESSOR, f"{PROCESSORS_HEADING}: {PROCESSOR_WHY} ----")
#: karni_site's own URLs (robots.txt, sitemap.xml, the form view), included at "" before the site.
SITE_URLS = "karni_site.urls"
#: The line in tests/test_pages.py that `karni make view` inserts page URLs above.
PAGES_MARKER = "# karni:pages"
#: The content file the page test loads (karni design extract -o, karni.testing.load_content).
SITE_CONTENT = "content/site.json"
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


def pages_test(app: App) -> Path:
    return app.file("tests", "test_pages.py")


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
            'is `karni make form` and {% karni_form "<name>" %} in a template.',
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
        "{% load static karni_site %}"
        "{# The site's details are `site`, edited in the admin. Its name starts as this: #}"
        f'{{% site_defaults name="{title}" %}}<!DOCTYPE html>\n'
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  {# The title, description, canonical link, share tags and JSON-LD (karni-site). The #}\n"
        "  {# tags inside are the defaults. The page test fails an empty description. #}\n"
        "  {% karni_seo %}<title>{% block title %}{{ site.name }}{% endblock %}</title>\n"
        '  <meta name="description" content="{% block description %}{% endblock %}">'
        "{% block seo %}{% endblock %}{% endkarni_seo %}\n"
        f'  <link rel="stylesheet" href="{{% static \'{app.label}/site.css\' %}}">\n'
        "  {% block head %}{% endblock %}\n"
        "</head>\n"
        "<body>\n"
        "  <header>\n"
        f"    <a href=\"{{% url '{app.label}:home' %}}\">{{{{ site.name }}}}</a>\n"
        "    {# Each link marks itself current with {% ifactive %} (karni-site). #}\n"
        '    <nav aria-label="Main">\n'
        f'      <a href="{{% url \'{app.label}:home\' %}}"{{% ifactive "{app.label}:home" %}}'
        ' aria-current="page"{% endifactive %}>Home</a>\n'
        "    </nav>\n"
        "  </header>\n"
        "  <main>\n"
        "    {% block content %}{% endblock %}\n"
        "  </main>\n"
        "  <footer>\n"
        '    <p>&copy; {% now "Y" %} {{ site.name }}</p>\n'
        "  </footer>\n"
        "</body>\n"
        "</html>\n"
    )


#: The description a generated page starts with. ``karni check --seo`` reports it as one to
#: write (SITE012), so it must stay karni_site.checks_seo.PLACEHOLDER_DESCRIPTION's text.
PLACEHOLDER_DESCRIPTION = "One sentence that search engines show under this page's title."


def page_source(app: App, title: str, description: str, body: str) -> str:
    return (
        f'{{% extends "{app.label}/base.html" %}}{{% load karni_site %}}\n'
        f"{{% block title %}}{title}{{% endblock %}}\n"
        f"{{% block description %}}{description}{{% endblock %}}\n"
        "{% block content %}\n"
        f"{body}"
        "{% endblock %}\n"
    )


def home_source(app: App) -> str:
    return page_source(
        app,
        "Home",
        PLACEHOLDER_DESCRIPTION,
        "  <h1>{{ site.name }}</h1>\n"
        "  {# Text a client may change is a block, edited in the admin (karni-site). #}\n"
        '  <p>{% editable "home.intro" %}This page is rendered by Django from '
        f"{app.label}/templates/{app.label}/home.html. Replace it with the site's own "
        f"markup. Its stylesheet is {app.label}/static/{app.label}/site.css."
        "{% endeditable %}</p>\n",
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


def server_error_source(app: App) -> str:
    return page_source(
        app,
        "Something went wrong",
        "The site could not show this page.",
        "  <h1>Something went wrong</h1>\n"
        "  <p>The site could not show this page. Please try again in a moment.</p>\n"
        f"  <p><a href=\"{{% url '{app.label}:home' %}}\">Back to the home page</a></p>\n",
    )


def css_source(app: App) -> str:
    return (
        f"/* {app.label}/static/{app.label}/site.css: the site's own stylesheet, served by\n"
        "   Django's staticfiles (collectstatic in production). Hand-written CSS belongs\n"
        "   here: the @karni/ui token rule (K206) applies to app screens only. */\n"
    )


def tests_source(app: App, line_length: int) -> str:
    """The site's page test: ``assert_pages`` over a ``PAGES`` list with a marker."""
    return (
        docstring(
            f"The {app.label} pages: each answers 200 with a title, a description and alt text "
            "on every image, its links reach pages that exist, and an unknown URL is a 404.",
            "",
            line_length,
        )
        + "\n\n"
        "from pathlib import Path\n\n"
        "import pytest\n"
        "from django.test import Client\n"
        "from karni.testing import assert_pages, load_content\n"
        "from pytest_django import Settings\n\n"
        + comment(
            "Every page of the site. `karni make view` adds each new URL above the marker. "
            "A path with a capture, such as /services/<slug:slug>/, needs a real URL here: "
            "one whose row content/site.json holds.",
            "",
            line_length,
        )
        + "\n"
        "PAGES = [\n"
        '    "/",\n'
        f"    {PAGES_MARKER}\n"
        "]\n\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def site_content(db: None, settings: Settings, tmp_path: Path) -> None:\n"
        + docstring(
            "The site's real content, so every page renders real rows: content/site.json "
            "(karni design extract), read from the project root. Nothing until it exists.",
            "    ",
            line_length,
        )
        + "\n"
        "    settings.MEDIA_ROOT = str(tmp_path)  # its images go to a folder the test owns\n"
        f'    load_content("{SITE_CONTENT}", missing_ok=True)\n\n\n'
        "@pytest.mark.django_db\n"
        "def test_every_page_passes_the_page_checks(client: Client) -> None:\n"
        "    assert_pages(client, PAGES)\n"
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


def add_page_to_test(ws: Workspace, app: App, url: str) -> None:
    """Insert ``"<url>",`` above the ``# karni:pages`` marker of the site's page test.

    The view is written either way: a missing test file or marker, or a URL
    with a capture, ends in a note that names the manual step.
    """
    path = pages_test(app)
    rel = ws.rel(path)
    entry = f"{pystr(url)},"
    if "<" in url:
        ws.note(
            f"page test: {url} has a capture, so it is not in {rel}. Add a real URL to PAGES "
            "there, and create the content that page shows in the test."
        )
        return
    manual = f"Add {pystr(url)} to the URLs that {rel} passes to assert_pages yourself."
    text = ws.read(path)
    lines = text.splitlines() if text is not None else []
    index = marker_line(lines, PAGES_MARKER)
    if text is None or index is None:
        missing = "not found" if text is None else f"has no `{PAGES_MARKER}` marker"
        ws.note(f"page test: {rel} {missing}. {manual}")
        return
    if any(line.strip() == entry for line in lines):
        return
    marker = lines[index]
    lines.insert(index, marker[: len(marker) - len(marker.lstrip())] + entry)
    ws.write(path, "\n".join(lines) + "\n")


def wire_config_urls(ws: Workspace, app: App) -> None:
    """Include the site at ``""`` in config/urls.py, before ``*welcome_urls()``."""
    rel = CONFIG_URLS.as_posix()
    entry = f'path("", include({pystr(app.module + ".urls")})),'
    text = ws.read(CONFIG_URLS)
    if text is None:
        raise CliError(f"{rel} not found. Run inside a Karni project.", code="C001")
    for route, _, include in routes(text):
        # karni_site's own URLs (the form view) live at "" next to the site's.
        if route == "" and include not in (None, f"{app.module}.urls", "karni_site.urls"):
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


def with_site_urls(text: str, filename: str) -> str | None:
    """config/urls.py ``text`` including karni_site's URLs before the site's own, ``None`` if it does.

    The include goes before the first ``path("", include(...))`` above the
    ``# karni:urls`` marker (the site), else at the marker, so a site's
    catch-all pattern never shadows robots.txt or sitemap.xml.

    :raises CliError: when the file has no marker (``C108``).
    """
    if any(include == SITE_URLS for _route, _name, include in routes(text)):
        return None
    entry = f'path("", include({pystr(SITE_URLS)})),'
    lines = text.splitlines()
    marker = marker_line(lines)
    if marker is None:
        raise CliError(
            f"No `{URLS_MARKER}` marker in {filename}. Add `{entry}` to urlpatterns before the "
            "site's own include yourself, or run `karni upgrade` to add the marker.",
            code="C108",
        )
    target = next(
        (
            index
            for index, line in enumerate(lines[:marker])
            if re.search(r"""path\(\s*["']{2}\s*,\s*include\(""", line)
        ),
        marker,
    )
    indent = lines[marker][: len(lines[marker]) - len(lines[marker].lstrip())]
    lines.insert(target, indent + entry)
    return "\n".join(lines) + "\n"


def wire_site_urls(ws: Workspace) -> None:
    """``path("", include("karni_site.urls"))`` in config/urls.py: robots.txt and sitemap.xml.

    A file without the ``# karni:urls`` marker gets a note naming the line to add.
    """
    rel = CONFIG_URLS.as_posix()
    text = ws.read(CONFIG_URLS)
    if text is None:
        raise CliError(f"{rel} not found. Run inside a Karni project.", code="C001")
    try:
        updated = with_site_urls(text, rel)
    except CliError as exc:
        ws.note(f"robots.txt and sitemap.xml: {exc.message}")
        return
    if updated is not None:
        ws.write(CONFIG_URLS, ensure_imports(ws, rel, updated, [Import("django.urls", "include")]))
        ws.note(f"{SITE_URLS}: included in {rel} (robots.txt, sitemap.xml, the form view)")


def wire_site_settings(text: str, filename: str) -> tuple[str, list[str]]:
    """Settings ``text`` with karni-site's redirect middleware and ``site`` context processor.

    The middleware goes into the ``# karni:middleware`` block, the context
    processor into a ``# karni:context_processors`` block appended once. Each
    is added only when the text does not name it yet. Returns the text and
    what changed (or what to add by hand). ``karni add site`` does the same
    from karni-site's manifest (:func:`karni_cli.settings_edit.wire_entries`).
    """
    return wire_entries(
        text,
        filename,
        middleware=[(REDIRECT_MIDDLEWARE, REDIRECT_WHY)],
        processors=[(SITE_PROCESSOR, PROCESSOR_WHY)],
        heading=PROCESSORS_HEADING,
    )


def wire_site_module(ws: Workspace) -> bool:
    """Wire karni-site the way ``karni add site`` does. Returns ``True`` when it was missing.

    The dependency goes into pyproject.toml and ``karni_site`` into the
    ``# karni:apps`` block, both through the workspace, and the project's kind
    gets its site (an app becomes a site+app, :func:`karni_cli.kinds.adopt_site_text`).
    The command records the module's agent guidance after the commit
    (:func:`record_site_guidance`).
    """
    settings_text = ws.read(SETTINGS)
    if settings_text is None:
        raise CliError(f"{SETTINGS.as_posix()} not found. Run inside a Karni project.", code="C001")
    added = False
    if SITE_APP not in block_entries(settings_text):
        updated = add_entry(
            settings_text,
            SITE_APP,
            setting="INSTALLED_APPS",
            marker=MARKER,
            filename=SETTINGS.as_posix(),
        )
        if updated is not None:
            settings_text = updated
            ws.write(SETTINGS, updated)
            added = True
    wired, wiring = wire_site_settings(settings_text, SETTINGS.as_posix())
    if wired != settings_text:
        ws.write(SETTINGS, wired)
    for note in wiring:
        ws.note(note)
    pyproject = ws.read(PYPROJECT)
    if pyproject is not None:
        updated = add_dependency_text(pyproject, SITE_REQUIREMENT)
        if updated is not None:
            ws.write(PYPROJECT, updated)
            added = True
        adopted = kinds.adopt_site_text(ws.read(PYPROJECT) or pyproject, ws.root)
        if adopted is not None:
            ws.write(PYPROJECT, adopted[0])
            ws.note(kinds.adoption_note(adopted[1], adopted[2]))
    if added:
        ws.note(
            f"{SITE_DISTRIBUTION}: added to pyproject.toml and INSTALLED_APPS (the site's "
            "template tags, error pages and editable content come from it). Install it "
            "(uv pip install -r pyproject.toml, or docker compose build), then karni migrate."
        )
    return added


def record_site_guidance(ws: Workspace) -> None:
    """After a commit: record karni-site's agent guidance, as ``karni add site`` does."""
    record_guidance(ws.root, SITE_MODULE)


def set_error_handlers(ws: Workspace) -> None:
    """``handler404`` and ``handler500`` in config/urls.py: karni_site's views, once."""
    rel = CONFIG_URLS.as_posix()
    text = ws.read(CONFIG_URLS)
    if text is None:
        raise CliError(f"{rel} not found. Run inside a Karni project.", code="C001")
    tree = parse(ws, rel, text)
    missing = [(name, view) for name, view in HANDLERS if top_level(tree, name) is None]
    if not missing:
        return
    block = comment(
        "The site's own error pages (templates/404.html and 500.html), rendered with the "
        "request by karni_site, which falls back to a plain page if one fails.",
        "",
        ws.line_length,
    )
    block += "\n" + "".join(f"{name} = {pystr(view)}\n" for name, view in missing)
    ws.write(CONFIG_URLS, append(text, block))


def ensure_runtime(ws: Workspace, app: App) -> None:
    """What every site app needs from karni-site: the module, the handlers, its URLs, the
    404 and 500 pages in the site's layout.

    Idempotent, so an app created before this existed gets the missing pieces
    (``karni make site <app> --force``, or ``karni import design``).
    """
    wire_site_module(ws)
    set_error_handlers(ws)
    wire_site_urls(ws)
    if not ws.exists(app.file("templates", "404.html")):
        ws.create(app.file("templates", "404.html"), not_found_source(app))
    if not ws.exists(app.file("templates", "500.html")):
        ws.create(app.file("templates", "500.html"), server_error_source(app))


def plan(ws: Workspace, name: str, *, register: bool = True, next_step: bool = True) -> App:
    """Plan the site app ``name`` (created, or an existing local app).

    ``next_step=False`` leaves out the "next:" note (``karni import design``
    runs this as its first step).
    """
    require_snake(name, "App name")
    app, _created = resolve_site_app(ws, name)
    ws.create_skeleton(
        {
            base_template(app): base_source(app),
            page_template(app, "home"): home_source(app),
            app.file("templates", "404.html"): not_found_source(app),
            app.file("templates", "500.html"): server_error_source(app),
            app.file("static", app.label, "site.css"): css_source(app),
            pages_test(app): tests_source(app, ws.line_length),
        }
    )
    if not ws.exists(app.file("tests", "__init__.py")):
        ws.create(app.file("tests", "__init__.py"), "")
    add_view(
        ws, app, "home", f"{app.label}/home.html", [], header=views_header(app, ws.line_length)
    )
    register_route(ws, app, "", "home")
    ensure_runtime(ws, app)
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
    if next_step:
        ws.note(
            f"next: karni import design <folder> --app {app.label} for a designer's pages, or "
            f"karni make view <name> --app {app.label} [--path /about/]"
        )
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
    NAME/templates/404.html and 500.html, NAME/static/NAME/site.css and
    NAME/tests/test_pages.py (assert_pages on every page in its PAGES list),
    then inserts `path("", include("NAME.urls"))` at the `# karni:urls`
    marker of config/urls.py, so the home page replaces the welcome page,
    and sets handler404 and handler500 there to karni_site's views. The
    site's runtime is the karni-site module: when the project lacks it, the
    dependency, the `# karni:apps` entry, its redirect middleware and its
    `site` context processor are added as `karni add site` would (then
    `karni migrate`). A new app also gets the `karni make app` skeleton and the
    `# karni:apps` entry. An existing app keeps every file it has (with
    --force, only the missing files are created). Add pages with `karni
    import design` or `karni make view`.
    """
    ws = project_workspace(force)
    plan(ws, name, register=not no_route)
    ws.commit(dry_run=dry_run)
    if not dry_run:
        record_site_guidance(ws)
