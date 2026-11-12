"""Row actions: named ``POST <resource>/<id>/<name>/`` steps, legal in some states and roles.

A lifecycle is moved by named actions (pay, ship, cancel, refund), not by a
free ``PATCH`` of its state. A viewset declares them once::

    from karni.api import BaseViewSet, HasRole, Owned, RowAction

    class OrderViewSet(BaseViewSet):
        model = Order
        access = Access(read=..., write=...)
        row_actions = {
            "pay": RowAction(from_="pending", by=Owned("buyer")),
            "ship": RowAction(from_="paid", to="shipped", by=Owned("listing__seller__user")),
            "refund": RowAction(from_="paid", to="refunded", by=HasRole("staff")),
        }

and gets, for each one:

* **the endpoint**: an action with ``to=`` and no method of its name on the
  class is routed by Karni: it moves the row's StateField to ``to`` with
  ``transition()`` (the fields ``class Karni: moves`` requires for that state
  are read from the request body) and answers the row. An action without
  ``to`` runs the viewset's own ``@action`` method of that name (``pay``
  opens a payment); ``karni check`` warns about one that has none yet (``W136``);
* **who may**: ``by`` is the action's access predicate (gate and row), like
  ``@action(access=...)``; without it the action follows ``access.write``;
* **where it is legal**: called while the row's state is not one of
  ``from_``, it is refused with a 409 naming the state and the legal ones
  (``E997``). An action with ``to`` whose row is already there answers 200
  and changes nothing, so calling it twice is safe;
* **the schema**: the list and detail operations carry ``x-karni-actions``
  (each action's ``from``, ``to``, ``field``, ``by`` and ``requires``), and
  each action's own operation ``x-karni-action``, the way a StateField
  publishes ``x-karni-transitions``, so a client shows only the buttons that
  are legal.

Override / escape hatches: define the method yourself (Karni still checks the
state and ``by`` first); override :meth:`RowAction.legal` for a rule that is
not a list of states; override ``BaseViewSet.run_row_action`` to change what
a generated action does.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from rest_framework.request import Request
from rest_framework.response import Response

from karni.conflicts import KarniConflict
from karni.exceptions import KarniImproperlyConfigured

__all__ = ["RowAction", "RowActionRefused", "guard", "row_action_handler", "state_field_of"]

#: Marks a handler Karni wrapped or generated, so a class never wraps it twice.
_GUARDED: Final = "_karni_row_action"


class RowActionRefused(KarniConflict):
    """A row action called in a state where it is not legal (``E997``, HTTP 409)."""

    code = "E997"


def _states(value: str | Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclass(frozen=True, init=False)
class RowAction:
    """One row action: the states it runs from, the state it moves to, who may run it.

    :param from_: the states of ``field`` the action may run from (one, or a
        list). Empty: any state.
    :param to: the state the action moves the row to, or ``None`` when the
        viewset's own method does the work.
    :param by: the access predicate of the action (default: ``access.write``).
    :param field: the StateField the states belong to (default: the model's
        only StateField).
    """

    from_: tuple[str, ...]
    to: str | None
    by: Any
    field: str | None

    def __init__(
        self,
        *,
        from_: str | Iterable[str] | None = None,
        to: str | None = None,
        by: Any = None,
        field: str | None = None,
    ) -> None:
        from karni.api.access import Predicate

        if by is not None and not isinstance(by, Predicate):
            raise KarniImproperlyConfigured(
                f"RowAction(by=...) takes a predicate such as Owned('buyer') or "
                f"HasRole('staff'), got {by!r}.",
                code="E103",
            )
        object.__setattr__(self, "from_", _states(from_))
        object.__setattr__(self, "to", to)
        object.__setattr__(self, "by", by)
        object.__setattr__(self, "field", field)

    def legal(self, state: Any) -> bool:
        """Whether the action may run while the row holds ``state``."""
        return not self.from_ or str(state) in self.from_

    def describe(self, model: Any = None) -> dict[str, Any]:
        """The action as ``x-karni-actions`` publishes it."""
        field = state_field_of(model, self) if model is not None else self.field
        requires: list[str] = []
        if model is not None and self.to is not None and field is not None:
            requires = list(_required(model, field, self.to))
        return {
            "from": list(self.from_),
            "to": self.to,
            "field": field,
            "by": self.by.describe() if self.by is not None else None,
            "requires": requires,
        }


def state_field_of(model: Any, declared: RowAction) -> str | None:
    """The name of the StateField ``declared`` moves or reads (``None``: the model has none)."""
    if declared.field is not None:
        return declared.field
    from karni.lifecycle import state_fields

    fields = state_fields(model)
    if len(fields) == 1:
        return fields[0].name
    return None


def _required(model: Any, field: str, to: str) -> tuple[str, ...]:
    """The fields ``class Karni: moves`` requires for a move of ``field`` into ``to``."""
    from karni.rules import rules_of

    found: list[str] = []
    for move in rules_of(model).moves:
        if move.field == field and move.to == to:
            found.extend(move.requires)
    return tuple(found)


def _state(view: Any, instance: Any, declared: RowAction, name: str) -> Any:
    field = state_field_of(type(instance), declared)
    if field is None:
        raise KarniImproperlyConfigured(
            f"{type(view).__name__}.row_actions[{name!r}] names states, but "
            f"{type(instance).__name__} has no single StateField: pass "
            "RowAction(field='<the StateField>').",
            code="E136",
        )
    return field, getattr(instance, field)


def guard(name: str, method: Callable[..., Any]) -> Callable[..., Any]:
    """``method`` (a viewset's ``@action``), run only where ``row_actions[name]`` allows."""
    if getattr(method, _GUARDED, False):
        return method

    @functools.wraps(method)
    def guarded(self: Any, request: Request, *args: Any, **kwargs: Any) -> Any:
        declared: RowAction = type(self).row_actions[name]
        instance = self.get_object()
        self.__dict__["_karni_row_object"] = instance
        try:
            field, state = _state(self, instance, declared, name)
            if declared.to is not None and str(state) == declared.to:
                return Response(self.get_serializer(instance).data)  # done already: safe twice
            if not declared.legal(state):
                legal = ", ".join(repr(item) for item in declared.from_)
                raise RowActionRefused(
                    f"{type(instance).__name__} {instance.pk} is {state!r}, and {name} runs only "
                    f"from {legal}. Reload the row: x-karni-actions lists what it allows now.",
                    field=field,
                    details={"action": name, "state": str(state), "from": list(declared.from_)},
                )
            return method(self, request, *args, **kwargs)
        finally:
            self.__dict__.pop("_karni_row_object", None)

    setattr(guarded, _GUARDED, True)
    return guarded


def row_action_handler(name: str, declared: RowAction) -> Callable[..., Any]:
    """The routed handler Karni writes for a row action with ``to`` and no method of its own."""
    from rest_framework.decorators import action

    def handler(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.run_row_action(name, request)  # type: ignore[no-any-return]

    handler.__name__ = name
    handler.__qualname__ = name
    handler.__doc__ = (
        f"Move the row to {declared.to!r}"
        + (f" from {', '.join(declared.from_)}" if declared.from_ else "")
        + " (a row action: x-karni-action)."
    )
    routed = action(detail=True, methods=["post"], url_path=name)(handler)
    return guard(name, routed)


def run(view: Any, name: str, request: Request) -> Response:
    """What a generated row action does: ``transition()`` to ``to``, then the row."""
    declared: RowAction = type(view).row_actions[name]
    instance = view.get_object()
    field = state_field_of(type(instance), declared)
    data: Mapping[str, Any] = request.data if isinstance(request.data, Mapping) else {}
    wanted = _required(type(instance), str(field), str(declared.to))
    values = {key: data[key] for key in wanted if key in data}
    instance.transition(str(field), declared.to, **values)
    return Response(view.get_serializer(instance).data)


def install(cls: Any) -> None:
    """Route and guard the row actions a viewset class declares (``__init_subclass__``)."""
    declared = cls.__dict__.get("row_actions")
    if declared is not None and not isinstance(declared, Mapping):
        raise KarniImproperlyConfigured(
            f"{cls.__name__}.row_actions must map an action name to RowAction(...), got "
            f"{declared!r}.",
            code="E136",
        )
    for name, item in (getattr(cls, "row_actions", None) or {}).items():
        if not isinstance(item, RowAction):
            raise KarniImproperlyConfigured(
                f"{cls.__name__}.row_actions[{name!r}] must be a RowAction(...), got {item!r}.",
                code="E136",
            )
        own = cls.__dict__.get(name)
        if own is not None:
            if callable(own) and hasattr(own, "mapping"):
                setattr(cls, name, guard(name, own))
            continue
        if getattr(cls, name, None) is None and item.to is not None:
            setattr(cls, name, row_action_handler(name, item))


def missing_methods(cls: Any) -> list[str]:
    """Row actions without ``to`` that the class has no ``@action`` method for (``W136``)."""
    return [
        name
        for name, item in (getattr(cls, "row_actions", None) or {}).items()
        if isinstance(item, RowAction)
        and item.to is None
        and not hasattr(getattr(cls, name, None), "mapping")
    ]


def described(cls: Any, model: Any) -> dict[str, Any]:
    """``x-karni-actions``: every row action of ``cls`` as :meth:`RowAction.describe` gives it."""
    return {
        name: item.describe(model)
        for name, item in (getattr(cls, "row_actions", None) or {}).items()
        if isinstance(item, RowAction)
    }
