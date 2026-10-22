"""The admin honours ``Karni.field_roles``: a hidden field is absent from every admin surface."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, RequestFactory
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.admin.base import build_model_admin
from tests.testapp.models import Customer


pytestmark = pytest.mark.django_db


def _visible(response: Any) -> str:
    """The page without its random tokens (CSRF, nonces), which can contain "vip" or "9000"."""
    return re.sub(r"[A-Za-z0-9]{32,}", "", response.content.decode())


def _staff(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(
        email=email, password="a-strong-password-123", is_staff=True
    )
    for role in roles:
        assign_role(user, role)
    user.user_permissions.add(
        *Permission.objects.filter(content_type=ContentType.objects.get_for_model(Customer))
    )
    return user


def _request(user: Any) -> Any:
    request = RequestFactory().get("/")
    request.user = user
    return request


def _admin() -> Any:
    return build_model_admin(Customer)(Customer, AdminSite())


def test_a_hidden_field_is_absent_from_every_admin_surface() -> None:
    member = _staff("member@example.com", "user")  # phone: read; note, salary: hidden
    model_admin = _admin()
    request = _request(member)
    assert "salary" not in model_admin.get_list_display(request)
    assert "phone" in model_admin.get_list_display(request)
    assert "internal_note" not in model_admin.get_search_fields(request)
    assert "name" in model_admin.get_search_fields(request)
    assert not {"salary", "internal_note"} & set(model_admin.get_sortable_by(request))
    assert not {"salary", "internal_note"} & set(model_admin.get_fields(request))
    assert "phone" in model_admin.get_fields(request)
    for _title, options in model_admin.get_fieldsets(request):
        assert not {"salary", "internal_note"} & set(options["fields"])
    assert "phone" in model_admin.get_readonly_fields(request)  # readable, not writable
    assert model_admin.lookup_allowed("salary__gte", "1", request) is False
    assert model_admin.lookup_allowed("name", "x", request) is True


def test_a_role_that_may_see_everything_keeps_every_surface() -> None:
    staff = _staff("staff@example.com", "staff")
    model_admin = _admin()
    request = _request(staff)
    assert {"salary", "phone"} <= set(model_admin.get_list_display(request))
    assert "internal_note" in model_admin.get_search_fields(request)
    assert "phone" not in model_admin.get_readonly_fields(request)
    assert model_admin.lookup_allowed("salary__gte", "1", request) is True


def test_through_the_admin_site() -> None:
    if Customer not in admin.site._registry:
        pytest.skip("Customer is not registered on the default admin site")
    member = _staff("member@example.com", "user")
    customer = Customer.objects.create(  # created by the member: inside their `own` row scope
        name="Ada",
        phone="+1 555 0100",
        internal_note="vip",
        salary=Decimal("9000.00"),
        created_by=member,
    )
    client = Client()
    client.force_login(member)
    changelist = reverse("admin:testapp_customer_changelist")
    page = _visible(client.get(changelist))

    def around(token: str) -> str:
        index = page.find(token)
        return page[max(0, index - 300) : index + 80] if index >= 0 else ""

    assert "9000" not in page, around("9000")
    assert "vip" not in page, around("vip")
    assert "+1 555 0100" in page
    assert client.get(changelist, {"salary__gte": "1"}).status_code == 400  # disallowed lookup
    searched = client.get(changelist, {"q": "vip"})  # the hidden note is not searched
    assert searched.context_data["cl"].queryset.count() == 0
    assert client.get(changelist, {"q": "Ada"}).context_data["cl"].queryset.count() == 1
    change = client.get(reverse("admin:testapp_customer_change", args=[customer.pk]))
    assert change.status_code == 200
    body = _visible(change)
    assert "9000" not in body and "vip" not in body
    assert 'name="phone"' not in body and "+1 555 0100" in body  # read-only, still shown
