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

The vocabulary is closed (ADR 0001 Q2.8): :class:`Granted` (the default:
the roles' grants for the viewset's model and the current action, ADR 0002),
:class:`Owned`, :class:`HasRole`, :class:`Can`, :class:`Authenticated`,
:class:`Public`, :class:`Where`, :class:`Unscoped`, ``|`` and ``&``. Every
predicate has a request-level answer (:meth:`Predicate.allows`) and a
row-level answer (:meth:`Predicate.rows`: ``True`` = every row, ``False`` =
no row, or a ``Q``). No predicate can lift a model-level scope: the row ``Q``
is only ever ``filter()``-ed onto the model's default manager.

Escape hatches, least to most drastic: change the declaration; ``Where(...)``
for arbitrary row logic; ``scope_exempt = True`` with a
``scope_exempt_reason`` (the gate stays, the row filter goes; ``karni check``
lists every exemption); override ``filter_queryset_for_user`` (needs
``# karni: allow(access-override): <reason>``); ``access =
Unscoped(reason="...")`` (plain DRF ``permission_classes``, no row policy);
``auto_register = False`` plus your own view. ``get_access()`` on the viewset
may return a declaration computed at request time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, Q, QuerySet
from django.db.models.constants import LOOKUP_SEP
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from karni.exceptions import KarniImproperlyConfigured, KarniTypeError, docs_url
from karni.meta import model_actions, owner_field, permission_key, scope_paths
from karni.rows import RowFilter, apply_rows, combine_and, combine_or

if TYPE_CHECKING:
    from rest_framework.request import Request

__all__ = [
    "TRACE_ATTR",
    "Access",
    "AccessEvent",
    "AccessPermission",
    "AllOf",
    "AnyOf",
    "Authenticated",
    "Can",
    "Explained",
    "Granted",
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
    "granted_action",
    "missing_access_message",
    "missing_access_text",
    "owner_paths_models",
    "predicate_leaves",
    "readable",
    "routed_view",
    "rows_or_exempt",
    "target_read_scope",
    "trace",
]

logger = logging.getLogger(__name__)

_or = combine_or
_and = combine_and

#: Standard ``ModelViewSet`` actions → the ``Access`` slot that governs them.
ACTION_SLOTS: Final[dict[str, str]] = {
    "list": "read",
    "retrieve": "read",
    "create": "create",
    "update": "write",
    "partial_update": "write",
    "destroy": "write",
}

#: Standard actions → the permission action a ``Granted()`` grant names.
GRANTED_ACTIONS: Final[dict[str, str]] = {
    "list": "view",
    "retrieve": "view",
    "metadata": "view",
    "create": "add",
    "update": "change",
    "partial_update": "change",
    "destroy": "delete",
}
_METHOD_ACTIONS: Final[dict[str, str]] = {
    "POST": "add",
    "PUT": "change",
    "PATCH": "change",
    "DELETE": "delete",
}

_ROLE_CACHE: Final = "_karni_access_roles"
_VIEW_CACHE: Final = "_karni_access_target_views"

OWNED_NEEDS_A_FIELD: Final = (
    "Owned() needs the owner field: name the relation to the user model, e.g. "
    'Owned("organizer") or Owned("event__organizer"). Use Owned("created_by") '
    "only when whoever created the row is its owner (ADR 0001 Q2.6)."
)


# decision trace (``karni why``)

#: Attribute ``karni why`` sets on a request (a list) to receive every decision
#: the access layer makes for it. Absent on real requests: :func:`trace` is a
#: dictionary lookup and nothing else.
TRACE_ATTR: Final = "_karni_access_trace"


@dataclass(frozen=True)
class AccessEvent:
    """One decision the access layer made: ``kind`` and what it decided with.

    Kinds: ``gate`` (:meth:`AccessPermission.has_permission`: ``predicate``,
    ``allowed``, ``declaration``), ``veto`` (``name``, ``reason``), ``object``
    (:meth:`AccessPermission.has_object_permission`: ``predicate``, ``rows``,
    ``allowed``) and ``read_scope`` (``BaseViewSet.read_scope``:
    ``predicate``, ``rows``, ``exempt``, ``hook``). ``view`` is the viewset
    instance the decision was made for (relation scoping reuses the request).
    """

    kind: str
    data: Mapping[str, Any]


def trace(request: Any, kind: str, **data: Any) -> None:
    """Record a decision on ``request`` when ``karni why`` listens; a no-op otherwise."""
    events = getattr(request, "__dict__", {}).get(TRACE_ATTR)
    if events is not None:
        events.append(AccessEvent(kind, data))


# request helpers


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


# the predicate vocabulary


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

    def explain(self, request: Any) -> Explained:
        """Both answers for ``request``, part by part (``karni why``).

        A leaf calls its own :meth:`allows` and :meth:`rows`; ``|``, ``&``
        and ``bypass=`` combine their parts' explanations with the folds
        their own answers use. Override :meth:`facts` to add what a leaf read.
        """
        return Explained(self, self.allows(request), self.rows(request), facts=self.facts(request))

    def facts(self, request: Any) -> dict[str, Any]:
        """What this leaf's evaluation reads for ``request`` (shown by ``karni why``)."""
        return {}

    def owned(self) -> Iterator[Owned]:
        """Every :class:`Owned` inside this predicate (validation, owner stamping)."""
        return iter(())

    def bind(self, view: Any, action: str | None = None) -> Predicate:
        """The predicate evaluated for ``view``'s model and action.

        Only :class:`Granted` depends on the view; every other predicate is
        its own binding. ``action`` overrides the view's current action
        (``"view"`` when the read scope is being compiled).
        """
        return self

    def __or__(self, other: object) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return AnyOf((*_flatten(self, AnyOf), *_flatten(other, AnyOf)))

    def __and__(self, other: object) -> Predicate:
        if not isinstance(other, Predicate):
            return NotImplemented
        return AllOf((*_flatten(self, AllOf), *_flatten(other, AllOf)))

    def __bool__(self) -> bool:
        raise KarniTypeError(
            "Access predicates combine with | and & (e.g. Owned('user') | HasRole('staff')), "
            "because `or`, `and` and `not` would silently drop one side.",
            code="E109",
        )


def _flatten(predicate: Predicate, kind: type[AnyOf] | type[AllOf]) -> tuple[Predicate, ...]:
    if isinstance(predicate, kind):
        return predicate.parts
    return (predicate,)


# The folds ``|`` and ``&`` combine their parts with. ``allows()``/``rows()``
# and ``explain()`` both go through them, so an explanation cannot disagree
# with the answer it explains. Iterables are consumed lazily: enforcement
# stops at the first decisive part, an explanation evaluates every part.


def _any_allows(answers: Iterable[bool]) -> bool:
    return any(answers)


def _all_allows(answers: Iterable[bool]) -> bool:
    return all(answers)


def _any_rows(answers: Iterable[RowFilter]) -> RowFilter:
    result: RowFilter = False
    for answer in answers:
        result = _or(result, answer)
        if result is True:
            break
    return result


def _all_rows(answers: Iterable[RowFilter]) -> RowFilter:
    result: RowFilter = True
    for answer in answers:
        result = _and(result, answer)
        if result is False:
            break
    return result


@dataclass(frozen=True)
class Explained:
    """A predicate's answer for one request, with its parts' answers (``karni why``).

    ``allows`` and ``rows`` come from the predicate's own :meth:`Predicate.allows`
    and :meth:`Predicate.rows` (a leaf) or from its parts through the same
    folds ``|`` and ``&`` use, so the explanation is the enforcement, part by
    part. ``facts`` is what the evaluation read: the roles held, the grants
    found, the owner path.
    """

    predicate: Predicate
    allows: bool
    rows: RowFilter
    parts: tuple[Explained, ...] = ()
    facts: Mapping[str, Any] = field(default_factory=dict)

    def leaves(self) -> Iterator[Explained]:
        """Every leaf explanation, left to right."""
        if not self.parts:
            yield self
            return
        for part in self.parts:
            yield from part.leaves()


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
            raise KarniImproperlyConfigured(OWNED_NEEDS_A_FIELD, code="E104")
        if not isinstance(path, str):
            raise KarniImproperlyConfigured(
                f"Owned() takes the owner field's name as a string, got {path!r}. "
                + OWNED_NEEDS_A_FIELD,
                code="E104",
            )
        if bypass is not None and not isinstance(bypass, Predicate):
            raise KarniImproperlyConfigured(
                f"Owned(bypass=...) takes a predicate such as HasRole('admin'), got {bypass!r}.",
                code="E103",
            )
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "bypass", bypass)

    def allows(self, request: Any) -> bool:
        return _any_allows(self._branch_allows(request))

    def rows(self, request: Any) -> RowFilter:
        return _any_rows(self._branch_rows(request))

    def _branch_allows(self, request: Any) -> Iterator[bool]:
        """The owner branch, then ``bypass`` (lazily: the fold stops at the first yes)."""
        yield _authenticated(request)
        if self.bypass is not None:
            yield self.bypass.allows(request)

    def _branch_rows(self, request: Any) -> Iterator[RowFilter]:
        yield self._own_rows(request)
        if self.bypass is not None:
            yield self.bypass.rows(request)

    def _own_rows(self, request: Any) -> RowFilter:
        if not _authenticated(request):
            return False
        user = _user(request)
        last = self.path.rsplit(LOOKUP_SEP, 1)[-1]
        # A relation path compares against the user; the user model's own
        # primary key ("pk"/"id") compares against its value.
        value = user.pk if last in {"pk", user._meta.pk.name} else user
        return Q(**{self.path: value})

    def explain(self, request: Any) -> Explained:
        if self.bypass is None:
            return super().explain(request)
        own = Owned(self.path).explain(request)
        bypass = self.bypass.explain(request)
        return Explained(
            self,
            _any_allows((own.allows, bypass.allows)),
            _any_rows((own.rows, bypass.rows)),
            parts=(own, bypass),
        )

    def facts(self, request: Any) -> dict[str, Any]:
        return {"path": self.path, "authenticated": _authenticated(request)}

    def describe(self) -> dict[str, Any]:
        own = {"owned": self.path}
        if self.bypass is None:
            return own
        return {"any": [own, *_flatten_described(self.bypass, "any")]}

    def owned(self) -> Iterator[Owned]:
        yield self
        if self.bypass is not None:
            yield from self.bypass.owned()

    def bind(self, view: Any, action: str | None = None) -> Predicate:
        if self.bypass is None:
            return self
        bound = self.bypass.bind(view, action)
        return self if bound is self.bypass else Owned(self.path, bypass=bound)

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
            raise KarniImproperlyConfigured(
                "HasRole() needs one or more role (group) names, e.g. HasRole('staff').",
                code="E105",
            )
        object.__setattr__(self, "names", tuple(names))

    def allows(self, request: Any) -> bool:
        return not request_roles(request).isdisjoint(self.names)

    def rows(self, request: Any) -> RowFilter:
        return self.allows(request)

    def facts(self, request: Any) -> dict[str, Any]:
        return {"required": list(self.names), "held": sorted(request_roles(request))}

    def describe(self) -> dict[str, Any]:
        return {"role": list(self.names)}

    def __repr__(self) -> str:
        return f"HasRole({', '.join(repr(name) for name in self.names)})"


@dataclass(frozen=True, init=False, repr=False)
class Can(Predicate):
    """The requesting user holds a grant for **any** of the named permissions (ADR 0002).

    A permission is ``"app_label.model:action"`` — ``view`` / ``add`` /
    ``change`` / ``delete`` or an action the model declares in ``class
    Karni: actions``. Grants come from the roles' ``RolePermission`` rows
    (``KARNI_ROLES``, reconciled by ``karni sync-roles``), resolved once per
    request. Request level: any grant. Row level: the union of the grants'
    scopes — ``all`` → every row, ``own`` → ``Karni.owner_field`` is the user,
    ``related:<key>`` → ``Karni.scope_paths[key]`` equals ``user.<key>``,
    ``custom:<name>`` → the registered callable's ``Q``.

    The row filter is built against the permission's own model, so a
    ``Can`` in a viewset's ``access`` must name that viewset's model
    (``validate_access`` enforces it); a different model's permission can
    only gate, which ``HasRole`` already does. ``Granted()`` (P2) is ``Can``
    for the viewset's model and the current action.
    """

    keys: tuple[str, ...]

    def __init__(self, *keys: str) -> None:
        if not keys or not all(isinstance(key, str) and _permission_key_ok(key) for key in keys):
            raise KarniImproperlyConfigured(
                "Can() needs one or more permissions as 'app_label.model:action', e.g. "
                "Can('events.event:approve'). Extra actions come from `class Karni: "
                "actions = [...]` on the model.",
                code="E209",
            )
        object.__setattr__(self, "keys", tuple(keys))

    def allows(self, request: Any) -> bool:
        return _any_allows(self._key_allows(request, key) for key in self.keys)

    def rows(self, request: Any) -> RowFilter:
        if not _authenticated(request):
            return False
        return _any_rows(self._key_rows(request, key) for key in self.keys)

    @staticmethod
    def _key_allows(request: Any, key: str) -> bool:
        from karni.accounts.roles import user_can

        return user_can(_user(request), key)

    def _key_rows(self, request: Any, key: str) -> RowFilter:
        from karni.accounts.roles import rows_for

        model, action = self.target(key)
        return rows_for(_user(request), model, action)

    def explain(self, request: Any) -> Explained:
        if len(self.keys) == 1:
            return super().explain(request)
        parts = tuple(Can(key).explain(request) for key in self.keys)
        return Explained(
            self,
            _any_allows(part.allows for part in parts),
            _any_rows(part.rows for part in parts),
            parts=parts,
        )

    def facts(self, request: Any) -> dict[str, Any]:
        """The grants behind each permission, and the rows each one reaches."""
        from karni.accounts.roles import grant_rows, grant_sources, grants_for

        user = _user(request)
        found: dict[str, Any] = {}
        for key in self.keys:
            model, _action = self.target(key)
            grants = grants_for(user).get(key, [])
            found[key] = {
                "grants": [(grant, grant_rows(user, model, grant)) for grant in grants],
                "sources": grant_sources(user, key),
            }
        return {"permissions": found, "authenticated": _authenticated(request)}

    def describe(self) -> dict[str, Any]:
        return {"can": list(self.keys)}

    @staticmethod
    def target(key: str) -> tuple[type[Model], str]:
        """The model and action a permission key names."""
        from django.apps import apps

        label, action = key.rsplit(":", 1)
        return apps.get_model(label), action

    def __repr__(self) -> str:
        return f"Can({', '.join(repr(key) for key in self.keys)})"


def _permission_key_ok(key: str) -> bool:
    label, sep, action = key.rpartition(":")
    return bool(sep and action and label.count(".") == 1 and all(label.split(".")))


def _view_model(view: Any) -> type[Model] | None:
    """The model a viewset (class or instance) serves, or ``None``."""
    model = getattr(view, "model", None)
    if model is None:
        model = getattr(getattr(view, "queryset", None), "model", None)
    return model


def granted_action(view: Any, action: str | None = None) -> str:
    """The permission action ``Granted()`` names for ``view``'s current action.

    ``list``/``retrieve`` → ``view``, ``create`` → ``add``,
    ``update``/``partial_update`` → ``change``, ``destroy`` → ``delete``. A
    custom ``@action`` is its own permission when the model declares it in
    ``class Karni: actions``; otherwise a safe (GET) action reads (``view``)
    and an unsafe one is an error (``E211``), because silently mapping it to
    ``change`` would grant more than the role says.
    """
    name = action if action is not None else getattr(view, "action", None)
    if name in GRANTED_ACTIONS:
        return GRANTED_ACTIONS[name]
    model = _view_model(view)
    if name and model is not None and name in model_actions(model):
        return name
    method = str(getattr(getattr(view, "request", None), "method", None) or "GET").upper()
    if not name:
        return _METHOD_ACTIONS.get(method, "view")
    if method in SAFE_METHODS:
        return "view"
    owner = type(view).__name__ if not isinstance(view, type) else view.__name__
    target = model.__name__ if model is not None else "the model"
    raise KarniImproperlyConfigured(
        f"{owner}.{name}: Granted() has no permission for this action. Add {name!r} to "
        f"`class Karni: actions = [...]` on {target} (then grant 'app.model:{name}' in "
        f"KARNI_ROLES), or give the action its own @action(access=...).",
        code="E211",
    )


@dataclass(frozen=True, repr=False)
class Granted(Predicate):
    """Whatever the roles say: :class:`Can` for the viewset's own model and current action.

    ``access = Granted()`` is the default declaration (ADR 0002, P2): the gate
    asks whether the user holds a grant for ``<model>:<action>`` and the rows
    are the union of those grants' scopes (``all``, ``own``, ``related:``,
    ``custom:``), so scoping is on without the viewset naming anything. Reads
    compile the ``view`` permission's rows; ``create`` needs ``add``; writes
    need ``change`` / ``delete`` on a row that is also readable (else 404). A
    custom action is its own permission when the model declares it in
    ``class Karni: actions`` (:func:`granted_action`).

    The predicate is evaluated through :meth:`bind`, which
    :func:`action_predicate` and the viewset's read scope call for you.
    Evaluating it unbound is an error, never a silent deny.
    """

    def bind(self, view: Any, action: str | None = None) -> Predicate:
        model = _view_model(view)
        if model is None:
            return self
        return Can(permission_key(model, granted_action(view, action)))

    def _unbound(self) -> KarniImproperlyConfigured:
        return KarniImproperlyConfigured(
            "Granted() answers only for a viewset's model and action: evaluate it through "
            "karni.api.access.action_predicate(view, access) or predicate.bind(view).",
            code="E211",
        )

    def allows(self, request: Any) -> bool:
        raise self._unbound()

    def rows(self, request: Any) -> RowFilter:
        raise self._unbound()

    def explain(self, request: Any) -> Explained:
        raise self._unbound()

    def describe(self) -> dict[str, Any]:
        return {"granted": True}

    def __repr__(self) -> str:
        return "Granted()"


@dataclass(frozen=True, repr=False)
class Authenticated(Predicate):
    """Any authenticated user, on every row."""

    def allows(self, request: Any) -> bool:
        return _authenticated(request)

    def rows(self, request: Any) -> RowFilter:
        return _authenticated(request)

    def facts(self, request: Any) -> dict[str, Any]:
        return {"authenticated": _authenticated(request)}

    def describe(self) -> dict[str, Any]:
        return {"authenticated": True}

    def __repr__(self) -> str:
        return "Authenticated()"


@dataclass(frozen=True, repr=False)
class Public(Predicate):
    """Everyone, anonymous included, on every row. The explicit public form."""

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
            raise KarniImproperlyConfigured(
                "Where() takes a function of the request, e.g. "
                f"Where(lambda request: Q(published=True)). Got {self.fn!r}.",
                code="E106",
            )

    def _evaluate(self, request: Any) -> Q | bool:
        value = self.fn(request)
        if isinstance(value, Q | bool):
            return value
        raise KarniImproperlyConfigured(
            f"{self!r} returned {value!r}, but a Where() function must return a Q or a bool.",
            code="E106",
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
        return _any_allows(part.allows(request) for part in self.parts)

    def rows(self, request: Any) -> RowFilter:
        return _any_rows(part.rows(request) for part in self.parts)

    def explain(self, request: Any) -> Explained:
        parts = tuple(part.explain(request) for part in self.parts)
        return Explained(
            self,
            _any_allows(part.allows for part in parts),
            _any_rows(part.rows for part in parts),
            parts=parts,
        )

    def describe(self) -> dict[str, Any]:
        return {"any": [d for part in self.parts for d in _flatten_described(part, "any")]}

    def owned(self) -> Iterator[Owned]:
        for part in self.parts:
            yield from part.owned()

    def bind(self, view: Any, action: str | None = None) -> Predicate:
        bound = tuple(part.bind(view, action) for part in self.parts)
        return self if all(a is b for a, b in zip(bound, self.parts, strict=True)) else AnyOf(bound)

    def __repr__(self) -> str:
        return " | ".join(repr(part) for part in self.parts)


@dataclass(frozen=True, repr=False)
class AllOf(Predicate):
    """``a & b & …`` — produced by ``&``; every part must grant."""

    parts: tuple[Predicate, ...]

    def allows(self, request: Any) -> bool:
        return _all_allows(part.allows(request) for part in self.parts)

    def rows(self, request: Any) -> RowFilter:
        return _all_rows(part.rows(request) for part in self.parts)

    def explain(self, request: Any) -> Explained:
        parts = tuple(part.explain(request) for part in self.parts)
        return Explained(
            self,
            _all_allows(part.allows for part in parts),
            _all_rows(part.rows for part in parts),
            parts=parts,
        )

    def describe(self) -> dict[str, Any]:
        return {"all": [d for part in self.parts for d in _flatten_described(part, "all")]}

    def owned(self) -> Iterator[Owned]:
        for part in self.parts:
            yield from part.owned()

    def bind(self, view: Any, action: str | None = None) -> Predicate:
        bound = tuple(part.bind(view, action) for part in self.parts)
        return self if all(a is b for a, b in zip(bound, self.parts, strict=True)) else AllOf(bound)

    def __repr__(self) -> str:
        return " & ".join(
            f"({part!r})" if isinstance(part, AnyOf) else repr(part) for part in self.parts
        )


def _flatten_described(predicate: Predicate, key: str) -> list[dict[str, Any]]:
    described = predicate.describe()
    if set(described) == {key}:
        return list(described[key])
    return [described]


# declarations


def _require_predicate(slot: str, value: object) -> Predicate:
    if isinstance(value, Predicate):
        return value
    if isinstance(value, type) and issubclass(value, Predicate):
        raise KarniImproperlyConfigured(
            f"Access({slot}={value.__name__}) needs an instance: write {value.__name__}().",
            code="E103",
        )
    raise KarniImproperlyConfigured(
        f"Access({slot}=...) takes a predicate (Owned, HasRole, Authenticated, Public, "
        f"Where, combined with | and &), got {value!r}.",
        code="E103",
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
            raise KarniImproperlyConfigured(
                'Unscoped(reason="...") needs a non-empty reason saying why this viewset '
                "opts out of access control (e.g. reason='public catalogue').",
                code="E107",
            )


# compilation helpers


def missing_access_text(view_class: type[Any]) -> str:
    """What is wrong and how to fix it, for a viewset that declares no ``access``."""
    return (
        f"{view_class.__name__} declares no `access`, so every request is denied: access "
        "is mandatory (ADR 0001 Q2.1). Declare one on the viewset: `access = Granted()` "
        "(the roles' grants for this model, row-scoped), e.g. "
        "`access = Access(read=Authenticated(), write=Owned('owner'))` for a custom rule, "
        "or opt out explicitly with `access = Unscoped(reason=...)`."
    )


def missing_access_message(view_class: type[Any]) -> str:
    """The deny-all message (code E101 and docs link) for a viewset without ``access``."""
    return f"E101: {missing_access_text(view_class)} See {docs_url('E101')}"


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
        raise KarniImproperlyConfigured(
            f"{type(view).__name__}.{action}: @action(access=...) takes a predicate such as "
            f"HasRole('admin'), got {override!r}.",
            code="E103",
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


def _write_or_create(view: Any, action: str | None) -> bool:
    """Whether ``action`` is one the view lists in ``write_or_create_actions``."""
    return bool(action) and action in (getattr(view, "write_or_create_actions", None) or ())


def action_predicate(view: Any, access: Access, method: str | None = None) -> Predicate:
    """The predicate governing the view's current action under ``access``, bound to the view.

    An action the view names in ``write_or_create_actions`` (an import: it
    creates some rows and changes others) is governed by ``create`` **or**
    ``write`` — whoever may do either may start it; which rows each may
    touch is the action's own business, per row.
    """
    override = action_override(view)
    if override is not None:
        return override.bind(view)
    action = getattr(view, "action", None)
    if _write_or_create(view, action):
        return AnyOf((access.create.bind(view, "create"), access.write.bind(view, "update")))
    if method is None:
        method = getattr(getattr(view, "request", None), "method", None)
    return access.slot(action_slot(action, method)).bind(view)


def describe_access(declaration: Access | Unscoped | None, predicate: Predicate | None) -> Any:
    """The ``x-karni-access`` value for one operation."""
    if declaration is None:
        return {"deny": "no access declared"}
    if isinstance(declaration, Unscoped):
        return {"unscoped": declaration.reason}
    return predicate.describe() if predicate is not None else None


def rows_or_exempt(view: Any, predicate: Predicate, request: Any) -> RowFilter:
    """``predicate.rows(request)``, or every row the gate admits when ``view`` is ``scope_exempt``.

    ``scope_exempt = True`` (with a ``scope_exempt_reason``) keeps the request
    gate and drops the row filter for one viewset; ``karni check`` lists every
    exemption so they stay visible.
    """
    if getattr(view, "scope_exempt", False):
        return True if predicate.allows(request) else False
    return predicate.rows(request)


# validation


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
        raise KarniImproperlyConfigured(
            f"{name}.access must be an Access(...) or Unscoped(...) declaration, got "
            f"{declaration!r}. Write {hint}.",
            code="E102",
        )
    owned: list[Owned] = list(declaration.owned()) if isinstance(declaration, Access) else []
    for extra in getattr(view_class, "get_extra_actions", lambda: [])():
        override = getattr(extra, "kwargs", {}).get("access")
        if override is None:
            continue
        if not isinstance(override, Predicate):
            raise KarniImproperlyConfigured(
                f"{name}.{extra.__name__}: @action(access=...) takes a predicate such as "
                f"HasRole('admin'), got {override!r}.",
                code="E103",
            )
        owned.extend(override.owned())
    exempt = getattr(view_class, "scope_exempt", False)
    reason = getattr(view_class, "scope_exempt_reason", "")
    if exempt and (not isinstance(reason, str) or not reason.strip()):
        raise KarniImproperlyConfigured(
            f"{name}: scope_exempt = True needs scope_exempt_reason = '...' saying why this "
            "viewset shows every row its gate admits (karni check lists every exemption).",
            code="E210",
        )
    granted = any(isinstance(p, Granted) for p in _leaves(declaration, view_class))
    if model is None:
        if granted:
            raise KarniImproperlyConfigured(
                f"{name}: Granted() needs the viewset's model (set `model = ...`) to know "
                "which permissions the roles grant.",
                code="E211",
            )
        return
    for predicate in owned:
        valid, problem = _owned_target(model, predicate.path)
        if not valid:
            raise KarniImproperlyConfigured(
                f"{name}: Owned({predicate.path!r}) does not lead from {model.__name__} to "
                f"the user model ({problem}). Name a relation path ending at the user, "
                'e.g. Owned("organizer") or Owned("event__organizer").',
                code="E104",
            )
    for can in (p for p in _leaves(declaration, view_class) if isinstance(p, Can)):
        for key in can.keys:
            label = key.rsplit(":", 1)[0]
            if label != model._meta.label_lower:
                raise KarniImproperlyConfigured(
                    f"{name}: Can({key!r}) names {label}, but the viewset's model is "
                    f"{model._meta.label_lower}, and the row filter is built against the "
                    f"permission's model. Use Can('{model._meta.label_lower}:"
                    f"{key.rsplit(':', 1)[1]}'), or HasRole(...) to gate on another model's "
                    "permission.",
                    code="E209",
                )
    if granted:
        _validate_granted_actions(view_class, declaration, model)


def _validate_granted_actions(view_class: type[Any], declaration: Any, model: type[Model]) -> None:
    """E211 for an unsafe ``@action`` that ``Granted()`` governs but the model never declared."""
    for extra in getattr(view_class, "get_extra_actions", lambda: [])():
        override = getattr(extra, "kwargs", {}).get("access")
        if _write_or_create(view_class, extra.__name__):
            continue  # governed by create | write, bound to those actions
        for method in getattr(extra, "mapping", {}):
            verb = str(method).upper()
            if verb in SAFE_METHODS:
                continue
            if override is not None:
                governing: Predicate | None = override
            elif isinstance(declaration, Access):
                governing = declaration.slot(action_slot(extra.__name__, verb))
            else:
                governing = None
            if governing is None:
                continue
            if not any(isinstance(p, Granted) for p in _flatten_leaves(governing)):
                continue
            if extra.__name__ not in model_actions(model):
                raise KarniImproperlyConfigured(
                    f"{view_class.__name__}.{extra.__name__}: Granted() has no permission for "
                    f"this action. Add {extra.__name__!r} to `class Karni: actions = [...]` on "
                    f"{model.__name__} (then grant 'app.model:{extra.__name__}' in KARNI_ROLES), "
                    "or give the action its own @action(access=...).",
                    code="E211",
                )


def predicate_leaves(predicate: Predicate) -> list[Predicate]:
    """Every leaf predicate inside ``predicate`` (through ``|``, ``&`` and ``bypass=``)."""
    return _flatten_leaves(predicate)


def _flatten_leaves(predicate: Predicate) -> list[Predicate]:
    pending: list[Predicate] = [predicate]
    found: list[Predicate] = []
    while pending:
        current = pending.pop()
        if isinstance(current, AnyOf | AllOf):
            pending.extend(current.parts)
        elif isinstance(current, Owned):
            found.append(current)
            if current.bypass is not None:
                pending.append(current.bypass)
        else:
            found.append(current)
    return found


def _leaves(declaration: Any, view_class: type[Any]) -> list[Predicate]:
    """Every leaf predicate of the viewset's ``access`` and its ``@action(access=...)``."""
    predicates: list[Predicate] = []
    if isinstance(declaration, Access):
        predicates.extend((declaration.read, declaration.write, declaration.create))
    for extra in getattr(view_class, "get_extra_actions", lambda: [])():
        override = getattr(extra, "kwargs", {}).get("access")
        if isinstance(override, Predicate):
            predicates.append(override)
    return [leaf for predicate in predicates for leaf in _flatten_leaves(predicate)]


def _direct_user_fk(model: type[Model], name: str) -> bool:
    """Whether ``model.<name>`` is a concrete FK/O2O to the user model."""
    if LOOKUP_SEP in name:
        return False
    try:
        relation = model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return bool(
        getattr(relation, "concrete", False)
        and (relation.many_to_one or relation.one_to_one)
        and relation.related_model is get_user_model()
    )


def owner_fields(declaration: Access | Unscoped | None, model: type[Model]) -> tuple[str, ...]:
    """Direct FKs to the user model that ``write``/``create`` own.

    Named by ``Owned`` there, or — under ``Granted()`` — the model's
    ``Karni.owner_field`` (the ``own`` scope). These are stamped from
    ``request.user`` on create and read-only in the generated serializer.
    Traversals and to-many paths are never stamped.
    """
    if not isinstance(declaration, Access):
        return ()
    names: list[str] = []
    for predicate in (*declaration.write.owned(), *declaration.create.owned()):
        if predicate.path not in names and _direct_user_fk(model, predicate.path):
            names.append(predicate.path)
    leaves = (*_flatten_leaves(declaration.write), *_flatten_leaves(declaration.create))
    if any(isinstance(leaf, Granted) for leaf in leaves):
        owner = owner_field(model)
        if owner and owner not in names and _direct_user_fk(model, owner):
            names.append(owner)
    return tuple(names)


def owner_paths_models(
    declaration: Access | Unscoped | None, model: type[Model]
) -> set[type[Model]]:
    """Models crossed by the ``read`` predicate's row paths (cache invalidation).

    ``Owned`` paths, plus — under ``Granted()`` — the model's owner field and
    scope paths. A write to any of them can change which rows a requester sees.
    """
    if not isinstance(declaration, Access):
        return set()
    paths = [predicate.path for predicate in declaration.read.owned()]
    if any(isinstance(leaf, Granted) for leaf in _flatten_leaves(declaration.read)):
        owner = owner_field(model)
        paths.extend([owner] if owner else [])
        paths.extend(scope_paths(model).values())
    found: set[type[Model]] = set()
    for path in paths:
        current = model
        for segment in path.split(LOOKUP_SEP):
            try:
                relation = current._meta.get_field(segment)
            except FieldDoesNotExist:
                break
            target = getattr(relation, "related_model", None)
            if target is None:
                break
            found.add(target)
            current = target
    return found


# the request gate


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
            trace(request, "gate", view=view, declaration=None, predicate=None, allowed=False)
            raise PermissionDenied(detail=missing_access_message(type(view)), code="E101")
        if isinstance(declaration, Unscoped):
            trace(request, "gate", view=view, declaration=declaration, predicate=None, allowed=True)
            return self._not_vetoed(request, view)
        predicate = action_predicate(view, declaration)
        allowed = predicate.allows(request)
        trace(
            request,
            "gate",
            view=view,
            declaration=declaration,
            predicate=predicate,
            allowed=allowed,
        )
        if allowed:
            return self._not_vetoed(request, view)
        self.message = f"Access denied: this action requires {predicate!r}."
        return False

    def _not_vetoed(self, request: Request, view: Any) -> bool:
        """Consult :mod:`karni.vetoes` for the current action (the gate's last word)."""
        from karni.vetoes import VetoContext, first_veto

        model = _view_model(view)
        action = str(getattr(view, "action", None) or request.method or "").lower()
        permission: str | None = None
        if model is not None:
            try:
                permission = permission_key(model, granted_action(view))
            except KarniImproperlyConfigured:
                permission = None
        context = VetoContext(request, "api", action, model=model, permission=permission, view=view)
        found = first_veto(context)
        if found is None:
            return True
        name, reason = found
        trace(request, "veto", view=view, name=name, reason=reason, context=context)
        self.message = reason
        return False

    def has_object_permission(self, request: Request, view: Any, obj: Any) -> bool:
        declaration = view.get_access()
        if not isinstance(declaration, Access):
            return declaration is not None
        slot = action_slot(getattr(view, "action", None), request.method)
        if slot == "read" and action_override(view) is None:
            trace(request, "object", view=view, predicate=None, rows=True, allowed=True, row=obj)
            return True  # the row was already found through the read scope
        predicate = action_predicate(view, declaration)
        rows = rows_or_exempt(view, predicate, request)
        allowed = rows is True
        if rows is not True and rows is not False:
            model = type(obj)
            allowed = apply_rows(model._default_manager.filter(pk=obj.pk), rows).exists()
        trace(
            request, "object", view=view, predicate=predicate, rows=rows, allowed=allowed, row=obj
        )
        if allowed:
            return True
        self.message = f"Access denied: this row is readable but the action requires {predicate!r}."
        return False


_LOGGED_MISSING: set[type[Any]] = set()


def _log_missing(view_class: type[Any]) -> None:
    if view_class not in _LOGGED_MISSING:
        _LOGGED_MISSING.add(view_class)
        logger.error(missing_access_message(view_class))


# relation targets (ADR 0001 Q2.5)


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


def routed_view(model: type[Model], request: Any) -> Any | None:
    """The request-bound instance of the ``BaseViewSet`` routed for ``model``, or ``None``.

    What relation scoping and the importer use to evaluate a model's own
    ``access`` declaration outside its viewset (cached per request).
    """
    return _target_view(model, request)


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
