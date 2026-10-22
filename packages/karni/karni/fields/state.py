"""``StateField``: a lifecycle column with declared states and legal transitions.

A status column written as a free ``CharField`` accepts any string from any
code path, and nothing stops ``confirmed`` from going back to ``draft``.
Neither shows up in tests. ``StateField`` declares the lifecycle once::

    from karni.fields import StateField

    class Order(BaseModel):
        status = StateField(
            states=["draft", "confirmed", "cancelled", "refunded"],
            transitions={
                "draft": ["confirmed", "cancelled"],
                "confirmed": ["cancelled", "refunded"],
            },
        )

and every layer enforces it:

* **The database.** The column carries ``CHECK ("status" IN ('draft', ...))``,
  so raw SQL cannot write an undeclared state (PostgreSQL and SQLite alike).
* **The model.** ``order.transition("status", "confirmed")`` and plain
  assignment followed by ``save()`` are both checked against the transitions,
  from the value the row had when it was loaded. The ``UPDATE`` is
  conditional (``... WHERE "status" = 'draft'``), so two concurrent
  transitions from the same state cannot both succeed. That part lives in
  :class:`karni.models.GuardedModel`, which :class:`~karni.models.BaseModel`
  includes. Details: :mod:`karni.lifecycle`.
* **Forms and the API.** ``Field.validate`` refuses an illegal transition in
  the admin, and the generated serializer answers 400 naming the legal ones.

Defaults: the default state is ``default=`` or else the first state; a row
may be created only in an ``initial`` state (default: just the default
state); a state without outgoing transitions is *terminal*.

Override / escape hatch: ``initial=`` widens the states a row may start in;
``audit=False`` stops recording transitions in the change log;
``karni.lifecycle.any_initial_state(reason=...)`` lets data loading create
rows in any declared state (Karni's factories and seeders use it).
``QuerySet.update()`` and ``bulk_create()`` bypass the transition rules
(never the CHECK), exactly as they bypass ``save()``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models.fields import NOT_PROVIDED

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["StateField", "StateMachine"]

#: A state value: letters, digits, ``_`` and ``-`` (it is written into a CHECK constraint).
_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MIN_LENGTH = 20


def _value(state: Any) -> str:
    """A state as text: a ``TextChoices`` member or a plain string."""
    return str(getattr(state, "value", state))


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").title()


@dataclass(frozen=True)
class StateMachine:
    """The lifecycle a :class:`StateField` declares.

    ``transitions`` maps every state to the states it may move to (a
    terminal state maps to ``()``); ``initial`` lists the states a row may be
    created in.
    """

    states: tuple[str, ...]
    labels: Mapping[str, str]
    transitions: Mapping[str, tuple[str, ...]]
    initial: tuple[str, ...]
    default: str

    @property
    def terminal(self) -> tuple[str, ...]:
        """States nothing can leave."""
        return tuple(state for state in self.states if not self.transitions[state])

    def allowed(self, source: str | None) -> tuple[str, ...]:
        """The states ``source`` may move to (the initial states when ``source`` is ``None``)."""
        if source is None:
            return self.initial
        return self.transitions.get(source, ())

    def is_legal(self, source: str, target: str) -> bool:
        return target in self.transitions.get(source, ())

    def as_schema(self) -> dict[str, Any]:
        """The OpenAPI vendor extensions (``x-karni-transitions``, ``x-karni-initial``)."""
        return {
            "x-karni-transitions": {state: list(self.transitions[state]) for state in self.states},
            "x-karni-initial": list(self.initial),
        }


def _states(owner: str, states: Any) -> list[tuple[str, str]]:
    """``[(value, label)]`` from a list of values, ``(value, label)`` pairs or a Choices class."""
    if isinstance(states, type) and issubclass(states, models.Choices):
        members: Any = states
        pairs = [(_value(member), str(member.label)) for member in members]
    elif isinstance(states, str) or not isinstance(states, Iterable):
        raise KarniImproperlyConfigured(
            f"{owner}: states must be a list of state names (or a TextChoices class), got "
            f"{states!r}. Example: StateField(states=['draft', 'confirmed', 'cancelled'], ...).",
            code="E983",
        )
    else:
        pairs = []
        for item in states:
            if isinstance(item, list | tuple) and len(item) == 2:
                pairs.append((_value(item[0]), str(item[1])))
            else:
                pairs.append((_value(item), _label(_value(item))))
    if not pairs:
        raise KarniImproperlyConfigured(
            f"{owner}: states is empty. Declare every state the column may hold, e.g. "
            "states=['draft', 'confirmed', 'cancelled'].",
            code="E983",
        )
    seen: set[str] = set()
    for value, _ in pairs:
        if not _STATE.match(value):
            raise KarniImproperlyConfigured(
                f"{owner}: state {value!r} may only use letters, digits, '_' and '-' (it is "
                "written into the column's CHECK constraint). Rename it, e.g. 'in_progress'.",
                code="E983",
            )
        if value in seen:
            raise KarniImproperlyConfigured(
                f"{owner}: state {value!r} is declared twice.", code="E983"
            )
        seen.add(value)
    return pairs


def build_machine(
    owner: str,
    states: Any,
    transitions: Any,
    initial: Any = None,
    default: Any = NOT_PROVIDED,
) -> StateMachine:
    """Validate a declaration and return its :class:`StateMachine` (``E983`` when invalid)."""
    pairs = _states(owner, states)
    values = tuple(value for value, _ in pairs)
    declared = set(values)
    if not isinstance(transitions, Mapping):
        raise KarniImproperlyConfigured(
            f"{owner}: transitions must be a dict of state -> list of states it may move to, "
            "e.g. transitions={'draft': ['confirmed', 'cancelled'], 'confirmed': ['cancelled']}.",
            code="E983",
        )
    edges: dict[str, tuple[str, ...]] = {value: () for value in values}
    for raw_source, raw_targets in transitions.items():
        source = _value(raw_source)
        if source not in declared:
            raise KarniImproperlyConfigured(
                f"{owner}: transitions names {source!r}, which is not one of the declared "
                f"states ({', '.join(values)}). Add it to states= or fix the spelling.",
                code="E983",
            )
        if isinstance(raw_targets, str) or not isinstance(raw_targets, Iterable):
            raise KarniImproperlyConfigured(
                f"{owner}: transitions[{source!r}] must be a list of states, got "
                f"{raw_targets!r}. Write {source!r}: [{_value(raw_targets)!r}].",
                code="E983",
            )
        targets = tuple(dict.fromkeys(_value(target) for target in raw_targets))
        for target in targets:
            if target not in declared:
                raise KarniImproperlyConfigured(
                    f"{owner}: transitions[{source!r}] names {target!r}, which is not one of "
                    f"the declared states ({', '.join(values)}).",
                    code="E983",
                )
            if target == source:
                raise KarniImproperlyConfigured(
                    f"{owner}: transitions[{source!r}] lists {source!r} itself. Saving the same "
                    "state is never a transition. Remove it.",
                    code="E983",
                )
        edges[source] = targets
    unset = default is NOT_PROVIDED or default is None
    default_value = values[0] if unset else _value(default)
    if (not unset and callable(default)) or default_value not in declared:
        raise KarniImproperlyConfigured(
            f"{owner}: default must be one of the declared states ({', '.join(values)}), got "
            f"{default!r}.",
            code="E983",
        )
    if initial is None:
        starts: tuple[str, ...] = (default_value,)
    elif isinstance(initial, str) or not isinstance(initial, Iterable):
        raise KarniImproperlyConfigured(
            f"{owner}: initial must be a list of states, got {initial!r}.", code="E983"
        )
    else:
        starts = tuple(dict.fromkeys(_value(state) for state in initial))
        unknown = [state for state in starts if state not in declared]
        if unknown:
            raise KarniImproperlyConfigured(
                f"{owner}: initial names {', '.join(map(repr, unknown))}, which "
                f"{'is' if len(unknown) == 1 else 'are'} not declared in states=.",
                code="E983",
            )
        if default_value not in starts:
            raise KarniImproperlyConfigured(
                f"{owner}: the default state {default_value!r} must be one of the initial "
                f"states {list(starts)!r}: a row created without a state starts in the default.",
                code="E983",
            )
    reachable = set(starts)
    frontier = list(starts)
    while frontier:
        for target in edges[frontier.pop()]:
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    stranded = [value for value in values if value not in reachable]
    if stranded:
        raise KarniImproperlyConfigured(
            f"{owner}: no transition leads to {', '.join(map(repr, stranded))} and "
            f"{'it is' if len(stranded) == 1 else 'they are'} not an initial state, so no row "
            "could ever enter it. Add a transition into it (or list it in initial=).",
            code="E983",
        )
    return StateMachine(
        states=values,
        labels=dict(pairs),
        transitions=edges,
        initial=starts,
        default=default_value,
    )


class StateField(models.CharField):
    """A ``CharField`` whose value is one of declared states, changed only along transitions.

    :param states: every state, in display order: names, ``(value, label)``
        pairs, or a ``TextChoices`` class.
    :param transitions: ``{state: [states it may move to]}``; a state left out
        is terminal.
    :param initial: the states a row may be created in (default: the default state).
    :param audit: record each transition in the change log (``karni.audit``).

    ``default=`` (default: the first state), ``max_length`` (default: the
    longest state, at least 20) and ``choices`` (from ``states``) are derived.
    """

    description = "A lifecycle state with declared transitions"
    non_db_attrs = (*models.CharField.non_db_attrs, "transitions", "initial", "audit")

    def __init__(
        self,
        *args: Any,
        states: Any = None,
        transitions: Mapping[Any, Iterable[Any]] | None = None,
        initial: Iterable[Any] | None = None,
        audit: bool = True,
        **kwargs: Any,
    ) -> None:
        owner = "StateField"
        if states is None:
            raise KarniImproperlyConfigured(
                "StateField needs states=[...] (and transitions={...}): the lifecycle is the "
                "point of the field. Example: StateField(states=['draft', 'confirmed'], "
                "transitions={'draft': ['confirmed']}).",
                code="E983",
            )
        if "choices" in kwargs:
            raise KarniImproperlyConfigured(
                "StateField derives its choices from states=, so remove choices=.", code="E983"
            )
        self.machine = build_machine(
            owner,
            states,
            {} if transitions is None else transitions,
            initial,
            kwargs.get("default", NOT_PROVIDED),
        )
        self.audit = audit
        longest = max(len(state) for state in self.machine.states)
        kwargs.setdefault("max_length", max(_MIN_LENGTH, longest))
        if kwargs["max_length"] < longest:
            raise KarniImproperlyConfigured(
                f"StateField: max_length={kwargs['max_length']} is shorter than the state "
                f"{max(self.machine.states, key=len)!r}. Drop max_length= (it is derived).",
                code="E983",
            )
        kwargs["default"] = self.machine.default
        kwargs["choices"] = [(state, self.machine.labels[state]) for state in self.machine.states]
        super().__init__(*args, **kwargs)

    @property
    def states(self) -> tuple[str, ...]:
        return self.machine.states

    @property
    def transitions(self) -> Mapping[str, tuple[str, ...]]:
        return self.machine.transitions

    @property
    def initial(self) -> tuple[str, ...]:
        return self.machine.initial

    @property
    def terminal(self) -> tuple[str, ...]:
        return self.machine.terminal

    if TYPE_CHECKING:  # the instance attribute holds the state string, not the field

        def __get__(self, instance: Any, owner: Any) -> Any: ...
        def __set__(self, instance: Any, value: Any) -> None: ...

    def deconstruct(self) -> Any:
        name, _path, args, kwargs = super().deconstruct()
        kwargs.pop("choices", None)
        longest = max(len(state) for state in self.machine.states)
        if kwargs.get("max_length") == max(_MIN_LENGTH, longest):
            kwargs.pop("max_length")
        if kwargs.get("default") == self.machine.states[0]:
            kwargs.pop("default")
        labels = self.machine.labels
        if all(labels[state] == _label(state) for state in self.machine.states):
            kwargs["states"] = list(self.machine.states)
        else:
            kwargs["states"] = [[state, labels[state]] for state in self.machine.states]
        kwargs["transitions"] = {
            state: list(targets) for state, targets in self.machine.transitions.items() if targets
        }
        if self.machine.initial != (self.machine.default,):
            kwargs["initial"] = list(self.machine.initial)
        if not self.audit:
            kwargs["audit"] = False
        return name, "karni.fields.StateField", args, kwargs

    def db_check(self, connection: Any) -> str:
        """``"<column>" IN ('draft', ...)`` — the database refuses an undeclared state."""
        values = ", ".join(f"'{state}'" for state in self.machine.states)
        return f"{connection.ops.quote_name(self.column)} IN ({values})"

    def validate(self, value: Any, model_instance: Any) -> None:
        """Choices first, then the lifecycle rules (``E980`` / ``E982``) — what forms run."""
        super().validate(value, model_instance)
        if model_instance is None:
            return
        from django.core.exceptions import ValidationError

        from karni.lifecycle import transition_problem

        problem = transition_problem(model_instance, self, value)
        if problem is not None:
            raise ValidationError(f"{problem.code}: {problem.message}", code=problem.code)
