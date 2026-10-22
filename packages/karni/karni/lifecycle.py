"""Lifecycle columns at runtime: transitions, their errors, their event and their history.

A :class:`~karni.fields.StateField` declares the lifecycle; this module runs
it. On any model that inherits :class:`karni.models.GuardedModel` (every
``BaseModel`` does):

* ``order.transition("status", "confirmed")`` is the explicit API. It checks
  the transition, writes the state (and any other ``field=value`` passed) in
  one conditional ``UPDATE ... WHERE "status" = 'draft'``, records the
  change and sends :data:`state_changed`.
* ``order.status = "confirmed"; order.save()`` is checked the same way,
  against the value the row had **when it was loaded** (tracked per
  instance), and written with the same conditional ``UPDATE``. When another
  transaction moved the state first, nothing is written and
  :class:`StateConflict` (``E981``, HTTP 409) names the state the row is in
  now — two concurrent transitions from one state never both succeed.
* An illegal transition raises :class:`IllegalTransition` (``E980``) naming
  the current state, the requested one and the legal ones — from the ORM,
  the admin (a form error), the API (a 400 on the field), management
  commands and tasks alike. A new row must start in an ``initial`` state
  (``E982``).
* Every transition leaves a change-log entry (``karni.audit``, action
  ``transition``, ``{"status": ["draft", "confirmed"]}``, with the actor) and
  sends :data:`state_changed`; ``karni.events.on_transition`` is the
  listener decorator.

Override / escape hatch: ``StateField(audit=False)`` skips the change-log
entry; :func:`any_initial_state` lets data loading create rows in any
declared state; ``QuerySet.update()`` bypasses the rules (the column's CHECK
still applies), exactly as it bypasses ``save()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.dispatch import Signal

from karni.conflicts import KarniConflict, Violation, column_check
from karni.errorcodes import KarniError
from karni.exceptions import KarniValueError
from karni.fields.state import StateField, _value

if TYPE_CHECKING:
    from karni.fields.state import StateMachine

__all__ = [
    "IllegalTransition",
    "StateConflict",
    "Transition",
    "allowed_transitions",
    "any_initial_state",
    "state_changed",
    "state_field",
    "state_fields",
    "transition",
]

#: Sent after a transition is written, inside the save's transaction:
#: ``sender`` (the model class), ``instance``, ``field`` (its name),
#: ``source``, ``target`` and ``using``.
state_changed = Signal()

_ANY_INITIAL: ContextVar[str | None] = ContextVar("karni_any_initial_state", default=None)


class IllegalTransition(KarniError, ValueError):
    """A state change the declared lifecycle does not allow (``E980``; ``E982`` for a new row).

    ``field``, ``current`` (``None`` for a new row), ``requested`` and
    ``allowed`` say what was refused; the API answers 400 on ``field``.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "E980",
        field: str = "",
        current: str | None = None,
        requested: str | None = None,
        allowed: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, code=code)
        self.field = field
        self.current = current
        self.requested = requested
        self.allowed = allowed


class StateConflict(KarniConflict):
    """The row's state changed since this instance was loaded (``E981``, HTTP 409)."""

    code = "E981"


@dataclass(frozen=True)
class Transition:
    """One state change a save writes."""

    field: StateField
    source: str
    target: str


@contextmanager
def any_initial_state(reason: str) -> Iterator[None]:
    """Create rows in any declared state inside the block (data loading, seeds, fixtures).

    ``reason`` is required and names why the initial-state rule does not
    apply. Transitions between existing rows are still checked, and the
    column's CHECK still refuses undeclared states.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise KarniValueError(
            "any_initial_state() needs reason='...': say why rows may skip the initial-state "
            "rule here (e.g. 'seed data').",
            code="E982",
        )
    token = _ANY_INITIAL.set(reason)
    try:
        yield
    finally:
        _ANY_INITIAL.reset(token)


_FIELDS: dict[type[models.Model], tuple[StateField, ...]] = {}


def state_fields(model: type[models.Model]) -> tuple[StateField, ...]:
    """Every :class:`StateField` of ``model`` (concrete fields, declaration order)."""
    found = _FIELDS.get(model)
    if found is None:
        found = tuple(f for f in model._meta.concrete_fields if isinstance(f, StateField))
        _FIELDS[model] = found
    return found


def state_field(model: type[models.Model], name: str) -> StateField:
    """``model``'s StateField called ``name`` (``E983`` when there is none)."""
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        field = None
    if not isinstance(field, StateField):
        names = ", ".join(f.name for f in state_fields(model)) or "none"
        raise KarniValueError(
            f"{model.__name__}.{name} is not a StateField (the model's StateFields: {names}). "
            f"Call transition() with one of them.",
            code="E983",
        )
    return field


def _label(instance: models.Model) -> str:
    pk = getattr(instance, "pk", None)
    return (
        f"{type(instance).__name__} {pk}" if pk is not None else f"a new {type(instance).__name__}"
    )


def _quoted(states: tuple[str, ...]) -> str:
    return ", ".join(repr(state) for state in states)


def _illegal(
    instance: models.Model, field: StateField, source: str, target: str
) -> IllegalTransition:
    machine: StateMachine = field.machine
    allowed = machine.allowed(source)
    name = f"{type(instance).__name__}.{field.name}"
    if target not in machine.states:
        message = (
            f"{_label(instance)}: {target!r} is not a state of {name} (declared: "
            f"{_quoted(machine.states)})."
        )
    elif allowed:
        message = (
            f"{_label(instance)}: {field.name} cannot go from {source!r} to {target!r}. From "
            f"{source!r} the legal transitions are: {_quoted(allowed)}. Move it to one of "
            f"those, or add {target!r} to transitions[{source!r}] on {name} if the lifecycle "
            "should allow it."
        )
    else:
        message = (
            f"{_label(instance)}: {field.name} is {source!r}, a terminal state of {name}: "
            f"nothing can leave it, so it cannot become {target!r}. Add a transition from "
            f"{source!r} on {name} if the lifecycle should allow one."
        )
    return IllegalTransition(
        message,
        code="E980",
        field=field.name,
        current=source,
        requested=target,
        allowed=allowed,
    )


def _not_initial(instance: models.Model, field: StateField, target: str) -> IllegalTransition:
    machine = field.machine
    name = f"{type(instance).__name__}.{field.name}"
    paths = [state for state in machine.states if target in machine.transitions[state]]
    via = f" (it is reached from {_quoted(tuple(paths))})" if paths else ""
    return IllegalTransition(
        f"A new {type(instance).__name__} cannot start with {field.name}={target!r}: rows of "
        f"{name} start in {_quoted(machine.initial)}{via}. Create it in "
        f"{machine.initial[0]!r} and call .transition({field.name!r}, {target!r}), or add "
        f"{target!r} to initial= on {name}.",
        code="E982",
        field=field.name,
        current=None,
        requested=target,
        allowed=machine.initial,
    )


def transition_problem(
    instance: models.Model, field: StateField, value: Any, source: Any = None
) -> IllegalTransition | None:
    """What is wrong with ``instance`` holding ``value`` in ``field``, or ``None``.

    A new row must hold an initial state (unless inside
    :func:`any_initial_state`); an existing row may only have moved along a
    declared transition from the state it was loaded with (``source``,
    default: the tracked loaded value; unknown means nothing to check).
    """
    from karni.guards import MISSING, loaded

    target = _value(value) if value is not None else None
    machine = field.machine
    if target is None:
        return None  # null / blank are the field's own validation
    if target not in machine.states:
        return _illegal(instance, field, target, target)
    if instance._state.adding:
        if target in machine.initial or _ANY_INITIAL.get() is not None:
            return None
        return _not_initial(instance, field, target)
    before = loaded(instance, field.attname) if source is None else source
    if before is MISSING or before is None or before == target:
        return None
    if machine.is_legal(before, target):
        return None
    return _illegal(instance, field, before, target)


def _current(instance: models.Model, field: StateField) -> str | None:
    from karni.guards import MISSING, loaded

    before = loaded(instance, field.attname)
    value = getattr(instance, field.attname) if before is MISSING else before
    return None if value is None else _value(value)


def allowed_transitions(instance: models.Model, field: str) -> tuple[str, ...]:
    """The states ``instance``'s ``field`` may move to now (from its loaded state)."""
    found = state_field(type(instance), field)
    if instance._state.adding:
        return found.machine.initial
    current = _current(instance, found)
    return found.machine.allowed(current) if current is not None else ()


def transition(instance: models.Model, field: str, to: Any, **values: Any) -> None:
    """Move ``instance``'s ``field`` to ``to`` and save it, with ``values`` in the same write.

    ``booking.transition("status", "confirmed", confirmed_at=now)`` checks
    the transition (:class:`IllegalTransition`), then writes ``status``,
    ``confirmed_at`` and ``updated_at`` in one ``UPDATE ... WHERE "status" =
    '<loaded state>'`` (:class:`StateConflict` when another transaction moved
    it first), records it in the change log and sends :data:`state_changed`.
    On failure the instance keeps its previous values.
    """
    found = state_field(type(instance), field)
    target = _value(to)
    if instance._state.adding or instance.pk is None:
        raise KarniValueError(
            f"{_label(instance)} is not saved yet: transition() moves an existing row. Create "
            f"it (it starts in {found.machine.default!r}), then call "
            f".transition({field!r}, {target!r}).",
            code="E980",
        )
    source = _current(instance, found)
    problem = transition_problem(instance, found, target, source=source)
    if problem is not None:
        raise problem
    concrete = {f.name: f for f in instance._meta.concrete_fields}
    unknown = sorted(name for name in values if name not in concrete)
    if unknown:
        raise KarniValueError(
            f"transition() on {type(instance).__name__} got {', '.join(unknown)}, which "
            f"{'is not a field' if len(unknown) == 1 else 'are not fields'} of the model. Pass "
            "only concrete fields to write together with the state.",
            code="E983",
        )
    attnames = [found.attname, *(concrete[name].attname for name in values)]
    previous = {attname: instance.__dict__.get(attname, _UNSET) for attname in attnames}
    update_fields = [found.name, *values]
    if "updated_at" in concrete and "updated_at" not in update_fields:
        update_fields.append("updated_at")
    setattr(instance, found.attname, target)
    for name, value in values.items():
        setattr(instance, name, value)
    try:
        instance.save(update_fields=update_fields)
    except BaseException:
        for attname, value in previous.items():
            if value is _UNSET:
                instance.__dict__.pop(attname, None)  # it was deferred: load it again on access
            else:
                instance.__dict__[attname] = value
        raise


_UNSET = object()


def record(instance: models.Model, changes: list[Transition], using: str) -> None:
    """Write each transition to the change log and send :data:`state_changed`."""
    if not changes:
        return
    if apps.is_installed("karni.audit"):
        from karni.audit.capture import record as audit_record

        for change in changes:
            if change.field.audit:
                audit_record(
                    instance, "transition", {change.field.name: [change.source, change.target]}
                )
    for change in changes:
        state_changed.send(
            sender=type(instance),
            instance=instance,
            field=change.field.name,
            source=change.source,
            target=change.target,
            using=using,
        )


def undeclared_state(
    found: Violation,
    model: type[models.Model],
    instance: models.Model | None,
    using: str | None,
) -> KarniError | None:
    """The CHECK of a StateField refused a value (raw or bulk write): ``E980``."""
    for field in state_fields(model):
        if column_check(found, model, field.column):
            value = getattr(instance, field.attname, None) if instance is not None else None
            shown = f" {value!r}" if value is not None else ""
            return IllegalTransition(
                f"The database refused{shown} for {model.__name__}.{field.name}: its CHECK "
                f"constraint allows only the declared states ({_quoted(field.machine.states)}).",
                code="E980",
                field=field.name,
                requested=None if value is None else _value(value),
                allowed=field.machine.states,
            )
    return None
