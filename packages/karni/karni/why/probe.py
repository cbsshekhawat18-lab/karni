"""Run the real gate and the real lookups for one request, without running the handler.

The probe builds the viewset exactly as the router does (same class, same
initkwargs, same method → action map), wraps a request for the user the way
DRF's test client does (``force_authenticate``), and calls DRF's own
``initial()`` — authentication, ``check_permissions`` (Karni's
:class:`~karni.api.access.AccessPermission` first, then any
``permission_classes``) — then the lookup the action would make:
``get_object()`` for a detail action (the read scope, then the object
check), ``filter_queryset(get_queryset())`` for a list. Exceptions go through
the view's own ``handle_exception``, so the status is the one the API sends
(401 vs 403 included). The handler body never runs, nothing is written,
throttles are not consumed, and everything happens inside a transaction that
is rolled back.

While it runs, the access layer records each decision on the request
(:data:`karni.api.access.TRACE_ATTR`): the verdict ``karni why`` prints is
read from what the enforcement code did, never recomputed beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import router as db_router
from django.db import transaction

from karni.api.access import TRACE_ATTR, AccessEvent
from karni.why.resolve import ActionSpec, Resource

__all__ = ["Probe", "run_probe"]

#: The status an action answers when the access layer admits it and the handler succeeds.
SUCCESS: dict[str, int] = {"create": 201, "destroy": 204}


@dataclass
class Probe:
    """What the API did with one request, up to (not including) the handler."""

    resource: Resource
    action: ActionSpec
    user: Any
    pk: Any
    path: str
    query: dict[str, list[str]]
    status: int = 0
    detail: Any = None
    events: list[AccessEvent] = field(default_factory=list)
    view: Any = None
    request: Any = None
    instance: Any = None
    in_list: bool | None = None
    count: int | None = None
    exception: BaseException | None = None
    uncaught: BaseException | None = None

    def mine(self, kind: str) -> list[AccessEvent]:
        """This view's events of ``kind`` (relation scoping records its targets' too)."""
        return [e for e in self.events if e.kind == kind and e.data.get("view") is self.view]

    def first(self, kind: str) -> AccessEvent | None:
        found = self.mine(kind)
        return found[0] if found else None

    @property
    def allowed(self) -> bool:
        return 200 <= self.status < 300


def _never_throttled(request: Any) -> None:
    """``check_throttles`` replacement: a probe must not use up anyone's rate limit."""


def _host() -> str:
    hosts = [h for h in getattr(settings, "ALLOWED_HOSTS", []) or [] if h and h != "*"]
    if not hosts:
        return "localhost"
    host = hosts[0].lstrip(".")
    return host or "localhost"


def run_probe(
    resource: Resource,
    action: ActionSpec,
    user: Any,
    *,
    pk: Any = None,
    query: dict[str, list[str]] | None = None,
    path: str | None = None,
) -> Probe:
    """The API's answer to ``action`` on ``resource`` (row ``pk``) for ``user``, minus effects."""
    from rest_framework.test import APIRequestFactory, force_authenticate

    from karni.middleware import current_user

    query = {key: list(values) for key, values in (query or {}).items()}
    url = path or action.path(resource, pk)
    probe = Probe(resource=resource, action=action, user=user, pk=pk, path=url, query=query)
    encoded = urlencode(query, doseq=True)
    factory = APIRequestFactory(SERVER_NAME=_host())
    django_request = factory.generic(
        action.method,
        f"{url}?{encoded}" if encoded else url,
        content_type="application/json",
    )
    authenticated = bool(getattr(user, "is_authenticated", False))
    if authenticated:
        force_authenticate(django_request, user=user)

    view = resource.viewset(**action.initkwargs)
    view.action_map = dict(action.mapping)
    for method, name in view.action_map.items():
        setattr(view, method, getattr(view, name))
    kwargs = {action.lookup: str(pk)} if action.detail and pk is not None else {}
    view.request = django_request
    view.args = ()
    view.kwargs = kwargs
    view.headers = view.default_response_headers
    probe.view = view

    using = db_router.db_for_read(resource.model)
    with transaction.atomic(using=using), current_user(user if authenticated else None):
        request = view.initialize_request(django_request, **kwargs)
        setattr(request, TRACE_ATTR, probe.events)
        view.request = request
        view.check_throttles = _never_throttled  # instance attribute: the class is untouched
        probe.request = request
        try:
            view.initial(request, **kwargs)
            probe.status = _lookup(view, action, probe)
        except Exception as exc:  # noqa: BLE001 - every outcome is the answer
            probe.exception = exc
            try:
                response = view.handle_exception(exc)
            except Exception as uncaught:  # noqa: BLE001 - a 500 is an answer too
                probe.uncaught = uncaught
                probe.status = 500
                probe.detail = str(uncaught)
            else:
                probe.status = int(response.status_code)
                probe.detail = response.data
        transaction.set_rollback(True, using=using)
    return probe


def _lookup(view: Any, action: ActionSpec, probe: Probe) -> int:
    """What the action does before its own code runs: the row lookup or the list query."""
    if action.name == "list":
        queryset = view.filter_queryset(view.get_queryset())
        probe.count = queryset.count()
        if probe.pk is not None:
            try:
                probe.in_list = queryset.filter(pk=probe.pk).exists()
            except (ValidationError, ValueError, TypeError):
                probe.in_list = False
        return 200
    if action.detail and probe.pk is not None:
        probe.instance = view.get_object()
    # A detail action probed without a row answers the gate only.
    return SUCCESS.get(action.name, 200)
