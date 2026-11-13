"""The sign-in pages list the demo accounts, and the React app is served at /."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from django.test import Client

INDEX = (
    "<!doctype html><html><head><title>Shop Demo</title>"
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
def test_the_sign_in_notice_lists_both_demo_accounts_with_what_they_can_do(
    seeded: dt.datetime,
) -> None:
    body = Client().get("/api/demo/").json()

    assert body["enabled"] is True and body["reset_hours"] == 24 and body["admin_url"] == "/admin/"
    staff, customer = body["accounts"]
    assert (staff["login"], staff["label"], staff["password"]) == (
        "demo@example.com",
        "Staff",
        "karni-password",
    )
    assert "admin" in staff["can"]
    assert (customer["login"], customer["label"], customer["roles"]) == (
        "customer@example.com",
        "Customer",
        ["customer"],
    )
    assert "cart" in customer["can"]


@pytest.mark.django_db
def test_without_demo_mode_there_is_no_notice_and_the_page_carries_no_login(
    built: Path, demo: Any
) -> None:
    demo.KARNI_DEMO_MODE = False
    assert Client().get("/api/demo/").status_code == 404
    page = Client().get("/").content.decode()
    assert "demo-login" not in page and "karni-password" not in page


@pytest.mark.django_db
def test_the_admin_sign_in_page_shows_both_demo_accounts(demo: Any) -> None:
    page = Client().get("/admin/login/").content.decode()
    assert "data-demo-login" in page
    assert "demo@example.com" in page and "customer@example.com" in page
    assert "karni-password" in page

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
    assert answer.status_code == 503
    assert b"npm run build" in answer.content
