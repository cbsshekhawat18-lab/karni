"""The write rule: only the demo account writes, and never to its own account."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from karni.accounts import terms
from shop.models import Category, Product

from demo import account

from .conftest import CUSTOMER, bearer, demo_user, token

JSON = "application/json"


def refused(answer: Any, code: str) -> bool:
    return answer.status_code == 403 and answer.json()["code"] == code


# anonymous


@pytest.mark.django_db
def test_anonymous_callers_read_and_never_write(seeded: dt.datetime) -> None:
    client = Client()

    assert client.get("/api/products/").json()["count"] == 40
    answer = client.post("/api/categories/", {"name": "Spam"}, content_type=JSON)
    assert refused(answer, "demo_read_only")
    assert "demo@example.com" in answer.json()["detail"]
    assert Category.objects.count() == 5


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/auth/register/", {"email": "new@example.com", "password": "a-long-password-1"}),
        ("/api/auth/otp/send/", {"email": "new@example.com"}),
        ("/api/auth/password/reset/", {"email": "demo@example.com"}),
        ("/payments/webhook/test/", {"id": "evt_1", "type": "payment.succeeded"}),
    ],
)
def test_sign_up_codes_resets_and_webhooks_are_closed(
    seeded: dt.datetime, path: str, body: dict[str, str]
) -> None:
    assert refused(Client().post(path, body, content_type=JSON), "demo_read_only")


@pytest.mark.django_db
def test_sign_in_refresh_and_sign_out_stay_open(seeded: dt.datetime) -> None:
    client = Client()
    signed_in = client.post(
        "/api/auth/login/",
        {"email": account.email(), "password": account.password()},
        content_type=JSON,
    )
    assert signed_in.status_code == 200
    tokens = signed_in.json()

    refreshed = client.post("/api/auth/refresh/", {"refresh": tokens["refresh"]}, content_type=JSON)
    assert refreshed.status_code == 200 and refreshed.json()["access"]

    rotated = refreshed.json().get("refresh", tokens["refresh"])
    signed_out = client.post(
        "/api/auth/logout/",
        {"refresh": rotated},
        content_type=JSON,
        **bearer(refreshed.json()["access"]),
    )
    assert signed_out.status_code < 400


# another account


@pytest.mark.django_db
def test_another_account_signs_in_and_reads_but_never_writes(seeded: dt.datetime) -> None:
    client = Client()
    access = token(client, CUSTOMER)
    current = terms.config()
    assert current is not None
    accepted = client.post(
        "/api/auth/terms/accept/", {"version": current.version}, content_type=JSON, **bearer(access)
    )
    assert accepted.status_code in (200, 201)

    assert client.get("/api/orders/", **bearer(access)).status_code == 200
    answer = client.post("/api/carts/", {}, content_type=JSON, **bearer(access))
    assert refused(answer, "demo_read_only")
    renamed = client.patch(
        f"/api/products/{Product.objects.first().pk}/",
        {"name": "Mine now"},
        content_type=JSON,
        **bearer(access),
    )
    assert refused(renamed, "demo_read_only")


# the demo account


@pytest.mark.django_db
def test_the_demo_account_writes(seeded: dt.datetime) -> None:
    client = Client()
    access = token(client, account.email())
    product = Product.objects.order_by("pk").first()

    created = client.post(
        "/api/categories/", {"name": "Made in the demo"}, content_type=JSON, **bearer(access)
    )
    changed = client.patch(
        f"/api/products/{product.pk}/", {"name": "Renamed"}, content_type=JSON, **bearer(access)
    )

    assert created.status_code == 201
    assert changed.status_code == 200
    assert Product.objects.get(pk=product.pk).name == "Renamed"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method, path, body",
    [
        (
            "post",
            "/api/auth/password/change/",
            {"old_password": "karni-password", "new_password": "a-new-password-1"},
        ),
        ("post", "/api/auth/email/change/", {"email": "mine@example.com"}),
        ("patch", "/api/auth/me/", {"email": "mine@example.com", "first_name": "Me"}),
        ("post", "/api/auth/permissions/matrix/", {"changes": []}),
    ],
)
def test_the_demo_account_cannot_change_its_account_or_roles(
    seeded: dt.datetime, method: str, path: str, body: dict[str, Any]
) -> None:
    client = Client()
    access = token(client, account.email())

    answer = getattr(client, method)(path, body, content_type=JSON, **bearer(access))

    assert refused(answer, "demo_account_locked")
    assert token(Client(), account.email())  # the next visitor still signs in


# the admin


@pytest.mark.django_db
def test_the_admin_blocks_changes_to_the_demo_account(seeded: dt.datetime) -> None:
    client = Client()
    demo = demo_user()
    client.force_login(demo)
    pk = demo.pk

    change = reverse("admin:karni_accounts_user_change", args=[pk])
    delete = reverse("admin:karni_accounts_user_delete", args=[pk])
    password = reverse("admin:auth_user_password_change", args=[pk])
    for path, body in (
        (change, {"email": "mine@example.com", "is_superuser": ""}),
        (delete, {"post": "yes"}),
        (password, {"password1": "a-new-password-1", "password2": "a-new-password-1"}),
        (reverse("admin:password_change"), {"old_password": "karni-password"}),
        (reverse("admin:auth_group_changelist"), {"action": "delete_selected"}),
    ):
        answer = client.post(path, body)
        assert answer.status_code == 403, path
        assert b"Read-only demo" in answer.content

    demo = demo_user()
    assert demo.pk == pk and demo.is_superuser and demo.check_password("karni-password")


@pytest.mark.django_db
def test_the_demo_account_changes_shop_data_in_the_admin(seeded: dt.datetime) -> None:
    client = Client()
    client.force_login(demo_user())

    answer = client.post(
        reverse("admin:shop_category_add"), {"name": "From the admin", "slug": "from-the-admin"}
    )

    assert answer.status_code == 302, answer.content[:500]
    assert Category.objects.filter(name="From the admin").exists()


@pytest.mark.django_db
def test_another_staff_account_is_read_only_in_the_admin(seeded: dt.datetime) -> None:
    from django.contrib.auth import get_user_model

    staff = get_user_model().objects.create_user(
        email="staff@example.com", password="a-long-password-1", is_staff=True, is_superuser=True
    )
    client = Client()
    client.force_login(staff)

    assert client.get(reverse("admin:shop_category_changelist")).status_code == 200
    answer = client.post(reverse("admin:shop_category_add"), {"name": "Nope", "slug": "nope"})
    assert answer.status_code == 403
    assert not Category.objects.filter(name="Nope").exists()


@pytest.mark.django_db
def test_admin_sign_in_stays_open(seeded: dt.datetime) -> None:
    answer = Client().post(
        reverse("admin:login"),
        {"username": account.email(), "password": account.password(), "next": "/admin/"},
    )
    assert answer.status_code == 302


# demo mode off


@pytest.mark.django_db
def test_without_demo_mode_the_shop_rules_alone_apply(seeded: dt.datetime, demo: Any) -> None:
    demo.DEMO_MODE = False
    answer = Client().post("/api/categories/", {"name": "Spam"}, content_type=JSON)
    assert answer.status_code in (401, 403)
    assert "code" not in answer.json() or answer.json()["code"] != "demo_read_only"
