"""Experimental. ``karni spec validate``: every problem in a ``karni.yaml``, with its code and line.

Three passes, each reporting every problem it finds:

1. **YAML.** The text parses (``C211``), no key is written twice in one
   mapping (``C222``), the version is one this release reads (``C214``), and
   no key is one reserved for a later release (``C224``). Keys that start
   with ``x-`` are removed here, at every level: they are kept in the file and
   ignored.
2. **Shape.** The :mod:`karni_cli.spec.schema` models: unknown keys
   (``C212``), wrong types and missing required keys (``C213``).
3. **Meaning**, once the shape is right: names (``C215``), each field through
   ``karni make model``'s own parser and renderer (``C216``), access rules,
   grants, features, pages, modules and seed counts, and every reference
   between them (``C230`` to ``C242``), then the keys of external tables and
   other databases (``C251`` to ``C253``) and the renames written with
   ``was`` (``C254``). Whether a ``database`` is one of the project's
   aliases is checked when the caller knows them (``karni plan`` does).

An issue carries the code, the 1-based line (the YAML parser's), the dotted
path of the key, the message and the fix. ``karni explain <code>`` prints
the code's entry.

Override / escape hatch: :func:`validate_text` takes text, so a tool that
writes a spec validates it before saving, and ``databases`` to check the
aliases against a project's.
"""

from __future__ import annotations

import fnmatch
import keyword
import re
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import ValidationError

from karni_cli.generators.fields import (
    FieldSpec,
    RelationTarget,
    Rendered,
    is_user_target,
    parse_field,
    relation_name,
    render_field,
)
from karni_cli.generators.naming import default_route
from karni_cli.generators.pysource import pystr
from karni_cli.project import CliError
from karni_cli.spec import schema
from karni_cli.spec.catalog import (
    FEATURES,
    MODULES,
    OTHER_MODELS,
    SOCIAL_PROVIDERS,
    KnownFeature,
    KnownModule,
)
from karni_cli.spec.source import Loc, Source, YamlError, load

__all__ = ["SHIPPED_ROLES", "Issue", "Report", "iter_codes", "validate_text"]

#: Experimental. Karni's own KARNI_ROLES (karni.conf.base), the roles a spec without ``roles:`` has.
SHIPPED_ROLES: Final = ("staff", "user", "customer")
#: Roles a module declares through the ``karni.roles`` entry point.
MODULE_ROLES: Final = {"site": ("editor",)}
#: Keys a later release adds, by where they go: what each is for.
RESERVED: Final[dict[str, dict[str, str]]] = {
    "spec": {"search": "a search block for search across entities"},
    "entity": {
        "tree": "trees (large-apps roadmap)",
        "taxonomies": "taxonomies (large-apps roadmap)",
        "aggregate": "aggregation endpoints (large-apps item 8)",
    },
}
#: Field types a later release adds.
RESERVED_TYPES: Final = {"markdown": "markdown fields (large-apps item 12)"}
ACCESS_WORDS: Final = ("public", "authenticated", "granted")
STANDARD_ACTIONS: Final = ("view", "add", "change", "delete")
ENTITY_PAGES: Final = ("list", "detail", "form")
NAMED_PAGES: Final = ("dashboard", "blank", "login")
#: Fields every BaseModel has, which key, order and search may name.
BASE_FIELDS: Final = ("id", "created_at", "updated_at")
_USER_TARGET: Final = "__user__"
#: App labels a spec app may not take: Django's and Karni's own.
TAKEN_LABELS: Final = frozenset(
    {"admin", "auth", "contenttypes", "sessions", "messages", "staticfiles", "sites", "karni"}
    | {f"karni_{name}" for name in ("accounts", "admin", "audit", "transfer", *MODULES)}
)
_PATH: Final = re.compile(r"^[a-z_][a-z0-9_]*(__[a-z_][a-z0-9_]*)*$")
#: ``table`` or ``schema.table``, as ``karni make model --table`` takes it.
_TABLE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*)?$")
_ALIAS: Final = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
#: The database of the user, the modules' models and Django's: the project's default.
DEFAULT_DATABASE: Final = "default"


@dataclass(frozen=True)
class Issue:
    """Experimental. One problem in a spec: code, line, where, what is wrong and the fix."""

    code: str
    line: int | None
    path: str
    message: str
    fix: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "line": self.line,
            "path": self.path,
            "message": self.message,
            "fix": self.fix,
        }

    def render(self, file: str) -> str:
        where = f"{file}:{self.line}" if self.line else file
        return f"{where}: {self.code}: {self.message} Fix: {self.fix}"


@dataclass
class Report:
    """Experimental. The outcome: the spec when its shape is valid, and every issue."""

    spec: schema.Spec | None
    issues: list[Issue] = field(default_factory=list)
    source: Source | None = None

    @property
    def ok(self) -> bool:
        return not self.issues


def _dotted(path: Loc) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


class _Checker:
    def __init__(self, source: Source) -> None:
        self.source = source
        self.issues: list[Issue] = []

    def add(self, code: str, path: Loc, message: str, fix: str, *, key: bool = False) -> None:
        line = self.source.line(path) if key else self.source.value_line(path)
        self.issues.append(Issue(code, line, _dotted(path), message, fix))


def _strip_extensions(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_extensions(item)
            for key, item in value.items()
            if not str(key).startswith("x-")
        }
    if isinstance(value, list):
        return [_strip_extensions(item) for item in value]
    return value


# pass 1 ------------------------------------------------------------------------


def _first_pass(check: _Checker, data: Any) -> Any:
    for path, line, first in check.source.duplicates:
        check.issues.append(
            Issue(
                "C222",
                line,
                _dotted(path),
                f"{path[-1]!r} is written twice in this mapping (first on line {first}). YAML "
                "keeps the last one and drops the first without a word.",
                "Keep one of them and merge what the other said into it.",
            )
        )
    if not isinstance(data, dict):
        check.add(
            "C213",
            (),
            f"The spec must be a mapping with version, app and the other keys, got {_kind(data)}.",
            "Start the file with `version: 1` and `app: {name: ...}` (karni spec export "
            "writes one for an existing project).",
        )
        return None
    data = _strip_extensions(data)
    if "version" in data and (
        data["version"] != schema.VERSION or isinstance(data["version"], bool)
    ):
        check.add(
            "C214",
            ("version",),
            f"version {data['version']!r} is not a spec version this karni reads (it reads "
            f"{schema.VERSION}).",
            f"Write `version: {schema.VERSION}`, or upgrade karni-cli if the spec comes from a "
            "newer release.",
        )
        return None
    for key in [key for key in data if key in RESERVED["spec"]]:
        _reserved(check, (key,), RESERVED["spec"][key])
        data.pop(key)
    for label, app in (
        (data.get("apps") or {}).items() if isinstance(data.get("apps"), dict) else ()
    ):
        entities = app.get("entities") if isinstance(app, dict) else None
        if not isinstance(entities, dict):
            continue
        for name, entity in entities.items():
            if not isinstance(entity, dict):
                continue
            for key in [key for key in entity if key in RESERVED["entity"]]:
                _reserved(check, ("apps", label, "entities", name, key), RESERVED["entity"][key])
                entity.pop(key)
    return data


def _reserved(check: _Checker, path: Loc, what: str) -> None:
    check.add(
        "C224",
        path,
        f"{path[-1]!r} is reserved for {what}, which this release does not have yet.",
        "Remove the key. Until the feature ships, write that part by hand in the project.",
        key=True,
    )


def _kind(value: Any) -> str:
    names = {
        dict: "a mapping",
        list: "a list",
        str: "a string",
        bool: "true or false",
        int: "a number",
        float: "a number",
        type(None): "nothing (null)",
    }
    return names.get(type(value), type(value).__name__)


# pass 2 ------------------------------------------------------------------------

#: Pydantic error type -> what the value should have been.
_EXPECTED: Final = {
    "string_type": "a string",
    "list_type": "a list",
    "tuple_type": "a list",
    "dict_type": "a mapping",
    "model_type": "a mapping",
    "model_attributes_type": "a mapping",
    "bool_type": "true or false",
    "int_type": "a whole number",
    "literal_error": "one of the listed values",
}


def _known_keys(path: Loc) -> list[str]:
    """The keys the mapping at ``path`` takes (``path`` ends at the unknown key)."""
    shapes: list[tuple[tuple[str | None, ...], type[schema.BaseModel]]] = [
        ((), schema.Spec),
        (("app",), schema.AppInfo),
        (("features",), schema.Features),
        (("features", "terms"), schema.Terms),
        (("roles", None), schema.Role),
        (("apps", None), schema.App),
        (("apps", None, "entities", None), schema.Entity),
        (("apps", None, "entities", None, "fields", None), schema.FieldEntry),
        (("apps", None, "entities", None, "access"), schema.Access),
    ]
    parent = path[:-1]
    for pattern, model in shapes:
        if len(pattern) == len(parent) and all(
            want is None or want == got for want, got in zip(pattern, parent, strict=True)
        ):
            return list(model.model_fields)
    return []


def _shape_issues(check: _Checker, error: ValidationError, data: dict[str, Any]) -> None:
    for item in error.errors():
        path: Loc = tuple(
            part for part in item["loc"] if not (isinstance(part, str) and part.startswith("="))
        )
        kind = item["type"]
        where = _dotted(path) or "the spec"
        if kind == "extra_forbidden":
            known = ", ".join(_known_keys(path))
            check.add(
                "C212",
                path,
                f"Unknown key {path[-1]!r} in {_dotted(path[:-1]) or 'the spec'}"
                + (f" (keys: {known})." if known else "."),
                "Fix the spelling or remove it. A key that starts with x- is kept and ignored, "
                "for notes of your own.",
                key=True,
            )
        elif kind == "missing":
            check.add(
                "C213",
                path[:-1],
                f"{_dotted(path[:-1]) or 'The spec'} needs the key {path[-1]!r}.",
                f"Add {path[-1]}: (docs/app-spec.md lists what it takes).",
            )
        else:
            expected = _EXPECTED.get(kind)
            if kind == "literal_error":
                expected = f"one of {item.get('ctx', {}).get('expected', '')}"
            got = _value_at(data, path)
            check.add(
                "C213",
                path,
                f"{where} must be {expected or item['msg'].lower()}, got {_kind(got)}"
                + (f" ({got!r})" if isinstance(got, str | int | float) else "")
                + ".",
                "Write the value in the form docs/app-spec.md shows for this key. Quote a "
                "value that YAML would read as a date, a number or true/false.",
            )


def _value_at(data: Any, path: Loc) -> Any:
    for part in path:
        try:
            data = data[part]
        except (KeyError, IndexError, TypeError):
            return None
    return data


# pass 3 ------------------------------------------------------------------------


@dataclass
class _Entity:
    app: str
    name: str
    path: Loc
    entity: schema.Entity
    fields: dict[str, FieldSpec]
    #: relation field -> target ("app.Name", _USER_TARGET, or a module/other model label).
    targets: dict[str, str]

    @property
    def label(self) -> str:
        return f"{self.app}.{self.name}"

    @property
    def owner(self) -> str:
        return self.entity.owner or "created_by"


class _Meaning:
    def __init__(
        self, check: _Checker, spec: schema.Spec, databases: Collection[str] | None = None
    ) -> None:
        self.check = check
        self.spec = spec
        self.databases = databases
        self.entities: dict[str, _Entity] = {}  # label -> entity
        self.modules = set(spec.modules)
        if spec.app.kind in ("site", "site+app"):
            self.modules.add("site")

    def add(self, code: str, path: Loc, message: str, fix: str, *, key: bool = False) -> None:
        self.check.add(code, path, message, fix, key=key)

    def run(self) -> None:
        self.names()
        self.collect()
        for entity in self.entities.values():
            self.relations(entity)
        for entity in self.entities.values():
            self.options(entity)
            self.access(entity)
            self.storage(entity)
            self.renames(entity)
        self.roles()
        self.features()
        self.modules_()
        self.requirements()
        self.pages()
        self.seed()

    # names and fields

    def names(self) -> None:
        for label in self.spec.apps:
            if not re.fullmatch(schema.APP_LABEL, label) or keyword.iskeyword(label):
                self.add(
                    "C215",
                    ("apps", label),
                    f"App label {label!r} must be snake_case: lowercase letters, digits and _.",
                    "Rename it, e.g. classes or shop.",
                    key=True,
                )
            elif label in TAKEN_LABELS:
                self.add(
                    "C215",
                    ("apps", label),
                    f"App label {label!r} is taken by Django, Karni or a module.",
                    "Choose a label of your own, e.g. the domain's noun in the plural.",
                    key=True,
                )
            for name in self.spec.apps[label].entities:
                if not re.fullmatch(schema.ENTITY_NAME, name):
                    self.add(
                        "C215",
                        ("apps", label, "entities", name),
                        f"Entity name {name!r} must be a class name in PascalCase.",
                        "Rename it, e.g. Booking or TicketTier.",
                        key=True,
                    )
        for slug in self.spec.roles:
            if not re.fullmatch(schema.ROLE_SLUG, slug):
                self.add(
                    "C215",
                    ("roles", slug),
                    f"Role slug {slug!r} may only use letters, digits, _, . and -.",
                    "Rename it, e.g. instructor or venue_manager.",
                    key=True,
                )

    def collect(self) -> None:
        for label, app in self.spec.apps.items():
            for name, entity in app.entities.items():
                path: Loc = ("apps", label, "entities", name)
                specs: dict[str, FieldSpec] = {}
                for field_name, token in entity.tokens().items():
                    where: Loc = (*path, "fields", field_name)
                    if not isinstance(entity.fields[field_name], str):
                        where = (*where, "type")
                    kind = token.split(":", 1)[0].rstrip("?").lower()
                    if kind in RESERVED_TYPES:
                        self.add(
                            "C224",
                            where,
                            f"The field type {kind!r} is reserved for {RESERVED_TYPES[kind]}, "
                            "which this release does not have yet.",
                            "Use text for now, e.g. body: text.",
                        )
                        continue
                    try:
                        specs[field_name] = parse_field(f"{field_name}:{token}")
                    except CliError as exc:
                        self.add("C216", where, _field_message(exc), _FIELD_FIX)
                self.entities[f"{label}.{name}"] = _Entity(label, name, path, entity, specs, {})

    def relations(self, entity: _Entity) -> None:
        specs = list(entity.fields.values())
        keys = []
        for spec in specs:
            if not spec.is_relation:
                continue
            where = (*entity.path, "fields", spec.name)
            try:
                raw = relation_name(spec)
            except CliError as exc:
                self.add("C216", where, _field_message(exc), _FIELD_FIX)
                continue
            target = self.resolve(entity, raw, where)
            if target is not None:
                entity.targets[spec.name] = target
                keys.append(target)
                self.same_database(entity, target, where)
        resolve = {
            spec.name: RelationTarget(pystr("x"), False, entity.targets.get(spec.name, spec.name))
            for spec in specs
            if spec.is_relation
        }
        for spec in specs:
            if spec.is_relation and spec.name not in entity.targets:
                continue
            try:
                render_field(
                    spec,
                    Rendered(),
                    specs=specs,
                    model=entity.name,
                    app_label=entity.app,
                    resolve=resolve,
                    line_length=100,
                    targets=keys,
                )
            except CliError as exc:
                self.add(
                    "C216", (*entity.path, "fields", spec.name), _field_message(exc), _FIELD_FIX
                )

    def resolve(self, entity: _Entity, raw: str, where: Loc) -> str | None:
        """The label a relation's target names, or ``None`` after reporting it."""
        if is_user_target(raw):
            return _USER_TARGET
        if raw in ("self", entity.name, entity.label):
            return entity.label
        if "." in raw:
            app, _, name = raw.partition(".")
            if app in self.spec.apps:
                if f"{app}.{name}" in self.entities:
                    return f"{app}.{name}"
                self.add(
                    "C230",
                    where,
                    f"{entity.name}.{where[-1]} points at {raw}, but app {app} has no entity "
                    f"{name}.",
                    f"Add {name} under apps.{app}.entities, or point at an entity that exists.",
                )
                return None
            module = app.removeprefix("karni_")
            known = MODULES.get(module)
            if known is not None and app == known.app and name in known.models:
                if module not in self.modules:
                    self.add(
                        "C230",
                        where,
                        f"{entity.name}.{where[-1]} points at {raw}, a model of the {module} "
                        "module, which the spec does not add.",
                        f"Add the module: modules: {{{module}: {{}}}}.",
                    )
                return raw
            if raw in OTHER_MODELS:
                return raw
            self.add(
                "C230",
                where,
                f"{entity.name}.{where[-1]} points at {raw}, which is neither an entity of the "
                "spec nor a model Karni or an added module provides.",
                "Point at an entity of the spec (Name or app.Name), User, or a module's model "
                "such as karni_payments.Payment.",
            )
            return None
        owners = [label for label, e in self.entities.items() if e.name == raw]
        if f"{entity.app}.{raw}" in owners:
            return f"{entity.app}.{raw}"
        if len(owners) == 1:
            return owners[0]
        if owners:
            self.add(
                "C231",
                where,
                f"{entity.name}.{where[-1]} points at {raw}, which apps "
                f"{', '.join(o.split('.')[0] for o in owners)} all define.",
                f"Name the app: {where[-1]}: {self.spec_token(entity, where[-1], owners[0])}.",
            )
            return None
        self.add(
            "C230",
            where,
            f"{entity.name}.{where[-1]} points at {raw}, but no app of the spec has an entity "
            f"named {raw}.",
            f"Add the entity {raw} (or fix the name). A Django model the project has outside the "
            "spec cannot be named here: User and the modules' models can.",
        )
        return None

    def database_of(self, label: str) -> str:
        """The alias the entity ``label`` lives on (the user and modules' models: default)."""
        found = self.entities.get(label)
        return (found.entity.database if found else None) or DEFAULT_DATABASE

    def same_database(self, entity: _Entity, target: str, where: Loc) -> None:
        here, there = self.database_of(entity.label), self.database_of(target)
        if here == there:
            return
        shown = "the user" if target == _USER_TARGET else target
        self.add(
            "C253",
            where,
            f"{entity.name}.{where[-1]} joins {entity.name} (database {here}) to {shown} "
            f"(database {there}). Django joins related tables in one database, so Karni refuses "
            "a relation across databases (karni.E276).",
            "Keep both entities on one database, or store the other row's key in a plain field "
            "(e.g. sku: str:20) and look it up in code.",
        )

    def spec_token(self, entity: _Entity, field_name: Any, label: str) -> str:
        spec = entity.fields[str(field_name)]
        return f"{spec.kind}:{label}{'?' if spec.optional else ''}"

    # entity options

    def field_names(self, entity: _Entity) -> set[str]:
        return set(entity.entity.fields)

    def options(self, entity: _Entity) -> None:
        names = self.field_names(entity)
        known = names | set(BASE_FIELDS)
        e = entity.entity

        def missing(key: str, value: str, extra: str = "") -> None:
            fields = ", ".join(sorted(names)) or "none"
            self.add(
                "C238",
                (*entity.path, key),
                f"{entity.name}.{key} names {value!r}, which is not a field of {entity.name} "
                f"(fields: {fields}{extra}).",
                f"Name one of its fields, or add the field under {entity.name}.fields.",
            )

        if e.key is not None and e.key not in known:
            missing("key", e.key, ", plus id, created_at, updated_at")
        for name in e.search:
            first = name.lstrip("^=@$").split("__", 1)[0]
            if first not in known:
                missing("search", name)
            elif "__" in name and first in entity.fields and not entity.fields[first].is_relation:
                missing("search", name, f", and {first} is not a relation for __ to follow")
        for name in e.order:
            if name.lstrip("-") not in known:
                missing("order", name, ", plus id, created_at, updated_at")
        if isinstance(e.audit, list):
            for name in e.audit:
                if name not in names:
                    missing("audit", name)
        for key, path in e.scope_paths.items():
            if not key.isidentifier():
                self.add(
                    "C215",
                    (*entity.path, "scope_paths", key),
                    f"Scope path key {key!r} must be an identifier: it is also the user's "
                    "attribute the related scope compares with.",
                    "Rename it, e.g. branch.",
                    key=True,
                )
            if path.split("__", 1)[0] not in names:
                missing("scope_paths", path)
        seen: dict[str, str] = {}
        for title, members in e.groups.items():
            if not title.strip():
                self.add(
                    "C215",
                    (*entity.path, "groups", title),
                    "A field group needs a title.",
                    "Give the group a title, e.g. Details.",
                    key=True,
                )
            for name in members:
                if name not in names:
                    self.add(
                        "C237",
                        (*entity.path, "groups", title),
                        f"Group {title!r} of {entity.name} names {name!r}, which is not a field "
                        f"of {entity.name}.",
                        "Name a field the entity declares, or add it under fields.",
                    )
                elif name in seen:
                    self.add(
                        "C237",
                        (*entity.path, "groups", title),
                        f"{entity.name}.{name} is in group {seen[name]!r} and in group {title!r}.",
                        "Keep each field in one group.",
                    )
                else:
                    seen[name] = title
        if e.owner is not None and not self.leads_to_user(entity, e.owner):
            self.add(
                "C239",
                (*entity.path, "owner"),
                f"{entity.name}.owner is {e.owner!r}, which does not lead to the user: the own "
                "scope compares it with the signed-in user.",
                "Name a relation to the user (e.g. member: fk:User, then owner: member) or a "
                "path through relations, e.g. workspace__members.",
            )

    def leads_to_user(self, entity: _Entity, path: str) -> bool:
        """Whether ``path`` (``a__b``) follows relations from ``entity`` to the user."""
        if not _PATH.match(path):
            return False
        current: _Entity | None = entity
        parts = path.split("__")
        for index, part in enumerate(parts):
            if current is None:
                return True  # it left the spec (a module's model): Karni checks the rest
            if part in ("created_by", "updated_by"):
                return index == len(parts) - 1
            spec = current.fields.get(part)
            if spec is None or not spec.is_relation:
                return False
            target = current.targets.get(part)
            if target == _USER_TARGET:
                return index == len(parts) - 1
            current = self.entities.get(target or "")
        return False

    def access(self, entity: _Entity) -> None:
        rule = entity.entity.access
        if rule == "code" or not isinstance(rule, schema.Access):
            return
        slots = {"read": rule.read, "write": rule.write, "create": rule.create}
        for slot, items in slots.items():
            if items is None:
                continue
            where = (*entity.path, "access", slot)
            if not items:
                self.add(
                    "C217",
                    where,
                    f"{entity.name}.access.{slot} is an empty list, which would admit nobody.",
                    "Name who may: public, authenticated, granted, role:<slug> or owned:<field>.",
                )
            for item in items:
                word, colon, arg = item.partition(":")
                if not colon and word in ACCESS_WORDS:
                    continue
                if word == "role" and arg:
                    if arg not in self.declared_roles():
                        self.add(
                            "C232",
                            where,
                            f"{entity.name}.access.{slot} names role {arg!r}, which the spec does "
                            f"not declare (roles: {', '.join(sorted(self.declared_roles()))}).",
                            f"Declare it under roles ({arg}: {{name: ...}}) or fix the slug.",
                        )
                    continue
                if word == "owned" and arg:
                    if not self.leads_to_user(entity, arg):
                        self.add(
                            "C240",
                            where,
                            f"{entity.name}.access.{slot} has owned:{arg}, but {arg!r} does not "
                            f"lead from {entity.name} to the user.",
                            "Name a relation to the user, e.g. owned:member, or a path such as "
                            "owned:session__instructor.",
                        )
                    continue
                self.add(
                    "C217",
                    where,
                    f"{entity.name}.access.{slot} has {item!r}, which is not an access rule.",
                    "Use public, authenticated, granted, role:<slug> or owned:<field>, or a list "
                    "of them. For anything else write access: code and declare Access(...) in "
                    "the viewset.",
                )

    def storage(self, entity: _Entity) -> None:
        """pk, external, table, writable and database (``C251``, ``C252``)."""
        e, path = entity.entity, entity.path
        if e.external:
            if e.table is None:
                self.add(
                    "C251",
                    (*path, "external"),
                    f"{entity.name} is external but names no table: Karni reads a table it does "
                    "not own, so it must know which one.",
                    "Add table: <table> or table: <schema>.<table>, e.g. table: reporting.sales.",
                    key=True,
                )
            if e.pk is not None:
                self.add(
                    "C251",
                    (*path, "pk"),
                    f"{entity.name} is external, so its key is the table's own primary key "
                    "column, and pk does not apply.",
                    "Remove pk. karni make model --external reads the key from the table.",
                    key=True,
                )
        else:
            for key in ("table", "writable"):
                if getattr(e, key) not in (None, False):
                    self.add(
                        "C251",
                        (*path, key),
                        f"{entity.name}.{key} applies to an external entity only.",
                        "Add external: true, or remove the key.",
                        key=True,
                    )
        if e.table is not None and not _TABLE.match(e.table):
            self.add(
                "C251",
                (*path, "table"),
                f"{entity.name}.table {e.table!r} is not a table name: write table or "
                "schema.table.",
                "Write e.g. table: sales or table: reporting.sales.",
            )
        if e.database is None:
            return
        if not _ALIAS.match(e.database):
            self.add(
                "C252",
                (*path, "database"),
                f"{entity.name}.database {e.database!r} is not a database alias.",
                "Name an alias of DATABASES, e.g. database: warehouse.",
            )
        elif self.databases is not None and e.database not in self.databases:
            self.add(
                "C252",
                (*path, "database"),
                f"{entity.name}.database is {e.database!r}, which the project's DATABASES does "
                f"not have (aliases: {', '.join(sorted(self.databases))}).",
                f'Add it in config/settings.py (DATABASES["{e.database}"] = '
                'env.db_url("..._DATABASE_URL")), or name an alias it has.',
            )

    def renames(self, entity: _Entity) -> None:
        """``was`` on the entity and its fields (``C254``)."""
        e, path = entity.entity, entity.path
        if e.was is not None:
            siblings = self.spec.apps[entity.app].entities
            others = [
                name
                for name, other in siblings.items()
                if name != entity.name and other.was == e.was
            ]
            if not re.fullmatch(schema.ENTITY_NAME, e.was) or e.was == entity.name:
                problem = "is its own name" if e.was == entity.name else "is not an entity name"
                self.add(
                    "C254",
                    (*path, "was"),
                    f"{entity.name}.was {problem} ({e.was!r}): was names the entity's old name.",
                    "Write the old PascalCase name, e.g. was: Lesson, or remove was.",
                )
            elif e.was in siblings:
                self.add(
                    "C254",
                    (*path, "was"),
                    f"{entity.name}.was is {e.was}, which the app {entity.app} still declares: "
                    "a rename leaves only the new name.",
                    f"Remove the entity {e.was}, or remove was.",
                )
            elif others:
                self.add(
                    "C254",
                    (*path, "was"),
                    f"{entity.name} and {others[0]} both say was: {e.was}. One table can become "
                    "one entity only.",
                    "Keep was on the entity that takes over the rows.",
                )
        seen: dict[str, str] = {}
        for name, old in e.renamed().items():
            where = (*path, "fields", name, "was")
            if not re.fullmatch(schema.FIELD_NAME, old) or old == name:
                problem = "is its own name" if old == name else "is not a field name"
                self.add(
                    "C254",
                    where,
                    f"{entity.name}.{name}.was {problem} ({old!r}): was names the field's old "
                    "name.",
                    "Write the old snake_case name, e.g. was: title, or remove was.",
                )
            elif old in e.fields:
                self.add(
                    "C254",
                    where,
                    f"{entity.name}.{name}.was is {old}, which {entity.name} still declares: a "
                    "rename leaves only the new name.",
                    f"Remove the field {old}, or remove was.",
                )
            elif old in seen:
                self.add(
                    "C254",
                    where,
                    f"{entity.name}.{name} and {entity.name}.{seen[old]} both say was: {old}. "
                    "One column can become one field only.",
                    "Keep was on the field that takes over the column.",
                )
            else:
                seen[old] = name

    def declared_roles(self) -> set[str]:
        roles = set(self.spec.roles) or set(SHIPPED_ROLES)
        for module in self.modules:
            roles |= set(MODULE_ROLES.get(module, ()))
        return roles

    # roles

    def roles(self) -> None:
        for slug, role in self.spec.roles.items():
            for pattern, scope in role.grants.items():
                self.grant(("roles", slug, "grants", pattern), slug, pattern, scope)

    def grant(self, where: Loc, slug: str, pattern: str, scope: str) -> None:
        if pattern == "*":
            matched: list[_Entity | None] = [None]
            explicit: _Entity | None = None
        else:
            target, _, action = pattern.partition(":")
            app, dot, model = target.partition(".")
            if not dot or not app or not model or (action == "" and ":" in pattern):
                self.add(
                    "C218",
                    where,
                    f"Role {slug!r}: grant pattern {pattern!r} must look like app.entity or "
                    "app.entity:action, with * for a part, or * alone.",
                    "Write e.g. classes.session, classes.session:view or classes.*.",
                    key=True,
                )
                return
            if action and action != "*" and "*" not in action and action not in STANDARD_ACTIONS:
                self.add(
                    "C218",
                    where,
                    f"Role {slug!r}: {pattern!r} names the action {action!r}. A spec grants "
                    f"{', '.join(STANDARD_ACTIONS)} or *.",
                    "Grant a standard action. An entity's own actions (class Karni: actions) "
                    "are granted in KARNI_ROLES by hand.",
                    key=True,
                )
                return
            matched = self.matching(app, model)
            if not matched:
                self.add(
                    "C233",
                    where,
                    f"Role {slug!r}: grant {pattern!r} names no entity of the spec and no model "
                    "of an added module.",
                    "Name an entity as app.entity (e.g. classes.session), or add the module whose "
                    "model it names.",
                    key=True,
                )
                return
            explicit = matched[0] if len(matched) == 1 and "*" not in target else None
        kind, colon, arg = scope.partition(":")
        if kind == "all" and not colon:
            return
        if kind == "own" and not colon:
            return
        if kind == "own" and arg:
            if explicit is None:
                self.add(
                    "C218",
                    where,
                    f"Role {slug!r}: own:{arg} on {pattern!r} names a field, so the pattern must "
                    "name one entity.",
                    "Write own (each entity's own owner field), or name one entity.",
                )
            elif arg != explicit.owner:
                self.add(
                    "C234",
                    where,
                    f"Role {slug!r}: own:{arg} on {pattern!r}, but {explicit.name}'s owner field "
                    f"is {explicit.owner!r}. Karni's own scope compares the owner field with "
                    "the user.",
                    f"Set owner: {arg} on {explicit.name}, or write own.",
                )
            return
        if kind == "related" and arg and not arg.isidentifier():
            self.add(
                "C218",
                where,
                f"Role {slug!r}: related:{arg} on {pattern!r}. Karni's related scope takes a scope "
                "path key (from the entity's scope_paths), compared with the user's attribute of "
                "the same name, not a path.",
                "For rows reached through a relation to the user, write owned:<path> in the "
                "entity's access (e.g. owned:session__instructor), or declare a scope path key.",
            )
            return
        if kind == "related" and arg:
            if explicit is not None and arg not in explicit.entity.scope_paths:
                self.add(
                    "C234",
                    where,
                    f"Role {slug!r}: related:{arg} on {pattern!r}, but {explicit.name} has no "
                    f"scope path {arg!r}.",
                    f"Add scope_paths: {{{arg}: <lookup>}} to {explicit.name}, e.g. "
                    f"{{{arg}: {arg}}}.",
                )
            return
        if kind == "custom" and arg:
            return
        self.add(
            "C218",
            where,
            f"Role {slug!r}: scope {scope!r} on {pattern!r} is not a scope.",
            "Use all, own, own:<owner field>, related:<scope path key> or custom:<name>.",
        )

    def matching(self, app: str, model: str) -> list[_Entity | None]:
        found: list[_Entity | None] = [
            entity
            for entity in self.entities.values()
            if fnmatch.fnmatchcase(entity.app, app)
            and fnmatch.fnmatchcase(entity.name.lower(), model.lower())
        ]
        for name in self.modules:
            known = MODULES.get(name)
            if (
                known is not None
                and fnmatch.fnmatchcase(known.app, app)
                and any(fnmatch.fnmatchcase(m.lower(), model.lower()) for m in known.models)
            ):
                found.append(None)
        return found

    # features, modules

    def features(self) -> None:
        social = self.spec.features.social_login
        for name in social:
            if name not in SOCIAL_PROVIDERS:
                self.add(
                    "C219",
                    ("features", "social_login"),
                    f"social_login names {name!r}, which is not a built-in provider "
                    f"({', '.join(SOCIAL_PROVIDERS)}).",
                    "Name a built-in provider. A provider class of your own goes in "
                    "KARNI_SOCIAL_TOKEN_PROVIDERS by hand.",
                )
        if len(set(social)) != len(social):
            self.add(
                "C219",
                ("features", "social_login"),
                "social_login names a provider twice.",
                "List each provider once.",
            )
        terms = self.spec.features.terms
        if terms is None:
            return
        if not terms.version.strip() or len(terms.version) > 100:
            self.add(
                "C219",
                ("features", "terms", "version"),
                f"terms.version {terms.version!r} must be a non-empty text of at most 100 "
                "characters.",
                'Write the version as text, e.g. version: "2026-11".',
            )
        for key in ("paths", "exempt"):
            for prefix in getattr(terms, key) or []:
                if not prefix.startswith("/"):
                    self.add(
                        "C219",
                        ("features", "terms", key),
                        f"terms.{key} has {prefix!r}, which is not a URL path prefix.",
                        "Start each prefix with /, e.g. /api/.",
                    )

    def modules_(self) -> None:
        for name, options in self.spec.modules.items():
            known = MODULES.get(name)
            if known is None:
                self.add(
                    "C236",
                    ("modules", name),
                    f"Karni does not know a module named {name!r} (modules: "
                    f"{', '.join(sorted(MODULES))}).",
                    "Fix the name. A module of your own is added with karni add and stays out of "
                    "the spec.",
                    key=True,
                )
                continue
            for option, value in options.items():
                where = ("modules", name, option)
                types = known.options.get(option)
                if types is None:
                    self.add(
                        "C221",
                        where,
                        f"The {name} module has no option {option!r} (options: "
                        f"{', '.join(known.options)}).",
                        f"Use one of its options, each the setting {known.setting('<option>')}.",
                        key=True,
                    )
                elif _json_type(value) not in types:
                    self.add(
                        "C221",
                        where,
                        f"{name}.{option} ({known.setting(option)}) must be "
                        f"{' or '.join(types)}, got {_kind(value)}.",
                        "Write the value the setting takes (the module's README lists them).",
                    )
        if self.spec.app.kind == "app" and "site" in self.spec.modules:
            self.add(
                "C225",
                ("modules", "site"),
                "The site module is added, but app.kind is app: karni add site makes the "
                "project a site+app.",
                "Write kind: site+app (karni new --kind site+app adds the module by itself).",
                key=True,
            )

    def requirements(self) -> None:
        """What each listed module and feature requires and conflicts with (the catalog's)."""
        listed: dict[str, tuple[str, KnownModule | KnownFeature]] = {
            name: ("modules", MODULES[name]) for name in self.spec.modules if name in MODULES
        }
        if self.spec.app.kind != "app" and "site" in MODULES:
            listed.setdefault("site", ("modules", MODULES["site"]))
        for name, feature in FEATURES.items():
            if getattr(self.spec.features, name, None):
                listed[name] = ("features", feature)
        reported: set[frozenset[str]] = set()
        for name, (area, known) in listed.items():
            for other in known.requires:
                if other not in listed and (other in MODULES or other in FEATURES):
                    where = "modules" if other in MODULES else "features"
                    self.add(
                        "C324",
                        (area, name),
                        f"{name} requires {other}, which the spec does not list.",
                        f"Add {other} under {where}:, or leave {name} out.",
                        key=True,
                    )
            for other in known.conflicts:
                if other in listed and frozenset((name, other)) not in reported:
                    reported.add(frozenset((name, other)))
                    self.add(
                        "C324",
                        (area, name),
                        f"{name} and {other} cannot be used together.",
                        f"Leave {name} or {other} out.",
                        key=True,
                    )

    # pages, seed

    def find(self, name: str) -> _Entity | str:
        """The entity ``Name`` or ``app.Name`` names, else a message saying why it names none."""
        if "." in name:
            return self.entities.get(name) or f"no entity {name}"
        found = [e for e in self.entities.values() if e.name == name]
        if len(found) == 1:
            return found[0]
        if found:
            apps = ", ".join(e.app for e in found)
            return f"apps {apps} all define {name} (write app.{name})"
        return f"no app of the spec has an entity {name}"

    def pages(self) -> None:
        routes: dict[str, int] = {}
        seen: set[str] = set()
        for index, item in enumerate(self.spec.pages):
            where: Loc = ("pages", index)
            if len(item) != 1:
                self.add(
                    "C220",
                    where,
                    f"Page entry {index + 1} has {len(item)} keys: each entry is one key, an "
                    "entity with its pages or a page name with its kind.",
                    "Write one entry per line, e.g. - Session: [list, detail, form].",
                )
                continue
            ((name, kinds),) = item.items()
            where = ("pages", index, name)
            if name in seen:
                self.add(
                    "C220",
                    where,
                    f"{name} is listed twice in pages.",
                    "List each entity or page once.",
                    key=True,
                )
                continue
            seen.add(name)
            paths: list[str] = []
            if name[:1].isupper():
                entity = self.find(name)
                if not isinstance(entity, _Entity):
                    self.add(
                        "C235",
                        where,
                        f"pages names the entity {name}, but {entity}.",
                        "Name an entity of the spec, or add it under apps.",
                        key=True,
                    )
                    continue
                bad = [kind for kind in kinds if kind not in ENTITY_PAGES]
                if bad or not kinds or len(set(kinds)) != len(kinds):
                    self.add(
                        "C220",
                        where,
                        f"{name}'s pages are {kinds!r}: an entity takes list, detail and form, "
                        "each once.",
                        f"Write e.g. - {name}: [list, detail, form].",
                    )
                    continue
                base = f"/{default_route(entity.name)}"
                paths = [
                    *([base] if "list" in kinds else []),
                    *([f"{base}/$id"] if "detail" in kinds else []),
                    *([f"{base}/new", f"{base}/$id/edit"] if "form" in kinds else []),
                ]
            else:
                if not re.fullmatch(schema.PAGE_NAME, name):
                    self.add(
                        "C215",
                        where,
                        f"Page name {name!r} must be kebab-case, or an entity's PascalCase name.",
                        "Rename it, e.g. about or price-list.",
                        key=True,
                    )
                    continue
                if len(kinds) != 1 or kinds[0] not in NAMED_PAGES:
                    self.add(
                        "C220",
                        where,
                        f"Page {name!r} is {kinds!r}: a named page is one of "
                        f"{', '.join(NAMED_PAGES)}.",
                        f"Write e.g. - {name}: blank (or - home: dashboard, - login: login).",
                    )
                    continue
                if kinds[0] == "dashboard" and name != "home":
                    self.add(
                        "C220",
                        where,
                        f"Page {name!r} is a dashboard. The dashboard is the scaffold's home page, "
                        "at /.",
                        "Write - home: dashboard, and blank for a page of your own.",
                    )
                    continue
                paths = ["/"] if kinds[0] == "dashboard" else [f"/{name}"]
            for path in paths:
                if path in routes:
                    self.add(
                        "C242",
                        where,
                        f"{name}'s page at {path} has the route of page entry {routes[path] + 1}.",
                        "Rename the page, or drop one of them.",
                        key=True,
                    )
                routes[path] = index

    def seed(self) -> None:
        for name, count in self.spec.seed.items():
            entity = self.find(name)
            if not isinstance(entity, _Entity):
                self.add(
                    "C241",
                    ("seed", name),
                    f"seed names the entity {name}, but {entity}.",
                    "Name an entity of the spec.",
                    key=True,
                )
            elif entity.entity.external and count:
                self.add(
                    "C251",
                    ("seed", name),
                    f"seed.{name} is {count}, but {name} is external: another system fills its "
                    "table, so karni seed skips it.",
                    f"Remove {name} from seed, or write 0.",
                    key=True,
                )
            if count < 0:
                self.add(
                    "C223",
                    ("seed", name),
                    f"seed.{name} is {count}: a count of demo rows is 0 or more (0 skips it).",
                    f"Write a count, e.g. {name}: 20.",
                )


_FIELD_FIX: Final = (
    "Write the type as karni make model takes it: name: type[:arg...], a trailing ? for "
    "optional (karni make model --help lists the types)."
)


def _field_message(exc: CliError) -> str:
    """The generator's own message, which names the field and what is wrong."""
    return f"{exc.message} (karni make model {exc.code})" if exc.code else exc.message


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def validate_text(text: str, *, databases: Collection[str] | None = None) -> Report:
    """Experimental. Validate a spec's text: the parsed :class:`~schema.Spec` and every issue.

    ``databases``: the project's ``DATABASES`` aliases, when the caller knows
    them, to check each entity's ``database`` against (``C252``).
    """
    try:
        source = load(text)
    except YamlError as exc:
        return Report(
            None,
            [
                Issue(
                    "C211",
                    exc.line,
                    "",
                    f"The spec is not valid YAML: {exc.message}.",
                    "Fix the line it names. Indent with spaces. Quote a value that holds ': ' "
                    "or starts with *, &, !, %, @ or a backtick, and inside {...} or [...] "
                    'quote every value that holds a colon: {name: "str:120"}.',
                )
            ],
        )
    check = _Checker(source)
    data = _first_pass(check, source.data)
    spec = None
    if data is not None:
        try:
            spec = schema.Spec.model_validate(data)
        except ValidationError as exc:
            _shape_issues(check, exc, data)
    if spec is not None and not any(issue.code == "C214" for issue in check.issues):
        _Meaning(check, spec, databases).run()
    issues = sorted(check.issues, key=lambda issue: (issue.line or 0, issue.code))
    return Report(spec, issues, source)


def iter_codes() -> Iterator[str]:
    """Experimental. Every code this module reports (the error registry documents each one)."""
    yield from ("C211", "C212", "C213", "C214", "C215", "C216", "C217", "C218", "C219")
    yield from ("C220", "C221", "C222", "C223", "C224", "C225")
    yield from (f"C{n}" for n in range(230, 243))
    yield from ("C251", "C252", "C253", "C254")
    yield "C324"
