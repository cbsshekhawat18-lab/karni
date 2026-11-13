"""What a demo exposes: GET /api/demo/, the React app at /, the admin sign-in notice."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from django.test import Client

from karni.demo import urls

from .conftest import CUSTOMER, STAFF

INDEX = (
    "<!doctype html><html><head><title>Demo</title>"
    '<script type="module" src="/assets/index-abcdefgh.js"></script></head>'
    '<body><div id="root"></div></body></html>'
)


@pytest.fixture
def built(demo: Any, tmp_path: Path) -> Path:
    """A built index.html, as frontend/dist holds one after npm run build."""
    index = tmp_path / "index.html"
    index.write_text(INDEX)
    demo.KARNI_DEMO_APP_INDEX = str(index)
    return index


@pytest.mark.django_db
def test_the_info_route_lists_every_account_with_what_it_can_do(seeded: dt.datetime) -> None:
    body = Client().get("/api/demo/").json()

    assert body["enabled"] is True and body["reset_hours"] == 24 and body["admin_url"] == "/admin/"
    assert body["next_reset"] is not None
    first, second = body["accounts"]
    assert (first["login"], first["label"], first["can"], first["password"]) == (
        STAFF,
        "Staff",
        "Everything.",
        "karni-password",
    )
    assert second["login"] == CUSTOMER and second["roles"] == ["customer"]
    assert first["roles"], "roles 'all' lists the roles the API names"


@pytest.mark.django_db
def test_the_info_route_is_404_e954_outside_demo_mode(demo: Any) -> None:
    demo.KARNI_DEMO_MODE = False
    answer = Client().get("/api/demo/")
    assert answer.status_code == 404 and answer.json()["code"] == "E954"


@pytest.mark.django_db
def test_the_info_route_needs_no_sign_in_and_no_token(seeded: dt.datetime) -> None:
    assert Client(HTTP_AUTHORIZATION="Bearer garbage").get("/api/demo/").status_code == 200


@pytest.mark.django_db
def test_the_admin_sign_in_page_lists_the_accounts(seeded: dt.datetime, demo: Any) -> None:
    page = Client().get("/admin/login/").content.decode()
    assert "data-demo-login" in page
    for text in (STAFF, CUSTOMER, "Place orders.", "karni-password", "24 hours"):
        assert text in page

    demo.KARNI_DEMO_MODE = False
    assert "karni-password" not in Client().get("/admin/login/").content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", "/products", "/orders/0d5c7a9e/", "/carts/x"])
def test_every_page_of_the_app_answers_its_index(built: Path, path: str) -> None:
    answer = Client().get(path)
    assert answer.status_code == 200
    assert answer["Cache-Control"] == "no-cache"
    assert '<div id="root">' in answer.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/api/nothing-here/", "/assets/missing.js", "/static/missing.css"]
)
def test_django_paths_never_answer_the_app(built: Path, path: str) -> None:
    assert Client().get(path).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/admin", "/api"])
def test_a_django_path_without_its_slash_is_redirected_to_it(built: Path, path: str) -> None:
    answer = Client().get(path)
    assert answer.status_code == 301 and answer["Location"] == f"{path}/"


@pytest.mark.django_db
def test_an_unbuilt_app_says_how_to_build_it(demo: Any, tmp_path: Path) -> None:
    demo.KARNI_DEMO_APP_INDEX = str(tmp_path / "missing" / "index.html")
    answer = Client().get("/")
    assert answer.status_code == 503 and b"npm run build" in answer.content


def test_extra_reserved_segments_are_a_setting(settings: Any) -> None:
    settings.KARNI_DEMO_APP_RESERVED = ["payments", "/hooks/"]
    found = urls.reserved()
    assert "payments" in found and "hooks" in found and "api" in found
    assert len(found) == len(set(found))
