"""@pages: a view behind a capture declares its known addresses, and they join sitemap.xml,
karni check --seo and the page test."""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.test import Client
from karni.exceptions import KarniImproperlyConfigured
from karni.testing import assert_pages

from karni_site import checks_seo
from karni_site.sitemaps import declared_pages, pages

pytestmark = pytest.mark.django_db

DECLARED = ["/topics/tides/", "/topics/harbours/", "/seasons/winter/"]


@pytest.fixture(autouse=True)
def _site(settings: Any) -> None:
    settings.ROOT_URLCONF = "tests.topics_urls"


def listed() -> list[str]:
    response = Client().get("/sitemap.xml")
    assert response.status_code == 200
    return re.findall(r"<loc>http://testserver([^<]+)</loc>", response.content.decode())


def test_the_declared_pages_join_the_sitemap() -> None:
    assert declared_pages() == DECLARED
    assert listed() == ["/", *DECLARED]


def test_check_seo_finds_no_page_left_out() -> None:
    crawl = checks_seo.SeoCrawl()
    assert crawl.run() == []
    assert set(DECLARED) <= set(crawl.pages)


def test_the_page_test_takes_them(client: Client) -> None:
    assert_pages(client, ["/", *declared_pages()])


def test_an_excluded_page_stays_out_of_the_sitemap_only(settings: Any) -> None:
    settings.KARNI_SITE_SITEMAP_EXCLUDE = ["topics:season"]
    assert listed() == ["/", "/topics/tides/", "/topics/harbours/"]
    assert declared_pages() == DECLARED


def test_a_declaration_that_is_not_an_address_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests import topics_urls

    monkeypatch.setattr(topics_urls.topic, "karni_site_pages", ({"name": "tides"},))
    with pytest.raises(KarniImproperlyConfigured, match="SITE019") as failed:
        declared_pages()
    assert "topics:topic" in str(failed.value)


def test_pages_keeps_the_view_as_it_is() -> None:
    def view(request: Any) -> str:
        return "ok"

    assert pages({"slug": "a"})(view) is view
    assert view(None) == "ok"
