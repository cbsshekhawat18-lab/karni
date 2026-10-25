"""The error pages: the site's own, with the request, and a fallback that cannot fail."""

from __future__ import annotations

import pytest
from django.test import Client, RequestFactory
from pytest_django import Settings

from karni_site import views

pytestmark = pytest.mark.django_db


@pytest.fixture
def production(settings: Settings) -> Settings:
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver"]
    return settings


def test_not_found_renders_the_sites_page_with_the_request(production: Settings) -> None:
    response = Client().get("/no-such-page/")
    assert response.status_code == 404
    page = response.content.decode()
    assert "<h1>Not here: /no-such-page/</h1>" in page
    assert "<title>Not here</title>" in page
    # The layout's tags ran with the request: its inline script is allowed.
    assert "'sha256-" in response.headers["Content-Security-Policy"]


def test_server_error_renders_the_sites_page_with_the_request(production: Settings) -> None:
    client = Client(raise_request_exception=False)
    response = client.get("/boom/")
    assert response.status_code == 500
    assert "<h1>Sorry</h1>" in response.content.decode()
    assert "'sha256-" in response.headers["Content-Security-Policy"]


def test_a_page_that_fails_to_render_falls_back(
    production: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    production.KARNI_SITE_SERVER_ERROR_TEMPLATES = ["missing.html", "website/broken.html"]
    response = Client(raise_request_exception=False).get("/boom/")
    assert response.status_code == 500
    assert response.content.decode() == views.PLAIN_500
    production.KARNI_SITE_SERVER_ERROR_TEMPLATES = ["500.html", "karni_site/500.html"]


def test_the_modules_own_pages_need_nothing(rf: RequestFactory) -> None:
    request = rf.get("/x/")
    response = views.server_error(request, template_name="karni_site/500.html")
    assert response.status_code == 500 and "Something went wrong" in response.content.decode()
    response = views.page_not_found(request, Exception("gone"), "karni_site/404.html")
    assert response.status_code == 404 and "Page not found" in response.content.decode()


def test_a_raising_template_is_logged_and_skipped(
    rf: RequestFactory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class Boom:
        @property
        def boom(self) -> str:
            raise RuntimeError("the database is down")

    request = rf.get("/x/")
    content = views.render_first(request, ["500.html", "karni_site/500.html"], {"fail": Boom()})
    assert content is not None and "Something went wrong" in content
    assert "500.html failed to render" in caplog.text
