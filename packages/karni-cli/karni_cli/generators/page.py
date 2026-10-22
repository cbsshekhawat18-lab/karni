"""``karni make page <name>`` — a ≤ 50-line page composing @karni/ui, routed.

Kinds (``--resource R --kind ...``), with routes under a base path
(``--path``, default ``/<resource>``):

* ``list``   → ``<base>``: ``<Page><ResourceTable resource=R /></Page>``
* ``detail`` → ``<base>/$id``: ``<ResourceDetail resource=R id={id} />``
* ``form``   → ``<base>/new`` and ``<base>/$id/edit``: ``<ResourceForm />``

Pages link to their siblings only when those routes exist (or are generated
in the same run) — TanStack Router's typed ``navigate`` rejects unknown
paths, so a link to a missing page would not compile. Without
``--resource`` the page is a bare ``<Page title=... />`` at ``/<name>``.

Routes are registered in ``frontend/src/routes.tsx`` between the
``// karni:page-imports`` and ``// karni:routes`` markers.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import typer

from karni_cli.generators.core import (
    DRY_RUN_OPTION,
    FORCE_OPTION,
    FRONTEND,
    Workspace,
    local_apps,
    project_workspace,
    require_frontend,
)
from karni_cli.generators.introspect import viewsets_file
from karni_cli.generators.naming import default_route, humanize, pascal, require_kebab
from karni_cli.generators.pysource import parse
from karni_cli.project import CliError

NAME = "page"
SUMMARY = "Add a frontend page (<= 50 lines) composing @karni/ui, with its route."

KINDS = ("list", "detail", "form", "login")
MAX_LINES = 50
PAGES = FRONTEND / "src" / "pages"
ROUTES = FRONTEND / "src" / "routes.tsx"
IMPORT_MARKER = "// karni:page-imports"
ROUTE_MARKER = "// karni:routes"

_PATH = re.compile(r"^/([A-Za-z0-9_.$-]+(/[A-Za-z0-9_.$-]+)*)?$")
_ROUTE_PATH = re.compile(r"""path:\s*["']([^"']+)["']""")
_SUFFIXES = ("-detail", "-form", "-list", "-page")


@dataclass(frozen=True)
class PageSpec:
    name: str
    kind: str | None
    resource: str | None
    base: str
    title: str
    #: Relation fields a detail page asks the API to expand (labels, not raw ids).
    expand: tuple[str, ...] = ()

    @property
    def component(self) -> str:
        stem = pascal(self.name)
        return stem if stem.endswith("Page") else f"{stem}Page"

    @property
    def paths(self) -> list[str]:
        if self.kind == "detail":
            return [f"{self.base}/$id"]
        if self.kind == "form":
            return [f"{self.base}/new", f"{self.base}/$id/edit"]
        return [self.base]

    @property
    def file(self) -> Path:
        return PAGES / f"{self.name}.tsx"


def spec_for(
    name: str,
    *,
    resource: str | None,
    kind: str | None,
    path: str | None,
    title: str | None = None,
    expand: tuple[str, ...] | list[str] | None = None,
) -> PageSpec:
    require_kebab(name, "Page name")
    if kind is not None and kind not in KINDS:
        raise CliError(f"--kind {kind!r}: choose one of {', '.join(KINDS)}.", code="C106")
    if kind is not None and kind != "login" and resource is None:
        raise CliError(
            f"--kind {kind} needs --resource <route>, e.g. --resource events.", code="C004"
        )
    if resource is not None:
        require_kebab(resource, "--resource")
        kind = kind or "list"
    base = (path or f"/{resource or name}").rstrip("/") or "/"
    if not _PATH.match(base):
        raise CliError(f"--path {path!r} must look like /events or /admin/events.", code="C106")
    if title is None:
        stem = name
        for suffix in _SUFFIXES:
            stem = stem.removesuffix(suffix)
        title = (
            "Sign in"
            if kind == "login"
            else humanize(resource if kind == "list" and resource else stem)
        )
    if any(ch in title for ch in '"{}<>\\`'):
        raise CliError(
            f"--title {title!r}: plain text only (no quotes, braces or angle brackets).",
            code="C106",
        )
    return PageSpec(name, kind, resource, base, title, tuple(expand or ()))


def known_routes(ws: Workspace) -> set[str]:
    text = ws.read(ROUTES) or ""
    return set(_ROUTE_PATH.findall(text))


def _routed_resources(ws: Workspace) -> set[str]:
    """Routes of the project's viewsets (default kebab-plural, or an explicit ``route``)."""
    found: set[str] = set()
    for app in local_apps(ws):
        path = viewsets_file(ws, app)
        text = ws.read(path)
        if not text:
            continue
        for node in parse(ws, ws.rel(path), text).body:
            if not isinstance(node, ast.ClassDef):
                continue
            explicit = None
            model = None
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "route" and isinstance(stmt.value, ast.Constant):
                    explicit = str(stmt.value.value)
                elif target.id == "model" and isinstance(stmt.value, ast.Name):
                    model = stmt.value.id
            if explicit:
                found.add(explicit)
            elif model:
                found.add(default_route(model))
    return found


# rendering


def _ui_import(names: set[str]) -> str:
    return "import { " + ", ".join(sorted(names)) + ' } from "@karni/ui";'


def _router_import(names: set[str]) -> str:
    return "import { " + ", ".join(sorted(names)) + ' } from "@tanstack/react-router";'


def _go(to: str, params: str = "") -> str:
    extra = f", params: {{ {params} }}" if params else ""
    return f'void navigate({{ to: "{to}"{extra} }})'


def render(spec: PageSpec, routes: set[str]) -> str:
    """The page source; links only to routes in ``routes``."""
    base = spec.base.rstrip("/")
    if spec.kind is None:
        return (
            f"{_ui_import({'Page'})}\n\n"
            f"export default function {spec.component}() {{\n"
            f'    return <Page title="{spec.title}" />;\n'
            "}\n"
        )
    if spec.kind == "login":
        home = "/" if "/" in routes or not routes else min(routes)
        props = [f"onSuccess={{() => {_go(home)}}}"]
        return _shell(spec, "LoginForm", props, None, hooks=[], ui={"LoginForm"})
    detail, new, edit = f"{base}/$id", f"{base}/new", f"{base}/$id/edit"
    resource = spec.resource
    if spec.kind == "list":
        props = [f'resource="{resource}"']
        if detail in routes:
            props.append(f"onRowClick={{(row) =>\n    {_go(detail, 'id: String(row.id)')}\n}}")
        if edit in routes:
            props.append(f"onEdit={{(row) =>\n    {_go(edit, 'id: String(row.id)')}\n}}")
        actions = f"<Button onClick={{() => {_go(new)}}}>New</Button>" if new in routes else None
        return _shell(spec, "ResourceTable", props, actions, hooks=[], ui={"ResourceTable"})
    if spec.kind == "detail":
        hooks = [f'const {{ id }} = useParams({{ from: "{detail}" }});']
        actions = None
        if edit in routes:
            actions = f"<Button onClick={{() => {_go(edit, 'id')}}}>\n    Edit\n</Button>"
        props = [f'resource="{resource}"', "id={id}"]
        if spec.expand:
            names = ", ".join(f'"{name}"' for name in spec.expand)
            props.append(f"expand={{[{names}]}}")
        return _shell(spec, "ResourceDetail", props, actions, hooks=hooks, ui={"ResourceDetail"})
    hooks = ["const { id } = useParams({ strict: false });"]
    props = [f'resource="{resource}"', "id={id}"]
    if detail in routes:
        props.append(f"onSuccess={{(result) =>\n    {_go(detail, 'id: String(result.id)')}\n}}")
    elif spec.base in routes:
        props.append(f"onSuccess={{() => {_go(spec.base)}}}")
    noun = spec.title.lower()
    title = f'{{id === undefined ? "New {noun}" : "Edit {noun}"}}'
    return _shell(spec, "ResourceForm", props, None, hooks=hooks, ui={"ResourceForm"}, title=title)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else line for line in text.split("\n"))


def _shell(
    spec: PageSpec,
    element: str,
    props: list[str],
    actions: str | None,
    *,
    hooks: list[str],
    ui: set[str],
    title: str | None = None,
) -> str:
    body = "\n".join(props)
    navigates = "navigate(" in body or (actions is not None and "navigate(" in actions)
    if navigates:
        hooks = [*hooks, "const navigate = useNavigate();"]
    router: set[str] = set()
    if any("useParams(" in hook for hook in hooks):
        router.add("useParams")
    if navigates:
        router.add("useNavigate")
    title_attr = f"title={title}" if title else f'title="{spec.title}"'
    ui = {*ui, "Page", *({"Button"} if actions else set())}
    lines = [_ui_import(ui)]
    if router:
        lines.append(_router_import(router))
    lines += ["", f"export default function {spec.component}() {{"]
    lines += [f"    {hook}" for hook in hooks]
    lines.append("    return (")
    if actions:
        lines += ["        <Page", f"            {title_attr}", "            actions={"]
        lines.append(_indent(actions, 16))
        lines += ["            }", "        >"]
    else:
        lines.append(f"        <Page {title_attr}>")
    if len(props) == 1:
        lines.append(f"            <{element} {props[0]} />")
    elif all("\n" not in p for p in props) and len(" ".join(props)) <= 50:
        lines.append(f"            <{element} {' '.join(props)} />")
    else:
        lines.append(f"            <{element}")
        lines += [_indent(prop, 16) for prop in props]
        lines.append("            />")
    lines += ["        </Page>", "    );", "}", ""]
    return "\n".join(lines)


# planning


def plan(
    ws: Workspace,
    spec: PageSpec,
    *,
    register: bool = True,
    planned_routes: set[str] | None = None,
) -> None:
    """Plan the page file and its route entries."""
    require_frontend(ws)
    existing = known_routes(ws)
    routes = existing | set(planned_routes or ()) | set(spec.paths)
    source = render(spec, routes)
    count = source.count("\n")
    if count > MAX_LINES:  # pragma: no cover - the templates stay far below the cap
        raise CliError(f"internal: generated page is {count} lines (cap {MAX_LINES}).", code="C199")
    ws.create(spec.file, source)
    if spec.resource and spec.resource not in _routed_resources(ws):
        ws.note(
            f"note: no viewset in this project routes /api/{spec.resource}/ yet. Run "
            "karni make viewset <Model> (or point --resource at a module's resource)."
        )
    if register:
        _register(ws, spec, existing)
    else:
        ws.note(f"route not registered (--no-route): add {', '.join(spec.paths)} yourself.")
    ws.note(f"page: {', '.join(spec.paths)} -> {spec.component}")


def _register(ws: Workspace, spec: PageSpec, existing: set[str]) -> None:
    text = ws.read(ROUTES)
    manual = f'import {spec.component} from "./pages/{spec.name}";\n' + "\n".join(
        _route_line(spec, p) for p in spec.paths
    )
    if text is None or IMPORT_MARKER not in text or ROUTE_MARKER not in text:
        raise CliError(
            f"{ROUTES.as_posix()} with the `{IMPORT_MARKER}` and `{ROUTE_MARKER}` markers "
            "was not found (projects scaffolded before `karni make`). Register the route "
            f"yourself and re-run with --no-route:\n{manual}",
            code="C108",
        )
    lines = text.splitlines()
    import_line = f'import {spec.component} from "./pages/{spec.name}";'
    for path in spec.paths:
        if path in existing:
            owner = next((ln for ln in lines if f'"{path}"' in ln), "")
            if f"component: {spec.component}" not in owner:
                raise CliError(
                    f"Route {path} is already registered in {ROUTES.as_posix()}. Choose "
                    "another --path (or remove the existing route).",
                    code="C107",
                )
    if import_line not in lines:
        index = next(i for i, ln in enumerate(lines) if IMPORT_MARKER in ln)
        lines.insert(index, import_line)
    for path in spec.paths:
        if path in existing:
            continue
        index = next(i for i, ln in enumerate(lines) if ROUTE_MARKER in ln)
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        lines.insert(index, indent + _route_line(spec, path).strip())
    ws.write(ROUTES, "\n".join(lines) + "\n")


def _route_line(spec: PageSpec, path: str) -> str:
    return (
        f'    createRoute({{ getParentRoute: () => root, path: "{path}", '
        f"component: {spec.component} }}),"
    )


def command(
    name: str = typer.Argument(..., help="Page file name, kebab-case (e.g. events)."),
    resource: str | None = typer.Option(
        None, "--resource", help="API resource (router prefix, e.g. events)."
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        help="With --resource: list (default), detail or form. A login page needs no resource.",
    ),
    path: str | None = typer.Option(
        None,
        "--path",
        help="Route path. For resource pages it is the base (default `/<resource>`).",
    ),
    title: str | None = typer.Option(None, "--title", help="Page title (default: from the name)."),
    no_route: bool = typer.Option(
        False, "--no-route", help="Do not register the route in frontend/src/routes.tsx."
    ),
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add frontend/src/pages/NAME.tsx (at most 50 lines) and register its route.

    With --resource R --kind list|detail|form the page composes ResourceTable /
    ResourceDetail / ResourceForm for the API resource R. Without --resource the
    page is a bare `<Page>`. Routes: list at `<base>`, detail at `<base>/$id`,
    form at `<base>/new` and `<base>/$id/edit`, where the base is --path or
    `/<resource>`.
    """
    ws = project_workspace(force)
    spec = spec_for(name, resource=resource, kind=kind, path=path, title=title)
    plan(ws, spec, register=not no_route)
    ws.commit(dry_run=dry_run)
