"""The engine behind :class:`karni.models.GuardedModel`: loaded values, plans, conditional SQL.

:class:`~karni.fields.StateField`, :class:`~karni.fields.CapacityField` and
:class:`~karni.constraints.NoOverlap` need three things from every save,
which a field alone cannot do:

1. **What the row held when it was loaded.** ``from_db()`` and
   ``refresh_from_db()`` remember the value of every state, capacity and
   capacity-total column (:func:`remember`), so a transition is checked from
   the state the row *had*, and the conditional ``UPDATE`` compares against it.
2. **A plan, before any SQL.** :func:`plan_write` checks every state that
   changes (:class:`~karni.lifecycle.IllegalTransition`), refuses a direct
   write of a capacity counter, and works out how far a change of the total
   shifts the counter.
3. **Conditional SQL and named refusals.** The ``UPDATE`` of a row whose state
   is written carries ``AND "status" = '<loaded>'`` (:func:`expected_states`);
   when it matches nothing although the row exists, another transaction moved
   the state and :class:`~karni.lifecycle.StateConflict` says to what. An
   ``IntegrityError`` from a Karni constraint becomes the matching coded
   error (:func:`karni.conflicts.translate`).

Models without any of these fields or constraints pay one dictionary lookup
per save. Override / escape hatch: override the corresponding
``GuardedModel`` method (``save``, ``_do_update``, ``from_db``,
``refresh_from_db``) on your model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from django.db import models

from karni.fields.capacity import CapacityField
from karni.fields.state import StateField, _value

__all__ = [
    "MISSING",
    "Guards",
    "Plan",
    "after_write",
    "capacity_shift",
    "expected_states",
    "guards_for",
    "loaded",
    "plan_write",
    "remember",
    "remember_value",
    "state_moved",
]

#: "Not known": the value was never loaded (deferred, or a hand-built instance).
MISSING: Final = object()

_LOADED: Final = "_karni_loaded"
_PLAN: Final = "_karni_plan"


@dataclass(frozen=True)
class Guards:
    """What a model needs guarded: its state and capacity fields, its NoOverlap constraints."""

    states: tuple[StateField, ...]
    capacities: tuple[CapacityField, ...]
    overlaps: tuple[Any, ...]
    #: attnames whose loaded value is remembered.
    tracked: tuple[str, ...]

    @property
    def active(self) -> bool:
        return bool(self.states or self.capacities or self.overlaps)


_GUARDS: dict[type[models.Model], Guards] = {}


def guards_for(model: type[models.Model]) -> Guards:
    """The (cached) :class:`Guards` of ``model``."""
    found = _GUARDS.get(model)
    if found is None:
        from karni.constraints import no_overlap_constraints

        concrete = model._meta.concrete_fields
        states = tuple(f for f in concrete if isinstance(f, StateField))
        capacities = tuple(f for f in concrete if isinstance(f, CapacityField))
        tracked = [f.attname for f in states] + [f.attname for f in capacities]
        for capacity in capacities:
            total = capacity.total_field()
            if total is not None:
                tracked.append(total.attname)
        found = Guards(
            states=states,
            capacities=capacities,
            overlaps=no_overlap_constraints(model),
            tracked=tuple(dict.fromkeys(tracked)),
        )
        _GUARDS[model] = found
    return found


def clear_caches() -> None:
    """Forget per-model metadata (tests that build models at runtime)."""
    _GUARDS.clear()


# loaded values


def loaded(instance: models.Model, attname: str) -> Any:
    """What ``attname`` held when ``instance`` was loaded or last saved, else :data:`MISSING`."""
    return instance.__dict__.get(_LOADED, {}).get(attname, MISSING)


def remember_value(instance: models.Model, attname: str, value: Any) -> None:
    """Record ``value`` as what the database holds for ``attname`` (replaces, never mutates)."""
    instance.__dict__[_LOADED] = {**instance.__dict__.get(_LOADED, {}), attname: value}


def _forget(instance: models.Model, attname: str) -> None:
    current = dict(instance.__dict__.get(_LOADED, {}))
    current.pop(attname, None)
    instance.__dict__[_LOADED] = current


def remember(instance: models.Model, fields: Any = None) -> None:
    """Snapshot the tracked columns ``instance`` now holds (after ``from_db`` / a refresh).

    ``fields`` limits it to the refreshed names (``refresh_from_db(fields=...)``,
    which deferred loading uses).
    """
    tracked = guards_for(type(instance)).tracked
    if not tracked:
        return
    if fields is not None:
        wanted = set()
        for name in fields:
            try:
                wanted.add(instance._meta.get_field(name).attname)
            except Exception:  # noqa: BLE001 - an unknown name is Django's error to raise
                wanted.add(name)
        tracked = tuple(attname for attname in tracked if attname in wanted)
    current = dict(instance.__dict__.get(_LOADED, {}))
    for attname in tracked:
        if attname in instance.__dict__:
            current[attname] = instance.__dict__[attname]
    instance.__dict__[_LOADED] = current


def _fetch(instance: models.Model, attnames: list[str]) -> None:
    """Read the stored values of ``attnames`` (an instance that was never loaded)."""
    alias = instance._state.db or "default"
    row = type(instance)._base_manager.using(alias).filter(pk=instance.pk).values(*attnames).first()
    for attname in attnames:
        remember_value(instance, attname, None if row is None else row[attname])


# planning a write


@dataclass
class Plan:
    """What a save will do to guarded columns, worked out before any SQL."""

    adding: bool
    transitions: list[Any] = field(default_factory=list)
    #: CapacityField attname -> how far a change of its total shifts it.
    shifts: dict[str, int] = field(default_factory=dict)
    #: Fields the save must also write (a counter whose total changes).
    extra_fields: set[str] = field(default_factory=set)
    #: Tracked attnames this save writes.
    written: set[str] = field(default_factory=set)


def _writes(instance: models.Model, f: models.Field[Any, Any], update_fields: Any) -> bool:
    if f.attname not in instance.__dict__:
        return False  # deferred: Django leaves it out of the UPDATE
    if update_fields is None:
        return True
    return f.name in update_fields or f.attname in update_fields


def plan_write(instance: models.Model, update_fields: Any = None) -> Plan | None:
    """Check a save of ``instance`` before any SQL; ``None`` when it writes nothing guarded.

    Raises :class:`~karni.lifecycle.IllegalTransition` for an illegal state
    change or initial state, and ``E986`` for a direct write of a capacity
    counter.
    """
    guards = guards_for(type(instance))
    if not guards.active:
        return None
    from karni.exceptions import KarniValueError
    from karni.lifecycle import Transition, transition_problem

    adding = bool(instance._state.adding)
    plan = Plan(adding=adding)
    if not adding and instance.pk is not None:
        counted: tuple[Any, ...] = (*guards.states, *guards.capacities)
        unknown = [
            f.attname
            for f in counted
            if _writes(instance, f, update_fields) and loaded(instance, f.attname) is MISSING
        ]
        for capacity in guards.capacities:
            total = capacity.total_field()
            if (
                total is not None
                and _writes(instance, total, update_fields)
                and loaded(instance, total.attname) is MISSING
            ):
                unknown.append(total.attname)
        if unknown:
            _fetch(instance, unknown)
    for state in guards.states:
        if not _writes(instance, state, update_fields):
            continue
        value = getattr(instance, state.attname)
        problem = transition_problem(instance, state, value)
        if problem is not None:
            raise problem
        plan.written.add(state.attname)
        if adding or value is None:
            continue
        before = loaded(instance, state.attname)
        target = _value(value)
        if before is not MISSING and before is not None and before != target:
            plan.transitions.append(Transition(state, str(before), target))
    for capacity in guards.capacities:
        total = capacity.total_field()
        if adding:
            if getattr(instance, capacity.attname) is None and total is None:
                raise KarniValueError(
                    f"{type(instance).__name__}.{capacity.name} has no total= and no value: a "
                    "new row needs its starting count (pass it, or declare "
                    "CapacityField(total='<field>') to start full).",
                    code="E986",
                )
            plan.written.add(capacity.attname)
            if total is not None:
                plan.written.add(total.attname)
            continue
        writes_counter = _writes(instance, capacity, update_fields)
        if writes_counter:
            before = loaded(instance, capacity.attname)
            now = getattr(instance, capacity.attname)
            if before is not MISSING and now != before:
                raise KarniValueError(
                    f"{type(instance).__name__} {instance.pk}: {capacity.name} was set to "
                    f"{now!r} directly (the row holds {before!r}). A capacity counter changes "
                    "only through karni.capacity.reserve() / release(); set "
                    f"{capacity.total or 'the total'} to resize it.",
                    code="E986",
                )
            plan.written.add(capacity.attname)
        if total is None or not _writes(instance, total, update_fields):
            continue
        old_total = loaded(instance, total.attname)
        new_total = getattr(instance, total.attname)
        plan.written.add(total.attname)
        if old_total is MISSING or old_total is None or new_total is None:
            continue
        shift = int(new_total) - int(old_total)
        if shift:
            plan.shifts[capacity.attname] = shift
            if not writes_counter:
                plan.extra_fields.add(capacity.name)
                plan.written.add(capacity.attname)
    if not plan.written and not guards.overlaps:
        return None  # nothing guarded is written (a soft delete, another field): a plain save
    return plan


def capacity_shift(instance: models.Model, capacity: CapacityField) -> int:
    """How far this save moves ``capacity`` (the change of its total), for ``pre_save``."""
    plan = instance.__dict__.get(_PLAN)
    if plan is None:
        return 0
    return int(plan.shifts.get(capacity.attname, 0))


def begin(instance: models.Model, plan: Plan) -> None:
    instance.__dict__[_PLAN] = plan


def end(instance: models.Model) -> None:
    instance.__dict__.pop(_PLAN, None)


def after_write(instance: models.Model, plan: Plan, using: str) -> None:
    """Inside the save's transaction: update the snapshot, record transitions, send the signal."""
    from karni.lifecycle import record

    guards = guards_for(type(instance))
    shifted = set(plan.shifts)
    for attname in plan.written:
        if attname in shifted:
            # The UPDATE wrote "<col> + <shift>"; the exact value is read on next access.
            instance.__dict__.pop(attname, None)
            _forget(instance, attname)
        elif attname in instance.__dict__:
            value = instance.__dict__[attname]
            if any(f.attname == attname for f in guards.states) and value is not None:
                value = _value(value)
            remember_value(instance, attname, value)
    record(instance, plan.transitions, using)


# the conditional UPDATE


def expected_states(instance: models.Model, values: Any) -> dict[str, Any]:
    """``{attname: loaded state}`` for every state column this ``UPDATE`` writes."""
    guards = guards_for(type(instance))
    if not guards.states:
        return {}
    expected: dict[str, Any] = {}
    for written, *_rest in values:
        if isinstance(written, StateField) and written in guards.states:
            before = loaded(instance, written.attname)
            if before is not MISSING:
                expected[written.attname] = before
    return expected


def state_moved(
    instance: models.Model, base_qs: Any, pk_val: Any, expected: dict[str, Any]
) -> Exception | None:
    """After a conditional ``UPDATE`` matched nothing: the conflict (``None``: the row is gone)."""
    from karni.lifecycle import StateConflict

    current = base_qs.filter(pk=pk_val).values(*expected).first()
    if current is None:
        return None
    moved = {name: value for name, value in current.items() if value != expected[name]}
    attname, now = next(iter(moved.items())) if moved else next(iter(current.items()))
    before = expected[attname]
    return StateConflict(
        f"{type(instance).__name__} {instance.pk}: {attname} is {now!r} in the database, not "
        f"{before!r} as when this instance was loaded — another transaction changed it, so "
        "nothing was written. Reload the row (refresh_from_db()) and decide again from "
        f"{now!r}.",
        field=attname,
        details={
            "resource": instance._meta.label,
            "id": str(instance.pk),
            "field": attname,
            "expected": before,
            "current": now,
        },
    )
