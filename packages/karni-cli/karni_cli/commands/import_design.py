"""``karni import design <dir> --app <app>``: a designer's static pages become the site.

The folder's HTML, CSS, JavaScript and images become a site app with the
design kept as written: the files are copied unchanged under
``static/<app>/``, the markup every page shares becomes ``base.html`` (and
partials), each page becomes a template extending it with a view and a
route, links and asset paths become ``{% url %}`` and ``{% static %}``, a
meta-refresh stub becomes a permanent redirect, and the current menu item
is marked with ``{% ifactive %}`` wherever the designer marked it. The
planning is :mod:`karni_cli.design.site`; this command applies the plan to
the project through the generators' workspace and reports what it did and
what it could not map.

``.karni/design.json`` records the import. A second run with a new version
of the design reports what changed, writes the files the project has not
edited since the import, and keeps the edited ones (``--force`` replaces
them). ``--diff`` reports and writes nothing.

``--editable`` makes every text, image, menu and contact detail editable in
the admin (:mod:`karni_cli.design.editable`). The record remembers it, so a
later import stays editable until ``--no-editable``. ``--map <file>`` names
the content map ``karni design analyze`` wrote: what it reads into rows gets
no blocks (:mod:`karni_cli.design.regions`), and the record remembers it too.

:func:`run` is the command's work on any workspace (``karni new --design``
calls it).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import typer

from karni_cli.design import compare
from karni_cli.design import images as design_images
from karni_cli.design import site as design_site
from karni_cli.design.site import DESIGN_RECORD, SitePlan
from karni_cli.generators import site as site_gen
from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    SETTINGS,
    App,
    Workspace,
    local_apps,
    project_workspace,
)
from karni_cli.generators.naming import require_snake
from karni_cli.generators.pysource import (
    Import,
    call,
    ensure_imports,
    parse,
    pystr,
    top_level,
)
from karni_cli.project import CliError
from karni_cli.urls_edit import add_route, routes

import_app = typer.Typer(
    help="Import a designer's files into the project.",
    no_args_is_help=True,
    add_completion=False,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _design_dir(directory: Path) -> Path:
    if not directory.is_dir():
        raise CliError(
            f"{directory} is not a directory. Pass the folder that holds the design's "
            "HTML pages (index.html, about.html, ...).",
            code="C111",
        )
    return directory.resolve()


def _site_app(ws: Workspace, name: str | None) -> App:
    """The site app to import into: an existing local app, else one created now."""
    apps = local_apps(ws)
    if name is None:
        if len(apps) == 1:
            name = apps[0].label
        else:
            listing = ", ".join(app.label for app in apps) or "none yet"
            raise CliError(
                f"Which app? Pass --app <label> (local apps: {listing}). A new label creates "
                "the site app.",
                code="C102",
            )
    require_snake(name, "App name")
    app = next((app for app in apps if name in (app.label, app.module)), None)
    if app is None or not ws.exists(site_gen.base_template(app)):
        return site_gen.plan(ws, name, next_step=False)
    site_gen.ensure_runtime(ws, app)
    return app


def _placeholders(app: App) -> dict[str, str]:
    """What ``karni make site`` writes: an unchanged placeholder may be replaced."""
    return {
        "templates/" + app.label + "/base.html": site_gen.base_source(app),
        "templates/" + app.label + "/home.html": site_gen.home_source(app),
        "templates/404.html": site_gen.not_found_source(app),
        "templates/500.html": site_gen.server_error_source(app),
    }


class _Writer:
    """Writes the plan's files, keeping what the project edited since the last import."""

    def __init__(self, ws: Workspace, app: App, record: dict[str, Any] | None) -> None:
        self.ws = ws
        self.app = app
        self.recorded: dict[str, str] = dict((record or {}).get("files", {}))
        self.placeholders = _placeholders(app)
        self.hashes: dict[str, str] = {}
        self.kept: list[str] = []

    def may_write(self, rel: str, current: bytes | None) -> bool:
        """``rel`` (project-relative) may be replaced: new, unchanged since the import,
        an untouched placeholder, or ``--force``."""
        if current is None or self.ws.force:
            return True
        digest = _sha256(current)
        if self.recorded.get(rel) == digest:
            return True
        app_rel = rel.removeprefix(self.ws.rel(self.app.path) + "/")
        placeholder = self.placeholders.get(app_rel)
        if placeholder is not None and placeholder.encode("utf-8") == current:
            return True
        self.kept.append(rel)
        if rel in self.recorded:
            self.hashes[rel] = self.recorded[rel]
        return False

    def template(self, app_rel: str, content: str) -> None:
        path = self.app.file(*app_rel.split("/"))
        rel = self.ws.rel(path)
        existing = self.ws.read(path)
        current = existing.encode("utf-8") if existing is not None else None
        if not self.may_write(rel, current):
            return
        if current == content.encode("utf-8"):
            self.hashes[rel] = _sha256(current)
            return
        self.ws.write(path, content)
        self.hashes[rel] = _sha256(content.encode("utf-8"))

    def asset(self, design_path: str, source: Path) -> tuple[Path, Path] | None:
        """The copy to make for an asset, or ``None`` when it is current or kept."""
        target = self.app.file("static", self.app.label, *design_path.split("/"))
        rel = self.ws.rel(target)
        data = source.read_bytes()
        digest = _sha256(data)
        current = target.read_bytes() if target.is_file() else None
        if current == data:
            self.hashes[rel] = digest
            return None
        if not self.may_write(rel, current):
            return None
        self.hashes[rel] = digest
        return source, target


def _add_views(ws: Workspace, app: App, plan: SitePlan) -> None:
    path = app.file("views.py")
    text = ws.read(path) or ""
    tree = parse(ws, ws.rel(path), text)
    for name, template in plan.views:
        existing = top_level(tree, name)
        if existing is not None and not ws.force:
            continue  # the view is there (a re-import, or the home view karni make site wrote)
        site_gen.add_view(
            ws, app, name, template, [], header=site_gen.views_header(app, ws.line_length)
        )
        text = ws.read(path) or ""
        tree = parse(ws, ws.rel(path), text)


def _redirect_entry(route: str, target: str, name: str, line_length: int) -> str:
    """The redirect's ``path(...)`` entry, split the way ruff format splits it (no indent)."""
    view_args = [target, "permanent=True", "query_string=True"]
    view = f"RedirectView.as_view({', '.join(view_args)})"
    flat = call("path", [route, view, f"name={name}"], "    ", line_length, tail=",")
    if all(len(line) <= line_length for line in flat.splitlines()):
        return "\n".join(line.removeprefix("    ") for line in flat.splitlines())
    nested = call("RedirectView.as_view", view_args, " " * 8, line_length, tail=",")
    lines = ["path(", f"    {route},", *(line[4:] for line in nested.splitlines())]
    return "\n".join([*lines, f"    name={name},", "),"])


def _add_redirects(ws: Workspace, app: App, plan: SitePlan) -> None:
    if not plan.redirects:
        return
    path = app.file("urls.py")
    rel = ws.rel(path)
    text = ws.read(path)
    if text is None:
        return
    text = ensure_imports(ws, rel, text, [Import("django.views.generic", "RedirectView")])
    ws.write(path, text)
    for redirect in plan.redirects:
        target = (
            f"url={pystr(redirect.to)}"
            if redirect.external
            else f"pattern_name={pystr(f'{app.label}:{redirect.to}')}"
        )
        entry = _redirect_entry(pystr(redirect.route), target, pystr(redirect.name), ws.line_length)
        text = ws.read(path) or ""
        clash = next(
            (
                (route, name)
                for route, name, _ in routes(text)
                if (route == redirect.route) != (name == redirect.name)
            ),
            None,
        )
        if clash is not None:
            raise CliError(
                f"{rel} already routes {clash[0]!r} (name {clash[1]!r}), which the redirect "
                f"from {redirect.source} needs. Remove that route or rename the page.",
                code="C107",
            )
        updated = add_route(
            text,
            entry,
            filename=rel,
            manual=f"Add `{entry}` to its urlpatterns yourself.",
        )
        if updated is not None:
            ws.write(path, updated)


def _theme_from_css(ws: Workspace, plan: SitePlan, *, dry_run: bool) -> None:
    """Theme the staff app and the admin from the design's CSS (``karni ui detect --css``)."""
    from karni_cli.commands import ui

    css = [path for name, path in plan.assets.items() if name.lower().endswith(".css")]
    if not css:
        return
    # A project without a staff app themes only its admin (KARNI_THEME_CSS).
    what = "staff app theme" if ws.is_dir("frontend") else "admin theme"
    try:
        outcome = ui.detect_from_css(ws.root, css, dry_run=dry_run)
    except CliError as exc:
        ws.note(f"{what}: not detected ({exc.message}). Run `karni ui detect --css`.")
        return
    if outcome:
        ws.note(f"{what}: {outcome}")


def _write_image_copies(
    ws: Workspace, app: App, plan: SitePlan, record: dict[str, Any] | None
) -> None:
    """The WebP copies the plan's srcsets name, next to each image under static/<app>/.

    A copy is made again only when its image changed since the last import
    (or the copy is missing). Needs Pillow, which the plan checked.
    """
    if not plan.copies:
        return
    before = ((record or {}).get("assets") or {}).get("files") or {}
    now = (plan.design.get("assets") or {}).get("files") or {}
    static = app.file("static", app.label)
    made = 0
    for path, width, target in design_images.copy_targets(static, plan.copies):
        unchanged = (before.get(path) or {}).get("sha256") == (now.get(path) or {}).get("sha256")
        if unchanged and target.is_file():
            continue
        try:
            data = design_images.make_copy(plan.assets[path].read_bytes(), width)
        except Exception as exc:  # noqa: BLE001 - one unreadable image does not stop the import
            typer.echo(f"copy of {path} at {width}w not written: {exc}", err=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        made += 1
    if made:
        typer.echo(f"wrote    {made} smaller WebP image copies under {ws.rel(static)}/")


HIGHLIGHT_SETTING = "KARNI_SITE_HIGHLIGHT"


def _highlight_setting(ws: Workspace, plan: SitePlan) -> None:
    """Tell karni-site how the design highlights words, when the project has not said."""
    found = (plan.design.get("editable") or {}).get("highlight")
    if not found:
        return
    text = ws.read(SETTINGS)
    if text is None or HIGHLIGHT_SETTING in text:
        return
    line = (
        f'{HIGHLIGHT_SETTING} = {{"marker": "==", "tag": {pystr(found["tag"])}, '
        f'"class": {pystr(found["class"])}}}'
    )
    block = (
        "\n# The design highlights words in its headings with "
        f'<{found["tag"]} class="{found["class"]}">. A client types ==words== in an editable\n'
        "# block for the same (karni import design --editable).\n" + line + "\n"
    )
    ws.write(SETTINGS, text.rstrip("\n") + "\n" + block)


def _editable_lines(plan: SitePlan) -> list[str]:
    report = plan.editable
    if report is None:
        return []
    menus = ", ".join(report.menus) or "none"
    lines = [
        (
            f"editable: {report.blocks} text block(s), {report.images} image(s), "
            f"{len(report.menus)} menu(s) ({menus}), edited in the admin."
        )
    ]
    if report.site:
        details = ", ".join(f"{name}={value!r}" for name, value in report.site.items())
        lines.append(f"site details from the design (site_defaults in base.html): {details}")
    found = (plan.design.get("editable") or {}).get("highlight")
    if found:
        lines.append(
            f'highlight: <{found["tag"]} class="{found["class"]}"> in headings, typed as ==words== '
            f"({HIGHLIGHT_SETTING} in config/settings.py)."
        )
    lines.extend(f"  - {note}" for note in report.notes)
    return lines


def _report(plan: SitePlan, writer: _Writer, copied: int, diff: list[str]) -> list[str]:
    lines: list[str] = []
    pages = len(plan.views)
    lines.append(
        f"imported {pages} page(s), {len(plan.redirects)} redirect(s), "
        f"{len(plan.design.get('partials', []))} partial(s), {copied} file(s) copied."
    )
    lines.extend(plan.notes)
    lines.extend(_editable_lines(plan))
    for redirect in plan.redirects:
        lines.append(f"redirect: /{redirect.route} -> {redirect.to} (from {redirect.source})")
    active = plan.design.get("active", {})
    markers = [f'class="{token}"' for token in active.get("class", [])]
    markers += [f'{name}="{value}"' for name, value in active.get("attributes", {}).items()]
    if markers:
        lines.append(
            "current page: the design marks it with "
            + ", ".join(markers)
            + ", now {% ifactive %} on each link."
        )
    if plan.unused_assets:
        lines.append(
            f"copied but unused by any page or stylesheet ({len(plan.unused_assets)}): "
            + ", ".join(plan.unused_assets)
        )
    if plan.problems:
        lines.append(f"not mapped ({len(plan.problems)}):")
        lines.extend(f"  - {problem}" for problem in plan.problems)
    if diff:
        lines.append(f"changes since the last import ({len(diff)}):")
        lines.extend(f"  - {line}" for line in diff)
    if writer.kept:
        lines.append(
            f"kept, edited since the last import ({len(writer.kept)}): "
            + ", ".join(writer.kept)
            + ". Re-run with --force to replace them."
        )
    return lines


def _content_map(ws: Workspace, given: Path | None, record: dict[str, Any] | None) -> Path | None:
    """The content map to follow: ``--map``, else the one the last import followed."""
    if given is not None:
        path = given if given.is_absolute() else Path.cwd() / given
        if not path.is_file():
            raise CliError(
                f"{given}: no such file. Write the content map first: karni design analyze "
                f"<design folder> --map {given}.",
                code="C121",
            )
        return path.resolve()
    recorded = ((record or {}).get("editable") or {}).get("map")
    if not recorded:
        return None
    path = ws.path(str(recorded))
    if not path.is_file():
        ws.note(
            f"{recorded}: the content map the last import followed is gone, so every part of "
            "every page is editable again."
        )
        return None
    return path


def _read_content_map(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError(f"{path}: not a JSON content map ({exc}).", code="C121") from None
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise CliError(
            f'{path}: a content map is an object with a "models" list (karni design analyze '
            "--map writes one).",
            code="C121",
        )
    return data


def run(
    ws: Workspace,
    directory: Path,
    app: str | None,
    *,
    diff: bool = False,
    dry_run: bool = False,
    editable: bool | None = None,
    content_map: Path | None = None,
    guidance: bool = True,
) -> None:
    """Import the design folder ``directory`` into the project ``ws`` is over.

    The command's whole work, for any workspace: ``karni new --design`` runs it
    on the project it just made, with ``guidance=False`` (it writes the agent
    files itself, after the import).
    """
    source = _design_dir(directory)
    label = Path(os.path.relpath(source, ws.root)).as_posix()
    existing_text = ws.read(DESIGN_RECORD)
    record: dict[str, Any] | None = None
    if existing_text is not None:
        try:
            record = json.loads(existing_text)
        except json.JSONDecodeError as exc:
            raise CliError(
                f"{DESIGN_RECORD.as_posix()} is not valid JSON ({exc}). Fix or remove it.",
                code="C110",
            ) from None
    app_label = app or (record or {}).get("app")
    if editable is None:
        editable = bool(((record or {}).get("editable") or {}).get("enabled"))
    map_path = _content_map(ws, content_map, record)
    spec = _read_content_map(map_path) if map_path is not None else None
    if spec is not None and not editable:
        ws.note(
            "--map changes only an editable import (--editable): without blocks, nothing is "
            "left out."
        )
        spec, map_path = None, None
    try:
        plan = design_site.plan(
            source,
            app_label or "website",
            source_label=label,
            editable=editable,
            previous=record,
            content_map=spec,
        )
    except ValueError as exc:
        raise CliError(str(exc), code="C111") from None
    changes = compare.diff(record, plan.design) if record else []
    if diff:
        if record is None:
            typer.echo(f"no {DESIGN_RECORD.as_posix()} yet: nothing to compare with.")
        for line in _report(plan, _Writer(ws, App("", "", ws.root), record), 0, changes):
            typer.echo(line)
        typer.echo("(--diff: nothing written)")
        return
    site_app = _site_app(ws, app_label)
    if site_app.label != plan.app:
        plan = design_site.plan(
            source,
            site_app.label,
            source_label=label,
            editable=editable,
            previous=record,
            content_map=spec,
        )
        changes = compare.diff(record, plan.design) if record else []
    writer = _Writer(ws, site_app, record)
    for app_rel, content in plan.templates.items():
        writer.template(app_rel, content)
    _add_views(ws, site_app, plan)
    for route, name in plan.routes:
        site_gen.register_route(ws, site_app, route, name)
    _add_redirects(ws, site_app, plan)
    for url in plan.page_urls:
        site_gen.add_page_to_test(ws, site_app, url)
    copies = [
        copy for path, file in plan.assets.items() if (copy := writer.asset(path, file)) is not None
    ]
    _highlight_setting(ws, plan)
    _theme_from_css(ws, plan, dry_run=dry_run)
    record_out = {**plan.design, "files": dict(sorted(writer.hashes.items()))}
    if map_path is not None and isinstance(record_out.get("editable"), dict):
        record_out["editable"] = {
            **record_out["editable"],
            "map": Path(os.path.relpath(map_path, ws.root)).as_posix(),
        }
    ws.write(DESIGN_RECORD, json.dumps(record_out, indent=2, ensure_ascii=False) + "\n")
    for line in _report(plan, writer, len(copies), changes):
        ws.note(line)
    ws.note("next: karni test (the page test covers every page), then karni serve.")
    ws.commit(dry_run=dry_run)
    if dry_run:
        for source_file, target in copies:
            typer.echo(f"would copy {ws.rel(target)}")
        count = sum(len(widths) for widths in plan.copies.values())
        if count:
            typer.echo(f"would write {count} smaller WebP copies of the design's images")
        return
    for source_file, target in copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)
        typer.echo(f"copied   {ws.rel(target)}")
    _write_image_copies(ws, site_app, plan, record)
    if guidance:
        site_gen.record_site_guidance(ws)


@import_app.command("design")
def design(
    directory: Path = typer.Argument(
        ..., help="The folder with the design's HTML pages, CSS, JavaScript and images."
    ),
    app: str | None = APP_OPTION,
    diff: bool = typer.Option(
        False, "--diff", help="Report what changed since the last import and write nothing."
    ),
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    editable: bool | None = typer.Option(
        None,
        "--editable/--no-editable",
        help=(
            "Make every text, image, menu and contact detail editable in the admin "
            "(karni-site blocks, menus and site settings). Remembered for later imports."
        ),
    ),
    content_map: Path | None = typer.Option(
        None,
        "--map",
        help=(
            "The content map from karni design analyze --map: with --editable, the content it "
            "reads into rows (cards, detail pages, galleries) gets no blocks, because the "
            "templates render it from the rows. Remembered for later imports."
        ),
    ),
) -> None:
    """Build the public site from a folder of static pages, keeping the design as written.

    Copies the CSS, JavaScript and images into APP/static/APP/ unchanged,
    puts the header, navigation and footer every page shares into
    APP/templates/APP/base.html (a block shared by some pages becomes a
    partial), turns each page into a template extending it with a view and a
    route (index.html answers "/", about.html "/about/", a folder a nested
    route), rewrites links to `{% url %}` and asset paths to `{% static %}`
    (anchors and query strings kept), turns a meta-refresh stub into a
    permanent redirect, marks the current menu item with `{% ifactive %}`
    wherever the design marked it, wraps inline scripts in `{% csp_hash %}`
    so they run under the Content-Security-Policy, and adds every page to
    the page test. base.html's title, description and share tags go inside
    `{% karni_seo %}`. Every image of the design gets its width and height,
    and, with Pillow installed, smaller WebP copies and a srcset. It reports
    the files it did not see used and anything it could not map. The app is
    created with `karni make site` when needed.

    With --editable, every text becomes a block (`{% editable %}`), every
    image `{% editable_image %}`, each navigation a menu (`{% get_menu %}`)
    seeded from the design's links, and the site's name, logo, favicon,
    phone, email, map and social links come from the site's settings: the
    client changes all of it in the admin, and the templates hold the
    design's text as the defaults.

    Writes .karni/design.json. A second run with a new version of the design
    reports the changes and keeps every file the project edited since, and
    every block keeps its key.

    With --map content/design-map.json (karni design analyze --map writes
    it), the content the map reads into rows gets no blocks: the cards,
    detail pages and galleries that become models are rendered from the
    rows, and the client edits the rows in the admin.
    """
    run(
        project_workspace(force),
        directory,
        app,
        diff=diff,
        dry_run=dry_run,
        editable=editable,
        content_map=content_map,
    )
