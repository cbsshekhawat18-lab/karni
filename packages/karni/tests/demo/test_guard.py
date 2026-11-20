"""The write rule: only demo accounts write, and never to their own account."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from karni.accounts import terms
from karni.demo import guard
from tests.testapp.models import Venue

from .conftest import CUSTOMER, JSON, OUTSIDER, STAFF, bearer, make_outsider, token, user


def refused(answer: Any, code: str) -> bool:
    return answer.status_code == 403 and answer.json()["code"] == code


def add_venue(client: Client, **extra: Any) -> Any:
    return client.post("/api/venues/", {"name": "Hall", "city": "Oslo"}, content_type=JSON, **extra)


@pytest.mark.django_db
def test_anonymous_callers_read_and_never_write(seeded: dt.datetime) -> None:
    client = Client()

    assert client.get("/api/venues/").json()["count"] == 3
    answer = add_venue(client)
    assert refused(answer, "demo_read_only")
    assert STAFF in answer.json()["detail"] and "1 more demo accounts" in answer.json()["detail"]
    assert Venue.objects.count() == 3


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path, body",
    [
        ("/api/auth/register/", {"email": "new@example.com", "password": "a-long-password-1"}),
        ("/api/auth/otp/send/", {"email": "new@example.com"}),
        ("/api/auth/password/reset/", {"email": STAFF}),
    ],
)
def test_sign_up_codes_and_resets_are_closed(
    seeded: dt.datetime, path: str, body: dict[str, str]
) -> None:
    assert refused(Client().post(path, body, content_type=JSON), "demo_read_only")


@pytest.mark.django_db
def test_sign_in_refresh_and_sign_out_stay_open(seeded: dt.datetime) -> None:
    client = Client()
    signed_in = client.post(
        "/api/auth/login/", {"email": STAFF, "password": "karni-password"}, content_type=JSON
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


@pytest.mark.django_db
def test_accepting_the_terms_stays_open(seeded: dt.datetime, demo: Any) -> None:
    from types import ModuleType

    from django.urls import include, path

    from karni.accounts.urls import build_urlpatterns

    demo.KARNI_TERMS = {"version": "2026-02", "url": "/terms/"}
    module = ModuleType("demo_terms_urls")  # the terms routes exist while KARNI_TERMS is set
    module.__dict__["urlpatterns"] = [
        path("api/auth/", include(build_urlpatterns())),
        path("api/", include("karni.api.urls")),
    ]
    demo.ROOT_URLCONF = module
    other = make_outsider()
    other.set_password("karni-password")
    other.save()
    client = Client()
    access = token(client, OUTSIDER, "karni-password")

    answer = client.post(
        "/api/auth/terms/accept/", {"version": "2026-02"}, content_type=JSON, **bearer(access)
    )

    assert answer.status_code in (200, 201)
    assert terms.has_accepted(other.pk, "2026-02")


@pytest.mark.django_db
def test_an_account_that_is_not_a_demo_account_never_writes(seeded: dt.datetime) -> None:
    outsider = make_outsider()
    client = Client()
    client.force_login(outsider)

    assert client.get(reverse("admin:testapp_venue_changelist")).status_code == 200
    answer = client.post(reverse("admin:testapp_venue_add"), {"name": "No", "city": "No"})
    assert answer.status_code == 403 and b"Read-only demo" in answer.content
    other = Client()
    other.force_login(outsider)
    assert refused(add_venue(other), "demo_read_only")
    assert (
        not Venue.objects.filter(name="Hall").exists()
        and not Venue.objects.filter(name="No").exists()
    )


@pytest.mark.django_db
@pytest.mark.parametrize("login", [STAFF, CUSTOMER])
def test_each_demo_account_writes(seeded: dt.datetime, login: str) -> None:
    client = Client()
    access = token(client, login)

    answer = add_venue(client, **bearer(access))

    assert answer.status_code == 201, answer.content
    assert Venue.objects.filter(name="Hall").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("login", [STAFF, CUSTOMER])
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
def test_no_demo_account_changes_its_account_or_roles(
    seeded: dt.datetime, login: str, method: str, path: str, body: dict[str, Any]
) -> None:
    client = Client()
    access = token(client, login)

    answer = getattr(client, method)(path, body, content_type=JSON, **bearer(access))

    assert refused(answer, "demo_account_locked")
    assert token(Client(), login)  # the next visitor still signs in


@pytest.mark.django_db
def test_the_admin_blocks_changes_to_a_demo_account(seeded: dt.datetime) -> None:
    for login in (STAFF, CUSTOMER):
        account = user(login)
        client = Client()
        client.force_login(user(STAFF))
        paths = (
            (
                reverse("admin:karni_accounts_user_change", args=[account.pk]),
                {"email": "mine@example.com"},
            ),
            (reverse("admin:karni_accounts_user_delete", args=[account.pk]), {"post": "yes"}),
            (reverse("admin:password_change"), {"old_password": "karni-password"}),
            (reverse("admin:auth_group_changelist"), {"action": "delete_selected"}),
        )
        for path, body in paths:
            answer = client.post(path, body)
            assert answer.status_code == 403, path
            assert b"Read-only demo" in answer.content
        account = user(login)
        assert account.check_password("karni-password")


@pytest.mark.django_db
def test_a_demo_account_changes_data_in_the_admin(seeded: dt.datetime) -> None:
    client = Client()
    client.force_login(user(STAFF))

    answer = client.post(reverse("admin:testapp_venue_add"), {"name": "Admin hall", "city": "Rome"})

    assert answer.status_code == 302, answer.content[:300]
    assert Venue.objects.filter(name="Admin hall").exists()


@pytest.mark.django_db
def test_admin_sign_in_stays_open(seeded: dt.datetime) -> None:
    answer = Client().post(
        reverse("admin:login"), {"username": STAFF, "password": "karni-password", "next": "/admin/"}
    )
    assert answer.status_code == 302


@pytest.mark.django_db
def test_open_and_locked_paths_are_settings(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_OPEN_PATHS = ["/api/venues/*"]
    demo.KARNI_DEMO_LOCKED_PATHS = ["/api/tags/*"]
    answer = add_venue(Client())  # anonymous: no longer the demo's 403, the API's own 401
    assert answer.status_code == 401 and answer.json().get("code") != "demo_read_only"

    demo.KARNI_DEMO_OPEN_PATHS = []
    client = Client()
    access = token(client, STAFF)
    answer = client.post("/api/tags/", {"name": "x"}, content_type=JSON, **bearer(access))
    assert refused(answer, "demo_account_locked")


def refuse_everything(request: Any) -> guard.Refusal | None:
    return guard.Refusal("custom", "No.") if request.method == "DELETE" else None


@pytest.mark.django_db
def test_the_write_rule_can_be_replaced(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_WRITE_RULE = "tests.demo.test_guard.refuse_everything"
    client = Client()

    assert add_venue(client).status_code in (201, 401, 403) and not refused(
        add_venue(client), "demo_read_only"
    )
    answer = client.delete("/api/venues/1/")
    assert answer.status_code == 403 and answer.json()["code"] == "custom"


@pytest.mark.django_db
def test_a_write_rule_that_cannot_be_imported_raises_e952(seeded: dt.datetime, demo: Any) -> None:
    from karni.exceptions import KarniImportError

    demo.KARNI_DEMO_WRITE_RULE = "tests.demo.nothing.rule"
    from django.test import RequestFactory

    request = RequestFactory().post("/api/venues/", {}, content_type=JSON)
    with pytest.raises(KarniImportError) as caught:
        guard.check_request(request)
    assert caught.value.code == "E952"


@pytest.mark.django_db
def test_without_demo_mode_the_project_rules_alone_apply(seeded: dt.datetime, demo: Any) -> None:
    demo.KARNI_DEMO_MODE = False
    answer = add_venue(Client())
    assert answer.status_code in (401, 403)
    assert answer.json().get("code") != "demo_read_only"
