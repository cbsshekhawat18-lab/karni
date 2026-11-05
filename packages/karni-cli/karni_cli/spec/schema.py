"""Experimental. The ``karni.yaml`` format as Pydantic models, and its JSON Schema.

Each model is one level of the file and each attribute one key. The shape
checks (unknown keys, types, required keys) come from these models. What a
value means (a field type, a role an access rule names, an entity a page
names) is checked by :mod:`karni_cli.spec.validate`, which reads the same
models. :func:`json_schema` turns them into the JSON Schema published as
``docs/assets/karni-spec.schema.json``, which editors and agents use to
complete and check the file as it is typed.

Keys that start with ``x-`` are allowed everywhere and ignored: they are
removed before these models see the data, and the JSON Schema allows them
(``patternProperties``). A new optional key never changes what an old file
means, and ``version`` moves only for a breaking change.

Override / escape hatch: anything the format does not express stays in the
project's own code (``access: code`` for an access rule). The models are
plain Pydantic, so a tool can build a :class:`Spec` in code and validate it.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    WithJsonSchema,
)

from karni_cli.generators.fields import TYPES
from karni_cli.spec.catalog import MODULES, SOCIAL_PROVIDERS

__all__ = [
    "AGGREGATE_BUCKETS",
    "AGGREGATE_METRICS",
    "SCHEMA_URL",
    "UNCACHED_REASON",
    "VERSION",
    "Access",
    "Aggregate",
    "ApiCache",
    "App",
    "AppInfo",
    "Entity",
    "Features",
    "FieldEntry",
    "NavigationEntry",
    "NavigationOptions",
    "NavigationValue",
    "Role",
    "Spec",
    "Terms",
    "json_schema",
]

#: Experimental. The format version this release reads and writes.
VERSION: Final = 1
#: Experimental. Where the JSON Schema is published (the docs site serves docs/assets/).
SCHEMA_URL: Final = "https://cbsshekhawat18-lab.github.io/karni/assets/karni-spec.schema.json"

#: Experimental. The reason of the ``Uncached(reason=...)`` an entity's ``cache: false`` means.
UNCACHED_REASON: Final = "spec"

APP_LABEL: Final = r"[a-z][a-z0-9_]*"
ENTITY_NAME: Final = r"[A-Z][A-Za-z0-9]*"
FIELD_NAME: Final = r"[a-z][a-z0-9_]*"
ROLE_SLUG: Final = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
PAGE_NAME: Final = r"[a-z][a-z0-9-]*"
#: Experimental. The metrics ``aggregate.metrics`` takes: ``karni.aggregation.METRICS``.
AGGREGATE_METRICS: Final = ("count", "sum", "avg", "min", "max", "distinct_count")
#: Experimental. The date buckets a group takes after a colon: ``karni.aggregation.BUCKETS``.
AGGREGATE_BUCKETS: Final = ("year", "quarter", "month")


def _names(core: str) -> dict[str, Any]:
    """``propertyNames`` for a mapping keyed by names (``x-`` keys are allowed too)."""
    return {"propertyNames": {"pattern": f"^(?:x-.*|{core})$"}}


def _one_or_many(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


def _none_is_empty(value: Any) -> Any:
    return {} if value is None else value


_STRING_OR_LIST: Final = {
    "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
}

#: One name or a list of names: ``search: name`` or ``search: [name, city]``.
Names = Annotated[list[str], BeforeValidator(_one_or_many), WithJsonSchema(_STRING_OR_LIST)]


class _Node(BaseModel):
    """One mapping of the file: unknown keys are errors, values are never coerced."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={"patternProperties": {"^x-": {}}},
    )


class AppInfo(_Node):
    """Experimental. ``app:``: what the project is."""

    name: str = Field(description="The project's name, as given to karni new.")
    kind: Literal["site", "app", "site+app"] = Field(
        "app", description="The project's kind, as karni new --kind: site, app or site+app."
    )
    recipe: str | None = Field(
        None, description="The recipe the spec started from. For the record only."
    )


class Terms(_Node):
    """Experimental. ``features.terms``: ``KARNI_TERMS``."""

    version: str = Field(description="The current terms version, e.g. 2026-11.")
    url: str = Field(description="Where the terms are, e.g. /terms/.")
    required: bool = Field(True, description="False keeps the routes and gates nothing.")
    paths: list[str] | None = Field(
        None, description='URL prefixes the gate covers (default ["/api/"]).'
    )
    exempt: list[str] | None = Field(None, description="URL prefixes the gate leaves open.")


class ApiCache(_Node):
    """Experimental. ``features.api_cache`` as a mapping: on, with its lifetime."""

    ttl: int = Field(
        description="KARNI_API_CACHE_TTL: the seconds a cached response lives (default 300)."
    )


def _api_cache_member(value: Any) -> str:
    return "=bool" if isinstance(value, bool) else "=ttl"


ApiCacheValue = Annotated[
    Annotated[bool, Tag("=bool")] | Annotated[ApiCache, Tag("=ttl")],
    Discriminator(_api_cache_member),
]


def _cache_member(value: Any) -> str:
    return "=bool" if isinstance(value, bool) else "=ttl"


#: An entity's ``cache:``: a lifetime in seconds, or ``false`` (never cached).
CacheValue = Annotated[
    Annotated[bool, Tag("=bool")] | Annotated[int, Tag("=ttl")],
    Discriminator(_cache_member),
]


class Features(_Node):
    """Experimental. ``features:``: built-in options, each switched by a setting."""

    two_factor: bool = Field(False, description="KARNI_2FA. Needs karni[2fa].")
    email_code_login: bool = Field(False, description="KARNI_EMAIL_OTP: sign-in with a code.")
    social_login: Names = Field(
        default_factory=list,
        description=(
            "KARNI_SOCIAL_TOKEN_PROVIDERS: the providers, of "
            + ", ".join(SOCIAL_PROVIDERS)
            + ". Their client ids stay in settings or .env. Needs karni[social-token]."
        ),
    )
    terms: Terms | None = Field(None, description="KARNI_TERMS: the terms acceptance gate.")
    user_grants: bool = Field(
        False, description="KARNI_USER_GRANTS: per-user grants next to the role grants."
    )
    api_cache: ApiCacheValue = Field(
        False,
        description=(
            "KARNI_API_CACHE: cached list and detail responses, invalidated on every write. "
            "true, or {ttl: <seconds>} to set KARNI_API_CACHE_TTL too."
        ),
    )


class Role(_Node):
    """Experimental. One role of ``roles:``: an entry of ``KARNI_ROLES``."""

    name: str | None = Field(None, description="The role's name (default: from the slug).")
    description: str = Field("", description="What the role is for.")
    system: bool = Field(False, description="A system role cannot be deleted in the admin.")
    default: bool = Field(
        False, description="Every self-registered user gets it (KARNI_ACCOUNTS_DEFAULT_ROLES)."
    )
    grants: dict[str, str] = Field(
        default_factory=dict,
        description=(
            'Permission pattern -> scope. Patterns: "*", app.entity, app.entity:action, with * '
            "for a part. Scopes: all, own, own:<owner field>, related:<scope path key>, "
            "custom:<registered name>, tree:<path to a tree entity> (experimental)."
        ),
    )


def _access_member(value: Any) -> str:
    return "=code" if isinstance(value, str) else "=rule"


class Access(_Node):
    """Experimental. ``access:`` of an entity: the viewset's ``Access(...)``.

    Each slot takes ``public``, ``authenticated``, ``granted``,
    ``role:<slug>``, ``owned:<field>``, or a list of them (any of them
    admits). ``read`` and ``write`` default to ``granted``, ``create`` to
    ``write``.
    """

    read: Names = Field(
        default_factory=lambda: ["granted"], description="Who sees which rows (list, detail)."
    )
    write: Names = Field(
        default_factory=lambda: ["granted"],
        description="Who changes and deletes which rows.",
    )
    create: Names | None = Field(None, description="Who creates rows (default: write).")


AccessValue = Annotated[
    Annotated[Literal["code"], Tag("=code")] | Annotated[Access, Tag("=rule")],
    Discriminator(_access_member),
]


def _audit_member(value: Any) -> str:
    return "=bool" if isinstance(value, bool) else "=list"


AuditValue = Annotated[
    Annotated[bool, Tag("=bool")] | Annotated[list[str], Tag("=list")],
    Discriminator(_audit_member),
]


def _tree_member(value: Any) -> str:
    return "=bool" if isinstance(value, bool) else "=kind"


#: Experimental. ``tree:`` of an entity: ``true`` (TreeModel), ``ordered`` or ``false``.
TreeValue = Annotated[
    Annotated[bool, Tag("=bool")] | Annotated[Literal["ordered"], Tag("=kind")],
    Discriminator(_tree_member),
]


class FieldEntry(_Node):
    """Experimental. A field written as a mapping, to say what it was called before.

    ``title: {type: "str:200", was: name}`` is the field ``title`` of type
    ``str:200``, which ``karni plan`` and ``karni build`` treat as the field
    ``name`` renamed: the column keeps its rows.
    """

    type: str = Field(description="The field's type, as in the short form (str:200, fk:Studio).")
    was: str | None = Field(
        None, description="The field's old name: a rename that keeps the column and its rows."
    )


def _field_member(value: Any) -> str:
    return "=type" if isinstance(value, str) else "=entry"


FieldValue = Annotated[
    Annotated[str, Tag("=type")] | Annotated[FieldEntry, Tag("=entry")],
    Discriminator(_field_member),
]


class Aggregate(_Node):
    """Experimental. ``aggregate:`` of an entity: ``class Karni: aggregate``.

    What ``GET <resource>/aggregate/`` may group by and sum (docs/aggregations.md).
    Expressions (``TextNumber`` and your own) stay in the project's code.
    """

    group_by: Names = Field(
        description=(
            "Fields or relation paths (category__parent) a request may group by. A date or "
            "datetime field takes :year, :quarter or :month, or allows every bucket without one."
        )
    )
    values: Names = Field(
        default_factory=list, description="Fields a metric other than a plain count reads."
    )
    metrics: Names | None = Field(
        None,
        description=(
            "The metrics a request may name, of "
            + ", ".join(AGGREGATE_METRICS)
            + " (default: all of them)."
        ),
    )


class Entity(_Node):
    """Experimental. One entity: a model on BaseModel or BigIntBaseModel, its viewset and options."""

    fields: dict[str, FieldValue] = Field(
        default_factory=dict,
        description=(
            "Field name -> type, in karni make model's syntax (types: "
            + " ".join(TYPES)
            + "), a trailing ? for optional. Or {type, was} to rename a field and keep its rows."
        ),
        json_schema_extra=_names(FIELD_NAME),
    )
    was: str | None = Field(
        None,
        description="The entity's old name in the same app: a rename that keeps the table's rows.",
    )
    pk: Literal["uuid", "bigint"] | None = Field(
        None,
        description=(
            "The key type: uuid (BaseModel) or bigint (BigIntBaseModel). Default: the "
            "project's KARNI_PK."
        ),
    )
    external: bool = Field(
        False,
        description=(
            "A table or view another system owns: Meta.managed = False and class Karni: "
            "external = True. No migration changes it, and it is read-only unless writable."
        ),
    )
    table: str | None = Field(
        None, description="With external: the table or view, as [schema.]table (Meta.db_table)."
    )
    writable: bool = Field(
        False, description="With external: the API and the admin may write it (Karni.writable)."
    )
    database: str | None = Field(
        None,
        description=(
            "The DATABASES alias its reads, writes and migrations go to (Karni.database). "
            "Default: default."
        ),
    )
    tree: TreeValue = Field(
        False,
        description=(
            "Experimental. A hierarchy: true inherits TreeModel (a parent field and the tree "
            "endpoints), ordered inherits OrderedTreeModel (also a position among siblings)."
        ),
    )
    taxonomies: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Experimental. Tag the entity to tree entities: key -> tree entity (Name or "
            "app.Name). Each key is a many-to-many of that name, with the list filters "
            "?<key>= and ?<key>_descendants=, the facets/ counts and the tree:<key> scope "
            "(class Karni: taxonomies)."
        ),
        json_schema_extra=_names(FIELD_NAME),
    )
    key: str | None = Field(
        None, description="The natural key imports match rows on (Karni.import_key)."
    )
    search: Names = Field(default_factory=list, description="The viewset's search_fields.")
    owner: str | None = Field(
        None, description="The owner field the own scope uses (Karni.owner_field)."
    )
    audit: AuditValue = Field(
        False, description="Change history (Karni.audit): true, or a list of fields."
    )
    groups: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Field groups: title -> fields (the admin form's fieldsets).",
    )
    order: Names = Field(
        default_factory=list, description="Default ordering (Meta.ordering), - for descending."
    )
    scope_paths: dict[str, str] = Field(
        default_factory=dict,
        description="Keys the related:<key> scope uses -> lookup path (Karni.scope_paths).",
    )
    access: AccessValue = Field(
        default_factory=lambda: Access.model_validate({}),
        description="Who reads and writes: a mapping {read, write, create}, or code.",
    )
    aggregate: Aggregate | None = Field(
        None,
        description=(
            "What GET <resource>/aggregate/ may group by and sum (Karni.aggregate): group_by, "
            "values, metrics."
        ),
    )
    cache: CacheValue | None = Field(
        None,
        description=(
            "The viewset's response caching: a lifetime in seconds (Cache(ttl=...)), or false "
            '(Uncached(reason="spec")). Default: KARNI_API_CACHE and KARNI_API_CACHE_TTL.'
        ),
    )

    def tokens(self) -> dict[str, str]:
        """Experimental. Field name -> type, for both forms of a field."""
        return {
            name: value if isinstance(value, str) else value.type
            for name, value in self.fields.items()
        }

    def renamed(self) -> dict[str, str]:
        """Experimental. New field name -> old name, for the fields written with ``was``."""
        return {
            name: value.was
            for name, value in self.fields.items()
            if isinstance(value, FieldEntry) and value.was is not None
        }


class App(_Node):
    """Experimental. One Django app of ``apps:`` and its entities."""

    entities: dict[str, Entity] = Field(
        default_factory=dict,
        description="Entity name (PascalCase) -> entity.",
        json_schema_extra=_names(ENTITY_NAME),
    )


ModuleOptions = Annotated[
    dict[str, Any],
    BeforeValidator(_none_is_empty),
    WithJsonSchema({"anyOf": [{"type": "object"}, {"type": "null"}]}),
]


class NavigationOptions(_Node):
    """Experimental. A ``navigation:`` entry written as a mapping's value: a page's or a group's options.

    A page takes ``label``, ``icon`` and ``requires``. A group takes
    ``items`` (its entries), ``icon`` and ``requires``.
    """

    label: str | None = Field(None, description="A page's label in the menu (default: its title).")
    icon: str | None = Field(None, description="An icon name the frontend knows, e.g. home.")
    requires: str | None = Field(
        None,
        description=(
            "public, authenticated or a permission pattern (app.entity:action). Default: from "
            "the page's access, and for a group public when one of its entries is."
        ),
    )
    items: list[NavigationEntry] | None = Field(None, description="A group's entries.")


def _navigation_member(value: Any) -> str:
    return "=page" if isinstance(value, str) else "=entry"


def _navigation_value(value: Any) -> str:
    return "=items" if isinstance(value, list) else "=options"


def _navigation_switch(value: Any) -> str:
    return "=bool" if isinstance(value, bool) else "=list"


#: Experimental. One ``navigation:`` entry: a page's key, or a one-key mapping to a page's
#: options or to a group's entries.
type NavigationEntry = Annotated[
    Annotated[str, Tag("=page")]
    | Annotated[
        dict[
            str,
            Annotated[
                Annotated[list[NavigationEntry], Tag("=items")]
                | Annotated[NavigationOptions, Tag("=options")],
                Discriminator(_navigation_value),
            ],
        ],
        Tag("=entry"),
    ],
    Discriminator(_navigation_member),
]

#: Experimental. ``navigation:``: ``true`` (every page, in order) or a list of entries.
NavigationValue = Annotated[
    Annotated[bool, Tag("=bool")] | Annotated[list[NavigationEntry], Tag("=list")],
    Discriminator(_navigation_switch),
]


class Spec(_Node):
    """Experimental. A whole ``karni.yaml``."""

    version: Literal[1] = Field(description="The format version: 1.")
    app: AppInfo = Field(description="What the project is.")
    modules: dict[str, ModuleOptions] = Field(
        default_factory=dict,
        description="karni add <name>, with the module's options (its KARNI_<MODULE>_* settings).",
        json_schema_extra={
            "propertyNames": {"anyOf": [{"enum": [*sorted(MODULES)]}, {"pattern": "^x-"}]}
        },
    )
    features: Features = Field(
        default_factory=lambda: Features.model_validate({}), description="Built-in options."
    )
    roles: dict[str, Role] = Field(
        default_factory=dict,
        description="KARNI_ROLES: slug -> role.",
        json_schema_extra=_names(ROLE_SLUG),
    )
    apps: dict[str, App] = Field(
        default_factory=dict,
        description="App label -> app.",
        json_schema_extra=_names(APP_LABEL),
    )
    pages: list[dict[str, Names]] = Field(
        default_factory=list,
        description=(
            "karni make page, in navigation order. Each item is one key: an entity with its "
            "pages (list, detail, form), or a page name with its kind (dashboard, blank, login, "
            "or code: a page of the project's own at /<name>, which karni build leaves alone)."
        ),
    )
    navigation: NavigationValue = Field(
        False,
        description=(
            "Experimental. The menu karni build writes to KARNI_NAVIGATION: true for every page "
            "of pages in their order, or a list of pages (by their key) and groups "
            "({label: [entries]}), each page with optional {label, icon, requires}."
        ),
    )
    seed: dict[str, int] = Field(
        default_factory=dict,
        description="Entity -> demo rows per karni seed run (a Seeder's Meta.count).",
        json_schema_extra=_names(ENTITY_NAME),
    )


def _tidy(node: Any, *, names: bool = False) -> Any:
    """Drop Pydantic's generated titles and ``null`` defaults (noise for an editor).

    ``names``: ``node`` maps property names to schemas, so a property named
    ``title`` or ``default`` stays.
    """
    if isinstance(node, dict):
        cleaned = {
            key: _tidy(value, names=key == "properties" and not names)
            for key, value in node.items()
            if names or (key != "title" and not (key == "default" and value is None))
        }
        return cleaned
    if isinstance(node, list):
        return [_tidy(item) for item in node]
    return node


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``karni.yaml``, as published at :data:`SCHEMA_URL`."""
    schema = _tidy(Spec.model_json_schema())
    # Each page entry is one key: an entity with its pages, or a page name with its kind.
    schema["properties"]["pages"]["items"] |= {"minProperties": 1, "maxProperties": 1}
    # So is each navigation entry written as a mapping: a page with its options, or a group.
    schema["$defs"]["NavigationEntry"]["oneOf"][1] |= {"minProperties": 1, "maxProperties": 1}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_URL,
        "title": "karni.yaml",
        "description": (
            "Experimental. A Karni app spec: what karni make, karni add and the settings "
            "build. Generated by python -m karni_cli.spec.schema. Never edit it by hand."
        ),
        **schema,
    }


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.spec.schema
    import json

    print(json.dumps(json_schema(), indent=2, sort_keys=False))
