"""The test people forget, in one line: a role cannot reach another owner's (or tenant's) rows.

::

    assert_isolated(EventViewSet, "organizer")          # pytest style
    self.assert_isolated(EventViewSet, "organizer")     # in a karni APITestCase

For every **isolation dimension** that applies to the resource, two users
with the role are created — *mine* and *theirs* — each with a row of their
own, and through the resource's URLs *mine* must:

* see their own row in the list and retrieve it (the positive control: an
  endpoint that shows nobody anything would otherwise pass);
* not see *theirs*' row in the list, get 404 (or 403) retrieving, updating
  and deleting it, and leave it unchanged and undeleted;
* not be able to create a row owned by *theirs*: a body naming another
  owner is ignored and the row is stamped with the requester.

Dimensions (:class:`Isolation`): ``owner`` ships with Karni and applies to
every resource whose ``access`` ``read`` names an ``Owned(...)`` path
(``owner="field"`` names the path when rows are scoped by ``Where(...)`` or
``filter_queryset_for_user`` instead). A tenancy module adds ``tenant`` by
registering a dimension under the ``karni.isolation`` entry-point group (or
:func:`register_isolation`): ``assert_isolated(resource)`` then tests it too,
with no change to existing tests. ``by="owner"`` limits the run to one
dimension.

A resource no dimension applies to fails, naming why: ``read=Authenticated()``
lets every authenticated user see every row, which is exactly the bug this
helper exists to catch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, ClassVar, Final

from karni.exceptions import KarniAssertionError, KarniValueError
from karni.testing.api import (
    Resource,
    _ids,
    _json_value,
    _unthrottled,
    build_payload,
    client_as,
    expectation,
    resolve_resource,
    user_with_roles,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "Isolation",
    "IsolationCase",
    "OwnerIsolation",
    "Principal",
    "assert_isolated",
    "isolation_dimensions",
    "register_isolation",
]

ENTRY_POINT_GROUP: Final = "karni.isolation"
"""Entry points naming :class:`Isolation` classes (e.g. a tenancy module's ``tenant``)."""


@dataclass
class Principal:
    """One side of an isolation check: a user and the context its requests run in."""

    label: str
    user: Any
    #: Binds whatever else scopes this principal (a tenant) around its requests and rows.
    bind: Callable[[], AbstractContextManager[Any]] = nullcontext


@dataclass
class IsolationCase:
    """What a dimension gets to work with."""

    resource: Resource
    role: str | None
    values: Mapping[str, Any] = field(default_factory=dict)
    owner: str | None = None


class Isolation:
    """One way rows are partitioned between principals. Subclass and register to add one.

    Implement :meth:`applies` (and say why not via :meth:`reason`),
    :meth:`principals` (two principals that must not see each other's rows)
    and :meth:`row` (a new row belonging to a principal).
    """

    name: ClassVar[str] = ""

    def applies(self, case: IsolationCase) -> bool:
        raise NotImplementedError

    def reason(self, case: IsolationCase) -> str:
        """Why the dimension does not apply (shown when nothing applies)."""
        return f"{self.name} isolation does not apply"

    def principals(self, case: IsolationCase) -> tuple[Principal, Principal]:
        """``(mine, theirs)`` — by default two new users holding the case's role."""
        roles = [case.role] if case.role else []
        mine = Principal("mine", user_with_roles(*roles))
        return mine, Principal("theirs", user_with_roles(*roles))

    def row(self, case: IsolationCase, principal: Principal) -> Any:
        raise NotImplementedError

    def owner_fields(self, case: IsolationCase) -> tuple[str, ...]:
        """Direct FK fields a request body might use to claim a row for someone else."""
        return ()


class OwnerIsolation(Isolation):
    """Rows owned through the ``read`` predicate's ``Owned(...)`` paths (or ``owner=``)."""

    name = "owner"

    def paths(self, case: IsolationCase) -> list[str]:
        if case.owner:
            return [case.owner]
        declaration = getattr(case.resource.viewset, "access", None)
        read = getattr(declaration, "read", None)
        return [owned.path for owned in read.owned()] if read is not None else []

    def applies(self, case: IsolationCase) -> bool:
        return bool(self.paths(case))

    def reason(self, case: IsolationCase) -> str:
        declaration = getattr(case.resource.viewset, "access", None)
        read = getattr(declaration, "read", declaration)
        return (
            f"{case.resource.name}.access read={read!r} names no Owned(...) path, so every "
            "user who passes it sees every row. Scope reads with Owned('<owner field>'), or "
            "pass owner='<field>' when Where(...)/filter_queryset_for_user scopes them"
        )

    def row(self, case: IsolationCase, principal: Principal) -> Any:
        from karni.testing.factories import create

        model = case.resource.model
        owned: dict[str, Any] = {}
        for path in self.paths(case):
            head = path.split("__", 1)[0]
            relation = model._meta.get_field(head)
            many = getattr(relation, "many_to_many", False) and "__" not in path
            owned[path] = [principal.user] if many else principal.user
        return create(model, **{**case.values, **owned})

    def owner_fields(self, case: IsolationCase) -> tuple[str, ...]:
        return tuple(path for path in self.paths(case) if "__" not in path)


_REGISTERED: dict[str, Isolation] = {"owner": OwnerIsolation()}
_LOADED = False


def register_isolation(dimension: Isolation) -> None:
    """Add (or replace) a dimension; ``assert_isolated`` tests it wherever it applies."""
    if not dimension.name:
        raise KarniValueError("an Isolation needs a name", code="E605")
    _REGISTERED[dimension.name] = dimension


def isolation_dimensions() -> dict[str, Isolation]:
    """Every dimension: the built-in ``owner`` plus the ``karni.isolation`` entry points."""
    global _LOADED
    if not _LOADED:
        _LOADED = True
        for point in entry_points(group=ENTRY_POINT_GROUP):
            loaded = point.load()
            register_isolation(loaded() if isinstance(loaded, type) else loaded)
    return dict(_REGISTERED)


@dataclass
class IsolationReport:
    resource: str
    dimensions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def _check(dimension: Isolation, case: IsolationCase, report: IsolationReport) -> None:
    resource = case.resource
    model = resource.model
    mine, theirs = dimension.principals(case)
    with theirs.bind():
        their_row = dimension.row(case, theirs)
    with mine.bind():
        my_row = dimension.row(case, mine)
    me = client_as(user=mine.user)
    tag = f"{dimension.name}:"

    def fail(message: str) -> None:
        report.failures.append(f"{tag} {message}")

    with mine.bind():
        listed = me.get(resource.list_url())
        if listed.status_code != 200:
            fail(f"GET {resource.list_url()} as {mine.label} answered {listed.status_code}")
            return
        ids = _ids(listed.json())
        if str(my_row.pk) not in ids:
            fail(
                f"positive control: {mine.label} cannot see their own row {my_row.pk} in the "
                "list — isolation would pass vacuously"
            )
        if str(their_row.pk) in ids:
            fail(f"GET {resource.list_url()} as {mine.label} lists another {dimension.name}'s row")
        own = me.get(resource.detail_url(my_row.pk))
        if own.status_code != 200:
            fail(f"positive control: GET own row answered {own.status_code}")
        url = resource.detail_url(their_row.pk)
        before = model._default_manager.filter(pk=their_row.pk).values().first()
        for method, response in (
            ("GET", me.get(url)),
            ("PATCH", me.patch(url, {}, format="json")),
            ("DELETE", me.delete(url)),
        ):
            if response.status_code not in {403, 404}:
                fail(
                    f"{method} {url} (another {dimension.name}'s row) as {mine.label} "
                    f"answered {response.status_code}, expected 404"
                )
        after = model._default_manager.filter(pk=their_row.pk).values().first()
        if after is None:
            fail(f"another {dimension.name}'s row was deleted by {mine.label}")
        elif after != before:
            fail(f"another {dimension.name}'s row was changed by {mine.label}")
        _check_create(dimension, case, mine, theirs, fail)


def _check_create(
    dimension: Isolation,
    case: IsolationCase,
    mine: Principal,
    theirs: Principal,
    fail: Callable[[str], None],
) -> None:
    resource = case.resource
    owners = dimension.owner_fields(case)
    if not owners or not expectation(resource, "create", mine.user).allowed:
        return
    body = build_payload(resource, mine.user, values=case.values)
    body.data.update({name: _json_value(theirs.user.pk) for name in owners})
    response = client_as(user=mine.user).post(resource.list_url(), body.data, format="json")
    if response.status_code != 201:
        return  # refusing the body is fine too
    created = resource.model._default_manager.filter(pk=response.json().get("id")).first()
    for name in owners:
        if created is not None and getattr(created, f"{name}_id", None) == theirs.user.pk:
            fail(
                f"POST {resource.list_url()} with {name}={theirs.user.pk} created a row owned "
                f"by {theirs.label} — the body chose the owner"
            )


def assert_isolated(
    resource: Any,
    role: str | None = None,
    *,
    by: str | tuple[str, ...] | None = None,
    owner: str | None = None,
    values: Mapping[str, Any] | None = None,
) -> IsolationReport:
    """Assert ``role`` cannot reach another owner's (or tenant's) rows of ``resource``.

    :param resource: a viewset class, a model class, a route prefix or ``"app.Model"``.
    :param role: the role both principals hold; ``None`` = plain authenticated users.
    :param by: dimension name(s) to test (default: every one that applies).
    :param owner: the owner path when ``access`` does not name one (``Where``-scoped reads).
    :param values: factory overrides for the rows created.
    :raises AssertionError: listing every leak found.
    """
    case = IsolationCase(resolve_resource(resource), role, dict(values or {}), owner)
    dimensions = isolation_dimensions()
    names = (by,) if isinstance(by, str) else tuple(by or dimensions)
    unknown = [name for name in names if name not in dimensions]
    if unknown:
        raise KarniAssertionError(
            f"Unknown isolation dimension(s) {unknown} (registered: {', '.join(dimensions)}).",
            code="E605",
        )
    report = IsolationReport(case.resource.name)
    applicable = [dimensions[name] for name in names if dimensions[name].applies(case)]
    if not applicable:
        reasons = "; ".join(dimensions[name].reason(case) for name in names)
        raise KarniAssertionError(
            f"assert_isolated({case.resource.name}): nothing isolates rows — {reasons}.",
            code="E605",
        )
    with _unthrottled(case.resource.viewset):
        for dimension in applicable:
            report.dimensions.append(dimension.name)
            _check(dimension, case, report)
    if report.failures:
        who = f"role {role!r}" if role else "authenticated users"
        lines = "\n".join(f"  - {failure}" for failure in report.failures)
        raise KarniAssertionError(
            f"assert_isolated({case.resource.name}) for {who}: rows leak\n{lines}", code="E606"
        )
    return report
