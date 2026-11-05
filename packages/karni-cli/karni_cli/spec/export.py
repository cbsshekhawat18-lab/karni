"""Experimental. ``karni spec export``: the spec of an existing project, from its code.

The backend facts come from ``manage.py karni_facts`` through the project's
interpreter (the CLI never imports project code): each model's fields with
their class and ``deconstruct()`` arguments, ``Meta.ordering``, ``class
Karni`` and ``AdminMeta``, each viewset's access, search fields and
response caching, the settings behind roles and features, the installed modules' settings and the
seeders. The pages come from ``frontend/src/routes.tsx`` and the page files
it imports, read as text. ``navigation`` (experimental) comes from a
``KARNI_NAVIGATION`` list: each item names the page whose route it links to
(:func:`karni_cli.spec.navigation.entries_from_setting`).

A field is written in the field syntax when the type it names makes the same
column: the same class and the same length, digits, null, choices, states,
target and unique. An argument the syntax does not carry that only changes
behaviour (a ``default``, a ``help_text``, an ``on_delete``) keeps the field
in the spec and is listed as a note. A field whose column the syntax cannot
make (a ``SearchField``, Django's own ``EmailField``, a ``MoneyField`` with
other digits) is left out and listed. So are access declarations other than
the spec's shapes (written ``access: code``), ``class Karni`` options the
spec has no key for (``search`` is ``global_search``), a ``Cache``'s ``depends_on`` and an
``Uncached``'s reason (the spec writes ``cache: <ttl>`` or ``cache: false``), hand-written
pages and grants the spec cannot name. The
list is printed, and written as comments at the top of the file.

An entity is a model on ``BaseModel`` or ``BigIntBaseModel`` (its ``pk``
written when it differs from the project's ``KARNI_PK``, ``tree`` when
it inherits ``TreeModel`` or ``OrderedTreeModel``, and ``taxonomies`` from
``class Karni: taxonomies``, a generated many-to-many left out of the
fields), an external model
(``external``, ``table``, ``writable``, ``database``), or a model Karni
manages on another database (``database``, on ``UUIDModel`` or
``IntegerKeyModel``).

Override / escape hatch: :func:`build` takes the facts and the project
directory, so a tool with facts of its own (or a test) maps them without a
project interpreter.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli import project as project_mod
from karni_cli.generators.naming import default_route, snake
from karni_cli.kinds import project_kind
from karni_cli.project import CliError
from karni_cli.spec import emit, navigation, schema
from karni_cli.spec.catalog import (
    DEFAULT_CACHE_TTL,
    MODULES,
    OTHER_MODELS,
    SOCIAL_PROVIDERS,
    module_setting,
)
from karni_cli.spec.normal import role_name
from karni_cli.spec.schema import AGGREGATE_METRICS
from karni_cli.spec.validate import TREE_FIELDS

__all__ = [
    "Exported",
    "aggregate_of",
    "build",
    "export_project",
    "is_entity",
    "read_facts",
    "roles_of",
    "spec_table",
]

_MISSING: Final = object()
#: Arguments that change the column (or its constraint or index): a difference leaves the field out.
COLUMN_ARGS: Final = frozenset(
    {
        "max_length",
        "max_digits",
        "decimal_places",
        "null",
        "unique",
        "db_index",
        "primary_key",
        "db_column",
        "choices",
        "currency",
        "currency_field",
        "min_value",
        "max_value",
        "rounding",
        "total",
        "base_field",
        "size",
        "indexed",
        "queried",
        "populate_from",
        "states",
        "transitions",
        "through",
        "db_table",
    }
)
_DJ = "django.db.models.fields."
KINDS: Final = {
    f"{_DJ}CharField": "str",
    f"{_DJ}TextField": "text",
    f"{_DJ}IntegerField": "int",
    f"{_DJ}FloatField": "float",
    f"{_DJ}DecimalField": "decimal",
    f"{_DJ}BooleanField": "bool",
    f"{_DJ}DateField": "date",
    f"{_DJ}DateTimeField": "datetime",
    f"{_DJ}URLField": "url",
    f"{_DJ}UUIDField": "uuid",
    f"{_DJ}files.FileField": "file",
    f"{_DJ}files.ImageField": "image",
    f"{_DJ}related.ForeignKey": "fk",
    f"{_DJ}related.OneToOneField": "o2o",
    f"{_DJ}related.ManyToManyField": "m2m",
    "karni.fields.money.MoneyField": "money",
    "karni.fields.numbers.PercentField": "percent",
    "karni.fields.numbers.QuantityField": "quantity",
    "karni.fields.text.EmailField": "email",
    "karni.fields.text.SlugField": "slug",
    "karni.fields.text.PhoneField": "phone",
    "karni.fields.text.MarkdownField": "markdown",
    "karni.fields.iso.CountryField": "country",
    "karni.fields.iso.CurrencyField": "currency",
    "karni.fields.structured.JSONField": "json",
    "karni.fields.arrays.ArrayField": "array",
    "karni.fields.state.StateField": "state",
    "karni.fields.ranges.DateRangeField": "daterange",
    "karni.fields.ranges.DateTimeRangeField": "datetimerange",
    "karni.fields.capacity.CapacityField": "capacity",
    # karni-storage's protected fields: file:protected and image:protected
    "karni_storage.fields.ProtectedFileField": "file",
    "karni_storage.fields.ProtectedImageField": "image",
}
_STRINGISH: Final = frozenset(
    {"str", "text", "email", "url", "slug", "file", "image", "choice", "phone", "country"}
    | {"currency", "markdown"}
)
_ARRAY_BASES: Final = {
    "django.db.models.CharField": "str",
    "django.db.models.TextField": "text",
    "django.db.models.IntegerField": "int",
    "django.db.models.BooleanField": "bool",
    "django.db.models.DateField": "date",
    "django.db.models.DateTimeField": "datetime",
    "django.db.models.UUIDField": "uuid",
}
_CASCADE: Final = "django.db.models.deletion.CASCADE"
_SET_NULL: Final = "django.db.models.deletion.SET_NULL"
#: ``class Karni`` options the spec writes, by spec key.
KARNI_KEYS: Final = {
    "import_key": "key",
    "owner_field": "owner",
    "audit": "audit",
    "scope_paths": "scope_paths",
    "field_groups": "groups",
    "column_sets": "column_sets",
}
_IMPORT: Final = re.compile(
    r"""^import\s+(\w+)\s+from\s+["']\./pages/([\w./-]+)["'];?""", re.MULTILINE
)
_ROUTE: Final = re.compile(r"""path:\s*["']([^"']+)["']\s*,\s*component:\s*(\w+)""")
_RESOURCE: Final = re.compile(
    r"""<(ResourceTable|ResourceDetail|ResourceForm)\b[^>]*?resource=["']([\w-]+)["']"""
)
_PAGE_KINDS: Final = {"ResourceTable": "list", "ResourceDetail": "detail", "ResourceForm": "form"}
#: A detail page's related tabs: ``related={["deals", "deals.partner"]}``.
_RELATED: Final = re.compile(r"""\brelated=\{\[([^\]]*)\]\}""")


@dataclass
class Exported:
    """Experimental. The exported spec's data and what it leaves to the code."""

    data: dict[str, Any]
    #: What the spec does not carry, one line each ("events.Event.search: ...").
    left_out: list[str] = field(default_factory=list)

    def text(self) -> str:
        header = [
            f"yaml-language-server: $schema={schema.SCHEMA_URL}",
            "Written by karni spec export (experimental). Check it: karni spec validate.",
        ]
        if self.left_out:
            header += ["", "Not in this spec, kept in the project's code:"]
            header += [f"  - {line}" for line in self.left_out]
        return emit.dump(self.data, header=header)


def read_facts(
    root: Path,
    *,
    docker: bool | None = None,
    service: str = "django",
    command: str = "karni spec export",
    code: str = "C245",
) -> Any:
    """Experimental. ``manage.py karni_facts`` through the project's interpreter, parsed.

    ``command`` and ``code`` name the command that reads the project in the
    error (``karni plan`` passes its own, ``C250``).
    """
    proc = project_mod.run_manage(root, ["karni_facts"], docker=docker, service=service)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise _unreadable(
            f"manage.py karni_facts failed, so {command} cannot read the project "
            f"({' '.join(detail) or f'exit {proc.returncode}'}).",
            code,
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise _unreadable(
            "manage.py karni_facts did not print JSON. Something in the project prints to "
            "stdout at startup.",
            code,
        ) from None


def _unreadable(message: str, code: str) -> CliError:
    """The error of the command that could not read the project (``C250`` for karni plan)."""
    if code == "C250":
        return CliError(message, code="C250")
    return CliError(message, code="C245")


def export_project(root: Path, *, docker: bool | None = None, service: str = "django") -> Exported:
    """Experimental. The spec of the project at ``root``."""
    return build(read_facts(root, docker=docker, service=service), root)


# fields ---------------------------------------------------------------------------


@dataclass
class _Ctx:
    facts: dict[str, Any]
    #: model label -> how a relation in the spec names it, for every model the spec knows.
    names: dict[str, str]
    left_out: list[str]
    #: the project's KARNI_PK: an entity's pk is written when it differs.
    pk: str = "uuid"


def is_entity(model: dict[str, Any]) -> bool:
    """Experimental. Whether a model's facts make it an entity (see the module docstring)."""
    if model.get("proxy"):
        return False
    karni = model.get("karni") or {}
    if model.get("base_model") or karni.get("external") is True:
        return True
    return bool(karni.get("database")) and model.get("pk") in ("uuid", "bigint")


def spec_table(db_table: str) -> str:
    """Experimental. ``Meta.db_table`` as the spec's ``table``: ``reporting.sales`` for ``reporting"."sales``."""
    return db_table.replace('"."', ".")


def _expected(kind: str, optional: bool) -> dict[str, Any]:
    if not optional:
        return {}
    if kind in _STRINGISH or kind == "m2m":
        return {"blank": True}
    return {"null": True, "blank": True}


def _target(fact: dict[str, Any], app: str, model: str, ctx: _Ctx) -> str | None:
    if fact.get("related_is_user"):
        return "User"
    label = fact.get("related", "")
    if label == f"{app}.{model}":
        return "self"
    if label in ctx.names:
        target = ctx.names[label]
        return target.split(".", 1)[1] if target.startswith(f"{app}.") else target
    return None


def field_token(
    fact: dict[str, Any], app: str, model: str, ctx: _Ctx, siblings: set[str]
) -> tuple[str | None, list[str]]:
    """The field syntax for one field fact and its notes, or ``None`` and why it is left out."""
    name = fact["name"]
    where = f"{app}.{model}.{name}"
    kind = KINDS.get(fact["class"])
    if fact.get("generated") or kind is None:
        return None, [
            f"{where}: a field of class {fact['path']}, which no type of the syntax makes"
        ]
    kw = dict(fact["kwargs"])
    kw.pop("to", None)
    optional = bool(fact["blank"] if kind in _STRINGISH or kind == "m2m" else fact["null"])
    if kind == "slug" and kw.get("populate_from"):
        optional = False  # a generated slug is blank until saved: slug:title and slug:title? agree
    args: list[str] = []
    expected = _expected(kind, optional)
    explained: set[str] = set()
    if kind == "str" and fact.get("choices"):
        kind = "choice"
        values = fact["choices"]
        args = ["|".join(values)]
        expected["max_length"] = max(20, *(len(value) for value in values))
        explained.add("choices")
        if not optional:
            expected["default"] = values[0]
    elif kind == "str":
        length = kw.get("max_length", 255)
        args = [] if length == 255 else [str(length)]
        expected["max_length"] = length
    elif kind == "decimal":
        digits, places = kw.get("max_digits"), kw.get("decimal_places")
        args = [] if (digits, places) == (10, 2) else [str(digits), str(places)]
        expected |= {"max_digits": digits, "decimal_places": places}
    elif kind == "bool" and not optional:
        expected["default"] = False
    elif kind == "url" and "max_length" in kw:
        args = [str(kw["max_length"])]
        expected["max_length"] = kw["max_length"]
    elif kind == "uuid" and not optional:
        expected["default"] = "uuid.uuid4"
    elif kind in ("file", "image"):
        expected["upload_to"] = f"{app}/{snake(model)}/"
        if str(fact["class"]).startswith("karni_storage."):
            args = ["protected"]
    elif kind in ("fk", "o2o", "m2m"):
        target = _target(fact, app, model, ctx)
        if target is None:
            return None, [f"{where}: points at {fact.get('related')}, which is not in the spec"]
        args = [target]
        if kind != "m2m":
            expected["on_delete"] = _SET_NULL if optional else _CASCADE
            if optional:
                expected["null"] = True
        explained |= {"related_name", "symmetrical"} & {
            key
            for key, value in kw.items()
            if key == "symmetrical" or value == f"{snake(model)}_{name}_set"
        }
    elif kind == "money":
        expected |= {"max_digits": 19, "decimal_places": 4}
        if "currency" in kw:
            args = [str(kw["currency"])]
            expected["currency"] = kw["currency"]
        elif kw.get("currency_field") == f"{name}_currency":
            expected["currency_field"] = kw["currency_field"]
    elif kind == "percent":
        low, high = kw.get("min_value"), kw.get("max_value")
        if low is not None or high is not None:
            args = [str(low if low is not None else ""), str(high if high is not None else "")]
            args = [arg.removesuffix(".0") for arg in args]
        explained |= {"min_value", "max_value", "max_digits", "decimal_places"}
        if not optional:
            expected["default"] = 0
    elif kind == "quantity" and not optional:
        expected["default"] = 0
    elif kind == "email":
        expected["max_length"] = 254
        if kw.get("unique"):
            args = ["unique"]
            expected["unique"] = True
    elif kind == "slug":
        if kw.get("populate_from"):
            args = [str(kw["populate_from"])]
            expected["populate_from"] = kw["populate_from"]
        elif kw.get("max_length", 50) != 50:
            args = [str(kw["max_length"])]
            expected["max_length"] = kw["max_length"]
    elif kind in ("phone", "country", "currency"):
        explained.add("iso_revision")
    elif kind == "json":
        if not optional:
            expected["default"] = "builtins.dict"
        if kw.get("queried"):
            args = ["queried"]
            expected["queried"] = True
    elif kind == "array":
        base = kw.get("base_field") or {}
        base_kind = _ARRAY_BASES.get(base.get("class", ""))
        if base_kind is None:
            return None, [f"{where}: an ArrayField of {base.get('class')}, not in the syntax"]
        args = [base_kind]
        base_kwargs = base.get("kwargs", {})
        if base_kind == "str" and base_kwargs.get("max_length", 50) != 50:
            args.append(str(base_kwargs["max_length"]))
        expected["base_field"] = base
        expected["size"] = None
        if not optional:
            expected |= {"default": "builtins.list", "blank": True}
    elif kind == "state":
        states = fact.get("states") or []
        moves = fact.get("transitions") or {}
        args = ["|".join(f"{s}>{t}" for s in states for t in moves.get(s, []))]
        if not any(moves.values()):
            args = [",".join(states)]
        explained |= {"states", "transitions", "max_length", "default"}
        if kw.get("states") and all(isinstance(state, list) for state in kw["states"]):
            return _with_notes(kind, args, optional, [f"{where}: its state labels"])
    elif kind == "capacity":
        if kw.get("total"):
            args = [str(kw["total"])]
            expected["total"] = kw["total"]
        else:
            expected["default"] = 0
    if kind == "money" and "currency_field" in expected:
        siblings.add(f"{name}_currency")
    differing = sorted(
        key
        for key in set(kw) | set(expected)
        if key not in explained and kw.get(key, _MISSING) != expected.get(key, _MISSING)
    )
    column = [key for key in differing if key in COLUMN_ARGS]
    if column:
        shown = ", ".join(f"{key}={kw.get(key)!r}" for key in column)
        return None, [f"{where}: {shown}, which its type in the spec would not make"]
    notes = [f"{where}: {key}={kw.get(key)!r}" for key in differing]
    return _with_notes(kind, args, optional, notes)


def _with_notes(
    kind: str, args: list[str], optional: bool, notes: list[str]
) -> tuple[str, list[str]]:
    return ":".join([kind, *args]) + ("?" if optional else ""), notes


# the whole spec ---------------------------------------------------------------------


def _project_name(root: Path) -> str:
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        described = str(data.get("project", {}).get("description", ""))
    except (OSError, tomllib.TOMLDecodeError):
        described = ""
    if described.endswith(", a Karni project."):
        return described.removesuffix(", a Karni project.")
    readme = root / "README.md"
    if readme.is_file():
        first = readme.read_text(encoding="utf-8").lstrip().splitlines()[:1]
        if first and first[0].startswith("# "):
            return first[0][2:].strip()
    return root.name


def _access_items(described: dict[str, Any]) -> list[str] | None:
    if "any" in described:
        found: list[str] = []
        for part in described["any"]:
            items = _access_items(part)
            if items is None:
                return None
            found += items
        return found
    for word in ("public", "authenticated", "granted"):
        if described.get(word) is True and len(described) == 1:
            return [word]
    if set(described) == {"role"}:
        return [f"role:{name}" for name in described["role"]]
    if set(described) == {"owned"}:
        return [f"owned:{described['owned']}"]
    return None


def _one(items: list[str]) -> str | list[str]:
    return items[0] if len(items) == 1 else items


def _names_of(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def _access(viewset: dict[str, Any] | None, label: str, left_out: list[str]) -> Any:
    if viewset is None:
        left_out.append(f"{label}: no viewset (no API), so access is code")
        return "code"
    declared = viewset["access"]
    slots: dict[str, list[str]] = {}
    for slot in ("read", "write", "create"):
        items = _access_items(declared[slot]) if slot in declared else []
        if items is None:
            break
        if items:
            slots[slot] = items
    else:
        items = []
    if items is None or not {"read", "write"} <= set(slots):
        cls = viewset["class"].rsplit(".", 1)[-1]
        left_out.append(f"{label}: {cls}'s access is not one of the spec's shapes (access: code)")
        return "code"
    if slots == {"read": ["granted"], "write": ["granted"]}:
        return None
    return {slot: _one(sorted(dict.fromkeys(items))) for slot, items in slots.items()}


def _grant_ok(pattern: str, apps: dict[str, Any], modules: set[str]) -> bool:
    if pattern == "*":
        return True
    target, _, action = pattern.partition(":")
    app, _, model = target.partition(".")
    if action not in ("", "*", "view", "add", "change", "delete"):
        return False
    candidates = [
        name.lower()
        for label, application in apps.items()
        if fnmatch.fnmatchcase(label, app)
        for name in application["entities"]
    ]
    for module in modules:
        known = MODULES.get(module)
        if known is not None and fnmatch.fnmatchcase(known.app, app):
            candidates += [name.lower() for name in known.models]
    return any(fnmatch.fnmatchcase(name, model.lower()) for name in candidates)


def build(facts: dict[str, Any], root: Path) -> Exported:
    """Experimental. The spec data of a project from its facts (see the module docstring)."""
    left_out: list[str] = []
    kind = project_kind(root)
    app_info: dict[str, Any] = {"name": _project_name(root), "kind": kind.kind if kind else "app"}
    api_version = facts["settings"].get("KARNI_API_VERSION")
    if isinstance(api_version, str) and api_version:
        app_info["api_version"] = api_version
    data: dict[str, Any] = {"version": schema.VERSION, "app": app_info}
    # every model the spec can name: the entities, the added modules' models, Django's two
    entities: dict[str, dict[str, Any]] = {}
    for app in facts["apps"]:
        for model in app["models"]:
            if not is_entity(model):
                left_out.append(
                    f"{model['label']}: not on BaseModel or BigIntBaseModel and not external, "
                    "so not an entity"
                )
                continue
            entities[model["label"]] = model
    names_count: dict[str, int] = {}
    for label in entities:
        names_count[label.split(".", 1)[1]] = names_count.get(label.split(".", 1)[1], 0) + 1
    names = {label: label for label in entities}
    module_names = {module["name"] for module in facts["modules"]}
    for module in module_names:
        known = MODULES.get(module)
        for model in known.models if known else ():
            names[f"{known.app}.{model}"] = f"{known.app}.{model}"  # type: ignore[union-attr]
    for other in OTHER_MODELS:
        names[other] = other
    ctx = _Ctx(facts, names, left_out, str(facts["settings"].get("KARNI_PK") or "uuid"))
    viewsets: dict[str, dict[str, Any]] = {}
    routes: dict[str, str] = {}
    for viewset in facts["viewsets"]:
        if viewset["model"] in entities and viewset["model"] not in viewsets:
            viewsets[viewset["model"]] = viewset
            routes[viewset["route"]] = viewset["model"]
    apps: dict[str, Any] = {}
    for app in facts["apps"]:
        out: dict[str, Any] = {}
        for model in app["models"]:
            if model["label"] in entities:
                out[model["name"]] = _entity(model, app["label"], ctx, viewsets.get(model["label"]))
        if out:
            apps[app["label"]] = {"entities": out}
    # modules, before the roles (a grant may name a module's model)
    modules: dict[str, Any] = {}
    for module in facts["modules"]:
        known = MODULES.get(module["name"])
        if known is None:
            left_out.append(f"modules: karni_{module['name']}, which the spec does not know")
            continue
        options = {
            option: module["settings"][module_setting(known.name, option)]
            for option in known.options
            if module["settings"].get(module_setting(known.name, option), _MISSING)
            != module["defaults"].get(module_setting(known.name, option), _MISSING)
        }
        if known.name == "site" and app_info["kind"] != "app" and not options:
            continue
        modules[known.name] = options
    if modules:
        data["modules"] = modules
    settings = facts["settings"]
    features = _features(settings, left_out)
    if features:
        data["features"] = features
    roles = _roles(facts, apps, set(modules) | ({"site"} if app_info["kind"] != "app" else set()))
    if roles is not None:
        data["roles"] = roles[0]
        left_out += roles[1]
    if apps:
        data["apps"] = apps
    pages = _pages(root, routes, entities, names_count, left_out)
    if pages:
        data["pages"] = pages
    menu = navigation.entries_from_setting(
        settings.get("KARNI_NAVIGATION"),
        navigation.pages(schema.Spec.model_validate(data)),
        left_out,
    )
    if menu:
        data["navigation"] = menu
    seed = {
        _entity_ref(label, names_count): count
        for label, count in facts["seeders"].items()
        if label in entities and count is not None
    }
    if seed:
        data["seed"] = seed
    return Exported(data, left_out)


def _entity_ref(label: str, names_count: dict[str, int]) -> str:
    name = label.split(".", 1)[1]
    return name if names_count.get(name) == 1 else label


def _entity(
    model: dict[str, Any], app: str, ctx: _Ctx, viewset: dict[str, Any] | None
) -> dict[str, Any]:
    label = model["label"]
    fields: dict[str, str] = {}
    siblings: set[str] = set()
    tokens = [
        (fact, *field_token(fact, app, model["name"], ctx, siblings)) for fact in model["fields"]
    ]
    for fact, token, notes in tokens:
        if fact["name"] in siblings and fact["class"] == "karni.fields.iso.CurrencyField":
            continue  # the money field's own currency column
        if token is not None:
            fields[fact["name"]] = token
        ctx.left_out.extend(notes)
    entity: dict[str, Any] = {"fields": fields}
    karni = dict(model["karni"])
    external = karni.pop("external", None) is True
    writable = karni.pop("writable", None) is True
    database = karni.pop("database", None)
    if external:
        entity["external"] = True
        entity["table"] = spec_table(str(model.get("db_table") or ""))
        if writable:
            entity["writable"] = True
    elif model.get("pk") in ("uuid", "bigint") and model["pk"] != ctx.pk:
        entity["pk"] = model["pk"]
    if isinstance(database, str) and database and database != "default":
        entity["database"] = database
    tree = model.get("tree")  # the facts leave parent (and position) out of the fields
    if tree in ("tree", "ordered"):
        entity["tree"] = True if tree == "tree" else "ordered"
    karni.pop("taxonomies", None)  # read from the facts' own taxonomies, targets resolved
    taxonomies = _taxonomies(model, ctx)
    if taxonomies:
        entity["taxonomies"] = taxonomies
    for option, key in KARNI_KEYS.items():
        if option in karni:
            value = karni.pop(option)
            if value not in (None, False, {}, []):
                entity[key] = value
    if karni.get("aggregate") not in (None, False):
        found = aggregate_of(karni["aggregate"])
        if found is not None:
            entity["aggregate"] = found
            karni.pop("aggregate")
    searched = karni.pop("search", None)
    for option in sorted(karni):
        ctx.left_out.append(f"{label}: class Karni {option}")
    if viewset is not None and viewset["search_fields"]:
        entity["search"] = _one(viewset["search_fields"])
    if searched not in (None, False):
        value = _global_search(searched, entity.get("search"))
        if value is None:
            ctx.left_out.append(f"{label}: class Karni search (a shape the spec cannot write)")
        else:
            entity["global_search"] = value
    admin = dict(model["admin_meta"])
    extra = dict(admin.pop("extra", None) or {})
    fieldsets = extra.pop("fieldsets", None)
    # Before Karni.field_groups, karni build wrote the groups as the admin's fieldsets.
    if fieldsets and "groups" not in entity:
        groups = {}
        for title, options in fieldsets:
            if not title:
                ctx.left_out.append(f"{label}: a field group without a title")
                continue
            groups[str(title)] = list(options.get("fields", []))
        if groups:
            entity["groups"] = groups
    elif fieldsets:
        ctx.left_out.append(f"{label}: AdminMeta fieldsets (the spec's groups are field_groups)")
    for option in sorted([*admin, *extra]):
        ctx.left_out.append(f"{label}: AdminMeta {option}")
    for option in model["api_meta"]:
        ctx.left_out.append(f"{label}: APIMeta {option}")
    order = [item for item in model["ordering"] if isinstance(item, str)]
    if len(order) != len(model["ordering"]):
        ctx.left_out.append(f"{label}: an ordering expression")
    if order:
        entity["order"] = _one(order)
    access = _access(viewset, label, ctx.left_out)
    if access is not None:
        entity["access"] = access
    cache = _cache(viewset, label, ctx.left_out)
    if cache is not None:
        entity["cache"] = cache
    _drop_unknown(entity, label, ctx.left_out)
    return entity


def _taxonomies(model: dict[str, Any], ctx: _Ctx) -> dict[str, str]:
    """Experimental. The facts' taxonomies as the spec's: key -> how the spec names the tree.

    A tree model the spec does not know is left out with a note.
    """
    found: dict[str, str] = {}
    for key, fact in (model.get("taxonomies") or {}).items():
        name = ctx.names.get(str(fact.get("to")))
        if name is None:
            ctx.left_out.append(f"{model['label']}: the taxonomy {key} on {fact.get('to')}")
            continue
        found[str(key)] = name
    return found


def aggregate_of(declared: Any) -> dict[str, Any] | None:
    """Experimental. ``class Karni: aggregate`` (as the facts carry it) in the spec's form.

    ``None`` when the spec cannot express it: expressions (``TextNumber`` and
    the project's own stay in code), or anything but a dict of name lists.
    """
    if not isinstance(declared, dict) or set(declared) - {"group_by", "values", "metrics"}:
        return None
    lists = {key: declared.get(key) or [] for key in ("group_by", "values", "metrics")}
    if not all(
        isinstance(value, list) and all(isinstance(item, str) for item in value)
        for value in lists.values()
    ):
        return None
    found: dict[str, Any] = {"group_by": list(lists["group_by"])}
    if lists["values"]:
        found["values"] = list(lists["values"])
    if lists["metrics"] and set(lists["metrics"]) != set(AGGREGATE_METRICS):
        found["metrics"] = list(lists["metrics"])
    return found


def _cache(viewset: dict[str, Any] | None, label: str, left_out: list[str]) -> int | bool | None:
    """``cache:`` from the viewset's ``cache`` declaration: its ttl, ``false``, or none."""
    declared = (viewset or {}).get("cache")
    if not isinstance(declared, dict):
        return None
    if "uncached" in declared:
        reason = declared["uncached"]
        if reason != schema.UNCACHED_REASON:
            left_out.append(
                f'{label}: the reason of Uncached, "{reason}" '
                f'(the spec writes "{schema.UNCACHED_REASON}")'
            )
        return False
    depends_on = declared.get("depends_on") or []
    if depends_on:
        left_out.append(f"{label}: Cache depends_on {', '.join(map(str, depends_on))}")
    ttl = declared.get("ttl")
    return ttl if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl > 0 else None


def _global_search(declared: Any, search: Any) -> Any:
    """``Karni.search`` as the spec's ``global_search``: ``true`` when it is the defaults.

    ``None`` for a declaration the key cannot carry (no list of fields).
    """
    if not isinstance(declared, dict):
        return None
    raw = declared.get("fields")
    fields = [raw] if isinstance(raw, str) else raw
    if not isinstance(fields, list) or not fields or not all(isinstance(f, str) for f in fields):
        return None
    searched = [search] if isinstance(search, str) else list(search or [])
    written: dict[str, Any] = {}
    if fields != searched:
        written["fields"] = fields
    title, subtitle, weight = (declared.get(key) for key in ("title", "subtitle", "weight"))
    if isinstance(title, str) and title != fields[0]:
        written["title"] = title
    if isinstance(subtitle, str):
        written["subtitle"] = subtitle
    if isinstance(weight, int | float) and not isinstance(weight, bool) and weight != 1:
        written["weight"] = weight
    return written or True


def _drop_unknown(entity: dict[str, Any], label: str, left_out: list[str]) -> None:
    """Drop what names a field the spec left out, so the export always validates."""
    fields = set(entity["fields"]) | set(TREE_FIELDS.get(entity.get("tree", False), ()))
    fields |= set(entity.get("taxonomies", {}))
    known = fields | {"id", "created_at", "updated_at"}

    def keep(value: str, names: set[str]) -> bool:
        return value.lstrip("-^=@$").split("__", 1)[0] in names

    original_search = _names_of(entity.get("search"))
    for key, names in (("search", known), ("order", known), ("audit", fields)):
        value = entity.get(key)
        if not isinstance(value, list | str):
            continue
        items = [value] if isinstance(value, str) else value
        kept = [item for item in items if keep(item, names)]
        for item in items:
            if item not in kept:
                left_out.append(f"{label}: {key} {item}, a field the spec leaves out")
        if kept:
            entity[key] = _one(kept) if key != "audit" else kept
        else:
            entity.pop(key)
    for key in ("key", "owner"):
        value = entity.get(key)
        if isinstance(value, str) and not keep(value, known | {"created_by"}):
            left_out.append(f"{label}: {key} {value}, a field the spec leaves out")
            entity.pop(key)
    _drop_unknown_search(entity, label, left_out, original_search)
    for title, members in list(entity.get("groups", {}).items()):
        if any(member not in fields for member in members):
            left_out.append(f"{label}: the field group {title}, with a field the spec leaves out")
            entity["groups"].pop(title)
    if entity.get("groups") == {}:
        entity.pop("groups")
    for name, columns in list(entity.get("column_sets", {}).items()):
        if any(column not in known for column in columns):
            left_out.append(f"{label}: the column set {name}, with a field the spec leaves out")
            entity["column_sets"].pop(name)
    if entity.get("column_sets") == {}:
        entity.pop("column_sets")
    aggregate = entity.get("aggregate")
    if aggregate is not None:
        reach = known | {"created_by", "updated_by"}
        entries = [*aggregate["group_by"], *aggregate.get("values", [])]
        if any(entry.partition(":")[0].split("__", 1)[0] not in reach for entry in entries):
            left_out.append(f"{label}: aggregate, with a field the spec leaves out")
            entity.pop("aggregate")


def _drop_unknown_search(
    entity: dict[str, Any], label: str, left_out: list[str], original_search: list[str]
) -> None:
    """Drop ``global_search`` when it names a field the spec left out.

    ``original_search`` is the ``search`` list before :func:`_drop_unknown`
    trimmed it: ``global_search: true`` takes its fields from it, so a
    trimmed list turns ``true`` into the fields it stood for.
    """
    searched = entity.get("global_search")
    if searched is None:
        return
    mapping: dict[str, Any] = searched if isinstance(searched, dict) else {}
    names = _names_of(mapping["fields"]) if "fields" in mapping else original_search
    shown = [path for path in (mapping.get("title"), mapping.get("subtitle")) if path]
    known = set(entity["fields"]) | {"id", "created_at", "updated_at"}
    if any(name not in entity["fields"] for name in names) or any(
        str(path).split("__", 1)[0] not in known for path in shown
    ):
        left_out.append(f"{label}: class Karni search, with a field the spec leaves out")
        entity.pop("global_search")
        return
    if "fields" not in mapping and _names_of(entity.get("search")) != original_search:
        entity["global_search"] = {**mapping, "fields": names}


def _features(settings: dict[str, Any], left_out: list[str]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    if settings.get("KARNI_2FA"):
        features["two_factor"] = True
    if settings.get("KARNI_EMAIL_OTP"):
        features["email_code_login"] = True
    providers = settings.get("KARNI_SOCIAL_TOKEN_PROVIDERS") or {}
    social = []
    for name, entry in providers.items():
        if name in SOCIAL_PROVIDERS and not (isinstance(entry, dict) and entry.get("class")):
            social.append(name)
        else:
            left_out.append(f"features: the social sign-in provider {name} (its own class)")
    if social:
        features["social_login"] = social
    terms = settings.get("KARNI_TERMS")
    if isinstance(terms, dict):
        written = {key: terms[key] for key in ("version", "url") if key in terms}
        if terms.get("required", True) is not True:
            written["required"] = terms["required"]
        for key in ("paths", "exempt"):
            if key in terms:
                written[key] = list(terms[key])
        features["terms"] = written
    if settings.get("KARNI_USER_GRANTS"):
        features["user_grants"] = True
    if settings.get("KARNI_API_CACHE") is True:
        ttl = settings.get("KARNI_API_CACHE_TTL")
        custom = isinstance(ttl, int) and not isinstance(ttl, bool) and ttl != DEFAULT_CACHE_TTL
        features["api_cache"] = {"ttl": ttl} if custom else True
    return features


def _roles(
    facts: dict[str, Any],
    apps: dict[str, Any],
    modules: set[str],
    *,
    declared: dict[str, Any] | None = None,
    defaults: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]] | None:
    """The spec's roles from ``KARNI_ROLES`` (``None`` when it is Karni's shipped roles).

    With ``declared`` (and ``defaults``), those roles instead, always:
    :func:`roles_of` gives the shipped roles in the spec's form this way.
    """
    if declared is None:
        declared = facts["settings"].get("KARNI_ROLES") or {}
        if declared == facts.get("shipped_roles"):
            return None
    if defaults is None:
        defaults = facts["settings"].get("KARNI_ACCOUNTS_DEFAULT_ROLES") or []
    roles: dict[str, Any] = {}
    notes = []
    for slug, spec in declared.items():
        role: dict[str, Any] = {}
        if spec.get("name") and spec["name"] != role_name(slug):
            role["name"] = spec["name"]
        if spec.get("description"):
            role["description"] = spec["description"]
        if spec.get("system"):
            role["system"] = True
        if slug in defaults:
            role["default"] = True
        grants = {}
        for pattern, scope in (spec.get("grants") or {}).items():
            if _grant_ok(pattern, apps, modules):
                grants[pattern.removesuffix(":*") if pattern != "*" else pattern] = scope
            else:
                notes.append(f"roles: {slug}'s grant {pattern} ({scope})")
        if grants:
            role["grants"] = grants
        roles[slug] = role
    for slug in defaults:
        if slug not in declared:
            notes.append(f"roles: the default role {slug}, which KARNI_ROLES does not declare")
    return roles, notes


def roles_of(
    facts: dict[str, Any], declared: dict[str, Any], defaults: list[str], apps: dict[str, Any]
) -> dict[str, Any]:
    """Experimental. ``declared`` (a ``KARNI_ROLES``) in the spec's form, whatever it holds.

    ``karni plan`` reads the project's roles this way, also when they are the
    shipped ones (which the export leaves out).
    """
    modules = {module["name"] for module in facts["modules"]}
    found = _roles(facts, apps, modules, declared=declared, defaults=defaults)
    return found[0] if found else {}


def _pages(
    root: Path,
    routes: dict[str, str],
    entities: dict[str, Any],
    names_count: dict[str, int],
    left_out: list[str],
) -> list[dict[str, Any]]:
    frontend = root / "frontend" / "src"
    text = (
        (frontend / "routes.tsx").read_text(encoding="utf-8")
        if (frontend / "routes.tsx").is_file()
        else ""
    )
    files = {component: file for component, file in _IMPORT.findall(text)}
    pages: dict[str, list[Any]] = {}
    for path, component in _ROUTE.findall(text):
        file = files.get(component)
        source = ""
        if file is not None:
            candidates = [frontend / "pages" / f"{file}{ext}" for ext in ("", ".tsx", ".ts")]
            found = next((c for c in candidates if c.is_file()), None)
            source = found.read_text(encoding="utf-8") if found else ""
        named = _page_entry(path, source, routes, entities, names_count)
        if named is None:
            if component != "AppLayout":
                left_out.append(f"pages: {path} ({component}), a page of the project's own")
            continue
        key, kind = named
        kinds = pages.setdefault(key, [])
        if kind not in kinds:
            kinds.append(kind)
    out = []
    for key, kinds in pages.items():
        if key[:1].isupper():
            kinds = [
                kind
                for name in ("list", "detail", "form")
                for kind in kinds
                if kind == name or (isinstance(kind, dict) and name in kind)
            ]
        out.append({key: kinds[0] if len(kinds) == 1 and isinstance(kinds[0], str) else kinds})
    return out


def _related(source: str, routes: dict[str, str], names_count: dict[str, int]) -> list[str]:
    """A detail page's related tabs as the spec writes them (Deal, Deal.partner)."""
    found = _RELATED.search(source)
    if found is None:
        return []
    refs: list[str] = []
    for name in re.findall(r"""["']([\w.-]+)["']""", found.group(1)):
        resource, _, field = name.partition(".")
        label = routes.get(resource)
        if label is None:
            continue
        ref = _entity_ref(label, names_count)
        refs.append(f"{ref}.{field}" if field else ref)
    return refs


def _page_entry(
    path: str,
    source: str,
    routes: dict[str, str],
    entities: dict[str, Any],
    names_count: dict[str, int],
) -> tuple[str, Any] | None:
    if path == "/" and "<Dashboard" in source:
        return "home", "dashboard"
    found = _RESOURCE.search(source)
    if found is not None:
        kind = _PAGE_KINDS[found.group(1)]
        resource = found.group(2)
        label = routes.get(resource)
        if label is None:
            return None
        base = f"/{default_route(label.split('.', 1)[1])}"
        expected = {
            "list": [base],
            "detail": [f"{base}/$id"],
            "form": [f"{base}/new", f"{base}/$id/edit"],
        }
        if path not in expected[kind] or resource != base[1:]:
            return None
        related = _related(source, routes, names_count) if kind == "detail" else []
        if related:
            return _entity_ref(label, names_count), {"detail": {"related": related}}
        return _entity_ref(label, names_count), kind
    name = path.lstrip("/")
    if not re.fullmatch(schema.PAGE_NAME, name):
        return None
    if "<LoginForm" in source:
        return name, "login"
    components = set(re.findall(r"<([A-Z]\w*)", source))
    if components == {"Page"}:
        return name, "blank"
    if components == {"Page", "DashboardGrid", "ChartCard"} and "useResourceCounts(" in source:
        return name, "dashboard"  # the dashboard karni make page --kind dashboard writes
    return name, "code"  # a page of the project's own: karni build leaves it alone
