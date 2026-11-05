"""Experimental. ``karni plan``: what ``karni build`` would change, from a spec and the project.

The plan compares two specs in the normal form of :mod:`karni_cli.spec.normal`:
the spec written in ``karni.yaml``, and the spec the project has now, which
:func:`karni_cli.spec.export.build` reads from ``manage.py karni_facts`` as
``karni spec export`` does. Each difference is one :class:`Change`: its
area, its action (``add``, ``change``, ``rename`` or ``remove``), its
target and what changes. Nothing is written.

A change is **risky** when it can lose data or open it to more people:
a field or an entity removed, a field's type changed (a shorter length, a
field that becomes required, a choice or state dropped, another kind), a
relation pointed at another entity, a module removed, an entity's key type
switched (out of scope for ``karni build``), an entity moved to another
database, an entity made a tree or flat again or its siblings' order dropped
(``tree``, experimental), a taxonomy removed or pointed at another tree (its
tags go, experimental), and access widened (writes from a role to every signed-in user or
to everyone, reads to everyone, a role's grant from its own rows to all).
``karni build`` (app-builder item A3) refuses them without
``--allow-destructive``. Each risky change names the rows it affects, as a
:class:`Count` that ``manage.py karni_rows`` answers when the database is
reachable (:func:`apply_counts`).

Renames: a field or an entity written with ``was: <old name>`` is renamed,
keeping its rows. A field removed and a field of the same type added to one
entity, without ``was``, is shown as a removal with the hint that it is
probably a rename.

Ownership: given :class:`Managed` (what ``.karni/build.json`` records),
each change is marked ``managed`` or not. ``karni build`` writes Karni's code
in files of its own (:mod:`karni_cli.builder.layout`), and a change on code the
project wrote by hand (a model, a viewset, a page, a module to remove) is not
managed: ``karni build`` leaves it to the project. ``access: code`` means
the project's viewset decides, so it matches any access the project has.

``--json`` prints :meth:`Plan.as_dict`, whose JSON Schema is
:func:`json_schema` (published as ``docs/assets/karni-plan.schema.json``).

Override / escape hatch: :func:`plan_project` takes the spec and the facts,
so a tool with facts of its own plans without a project interpreter, and
:func:`apply_counts` takes any counter (a callable from requests to counts).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from karni_cli import project as project_mod
from karni_cli.builder import layout
from karni_cli.generators.fields import is_user_target
from karni_cli.project import CliError
from karni_cli.spec import export, navigation, schema
from karni_cli.spec.catalog import DEFAULT_CACHE_TTL, MODULES, module_setting
from karni_cli.spec.normal import normalise, role_name
from karni_cli.spec.validate import validate_text

__all__ = [
    "ACTIONS",
    "AREAS",
    "PLAN_SCHEMA_URL",
    "PLAN_VERSION",
    "Change",
    "Count",
    "Managed",
    "Plan",
    "apply_counts",
    "json_schema",
    "manage_counter",
    "plan_project",
]

#: Experimental. The version of the ``--json`` output. It moves only for a breaking change.
PLAN_VERSION: Final = 1
#: Experimental. Where the JSON Schema of ``karni plan --json`` is published.
PLAN_SCHEMA_URL: Final = "https://cbsshekhawat18-lab.github.io/karni/assets/karni-plan.schema.json"
Area = Literal[
    "app",
    "modules",
    "features",
    "roles",
    "apps",
    "entities",
    "fields",
    "access",
    "pages",
    "migrations",
    "seed",
    "tests",
]
#: Experimental. The areas of a plan, in the order it lists them.
AREAS: Final[tuple[str, ...]] = get_args(Area)
#: Experimental. What a change does, and its mark in the text output.
ACTIONS: Final = {"add": "+", "change": "~", "rename": "~", "remove": "-"}
RowStatus = Literal["counted", "offline", "unreachable", "not needed"]
#: Experimental. The target of the menu's change in the pages area: the setting it writes.
MENU: Final = "KARNI_NAVIGATION"

_RELATIONS: Final = ("fk", "o2o", "m2m")
#: Field kinds whose length argument a shorter value must fit, with the default length.
_LENGTHS: Final = {"str": 255, "url": 200, "slug": 50}
_FEATURE_SETTINGS: Final = {
    "two_factor": "KARNI_2FA",
    "email_code_login": "KARNI_EMAIL_OTP",
    "social_login": "KARNI_SOCIAL_TOKEN_PROVIDERS",
    "terms": "KARNI_TERMS",
    "user_grants": "KARNI_USER_GRANTS",
    "api_cache": "KARNI_API_CACHE",
}
#: A text column becoming a markdown one, or back: the same column, only its rendering changes.
_TEXT_SWAPS: Final = frozenset({("text", "markdown"), ("markdown", "text")})
#: Entity options whose change writes a migration (the others live in class Karni or the viewset).
_MIGRATED: Final = frozenset({"order", "pk", "external", "table", "database", "tree", "taxonomies"})
_OPTIONS: Final = (
    "pk",
    "external",
    "table",
    "writable",
    "database",
    "tree",
    "taxonomies",
    "key",
    "search",
    "owner",
    "audit",
    "global_search",
    "groups",
    "column_sets",
    "order",
    "scope_paths",
    "aggregate",
    "cache",
)


@dataclass(frozen=True)
class Count:
    """Experimental. Rows to count for a risky change: a request to ``manage.py karni_rows``.

    ``kind`` is one of :data:`karni.facts.COUNT_KINDS`: ``all``, ``set``,
    ``empty``, ``longer`` (``arg``: the length) or ``in`` (``arg``: values).
    """

    model: str
    field: str | None = None
    kind: str = "all"
    arg: Any = None

    def request(self) -> dict[str, Any]:
        out: dict[str, Any] = {"model": self.model}
        if self.field is not None:
            out |= {"field": self.field, "kind": self.kind}
        if self.arg is not None:
            out["arg"] = list(self.arg) if isinstance(self.arg, tuple) else self.arg
        return out


@dataclass
class Change:
    """Experimental. One change of a plan (see the module docstring)."""

    area: str
    action: str
    target: str
    detail: str = ""
    risky: bool = False
    reason: str | None = None
    rows: int | None = None
    #: What :func:`apply_counts` counts for ``rows`` (summed). Empty: no count.
    counts: tuple[Count, ...] = ()
    #: Whether the counts were asked for and answered (``rows`` may still be unknown).
    counted: bool = False
    #: ``False``: the project's own code holds it, and karni build leaves it (see :class:`Managed`).
    managed: bool = True

    def line(self) -> str:
        """The change as one line of the text output."""
        text = f"{'! ' if self.risky else '  '}{ACTIONS[self.action]} {self.target}"
        if self.detail:
            text += f": {self.detail}"
        if self.reason:
            text += f", {self.reason}"
        if self.counted and self.counts:
            text += f" ({self.rows} rows)" if self.rows is not None else " (rows unknown)"
        if not self.managed:
            text += " (not managed)"
        return text

    def as_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "action": self.action,
            "target": self.target,
            "detail": self.detail,
            "risky": self.risky,
            "reason": self.reason,
            "rows": self.rows,
            "managed": self.managed,
        }


@dataclass(frozen=True)
class Managed:
    """Experimental. What karni build manages in a project, as ``.karni/build.json`` records it.

    ``entities`` are the ``app.Entity`` labels whose code Karni writes,
    ``pages`` the pages it writes (``app.Entity:list``, ``about:blank``) and
    ``adopted`` the Karni-owned files and blocks handed to the project with
    ``karni build --adopt``. A change on anything else that already exists is
    not managed. Something new (an entity, a page, a module) is managed.
    """

    entities: frozenset[str] = frozenset()
    pages: frozenset[str] = frozenset()
    adopted: frozenset[str] = frozenset()


@dataclass
class Plan:
    """Experimental. What ``karni build`` would change, and how the row counts went."""

    file: str
    changes: list[Change] = field(default_factory=list)
    row_counts: RowStatus = "not needed"
    #: Why the counts are missing (offline, a database that did not answer).
    note: str | None = None
    #: Both sides in normal form, and the renames, for karni build (not in the JSON output).
    current: dict[str, Any] = field(default_factory=dict, repr=False)
    desired: dict[str, Any] = field(default_factory=dict, repr=False)
    #: new ``app.Entity`` -> old, for the entities renamed with ``was:``.
    entity_renames: dict[str, str] = field(default_factory=dict, repr=False)
    #: (new ``app.Entity``, new field) -> old field, for the fields renamed with ``was:``.
    field_renames: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    @property
    def risky(self) -> list[Change]:
        return [change for change in self.changes if change.risky]

    @property
    def not_managed(self) -> list[Change]:
        return [change for change in self.changes if not change.managed]

    def summary(self) -> str:
        total, risky, left = len(self.changes), len(self.risky), len(self.not_managed)
        text = f"{total} change{'s' if total != 1 else ''}, {risky} risky"
        return text + (f", {left} not managed." if left else ".")

    def text(self) -> str:
        """The plan as the terminal shows it: one line per change, grouped by area."""
        if not self.changes:
            return f"No changes: the project matches {self.file}.\n"
        lines: list[str] = []
        for area in AREAS:
            found = [change for change in self.changes if change.area == area]
            if found:
                lines += [area, *(change.line() for change in found)]
        lines.append(self.summary())
        if self.not_managed:
            lines.append(
                "karni build leaves the changes marked not managed to the project's own code."
            )
        if self.risky:
            if self.note:
                lines.append(f"Row counts skipped: {self.note}.")
            lines.append("karni build refuses the risky (!) changes without --allow-destructive.")
        return "\n".join(lines) + "\n"

    def as_dict(self) -> dict[str, Any]:
        """The ``--json`` output (its schema: :func:`json_schema`)."""
        return {
            "version": PLAN_VERSION,
            "file": self.file,
            "valid": True,
            "issues": [],
            "changes": [change.as_dict() for change in self.changes],
            "summary": {
                "changes": len(self.changes),
                "risky": len(self.risky),
                "not_managed": len(self.not_managed),
            },
            "row_counts": {"status": self.row_counts, "note": self.note},
        }


# the JSON output's schema ---------------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _IssueOut(_Out):
    """A problem in the spec, as karni spec validate --json reports it."""

    code: str = Field(description="The error code (karni explain <code>).")
    line: int | None = Field(description="The 1-based line, when known.")
    path: str = Field(description="The dotted path of the key.")
    message: str = Field(description="What is wrong.")
    fix: str = Field(description="How to fix it.")


class _ChangeOut(_Out):
    """One change karni build would make."""

    area: Area = Field(description="Where the change is: " + ", ".join(AREAS) + ".")
    action: Literal["add", "change", "rename", "remove"] = Field(description="What it does.")
    target: str = Field(
        description="What it changes: a module, a role, app.Entity, app.Entity.field, ..."
    )
    detail: str = Field(description="The new value, or old -> new. Empty when nothing to add.")
    risky: bool = Field(
        description="It can lose data or open it to more people: karni build refuses it "
        "without --allow-destructive."
    )
    reason: str | None = Field(description="Why it is risky, or a note. null when none.")
    rows: int | None = Field(
        description="The rows it affects, when the database was counted. null when not counted."
    )
    managed: bool = Field(
        description="false: the project's own code holds it (a hand-written model, viewset or "
        "page, a module to remove), and karni build leaves it to the project."
    )


class _SummaryOut(_Out):
    changes: int = Field(description="How many changes.")
    risky: int = Field(description="How many of them are risky.")
    not_managed: int = Field(description="How many of them karni build leaves to the project.")


class _RowCountsOut(_Out):
    status: Literal["counted", "offline", "unreachable", "not needed"] = Field(
        description="counted, offline (--offline), unreachable (a database did not answer), "
        "or not needed (no risky change to count)."
    )
    note: str | None = Field(description="Why counts are missing. null when none.")


class _PlanOut(_Out):
    """Experimental. The output of karni plan --json."""

    version: Literal[1] = Field(description="The version of this output: 1.")
    file: str = Field(description="The spec file, as given.")
    valid: bool = Field(description="false when the spec has problems: then issues lists them.")
    issues: list[_IssueOut] = Field(description="The spec's problems (karni spec validate's).")
    changes: list[_ChangeOut] = Field(description="The changes, grouped by area in plan order.")
    summary: _SummaryOut
    row_counts: _RowCountsOut


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``karni plan --json``, as published at :data:`PLAN_SCHEMA_URL`."""
    from karni_cli.spec.schema import _tidy

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": PLAN_SCHEMA_URL,
        "title": "karni plan --json",
        "description": (
            "Experimental. What karni build would change. Generated by python -m "
            "karni_cli.spec.plan. Never edit it by hand."
        ),
        **_tidy(_PlanOut.model_json_schema()),
    }


def checked_output(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` checked against the published schema's models (raises when they disagree)."""
    return _PlanOut.model_validate(data).model_dump(mode="json")


def invalid_output(file: str, issues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The ``--json`` output for a spec with problems."""
    return checked_output(
        {
            "version": PLAN_VERSION,
            "file": file,
            "valid": False,
            "issues": list(issues),
            "changes": [],
            "summary": {"changes": 0, "risky": 0, "not_managed": 0},
            "row_counts": {"status": "not needed", "note": None},
        }
    )


# reading both sides ---------------------------------------------------------------


def _current_spec(facts: dict[str, Any], root: Path) -> schema.Spec:
    """The project's spec, as karni spec export reads it, with its roles always written."""
    exported = export.build(facts, root)
    data = dict(exported.data)
    if "roles" not in data:  # the export leaves the shipped roles out: the plan compares them
        settings = facts["settings"]
        roles = export.roles_of(
            facts,
            settings.get("KARNI_ROLES") or {},
            settings.get("KARNI_ACCOUNTS_DEFAULT_ROLES") or [],
            data.get("apps", {}),
        )
        if roles:
            data["roles"] = roles
    report = validate_text(export.Exported(data).text(), databases=facts.get("databases"))
    if report.spec is None or not report.ok:
        first = report.issues[0].render("the project's spec") if report.issues else "no spec"
        raise CliError(
            f"karni plan cannot read the project: its exported spec does not validate ({first}).",
            code="C250",
        )
    return report.spec


def _with_shipped_roles(spec: schema.Spec, facts: dict[str, Any]) -> schema.Spec:
    """A spec without roles has Karni's shipped roles: write them out to compare."""
    if spec.roles:
        return spec
    apps = {label: {"entities": dict(app.entities)} for label, app in spec.apps.items()}
    shipped = export.roles_of(facts, facts.get("shipped_roles") or {}, [], apps)
    roles = {slug: schema.Role.model_validate(role) for slug, role in shipped.items()}
    return spec.model_copy(update={"roles": roles})


def _entities(norm: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        f"{app}.{name}": entity
        for app, application in norm["apps"].items()
        for name, entity in application["entities"].items()
    }


def _resolver(labels: Iterable[str]) -> Callable[[str, str], str]:
    """``(ref, app) -> label`` for a reference to an entity (``Name`` or ``app.Name``)."""
    labels = list(labels)
    by_name: dict[str, list[str]] = {}
    for label in labels:
        by_name.setdefault(label.split(".", 1)[1], []).append(label)

    def resolve(ref: str, app: str = "") -> str:
        if "." in ref:
            return ref
        if f"{app}.{ref}" in labels:
            return f"{app}.{ref}"
        found = by_name.get(ref, [])
        return found[0] if len(found) == 1 else ref

    return resolve


def _target(token: str, label: str, resolve: Callable[[str, str], str]) -> str | None:
    """The label a relation token points at, ``User`` for the user, ``None`` for a non-relation."""
    kind, _, rest = token.rstrip("?").partition(":")
    if kind not in _RELATIONS:
        return None
    app, _, name = label.partition(".")
    if is_user_target(rest):
        return "User"
    if rest in ("self", name):
        return label
    return resolve(rest, app)


# comparing ------------------------------------------------------------------------


def _search_text(value: Any) -> str:
    """``global_search`` (normal form) in one phrase: its fields, then what is not a default."""
    if not isinstance(value, dict):
        return _show(value)
    fields = list(value.get("fields") or [])
    extra = []
    if value.get("title") not in (None, fields[0] if fields else None):
        extra.append(f"title {value['title']}")
    if value.get("subtitle"):
        extra.append(f"subtitle {value['subtitle']}")
    if value.get("weight", 1) != 1:
        extra.append(f"weight {value['weight']:g}")
    return (", ".join(fields) or "none") + (f" ({', '.join(extra)})" if extra else "")


def _show(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(_show(item) for item in value) or "none"
    if isinstance(value, dict):
        return ", ".join(f"{key} {_show(item)}" for key, item in value.items()) or "none"
    return str(value)


def _aggregate_text(value: Any) -> str:
    """``by category, launched_on:year of price (count, sum)``: an aggregate in one line."""
    if not value:
        return "none"
    text = "by " + ", ".join(value["group_by"])
    if value["values"]:
        text += " of " + ", ".join(value["values"])
    if set(value["metrics"]) != set(schema.AGGREGATE_METRICS):
        text += " (" + ", ".join(value["metrics"]) + ")"
    return text


def _rule(access: Any) -> str:
    if access == "code":
        return "code"
    parts = [f"read {' | '.join(access['read'])}", f"write {' | '.join(access['write'])}"]
    if "create" in access:
        parts.append(f"create {' | '.join(access['create'])}")
    return ", ".join(parts)


def _openness(items: list[str] | None) -> int:
    """3 for public, 2 for authenticated, 1 for anything narrower (or code: unknown)."""
    levels = {"public": 3, "authenticated": 2}
    return max((levels.get(item, 1) for item in items or ()), default=1)


def _widened(old: Any, new: Any) -> str | None:
    """Why ``new`` access opens rows ``old`` kept closed, else ``None``."""
    if new == "code":
        return None
    old_rule = old if old != "code" else {"read": [], "write": []}
    if _openness(new["read"]) == 3 and _openness(old_rule["read"]) < 3:
        return "reads open to everyone, signed in or not"
    for slot in ("write", "create"):
        before = _openness(old_rule.get(slot, old_rule["write"]))
        after = _openness(new.get(slot, new["write"]))
        if after > before and after >= 2:
            who = "everyone" if after == 3 else "every signed-in user"
            return f"{'writes' if slot == 'write' else 'creates'} open to {who}"
    return None


@dataclass
class _Field:
    kind: str
    args: list[str]
    optional: bool

    @classmethod
    def parse(cls, token: str) -> _Field:
        optional = token.endswith("?")
        kind, *args = token.rstrip("?").split(":")
        return cls(kind, args, optional)


def _values(spec: _Field) -> set[str]:
    raw = spec.args[0] if spec.args else ""
    if spec.kind == "choice":
        return set(raw.split("|"))
    return {state for move in raw.split("|") for state in move.split(">")}


def _length(spec: _Field) -> int | None:
    """The length a ``str``, ``url`` or ``slug`` value must fit (``None``: a slug's source)."""
    if not spec.args:
        return _LENGTHS[spec.kind]
    return int(spec.args[0]) if spec.args[0].isdigit() else None


def _field_risk(
    old: str, new: str, old_target: str | None, new_target: str | None
) -> tuple[str | None, str, Any]:
    """``(reason, count kind, count arg)`` for a changed field. ``reason`` ``None``: not risky."""
    a, b = _Field.parse(old), _Field.parse(new)
    if a.kind != b.kind:
        if (a.kind, b.kind) in (("str", "text"), ("str", "markdown")):
            return None, "set", None
        if (a.kind, b.kind) not in _TEXT_SWAPS:
            return f"its type changes from {a.kind} to {b.kind}", "set", None
    if a.kind in _RELATIONS and old_target != new_target:
        return f"it points at {new_target} instead of {old_target}", "set", None
    if a.kind in _LENGTHS:
        before, after = _length(a), _length(b)
        if before is not None and after is not None and after < before:
            return f"values longer than {after} do not fit", "longer", after
    if a.kind in ("choice", "state"):
        dropped = sorted(_values(a) - _values(b))
        if dropped:
            return f"{', '.join(dropped)} is no longer a value", "in", tuple(dropped)
    if a.kind == "decimal":
        digits = [int(x) for x in a.args] if a.args else [10, 2]
        changed = [int(x) for x in b.args] if b.args else [10, 2]
        if changed[0] < digits[0] or changed[1] != digits[1]:
            return "its digits change", "set", None
    if a.kind in ("money", "array") and a.args != b.args:
        return f"its {'currency' if a.kind == 'money' else 'items'} change", "set", None
    if a.kind == "email" and "unique" in b.args and "unique" not in a.args:
        return "it becomes unique", "set", None
    if a.optional and not b.optional and a.kind != "m2m":
        return "it becomes required", "empty", None
    return None, "set", None


@dataclass
class _Context:
    """Both sides in normal form, and what the plan needs to name things."""

    desired: dict[str, Any]
    current: dict[str, Any]
    facts: dict[str, Any]
    pk: str
    #: new label -> old label (``was:`` on an entity, applied).
    entity_renames: dict[str, str]
    #: (new label, new field) -> old field (``was:`` on a field).
    field_renames: dict[tuple[str, str], str]
    changes: list[Change] = field(default_factory=list)
    migrations: list[str] = field(default_factory=list)

    def add(self, change: Change) -> None:
        self.changes.append(change)

    def migrate(self, label: str) -> None:
        app = label.split(".", 1)[0]
        if app not in self.migrations:
            self.migrations.append(app)


def _app(ctx: _Context) -> None:
    for key in ("name", "kind"):
        old, new = ctx.current["app"].get(key), ctx.desired["app"].get(key)
        if old != new:
            ctx.add(Change("app", "change", key, f"{old} -> {new}"))


def _modules(ctx: _Context) -> None:
    old, new = ctx.current["modules"], ctx.desired["modules"]
    installed = {module["name"]: module for module in ctx.facts.get("modules") or []}
    for name, options in new.items():
        if name not in old:
            ctx.add(Change("modules", "add", name, _show(options) if options else ""))
            continue
        # the export leaves out an option at its default: compare the setting's value itself
        values = (installed.get(name) or {}).get("settings") or {}
        for option in sorted(set(options) | set(old[name])):
            before, after = old[name].get(option), options.get(option)
            setting = module_setting(name, option)
            if option not in old[name] and option in options and setting in values:
                before = values[setting]
            if before != after:
                ctx.add(
                    Change(
                        "modules",
                        "change",
                        f"{name}.{option}",
                        f"{_show(before) if option in old[name] else 'default'} -> "
                        f"{_show(after) if option in options else 'default'}",
                    )
                )
    for name in old:
        if name not in new:
            known = MODULES.get(name)
            counts = tuple(Count(f"{known.app}.{model}") for model in known.models) if known else ()
            ctx.add(
                Change(
                    "modules",
                    "remove",
                    name,
                    risky=True,
                    reason="its tables and their rows are dropped",
                    counts=counts,
                )
            )


def _features(ctx: _Context) -> None:
    old, new = ctx.current["features"], ctx.desired["features"]
    for key, setting in _FEATURE_SETTINGS.items():
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        if key == "api_cache":
            _api_cache(ctx, before, after)
            continue
        if key == "terms" and before and after:
            changed = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
            detail = ", ".join(
                f"{k} {_show(before.get(k))} -> {_show(after.get(k))}" for k in changed
            )
            ctx.add(Change("features", "change", key, f"{setting} {detail}"))
            continue
        if not after:
            ctx.add(Change("features", "remove", key, setting))
            continue
        shown = (
            {k: v for k, v in after.items() if v is not None and (k, v) != ("required", True)}
            if key == "terms"
            else after
        )
        value = "" if after is True else f" {_show(shown)}"
        action = "add" if not before else "change"
        ctx.add(Change("features", action, key, f"{setting}{value}"))


def _api_cache(ctx: _Context, before: Any, after: Any) -> None:
    """``KARNI_API_CACHE``, with ``KARNI_API_CACHE_TTL`` when it is not the default."""
    setting = _FEATURE_SETTINGS["api_cache"]
    if not after:
        ctx.add(Change("features", "remove", "api_cache", setting))
        return
    ttl = after["ttl"]
    if before:
        detail = f"KARNI_API_CACHE_TTL {before['ttl']} -> {ttl}"
        ctx.add(Change("features", "change", "api_cache", detail))
        return
    shown = "" if ttl == DEFAULT_CACHE_TTL else f", KARNI_API_CACHE_TTL {ttl}"
    ctx.add(Change("features", "add", "api_cache", f"{setting}{shown}"))


def _grant_counts(pattern: str, labels: Iterable[str]) -> tuple[Count, ...]:
    target = pattern.partition(":")[0]
    if "*" in target or "." not in target:
        return ()
    found = [label for label in labels if label.lower() == target.lower()]
    return (Count(found[0]),) if len(found) == 1 else ()


def _roles(ctx: _Context) -> None:
    old, new = ctx.current["roles"], ctx.desired["roles"]
    labels = list(_entities(ctx.current))
    for slug, role in new.items():
        if slug not in old:
            parts = [f"name {role['name']}"] if role["name"] != role_name(slug) else []
            parts += [flag for flag in ("system", "default") if role.get(flag)]
            if role["grants"]:
                parts.append("grants " + ", ".join(f"{p} {s}" for p, s in role["grants"].items()))
            ctx.add(Change("roles", "add", slug, ", ".join(parts)))
            continue
        before = old[slug]
        changed = [
            f"{key} {_show(before.get(key))} -> {_show(role.get(key))}"
            for key in ("name", "description", "system", "default")
            if before.get(key) != role.get(key)
        ]
        if changed:
            ctx.add(Change("roles", "change", slug, ", ".join(changed)))
        for pattern, scope in role["grants"].items():
            was = before["grants"].get(pattern)
            target = f"{slug} grant {pattern}"
            if was is None:
                ctx.add(Change("roles", "add", target, scope))
            elif was != scope:
                widened = scope == "all"
                ctx.add(
                    Change(
                        "roles",
                        "change",
                        target,
                        f"{was} -> {scope}",
                        risky=widened,
                        reason="the role reaches every row, not only its own" if widened else None,
                        counts=_grant_counts(pattern, labels) if widened else (),
                    )
                )
        for pattern, scope in before["grants"].items():
            if pattern not in role["grants"]:
                ctx.add(Change("roles", "remove", f"{slug} grant {pattern}", scope))
    for slug in old:
        if slug not in new:
            ctx.add(Change("roles", "remove", slug))


def tested(entity: dict[str, Any]) -> bool:
    """Experimental. Whether karni build writes an API test for ``entity`` (in normal form).

    A table another system owns, or one on another database, gets none: the
    test database holds neither.
    """
    return not entity.get("external") and entity.get("database") in (None, "default")


def _entity_line(label: str, entity: dict[str, Any], pk: str) -> str:
    fields = ", ".join(f"{name} {token}" for name, token in entity["fields"].items())
    options: list[str] = []
    for key in _OPTIONS:
        value = entity.get(key)
        if key == "pk" and value in (None, pk):
            continue
        if key == "external" and value:
            options.append(f"external {entity['table']}")
            continue
        if key == "cache" and value is False:
            options.append("cache false")
            continue
        if key == "table" or value in (None, False, [], {}):
            continue
        if value is True:
            options.append(key)
        elif key == "aggregate":
            options.append(f"aggregate {_aggregate_text(value)}")
        elif key in ("groups", "column_sets", "scope_paths"):
            options.append(f"{key} {', '.join(value)}")
        elif key == "global_search":
            options.append(f"{key} {_search_text(value)}")
        else:
            options.append(f"{key} {_show(value)}")
    return f"({fields}) {', '.join(options)}".rstrip()


def _outside(facts: dict[str, Any]) -> tuple[set[str], dict[str, set[str]]]:
    """Models that are not entities, and every model's field names, from the facts."""
    models: set[str] = set()
    fields: dict[str, set[str]] = {}
    for app in facts["apps"]:
        for model in app["models"]:
            fields[model["label"]] = {fact["name"] for fact in model["fields"]}
            if not export.is_entity(model):
                models.add(model["label"])
    return models, fields


def _entities_and_fields(ctx: _Context) -> None:
    old_entities, new_entities = _entities(ctx.current), _entities(ctx.desired)
    resolve_new = _resolver(new_entities)
    renamed_back = {old: new for new, old in ctx.entity_renames.items()}
    resolve_old_raw = _resolver(old_entities)

    def resolve_old(ref: str, app: str = "") -> str:
        label = resolve_old_raw(ref, app)
        return renamed_back.get(label, label)

    outside_models, outside_fields = _outside(ctx.facts)
    matched: set[str] = set()
    for label, entity in new_entities.items():
        app = label.split(".", 1)[0]
        old_label = label if label in old_entities else ctx.entity_renames.get(label)
        if old_label is None:
            risky = label in outside_models
            ctx.add(
                Change(
                    "entities",
                    "add",
                    label,
                    _entity_line(label, entity, ctx.pk),
                    risky=risky,
                    reason=(
                        f"the project has a model {label} outside the spec, which karni build "
                        "does not replace"
                        if risky
                        else None
                    ),
                )
            )
            ctx.migrate(label)
            if entity["access"] != {"read": ["granted"], "write": ["granted"]}:
                ctx.add(Change("access", "add", label, _rule(entity["access"])))
            if tested(entity):
                ctx.add(Change("tests", "add", layout.test_file(app, label.split(".")[1])))
            continue
        matched.add(old_label)
        before = old_entities[old_label]
        if old_label != label:
            ctx.add(
                Change("entities", "rename", label, f"from {old_label.split('.')[1]}, rows kept")
            )
            ctx.migrate(label)
        _options(ctx, label, old_label, before, entity)
        _fields(ctx, label, old_label, before, entity, resolve_old, resolve_new, outside_fields)
        # access: code is the project's viewset deciding: any access it has matches
        if entity["access"] != "code" and before["access"] != entity["access"]:
            why = _widened(before["access"], entity["access"])
            ctx.add(
                Change(
                    "access",
                    "change",
                    label,
                    f"{_rule(before['access'])} -> {_rule(entity['access'])}",
                    risky=why is not None,
                    reason=why,
                    counts=(Count(old_label),) if why and not why.startswith("creates") else (),
                )
            )
    for old_label, before in old_entities.items():
        if old_label in matched:
            continue
        owned = not before.get("external")  # an external table is never dropped
        ctx.add(
            Change(
                "entities",
                "remove",
                old_label,
                risky=owned,
                reason="its table and rows are dropped" if owned else "its table stays",
                counts=(Count(old_label),) if owned else (),
            )
        )
        ctx.migrate(old_label)


def _taxonomy_risk(old: Any, new: Any) -> str | None:
    """Experimental. Why a ``taxonomies`` change loses tags, or ``None`` when it only adds keys.

    A key that goes away, or points at another tree, drops its many-to-many
    and every tag it holds.
    """
    before, after = dict(old or {}), dict(new or {})
    lost = sorted(key for key, tree in before.items() if after.get(key) != tree)
    if not lost:
        return None
    return f"the tags under {', '.join(lost)} are dropped with their table"


def _tree_risk(old: Any, new: Any, label: str) -> tuple[str | None, tuple[Count, ...]]:
    """Experimental. ``(reason, counts)`` for a ``tree`` change. ``reason`` ``None``: not risky.

    Making an entity a tree or flat again changes its table, its delete and
    its API, so both are risky. Between ``true`` and ``ordered`` only dropping
    ``position`` is: adding it loses nothing.
    """
    if not old and new:
        why = "every row becomes a root, and a node with children can no longer be deleted alone"
        return why, (Count(label),)
    if old and not new:
        why = "the parent column is dropped, and every row's place in the tree with it"
        return why, (Count(label, "parent", "set"),)
    if old == "ordered" and new is True:
        why = "the position column is dropped, and the order of siblings with it"
        return why, (Count(label),)
    return None, ()


def _options(
    ctx: _Context, label: str, old_label: str, before: dict[str, Any], after: dict[str, Any]
) -> None:
    for key in _OPTIONS:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        risky, reason = False, None
        counts: tuple[Count, ...] = ()
        if key == "tree":
            reason, counts = _tree_risk(old, new, old_label)
            risky = reason is not None
        elif key == "taxonomies":
            reason = _taxonomy_risk(old, new)
            risky = reason is not None
        elif key == "pk" and old is not None and new is not None:
            risky = True
            reason = (
                "switching the key type of a table that holds rows is out of scope, so karni "
                "build will not apply it"
            )
        elif key == "database" and not after.get("external") and not before.get("external"):
            risky = True
            reason = f"the rows stay on {old or 'default'}, karni build does not move them"
        shown = {"aggregate": _aggregate_text, "global_search": _search_text}.get(key, _show)
        ctx.add(
            Change(
                "entities",
                "change",
                f"{label} {key}",
                f"{shown(old)} -> {shown(new)}",
                risky=risky,
                reason=reason,
                counts=counts or ((Count(old_label),) if risky else ()),
            )
        )
        if key in _MIGRATED or (key == "global_search" and _search_indexes_change(before, after)):
            ctx.migrate(label)


def _search_indexes_change(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Whether ``global_search`` changes the trigram indexes a migration writes."""
    if after.get("external"):
        return False  # no migration touches a table another system owns
    old, new = before.get("global_search"), after.get("global_search")
    return set((old or {}).get("fields") or []) != set((new or {}).get("fields") or [])


def _fields(
    ctx: _Context,
    label: str,
    old_label: str,
    before: dict[str, Any],
    after: dict[str, Any],
    resolve_old: Callable[[str, str], str],
    resolve_new: Callable[[str, str], str],
    outside_fields: dict[str, set[str]],
) -> None:
    old_fields, new_fields = before["fields"], after["fields"]
    owned = not after.get("external")  # no migration changes an external table's columns
    renames = {
        new: old
        for (owner, new), old in ctx.field_renames.items()
        if owner == label and old in old_fields and new not in old_fields
    }
    taken = set(renames.values())
    added = [name for name in new_fields if name not in old_fields and name not in renames]
    removed = [name for name in old_fields if name not in new_fields and name not in taken]

    def key(token: str, owner: str, resolve: Callable[[str, str], str]) -> str:
        target = _target(token, owner, resolve)
        if target is None:
            return token
        kind = token.split(":", 1)[0]
        return f"{kind}:{target}{'?' if token.endswith('?') else ''}"

    for name, token in new_fields.items():
        old_name = renames.get(name, name)
        if name in added:
            exists = name in outside_fields.get(old_label, set())
            ctx.add(
                Change(
                    "fields",
                    "add",
                    f"{label}.{name}",
                    token,
                    risky=exists,
                    reason=(
                        "the model has this field already, in a form the spec cannot express "
                        "(karni spec export says why)"
                        if exists
                        else None
                    ),
                )
            )
            ctx.migrate(label)
            continue
        old_token = old_fields[old_name]
        renamed = old_name != name
        same = key(old_token, old_label, resolve_old) == key(token, label, resolve_new)
        if same and not renamed:
            continue
        reason, kind, arg = (
            (None, "set", None)
            if same or not owned
            else _field_risk(
                old_token,
                token,
                _target(old_token, old_label, resolve_old),
                _target(token, label, resolve_new),
            )
        )
        parts = [f"from {old_name}"] if renamed else []
        if not same:
            parts.append(f"{old_token} -> {token}")
        detail = ", ".join(parts)
        ctx.add(
            Change(
                "fields",
                "rename" if renamed else "change",
                f"{label}.{name}",
                detail,
                risky=reason is not None,
                reason=reason,
                counts=(Count(old_label, old_name, kind, arg),) if reason else (),
            )
        )
        ctx.migrate(label)
    pairs: dict[str, str] = {}
    free = list(added)
    for name in removed:
        match = next(
            (
                new
                for new in free
                if key(new_fields[new], label, resolve_new)
                == key(old_fields[name], old_label, resolve_old)
            ),
            None,
        )
        if match is not None:
            pairs[name] = match
            free.remove(match)
    for name in removed:
        reason = "its values are lost" if owned else "its column stays"
        if name in pairs:
            reason += (
                f", probably renamed to {pairs[name]}: write {pairs[name]}: "
                f'{{type: "{new_fields[pairs[name]]}", was: {name}}} to keep them'
            )
        ctx.add(
            Change(
                "fields",
                "remove",
                f"{label}.{name}",
                old_fields[name],
                risky=owned,
                reason=reason,
                counts=(Count(old_label, name, "set"),) if owned else (),
            )
        )
        ctx.migrate(label)


def _apps(ctx: _Context) -> None:
    old, new = ctx.current["apps"], ctx.desired["apps"]
    for label in new:
        if label not in old:
            ctx.add(Change("apps", "add", label))
    for label in old:
        if label not in new:
            ctx.add(Change("apps", "remove", label))


def _pages(ctx: _Context) -> None:
    resolve_new = _resolver(_entities(ctx.desired))
    renamed_back = {old: new for new, old in ctx.entity_renames.items()}
    resolve_old_raw = _resolver(_entities(ctx.current))

    def ident(name: str, resolve: Callable[[str, str], str], back: dict[str, str]) -> str:
        if not name[:1].isupper() and "." not in name:
            return name
        label = resolve(name, "")
        return back.get(label, label)

    old = {
        ident(n, resolve_old_raw, renamed_back): (n, k)
        for e in ctx.current["pages"]
        for n, k in e.items()
    }
    new = {ident(n, resolve_new, {}): (n, k) for e in ctx.desired["pages"] for n, k in e.items()}
    counted = ", ".join(sorted(name for _label, name in _entity_names(ctx.desired)))
    for ident_, (name, kinds) in new.items():
        if ident_ not in old:
            ctx.add(Change("pages", "add", name, _show_page(name, kinds, counted)))
        elif old[ident_][1] != kinds:
            before = _show_page(name, old[ident_][1], "")
            ctx.add(Change("pages", "change", name, f"{before} -> {_show_page(name, kinds, '')}"))
    for ident_, (name, kinds) in old.items():
        if ident_ not in new:
            ctx.add(Change("pages", "remove", name, _show_page(name, kinds, "")))
    common_old = [i for i in old if i in new]
    common_new = [i for i in new if i in old]
    if common_old != common_new:
        ctx.add(Change("pages", "change", "navigation", ", ".join(new[i][0] for i in new)))


def _navigation(ctx: _Context) -> None:
    """The menu (experimental): ``KARNI_NAVIGATION`` as ``navigation:`` gives it, in the settings block."""
    old, new = ctx.current.get("navigation"), ctx.desired.get("navigation")
    if old == new:
        return
    if new is None:
        ctx.add(Change("pages", "remove", MENU, navigation.summary(old)))
    else:
        ctx.add(Change("pages", "add" if old is None else "change", MENU, navigation.summary(new)))


def _entity_names(data: dict[str, Any]) -> list[tuple[str, str]]:
    """``(app.Name, Name)`` of every entity of ``data`` (a normal form)."""
    return [
        (f"{app}.{name}", name)
        for app, application in data.get("apps", {}).items()
        for name in application.get("entities", {})
    ]


def _show_page(name: str, kinds: list[Any], counted: str) -> str:
    """A page entry's kinds in words: ``list, detail (related crm.Deal.company), form``.

    A dashboard other than the scaffold's home names what its chart counts (``counted``).
    """
    shown: list[str] = []
    for kind in kinds:
        if isinstance(kind, dict):
            for key, options in kind.items():
                related = ", ".join(options.get("related") or [])
                shown.append(f"{key} (related {related})" if related else key)
        elif kind == "dashboard" and name != "home" and counted:
            shown.append(f"dashboard (rows per entity: {counted})")
        else:
            shown.append(str(kind))
    return ", ".join(shown) or "none"


def _seed(ctx: _Context) -> None:
    resolve_new = _resolver(_entities(ctx.desired))
    renamed_back = {old: new for new, old in ctx.entity_renames.items()}
    resolve_old = _resolver(_entities(ctx.current))
    old = {
        renamed_back.get(resolve_old(n, ""), resolve_old(n, "")): c
        for n, c in ctx.current["seed"].items()
    }
    new = {resolve_new(n, ""): (n, c) for n, c in ctx.desired["seed"].items()}
    for label, (name, count) in new.items():
        if label not in old:
            ctx.add(Change("seed", "add", name, str(count)))
        elif old[label] != count:
            ctx.add(Change("seed", "change", name, f"{old[label]} -> {count}"))
    for label, count in old.items():
        if label not in new:
            ctx.add(Change("seed", "remove", label.split(".", 1)[1], str(count)))


def _own(ctx: _Context, managed: Managed) -> None:
    """Mark each change ``managed`` or not, from what ``.karni/build.json`` records."""
    current = _entities(ctx.current)
    desired = _entities(ctx.desired)
    resolve_new, resolve_old = _resolver(desired), _resolver(current)
    renamed_back = {old: new for new, old in ctx.entity_renames.items()}

    def known(label: str) -> bool:
        old = ctx.entity_renames.get(label, label)
        return label in managed.entities or old in managed.entities

    def new(label: str) -> bool:
        return label not in current and ctx.entity_renames.get(label) not in current

    def free(path: str) -> bool:
        return path not in managed.adopted

    old_pages = {
        renamed_back.get(resolve_old(n, ""), resolve_old(n, "")) if n[:1].isupper() else n: k
        for entry in ctx.current["pages"]
        for n, k in entry.items()
    }
    for change in ctx.changes:
        area, action, target = change.area, change.action, change.target
        if area in ("entities", "fields", "access"):
            label = target.split(" ", 1)[0]
            if area == "fields":
                label = label.rsplit(".", 1)[0]
            app = label.split(".", 1)[0]
            file = (
                layout.api_file(app)
                if area == "access" or target.endswith((" search", " cache"))
                else layout.models_file(app)
            )
            if action == "add" and area == "entities":
                # a model of that name outside the spec is the project's: build does not replace it
                ok = not change.risky
            elif action == "add" and area == "access":
                ok = new(label) or known(label)
            else:
                ok = known(label)
            change.managed = ok and free(file)
        elif area in ("roles", "features"):
            change.managed = free(layout.SETTINGS_BLOCK)
        elif area == "modules":
            change.managed = action == "add" or (action == "change" and free(layout.SETTINGS_BLOCK))
        elif area == "apps":
            change.managed = action == "add"
        elif area == "app":
            # karni add site turns an app into a site+app: the only kind change build makes
            change.managed = target == "kind" and change.detail == "app -> site+app"
        elif area == "tests":
            change.managed = free(target)
        elif area == "migrations":
            # an app gets a migration from build only for the changes build makes there
            change.managed = any(
                other.managed
                and other.area in ("entities", "fields")
                and other.target.split(".", 1)[0] == target
                for other in ctx.changes
            )
        elif area == "seed":
            name = target
            label = resolve_new(name, "") if action != "remove" else resolve_old(name, "")
            label = renamed_back.get(label, label) if action == "remove" else label
            app = label.split(".", 1)[0]
            change.managed = (new(label) or known(label)) and free(layout.seeds_file(app))
        elif area == "pages" and target == MENU:
            change.managed = free(layout.SETTINGS_BLOCK)
        elif area == "pages":
            change.managed = _page_managed(change, ctx, managed, resolve_new, old_pages)


def _page_managed(
    change: Change,
    ctx: _Context,
    managed: Managed,
    resolve: Callable[[str, str], str],
    old_pages: dict[str, list[str]],
) -> bool:
    if any(block in managed.adopted for block in layout.ROUTES_BLOCKS):
        return False
    if change.target == "navigation":
        return True
    name = change.target
    ident = resolve(name, "") if name[:1].isupper() else name
    before = old_pages.get(ident, [])
    after = schema.page_kind_names(
        next((k for e in ctx.desired["pages"] for n, k in e.items() if n == name), [])
    )
    if change.action == "add" and ("code" in after or ("dashboard" in after and name == "home")):
        return False  # the project's page (code), or the scaffold's home page (dashboard)
    dropped = [kind for kind in schema.page_kind_names(before) if kind not in after]
    return all(f"{ident}:{kind}" in managed.pages for kind in dropped)


def plan_project(
    spec: schema.Spec,
    facts: dict[str, Any],
    root: Path,
    *,
    file: str,
    managed: Managed | None = None,
) -> Plan:
    """Experimental. The plan for ``spec`` against the project ``facts`` describe (no counts yet).

    ``managed``: what karni build manages (:class:`Managed`, from
    ``.karni/build.json``). Each change is then marked managed or not.
    ``None`` marks every change managed.
    """
    pk = str(facts["settings"].get("KARNI_PK") or "uuid")
    current = normalise(_current_spec(facts, root), pk=pk)
    desired = normalise(_with_shipped_roles(spec, facts), pk=pk)
    # the normal form sorts apps, entities and seed: list them in the spec's own order
    desired["apps"] = {
        app: {
            "entities": {
                name: desired["apps"][app]["entities"][name] for name in application.entities
            }
        }
        for app, application in spec.apps.items()
    }
    desired["seed"] = {name: desired["seed"][name] for name in spec.seed}
    old_labels = set(_entities(current))
    entity_renames: dict[str, str] = {}
    field_renames: dict[tuple[str, str], str] = {}
    for app, application in spec.apps.items():
        for name, entity in application.entities.items():
            label = f"{app}.{name}"
            if entity.was and f"{app}.{entity.was}" in old_labels and label not in old_labels:
                entity_renames[label] = f"{app}.{entity.was}"
            for new, old in entity.renamed().items():
                field_renames[(label, new)] = old
    ctx = _Context(desired, current, facts, pk, entity_renames, field_renames)
    _app(ctx)
    _modules(ctx)
    _features(ctx)
    _roles(ctx)
    _apps(ctx)
    _entities_and_fields(ctx)
    _pages(ctx)
    _navigation(ctx)
    for app in ctx.migrations:
        ctx.add(Change("migrations", "add", app))
    _seed(ctx)
    if managed is not None:
        _own(ctx, managed)
    order = {area: index for index, area in enumerate(AREAS)}
    changes = sorted(ctx.changes, key=lambda change: order[change.area])
    return Plan(
        file,
        changes,
        current=current,
        desired=desired,
        entity_renames=entity_renames,
        field_renames=field_renames,
    )


# row counts -----------------------------------------------------------------------

#: ``requests -> {"rows": [...], "unreachable": {alias: why}}``, as ``manage.py karni_rows`` prints.
Counter = Callable[[list[dict[str, Any]]], dict[str, Any]]


def manage_counter(root: Path, *, docker: bool | None = None, service: str = "django") -> Counter:
    """Experimental. A counter that asks ``manage.py karni_rows`` in the project."""

    def count(requests: list[dict[str, Any]]) -> dict[str, Any]:
        proc = project_mod.run_manage(
            root,
            ["karni_rows", json.dumps(requests)],
            docker=docker,
            service=service,
            database=None,
        )
        if proc.returncode != 0:
            last = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
            return {"rows": [], "error": f"manage.py karni_rows failed ({' '.join(last)})"}
        try:
            return dict(json.loads(proc.stdout))
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"rows": [], "error": "manage.py karni_rows did not print JSON"}

    return count


def apply_counts(plan: Plan, counter: Counter | None) -> Plan:
    """Experimental. Fill each risky change's ``rows`` from ``counter`` (``None``: offline)."""
    wanted = [change for change in plan.changes if change.risky and change.counts]
    if not wanted:
        plan.row_counts = "not needed"
        return plan
    if counter is None:
        plan.row_counts, plan.note = "offline", "--offline"
        return plan
    requests = [count.request() for change in wanted for count in change.counts]
    answer = counter(requests)
    rows = list(answer.get("rows") or [])
    if answer.get("error") or len(rows) != len(requests):
        plan.row_counts = "unreachable"
        plan.note = str(answer.get("error") or "the counts did not come back")
        return plan
    index = 0
    for change in wanted:
        found = rows[index : index + len(change.counts)]
        index += len(change.counts)
        change.counted = True
        change.rows = None if any(n is None for n in found) else sum(found)
    unreachable = answer.get("unreachable") or {}
    if unreachable:
        plan.row_counts = "unreachable"
        plan.note = "the database did not answer (" + ", ".join(unreachable.values()) + ")"
        for change in wanted:
            if change.rows is None:
                change.counted = False
    else:
        plan.row_counts = "counted"
    return plan


if __name__ == "__main__":  # pragma: no cover - python -m karni_cli.spec.plan
    print(json.dumps(json_schema(), indent=2, sort_keys=False))
