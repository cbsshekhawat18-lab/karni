"""Vetoes: a registered callable that may refuse an action a user otherwise holds.

The access declaration and the roles' grants say what a user *may* do;
a veto says what they may *not* do right now, whatever they hold — the
``karni-impersonation`` module blocks deleting, exporting and payment
changes for the length of an impersonated session. Karni consults the
registry at every gate it owns and refuses with the veto's reason:

* the API's :class:`karni.api.access.AccessPermission` (``kind="api"``,
  the viewset action and, when known, its ``app.model:action`` permission);
* the admin's ``has_add/change/delete_permission`` (``kind="admin"``), its
  action list (``delete_selected``, ``export_csv``, …) and the import page.

A veto receives a :class:`VetoContext` and returns a reason (a string) to
refuse or ``None`` to allow. Register one from an app's ``ready()``::

    from karni.vetoes import register_veto

    def no_deletes_on_fridays(context):
        if context.action in {"destroy", "delete", "delete_selected"} and it_is_friday():
            return "No deletes on Fridays."
        return None

    register_veto(no_deletes_on_fridays, name="friday")

Override / escape hatch: :func:`unregister_veto` by name; a veto that only
answers for its own condition (an impersonated session, a maintenance
window) costs a function call per gate otherwise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db.models import Model

__all__ = ["Veto", "VetoContext", "check_vetoes", "register_veto", "unregister_veto", "vetoes"]


@dataclass(frozen=True)
class VetoContext:
    """What is about to happen: where (``kind``), what (``action``), to which model."""

    request: Any
    kind: str
    action: str
    model: type[Model] | None = None
    permission: str | None = None
    view: Any = None

    def names(self) -> frozenset[str]:
        """Every name a pattern may match: action, permission, model label, ``model:action``."""
        found = {self.action}
        if self.permission:
            found.add(self.permission)
        if self.model is not None:
            label = self.model._meta.label_lower
            found.add(label)
            found.add(f"{label}:{self.action}")
        return frozenset(found)


Veto = Callable[[VetoContext], str | None]

_VETOES: dict[str, Veto] = {}


def register_veto(fn: Veto, *, name: str | None = None) -> None:
    """Register ``fn`` (replacing a veto of the same ``name``; default: the function's module)."""
    _VETOES[name or f"{fn.__module__}.{fn.__qualname__}"] = fn


def unregister_veto(name: str) -> None:
    _VETOES.pop(name, None)


def vetoes() -> dict[str, Veto]:
    """The registered vetoes by name (a copy)."""
    return dict(_VETOES)


def check_vetoes(context: VetoContext) -> str | None:
    """The first reason a registered veto gives, or ``None``."""
    for fn in _VETOES.values():
        reason = fn(context)
        if reason:
            return str(reason)
    return None
