"""``GET /<resource>/<id>/history/``: scope- and visibility-aware, documented only when audited."""

from __future__ import annotations

import decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIRequestFactory, force_authenticate

from karni.accounts.permissions import assign_role
from karni.api import Access, Authenticated, BaseViewSet, Owned
from karni.api.routers import KarniRouter
from karni.middleware import current_user
from tests.testapp.models import Price, Venue

pytestmark = pytest.mark.django_db


class PriceViewSet(BaseViewSet):
    model = Price
    access = Access(read=Authenticated(), write=Authenticated())


class OwnPriceViewSet(BaseViewSet):
    model = Price
    access = Access(read=Owned("created_by"), write=Owned("created_by"))


class PlainVenueViewSet(BaseViewSet):
    model = Venue
    access = Access(read=Authenticated(), write=Authenticated())


def router() -> KarniRouter:
    found = KarniRouter()
    found.register("prices", PriceViewSet, basename="prices")
    found.register("own-prices", OwnPriceViewSet, basename="own-prices")
    found.register("plain-venues", PlainVenueViewSet, basename="plain-venues")
    return found


def _user(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(email=email, password="a-strong-password-123")
    for role in roles:
        assign_role(user, role)
    return user


def _history(viewset: type[Any], user: Any, pk: Any, **query: Any) -> Any:
    request = APIRequestFactory().get("/", query)
    force_authenticate(request, user=user)
    return viewset.as_view({"get": "history"})(request, pk=str(pk))


def test_history_lists_the_rows_changes_newest_first() -> None:
    staff = _user("staff@example.com", "staff")
    with current_user(staff):
        price = Price.objects.create(amount=decimal.Decimal("10.00"), currency="EUR")
        price.amount = decimal.Decimal("11.00")
        price.save()
    response = _history(PriceViewSet, staff, price.pk)
    assert response.status_code == 200, response.data
    results = response.data["results"]
    assert [entry["action"] for entry in results] == ["update", "create"]
    assert results[0]["diff"] == {"amount": ["10.00", "11.00"]}
    assert results[0]["fields_changed"] == ["amount"]
    assert results[0]["actor"]["email"] == "staff@example.com"
    assert "note" not in results[1]["diff"]  # empty on create: nothing recorded


def test_history_hides_fields_the_role_cannot_see() -> None:
    member = _user("member@example.com", "user")
    price = Price.objects.create(amount=decimal.Decimal("10.00"), currency="EUR")
    response = _history(PriceViewSet, member, price.pk)
    assert response.status_code == 200
    (entry,) = response.data["results"]
    assert "amount" not in entry["diff"] and entry["diff"]["currency"] == [None, "EUR"]
    assert entry["fields_changed"] and "amount" not in entry["fields_changed"]


def test_history_of_an_unreadable_row_is_404() -> None:
    alice = _user("alice@example.com")
    bob = _user("bob@example.com")
    with current_user(bob):
        theirs = Price.objects.create(amount=decimal.Decimal("1.00"))
    assert _history(OwnPriceViewSet, alice, theirs.pk).status_code == 404
    with current_user(alice):
        mine = Price.objects.create(amount=decimal.Decimal("2.00"))
    assert _history(OwnPriceViewSet, alice, mine.pk).status_code == 200


def test_an_unaudited_resource_has_no_history() -> None:
    user = _user("user@example.com")
    venue = Venue.objects.create(name="Arena", city="Berlin")
    response = _history(PlainVenueViewSet, user, venue.pk)
    assert response.status_code == 404
    assert "class Karni: audit = True" in str(response.data["detail"])


def test_the_schema_documents_history_only_for_audited_models() -> None:
    paths = SchemaGenerator(patterns=router().urls).get_schema(request=None, public=True)["paths"]
    assert "/prices/{id}/history/" in paths
    assert "/plain-venues/{id}/history/" not in paths
    operation = paths["/prices/{id}/history/"]["get"]
    assert operation["x-karni-access"] == {"authenticated": True}
    body = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert "PaginatedChangeLogList" in body["$ref"]
