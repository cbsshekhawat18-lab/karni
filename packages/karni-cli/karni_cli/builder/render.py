"""Experimental. The code ``karni build`` writes, rendered from the spec.

Every Karni-owned file and block (:mod:`karni_cli.builder.layout`) is a
function of the spec, the project's ``KARNI_PK``, the project's own routes
and which entities and pages Karni manages, so the same inputs always give
the same bytes. The fields, the viewset's access, the test and the pages
come from the generators ``karni make`` uses (:mod:`karni_cli.generators`),
so ``karni build`` and ``karni make`` write the same code.

For one entity, ``Session`` in the app ``classes``::

    classes/karni/models.py     class Session(BaseModel): the fields, Meta, Karni, AdminMeta
                                (abstract: Django migrates the project's subclass)
    classes/models.py           class Session(karni.Session): the project's methods
    classes/karni/api.py        class SessionViewSet(BaseViewSet): model, access, search
    classes/viewsets.py         class SessionViewSet(karni.SessionViewSet): the project's actions
    classes/karni/seeds.py      class SessionSeeder(Seeder): the seed count
    classes/seeds.py            class SessionSeeder(karni.SessionSeeder): the project's values
    classes/tests/karni/test_session.py   assert_crud (and assert_isolated)

The project's files (``models.py``, ``viewsets.py``, ``seeds.py``) are
created once, and a missing class is appended to them. Nothing in them is
ever rewritten, except the class line of a renamed entity (``was:``), and
the class of a removed entity while its body is still the one build wrote.

Override / escape hatch: each subclass in the project's files overrides
anything of its Karni base (a method, ``access``, ``class Karni(karni.Session.Karni)``),
``access: code`` leaves the access to the project's viewset, and a page of
kind ``code`` leaves the page to the project.
"""

from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Final

from karni_cli.builder import layout
from karni_cli.generators import apitest as test_gen
from karni_cli.generators import page as page_gen
from karni_cli.generators.app import plan as plan_app
from karni_cli.generators.core import SETTINGS, App, Workspace, local_apps
from karni_cli.generators.fields import (
    FieldSpec,
    RelationTarget,
    is_user_target,
    parse_fields,
    relation_name,
    render_model_body,
)
from karni_cli.generators.introspect import ModelInfo
from karni_cli.generators.naming import default_route
from karni_cli.generators.pysource import (
    Import,
    call,
    comment,
    docstring,
    ensure_imports,
    parse,
    pystr,
    tuple_literal,
)
from karni_cli.project import CliError
from karni_cli.spec import catalog, schema
from karni_cli.spec.normal import related_tab

__all__ = [
    "BLOCK_END",
    "BLOCK_START",
    "HEADER",
    "Inputs",
    "Output",
    "access_expression",
    "render",
    "settings_block",
]

#: Experimental. The first line of every Karni-owned Python file and page.
HEADER: Final = "Written by karni build from karni.yaml. Do not edit it: karni build rewrites it."
#: Experimental. The markers of the settings block (Python) and the routes blocks (``//``).
BLOCK_START: Final = "karni:spec start"
BLOCK_END: Final = "karni:spec end"
_ROUTE_BLOCKS: Final = {
    layout.ROUTES_BLOCKS[0]: ("karni:spec imports", page_gen.IMPORT_MARKER),
    layout.ROUTES_BLOCKS[1]: ("karni:spec routes", page_gen.ROUTE_MARKER),
}
_PREDICATES: Final = {
    "public": "Public",
    "authenticated": "Authenticated",
    "granted": "Granted",
}
#: The body of a class build appends to a project file: the line build recognises as its own.
STUB: Final = "The base class comes from karni.yaml (karni build). Add your own code here."
#: Experimental. The line a stub class's body is.
STUB_LINE: Final = f'    """{STUB}"""'
#: What build writes in the project's viewset for ``access: code``: a start the project changes.
_ACCESS_STUB: Final = [
    "",
    "    # access: code in karni.yaml. Who reads and writes is declared here, by the project.",
    "    access = Granted()",
]


@dataclass
class Inputs:
    """Experimental. What a render reads besides the files themselves."""

    spec: schema.Spec
    #: The project's ``KARNI_PK``: the key type of an entity that does not say.
    pk: str
    #: ``app.Entity`` labels whose code Karni writes.
    entities: set[str]
    #: ``app.Entity:kind`` and ``name:kind`` of the pages Karni writes.
    pages: set[str]
    #: Karni-owned files and blocks handed to the project (never written).
    adopted: set[str]
    #: new label -> old label, for the entities renamed in this build.
    renames: dict[str, str] = field(default_factory=dict)
    #: labels of the entities this build removes (their project classes go too).
    removed: set[str] = field(default_factory=set)


@dataclass
class Output:
    """Experimental. A render: every file in the workspace, and the Karni-owned ones by name."""

    ws: Workspace
    #: Karni-owned file -> its content (adopted files left out).
    files: dict[str, str] = field(default_factory=dict)
    #: Block name (:data:`layout.SETTINGS_BLOCK`, :data:`layout.ROUTES_BLOCKS`) -> its content.
    blocks: dict[str, str] = field(default_factory=dict)
    #: What each project file gained: path -> the classes appended or renamed.
    project: dict[str, list[str]] = field(default_factory=dict)


# the spec, entity by entity -------------------------------------------------------


def _entities(spec: schema.Spec) -> dict[str, tuple[str, str, schema.Entity]]:
    return {
        f"{app}.{name}": (app, name, entity)
        for app, application in spec.apps.items()
        for name, entity in application.entities.items()
    }


def _specs(entity: schema.Entity) -> list[FieldSpec]:
    return parse_fields([f"{name}:{token}" for name, token in entity.tokens().items()])


def _targets(
    spec: schema.Spec, app: str, name: str, specs: list[FieldSpec]
) -> dict[str, RelationTarget]:
    """The relation targets of ``specs``, resolved in the spec (as karni make model does in code)."""
    found: dict[str, RelationTarget] = {}
    for field_spec in specs:
        if not field_spec.is_relation:
            continue
        raw = relation_name(field_spec)
        if is_user_target(raw):
            found[field_spec.name] = RelationTarget("settings.AUTH_USER_MODEL", True, "user")
        elif raw in ("self", name, f"{app}.{name}"):
            found[field_spec.name] = RelationTarget(pystr("self"), False, "self")
        elif "." in raw:
            found[field_spec.name] = RelationTarget(pystr(raw), False, raw.lower())
        elif raw in spec.apps[app].entities:
            found[field_spec.name] = RelationTarget(pystr(raw), False, f"{app}.{raw}".lower())
        else:
            owners = [label for label, a in spec.apps.items() if raw in a.entities]
            target = f"{owners[0]}.{raw}" if len(owners) == 1 else raw
            found[field_spec.name] = RelationTarget(pystr(target), False, target.lower())
    return found


def _db_table(table: str) -> str:
    """The spec's ``schema.table`` as ``Meta.db_table`` (``schema"."table``)."""
    return table.replace(".", '"."')


def _base(entity: schema.Entity, pk: str) -> tuple[str, list[str], str]:
    """``(class bases, names to import from karni.models, Meta's base)``."""
    if entity.external:
        return "models.Model", [], ""
    key = entity.pk or pk
    if entity.database not in (None, "default"):
        # the audit users point at the user table on default: compose the mixins without them
        mixin = "UUIDModel" if key == "uuid" else "IntegerKeyModel"
        return f"{mixin}, TimestampedModel", [mixin, "TimestampedModel"], ""
    base = "BaseModel" if key == "uuid" else "BigIntBaseModel"
    return base, [base], f"{base}.Meta"


def _literal(value: Any, indent: str, line_length: int, head: str = "") -> str:
    """A Python literal laid out the way ruff format lays it out (one item per line when long)."""
    flat = f"{indent}{head}{_flat(value)}"
    if len(flat) <= line_length or not isinstance(value, dict | list | tuple) or not value:
        return flat
    inner = indent + "    "
    if isinstance(value, dict):
        items = [
            _literal(item, inner, line_length, f"{_flat(key)}: ") for key, item in value.items()
        ]
        open_, close = "{", "}"
    else:
        items = [_literal(item, inner, line_length) for item in value]
        open_, close = ("[", "]") if isinstance(value, list) else ("(", ")")
    body = "".join(f"{item},\n" for item in items)
    return f"{indent}{head}{open_}\n{body}{indent}{close}"


def _flat(value: Any) -> str:
    if isinstance(value, str):
        return pystr(value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_flat(k)}: {_flat(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_flat(item) for item in value) + "]"
    if isinstance(value, tuple):
        inner = ", ".join(_flat(item) for item in value)
        return f"({inner},)" if len(value) == 1 else f"({inner})"
    return repr(value)


def _model_class(
    spec: schema.Spec, app: str, name: str, entity: schema.Entity, pk: str, line: int
) -> tuple[list[str], list[Import], list[str]]:
    """``(lines, imports, notes)`` of the abstract class of one entity."""
    specs = _specs(entity)
    body = render_model_body(
        specs, model=name, app_label=app, resolve=_targets(spec, app, name, specs), line_length=line
    )
    bases, karni_names, meta_base = _base(entity, pk)
    imports = [*body.imports, *(Import("karni.models", n) for n in karni_names)]
    if entity.external:
        imports.append(Import("django.db", "models"))
    lines = [f"class {name}({bases}):"]
    if body.inner:
        lines += [*body.inner, ""]
    lines += body.lines
    meta = ["abstract = True"]
    if entity.external:
        meta += ["managed = False", f"db_table = {pystr(_db_table(entity.table or ''))}"]
    if entity.order:
        meta.append(_literal(list(entity.order), "", line - 8, "ordering = "))
    lines += ["", f"    class Meta{f'({meta_base})' if meta_base else ''}:"]
    lines += [f"        {row}" for item in meta for row in item.splitlines()]
    options: list[tuple[str, Any]] = []
    if entity.external:
        options.append(("external", True))
    if entity.writable:
        options.append(("writable", True))
    if entity.database not in (None, "default"):
        options.append(("database", entity.database))
    for key, option in (("key", "import_key"), ("owner", "owner_field")):
        value = getattr(entity, key)
        if value:
            options.append((option, value))
    if entity.audit:
        options.append(("audit", entity.audit if entity.audit is True else list(entity.audit)))
    if entity.scope_paths:
        options.append(("scope_paths", dict(entity.scope_paths)))
    if options:
        lines += ["", "    class Karni:"]
        lines += [_literal(value, "        ", line, f"{key} = ") for key, value in options]
    if entity.groups:
        sets: list[Any] = [
            (title, {"fields": list(names)}) for title, names in entity.groups.items()
        ]
        grouped = {member for names in entity.groups.values() for member in names}
        rest = [s.name for s in specs if s.name not in grouped]
        if rest:
            sets.append((None, {"fields": rest}))
        lines += ["", "    class AdminMeta:"]
        lines.append(_literal({"fieldsets": sets}, "        ", line, "extra = "))
    shown = next((s.name for s in specs if s.is_text), None)
    if shown is not None:
        lines += ["", "    def __str__(self) -> str:", f"        return self.{shown}"]
    return lines, imports, body.notes


def _header(purpose: str, line: int) -> str:
    """A Karni-owned module's docstring: the header line, then what the file is for."""
    body = textwrap.wrap(purpose, width=max(line, 40))
    return "\n".join([f'"""{HEADER}', "", *body, '"""']) + "\n"


def _module(ws: Workspace, rel: str, purpose: str, imports: list[Import], blocks: list[str]) -> str:
    """A Karni-owned module: the header docstring, the imports, the classes."""
    text = _header(purpose, ws.line_length)
    text = ensure_imports(ws, rel, text, imports) if imports else text
    for block in blocks:
        text = text.rstrip("\n") + "\n\n\n" + block.rstrip("\n") + "\n"
    return text


# access ---------------------------------------------------------------------------


def access_expression(items: list[str]) -> tuple[str, list[str]]:
    """Experimental. ``(predicate expression, names to import)`` for one access slot of the spec."""
    parts: list[str] = []
    names: list[str] = []
    for item in items:
        kind, _, arg = item.partition(":")
        if kind in _PREDICATES:
            parts.append(f"{_PREDICATES[kind]}()")
            names.append(_PREDICATES[kind])
        elif kind == "role":
            parts.append(f"HasRole({pystr(arg)})")
            names.append("HasRole")
        else:
            parts.append(f"Owned({pystr(arg)})")
            names.append("Owned")
    return " | ".join(parts), names


def _access_line(access: schema.Access, line: int) -> tuple[str, list[str]]:
    """``access = ...`` for a rule (``Granted()`` alone for the default), and the names it uses."""
    if access.read == access.write == ["granted"] and access.create is None:
        return "    access = Granted()", ["Granted"]
    args: list[str] = []
    names = ["Access"]
    for slot in ("read", "write", "create"):
        items = getattr(access, slot)
        if items is None:
            continue
        expression, used = access_expression(list(items))
        args.append(f"{slot}={expression}")
        names += used
    return call("access = Access", args, "    ", line), names


# per app ---------------------------------------------------------------------------


def _models_file(
    ws: Workspace, inputs: Inputs, app: str, names: list[str]
) -> tuple[str, list[str]]:
    rel = layout.models_file(app)
    blocks: list[str] = []
    imports: list[Import] = []
    notes: list[str] = []
    for name in names:
        entity = inputs.spec.apps[app].entities[name]
        lines, wanted, found = _model_class(
            inputs.spec, app, name, entity, inputs.pk, ws.line_length
        )
        blocks.append("\n".join(lines))
        imports += wanted
        notes += found
    purpose = f"Your own code goes in {app}/models.py, in the subclass of each class here."
    return _module(ws, rel, purpose, sorted(set(imports)), blocks), notes


def _api_file(ws: Workspace, inputs: Inputs, app: str, names: list[str]) -> str:
    rel = layout.api_file(app)
    blocks: list[str] = []
    used: set[str] = {"BaseViewSet"}
    line = ws.line_length
    for name in names:
        entity = inputs.spec.apps[app].entities[name]
        body = [f"class {name}ViewSet(BaseViewSet):", f"    model = {name}"]
        if entity.access == "code":
            body.append(f"    # access: code in karni.yaml: {app}/viewsets.py declares it.")
        else:
            access, names_used = _access_line(entity.access, line)
            body.append(access)
            used |= set(names_used)
        if entity.search:
            items = [pystr(item) for item in entity.search]
            body.append(tuple_literal("search_fields = ", items, "    ", line))
        blocks.append("\n".join(body))
    imports = [Import("karni.api", item) for item in sorted(used)]
    imports += [Import(f"{app}.models", name) for name in names]
    purpose = f"Your own code goes in {app}/viewsets.py, in the subclass of each class here."
    return _module(ws, rel, purpose, imports, blocks)


def _seeds_file(ws: Workspace, inputs: Inputs, app: str, counts: dict[str, int]) -> str:
    rel = layout.seeds_file(app)
    blocks = []
    for name, count in counts.items():
        blocks.append(
            "\n".join(
                [
                    f"class {name}Seeder(Seeder):",
                    "    class Meta:",
                    f"        model = {name}",
                    f"        count = {count}",
                ]
            )
        )
    imports = [Import("karni.seeding", "Seeder"), *(Import(f"{app}.models", n) for n in counts)]
    purpose = f"The rows karni seed makes. Steer a field's values in {app}/seeds.py."
    return _module(ws, rel, purpose, imports, blocks)


def _test_file(ws: Workspace, inputs: Inputs, app: str, name: str, api_text: str) -> str:
    """The entity's API test, as karni make test writes it, for the project's viewset."""
    tree = ast.parse(api_text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == f"{name}ViewSet")
    own = _project_class(ws, f"{app}/viewsets.py", f"{name}ViewSet")
    if own is not None and any(_assigns(stmt, "access") for stmt in own.body):
        cls = own  # access: code, or the project's own declaration: the test reads the project's
    info = ModelInfo(
        App(app, app, ws.path(app)), name, ws.path(f"{app}/models.py"), {}, frozenset()
    )
    choice = test_gen.choose(ws, info, cls, None)
    text = test_gen.render(
        ws,
        name,
        f"{name}ViewSet",
        f"{app}.viewsets",
        choice.role,
        choice.isolates,
        choice.note,
        isolation_role=choice.isolation_role,
    )
    return f"{comment(HEADER, '', ws.line_length)}\n{text}"


def _assigns(stmt: ast.stmt, name: str) -> bool:
    if isinstance(stmt, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets)
    if isinstance(stmt, ast.AnnAssign):
        return isinstance(stmt.target, ast.Name) and stmt.target.id == name
    if isinstance(stmt, ast.FunctionDef):
        return stmt.name == f"get_{name}"
    return False


def _project_class(ws: Workspace, rel: str, name: str) -> ast.ClassDef | None:
    text = ws.read(rel)
    if not text:
        return None
    for node in parse(ws, rel, text).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


# the project's own files: created once, a missing class appended ---------------------


def _karni_base(node: ast.ClassDef) -> str | None:
    """``Session`` for ``class X(karni.Session)``: the Karni class a project class extends."""
    for base in node.bases:
        if (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id == "karni"
        ):
            return base.attr
    return None


def _is_stub(node: ast.ClassDef) -> bool:
    """Whether a project class still has only the body build wrote (so build may remove it)."""
    body = [stmt for stmt in node.body if not isinstance(stmt, ast.Pass)]
    if not body:
        return True
    first = body[0]
    is_doc = (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and first.value.value == STUB
    )
    rest = body[1:] if is_doc else body
    # access: code's starting declaration counts as build's own
    return all(
        isinstance(stmt, ast.Assign)
        and _assigns(stmt, "access")
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "Granted"
        and not stmt.value.args
        for stmt in rest
    )


def _project_file(
    ws: Workspace,
    rel: str,
    wanted: list[tuple[str, str, list[str]]],
    *,
    module: str,
    purpose: str,
    renames: dict[str, str],
    removed: set[str],
    extra_imports: list[Import],
) -> list[str]:
    """Plan the project file ``rel``: append each missing class of ``wanted``.

    ``wanted`` is ``(class name, Karni base name, extra body lines)``.
    ``renames`` maps a new Karni base to its old one (the class line is
    renamed), ``removed`` names Karni bases whose class goes (while it is
    still build's stub). Returns what changed, for the summary.
    """
    text = ws.read(rel)
    created = text is None
    if text is None:
        text = docstring(purpose, "", ws.line_length) + "\n"
    tree = parse(ws, rel, text)
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    by_base = {_karni_base(node): node for node in classes.values() if _karni_base(node)}
    changed: list[str] = []
    lines = text.splitlines()
    # removals and renames first, bottom up, so line numbers stay right
    edits: list[tuple[int, int, list[str]]] = []
    for base in sorted(removed):
        node = by_base.get(base)
        if node is None:
            continue
        if not _is_stub(node):
            raise CliError(
                f"{rel}: class {node.name} has code of its own, and karni.yaml removes "
                f"{base}. Move that code (or delete the class), then run karni build again.",
                code="C283",
            )
        first = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
        edits.append((first, node.end_lineno or node.lineno, []))
        changed.append(f"removed class {node.name}")
    for new, old in renames.items():
        node = by_base.get(old)
        if node is None or new in by_base:
            continue
        index = node.lineno - 1
        header = lines[index]
        renamed = re.sub(rf"\b{re.escape(old)}\b", new, header)
        edits.append((index, index + 1, [renamed]))
        changed.append(f"renamed class {node.name} to {renamed.split('(')[0][6:]}")
        by_base[new] = node
    for first, last, replacement in sorted(edits, reverse=True):
        lines[first:last] = replacement
    text = "\n".join(lines).rstrip("\n") + "\n"
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    missing = [(name, base, body) for name, base, body in wanted if base not in by_base]
    clash = [name for name, _base, _body in missing if name in classes]
    if clash:
        raise CliError(
            f"{rel} already has a class {clash[0]} that does not extend karni.{clash[0]}, so "
            f"karni build cannot add its own. Rename yours, or make it extend karni.{clash[0]} "
            f"(from {module} import ... as karni).",
            code="C275",
        )
    if missing or created:
        imports = [Import(module.rsplit(".", 1)[0], module.rsplit(".", 1)[1], "karni")]
        if missing and extra_imports:
            imports += extra_imports
        text = ensure_imports(ws, rel, text, imports)
    for name, base, body in missing:
        block = "\n".join([f"class {name}(karni.{base}):", STUB_LINE, *body])
        text = text.rstrip("\n") + "\n\n\n" + block + "\n"
        changed.append(f"class {name}(karni.{base})")
    if changed or created:
        ws.write(rel, text)
    return changed if not created else [f"created ({', '.join(changed) or 'empty'})"]


# settings and routes blocks --------------------------------------------------------


def settings_block(spec: schema.Spec, line: int) -> str:
    """Experimental. The ``# karni:spec`` block: roles, features and module options."""
    rows: list[str] = [
        "# Roles, features and module options from karni.yaml. Change them there and run",
        "# karni build: it rewrites the lines between the markers.",
    ]
    features = spec.features
    if features.social_login:
        rows.append("from karni.conf import env")
        rows.append("")
    if spec.roles:
        roles: dict[str, Any] = {}
        for slug, role in spec.roles.items():
            entry: dict[str, Any] = {"name": role.name or _role_name(slug)}
            if role.description:
                entry["description"] = role.description
            if role.system:
                entry["system"] = True
            # own:<field> says which owner field: KARNI_ROLES takes own, the field is Karni.owner_field
            entry["grants"] = {
                (p if p == "*" or ":" in p else f"{p}:*"): "own" if s.startswith("own:") else s
                for p, s in role.grants.items()
            }
            roles[slug] = entry
        rows.append(_literal(roles, "", line, "KARNI_ROLES = "))
        defaults = [slug for slug, role in spec.roles.items() if role.default]
        rows.append(_literal(defaults, "", line, "KARNI_ACCOUNTS_DEFAULT_ROLES = "))
    rows.append(f"KARNI_2FA = {features.two_factor!r}")
    rows.append(f"KARNI_EMAIL_OTP = {features.email_code_login!r}")
    providers = [
        f'    {pystr(name)}: {{"client_ids": env.list({pystr(_client_ids(name))})}},'
        for name in features.social_login
    ]
    rows += (
        ["KARNI_SOCIAL_TOKEN_PROVIDERS = {", *providers, "}"]
        if providers
        else ["KARNI_SOCIAL_TOKEN_PROVIDERS = {}"]
    )
    terms = features.terms.model_dump(exclude_none=True) if features.terms else None
    if terms is not None and terms.get("required") is True:
        terms.pop("required")
    rows.append(_literal(terms, "", line, "KARNI_TERMS = "))
    for module, options in spec.modules.items():
        for option, value in (options or {}).items():
            rows.append(_literal(value, "", line, f"{catalog.module_setting(module, option)} = "))
    return "\n".join(rows)


def _client_ids(provider: str) -> str:
    """The environment variable a social provider's client ids come from."""
    return f"KARNI_SOCIAL_{provider.upper()}_CLIENT_IDS"


def _role_name(slug: str) -> str:
    from karni_cli.spec.normal import role_name

    return role_name(slug)


def splice(
    text: str, start: str, end: str, block: str, *, before: str, prefix: str, gap: bool = False
) -> str:
    """Experimental. ``text`` with ``block`` between ``start`` and ``end`` (inserted before ``before``).

    ``gap`` leaves a blank line between a newly inserted block and ``before``.
    """
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == f"{prefix} {start}"]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == f"{prefix} {end}"]
    if starts and ends and ends[0] > starts[0]:
        indent = lines[starts[0]][: len(lines[starts[0]]) - len(lines[starts[0]].lstrip())]
        body = [indent + row if row else row for row in block.splitlines()]
        lines[starts[0] + 1 : ends[0]] = body
        return "\n".join(lines) + "\n"
    index = next((i for i, ln in enumerate(lines) if before in ln), None)
    if index is None:
        raise ValueError(before)
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    body = [indent + row if row else row for row in block.splitlines()]
    lines[index:index] = [
        f"{indent}{prefix} {start}",
        *body,
        f"{indent}{prefix} {end}",
        *([""] if gap else []),
    ]
    return "\n".join(lines) + "\n"


def block_of(text: str, start: str, end: str, prefix: str) -> str | None:
    """Experimental. The lines between the markers (``None``: no such block), unindented."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == f"{prefix} {start}"]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == f"{prefix} {end}"]
    if not starts or not ends or ends[0] < starts[0]:
        return None
    indent = len(lines[starts[0]]) - len(lines[starts[0]].lstrip())
    return "\n".join(row[indent:] for row in lines[starts[0] + 1 : ends[0]])


def read_block(text: str | None, name: str) -> str | None:
    """Experimental. The content of the block ``name`` (a record name) in ``text``."""
    if text is None:
        return None
    if name == layout.SETTINGS_BLOCK:
        return block_of(text, BLOCK_START, BLOCK_END, "#")
    marker = _ROUTE_BLOCKS[name][0]
    return block_of(text, f"{marker} start", f"{marker} end", "//")


def _settings_call(ws: Workspace, text: str) -> str:
    """The ``karni_settings(globals())`` line, before which the block goes."""
    for node in parse(ws, SETTINGS, text).body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "karni_settings"
        ):
            return text.splitlines()[node.lineno - 1]
    raise CliError(
        f"{SETTINGS} has no karni_settings(globals()) call, so karni build has no place for its "
        "# karni:spec block (it goes right above the call, where every setting takes effect). "
        "Restore the call, or pass --adopt config/settings.py and keep the settings yourself.",
        code="C284",
    )


# pages ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Page:
    key: str  # app.Entity:kind or name:kind
    spec: page_gen.PageSpec


def _pages(inputs: Inputs) -> list[_Page]:
    """The pages Karni writes, in the spec's navigation order."""
    entities = _entities(inputs.spec)
    by_name = {name: label for label, (_a, name, _e) in entities.items()}
    apps = inputs.spec.model_dump(mode="json")["apps"]
    found: list[_Page] = []
    for item in inputs.spec.pages:
        ((name, written),) = item.items()
        kinds = schema.page_kind_names(written)
        if name[:1].isupper():
            label = name if "." in name else by_name.get(name, name)
            _app, entity_name, entity = entities[label]
            route = default_route(entity_name)
            names = layout.page_names(entity_name)
            expand = [
                s.name
                for s in _specs(entity)
                if s.is_relation and not is_user_target(relation_name(s))
            ]
            for kind in ("form", "detail", "list"):  # karni make model -a's order
                key = f"{label}:{kind}"
                if kind in kinds and key in inputs.pages:
                    spec = page_gen.spec_for(
                        names[kind],
                        resource=route,
                        kind=kind,
                        path=None,
                        expand=expand if kind == "detail" else None,
                        related=(
                            [related_tab(ref, label, apps) for ref in schema.page_related(written)]
                            if kind == "detail"
                            else None
                        ),
                    )
                    found.append(_Page(key, spec))
            continue
        kind = kinds[0]
        key = f"{name}:{kind}"
        if kind == "dashboard" and name != "home" and key in inputs.pages:
            counted = [default_route(entity_name) for _a, entity_name, _e in entities.values()]
            spec = page_gen.spec_for(name, resource=None, kind=kind, path=None, counts=counted)
            found.append(_Page(key, spec))
            continue
        if key not in inputs.pages or kind not in ("blank", "login"):
            continue
        found.append(
            _Page(
                key,
                page_gen.spec_for(
                    name, resource=None, kind=kind if kind == "login" else None, path=None
                ),
            )
        )
    return found


def _ordered(pages: list[_Page], spec: schema.Spec) -> list[_Page]:
    """``pages`` in navigation order: the spec's entries, and list, detail, form within one."""
    rank = {"list": 0, "detail": 1, "form": 2, "blank": 0, "login": 0, "dashboard": 0}
    order: dict[str, int] = {}
    for index, item in enumerate(spec.pages):
        ((name, _kinds),) = item.items()
        order[name] = index
    labels = {label: name for label, (_a, name, _e) in _entities(spec).items()}

    def key(page: _Page) -> tuple[int, int]:
        ident, kind = page.key.rsplit(":", 1)
        name = labels.get(ident, ident)
        return order.get(name, order.get(ident, 0)), rank[kind]

    return sorted(pages, key=key)


def page_text(spec: page_gen.PageSpec, routes: set[str]) -> str:
    """Experimental. A page Karni writes: karni make page's, with the header line."""
    return f"// {HEADER}\n{page_gen.render(spec, routes)}"


# the whole render ------------------------------------------------------------------


def render(ws: Workspace, inputs: Inputs) -> Output:
    """Experimental. Plan every Karni-owned file, block and project file into ``ws``."""
    out = Output(ws)
    spec = inputs.spec
    entities = _entities(spec)
    managed = [label for label in entities if label in inputs.entities]
    apps: dict[str, list[str]] = {}
    for label in managed:
        app, name, _entity = entities[label]
        apps.setdefault(app, []).append(name)
    existing = {app.label for app in local_apps(ws)}
    for app in apps:
        if app not in existing and not ws.is_dir(app):
            plan_app(ws, app, next_step=False)
            # the app is new: its models.py and viewsets.py say how build splits the code
            for rel, purpose in _purposes(app).items():
                if rel != f"{app}/seeds.py":
                    ws.write(rel, docstring(purpose, "", ws.line_length) + "\n")
            out.project.setdefault(app, []).append("created the app")
    renames_by_app: dict[str, dict[str, str]] = {}
    for new, old in inputs.renames.items():
        renames_by_app.setdefault(new.split(".", 1)[0], {})[new.split(".", 1)[1]] = old.split(
            ".", 1
        )[1]
    removed_by_app: dict[str, set[str]] = {}
    for label in inputs.removed:
        removed_by_app.setdefault(label.split(".", 1)[0], set()).add(label.split(".", 1)[1])
    for app in sorted(set(apps) | set(removed_by_app)):
        names = apps.get(app, [])
        _render_app(
            ws, out, inputs, app, names, renames_by_app.get(app, {}), removed_by_app.get(app, set())
        )
    _render_settings(ws, out, inputs)
    _render_pages(ws, out, inputs)
    return out


def _owned(out: Output, inputs: Inputs, rel: str, text: str) -> None:
    if rel in inputs.adopted:
        return
    out.files[rel] = text
    out.ws.write(rel, text)


def _render_app(
    ws: Workspace,
    out: Output,
    inputs: Inputs,
    app: str,
    names: list[str],
    renames: dict[str, str],
    removed: set[str],
) -> None:
    spec = inputs.spec
    if names:
        _owned(
            out, inputs, f"{app}/karni/__init__.py", docstring(HEADER, "", ws.line_length) + "\n"
        )
        models_text, notes = _models_file(ws, inputs, app, names)
        _owned(out, inputs, layout.models_file(app), models_text)
        for note in notes:
            ws.note(note)
        _owned(out, inputs, layout.api_file(app), _api_file(ws, inputs, app, names))
    counts = {}
    for name in names:
        label = f"{app}.{name}"
        for ref in (name, label):
            if ref in spec.seed:
                counts[name] = spec.seed[ref]
    if counts:
        _owned(out, inputs, layout.seeds_file(app), _seeds_file(ws, inputs, app, counts))
    models_wanted: list[tuple[str, str, list[str]]] = [(name, name, []) for name in names]
    access_code = [n for n in names if spec.apps[app].entities[n].access == "code"]
    viewsets_wanted: list[tuple[str, str, list[str]]] = [
        (
            f"{name}ViewSet",
            f"{name}ViewSet",
            _ACCESS_STUB if name in access_code else [],
        )
        for name in names
    ]
    purposes = _purposes(app)
    seeds_wanted: list[tuple[str, str, list[str]]] = [
        (f"{n}Seeder", f"{n}Seeder", []) for n in counts
    ]
    files: list[tuple[str, list[tuple[str, str, list[str]]], str, list[Import], str]] = [
        (f"{app}/models.py", models_wanted, f"{app}.karni.models", [], ""),
        (
            f"{app}/viewsets.py",
            viewsets_wanted,
            f"{app}.karni.api",
            [Import("karni.api", "Granted")] if access_code else [],
            "ViewSet",
        ),
        (f"{app}/seeds.py", seeds_wanted, f"{app}.karni.seeds", [], "Seeder"),
    ]
    for rel, wanted, module, extra, base in files:
        purpose = purposes[rel]
        if not wanted and not (removed and ws.exists(rel)):
            continue
        changed = _project_file(
            ws,
            rel,
            wanted,
            module=module,
            purpose=purpose,
            renames={f"{n}{base}": f"{o}{base}" for n, o in renames.items()},
            removed={f"{n}{base}" for n in removed},
            extra_imports=extra,
        )
        if changed:
            out.project.setdefault(rel, []).extend(changed)
    if names:
        tests = [n for n in names if _tested(spec.apps[app].entities[n])]
        if tests:
            _owned(out, inputs, f"{app}/tests/karni/__init__.py", "")
            if not ws.exists(f"{app}/tests/__init__.py"):
                ws.write(f"{app}/tests/__init__.py", "")
        for name in tests:
            api_text = ws.read(layout.api_file(app)) or _api_file(ws, inputs, app, names)
            text = _test_file(ws, inputs, app, name, api_text)
            _owned(out, inputs, layout.test_file(app, name), text)


def _purposes(app: str) -> dict[str, str]:
    """The docstring of each project file build creates."""
    return {
        f"{app}/models.py": (
            f"{app} models. Each class extends the one karni build writes in "
            f"{app}/karni/models.py from karni.yaml: add your methods here."
        ),
        f"{app}/viewsets.py": (
            f"{app} API. Each viewset extends the one karni build writes in "
            f"{app}/karni/api.py from karni.yaml: add your actions here."
        ),
        f"{app}/seeds.py": (
            f"{app} demo data for karni seed. Each seeder extends the one karni build writes in "
            f"{app}/karni/seeds.py: steer a field's values here."
        ),
    }


def _tested(entity: schema.Entity) -> bool:
    return not entity.external and entity.database in (None, "default")


def _render_settings(ws: Workspace, out: Output, inputs: Inputs) -> None:
    if layout.SETTINGS_BLOCK in inputs.adopted:
        return
    text = ws.read(SETTINGS)
    if text is None:
        raise CliError(
            f"{SETTINGS} not found. Run karni build inside a Karni project.", code="C001"
        )
    block = settings_block(inputs.spec, ws.line_length)
    out.blocks[layout.SETTINGS_BLOCK] = block
    call_line = _settings_call(ws, text) if read_block(text, layout.SETTINGS_BLOCK) is None else ""
    updated = splice(
        text, BLOCK_START, BLOCK_END, block, before=call_line or "\0", prefix="#", gap=True
    )
    ws.write(SETTINGS, updated)


def _render_pages(ws: Workspace, out: Output, inputs: Inputs) -> None:
    pages = _ordered(_pages(inputs), inputs.spec)
    text = ws.read(page_gen.ROUTES)
    if text is None:
        if pages:
            raise CliError(
                "No frontend/src/routes.tsx, so karni build cannot add its pages. Remove pages "
                "from karni.yaml, or restore the scaffold's frontend.",
                code="C284",
            )
        return
    adopted = [name for name in layout.ROUTES_BLOCKS if name in inputs.adopted]
    if adopted:
        return
    own_routes: set[str] = set()
    karni_paths = {path for page in pages for path in page.spec.paths}
    for path in page_gen.known_routes(ws):
        own_routes.add(path)
    for name in layout.ROUTES_BLOCKS:
        found = read_block(text, name) or ""
        own_routes -= set(page_gen.ROUTE_PATH.findall(found))
    taken = sorted(own_routes & karni_paths)
    if taken:
        raise CliError(
            f"frontend/src/routes.tsx already routes {taken[0]} to a page of the project's own, "
            "and karni.yaml asks karni build for a page there. Remove that route, or write the "
            "page's kind as code in karni.yaml (- <name>: code).",
            code="C275",
        )
    routes = own_routes | karni_paths
    imports: list[str] = []
    entries: list[str] = []
    for page in pages:
        _owned(out, inputs, layout.page_file(page.spec.name), page_text(page.spec, routes))
        imports.append(f'import {page.spec.component} from "./pages/karni/{page.spec.name}";')
        entries += [page_gen.route_line(page.spec, path).strip() for path in page.spec.paths]
    blocks = {
        layout.ROUTES_BLOCKS[0]: "\n".join(imports),
        layout.ROUTES_BLOCKS[1]: "\n".join(entries),
    }
    if not pages and all(read_block(text, name) is None for name in layout.ROUTES_BLOCKS):
        return  # no page of Karni's, and no block yet: leave routes.tsx alone
    for name, (marker, before) in _ROUTE_BLOCKS.items():
        if before not in text and read_block(text, name) is None:
            raise CliError(
                f"frontend/src/routes.tsx has no `{before}` marker, so karni build has no place "
                "for its routes. Restore the marker (see the scaffold's routes.tsx).",
                code="C284",
            )
        out.blocks[name] = blocks[name]
        text = splice(
            text, f"{marker} start", f"{marker} end", blocks[name], before=before, prefix="//"
        )
    ws.write(page_gen.ROUTES, text)
