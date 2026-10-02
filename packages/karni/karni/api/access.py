"""Declarative access control for :class:`karni.api.viewsets.BaseViewSet` (ADR 0001, Decision 2).

One declaration per viewset, compiled into both enforcement layers::

    from karni.api import Access, Authenticated, BaseViewSet, HasRole, Owned

    class EventViewSet(BaseViewSet):
        model = Event
        access = Access(
            read=Owned("organizer") | HasRole("staff"),
            write=Owned("organizer"),
            create=Authenticated(),          # organizer is stamped server-side
        )

* **Request gate** — :class:`AccessPermission`, a DRF permission class that
  ``BaseViewSet.get_permissions()`` always puts first. It answers 401/403
  before any query runs.
* **Row policy** — the ``read`` predicate compiled to a ``Q`` and applied in
  ``BaseViewSet.get_queryset()`` after the model's own scopes (soft delete,
  later tenant) and the viewset's base queryset. It is authoritative: lists,
  details, custom actions, relation-field PK validation and ``?expand=`` all
  go through it. Out of scope → 404; readable but not writable → 403.

Per action: ``list``/``retrieve`` and safe custom actions use ``read``;
``create`` uses ``create`` (default: ``write``); ``update``/
``partial_update``/``destroy`` and unsafe custom actions use ``write``;
``@action(..., access=HasRole("x"))`` replaces the predicate for one action.

The vocabulary is closed (ADR 0001 Q2.8): :class:`Owned`, :class:`HasRole`
(+ the reserved :class:`Can`), :class:`Authenticated`, :class:`Public`,
:class:`Where`, :class:`Unscoped`, ``|`` and ``&``. Every predicate has a
request-level answer (:meth:`Predicate.allows`) and a row-level answer
(:meth:`Predicate.rows`: ``True`` = every row, ``False`` = no row, or a
``Q``). No predicate can lift a model-level scope: the row ``Q`` is only ever
``filter()``-ed onto the model's default manager.

Escape hatches, least to most drastic: change the declaration; ``Where(...)``
for arbitrary row logic; override ``filter_queryset_for_user`` (needs
``# karni: allow(access-override): <reason>``); ``access =
Unscoped(reason="...")`` (plain DRF ``permission_classes``, no row policy);
``auto_register = False`` plus your own view. ``get_access()`` on the viewset
may return a declaration computed at request time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import Model, Q, QuerySet
from django.db.models.constants import LOOKUP_SEP
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

if TYPE_CHECKING:
    from rest_framework.request import Request

__all__ = [
    "Access",
    "AccessPermission",
    "AllOf",
    "AnyOf",
    "Authenticated",
    "Can",
    "HasRole",
    "Owned",
    "Predicate",
    "Public",
    "RowFilter",
    "Unscoped",
    "Where",
    "action_predicate",
    "apply_rows",
    "describe_access",
    "missing_access_message",
    "readable",
    "target_read_scope",
]

logger = logging.getLogger(__name__)

type RowFilter = bool | Q
"""Row-level answer: ``True`` (every row), ``False`` (no row) or a ``Q``."""

#: Standard ``ModelViewSet`` actions → the ``Access`` slot that governs them.
ACTION_SLOTS: Final[dict[str, str]] = {
    "list": "read",
    "retrieve": "read",
    "create": "create",
    "update": "write",
    "partial_update": "write",
    "destroy": "write",
}

_ROLE_CACHE: Final = "_karni_access_roles"
_VIEW_CACHE: Final = "_karni_access_target_views"

OWNED_NEEDS_A_FIELD: Final = (
    "Owned() needs the owner field: name the relation to the user model, e.g. "
    'Owned("organizer") or Owned("event__organizer"). Use Owned("created_by") '
    "only when whoever created the row is its owner (ADR 0001 Q2.6)."
)


# --- request helpers ---------------------------------------------------------


def _user(request: Any) -> Any:
    return getattr(request, "user", None)


def _authenticated(request: Any) -> bool:
    user = _user(request)
    return bool(user is not None and getattr(user, "is_authenticated", False))


def request_roles(request: Any) -> frozenset[str]:
    """The requesting user's role names, looked up once per request.

    Backed by :func:`karni.accounts.permissions.user_roles` (Django groups);
    cached on the request so any number of :class:`HasRole` checks cost one
    query (ADR 0001 R5).
    """
    from karni.accounts.permissions import user_roles

    if not _authenticated(request):
        return frozenset()
    user = _user(request)
    cache: dict[Any, frozenset[str]] = request.__dict__.setdefault(_ROLE_CACHE, {})
    key = getattr(user, "pk", None)
    if key not in cache:
        cache[key] = frozenset(user_roles(user))
    return cache[key]


def _or(left: RowFilter, right: RowFilter) -> RowFilter:
    if left is True or right is True:
        return True
    if left is False:
        return right
    if right is False:
        return left
    return left | right


def _and(left: RowFilter, right: RowFilter) -> RowFilter:
    if left is False or right is False:
        return False
    if left is True:
        return right
    if right is True:
        return left
    return left & right


# --- the predicate vocabulary -------------------------------------------------


class Predicate:
    """Base of every access predicate. Combine with ``|`` and ``&``.

    Subclasses answer two questions: :meth:`allows` (request level, the
    gate) and :meth:`rows` (row level, the queryset filter). Using ``or`` /
    ``and`` / ``not`` on a predicate raises ``TypeError`` — Python would
    silently keep only one operand.
    """

    __slots__ = ()

    def allows(self, request: Any) -> bool:
        """Request-level answer: may this request reach the action at all?"""
        raise NotImplementedError

    def rows(self, request: Any) -> RowFilter:
        """Row-level answer for this request: ``True``, ``False`` or a ``Q``."""
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        """JSON-serialisable form, published as the ``x-karni-access`` extension."""
        raise NotImplementedError

    def owned(self) -> Iterator[Owned]:
        """Every :class:`Owned` inside this predicate (validation, owner stamping)."""
        return iter(())

    def __or__(self, other: object) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return AnyOf((*_flatten(self, AnyOf), *_flatten(other, AnyOf)))

    def __and__(self, other: object) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return AllOf((*_flatten(self, AllOf), *_flatten(other, AllOf)))

    def __bool__(self) -> bool:
        raise TypeError(
            "Access predicates combine with | and & (e.g. Owned('user') | HasRole('staff')); "
            "`or`, `and` and `not` would silently drop one side."
        )


def _flatten(predicate: Predicate, kind: type[AnyOf] | type[AllOf]) -> tuple[Predicate, ...]:
    if isinstance(predicate, kind):
        return predicate.parts
    return (predicate,)


@dataclass(frozen=True, init=False, repr=False)
class Owned(Predicate):
    """Rows whose ``path`` points at the requesting user.

    ``path`` is a relation lookup ending at the user model: a forward FK
    (``"organizer"``), a traversal (``"event__organizer"``) or a to-many path
    (``"members"``; the queryset gets ``distinct()`` automatically). On the
    user model itself ``Owned("pk")`` means "the user's own row". The request
    gate requires authentication.

    ``bypass=`` ORs in another predicate, e.g.
    ``Owned("user", bypass=HasRole("payments-admin"))`` — the same as
    ``Owned("user") | HasRole("payments-admin")``.

    A direct FK named by ``Owned`` in ``write``/``create`` is the **owner
    field**: it is read-only in the generated serializer and stamped from
    ``request.user`` on create.
    """

    path: str
    bypass: Predicate | None = field(default=None)

    def __init__(self, path: str | None = None, *, bypass: Predicate | None = None) -> None:
        if path is None or path == "":
            raise ImproperlyConfigured(OWNED_NEEDS_A_FIELD)
        if not isinstance(path, str):
            raise ImproperlyConfigured(
                f"Owned() takes the owner field's name as a string, got {path!r}. "
                + OWNED_NEEDS_A_FIELD
            )
        if bypass is not None and not isinstance(bypass, Predicate):
            raise ImproperlyConfigured(
                f"Owned(bypass=...) takes a predicate such as HasRole('admin'), got {bypass!r}."
            )
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "bypass", bypass)

    def allows(self, request: Any) -> bool:
        if _authenticated(request):
            return True
        return self.bypass is not None and self.bypass.allows(request)

    def rows(self, request: Any) -> RowFilter:
        own: RowFilter = False
        if _authenticated(request):
            user = _user(request)
            last = self.path.rsplit(LOOKUP_SEP, 1)[-1]
            # A relation path compares against the user; the user model's own
            # primary key ("pk"/"id") compares against its value.
            value = user.pk if last in {"pk", user._meta.pk.name} else user
            own = Q(**{self.path: value})
        if self.bypass is None:
            return own
        return _or(own, self.bypass.rows(request))

    def describe(self) -> dict[str, Any]:
        own = {"owned": self.path}
        if self.bypass is None:
            return own
        return {"any": [own, *_flatten_described(self.bypass, "any")]}

    def owned(self) -> Iterator[Owned]:
        yield self
        if self.bypass is not None:
            yield from self.bypass.owned()

    def __repr__(self) -> str:
        if self.bypass is None:
            return f"Owned({self.path!r})"
        return f"Owned({self.path!r}, bypass={self.bypass!r})"


@dataclass(frozen=True, init=False, repr=False)
class HasRole(Predicate):
    """The requesting user holds **any** of the named roles (Django groups).

    Request level and row level agree: holders see every row (subject to
    the other predicates it is combined with), everyone else none. Role
    names are looked up once per request (:func:`request_roles`).
    """

    names: tuple[str, ...]

    def __init__(self, *names: str) -> None:
        if not names or not all(isinstance(name, str) and name for name in names):
            raise ImproperlyConfigured(
                "HasRole() needs one or more role (group) names, e.g. HasRole('staff')."
            )
        object.__setattr__(self, "names", tuple(names))

    def allows(self, request: Any) -> bool:
        return not request_roles(request).isdisjoint(self.names)

    def rows(self, request: Any) -> RowFilter:
        return self.allows(request)

    def describe(self) -> dict[str, Any]:
        return {"role": list(self.names)}

    def __repr__(self) -> str:
        return f"HasRole({', '.join(repr(name) for name in self.names)})"


class Can(Predicate):
    """Reserved for DB-backed ``area:action`` grants (ADR 0001 Q2.2).

    Not available yet: constructing it raises. Declarations written against
    :class:`HasRole` keep working when the grants tier arrives.
    """

    __slots__ = ()

    def __init__(self, *grants: str) -> None:
        raise ImproperlyConfigured(
            "Can(...) is reserved for the DB-grants tier (ADR 0001 Q2.2) and is not "
            "available yet; use HasRole(...) over Django groups."
        )


@dataclass(frozen=True, repr=False)
class Authenticated(Predicate):
    """Any authenticated user; every row."""

    def allows(self, request: Any) -> bool:
        return _authenticated(request)

    def rows(self, request: Any) -> RowFilter:
        return _authenticated(request)

    def describe(self) -> dict[str, Any]:
        return {"authenticated": True}

    def __repr__(self) -> str:
        return "Authenticated()"


@dataclass(frozen=True, repr=False)
class Public(Predicate):
    """Everyone, anonymous included; every row. The explicit public form."""

    def allows(self, request: Any) -> bool:
        return True

    def rows(self, request: Any) -> RowFilter:
        return True

    def describe(self) -> dict[str, Any]:
        return {"public": True}

    def __repr__(self) -> str:
        return "Public()"


@dataclass(frozen=True, repr=False)
class Where(Predicate):
    """Arbitrary logic: ``Where(lambda request: Q(...))``.

    The function receives the request and returns either a ``Q`` (a row
    filter; the request gate passes) or a ``bool`` (both the gate and the
    rows: ``True`` everything, ``False`` nothing). It must cope with
    anonymous requests — check ``request.user.is_authenticated`` before
    using the user. Add ``Owned``/``Authenticated`` with ``&`` instead when
    that is all you need.
    """

    fn: Callable[[Any], Q | bool]

    def __post_init__(self) -> None:
        if not callable(self.fn):
            raise ImproperlyConfigured(
                f"Where() takes a function of the request, got {self.fn!r}; "
                "e.g. Where(lambda request: Q(published=True))."
            )

    def _evaluate(self, request: Any) -> Q | bool:
        value = self.fn(request)
        if isinstance(value, Q | bool):
            return value
        raise ImproperlyConfigured(
            f"{self!r} returned {value!r}; a Where() function must return a Q or a bool."
        )

    def allows(self, request: Any) -> bool:
        value = self._evaluate(request)
        return value if isinstance(value, bool) else True

    def rows(self, request: Any) -> RowFilter:
        return self._evaluate(request)

    def describe(self) -> dict[str, Any]:
        return {"where": self._name()}

    def _name(self) -> str:
        name = getattr(self.fn, "__name__", "") or type(self.fn).__name__
        return "lambda" if name == "<lambda>" else name

    def __repr__(self) -> str:
        return f"Where({self._name()})"


@dataclass(frozen=True, repr=False)
class AnyOf(Predicate):
    """``a | b | …`` — produced by ``|``; any part may grant."""

    parts: tuple[Predicate, ...]

    def allows(self, request: Any) -> bool:
        return any(part.allows(request) for part in self.parts)

    def rows(self, request: Any) -> RowFilter:
        result: RowFilter = False
        for part in self.parts:
            result = _or(result, part.rows(request))
            if result is True:
                break
        return result

    def describe(self) -> dict[str, Any]:
        return {"any": [d for part in self.parts for d in _flatten_described(part, "any")]}

    def owned(self) -> Iterator[Owned]:
        for part in self.parts:
            yield from part.owned()

    def __repr__(self) -> str:
        return " | ".join(repr(part) for part in self.parts)


@dataclass(frozen=True, repr=False)
class AllOf(Predicate):
    """``a & b & …`` — produced by ``&``; every part must grant."""

    parts: tuple[Predicate, ...]

    def allows(self, request: Any) -> bool:
        return all(part.allows(request) for part in self.parts)

    def rows(self, request: Any) -> RowFilter:
        result: RowFilter = True
        for part in self.parts:
            result = _and(result, part.rows(request))
            if result is False:
                break
        return result

    def describe(self) -> dict[str, Any]:
        return {"all": [d for part in self.parts for d in _flatten_described(part, "all")]}

    def owned(self) -> Iterator[Owned]:
        for part in self.parts:
            yield from part.owned()

    def __repr__(self) -> str:
        return " & ".join(
            f"({part!r})" if isinstance(part, AnyOf) else repr(part) for part in self.parts
        )


def _flatten_described(predicate: Predicate, key: str) -> list[dict[str, Any]]:
    described = predicate.describe()
    if set(described) == {key}:
        return list(described[key])
    return [described]


# --- declarations -----------------------------------------------------------------


def _require_predicate(slot: str, value: object) -> Predicate:
    if isinstance(value, Predicate):
        return value
    if isinstance(value, type) and issubclass(value, Predicate):
        raise ImproperlyConfigured(
            f"Access({slot}={value.__name__}) needs an instance: write {value.__name__}()."
        )
    raise ImproperlyConfigured(
        f"Access({slot}=...) takes a predicate (Owned, HasRole, Authenticated, Public, "
        f"Where, combined with | and &), got {value!r}."
    )


@dataclass(frozen=True, init=False)
class Access:
    """A viewset's access declaration: ``access = Access(read=..., write=..., create=...)``.

    :param read: who sees which rows — ``list``, ``retrieve``, safe custom
        actions, and every lookup (``get_object``), relation validation and
        expansion into this model.
    :param write: who may change which (readable) rows — ``update``,
        ``partial_update``, ``destroy`` and unsafe custom actions.
    :param create: who may create; defaults to ``write``'s request gate.

    Override / escape hatch: override ``get_access()`` on the viewset to
    compute a declaration per request, or use :class:`Unscoped`.
    """

    read: Predicate
    write: Predicate
    create: Predicate

    def __init__(
        self, *, read: Predicate, write: Predicate, create: Predicate | None = None
    ) -> None:
        object.__setattr__(self, "read", _require_predicate("read", read))
        object.__setattr__(self, "write", _require_predicate("write", write))
        resolved = write if create is None else _require_predicate("create", create)
        object.__setattr__(self, "create", resolved)

    def slot(self, name: str) -> Predicate:
        """The predicate in slot ``"read"``, ``"write"`` or ``"create"``."""
        predicate: Predicate = getattr(self, name)
        return predicate

    def owned(self) -> Iterator[Owned]:
        """Every :class:`Owned` in the declaration."""
        for predicate in (self.read, self.write, self.create):
            yield from predicate.owned()


@dataclass(frozen=True, kw_only=True)
class Unscoped:
    """``access = Unscoped(reason="...")``: turn Karni's access layer off for one viewset.

    No compiled gate and no row policy: the request is gated by plain DRF —
    the viewset's ``permission_classes``, else
    ``REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"]`` — and rows are limited
    only by the model's own scopes and ``filter_queryset_for_user``. The
    reason is mandatory, greppable and published as
    ``x-karni-access: {"unscoped": reason}``.
    """

    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ImproperlyConfigured(
                'Unscoped(reason="...") needs a non-empty reason saying why this viewset '
                "opts out of access control (e.g. reason='public catalogue')."
            )


# --- compilation helpers ------------------------------------------------------------


def missing_access_message(view_class: type[Any]) -> str:
    """The deny-all message for a viewset that declares no ``access`` (names the fix)."""
    return (
        f"{view_class.__name__} declares no `access`, so every request is denied "
        "(ADR 0001 Q2.1). Declare one on the viewset, e.g. "
        "`access = Access(read=Authenticated(), write=Authenticated())`, "
        "or opt out explicitly with `access = Unscoped(reason=...)`."
    )


def action_override(view: Any) -> Predicate | None:
    """The ``@action(access=...)`` predicate of the view's current action, if any."""
    action = getattr(view, "action", None)
    if not action:
        return None
    handler = getattr(type(view), action, None)
    kwargs = getattr(handler, "kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    override = kwargs.get("access")
    if override is None:
        return None
    if not isinstance(override, Predicate):
        raise ImproperlyConfigured(
            f"{type(view).__name__}.{action}: @action(access=...) takes a predicate such as "
            f"HasRole('admin'), got {override!r}."
        )
    return override


def action_slot(action: str | None, method: str | None) -> str:
    """The ``Access`` slot governing ``action`` reached with HTTP ``method``."""
    slot = ACTION_SLOTS.get(action or "")
    if slot is not None:
        return slot
    verb = (method or "GET").upper()
    if verb in SAFE_METHODS:
        return "read"
    if verb == "POST" and action in (None, "", "metadata"):
        return "create"
    return "write"


def action_predicate(view: Any, access: Access, method: str | None = None) -> Predicate:
    """The predicate governing the view's current action under ``access``."""
    override = action_override(view)
    if override is not None:
        return override
    if method is None:
        method = getattr(getattr(view, "request", None), "method", None)
    return access.slot(action_slot(getattr(view, "action", None), method))


def describe_access(declaration: Access | Unscoped | None, predicate: Predicate | None) -> Any:
    """The ``x-karni-access`` value for one operation."""
    if declaration is None:
        return {"deny": "no access declared"}
    if isinstance(declaration, Unscoped):
        return {"unscoped": declaration.reason}
    return predicate.describe() if predicate is not None else None


def _spawns_duplicates(model: type[Model], node: Q) -> bool:
    """True when any lookup in ``node`` crosses a to-many relation."""
    for child in node.children:
        if isinstance(child, Q):
            if _spawns_duplicates(model, child):
                return True
            continue
        if not isinstance(child, tuple):
            continue  # expressions (Exists, …) add no join
        opts = model._meta
        for name in str(child[0]).split(LOOKUP_SEP):
            if name == "pk":
                name = opts.pk.name
            try:
                relation = opts.get_field(name)
            except FieldDoesNotExist:
                break  # a lookup/transform: the path ended
            path_infos = getattr(relation, "path_infos", None)
            if not path_infos:
                break
            if any(info.m2m for info in path_infos):
                return True
            opts = path_infos[-1].to_opts
    return False


def apply_rows(queryset: QuerySet[Any], rows: RowFilter) -> QuerySet[Any]:
    """Narrow ``queryset`` by a compiled row filter (``distinct()`` for to-many paths)."""
    if rows is True:
        return queryset
    if rows is False:
        return queryset.none()
    narrowed = queryset.filter(rows)
    if _spawns_duplicates(queryset.model, rows):
        narrowed = narrowed.distinct()
    return narrowed


# --- validation ------------------------------------------------------------------------


def _owned_target(model: type[Model], path: str) -> tuple[bool, str]:
    """(valid, problem) for ``Owned(path)`` declared against ``model``."""
    user_model = get_user_model()
    segments = path.split(LOOKUP_SEP)
    if len(segments) == 1 and model is user_model and path in {"pk", model._meta.pk.name}:
        return True, ""
    current: type[Model] = model
    for segment in segments:
        try:
            relation = current._meta.get_field(segment)
        except FieldDoesNotExist:
            return False, f"{current.__name__} has no field {segment!r}"
        target = getattr(relation, "related_model", None)
        if not getattr(relation, "is_relation", False) or target is None:
            return False, f"{current.__name__}.{segment} is not a relation"
        current = target
    if current is not user_model:
        return False, f"it ends at {current.__name__}, not the user model"
    return True, ""


def validate_access(view_class: type[Any], model: type[Model] | None) -> None:
    """Raise ``ImproperlyConfigured`` for an ``access`` that cannot work on ``model``.

    Checks the declaration's type and every :class:`Owned` path (the
    viewset's ``access`` and each ``@action(access=...)``).
    """
    name = view_class.__name__
    declaration = getattr(view_class, "access", None)
    if declaration is not None and not isinstance(declaration, Access | Unscoped):
        hint = (
            f"`access = Access(read={declaration!r}, write=...)`"
            if isinstance(declaration, Predicate)
            else "`access = Access(read=..., write=...)` or `Unscoped(reason=...)`"
        )
        raise ImproperlyConfigured(
            f"{name}.access must be an Access(...) or Unscoped(...) declaration, got "
            f"{declaration!r}; write {hint}."
        )
    owned: list[Owned] = list(declaration.owned()) if isinstance(declaration, Access) else []
    for extra in getattr(view_class, "get_extra_actions", lambda: [])():
        override = getattr(extra, "kwargs", {}).get("access")
        if override is None:
            continue
        if not isinstance(override, Predicate):
            raise ImproperlyConfigured(
                f"{name}.{extra.__name__}: @action(access=...) takes a predicate such as "
                f"HasRole('admin'), got {override!r}."
            )
        owned.extend(override.owned())
    if model is None:
        return
    for predicate in owned:
        valid, problem = _owned_target(model, predicate.path)
        if not valid:
            raise ImproperlyConfigured(
                f"{name}: Owned({predicate.path!r}) does not lead from {model.__name__} to "
                f"the user model ({problem}). Name a relation path ending at the user, "
                'e.g. Owned("organizer") or Owned("event__organizer").'
            )


def owner_fields(declaration: Access | Unscoped | None, model: type[Model]) -> tuple[str, ...]:
    """Direct FKs to the user model named by ``Owned`` in ``write``/``create``.

    These are stamped from ``request.user`` on create and read-only in the
    generated serializer. Traversals and to-many paths are never stamped.
    """
    if not isinstance(declaration, Access):
        return ()
    user_model = get_user_model()
    names: list[str] = []
    for predicate in (*declaration.write.owned(), *declaration.create.owned()):
        if LOOKUP_SEP in predicate.path or predicate.path in names:
            continue
        try:
            relation = model._meta.get_field(predicate.path)
        except FieldDoesNotExist:
            continue
        concrete = getattr(relation, "concrete", False)
        if (
            concrete
            and (relation.many_to_one or relation.one_to_one)
            and relation.related_model is user_model
        ):
            names.append(predicate.path)
    return tuple(names)


# --- the request gate -------------------------------------------------------------------


class AccessPermission(BasePermission):
    """DRF permission compiled from the view's ``access`` declaration.

    ``has_permission`` is the request gate of the current action's
    predicate; ``has_object_permission`` checks a looked-up row against that
    predicate's row filter (the row was found through ``read``, so a write
    refusal is a 403, never a 404). A view without a declaration is denied
    with a message that names the fix.
    """

    message = "You do not have permission to perform this action."

    def has_permission(self, request: Request, view: Any) -> bool:
        declaration = view.get_access()
        if declaration is None:
            _log_missing(type(view))
            raise PermissionDenied(detail=missing_access_message(type(view)), code="access_missing")
        if isinstance(declaration, Unscoped):
            return True
        predicate = action_predicate(view, declaration)
        if predicate.allows(request):
            return True
        self.message = f"Access denied: this action requires {predicate!r}."
        return False

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        declaration = view.get_access()
        if not isinstance(declaration, Access):
            return declaration is not None
        predicate = action_predicate(view, declaration)
        if predicate == declaration.read:
            return True  # the row was already found through the read scope
        rows = predicate.rows(request)
        if rows is True:
            return True
        if rows is not False:
            model = type(obj)
            if apply_rows(model._default_manager.filter(pk=obj.pk), rows).exists():
                return True
        self.message = f"Access denied: this row is readable but the action requires {predicate!r}."
        return False


_LOGGED_MISSING: set[type[Any]] = set()


def _log_missing(view_class: type[Any]) -> None:
    if view_class not in _LOGGED_MISSING:
        _LOGGED_MISSING.add(view_class)
        logger.error(missing_access_message(view_class))


# --- relation targets (ADR 0001 Q2.5) ---------------------------------------------------


def _target_view(model: type[Model], request: Any) -> Any | None:
    """A request-bound instance of the viewset routed for ``model`` (cached per request)."""
    from karni.api.routers import viewset_for_model
    from karni.api.viewsets import BaseViewSet

    cache: dict[type[Model], Any] = request.__dict__.setdefault(_VIEW_CACHE, {})
    if model in cache:
        return cache[model]
    viewset_class = viewset_for_model(model)
    view = None
    if viewset_class is not None and issubclass(viewset_class, BaseViewSet):
        view = viewset_class()
        view.request = request
        view.args = ()
        view.kwargs = {}
        view.format_kwarg = None
        view.action = "list"
    cache[model] = view
    return view


def target_read_scope(queryset: QuerySet[Any], request: Any | None) -> tuple[QuerySet[Any], bool]:
    """Narrow ``queryset`` to what ``request`` may read through its model's routed viewset.

    Returns ``(queryset, filtered)``; ``filtered`` is ``False`` when no row
    policy applied (every row stays). The target viewset is found with
    :func:`karni.api.routers.viewset_for_model` (the ``KARNI_API_ROUTER``
    registry — the same map ``x-karni-relation`` uses). Its ``read``
    predicate and ``filter_queryset_for_user`` hook apply; its own
    ``get_queryset`` does not.

    A model with no routed ``BaseViewSet`` is not an API resource and has no
    row policy: the queryset comes back unchanged (model-level scopes such as
    soft delete still hold, because callers start from the default manager).
    Without a request (server-side code) nothing is narrowed either.
    """
    if request is None:
        return queryset, False
    view = _target_view(queryset.model, request)
    if view is None:
        return queryset, False
    scoped, filtered = view.read_scope(queryset)
    return scoped, filtered


def readable(queryset: QuerySet[Any], request: Any | None) -> QuerySet[Any]:
    """:func:`target_read_scope` without the ``filtered`` flag."""
    return target_read_scope(queryset, request)[0]
