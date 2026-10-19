"""The admin History tab of an audited model shows field changes, visibility applied."""

from __future__ import annotations

import decimal
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.middleware import current_user
from tests.testapp.models import Price, Venue

pytestmark = pytest.mark.django_db


def _staff(email: str, *roles: str, superuser: bool = False) -> Any:
    model = get_user_model()
    if superuser:
        return model.objects.create_superuser(email=email, password="a-strong-password-123")
    user = model.objects.create_user(email=email, password="a-strong-password-123", is_staff=True)
    for role in roles:
        assign_role(user, role)
    user.user_permissions.add(
        *Permission.objects.filter(content_type=ContentType.objects.get_for_model(Price))
    )
    return user


def test_the_history_tab_shows_field_changes() -> None:
    if Price not in admin.site._registry:
        pytest.skip("Price is not registered on the default admin site")
    root = _staff("root@example.com", superuser=True)
    with current_user(root):
        price = Price.objects.create(amount=decimal.Decimal("10.00"), currency="EUR", note="vip")
        price.amount = decimal.Decimal("12.00")
        price.save()
    client = Client()
    client.force_login(root)
    page = client.get(reverse("admin:testapp_price_history", args=[price.pk]))
    assert page.status_code == 200
    body = page.content.decode()
    assert "Field changes" in body
    assert "10.00" in body and "12.00" in body and "EUR" in body
    assert "vip" not in body and "[redacted]" in body
    assert "root@example.com" in body


def test_the_history_tab_hides_fields_the_user_cannot_see() -> None:
    if Price not in admin.site._registry:
        pytest.skip("Price is not registered on the default admin site")
    member = _staff("member@example.com", "user")  # amount is staff-only (field_roles)
    with current_user(member):
        price = Price.objects.create(amount=decimal.Decimal("10.00"), currency="EUR")
    client = Client()
    client.force_login(member)
    page = client.get(reverse("admin:testapp_price_history", args=[price.pk]))
    assert page.status_code == 200
    # The page title carries str(price); the field-changes table is what must not leak.
    table = page.content.decode().split("Field changes", 1)[1].split("Admin actions", 1)[0]
    assert "EUR" in table and "10.00" not in table and "amount" not in table


def test_an_unaudited_model_keeps_djangos_history_page() -> None:
    if Venue not in admin.site._registry:
        pytest.skip("Venue is not registered on the default admin site")
    root = _staff("root@example.com", superuser=True)
    venue = Venue.objects.create(name="Arena", city="Berlin")
    client = Client()
    client.force_login(root)
    page = client.get(reverse("admin:testapp_venue_history", args=[venue.pk]))
    assert page.status_code == 200
    assert "Field changes" not in page.content.decode()
