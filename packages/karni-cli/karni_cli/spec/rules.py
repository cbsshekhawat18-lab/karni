"""Experimental. What ``karni spec validate`` checks in an entity's rules (karni.rules in core).

``bounds`` (``C760``), ``unique`` (``C761``), ``targets`` (``C762``),
``frozen`` (``C763``), ``delete`` (``C764``), ``moves`` (``C765``),
``actions`` (``C766``) and a row filter any of them holds (``C767``): each
names fields, states and entities the spec has, with values of the right
kind, so ``karni build`` never writes a rule that cannot work. Core checks
the same declarations at boot (``karni.E998``); this is the earlier,
spec-side check with the line of the file.

Override / escape hatch: a rule the spec cannot say stays in the project's
code (``class Karni(karni.<Entity>.Karni)`` in ``<app>/models.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from karni_cli.generators.lifecycle_fields import _states
from karni_cli.project import CliError

if TYPE_CHECKING:
    from karni_cli.spec.validate import _Entity, _Meaning

__all__ = ["CODES", "check"]

#: Experimental. The codes this module reports.
CODES: Final = ("C760", "C761", "C762", "C763", "C764", "C765", "C766", "C767")
NUMBER_KINDS: Final = frozenset({"int", "float", "decimal", "money", "percent", "quantity"})
DATE_KINDS: Final = frozenset({"date", "datetime"})
LOOKUPS: Final = frozenset({"exact", "gt", "gte", "lt", "lte", "in", "isnull"})
NAMED: Final = ("$me", "$now", "$today")
_BASE: Final = {"id": "uuid", "pk": "uuid", "created_at": "datetime", "updated_at": "datetime"}
_USERS: Final = ("created_by", "updated_by")
_LEFT: Final = "__left__"  # a path that leaves the spec (the user, a module's model)


def check(meaning: _Meaning, entity: _Entity) -> None:
    """Every rule key of ``entity``."""
    _bounds(meaning, entity)
    _unique(meaning, entity)
    _targets(meaning, entity)
    _frozen(meaning, entity)
    _delete(meaning, entity)
    _moves(meaning, entity)
    _actions(meaning, entity)


def _kind(entity: _Entity, name: str) -> str | None:
    spec = entity.fields.get(name)
    if spec is not None:
        return spec.kind
    return _BASE.get(name)


def _missing(meaning: _Meaning, entity: _Entity, key: str, where: Any, name: str) -> None:
    fields = ", ".join(sorted(entity.fields)) or "none"
    meaning.add(
        _CODE[key],
        where,
        f"{entity.name}.{key} names {name!r}, which is not a field of {entity.name} "
        f"(fields: {fields}).",
        f"Name one of its fields, or add the field under {entity.name}.fields.",
    )


_CODE: Final = {
    "bounds": "C760",
    "unique": "C761",
    "targets": "C762",
    "frozen": "C763",
    "delete": "C764",
    "moves": "C765",
    "actions": "C766",
}


# row filters


def walk(meaning: _Meaning, entity: _Entity, path: str) -> tuple[Any, str | None]:
    """``(where the path ends, problem)``: an entity, a field kind, or :data:`_LEFT`."""
    parts = path.split("__")
    if len(parts) > 1 and parts[-1] in LOOKUPS:
        parts = parts[:-1]
    current: Any = entity
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if current is _LEFT:
            return _LEFT, None
        if isinstance(current, str):
            return None, f"{path!r}: {parts[index - 1]} is not a relation for __ to follow"
        if part in _USERS:
            current = _LEFT
            continue
        spec = current.fields.get(part)
        if spec is None:
            if part in _BASE:
                current = _BASE[part]
                continue
            reverse = meaning.reverse(current, part)
            if reverse is None:
                return None, f"{path!r}: {current.name} has no field {part!r}"
            current = reverse
            continue
        if spec.is_relation:
            target = current.targets.get(part)
            found = meaning.entities.get(target or "")
            current = found if found is not None else _LEFT
        else:
            current = spec.kind
            if not last:
                return None, f"{path!r}: {part} is not a relation for __ to follow"
    return current, None


def _value_problem(
    meaning: _Meaning, row: _Entity | None, value: Any, *, fixed: bool
) -> str | None:
    if isinstance(value, dict):
        if set(value) != {"not"}:
            return f"{value!r} is not a value: write a literal, a $ name or {{not: <value>}}"
        value = value["not"]
        if isinstance(value, dict):
            return "{not: ...} takes a value, not another mapping"
    items = value if isinstance(value, list) else [value]
    for item in items:
        if not (isinstance(item, str) and item.startswith("$")):
            continue
        if fixed:
            return f"{item} is not a fixed value: this filter takes literals only"
        if item in NAMED:
            continue
        if row is None:
            return f"{item} names a field of the row, and there is none here"
        _end, problem = walk(meaning, row, item[1:])
        if problem is not None:
            return f"{item}: {problem}"
    return None


def row_filter(
    meaning: _Meaning,
    entity: _Entity,
    where: Any,
    value: Any,
    target: _Entity | None,
    *,
    row: _Entity | None = None,
    fixed: bool = False,
) -> None:
    """``C767`` for a row filter on ``target`` that cannot be read (``row``: the written row)."""
    if not isinstance(value, dict) or not value:
        meaning.add(
            "C767",
            where,
            f"{entity.name}: {value!r} is not a row filter.",
            "Write {field: value}, e.g. {active: true} or {status: {not: cancelled}}.",
        )
        return
    for key, item in value.items():
        problem = None
        if target is not None:
            _end, problem = walk(meaning, target, str(key))
        problem = problem or _value_problem(meaning, row, item, fixed=fixed)
        if problem is not None:
            meaning.add(
                "C767",
                (*where, key),
                f"{entity.name}: a row filter has {problem}.",
                "Name a field (or a path through relations, ending in gt, gte, lt, lte, in or "
                "isnull), with a literal, $me, $now, $today, $<field of the row> or "
                "{not: <value>}.",
            )


# the keys


def _bounds(meaning: _Meaning, entity: _Entity) -> None:
    for name, bound in entity.entity.bounds.items():
        where = (*entity.path, "bounds", name)
        kind = _kind(entity, name)
        if kind is None:
            _missing(meaning, entity, "bounds", where, name)
            continue
        if kind not in NUMBER_KINDS | DATE_KINDS:
            meaning.add(
                "C760",
                where,
                f"{entity.name}.bounds.{name}: {name} is {kind}, and bounds apply to numbers, "
                "dates and datetimes.",
                "Bound a number, date or datetime field, or drop the entry.",
            )
            continue
        if bound.min is None and bound.max is None:
            meaning.add(
                "C760", where, f"{entity.name}.bounds.{name} has no min or max.", "Write min, max."
            )
        for side in ("min", "max"):
            value = getattr(bound, side)
            if value is None:
                continue
            if kind in DATE_KINDS:
                ok = value in ("$now", "$today") or (isinstance(value, str) and _iso(value))
                hint = "$now, $today or a date such as 2000-01-01"
            else:
                ok = isinstance(value, int | float) or (isinstance(value, str) and _number(value))
                hint = "a number"
            if not ok:
                meaning.add(
                    "C760",
                    (*where, side),
                    f"{entity.name}.bounds.{name}.{side} is {value!r}, not {hint}.",
                    f"Write {hint}.",
                )


def _iso(value: str) -> bool:
    import datetime as dt

    try:
        dt.date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def _number(value: str) -> bool:
    from decimal import Decimal, InvalidOperation

    try:
        Decimal(value)
    except InvalidOperation:
        return False
    return True


def _unique(meaning: _Meaning, entity: _Entity) -> None:
    for index, entry in enumerate(entity.entity.unique):
        where = (*entity.path, "unique", index)
        names = entry if isinstance(entry, list) else entry.fields
        if not names:
            meaning.add("C761", where, f"{entity.name}.unique has an empty entry.", "Name fields.")
        for name in names:
            if _kind(entity, name) is None:
                _missing(meaning, entity, "unique", where, name)
        if entity.entity.external:
            meaning.add(
                "C761",
                where,
                f"{entity.name} is external: Karni adds no index to a table another system owns.",
                "Drop unique, or declare the index in that system.",
            )
        if not isinstance(entry, list) and entry.where is not None:
            row_filter(meaning, entity, (*where, "where"), entry.where, entity, fixed=True)


def _targets(meaning: _Meaning, entity: _Entity) -> None:
    for name, value in entity.entity.targets.items():
        where = (*entity.path, "targets", name)
        spec = entity.fields.get(name)
        if spec is None or spec.kind not in ("fk", "o2o"):
            meaning.add(
                "C762",
                where,
                f"{entity.name}.targets names {name!r}, which is not a foreign key of "
                f"{entity.name}.",
                "Name an fk or o2o field of the entity.",
            )
            continue
        target = meaning.entities.get(entity.targets.get(name) or "")
        row_filter(meaning, entity, where, value, target, row=entity)


def _frozen(meaning: _Meaning, entity: _Entity) -> None:
    for name, value in entity.entity.frozen.items():
        where = (*entity.path, "frozen", name)
        if name not in entity.fields:
            _missing(meaning, entity, "frozen", where, name)
            continue
        if value is False:
            meaning.add("C763", where, f"{entity.name}.frozen.{name} is false.", "Drop it.")
        elif isinstance(value, dict):
            row_filter(meaning, entity, where, value, entity, row=entity)


def related(meaning: _Meaning, entity: _Entity, ref: str) -> str | None:
    """The problem with a relation reference to ``entity`` (``Deal``, ``Deal.company``), or None."""
    parts = ref.split(".")
    field = parts.pop() if len(parts) > 1 and parts[-1][:1].islower() else None
    name = ".".join(parts)
    found = [
        other for other in meaning.entities.values() if other.name == name or other.label == name
    ]
    if len(found) != 1:
        return f"{ref!r} is not an entity of the spec"
    other = found[0]
    keys = [key for key, target in other.targets.items() if target == entity.label]
    if field is not None:
        return None if field in keys else f"{other.name}.{field} does not point at {entity.name}"
    if len(keys) != 1:
        return f"{other.name} has {len(keys)} fks to {entity.name}" + (
            f" ({', '.join(keys)}): name one, {other.name}.<field>" if keys else ""
        )
    return None


def _delete(meaning: _Meaning, entity: _Entity) -> None:
    rule = entity.entity.delete
    if rule is None:
        return
    where = (*entity.path, "delete")
    if rule.when is None and not rule.blocked_by:
        meaning.add("C764", where, f"{entity.name}.delete is empty.", "Write when or blocked_by.")
    if rule.when is not None:
        row_filter(meaning, entity, (*where, "when"), rule.when, entity, row=entity)
    items = (
        rule.blocked_by.items()
        if isinstance(rule.blocked_by, dict)
        else ((ref, None) for ref in rule.blocked_by)
    )
    for ref, condition in items:
        problem = related(meaning, entity, ref)
        if problem is not None:
            meaning.add(
                "C764",
                (*where, "blocked_by"),
                f"{entity.name}.delete.blocked_by: {problem}.",
                "Name an entity with an fk to this one (Deal), or Entity.field when it has two.",
            )
            continue
        if condition is not None:
            other = next(
                e for e in meaning.entities.values() if ref.split(".")[0] in (e.name, e.label)
            )
            row_filter(meaning, entity, (*where, "blocked_by", ref), condition, other)


def _state_values(entity: _Entity, name: str) -> list[str] | None:
    spec = entity.fields.get(name)
    if spec is None or spec.kind != "state":
        return None
    try:
        states, _moves, _declared = _states(name, ":".join(spec.args))
    except CliError:
        return None
    return list(states)


def _states_of(entity: _Entity) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for name in entity.fields:
        values = _state_values(entity, name)
        if values is not None:
            found[name] = values
    return found


def _moves(meaning: _Meaning, entity: _Entity) -> None:
    states = _states_of(entity)
    for key, rule in entity.entity.moves.items():
        where = (*entity.path, "moves", key)
        name, colon, state = key.partition(":")
        owners = [f for f, values in states.items() if (state if colon else key) in values]
        flag = entity.fields.get(key)
        if colon:
            ok = name in states and state in states[name]
        else:
            ok = len(owners) + int(flag is not None and flag.kind == "bool") == 1
        if not ok:
            meaning.add(
                "C765",
                where,
                f"{entity.name}.moves names {key!r}, which is not one state of its state field "
                "or a boolean field.",
                "Write a state (lost), <field>:<state> when two state fields have it, or a "
                "boolean field (published).",
            )
        for name in rule.requires:
            if name not in entity.fields:
                _missing(meaning, entity, "moves", (*where, "requires"), name)
        for name in rule.stamps:
            if _kind(entity, name) not in DATE_KINDS:
                meaning.add(
                    "C765",
                    (*where, "stamps"),
                    f"{entity.name}.moves.{key}.stamps names {name!r}, which is not a date or "
                    "datetime field of the entity.",
                    "Stamp a date or datetime field (closed_at: datetime?).",
                )
        if rule.notify is not None and not meaning.leads_to_user(entity, rule.notify):
            meaning.add(
                "C765",
                (*where, "notify"),
                f"{entity.name}.moves.{key}.notify is {rule.notify!r}, which does not lead from "
                f"{entity.name} to the user.",
                "Name a relation to the user, e.g. notify: member, or a path such as "
                "listing__seller__user.",
            )
        for ref in rule.needs:
            problem = related(meaning, entity, ref)
            if problem is not None:
                meaning.add(
                    "C765",
                    (*where, "needs"),
                    f"{entity.name}.moves.{key}.needs: {problem}.",
                    "Name an entity with an fk to this one (Lesson).",
                )


def _actions(meaning: _Meaning, entity: _Entity) -> None:
    states = _states_of(entity)
    for name, rule in entity.entity.actions.items():
        where = (*entity.path, "actions", name)
        field = rule.field or (next(iter(states)) if len(states) == 1 else None)
        if field is None or field not in states:
            if rule.from_ or rule.to is not None:
                meaning.add(
                    "C766",
                    where,
                    f"{entity.name}.actions.{name} names states, but "
                    + (
                        f"{rule.field!r} is not a state field."
                        if rule.field
                        else f"{entity.name} has {len(states)} state fields."
                    ),
                    "Give the entity one state field, or name it with field:.",
                )
            continue
        legal = states[field]
        for state in [*rule.from_, *([rule.to] if rule.to is not None else [])]:
            if state not in legal:
                meaning.add(
                    "C766",
                    where,
                    f"{entity.name}.actions.{name} names {state!r}, which is not a state of "
                    f"{field} ({', '.join(legal)}).",
                    "Name one of the field's states.",
                )
        for item in rule.by or []:
            word, colon, arg = item.partition(":")
            if word in ("public", "authenticated", "granted") and not colon:
                continue
            if word == "role" and arg in meaning.declared_roles():
                continue
            if word == "owned" and arg and meaning.leads_to_user(entity, arg):
                continue
            meaning.add(
                "C766",
                (*where, "by"),
                f"{entity.name}.actions.{name}.by has {item!r}, which is not an access rule of "
                "the entity.",
                "Use public, authenticated, granted, role:<declared slug> or owned:<path to the "
                "user>.",
            )
