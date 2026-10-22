"""API test helpers: a client per role, and a resource's whole CRUD surface in one call.

::

    from karni.testing import APITestCase

    class EventAPITests(APITestCase):
        def test_crud(self):
            self.assert_crud(EventViewSet, "organizer")

        def test_owners_are_isolated(self):
            self.assert_isolated(EventViewSet, "organizer")

        def test_cancel(self):
            client = self.client_as("organizer")          # a user in the "organizer" group
            response = client.post(f"/api/events/{event.pk}/cancel/")

**Roles** are Django groups (:mod:`karni.accounts.permissions`), created on
demand. ``client_as("organizer")`` returns an authenticated
:class:`KarniAPIClient` (``client.user`` is the user); the same roles give the
same user for the rest of the test. ``client_as()`` is a user without roles,
``client_as(None)`` an anonymous client, ``client_as(user=u)`` a given user.

**assert_crud(resource, role)** drives the resource through its routed URLs
as that role and checks, in one call:

* ``list`` / ``retrieve`` / ``create`` / ``update`` (PATCH and PUT) /
  ``delete`` — the status the resource's ``access`` declaration promises the
  role, and for allowed actions the effect: the created row exists with the
  sent values and its owner stamped from the requester, the update is
  stored, the deleted row is gone;
* **denials** — anonymous requests and a user without the role get 401/403
  (or 404 for rows outside their read scope) wherever the declaration denies
  them, and a denied write changes nothing;
* **pagination** — ``?page_size=`` limits the page, ``next`` reaches the
  rest, pages do not overlap;
* **filtering** — a derived filter keeps the matching row and drops the
  other (and ``?search=`` finds a row when ``search_fields`` is declared);
* **the OpenAPI contract** — every operation is in the schema, the filter
  and pagination parameters are documented, and every response body
  validates against its documented schema (no undeclared fields).

Expected statuses come from evaluating the viewset's own ``access``
declaration for each user, so a viewset that does not enforce what it
declares fails with a message naming the check, the request, the expected
and actual status and the predicate that decided it. Every failure is
reported, not only the first. Throttling is off for the resource while it
runs; query budgets stay on (the ``karni`` pytest plugin makes them raise).

Override / escape hatches: ``values={...}`` (factory overrides for every row
and the create payload), ``payload={...}`` (raw request fields),
``expect={"destroy": 403}`` (pin a status), ``skip=("filtering",)``,
``user=`` (an explicit requester). :func:`assert_crud` is a plain function
for pytest-style tests; the ``client_as`` fixture of the ``karni`` plugin
mirrors :meth:`APITestCase.client_as`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.urls import reverse
from rest_framework import serializers
from rest_framework import test as drf_test
from rest_framework.relations import ManyRelatedField, RelatedField

from karni.exceptions import KarniAssertionError, KarniValueError

__all__ = [
    "CHECKS",
    "APITestCase",
    "CrudReport",
    "KarniAPIClient",
    "Resource",
    "assert_crud",
    "client_as",
    "owner_values",
    "readable_row",
    "resolve_resource",
    "user_with_roles",
]

CHECKS: Final = (
    "list",
    "retrieve",
    "create",
    "update",
    "delete",
    "denials",
    "pagination",
    "filtering",
    "visibility",
    "schema",
)
"""Every check :func:`assert_crud` runs (names accepted by ``skip=``)."""

#: Statuses an allowed action answers with.
SUCCESS: Final = {
    "list": 200,
    "retrieve": 200,
    "create": 201,
    "update": 200,
    "partial_update": 200,
    "destroy": 204,
}
METHODS: Final = {
    "list": "GET",
    "retrieve": "GET",
    "create": "POST",
    "update": "PUT",
    "partial_update": "PATCH",
    "destroy": "DELETE",
}
ANONYMOUS_DENIAL: Final = frozenset({401, 403})


# users and clients


def user_with_roles(*roles: str, **fields: Any) -> Any:
    """A new user (generated factory, or the explicit one) holding ``roles`` (Django groups)."""
    from karni.accounts.permissions import assign_role
    from karni.testing.factories import create

    user = create(get_user_model(), **fields)
    for role in roles:
        assign_role(user, role)
    return user


class KarniAPIClient(drf_test.APIClient):
    """DRF's ``APIClient`` that remembers whom it is authenticated as (``client.user``)."""

    user: Any = None

    def force_authenticate(self, user: Any = None, token: Any = None) -> None:
        super().force_authenticate(user=user, token=token)
        self.user = user


def client_as(*roles: str | None, user: Any = None) -> KarniAPIClient:
    """A client authenticated as a new user holding ``roles`` (``None`` alone: anonymous)."""
    client = KarniAPIClient()
    if user is None and roles == (None,):
        return client
    if user is None:
        user = user_with_roles(*(role for role in roles if role))
    client.force_authenticate(user)
    return client


# resources


@dataclass(frozen=True)
class Resource:
    """A routed viewset: where it lives and what it serves."""

    viewset: type[Any]
    model: type[models.Model]
    prefix: str
    basename: str

    @property
    def name(self) -> str:
        return self.viewset.__name__

    @property
    def lookup(self) -> str:
        return str(self.viewset.lookup_url_kwarg or self.viewset.lookup_field)

    def list_url(self) -> str:
        return reverse(f"{self.basename}-list")

    def detail_url(self, pk: Any) -> str:
        return reverse(f"{self.basename}-detail", kwargs={self.lookup: str(pk)})


def resolve_resource(resource: Any) -> Resource:
    """A viewset class, a model class, a route prefix (``"events"``) or ``"app.Model"``."""
    from django.apps import apps

    from karni.api.routers import resolve_router, viewset_for_model

    router = resolve_router()
    registry = list(getattr(router, "registry", ()))
    viewset: Any = None
    if isinstance(resource, str) and "." in resource and "/" not in resource:
        resource = apps.get_model(resource)
    if isinstance(resource, type) and issubclass(resource, models.Model):
        viewset = viewset_for_model(resource, router)
        if viewset is None:
            raise KarniAssertionError(
                f"No routed viewset serves {resource.__name__}. Route one "
                f"(karni make viewset {resource.__name__}) or pass the viewset class.",
                code="E601",
            )
    elif isinstance(resource, str):
        prefix = resource.strip("/").removeprefix("api/")
        viewset = next((vs for p, vs, _b in registry if p == prefix), None)
        if viewset is None:
            known = ", ".join(sorted(p for p, _vs, _b in registry)) or "none"
            raise KarniAssertionError(
                f"No route {resource!r} on the API router (routes: {known}).", code="E601"
            )
    else:
        viewset = resource
    for prefix, registered, basename in registry:
        if registered is viewset:
            model = viewset.model if viewset.model is not None else viewset.queryset.model
            return Resource(viewset, model, prefix, basename)
    raise KarniAssertionError(
        f"{getattr(viewset, '__name__', viewset)!r} is not routed on the API router "
        "(KARNI_API_ROUTER), but assert_crud tests a resource through its URLs. Check "
        "auto_register, or register it on the router your factory builds.",
        code="E601",
    )


# rows a user can read


def owner_values(declaration: Any, model: type[models.Model], user: Any) -> dict[str, Any]:
    """Factory overrides that make a new ``model`` row belong to ``user``.

    One entry per ``Owned`` path of the ``read`` predicate: a direct FK or a
    traversal (``event__organizer`` — factory-boy passes it down the
    related factories) gets the user, a to-many path ``[user]``.
    """
    from karni.api.access import Access, Can, Granted, predicate_leaves

    if not isinstance(declaration, Access):
        return {}
    found: dict[str, Any] = {}
    for owned in declaration.read.owned():
        if model is get_user_model() and owned.path in {"pk", model._meta.pk.name}:
            continue
        head = owned.path.split("__", 1)[0]
        try:
            relation = model._meta.get_field(head)
        except FieldDoesNotExist:
            continue
        if getattr(relation, "many_to_many", False) and "__" not in owned.path:
            found[owned.path] = [user]
        elif getattr(relation, "concrete", False):
            found[owned.path] = user
    leaves = predicate_leaves(declaration.read)
    if user is not None and any(isinstance(leaf, Granted | Can) for leaf in leaves):
        found.update(granted_values(model, user))
    return found


def granted_values(model: type[models.Model], user: Any) -> dict[str, Any]:
    """Factory overrides putting a new ``model`` row inside ``user``'s ``view`` grants.

    An ``own`` grant sets the model's owner field to the user; a ``related``
    grant sets the scope path to the user's side of it (``user.venue``), when
    the user has one. An ``all`` grant needs nothing.
    """
    from karni.accounts.roles import grants_for
    from karni.meta import owner_field, permission_key, scope_paths

    found: dict[str, Any] = {}
    for grant in grants_for(user).get(permission_key(model, "view"), []):
        if grant.scope == "all":
            return {}
        if grant.scope == "own":
            owner = owner_field(model)
            if owner:
                found.setdefault(owner, user)
        elif grant.scope == "related":
            path = scope_paths(model).get(grant.scope_path)
            value = getattr(user, grant.scope_path, None)
            if path and value is not None:
                found.setdefault(path, value)
    return found


def readable_row(model: type[models.Model], user: Any, **values: Any) -> Any:
    """A new ``model`` row ``user`` can read through the model's routed viewset."""
    from karni.api.routers import viewset_for_model
    from karni.testing.factories import create

    if model is get_user_model() and not values:
        return user_with_roles()
    viewset = viewset_for_model(model)
    owned = owner_values(getattr(viewset, "access", None), model, user) if viewset else {}
    return create(model, **{**owned, **values})


# what the declaration promises


@dataclass(frozen=True)
class Expectation:
    """The statuses ``access`` promises one user for one action (and why)."""

    statuses: frozenset[int]
    allowed: bool
    reason: str = ""

    def describe(self) -> str:
        shown = "/".join(str(status) for status in sorted(self.statuses))
        return f"{shown} ({self.reason})" if self.reason else shown


def _request(method: str, user: Any) -> Any:
    from rest_framework.request import Request

    request = Request(drf_test.APIRequestFactory().generic(method, "/"))
    request.user = user if user is not None else AnonymousUser()
    return request


def _view(resource: Resource, action: str, user: Any) -> Any:
    view = resource.viewset()
    view.action = action
    view.request = _request(METHODS.get(action, "GET"), user)
    view.format_kwarg = None
    view.args, view.kwargs = (), {}
    return view


def _visible(view: Any, row: Any, rows: Any = None) -> bool:
    """Whether ``row`` passes the *declared* row policy (``access`` + ``filter_queryset_for_user``).

    Computed from the declaration, never from the view's (overridable)
    ``read_scope``/``get_queryset``, so a viewset that bypasses its own
    declaration is caught.
    """
    from karni.accounts.permissions import ObjectPermissionsMixin
    from karni.api.access import Access, apply_rows

    queryset = type(row)._default_manager.filter(pk=row.pk)
    declaration = view.get_access()
    if rows is None and isinstance(declaration, Access):
        rows = declaration.read.bind(view, "view").rows(view.request)
    if rows is not None:
        queryset = apply_rows(queryset, rows)
    hook = type(view).filter_queryset_for_user
    if hook is not ObjectPermissionsMixin.filter_queryset_for_user:
        queryset = view.filter_queryset_for_user(queryset)
    return bool(queryset.exists())


def expectation(resource: Resource, action: str, user: Any, row: Any = None) -> Expectation:
    """What the viewset's ``access`` declaration promises ``user`` for ``action`` (on ``row``)."""
    from karni.api.access import Access, Unscoped, action_predicate

    anonymous = user is None or not getattr(user, "is_authenticated", False)
    denied = ANONYMOUS_DENIAL if anonymous else frozenset({403})
    view = _view(resource, action, user)
    declaration = view.get_access()
    success = frozenset({SUCCESS[action]})
    if declaration is None:
        return Expectation(denied, False, f"{resource.name} declares no access")
    if isinstance(declaration, Unscoped):
        request = view.request
        if all(p.has_permission(request, view) for p in view.get_permissions()):
            return Expectation(success, True)
        return Expectation(denied, False, "the viewset's permission_classes")
    if not isinstance(declaration, Access):
        return Expectation(denied, False, "an invalid access declaration")
    predicate = action_predicate(view, declaration)
    slot = {"list": "read", "retrieve": "read", "create": "create"}.get(action, "write")
    if not predicate.allows(view.request):
        return Expectation(denied, False, f"access {slot}={predicate!r}")
    for permission in view.get_permissions()[1:]:
        if not permission.has_permission(view.request, view):
            return Expectation(denied, False, f"{type(permission).__name__}")
    if row is not None:
        if not _visible(view, row):
            return Expectation(frozenset({404}), False, f"access read={declaration.read!r}")
        if slot == "write" and not _visible(view, row, predicate.rows(view.request)):
            return Expectation(frozenset({403}), False, f"access write={predicate!r}")
    return Expectation(success, True)


# payloads


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value.total_seconds())
    return value


def _related_model(model: type[models.Model], name: str, field: Any) -> Any:
    queryset = getattr(field, "queryset", None)
    if queryset is None and isinstance(field, ManyRelatedField):
        queryset = getattr(field.child_relation, "queryset", None)
    if queryset is not None:
        return queryset.model
    try:
        return model._meta.get_field(field.source or name).related_model
    except FieldDoesNotExist:
        return None


@dataclass
class Payload:
    """A create/update request body plus what was put in it."""

    data: dict[str, Any]
    multipart: bool = False
    #: Scalar fields whose stored value must equal what was sent.
    scalars: list[str] = field(default_factory=list)


def build_payload(
    resource: Resource,
    user: Any,
    *,
    values: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Payload:
    """A valid create body for ``resource`` as ``user``: every writable field the API takes.

    Scalars come from an unsaved factory row (so names and types decide the
    values, uniques stay unique); a required relation gets a new row the
    user can read; optional relations and to-many fields are left out.
    """
    from django.core.files.uploadedfile import SimpleUploadedFile

    from karni.testing.factories import build

    view = _view(resource, "create", user)
    serializer = view.get_serializer_class()(context=view.get_serializer_context())
    template = build(resource.model, **dict(values or {}))
    body = Payload({})
    for name, serializer_field in serializer.fields.items():
        if serializer_field.read_only:
            continue
        if isinstance(serializer_field, ManyRelatedField | RelatedField):
            if not serializer_field.required:
                continue
            target = _related_model(resource.model, name, serializer_field)
            if target is None:
                continue
            related = readable_row(target, user)
            pk = _json_value(related.pk)
            body.data[name] = [pk] if isinstance(serializer_field, ManyRelatedField) else pk
            continue
        if isinstance(serializer_field, serializers.FileField):
            if serializer_field.required:
                body.data[name] = SimpleUploadedFile(f"{name}.txt", b"karni")
                body.multipart = True
            continue
        source = serializer_field.source or name
        if source == "*" or "." in source:
            continue
        current = getattr(template, source, None)
        if current is None and not serializer_field.required:
            continue
        try:
            body.data[name] = _json_value(serializer_field.to_representation(current))
        except Exception:  # noqa: BLE001 - a computed field; leave it to `payload=`
            continue
        body.scalars.append(name)
    body.data.update(payload or {})
    return body


# the run


@dataclass
class CrudReport:
    """What :func:`assert_crud` checked (``passed``) and what failed."""

    resource: str
    role: str | None
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def render(self) -> str:
        who = f"role {self.role!r}" if self.role else "an authenticated user"
        lines = [
            f"assert_crud({self.resource}) as {who}: {len(self.failures)} problem(s) "
            f"({len(self.passed)} checks passed)"
        ]
        lines += [f"  - {failure}" for failure in self.failures]
        return "\n".join(lines)


class _RequestError(KarniAssertionError):
    code = "E604"


@contextmanager
def _unthrottled(viewset: type[Any]) -> Iterator[None]:
    had = "throttle_classes" in viewset.__dict__
    previous = viewset.__dict__.get("throttle_classes")
    viewset.throttle_classes = ()
    try:
        yield
    finally:
        if had:
            viewset.throttle_classes = previous
        else:
            del viewset.throttle_classes


def _ids(data: Any) -> list[str]:
    rows = data.get("results", []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [str(row.get("id", row.get("pk"))) for row in rows if isinstance(row, dict)]


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return str(value)


class _Crud:
    """One :func:`assert_crud` run."""

    def __init__(
        self,
        resource: Resource,
        role: str | None,
        *,
        user: Any,
        values: Mapping[str, Any],
        payload: Mapping[str, Any],
        expect: Mapping[str, int],
        skip: Iterable[str],
    ) -> None:
        unknown = set(skip) - set(CHECKS)
        if unknown:
            raise KarniValueError(
                f"skip={sorted(unknown)}: unknown checks (known: {', '.join(CHECKS)})", code="E603"
            )
        self.resource = resource
        self.role = role
        self.values = dict(values)
        self.payload = dict(payload)
        self.expect = dict(expect)
        self.skip = set(skip)
        self.user = user if user is not None else user_with_roles(*([role] if role else []))
        self.report = CrudReport(resource.name, role)
        self.schema_errors: list[str] = []
        self.documented: dict[str, Any] = {}

    # plumbing

    def client(self, user: Any) -> KarniAPIClient:
        return client_as(None) if user is None else client_as(user=user)

    def call(
        self, check: str, user: Any, method: str, url: str, data: Any = None, **kw: Any
    ) -> Any:
        client = self.client(user)
        try:
            return getattr(client, method.lower())(url, data, **kw)
        except Exception as exc:
            raise _RequestError(
                f"{check}: {method} {url} raised {type(exc).__name__}: {exc}"
            ) from exc

    def fail(self, message: str) -> None:
        self.report.failures.append(message)

    def row(self, user: Any | None = None, **values: Any) -> Any:
        return readable_row(self.resource.model, user or self.user, **{**self.values, **values})

    def expected(self, action: str, user: Any, row: Any = None) -> Expectation:
        found = expectation(self.resource, action, user, row)
        pinned = self.expect.get(action)
        if pinned is not None and user is self.user:
            return Expectation(frozenset({pinned}), pinned < 400, "pinned by expect=")
        return found

    def status(self, check: str, response: Any, expected: Expectation, what: str) -> bool:
        if response.status_code in expected.statuses:
            return True
        detail = ""
        try:
            body = response.json()
            detail = f": {body.get('detail', body)!s:.160}" if isinstance(body, dict) else ""
        except Exception:  # noqa: BLE001 - a non-JSON body
            detail = ""
        self.fail(
            f"{check}: {what} answered {response.status_code}, expected "
            f"{expected.describe()}{detail}"
        )
        return False

    def contract(self, method: str, url: str, response: Any) -> None:
        """Validate a successful response body against its documented schema."""
        from karni.testing.schema import find_operation, generate_schema, response_schema, validate

        if "schema" in self.skip:
            return
        path = url.split("?", 1)[0]
        document = generate_schema(cached=True, user=self.user)  # the schema this role is served
        operation = find_operation(document, path, method)
        if operation is None:
            self.schema_errors.append(f"{method} {path} is not in the OpenAPI schema")
            return
        self.documented[f"{method} {path}"] = operation
        if response.status_code == 204 or getattr(response, "streaming", False):
            return None
        if not response.content:
            return
        documented = response_schema(operation, response.status_code)
        if documented is None:
            self.schema_errors.append(
                f"{method} {path} answered {response.status_code}, which the schema does not "
                "document"
            )
            return
        for problem in validate(response.json(), documented, document)[:5]:
            self.schema_errors.append(f"{method} {path} {response.status_code}: {problem}")

    def stored(self, row: Any) -> Any:
        return self.resource.model._default_manager.filter(pk=row.pk).first()

    def matches(self, sent: Payload, response: Any, row: Any, action: str) -> None:
        """The stored row carries every scalar that was sent."""
        view = _view(self.resource, action, self.user)
        serializer_class = view.get_serializer_class()
        context = view.get_serializer_context()
        rendered = serializer_class(instance=row, context=context).data
        fields = serializer_class(context=context).fields
        for name in sent.scalars:
            if name not in sent.data or name not in rendered:
                continue
            serializer_field = fields[name]
            try:
                want = serializer_field.to_internal_value(sent.data[name])
                have = serializer_field.to_internal_value(rendered[name])
            except Exception:  # noqa: BLE001 - compare the representations instead
                want, have = sent.data[name], rendered[name]
            if want != have:
                self.fail(
                    f"{action}: sent {name}={sent.data[name]!r} but stored {rendered[name]!r}"
                )

    # checks

    def preflight(self, row: Any) -> bool:
        """Fail early when the run could only confirm that everything is refused."""
        from karni.api.access import missing_access_message

        viewset = self.resource.viewset
        if viewset().get_access() is None:
            self.fail(f"access: {missing_access_message(viewset)}")
            return False
        actions = ("list", "retrieve", "create", "partial_update", "destroy")
        allowed = [
            action
            for action in actions
            if self.expected(
                action, self.user, row if action not in {"list", "create"} else None
            ).allowed
        ]
        if not allowed and not self.expect:
            who = f"role {self.role!r}" if self.role else "an authenticated user"
            self.fail(
                f"access: {who} is refused every action of {self.resource.name} "
                f"(access={viewset.access!r}). Check the role name, and pin the refusals "
                "with expect={...} if they are intended."
            )
            return False
        return True

    def run(self) -> CrudReport:
        with _unthrottled(self.resource.viewset):
            row = self.row()
            if not self.preflight(row):
                return self.report
            for name, check in (
                ("list", lambda: self.check_list(row)),
                ("retrieve", lambda: self.check_retrieve(row)),
                ("create", self.check_create),
                ("update", lambda: self.check_update(row)),
                ("delete", self.check_delete),
                ("denials", lambda: self.check_denials(row)),
                ("pagination", self.check_pagination),
                ("filtering", self.check_filtering),
                ("visibility", self.check_visibility),
                ("schema", self.check_schema),
            ):
                if name in self.skip:
                    self.report.skipped.append(name)
                    continue
                before = len(self.report.failures)
                try:
                    check()
                except _RequestError as exc:
                    self.fail(str(exc))
                    break  # the transaction may be unusable after an exception
                if len(self.report.failures) == before:
                    self.report.passed.append(name)
        return self.report

    def check_list(self, row: Any) -> None:
        expected = self.expected("list", self.user)
        url = self.resource.list_url()
        response = self.call("list", self.user, "GET", url)
        if not self.status("list", response, expected, f"GET {url}") or not expected.allowed:
            return
        self.contract("GET", url, response)
        if str(row.pk) not in _ids(response.json()):
            self.fail(
                f"list: GET {url} does not include the requester's row {row.pk} "
                f"(read={self.resource.viewset.access!r})"
            )

    def check_retrieve(self, row: Any) -> None:
        expected = self.expected("retrieve", self.user, row)
        url = self.resource.detail_url(row.pk)
        response = self.call("retrieve", self.user, "GET", url)
        if not self.status("retrieve", response, expected, f"GET {url}") or not expected.allowed:
            return
        self.contract("GET", url, response)
        body = response.json()
        if str(body.get("id", body.get("pk"))) != str(row.pk):
            self.fail(f"retrieve: GET {url} returned another row ({body.get('id')})")

    def check_create(self) -> None:
        expected = self.expected("create", self.user)
        sent = build_payload(self.resource, self.user, values=self.values, payload=self.payload)
        url = self.resource.list_url()
        manager = self.resource.model._default_manager
        before = manager.count()
        fmt = "multipart" if sent.multipart else "json"
        response = self.call("create", self.user, "POST", url, sent.data, format=fmt)
        if not self.status("create", response, expected, f"POST {url}"):
            return
        if not expected.allowed:
            if manager.count() != before:
                self.fail(f"create: POST {url} was refused but a row was written anyway")
            return
        self.contract("POST", url, response)
        created = manager.filter(pk=response.json().get("id")).first()
        if created is None:
            self.fail(f"create: POST {url} answered 201 but no row with its id exists")
            return
        self.matches(sent, response, created, "create")
        view = _view(self.resource, "create", self.user)
        for owner in view.get_owner_fields():
            if getattr(created, f"{owner}_id", None) != self.user.pk:
                self.fail(
                    f"create: {self.resource.model.__name__}.{owner} was not stamped with the "
                    "requester (access Owned(...) owner fields are set server-side)"
                )

    def check_update(self, row: Any) -> None:
        url = self.resource.detail_url(row.pk)
        expected = self.expected("partial_update", self.user, row)
        fresh = build_payload(self.resource, self.user, values=self.values, payload=self.payload)
        view = _view(self.resource, "partial_update", self.user)
        current = view.get_serializer_class()(row, context=view.get_serializer_context()).data
        change = next(
            (
                name
                for name in fresh.scalars
                if name in current and _json_value(current[name]) != fresh.data.get(name)
            ),
            None,
        )
        patch = {change: fresh.data[change]} if change else {}
        snapshot = self.stored(row)
        response = self.call("update", self.user, "PATCH", url, patch, format="json")
        if not self.status("update", response, expected, f"PATCH {url}"):
            return
        if not expected.allowed:
            if change and _field_value(self.stored(row), change) != _field_value(snapshot, change):
                self.fail(f"update: PATCH {url} was refused but {change} changed anyway")
            return
        self.contract("PATCH", url, response)
        if change:
            self.matches(Payload(patch, scalars=[change]), response, self.stored(row), "update")
        expected_put = self.expected("update", self.user, row)
        fmt = "multipart" if fresh.multipart else "json"
        response = self.call("update", self.user, "PUT", url, fresh.data, format=fmt)
        if self.status("update", response, expected_put, f"PUT {url}") and expected_put.allowed:
            self.contract("PUT", url, response)

    def check_delete(self) -> None:
        victim = self.row()
        url = self.resource.detail_url(victim.pk)
        expected = self.expected("destroy", self.user, victim)
        response = self.call("delete", self.user, "DELETE", url)
        if not self.status("delete", response, expected, f"DELETE {url}"):
            return
        still_there = self.stored(victim) is not None
        if not expected.allowed:
            if not still_there:
                self.fail(f"delete: DELETE {url} was refused but the row is gone")
            return
        if still_there:
            self.fail(f"delete: DELETE {url} answered 204 but the row is still visible")
        after = self.call("delete", self.user, "GET", url)
        if after.status_code != 404:
            self.fail(f"delete: GET {url} after the delete answered {after.status_code}, not 404")

    def check_denials(self, row: Any) -> None:
        outsider = user_with_roles()
        manager = self.resource.model._default_manager
        for who, user in (("anonymous", None), ("a user without the role", outsider)):
            if user is outsider and not self.role:
                continue  # without a role the requester already is such a user
            for action in ("list", "retrieve", "create", "partial_update", "destroy"):
                target = row if action in {"retrieve", "partial_update", "destroy"} else None
                expected = expectation(self.resource, action, user, target)
                if expected.allowed:
                    continue
                method = METHODS[action]
                url = self.resource.detail_url(row.pk) if target else self.resource.list_url()
                data = None
                if action == "create":
                    data = build_payload(self.resource, self.user, values=self.values).data
                before = manager.count()
                response = self.call("denials", user, method, url, data, format="json")
                self.status("denials", response, expected, f"{method} {url} as {who}")
                if method != "GET" and manager.count() != before:
                    self.fail(f"denials: {method} {url} as {who} changed the row count")
                if action == "destroy" and self.stored(row) is None:
                    self.fail(f"denials: DELETE {url} as {who} deleted the row")
                    return

    def check_pagination(self) -> None:
        from karni.pagination import UnpaginatedPagination

        if not self.expected("list", self.user).allowed:
            self.report.skipped.append("pagination (list is denied for this role)")
            return
        paginator = self.resource.viewset.pagination_class
        url = self.resource.list_url()
        if paginator is not None and issubclass(paginator, UnpaginatedPagination):
            response = self.call("pagination", self.user, "GET", url)
            if not isinstance(response.json(), list):
                self.fail(f"pagination: {url} declares Unpaginated but returned a page envelope")
            return
        for _ in range(3):
            self.row()
        param = getattr(paginator, "page_size_query_param", None) or "page_size"
        first = self.call("pagination", self.user, "GET", url, {param: 2})
        body = first.json()
        if not isinstance(body, dict) or "results" not in body:
            self.fail(f"pagination: GET {url}?{param}=2 returned no page envelope (results)")
            return
        page = _ids(body)
        if len(page) != 2:
            self.fail(
                f"pagination: GET {url}?{param}=2 returned {len(page)} rows, expected 2: the "
                f"paginator ignores {param} ({paginator.__name__ if paginator else None})"
            )
            return
        if "count" in body and (not isinstance(body["count"], int) or body["count"] < 3):
            self.fail(f"pagination: count is {body['count']!r} with at least 3 visible rows")
        following = body.get("next")
        if not following:
            self.fail(f"pagination: GET {url}?{param}=2 has no next link with more rows left")
            return
        second = self.call("pagination", self.user, "GET", following)
        overlap = set(page) & set(_ids(second.json()))
        if not _ids(second.json()) or overlap:
            self.fail(
                f"pagination: the next page ({following}) "
                + ("repeats rows " + ", ".join(sorted(overlap)) if overlap else "is empty")
            )
        self.contract("GET", url, first)

    def check_filtering(self) -> None:
        if not self.expected("list", self.user).allowed:
            self.report.skipped.append("filtering (list is denied for this role)")
            return
        first, second = self.row(), self.row()
        url = self.resource.list_url()
        candidate = _filter_candidate(self.resource, self.user, first, second)
        if candidate is None:
            self.report.skipped.append("filtering (no derived filter tells two rows apart)")
        else:
            param, value, shown = candidate
            response = self.call("filtering", self.user, "GET", url, {param: value})
            ids = _ids(response.json())
            if str(first.pk) not in ids:
                self.fail(f"filtering: GET {url}?{param}={value} lost the matching row {first.pk}")
            if str(second.pk) in ids:
                self.fail(
                    f"filtering: GET {url}?{param}={value} also returned a row whose "
                    f"{shown} differs, so the filter is ignored (check filter_backends / filterset)"
                )
            self.documented.setdefault("filter", param)
        search_fields = tuple(getattr(self.resource.viewset, "search_fields", ()) or ())
        if search_fields:
            token = _search_token(first, search_fields[0])
            if token:
                response = self.call("filtering", self.user, "GET", url, {"search": token})
                if str(first.pk) not in _ids(response.json()):
                    self.fail(f"filtering: GET {url}?search={token} did not find row {first.pk}")

    def check_visibility(self) -> None:
        """Fields ``Karni.field_roles`` hides from the role are absent everywhere (P3)."""
        from karni.accounts.visibility import hidden_fields, protected_fields

        model = self.resource.model
        hidden = hidden_fields(model, self.user)
        protected = protected_fields(model, self.user) - hidden
        if not hidden and not protected:
            self.report.skipped.append("visibility (field_roles hides nothing from this role)")
            return
        row = self.row()
        who = f"role {self.role!r}" if self.role else "this user"
        for action, url in (
            ("list", self.resource.list_url()),
            ("retrieve", self.resource.detail_url(row.pk)),
        ):
            target = row if action == "retrieve" else None
            if not self.expected(action, self.user, target).allowed:
                continue
            response = self.call("visibility", self.user, "GET", url)
            if response.status_code != 200:
                continue
            body = response.json()
            items = body.get("results", []) if action == "list" else [body]
            for item in items:
                leaked = sorted(hidden & set(item))
                if leaked:
                    self.fail(
                        f"visibility: GET {url} returns {', '.join(leaked)}, which "
                        f"field_roles hides from {who} (hidden fields must be absent)"
                    )
                    break
        view = _view(self.resource, "retrieve", self.user)
        published = set(view.get_serializer_class()(context=view.get_serializer_context()).fields)
        documented = sorted(hidden & published)
        if documented:
            self.fail(
                f"visibility: the serializer (and so the schema) for {who} still lists "
                f"{', '.join(documented)}"
            )
        if protected and self.expected("partial_update", self.user, row).allowed:
            name = sorted(protected)[0]
            current = getattr(row, name, None)
            sent = _json_value(current) if current is not None else ""
            response = self.call(
                "visibility", self.user, "PATCH", self.resource.detail_url(row.pk), {name: sent}
            )
            if response.status_code != 400 or name not in response.json():
                self.fail(
                    f"visibility: PATCH {name} as {who} answered {response.status_code}, but "
                    f"field_roles lets only {', '.join(protected_roles(model, name))} change "
                    "it, so the request must be refused naming the field"
                )

    def check_schema(self) -> None:
        from karni.testing.schema import find_operation, generate_schema

        document = generate_schema(cached=True, user=self.user)
        list_path = self.resource.list_url()
        probe = self.resource.detail_url(uuid.UUID(int=0))
        for method, path, action in (
            ("GET", list_path, "list"),
            ("POST", list_path, "create"),
            ("GET", probe, "retrieve"),
            ("PATCH", probe, "partial_update"),
            ("PUT", probe, "update"),
            ("DELETE", probe, "destroy"),
        ):
            viewset = self.resource.viewset
            if not callable(getattr(viewset, action, None)):
                continue
            if method.lower() not in viewset.http_method_names:
                continue
            if find_operation(document, path, method) is None:
                self.schema_errors.append(f"{method} {path} ({action}) is not in the schema")
        operation = find_operation(document, list_path, "GET") or {}
        names = {p.get("name") for p in operation.get("parameters", ()) if isinstance(p, dict)}
        paginator = self.resource.viewset.pagination_class
        wanted = {getattr(paginator, "page_size_query_param", None), self.documented.get("filter")}
        for name in sorted(n for n in wanted if n):
            if name not in names:
                self.schema_errors.append(f"GET {list_path}: parameter {name!r} is not documented")
        for problem in dict.fromkeys(self.schema_errors):
            self.fail(f"schema: {problem}")


def _field_value(row: Any, name: str) -> Any:
    return getattr(row, name, None) if row is not None else None


def protected_roles(model: type[models.Model], name: str) -> tuple[str, ...]:
    from karni.accounts.visibility import allowed_roles

    return allowed_roles(model, name, "write")


def _filter_candidate(
    resource: Resource, user: Any, first: Any, second: Any
) -> tuple[str, str, str] | None:
    """``(query param, value of first, field)`` for an exact filter that tells the rows apart."""
    from django_filters.rest_framework import DjangoFilterBackend

    view = _view(resource, "list", user)
    from karni.api.filters import KarniFilterBackend

    backends = [b for b in view.filter_backends if isinstance(b, type)]
    backend = next((b() for b in backends if issubclass(b, DjangoFilterBackend)), None)
    queryset = resource.model._default_manager.all()
    filterset = backend.get_filterset_class(view, queryset) if backend is not None else None
    if filterset is None:
        # What a BaseViewSet promises: the derived filters (a removed or broken
        # backend then shows up as an ignored filter).
        filterset = KarniFilterBackend().derive_filterset_class(resource.model)
    ranked: list[tuple[int, str, str]] = []
    for param, declared in filterset.base_filters.items():
        if getattr(declared, "lookup_expr", "exact") != "exact":
            continue
        name = declared.field_name
        try:
            model_field = resource.model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        ranked.append((_filter_rank(model_field), param, name))
    for _rank, param, name in sorted(ranked):
        left, right = getattr(first, name, None), getattr(second, name, None)
        if left is None or left == right:
            continue
        return param, _query_value(left), name
    return None


def _filter_rank(model_field: Any) -> int:
    if getattr(model_field, "choices", None):
        return 0
    if isinstance(model_field, models.CharField):
        return 1
    if isinstance(model_field, models.BooleanField):
        return 2
    if isinstance(model_field, models.IntegerField | models.DecimalField | models.FloatField):
        return 3
    if model_field.is_relation:
        return 4
    if isinstance(model_field, models.DateTimeField):
        return 6
    return 5


def _search_token(row: Any, path: str) -> str:
    value: Any = row
    for part in path.lstrip("^=@$").split("__"):
        value = getattr(value, part, None)
    words = [w.strip(".,;:!?'\"()") for w in str(value or "").split()]
    words = [w for w in words if len(w) >= 4 and w.isalpha()]
    return max(words, key=len) if words else ""


def assert_crud(
    resource: Any,
    role: str | None = None,
    *,
    user: Any = None,
    values: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
    expect: Mapping[str, int] | None = None,
    skip: Iterable[str] = (),
) -> CrudReport:
    """Assert the full CRUD surface of ``resource`` for ``role`` (see the module docstring).

    :param resource: a viewset class, a model class, a route prefix or ``"app.Model"``.
    :param role: the requester's role (Django group); ``None`` = any authenticated user.
    :param user: an explicit requester (overrides ``role``).
    :param values: factory overrides for every row created and for the create payload.
    :param payload: raw request fields merged into every create/update body.
    :param expect: pin the requester's status per action (``list``, ``retrieve``,
        ``create``, ``update``, ``partial_update``, ``destroy``).
    :param skip: checks to leave out (:data:`CHECKS`).
    :raises AssertionError: listing every failed check.
    """
    run = _Crud(
        resolve_resource(resource),
        role,
        user=user,
        values=values or {},
        payload=payload or {},
        expect=expect or {},
        skip=skip,
    )
    report = run.run()
    if report.failures:
        raise KarniAssertionError(report.render(), code="E602")
    return report


class APITestCase(drf_test.APITestCase):
    """DRF's ``APITestCase`` with clients per role and the one-call CRUD/isolation/hiding checks."""

    client_class = KarniAPIClient

    def _users(self) -> dict[tuple[str, ...], Any]:
        users: dict[tuple[str, ...], Any] | None = getattr(self, "_karni_users", None)
        if users is None:
            users = {}
            self._karni_users = users
        return users

    def user_as(self, *roles: str) -> Any:
        """The test's user holding exactly ``roles`` (created once per test)."""
        key = tuple(sorted(roles))
        users = self._users()
        if key not in users:
            users[key] = user_with_roles(*key)
        return users[key]

    def client_as(self, *roles: str | None, user: Any = None) -> KarniAPIClient:
        """A client for ``roles`` (the same user all test long); ``None`` alone: anonymous."""
        if user is None and roles == (None,):
            return client_as(None)
        if user is None:
            user = self.user_as(*(role for role in roles if role))
        return client_as(user=user)

    def assert_crud(self, resource: Any, role: str | None = None, **options: Any) -> CrudReport:
        """:func:`assert_crud` (``role``'s user is this test's :meth:`user_as` user)."""
        options.setdefault("user", self.user_as(*([role] if role else [])))
        return assert_crud(resource, role, **options)

    def assert_isolated(self, resource: Any, role: str | None = None, **options: Any) -> Any:
        """:func:`karni.testing.isolation.assert_isolated`."""
        from karni.testing.isolation import assert_isolated

        return assert_isolated(resource, role, **options)

    def assert_row_hidden(self, client: Any, resource: Any, row: Any, **options: Any) -> Any:
        """:func:`karni.testing.hidden.assert_row_hidden`."""
        from karni.testing.hidden import assert_row_hidden

        return assert_row_hidden(client, resource, row, **options)

    def assert_admin_row_hidden(self, client: Any, row: Any, **options: Any) -> Any:
        """:func:`karni.testing.hidden.assert_admin_row_hidden`."""
        from karni.testing.hidden import assert_admin_row_hidden

        return assert_admin_row_hidden(client, row, **options)
