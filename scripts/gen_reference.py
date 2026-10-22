#!/usr/bin/env python3
"""Generate Karni's reference from the source: docs/REFERENCE.md and README.md's generated blocks.

    python scripts/gen_reference.py           # rewrite both files
    python scripts/gen_reference.py --check   # exit 1 with a diff when either is stale (CI)

Everything is read from this checkout, never typed from memory:

- commands: the Typer app (``karni_cli.main.app``), walked as docs/cli.md is;
- base classes: ``__all__`` of karni.models, karni.api, karni.admin and
  karni.testing, with what each class gives a subclass (fields and managers,
  declarable attributes and endpoints, admin hooks, signatures);
- ``class Karni`` keys: ``karni.meta.OPTIONS`` plus each module's
  ``KARNI_OPTIONS``; a key that code reads through ``karni_option()`` but no
  list declares fails the run;
- settings: ``karni.conf.reference`` and each module's ``conf.DEFAULTS``;
- components and hooks: @karni/ui's barrel, read with the TypeScript compiler
  by scripts/gen_reference_ui.mjs;
- modules: modules/*/pyproject.toml (and ui/package.json);
- error codes: the registries docs/errors.md is generated from;
- make targets: the scaffold's Makefile; slash commands: karni.agent's
  procedures and the command adapters in agent_adapters.toml;
- status: :data:`CAPABILITIES` below. A capability is ``stable`` only with
  evidence (a reference-application file and a phrase in it), checked on
  every run, so a claim cannot outlive the code that backs it.

README.md keeps hand-written prose; only the regions between
``<!-- generated:NAME -->`` and ``<!-- /generated:NAME -->`` are replaced.
Every README link into docs/REFERENCE.md is checked against the anchors
GitHub generates for its headings.

Needs the packages installed (``make install-py``) and @karni/ui's
dependencies (``make install-ui``).
"""

from __future__ import annotations

import argparse
import ast
import difflib
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
import tomllib
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "REFERENCE.md"
README = ROOT / "README.md"
REF_LINK = "docs/REFERENCE.md"
SCAFFOLD = ROOT / "templates" / "project" / "{{cookiecutter.project_slug}}"


# --- status ------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    """One thing Karni does, with the evidence that decides its status.

    ``evidence`` is (file in a reference application, phrase in it). With
    evidence the capability is ``stable``; without, ``experimental`` (shipped
    and covered by Karni's own tests, not yet used by a reference
    application); with ``planned`` (a docs link) it is ``planned``.
    """

    area: str
    text: str
    evidence: tuple[tuple[str, str], ...] = ()
    planned: str = ""

    @property
    def status(self) -> str:
        if self.planned:
            return "planned"
        return "stable" if self.evidence else "experimental"


EH = "examples/eventhub"
SL = "examples/social-leads"

#: Every capability the README and the reference list, by area.
CAPABILITIES: tuple[Capability, ...] = (
    # models
    Capability(
        "models",
        "`BaseModel`: UUID key, created and updated timestamps, soft delete, "
        "`created_by` and `updated_by`",
        ((f"{EH}/events/models.py", "class Event(BaseModel)"),),
    ),
    Capability(
        "models",
        "Realistic, connected seed data (`karni seed`, `<app>/seeds.py`)",
        ((f"{EH}/events/seeds.py", "Seeder"),),
    ),
    Capability(
        "models",
        "Model events and listeners, optionally queued to Celery (`@on_updated`)",
        ((f"{EH}/events/listeners.py", "@on_updated(Booking, queued=True)"),),
    ),
    Capability(
        "models",
        "Field-level change history (`class Karni: audit = True`)",
        ((f"{SL}/crm/models.py", "audit = True"),),
    ),
    Capability("models", "Scheduled tasks (`<app>/schedules.py`, `karni schedule`)"),
    Capability(
        "models",
        "A tenant scope on every model (the `karni-tenancy` module)",
        planned="docs/models.md#scopes-the-filters-every-default-manager-applies",
    ),
    # api
    Capability(
        "api",
        "`BaseViewSet`: CRUD, filters, search, ordering, pagination, `?expand=` and the "
        "OpenAPI document, with no serializer",
        ((f"{EH}/events/viewsets.py", "class EventViewSet(BaseViewSet)"),),
    ),
    Capability(
        "api",
        "`access` declarations (`Public`, `Owned`, `HasRole`, `Where`, `Granted`) compiled "
        "into both the request gate and the row filter",
        ((f"{EH}/events/viewsets.py", "access = Access("),),
    ),
    Capability(
        "api",
        "Query budgets: a list endpoint that runs more queries than declared fails its test",
        ((f"{SL}/crm/viewsets.py", "query_budget = Budget("),),
    ),
    Capability(
        "api",
        "CSV and XLSX export of any list (`/export/?format=`)",
        ((f"{SL}/crm/tests/test_leads.py", "/export/?format=csv"),),
    ),
    Capability(
        "api",
        "Import from CSV or XLSX with a mandatory preview (`/import/`)",
        ((f"{SL}/frontend/src/pages/leads.tsx", "<ResourceImport"),),
    ),
    Capability("api", "Response caching per viewset (`Cache`, `Uncached`)"),
    Capability(
        "api",
        "TypeScript types and typed hooks from the OpenAPI document (`karni types`)",
        ((f"{EH}/Makefile", "karni types"),),
    ),
    # admin
    Capability(
        "admin",
        "Every model registered with derived columns, filters and search; no `admin.py`",
        ((f"{EH}/config/urls.py", 'path("admin/", admin.site.urls)'),),
    ),
    Capability(
        "admin",
        "Row scope from the roles' grants: a staff user sees and edits only the rows a "
        "grant allows",
    ),
    Capability("admin", "Field visibility, change history and the import and export screens"),
    Capability("admin", "A permission matrix of every role against every model and action"),
    # ui
    Capability(
        "ui",
        "`ResourceTable`, `ResourceForm` and `ResourceDetail` driven by the OpenAPI schema",
        (
            (f"{EH}/frontend/src/pages/events.tsx", "<ResourceTable"),
            (f"{EH}/frontend/src/pages/event-form.tsx", "<ResourceForm"),
            (f"{EH}/frontend/src/pages/event-detail.tsx", "<ResourceDetail"),
        ),
    ),
    Capability(
        "ui",
        "Sign-in, session restore and role checks (`AuthProvider`, `LoginForm`, `usePermission`)",
        ((f"{EH}/frontend/src/pages/login.tsx", "<LoginForm"),),
    ),
    Capability(
        "ui",
        "Data hooks with shared caching (`useResourceList`, `useResourceItem`)",
        ((f"{SL}/frontend/src/components/LeadKanban.tsx", "useResourceList"),),
    ),
    Capability(
        "ui",
        "Import screen with column mapping and preview (`ResourceImport`)",
        ((f"{SL}/frontend/src/pages/leads.tsx", "<ResourceImport"),),
    ),
    Capability(
        "ui",
        "Page building blocks: `Page`, `Layout`, `Stat`, `Modal`, `Toaster`, `EmptyState`",
        ((f"{EH}/frontend/src/pages/event-dashboard.tsx", "<Stat"),),
    ),
    Capability("ui", "`ChangeHistory`, `DataChart` and `FileUpload`"),
    Capability(
        "ui",
        "`karni ui detect`: the project's shadcn/ui, Tailwind, Material UI, Chakra UI or "
        "Mantine theme as Karni's tokens, and shadcn/ui components as Karni's primitives",
    ),
    # permissions
    Capability(
        "permissions",
        "One `access` declaration per viewset: 404 outside the read scope, 403 for "
        "read-but-not-write",
        ((f"{EH}/events/viewsets.py", 'write=Owned("organizer") | STAFF'),),
    ),
    Capability(
        "permissions",
        "Roles as data (`KARNI_ROLES`) with the `all` and `own` scopes",
        ((f"{SL}/config/settings.py", '"crm.*:*": "own"'),),
    ),
    Capability(
        "permissions",
        "The `related:<key>` scope (`class Karni: scope_paths`) and `custom:` scopes",
    ),
    Capability(
        "permissions",
        'Membership through a path: `owner_field = "workspace__members"`',
        ((f"{SL}/crm/models.py", 'owner_field = "workspace__members"'),),
    ),
    Capability(
        "permissions",
        "Scope paths that do not resolve fail `karni check` (`E214`) instead of answering 500",
        ((f"{SL}/crm/models.py", 'owner_field = "lead__workspace__members"'),),
    ),
    Capability("permissions", "Field visibility per role (`class Karni: field_roles`)"),
    Capability("permissions", "Row scope in the admin, from the same grants as the API"),
    Capability(
        "permissions",
        "Change history: who changed which field, when, from what to what",
        ((f"{SL}/crm/models.py", "audit = True"),),
    ),
    Capability("permissions", "Sensitive fields recorded in the history without their values"),
    Capability(
        "permissions",
        "Maker-checker approvals and safe impersonation (the `approvals` and "
        "`impersonation` modules)",
    ),
    Capability(
        "permissions",
        "Tenancy: a tenant scope applied to every model",
        planned="docs/models.md#scopes-the-filters-every-default-manager-applies",
    ),
    # agents
    Capability(
        "agents",
        "`karni context`, `karni rules` and `karni check` in the project workflow",
        ((f"{EH}/Makefile", "karni context"), (f"{EH}/Makefile", "karni check")),
    ),
    Capability(
        "agents",
        "Adapter files for every supported agent tool from one rule set (`karni rules sync`)",
        ((f"{EH}/AGENTS.md", "karni context"), (f"{EH}/.cursor/commands/new-model.md", "")),
    ),
    Capability(
        "agents",
        "Slash commands for the routine tasks (`/new-model`, `/new-page`, …)",
        ((f"{EH}/.claude/commands/new-model.md", "karni context"),),
    ),
    Capability("agents", "`karni explain <code>`: why an error happens and the fix, offline"),
    Capability(
        "agents",
        "`karni why` / `karni why-empty`: why a row, field or action is refused or missing for "
        "a user, from the code that decides it",
    ),
    Capability(
        "agents", "MCP server exposing `context`, `rules`, `check`, `why` and `why_empty` as tools"
    ),
    # testing
    Capability(
        "testing",
        "`assert_crud` and `assert_isolated`: the whole API surface and owner isolation in "
        "two calls",
        ((f"{EH}/events/tests/test_booking.py", "assert_isolated"),),
    ),
    Capability(
        "testing",
        "Generated tests from `karni make model … --with test`",
        ((f"{SL}/crm/tests/test_lead.py", "assert_isolated"),),
    ),
    Capability(
        "testing",
        "OpenAPI snapshot test (`assert_schema_snapshot`)",
        ((f"{EH}/tests/test_api_schema.py", "assert_schema_snapshot"),),
    ),
    Capability(
        "testing",
        "Clients per role (`client_as`)",
        ((f"{EH}/events/tests/test_booking_flow.py", "client_as"),),
    ),
    Capability("testing", "`query_budget` and `user_with_roles` helpers"),
    Capability(
        "testing",
        "Architecture rules that fail the build (`karni check`, the ESLint preset)",
        ((f"{EH}/Makefile", "karni check"),),
    ),
)

#: The modules' capabilities: which reference application uses each.
MODULE_EVIDENCE: dict[str, tuple[tuple[str, str], ...]] = {
    "payments": ((f"{EH}/config/settings.py", "karni_payments"),),
}
MODULE_PLANNED: dict[str, str] = {
    "tenancy": "docs/models.md#scopes-the-filters-every-default-manager-applies",
}

AREAS: tuple[tuple[str, str], ...] = (
    ("models", "Models"),
    ("api", "API"),
    ("admin", "Admin"),
    ("ui", "UI components and hooks"),
    ("permissions", "Permissions"),
    ("agents", "Agent integration"),
    ("testing", "Testing"),
)

STATUS_NOTE = (
    "`stable`: public under the [stability promise](stability.md) and used by a reference "
    "application (EventHub or the Social Stats rebuild). `experimental`: public and "
    "covered by Karni's own tests, but no reference application uses it yet, so expect "
    "rough edges. `planned`: documented as coming; not in the code."
)


def verify_evidence() -> list[str]:
    """Each piece of evidence must still be in its file; returns the failures."""
    problems = []
    for capability in CAPABILITIES:
        for rel, phrase in capability.evidence:
            path = ROOT / rel
            if not path.is_file():
                problems.append(f"{capability.text}: {rel} does not exist")
            elif phrase and phrase not in path.read_text(encoding="utf-8"):
                problems.append(f"{capability.text}: {rel} no longer contains {phrase!r}")
    for module, evidence in MODULE_EVIDENCE.items():
        for rel, phrase in evidence:
            path = ROOT / rel
            if not path.is_file() or phrase not in path.read_text(encoding="utf-8"):
                problems.append(f"module {module}: {rel} does not contain {phrase!r}")
    return problems


# --- helpers -----------------------------------------------------------------


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading (github-slugger's rules)."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(markdown: str) -> set[str]:
    """Every anchor a Markdown document defines: headings (deduplicated) and ``<a id>``."""
    seen: dict[str, int] = {}
    found: set[str] = set()
    in_code = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if match:
            base = slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            found.add(base if count == 0 else f"{base}-{count}")
        found.update(re.findall(r'<a id="([^"]+)"></a>', line))
    return found


def rst(text: str) -> str:
    """Docstring markup as Markdown: ``x`` and :role:`x` become `x`."""
    text = re.sub(r":[a-z]+:`~?([^`]+)`", r"`\1`", text)
    return text.replace("``", "`")


def first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    paragraph = inspect.cleandoc(doc).split("\n\n")[0]
    return rst(" ".join(line.strip() for line in paragraph.splitlines()))


def first_sentence(text: str | None) -> str:
    paragraph = first_paragraph(text)
    match = re.match(r"^(.+?[.!?])(\s|$)", paragraph)
    return (match.group(1) if match else paragraph).rstrip(".")


def cell(text: str) -> str:
    """A table cell: one line, pipes escaped, ``<`` outside code spans escaped."""
    parts = text.replace("\n", " ").split("`")
    for i in range(0, len(parts), 2):
        parts[i] = parts[i].replace("<", "&lt;").replace(">", "&gt;")
    return "`".join(parts).replace("|", "\\|")


def table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell(c) for c in row) + " |" for row in rows]
    return out + [""]


def repo_link(rel: str, *, tree: bool = False) -> str:
    """A file outside docs/ as an absolute GitHub URL (the docs site cannot serve it)."""
    from karni.links import REPO_URL

    return f"{REPO_URL}/{'tree' if tree else 'blob'}/main/{rel}"


def ref(anchor: str) -> str:
    return f"{REF_LINK}#{anchor}"


def capabilities(area: str) -> list[Capability]:
    return [c for c in CAPABILITIES if c.area == area]


# --- commands ----------------------------------------------------------------


def _cli() -> tuple[Any, dict[str, Any], list[tuple[str, list[str]]]]:
    import typer
    from karni_cli import clidoc
    from karni_cli.main import app

    root = typer.main.get_command(app)
    visible = {n: c for n, c in clidoc._subcommands(root).items() if not c.hidden}
    placed = {name for _, names in clidoc.SECTIONS for name in names}
    sections = [*clidoc.SECTIONS, ("Other", tuple(n for n in visible if n not in placed))]
    ordered = [(title, [n for n in names if n in visible]) for title, names in sections]
    return clidoc, visible, [(t, ns) for t, ns in ordered if ns]


def commands_section() -> list[str]:
    clidoc, visible, sections = _cli()
    out = [
        "## Commands",
        "",
        "`karni <command> --help` prints the same. Generated from the CLI's own help text "
        "(docs/cli.md has the same entries).",
        "",
    ]
    for title, names in sections:
        out += [f"### {title}", ""]
        for name in names:
            out += clidoc._command(name, visible[name], 4)
    return out


def commands_block() -> list[str]:
    clidoc, visible, sections = _cli()
    rows = []
    for _, names in sections:
        for name in names:
            command = visible[name]
            text = cell(first_sentence(command.help).rstrip(" .:") or "—")
            subs = [s for s, c in clidoc._subcommands(command).items() if not c.hidden]
            if subs:
                links = ", ".join(f"[{s}]({ref(slug(f'karni {name} {s}'))})" for s in subs)
                text = f"{text}: {links}"
            rows.append((f"[`karni {name}`]({ref(slug(f'karni {name}'))})", text))
    return ["| Command | What it does |", "|---|---|", *(f"| {a} | {b} |" for a, b in rows)]


# --- base classes -------------------------------------------------------------

BASE_MODULES: tuple[tuple[str, str], ...] = (
    ("karni.models", "Models"),
    ("karni.api", "API"),
    ("karni.admin", "Admin"),
    ("karni.testing", "Testing"),
)


def _annotation(value: Any) -> str:
    return value if isinstance(value, str) else inspect.formatannotation(value)


def _signature(obj: Callable[..., Any]) -> str:
    """``(a: int, *, b: str = 'x') -> None`` with annotations unquoted and sentinels as ``…``."""
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return ""
    parts: list[str] = []
    star_done = False
    for param in signature.parameters.values():
        if param.kind is param.KEYWORD_ONLY and not star_done:
            parts.append("*")
            star_done = True
        if param.kind is param.VAR_POSITIONAL:
            star_done = True
        prefix = {param.VAR_POSITIONAL: "*", param.VAR_KEYWORD: "**"}.get(param.kind, "")
        text = prefix + param.name
        if param.annotation is not param.empty:
            text += f": {_annotation(param.annotation)}"
        if param.default is not param.empty:
            default = param.default
            shown = "…" if type(default) is object else repr(default)
            text += f" = {shown}"
        parts.append(text)
    result = f"({', '.join(parts)})"
    if signature.return_annotation is not signature.empty:
        result += f" -> {_annotation(signature.return_annotation)}"
    return result


def _model_gets(cls: type) -> str:
    meta = cls._meta  # type: ignore[attr-defined]
    fields = [f.name for f in meta.get_fields() if getattr(f, "concrete", False)]
    parts = [f"fields {', '.join(f'`{n}`' for n in fields)}"] if fields else []
    managers = [
        f"`{m.name}`" + ("" if type(m).__name__.startswith("_") else f" ({type(m).__name__})")
        for m in meta.managers
    ]
    if managers:
        parts.append(f"managers {', '.join(managers)}")
    return "; ".join(parts)


def _own_methods(cls: type) -> list[str]:
    return [
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, type)
    ]


def _viewset_gets(cls: type) -> str:
    from rest_framework.viewsets import ModelViewSet

    declared = [
        name
        for name, value in vars(cls).items()
        if not name.startswith("_")
        and not hasattr(ModelViewSet, name)
        and not callable(value)
        and not isinstance(value, property | classmethod | staticmethod)
    ]
    endpoints = ["list", "create", "retrieve", "update", "partial_update", "destroy"]
    extra = sorted(
        re.sub(r"\(\?P<(\w+)>[^)]*\)", r"<\1>", action.url_path)
        for action in cls.get_extra_actions()  # type: ignore[attr-defined]
    )
    return (
        f"declare {', '.join(f'`{n}`' for n in declared)}; endpoints "
        f"{', '.join(f'`{e}`' for e in endpoints + extra)}"
    )


def _admin_gets(cls: type) -> str:
    from django.contrib.admin import ModelAdmin

    hooks = [n for n in _own_methods(cls) if hasattr(ModelAdmin, n)]
    return f"overrides {', '.join(f'`{h}`' for h in hooks)}" if hooks else ""


def base_entries() -> list[tuple[str, list[tuple[str, str, str, str]]]]:
    """(module, [(name, kind, purpose, what a subclass or caller gets)])."""
    from django.db import models

    result = []
    for module_name, _ in BASE_MODULES:
        module = importlib.import_module(module_name)
        rows = []
        for name in module.__all__:
            obj = getattr(module, name)
            purpose = first_paragraph(inspect.getdoc(obj) if not isinstance(obj, tuple) else "")
            gets = ""
            if isinstance(obj, type) and issubclass(obj, models.Model):
                kind, gets = "model", _model_gets(obj)
            elif isinstance(obj, type) and hasattr(obj, "get_extra_actions"):
                kind, gets = "viewset", _viewset_gets(obj)
            elif isinstance(obj, type) and module_name == "karni.admin":
                kind, gets = "admin class", _admin_gets(obj)
            elif isinstance(obj, type) and issubclass(obj, models.QuerySet | models.Manager):
                kind = "queryset" if issubclass(obj, models.QuerySet) else "manager"
                own = _own_methods(obj)
                gets = f"methods {', '.join(f'`{m}`' for m in own)}" if own else ""
            elif isinstance(obj, type):
                kind = "class"
                own_init = "__init__" in vars(obj) or hasattr(obj, "__dataclass_fields__")
                signature = _signature(obj) if own_init else ""
                if signature and signature not in ("()", "() -> None"):
                    gets = f"`{name}{signature}`"
                else:
                    own = _own_methods(obj)
                    gets = f"methods {', '.join(f'`{m}`' for m in own)}" if own else ""
            elif callable(obj):
                kind, gets = "function", f"`{name}{_signature(obj)}`"
            else:
                kind = "constant"
                purpose = purpose or f"`{name}`: {', '.join(f'`{v}`' for v in obj)}"
            rows.append((name, kind, purpose, gets))
        result.append((module_name, rows))
    return result


def bases_section() -> list[str]:
    out = [
        "## Base classes",
        "",
        "The public names of the four packages a project builds on, from their `__all__`. "
        "*What you get* is read from the class itself: the fields and managers a model "
        "inherits, the attributes a viewset declares and the endpoints it serves, the admin "
        "hooks it overrides, a function's signature.",
        "",
    ]
    for module_name, rows in base_entries():
        out += [f"### {module_name}", ""]
        out += table(
            ("Name", "Kind", "Purpose", "What you get"),
            [(f"`{n}`", k, p, g) for n, k, p, g in rows],
        )
    return out


# --- class Karni ---------------------------------------------------------------


def _module_dirs() -> list[Path]:
    return sorted(p for p in (ROOT / "modules").iterdir() if (p / "pyproject.toml").is_file())


def _package_of(module_dir: Path) -> str:
    return module_dir.name.replace("-", "_")


def options() -> list[tuple[str, Any]]:
    from karni.meta import OPTIONS

    found: list[tuple[str, Any]] = [("karni", option) for option in OPTIONS]
    for module_dir in _module_dirs():
        package = _package_of(module_dir)
        try:
            meta = importlib.import_module(f"{package}.meta")
        except ModuleNotFoundError:
            continue
        found += [(module_dir.name, option) for option in getattr(meta, "KARNI_OPTIONS", ())]
    return found


def read_option_keys() -> dict[str, list[str]]:
    """Keys code reads with ``karni_option(model, "key")``, by key → files."""
    sources = [ROOT / "packages" / "karni" / "karni"]
    sources += [module_dir / _package_of(module_dir) for module_dir in _module_dirs()]
    found: dict[str, list[str]] = {}
    for base in sources:
        for path in sorted(base.rglob("*.py")):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or len(node.args) < 2:
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                key = node.args[1]
                if name in ("karni_option", "_callable_option") and isinstance(key, ast.Constant):
                    found.setdefault(str(key.value), []).append(str(path.relative_to(ROOT)))
    return found


def options_section() -> list[str]:
    rows = [
        (f"`{o.name}`", source, o.default, o.summary, f"`{o.example}`") for source, o in options()
    ]
    return [
        "## Model metadata (`class Karni`)",
        "",
        "A model declares what Karni's data-driven layers need to know in a nested "
        "`class Karni`, next to `Meta`. Every key is optional. Modules add their own keys; "
        "the *From* column says which package reads it.",
        "",
        "```python",
        "class Lead(BaseModel):",
        "    class Karni:",
        '        owner_field = "workspace__members"',
        "        audit = True",
        "```",
        "",
        *table(("Key", "From", "Default", "What it controls", "Example"), rows),
    ]


# --- settings ------------------------------------------------------------------


def _module_settings(module_dir: Path) -> list[tuple[str, str, str, str]]:
    path = module_dir / _package_of(module_dir) / "conf.py"
    if not path.is_file():
        return []
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    rows = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.AnnAssign | ast.Assign)):
            continue
        targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
        if not any(isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not isinstance(key, ast.Constant):
                continue
            comments = []
            index = key.lineno - 2
            while index >= 0 and lines[index].strip().startswith("#"):
                comments.insert(0, lines[index].strip().lstrip("#").strip())
                index -= 1
            if not comments and rows:
                comments = [rows[-1][3]]
            env, default = "", ""
            if isinstance(value, ast.Call):
                if value.args and isinstance(value.args[0], ast.Constant):
                    env = str(value.args[0].value)
                for keyword in value.keywords:
                    if keyword.arg == "default":
                        default = ast.get_source_segment(source, keyword.value) or ""
            else:
                default = ast.get_source_segment(source, value) or ""
            rows.append(
                (
                    f"`{key.value}`",
                    f"`{env}`" if env else "—",
                    f"`{' '.join(default.split())}`",
                    " ".join(comments),
                )
            )
    return rows


def settings_section() -> list[str]:
    from karni.conf.reference import settings

    out = [
        "## Settings",
        "",
        "`karni_settings(globals())` in `config/settings.py` defines every setting below; "
        "anything assigned after the call wins. Each is read from the environment variable "
        "in the *Env* column when one is named. The Django and DRF settings Karni derives "
        "are described in [settings](settings.md).",
        "",
    ]
    section = None
    rows: list[tuple[str, str, str, str]] = []
    for entry in settings():
        if entry.section != section:
            if rows:
                out += table(("Setting", "Env", "Default", "What it controls"), rows)
                rows = []
            section = entry.section
            out += [f"### {section}", ""]
        rows.append(
            (
                f"`{entry.name}`",
                f"`{entry.env}`" if entry.env else "—",
                f"`{entry.default}`",
                entry.description,
            )
        )
    if rows:
        out += table(("Setting", "Env", "Default", "What it controls"), rows)
    for module_dir in _module_dirs():
        module_rows = _module_settings(module_dir)
        if module_rows:
            out += [f"### Module: {module_dir.name}", ""]
            out += table(("Setting", "Env", "Default", "What it controls"), module_rows)
    return out


# --- components and hooks ----------------------------------------------------


def ui_exports() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["node", str(ROOT / "scripts" / "gen_reference_ui.mjs")],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    exports: list[dict[str, Any]] = json.loads(result.stdout)
    return exports


def _source_link(rel: str) -> str:
    return f"[{Path(rel).name}]({repo_link(rel)})"


def ui_section(exports: list[dict[str, Any]]) -> list[str]:
    components = [e for e in exports if e["kind"] == "component"]
    hooks = [e for e in exports if e["kind"] == "hook"]
    others = [e for e in exports if e["kind"] not in ("component", "hook")]

    def props(entry: dict[str, Any]) -> str:
        required = entry.get("required") or []
        return ", ".join(f"`{p['name']}: {p['type']}`" for p in required) or "—"

    out = [
        "## Components and hooks",
        "",
        "Every value `@karni/ui` exports, read from its barrel (`src/index.ts`) with the "
        "TypeScript compiler. *Required props* are the props without a default; every "
        "component takes more ([UI guide](ui.md)).",
        "",
        "### Components",
        "",
        *table(
            ("Component", "Required props", "What it renders", "Source"),
            [
                (f"`{e['name']}`", props(e), e["summary"], _source_link(e["source"]))
                for e in components
            ],
        ),
        "### Hooks",
        "",
        *table(
            ("Hook", "Parameters", "What it does", "Source"),
            [
                (
                    f"`{e['name']}`",
                    ", ".join(f"`{p}`" for p in e.get("parameters", [])) or "—",
                    e["summary"],
                    _source_link(e["source"]),
                )
                for e in hooks
            ],
        ),
        "### Functions and constants",
        "",
        *table(
            ("Name", "Kind", "What it is", "Source"),
            [
                (f"`{e['name']}`", e["kind"], e["summary"], _source_link(e["source"]))
                for e in others
            ],
        ),
    ]
    return out


# --- modules ---------------------------------------------------------------------


def _scope(description: str) -> str:
    """A module's own sentence from its PyPI description.

    The description is "<what the module is> <Karni's canonical description>"
    (scripts/check_description.py): the canonical part is dropped, and so is a
    "… for Karni: " preamble.
    """
    canonical_file = ROOT / "docs" / "seo" / "description.txt"
    if canonical_file.is_file():
        canonical = canonical_file.read_text(encoding="utf-8").strip()
        description = description.removesuffix(canonical).strip()
    for preamble in (" for Karni: ", " framework: "):
        head, sep, rest = description.partition(preamble)
        if sep and "Karni" in head + preamble:
            return re.sub(r"[a-z]", lambda m: m.group(0).upper(), rest, count=1)
    return description


def modules() -> list[dict[str, str]]:
    found = []
    for module_dir in _module_dirs():
        project = tomllib.loads((module_dir / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        short = module_dir.name.removeprefix("karni-")
        ui = module_dir / "ui" / "package.json"
        status = "stable" if short in MODULE_EVIDENCE else "experimental"
        found.append(
            {
                "short": short,
                "name": project["name"],
                "version": project["version"],
                "description": _scope(project["description"]),
                "ui": json.loads(ui.read_text(encoding="utf-8"))["name"] if ui.is_file() else "",
                "status": status,
                "path": f"modules/{module_dir.name}",
            }
        )
    for short, link in MODULE_PLANNED.items():
        found.append(
            {
                "short": short,
                "name": f"karni-{short}",
                "version": "",
                "description": "",
                "ui": "",
                "status": "planned",
                "path": link,
            }
        )
    return found


def modules_section() -> list[str]:
    rows = []
    for m in modules():
        if m["status"] == "planned":
            rows.append(
                (
                    f"`{m['name']}`",
                    "planned",
                    "—",
                    "—",
                    f"[documented]({m['path'].removeprefix('docs/')})",
                )
            )
            continue
        rows.append(
            (
                f"[`{m['name']}`]({repo_link(m['path'], tree=True)})",
                m["status"],
                f"`karni add {m['short']}`",
                f"`{m['ui']}`" if m["ui"] else "—",
                m["description"],
            )
        )
    return [
        "## Modules",
        "",
        "Optional apps for anything with a RAM cost or a separate service. `karni add <name>` "
        "adds the dependency to `pyproject.toml`, wires the app into `INSTALLED_APPS` and "
        "records the module's agent guidance ([modules](modules.md)).",
        "",
        *table(("Module", "Status", "Install", "UI package", "Scope"), rows),
    ]


# --- error codes ----------------------------------------------------------------


def errors_section() -> list[str]:
    from karni.errorcodes import CODES as CORE
    from karni_cli import agent_data, errordoc
    from karni_cli.errorcodes import CODES as CLI
    from karni_cli.errorcodes import _module_entries

    def link(code: str) -> str:
        return f"[`{code}`](errors.md#{code.lower().replace('/', '-')})"

    groups: list[tuple[str, list[tuple[str, str, str]]]] = [
        (
            "Karni (`E`, `W`)",
            [(e.code, e.kind, e.title) for e in sorted(CORE, key=lambda e: e.code[1:])],
        ),
        (
            "Modules",
            [(e.code, e.kind, e.title) for e in sorted(_module_entries(), key=lambda e: e.code)],
        ),
        ("The `karni` command (`C`)", [(e.code, "cli", e.title) for e in CLI]),
        (
            "Agent rules (`K`)",
            [
                (str(r["code"]), "rule", str(r["summary"]))
                for r in sorted(agent_data.load(None).rules, key=lambda r: str(r["code"]))
            ],
        ),
        (
            "ESLint plugin (`karni/…`)",
            [(r["id"], "lint", r["title"]) for r in errordoc._eslint_manifest()],
        ),
    ]
    out = [
        "## Error codes",
        "",
        "Every code Karni, its modules, the CLI, the agent rules and the ESLint plugin can "
        "report. The [error page](errors.md) has why each happens and the fix; "
        "`karni explain <code>` prints the same offline.",
        "",
    ]
    for title, rows in groups:
        out += [f"### {title}", ""]
        out += table(("Code", "Kind", "Meaning"), [(link(c), k, t) for c, k, t in rows])
    return out


# --- make targets and slash commands --------------------------------------------


def make_targets() -> list[tuple[str, list[str]]]:
    lines = (SCAFFOLD / "Makefile").read_text(encoding="utf-8").splitlines()
    targets: list[tuple[str, list[str]]] = []
    for line in lines:
        match = re.match(r"^([a-z][a-z0-9-]*):\s*$", line)
        if match:
            targets.append((match.group(1), []))
        elif line.startswith("\t") and targets:
            targets[-1][1].append(line.strip())
    return targets


def procedures() -> tuple[list[Any], list[dict[str, Any]]]:
    from karni.agent import PROCEDURES

    adapters = tomllib.loads(
        (ROOT / "packages" / "karni-cli" / "karni_cli" / "agent_adapters.toml").read_text(
            encoding="utf-8"
        )
    )
    return list(PROCEDURES), list(adapters.get("commands", []))


def make_and_slash_section() -> list[str]:
    targets = [(f"`make {t}`", "; ".join(f"`{c}`" for c in cmds)) for t, cmds in make_targets()]
    procs, adapters = procedures()
    where = [(a["tool"], f"`{a['dir']}/<name>{a['suffix']}`") for a in adapters]
    return [
        "## Make targets",
        "",
        "The Makefile `karni new` writes. Every target is a thin alias for a `karni` command.",
        "",
        *table(("Target", "Runs"), targets),
        "## Slash commands",
        "",
        "One per routine task, written for each agent tool by `karni new` and "
        "`karni rules sync`; `karni rules --procedure <name>` prints the same steps.",
        "",
        *table(
            ("Command", "Arguments", "What it does"),
            [(f"`/{p.name}`", f"`{p.argument_hint}`", p.description) for p in procs],
        ),
        *table(("Tool", "Written to"), where),
    ]


# --- capabilities -----------------------------------------------------------------


def capabilities_section() -> list[str]:
    out = ["## Capabilities and status", "", STATUS_NOTE, ""]
    for area, title in AREAS:
        rows = []
        for c in capabilities(area):
            if c.planned:
                proof = f"[documented]({c.planned.removeprefix('docs/')})"
            elif c.evidence:
                proof = ", ".join(f"[{Path(rel).name}]({repo_link(rel)})" for rel, _ in c.evidence)
            else:
                proof = "Karni's own tests"
            rows.append((c.text, f"`{c.status}`", proof))
        out += [f"### {title}", ""]
        out += table(("Capability", "Status", "Evidence"), rows)
    return out


# --- the reference page -------------------------------------------------------------

CONTENTS: tuple[tuple[str, str], ...] = (
    ("Capabilities and status", "capabilities-and-status"),
    ("Commands", "commands"),
    ("Base classes", "base-classes"),
    ("Model metadata (class Karni)", "model-metadata-class-karni"),
    ("Settings", "settings"),
    ("Components and hooks", "components-and-hooks"),
    ("Modules", "modules"),
    ("Error codes", "error-codes"),
    ("Make targets", "make-targets"),
    ("Slash commands", "slash-commands"),
)


def render_reference(exports: list[dict[str, Any]]) -> str:
    out = [
        "---",
        "description: Every Karni command, base class, model option, setting, component, hook, "
        "module, error code, make target and slash command, generated from the source.",
        "---",
        "",
        "# Reference",
        "",
        "<!-- Generated by `python scripts/gen_reference.py`; CI fails when it is stale. "
        "Never edit by hand. -->",
        "",
        "Generated from the source of this commit by `scripts/gen_reference.py`. CI "
        "regenerates it and fails when the committed copy differs, so what is here is what "
        "the code does.",
        "",
        *[f"- [{title}](#{anchor})" for title, anchor in CONTENTS],
        "",
    ]
    for part in (
        capabilities_section(),
        commands_section(),
        bases_section(),
        options_section(),
        settings_section(),
        ui_section(exports),
        modules_section(),
        errors_section(),
        make_and_slash_section(),
    ):
        out += part
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).rstrip("\n") + "\n"


# --- README blocks ------------------------------------------------------------------


def _capability_lines(area: str) -> list[str]:
    return [f"- `{c.status}` {c.text}" for c in capabilities(area)]


def readme_blocks(exports: list[dict[str, Any]]) -> dict[str, list[str]]:
    components = [e["name"] for e in exports if e["kind"] == "component"]
    hooks = [e["name"] for e in exports if e["kind"] == "hook"]
    bases = dict(base_entries())
    blocks: dict[str, list[str]] = {
        "commands": commands_block(),
        "make-targets": [
            "```sh",
            *[f"make {t:<10} # {'; '.join(cmds)}" for t, cmds in make_targets()],
            "```",
        ],
    }
    for area, _ in AREAS:
        blocks[area] = _capability_lines(area)
    blocks["models"] += [
        "",
        "Base classes: "
        + ", ".join(f"`{n}`" for n, k, _, _ in bases["karni.models"] if k == "model")
        + ".",
    ]
    blocks["api"] += [
        "",
        "Declarations: "
        + ", ".join(f"`{n}`" for n, k, _, _ in bases["karni.api"] if k == "class")
        + ".",
    ]
    blocks["ui"] += [
        "",
        f"{len(components)} components and {len(hooks)} hooks, among them "
        + ", ".join(
            f"`{n}`"
            for n in components
            if n.startswith(("Resource", "Auth", "Login", "Page", "Layout"))
        )
        + "; hooks "
        + ", ".join(f"`{n}`" for n in hooks)
        + ".",
    ]
    blocks["testing"] += [
        "",
        "Helpers: " + ", ".join(f"`{n}`" for n, _, _, _ in bases["karni.testing"]) + ".",
    ]
    module_lines = []
    for m in modules():
        if m["status"] == "planned":
            module_lines.append(f"- `planned` `karni-{m['short']}`")
        else:
            module_lines.append(
                f"- `{m['status']}` `karni add {m['short']}`: {first_sentence(m['description'])}"
            )
    blocks["modules"] = module_lines
    procs, _ = procedures()
    blocks["agents"] += ["", "Slash commands: " + ", ".join(f"`/{p.name}`" for p in procs) + "."]
    return blocks


def apply_blocks(readme: str, blocks: dict[str, list[str]]) -> str:
    for name, lines in blocks.items():
        start, end = f"<!-- generated:{name} -->", f"<!-- /generated:{name} -->"
        pattern = re.compile(rf"{re.escape(start)}\n.*?{re.escape(end)}", re.S)
        if not pattern.search(readme):
            raise SystemExit(f"README.md has no {start} block")
        block = start + "\n" + "\n".join(lines) + "\n" + end
        readme = pattern.sub(lambda _m, block=block: block, readme)
    return readme


def check_links(readme: str, reference: str) -> list[str]:
    defined = anchors(reference)
    problems = []
    for anchor in re.findall(rf"{re.escape(REF_LINK)}#([\w-]+)", readme):
        if anchor not in defined:
            problems.append(f"README links {REF_LINK}#{anchor}, which has no such anchor")
    return problems


# --- main -------------------------------------------------------------------------


def setup_django() -> None:
    sys.path.insert(0, str(ROOT / "packages" / "karni"))
    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
    warnings.simplefilter("ignore")
    import django

    django.setup()


def unknown_option_keys() -> list[str]:
    declared = {option.name for _, option in options()}
    return [
        f"class Karni key {key!r} is read in {', '.join(sorted(set(files)))} but declared "
        "in no OPTIONS / KARNI_OPTIONS list"
        for key, files in sorted(read_option_keys().items())
        if key not in declared
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when a file is stale")
    args = parser.parse_args(argv)
    setup_django()
    problems = verify_evidence() + unknown_option_keys()
    exports = ui_exports()
    reference = render_reference(exports)
    readme = apply_blocks(README.read_text(encoding="utf-8"), readme_blocks(exports))
    problems += check_links(readme, reference)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    stale = []
    for path, text in ((REFERENCE, reference), (README, readme)):
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if current == text:
            continue
        stale.append(path)
        if args.check:
            diff = difflib.unified_diff(
                current.splitlines(),
                text.splitlines(),
                str(path.relative_to(ROOT)),
                "generated",
                lineterm="",
            )
            print("\n".join(list(diff)[:80]), file=sys.stderr)
        else:
            path.write_text(text, encoding="utf-8")
    if args.check and stale:
        names = ", ".join(str(p.relative_to(ROOT)) for p in stale)
        print(
            f"\n{names} out of date: run `python scripts/gen_reference.py` and commit.",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(
            f"wrote {', '.join(str(p.relative_to(ROOT)) for p in stale) or 'nothing (up to date)'}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
