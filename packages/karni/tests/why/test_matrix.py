"""Equivalence: for every (user, resource, action, row), ``karni why`` says what the API does.

The API side goes through the router's own URL patterns (``router.urls``):
the view function DRF builds, full ``dispatch``, the handler running for real
inside a rolled-back transaction. The why side is :func:`karni.why.explain_row`
/ :func:`karni.why.explain_field`, full explanation included, so a crash in
any explanation branch fails here too.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

import pytest
from django.db import transaction
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.api.routers import resolve_router
from karni.why import explain_field, explain_list, explain_row
from tests.testapp.models import Customer, Event

pytestmark = pytest.mark.django_db

RESOURCES = ("granted-events", "declared-events", "guarded-events", "open-events")
#: (why action word, router url suffix, HTTP method, needs a row)
ACTIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("view", "detail", "get", True),
    ("update", "detail", "patch", True),
    ("delete", "detail", "delete", True),
    ("create", "list", "post", False),
)
EXTRA = {"granted-events": ("approve", "post"), "declared-events": ("dashboard", "get")}


def _patterns() -> dict[str, Any]:
    router = resolve_router()
    assert router is not None
    return {pattern.name: pattern for pattern in router.urls if pattern.name}


def _api(
    name: str, method: str, user: Any, *, pk: Any = None, data: Any = None, query: Any = None
) -> Any:
    """The API's own answer: the router's view, dispatched, effects rolled back."""
    pattern = _patterns()[name]
    factory = APIRequestFactory()
    if method == "get":
        request = factory.get("/", query or {})
    else:
        request = getattr(factory, method)("/", data if data is not None else {}, format="json")
    if getattr(user, "is_authenticated", False):
        force_authenticate(request, user=user)
    with transaction.atomic():
        response = pattern.callback(request, **({"pk": str(pk)} if pk is not None else {}))
        response.render()
        transaction.set_rollback(True)
    return response


def _access_answer(status: int) -> int | str:
    """What an access decision can be: 401, 403, 404, or admitted (a 400 is the body's fault)."""
    return status if status in (401, 403, 404) else "admitted"


def test_row_verdicts_equal_the_api(world: Any) -> None:
    compared: Counter[str] = Counter()
    for resource in RESOURCES:
        actions = list(ACTIONS)
        if resource in EXTRA:
            word, method = EXTRA[resource]
            actions.append((word, word, method, True))
        for user_name, user in world.users.items():
            for word, suffix, method, needs_row in actions:
                rows = world.rows.items() if needs_row else [("-", None)]
                for row_name, row in rows:
                    pk = row.pk if row is not None else None
                    verdict = explain_row(resource, pk, user, word)
                    response = _api(f"{resource}-{suffix}", method, user, pk=pk)
                    case = f"{resource} {word} {row_name} as {user_name}"
                    if word == "create":
                        assert _access_answer(verdict.status or 0) == _access_answer(
                            response.status_code
                        ), case
                    else:
                        assert verdict.status == response.status_code, (
                            case,
                            verdict.status,
                            response.status_code,
                            verdict.text(),
                        )
                    assert verdict.summary and verdict.outcome, case
                    compared[resource] += 1
    assert sum(compared.values()) >= 700, compared


def test_list_presence_equals_the_api(world: Any) -> None:
    compared = 0
    for resource in RESOURCES:
        for user_name, user in world.users.items():
            response = _api(f"{resource}-list", "get", user, query={"page_size": 100})
            listed = (
                {str(item["id"]) for item in response.data["results"]}
                if response.status_code == 200
                else set()
            )
            for row_name, row in world.rows.items():
                verdict = explain_row(resource, row.pk, user, "list")
                case = f"{resource} list {row_name} as {user_name}"
                assert verdict.status == response.status_code, case
                if response.status_code == 200:
                    assert (verdict.outcome == "listed") == (str(row.pk) in listed), (
                        case,
                        verdict.text(),
                    )
                compared += 1
            empty = explain_list(resource, user)
            assert empty.status == response.status_code
            if response.status_code == 200:
                assert empty.data["count"] == response.data["count"], (resource, user_name)
                assert (empty.outcome == "empty") == (response.data["count"] == 0)
    assert compared >= 150


FIELDS: dict[str, dict[str, Any]] = {
    "customers": {
        "name": "Renamed",
        "phone": "+1 555 0199",
        "internal_note": "changed",
        "salary": "99.00",
    },
    "declared-events": {"title": "Retitled", "status": "published", "internal_note": "x"},
}


def _stored(resource: str, pk: Any, name: str) -> Any:
    model = Customer if resource == "customers" else Event
    value = getattr(model.objects.get(pk=pk), name)
    return str(value) if isinstance(value, Decimal) else value


def test_field_verdicts_equal_the_api(world: Any) -> None:
    compared = 0
    targets = {
        "customers": world.customers["acme"].pk,
        "declared-events": world.rows["alice-published"].pk,
    }
    for resource, pk in targets.items():
        for user_name, user in world.users.items():
            if not getattr(user, "is_authenticated", False):
                continue
            read = _api(f"{resource}-detail", "get", user, pk=pk)
            for name, value in FIELDS[resource].items():
                verdict = explain_field(resource, name, user)
                field = verdict.data["field"]
                case = f"{resource}.{name} as {user_name}"
                if read.status_code == 200:
                    assert field["readable"] == (name in read.data), (case, verdict.text())
                write = _patch_effect(resource, pk, name, value, user)
                if write is not None:
                    assert field["writable"] == write, (case, verdict.text())
                compared += 1
    assert compared >= 40


def _patch_effect(resource: str, pk: Any, name: str, value: Any, user: Any) -> bool | None:
    """Whether a PATCH of ``name`` changes the stored value (``None`` when the row is refused)."""
    pattern = _patterns()[f"{resource}-detail"]
    request = APIRequestFactory().patch("/", {name: value}, format="json")
    force_authenticate(request, user=user)
    with transaction.atomic():
        before = _stored(resource, pk, name)
        response = pattern.callback(request, pk=str(pk))
        changed = _stored(resource, pk, name) != before
        transaction.set_rollback(True)
    if response.status_code in (401, 403, 404):
        return None
    return bool(response.status_code == 200 and changed)
