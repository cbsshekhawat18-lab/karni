"""The ``karni make model`` field DSL: ``name:type[:arg...][?]``.

:data:`FIELD_DOCS` lists every type with the Django field it produces (it is
also rendered into docs/cli.md). A trailing ``?`` makes the field optional:
``null=True, blank=True``; string and file fields get ``blank=True`` only
(Django stores ``""``, not ``NULL``); an optional FK/O2O uses
``on_delete=models.SET_NULL``. Choice values are separated by ``|`` (quote
the argument in a shell) or ``,``. Quote any field with ``?`` in zsh.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

from karni_cli.generators import lifecycle_fields
from karni_cli.generators.naming import pascal, snake
from karni_cli.generators.pysource import Import, call, pystr
from karni_cli.project import CliError

#: (syntax, what it generates) — the DSL reference, rendered into docs/cli.md.
FIELD_DOCS: tuple[tuple[str, str], ...] = (
    ("title:str[:len]", "CharField(max_length=len) — 255 when omitted"),
    ("body:text", "TextField()"),
    ("count:int", "IntegerField()"),
    ("ratio:float", "FloatField()"),
    ("price:decimal[:max:places]", "DecimalField(max_digits=max, decimal_places=places) — 10, 2"),
    ("done:bool", "BooleanField(default=False)"),
    ("day:date / at:datetime", "DateField() / DateTimeField()"),
    (
        "email:email / site:url / slug:slug",
        "EmailField() / URLField() / SlugField() (:len optional)",
    ),
    ("meta:json", "JSONField(default=dict)"),
    (
        "doc:file / photo:image",
        'FileField / ImageField(upload_to="<app>/<model>/") — image needs Pillow',
    ),
    ("ref:uuid", "UUIDField(default=uuid.uuid4)"),
    ("status:choice:draft|live", "a TextChoices class + CharField(choices=..., default=first)"),
    *lifecycle_fields.FIELD_DOCS,  # state, ranges, capacity
    ("owner:fk:User", "ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)"),
    ("venue:fk:Venue / fk:shop.Venue", 'ForeignKey("Venue") in the same app, or "app.Model"'),
    ("tags:m2m:Tag / profile:o2o:User", "ManyToManyField / OneToOneField"),
    ("name:type?", "optional: null=True, blank=True (strings and files: blank=True)"),
)

#: Fields BaseModel already declares, and names its methods/managers use.
RESERVED = frozenset(
    {
        "id",
        "pk",
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "objects",
        "all_objects",
        "is_deleted",
        "delete",
        "hard_delete",
        "restore",
        "save",
        "clean",
    }
)

ALIASES = {
    "string": "str",
    "char": "str",
    "integer": "int",
    "boolean": "bool",
    "choices": "choice",
    "foreignkey": "fk",
    "manytomany": "m2m",
    "onetoone": "o2o",
}

TYPES = (
    "str",
    "text",
    "int",
    "float",
    "decimal",
    "bool",
    "date",
    "datetime",
    "email",
    "url",
    "slug",
    "json",
    "file",
    "image",
    "uuid",
    "choice",
    *lifecycle_fields.TYPES,  # state, daterange, datetimerange, capacity
    "fk",
    "m2m",
    "o2o",
)

_STRINGISH = frozenset({"str", "text", "email", "url", "slug", "file", "image", "choice"})
_RELATIONS = {"fk": "ForeignKey", "o2o": "OneToOneField", "m2m": "ManyToManyField"}
_SIMPLE = {
    "text": "TextField",
    "int": "IntegerField",
    "float": "FloatField",
    "date": "DateField",
    "datetime": "DateTimeField",
}
_USER_NAMES = frozenset({"user", "auth.user", "settings.auth_user_model"})
_CHOICE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str
    args: tuple[str, ...]
    optional: bool

    @property
    def is_relation(self) -> bool:
        return self.kind in _RELATIONS

    @property
    def is_text(self) -> bool:
        """A plain string column usable as ``__str__`` / search field."""
        return self.kind in {"str", "slug", "email"}


@dataclass
class Rendered:
    """A model body: inner classes, field lines and the imports they need."""

    inner: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_field(token: str) -> FieldSpec:
    raw = token.strip()
    optional = raw.endswith("?")
    parts = raw.rstrip("?").split(":")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise CliError(
            f"Field {token!r}: expected name:type[:arg][?], e.g. title:str:200 or "
            "starts_at:datetime? (types: " + ", ".join(TYPES) + ").",
            code="C104",
        )
    name, kind, *args = parts
    kind = ALIASES.get(kind.lower(), kind.lower())
    if kind not in TYPES:
        raise CliError(
            f"Field {token!r}: unknown type {kind!r} (types: {', '.join(TYPES)}).", code="C104"
        )
    if not name.isidentifier() or keyword.iskeyword(name) or name != name.lower():
        raise CliError(f"Field {token!r}: {name!r} must be a snake_case identifier.", code="C104")
    if name.startswith("_") or "__" in name:
        raise CliError(
            f"Field {token!r}: names may not start with _ or contain __ (Django).", code="C104"
        )
    if name in RESERVED:
        raise CliError(
            f"Field {token!r}: {name!r} is reserved — BaseModel already provides it "
            "(id, created_at, updated_at, deleted_at, created_by, updated_by) or uses the name.",
            code="C104",
        )
    return FieldSpec(name, kind, tuple(args), optional)


def parse_fields(tokens: list[str]) -> list[FieldSpec]:
    specs = [parse_field(token) for token in tokens]
    seen: set[str] = set()
    for spec in specs:
        if spec.name in seen:
            raise CliError(f"Field {spec.name!r} is declared twice.", code="C104")
        seen.add(spec.name)
    return specs


def _int_arg(spec: FieldSpec, index: int, default: int, what: str) -> int:
    if len(spec.args) <= index or spec.args[index] == "":
        return default
    value = spec.args[index]
    if not value.isdigit() or int(value) <= 0:
        raise CliError(
            f"Field {spec.name}: {what} must be a positive integer, got {value!r}.", code="C104"
        )
    return int(value)


def _optional_kwargs(spec: FieldSpec) -> list[str]:
    if not spec.optional:
        return []
    if spec.kind in _STRINGISH:
        return ["blank=True"]
    return ["null=True", "blank=True"]


@dataclass(frozen=True)
class RelationTarget:
    """How a relation field refers to its target model."""

    expr: str
    is_user: bool
    key: str


def render_model_body(
    specs: list[FieldSpec],
    *,
    model: str,
    app_label: str,
    resolve: dict[str, RelationTarget],
    line_length: int,
) -> Rendered:
    """Field lines (indented four spaces) for ``model`` in ``app_label``.

    :param resolve: relation target per field name (``spec.args[0]`` resolved
        by the caller, which can see the project's models).
    """
    out = Rendered()
    indent = "    "
    targets = [resolve[s.name].key for s in specs if s.is_relation]
    for spec in specs:
        head = f"{spec.name} = models."
        if spec.kind in {"str", "email", "url", "slug"}:
            django = {"str": "CharField", "email": "EmailField", "url": "URLField"}.get(
                spec.kind, "SlugField"
            )
            args: list[str] = []
            if spec.kind == "str":
                args.append(f"max_length={_int_arg(spec, 0, 255, 'max_length')}")
            elif spec.args and spec.args[0]:
                args.append(f"max_length={_int_arg(spec, 0, 1, 'max_length')}")
            out.lines.append(
                call(head + django, args + _optional_kwargs(spec), indent, line_length)
            )
        elif spec.kind in _SIMPLE:
            out.lines.append(
                call(head + _SIMPLE[spec.kind], _optional_kwargs(spec), indent, line_length)
            )
        elif spec.kind == "decimal":
            digits = _int_arg(spec, 0, 10, "max_digits")
            places = _int_arg(spec, 1, 2, "decimal_places")
            if places > digits:
                raise CliError(
                    f"Field {spec.name}: decimal_places ({places}) > max_digits ({digits}).",
                    code="C104",
                )
            args = [f"max_digits={digits}", f"decimal_places={places}", *_optional_kwargs(spec)]
            out.lines.append(call(head + "DecimalField", args, indent, line_length))
        elif spec.kind == "bool":
            args = _optional_kwargs(spec) or ["default=False"]
            out.lines.append(call(head + "BooleanField", args, indent, line_length))
        elif spec.kind == "json":
            args = _optional_kwargs(spec) or ["default=dict"]
            out.lines.append(call(head + "JSONField", args, indent, line_length))
        elif spec.kind == "uuid":
            if spec.optional:
                args = _optional_kwargs(spec)
            else:
                args = ["default=uuid.uuid4"]
                out.imports.append(Import("uuid"))
            out.lines.append(call(head + "UUIDField", args, indent, line_length))
        elif spec.kind in {"file", "image"}:
            django = "FileField" if spec.kind == "file" else "ImageField"
            upload = pystr(f"{app_label}/{snake(model)}/")
            args = [f"upload_to={upload}", *_optional_kwargs(spec)]
            out.lines.append(call(head + django, args, indent, line_length))
            if spec.kind == "image":
                out.notes.append(
                    f"note: {model}.{spec.name} is an ImageField — the project needs Pillow "
                    "(pip install 'karni[images]')."
                )
        elif spec.kind == "choice":
            _render_choice(spec, out, indent, line_length)
        elif spec.kind in lifecycle_fields.TYPES:
            names = {s.name for s in specs}
            lifecycle_fields.render(spec, out, indent, line_length, model, names)
        else:
            target = resolve[spec.name]
            args = [target.expr]
            if spec.kind != "m2m":
                if spec.optional:
                    args += ["on_delete=models.SET_NULL", "null=True", "blank=True"]
                else:
                    args.append("on_delete=models.CASCADE")
            elif spec.optional:
                args.append("blank=True")
            if targets.count(target.key) > 1:
                args.append(f"related_name={pystr(snake(model) + '_' + spec.name + '_set')}")
            out.lines.append(call(head + _RELATIONS[spec.kind], args, indent, line_length))
            if target.is_user:
                out.imports.append(Import("django.conf", "settings"))
    if out.lines:
        out.imports.append(Import("django.db", "models"))
    return out


def _render_choice(spec: FieldSpec, out: Rendered, indent: str, line_length: int) -> None:
    raw = ":".join(spec.args)
    values = [v.strip() for v in re.split(r"[|,]", raw) if v.strip()]
    if not values:
        raise CliError(
            f"Field {spec.name}: choice needs values, e.g. '{spec.name}:choice:draft|published'.",
            code="C104",
        )
    members: list[tuple[str, str]] = []
    for value in values:
        if not _CHOICE_VALUE.match(value):
            raise CliError(
                f"Field {spec.name}: choice value {value!r} may only use letters, digits, - and _.",
                code="C104",
            )
        member = re.sub(r"[^A-Za-z0-9]", "_", value).upper()
        if member[0].isdigit():
            member = f"V_{member}"
        if member in {m for m, _ in members}:
            raise CliError(
                f"Field {spec.name}: choice value {value!r} is listed twice.", code="C104"
            )
        members.append((member, value))
    enum = pascal(spec.name)
    out.inner.append(f"{indent}class {enum}(models.TextChoices):")
    out.inner += [f"{indent}    {member} = {pystr(value)}" for member, value in members]
    length = max(20, *(len(value) for _, value in members))
    args = [f"max_length={length}", f"choices={enum}.choices"]
    args += _optional_kwargs(spec) or [f"default={enum}.{members[0][0]}"]
    out.lines.append(call(f"{spec.name} = models.CharField", args, indent, line_length))


def relation_name(spec: FieldSpec) -> str:
    """The raw target the user wrote for a relation field."""
    if not spec.args or not spec.args[0]:
        raise CliError(
            f"Field {spec.name}: {spec.kind} needs a target model, e.g. "
            f"'{spec.name}:{spec.kind}:User' or '{spec.name}:{spec.kind}:shop.Product'.",
            code="C104",
        )
    return spec.args[0]


def is_user_target(name: str) -> bool:
    return name.lower() in _USER_NAMES
