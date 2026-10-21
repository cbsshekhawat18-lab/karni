"""The test people forget, in one line: a role cannot reach another owner's (or scope's) rows.

::

    assert_isolated(EventViewSet, "organizer")          # pytest style
    self.assert_isolated(EventViewSet, "organizer")     # in a karni APITestCase

For every **isolation dimension** that applies to the resource, two users
with the role are created — *mine* and *theirs* — each with a row of their
own, and *mine* must not reach *theirs*' row through any surface:

* the list (and *mine* must see their own row: the positive control, so an
  endpoint that shows nobody anything cannot pass);
* retrieve, update (PATCH and PUT) and delete — 404 (never a 403 that
  confirms the row exists; a 403 passes only when the verb is refused for a
  row that does not exist too), and the row stays unchanged and undeleted;
* every other check of :func:`karni.testing.hidden.assert_row_hidden`
  (:data:`ISOLATION_PROBES`): detail actions, filters, ``?search=``,
  ``?ordering=``, ``?expand=`` and lists of primary keys from any resource
  relating to it (a row pointing at it is created when none does), on reads
  and in write responses, and every export format;
* the admin — the changelist, its search, the change form and a POST to it;
* a create body naming another owner — ignored, the row is stamped with the
  requester.

Dimensions (:class:`Isolation`): ``owner`` applies to every resource whose
``access`` ``read`` names an ``Owned(...)`` path (``owner="field"`` names the
path when rows are scoped by ``Where(...)`` or ``filter_queryset_for_user``
instead); ``grant`` applies when the read is ``Granted()`` (or ``Can``) and
the role's grant for the model's ``view`` permission has an ``own`` or
``related:<key>`` scope (ADR 0002, P2). A tenancy module adds ``tenant`` by
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

from django.contrib.auth import get_user_model
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from karni.exceptions import KarniAssertionError, KarniValueError
from karni.testing.api import (
    Resource,
    _ids,
    _json_value,
    _search_token,
    _unthrottled,
    build_payload,
    client_as,
    expectation,
    readable_row,
    resolve_resource,
    user_with_roles,
)
from karni.testing.hidden import HiddenRowProbe, _missing_value

__all__ = [
    "ENTRY_POINT_GROUP",
    "GrantIsolation",
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

    def persistent(self, case: IsolationCase) -> bool:
        """Whether a principal's scope survives reloading its user from the database.

        The admin logs users in by primary key, so a scope carried only on
        the user *instance* (a ``related:`` key the user model has no field
        for) cannot be exercised there; the admin probe is then skipped.
        """
        return True

    def admin_applies(self, case: IsolationCase) -> bool:
        """Whether the admin partitions rows the way this dimension does.

        The admin's rows follow the roles' grants (:mod:`karni.admin.scope`),
        so only a dimension built on grants can expect the admin to agree
        with it; an ``Owned(...)`` partition says nothing about the admin.
        """
        return False


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
            "user who passes it sees every row. Scope reads with Owned('<owner field>') or "
            "Granted() (a role whose grant is 'own' or 'related:<key>'), or pass "
            "owner='<field>' when Where(...)/filter_queryset_for_user scopes them"
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


class GrantIsolation(Isolation):
    """Rows reached through the role's grants: a ``Granted()`` / ``Can`` read with a scoped grant.

    The grant for ``<model>:view`` decides the partition: ``own`` puts each
    principal's row on the model's ``Karni.owner_field``; ``related:<key>``
    gives each principal a distinct ``user.<key>`` (a new row of the related
    model, saved on the user when the user model has that field, otherwise
    set on the instance) and puts their row on the model's scope path.
    """

    name = "grant"

    def grant(self, case: IsolationCase) -> Any | None:
        """The role's scoped grant for the model's ``view`` permission, if any."""
        from django.contrib.contenttypes.models import ContentType

        from karni.accounts.models import RolePermission
        from karni.accounts.roles import Grant
        from karni.api.access import Can, Granted, predicate_leaves
        from karni.meta import permission_key

        if not case.role:
            return None
        declaration = getattr(case.resource.viewset, "access", None)
        read = getattr(declaration, "read", None)
        if read is None:
            return None
        model = case.resource.model
        key = permission_key(model, "view")
        leaves = predicate_leaves(read)
        if not any(
            isinstance(leaf, Granted) or (isinstance(leaf, Can) and key in leaf.keys)
            for leaf in leaves
        ):
            return None
        row = (
            RolePermission.objects.filter(
                role__slug=case.role,
                permission__content_type=ContentType.objects.get_for_model(model),
                permission__action="view",
            )
            .order_by("pk")
            .first()
        )
        if row is None or row.scope not in {"own", "related"}:
            return None
        return Grant(key, row.scope, row.scope_path)

    def applies(self, case: IsolationCase) -> bool:
        return self.grant(case) is not None

    def reason(self, case: IsolationCase) -> str:
        who = f"role {case.role!r}" if case.role else "a user without a role"
        return (
            f"{case.resource.name}: {who} holds no 'own' or 'related:<key>' grant for "
            f"{case.resource.model._meta.label_lower}:view, so grants do not partition its "
            "rows (an 'all' grant sees everything; grant 'own' or 'related:<key>' in "
            "KARNI_ROLES and run karni sync-roles)"
        )

    def _user_field(self, key: str) -> Any | None:
        try:
            return get_user_model()._meta.get_field(key)
        except FieldDoesNotExist:
            return None

    def _related_model(self, case: IsolationCase, key: str) -> type[models.Model] | None:
        from karni.meta import scope_paths

        user_field = self._user_field(key)
        if user_field is not None and getattr(user_field, "related_model", None) is not None:
            return user_field.related_model
        path = scope_paths(case.resource.model).get(key)
        if not path:
            return None
        current: Any = case.resource.model
        for segment in path.split("__"):
            try:
                relation = current._meta.get_field(segment)
            except FieldDoesNotExist:
                return None
            current = getattr(relation, "related_model", None)
            if current is None:
                return None
        return current

    def principals(self, case: IsolationCase) -> tuple[Principal, Principal]:
        from karni.testing.factories import create

        mine, theirs = super().principals(case)
        grant = self.grant(case)
        if grant is not None and grant.scope == "related":
            related = self._related_model(case, grant.scope_path)
            if related is None:
                raise KarniAssertionError(
                    f"{case.resource.name}: grant 'related:{grant.scope_path}' needs "
                    f"{case.resource.model.__name__}.Karni.scope_paths[{grant.scope_path!r}] "
                    "to end at a model.",
                    code="E605",
                )
            persistent = self._user_field(grant.scope_path) is not None
            for principal in (mine, theirs):
                setattr(principal.user, grant.scope_path, create(related))
                if persistent:
                    principal.user.save(update_fields=[grant.scope_path])
        return mine, theirs

    def persistent(self, case: IsolationCase) -> bool:
        grant = self.grant(case)
        if grant is None or grant.scope != "related":
            return True
        return self._user_field(grant.scope_path) is not None

    def admin_applies(self, case: IsolationCase) -> bool:
        return True

    def row(self, case: IsolationCase, principal: Principal) -> Any:
        from karni.meta import owner_field, scope_paths
        from karni.testing.factories import create

        model = case.resource.model
        grant = self.grant(case)
        scoped: dict[str, Any] = {}
        if grant is not None and grant.scope == "own":
            owner = owner_field(model)
            if owner:
                scoped[owner] = principal.user
        elif grant is not None:
            path = scope_paths(model)[grant.scope_path]
            scoped[path] = getattr(principal.user, grant.scope_path)
        return create(model, **{**case.values, **scoped})

    def owner_fields(self, case: IsolationCase) -> tuple[str, ...]:
        from karni.meta import owner_field

        grant = self.grant(case)
        if grant is None or grant.scope != "own":
            return ()
        owner = owner_field(case.resource.model)
        return (owner,) if owner and "__" not in owner else ()


_REGISTERED: dict[str, Isolation] = {"owner": OwnerIsolation(), "grant": GrantIsolation()}
_LOADED = False


def register_isolation(dimension: Isolation) -> None:
    """Add (or replace) a dimension; ``assert_isolated`` tests it wherever it applies."""
    if not dimension.name:
        raise KarniValueError("an Isolation needs a name", code="E605")
    _REGISTERED[dimension.name] = dimension


def isolation_dimensions() -> dict[str, Isolation]:
    """Every dimension: ``owner``, ``grant`` and the ``karni.isolation`` entry points."""
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
    #: Probes that could not run for this resource (no admin, no export, …).
    notes: list[str] = field(default_factory=list)


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

    def note(message: str) -> None:
        report.notes.append(f"{tag} {message}")

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
        missing_url = resource.detail_url(_missing_value(model, model._meta.pk.name))
        before = model._default_manager.filter(pk=their_row.pk).values().first()
        for method in ("GET", "PATCH", "PUT", "DELETE"):
            call = getattr(me, method.lower())
            status = call(url, {}, format="json").status_code
            allowed = {404}
            if method != "GET" and call(missing_url, {}, format="json").status_code == 403:
                allowed.add(403)  # the gate refuses the verb for every row, a missing one too
            if status not in allowed:
                fail(
                    f"{method} {url} (another {dimension.name}'s row) as {mine.label} "
                    f"answered {status}, expected 404"
                    + (" (a 403 confirms the row exists)" if status == 403 else "")
                )
        after = model._default_manager.filter(pk=their_row.pk).values().first()
        if after is None:
            fail(f"another {dimension.name}'s row was deleted by {mine.label}")
        elif after != before:
            fail(f"another {dimension.name}'s row was changed by {mine.label}")
        probe = _IsolationProbe(me, resource.viewset, their_row, visible=my_row, owner=mine)
        found = probe.run(ISOLATION_PROBES)
        for problem in (*found.failures, *found.unproven):
            fail(problem)
        for found_note in found.notes:
            note(found_note)
        _check_create(dimension, case, mine, theirs, fail)
    _check_admin(dimension, case, mine, my_row, their_row, fail, note)


ISOLATION_PROBES: Final = ("actions", "filters", "search", "ordering", "expand", "export")
"""The :mod:`karni.testing.hidden` checks ``assert_isolated`` runs on the other principal's row.

The list, the detail verbs and the admin are probed by ``assert_isolated``
itself (it knows both principals); everything else is the hidden-row probe.
"""


class _IsolationProbe(HiddenRowProbe):
    """The hidden-row probe, creating a row that points at the hidden one when none does."""

    def __init__(self, client: Any, resource: Any, row: Any, *, visible: Any, owner: Any) -> None:
        super().__init__(client, resource, row, visible=visible)
        self.owner = owner

    def pointing_rows(self, resource: Resource, relation: Any) -> list[models.Model]:
        found = super().pointing_rows(resource, relation)
        if found or not getattr(relation, "concrete", False):
            return found
        value = [self.row] if getattr(relation, "many_to_many", False) else self.row
        try:
            return [readable_row(resource.model, self.owner.user, **{relation.name: value})]
        except Exception:  # noqa: BLE001 - the source cannot be built for this user
            return []


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


def _check_admin(
    dimension: Isolation,
    case: IsolationCase,
    mine: Principal,
    my_row: Any,
    their_row: Any,
    fail: Callable[[str], None],
    note: Callable[[str], None],
) -> None:
    """The admin — changelist, search, change form, POST — shows the same rows as the API."""
    from django.contrib.auth.models import Permission
    from django.test import Client
    from django.urls import NoReverseMatch, reverse

    from karni.scoping import admin_site

    model = case.resource.model
    if not dimension.admin_applies(case):
        note(
            "admin: rows in the admin follow the roles' grants, not this dimension; "
            "the grant dimension (a Granted() read with an own/related grant) tests them"
        )
        return
    site = admin_site()
    if model not in site._registry:
        note("admin: the model is not registered in the admin")
        return
    if not dimension.persistent(case):
        note("admin: the scope lives on the user instance only (no user field); skipped")
        return
    opts = model._meta
    user = mine.user
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label=opts.app_label,
            codename__in=[f"{action}_{opts.model_name}" for action in ("view", "change", "delete")],
        )
    )
    client = Client()
    client.force_login(user)
    try:
        changelist = reverse(f"{site.name}:{opts.app_label}_{opts.model_name}_changelist")
        change = reverse(
            f"{site.name}:{opts.app_label}_{opts.model_name}_change", args=[their_row.pk]
        )
    except NoReverseMatch:
        note("admin: the admin site is not mounted in ROOT_URLCONF")
        return
    with mine.bind():
        response = client.get(changelist)
        if response.status_code != 200:
            fail(f"admin: GET {changelist} as {mine.label} answered {response.status_code}")
            return
        changelist_view = response.context_data.get("cl") if response.context_data else None
        if changelist_view is None:
            note("admin: the changelist rendered without a ChangeList context")
            return
        shown = {str(pk) for pk in changelist_view.queryset.values_list("pk", flat=True)}
        if str(my_row.pk) not in shown:
            fail(f"admin positive control: {mine.label} cannot see their own row in {changelist}")
        if str(their_row.pk) in shown:
            fail(f"admin: {changelist} lists another {dimension.name}'s row")
        search_fields = tuple(site._registry[model].get_search_fields(response.wsgi_request))
        if search_fields:
            token = _search_token(their_row, search_fields[0])
            if token:
                searched = client.get(changelist, {"q": token})
                found = searched.context_data.get("cl") if searched.context_data else None
                if found is not None and str(their_row.pk) in {
                    str(pk) for pk in found.queryset.values_list("pk", flat=True)
                }:
                    fail(f"admin: {changelist}?q={token} finds another {dimension.name}'s row")
        before = model._default_manager.filter(pk=their_row.pk).values().first()
        opened = client.get(change)
        if opened.status_code == 200:
            fail(f"admin: GET {change} (another {dimension.name}'s row) rendered the change form")
        posted = client.post(change, {"_save": "1"})
        if posted.status_code == 200:
            fail(f"admin: POST {change} (another {dimension.name}'s row) was accepted")
        after = model._default_manager.filter(pk=their_row.pk).values().first()
        if after != before:
            fail(f"admin: another {dimension.name}'s row was changed through {change}")


def assert_isolated(
    resource: Any,
    role: str | None = None,
    *,
    by: str | tuple[str, ...] | None = None,
    owner: str | None = None,
    values: Mapping[str, Any] | None = None,
) -> IsolationReport:
    """Assert ``role`` cannot reach another owner's (or scope's) rows of ``resource``.

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
