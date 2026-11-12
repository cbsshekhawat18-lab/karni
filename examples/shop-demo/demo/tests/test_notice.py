"""The sign-in pages show the demo login, and the React app is served at /."""

from __future__ import annotations

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
    demo.DEMO_APP_INDEX = str(index)
    return index


@pytest.mark.django_db
def test_the_sign_in_page_carries_the_demo_login(built: Path) -> None:
    page = Client().get("/").content.decode()

    assert '<meta name="demo-login-email" content="demo@example.com">' in page
    assert '<meta name="demo-login-password" content="karni-password">' in page
    assert '<meta name="demo-reset-hours" content="24">' in page
    assert '<meta name="demo-admin-url" content="/admin/">' in page
    assert page.index("demo-login-email") < page.index("</head>")


@pytest.mark.django_db
def test_without_demo_mode_the_page_carries_no_login(built: Path, demo: Any) -> None:
    demo.DEMO_MODE = False
    page = Client().get("/").content.decode()
    assert "demo-login" not in page
    assert "karni-password" not in page


@pytest.mark.django_db
def test_the_admin_sign_in_page_shows_the_demo_login(demo: Any) -> None:
    page = Client().get("/admin/login/").content.decode()
    assert "data-demo-login" in page
    assert "demo@example.com" in page and "karni-password" in page

    demo.DEMO_MODE = False
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
def test_an_unbuilt_app_says_how_to_build_it(demo: Any, tmp_path: Path) -> None:
    demo.DEMO_APP_INDEX = str(tmp_path / "missing" / "index.html")
    answer = Client().get("/")
    assert answer.status_code == 503
    assert b"npm run build" in answer.content
