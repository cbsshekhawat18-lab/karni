"""sitemap.xml and robots.txt: what is listed, what is left out, and robots per environment."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone
from pytest_django import Settings

from karni_site import seo_views, sitemaps
from karni_site.models import PageSeo
from tests.seo_helpers import seo_site  # noqa: F401
from tests.testapp.models import Article, Note, Project, Service

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("seo_site")]


def listed(path: str = "/sitemap.xml") -> list[str]:
    response = Client().get(path)
    assert response.status_code == 200, response.content
    assert response["Content-Type"] == "application/xml"
    return re.findall(r"<loc>([^<]+)</loc>", response.content.decode())


def test_the_sitemap_lists_the_pages_and_the_public_rows() -> None:
    Project.objects.create(title="Wedding cake", slug="wedding")
    Project.objects.create(title="Draft", slug="draft", published=False)
    gone = Project.objects.create(title="Gone", slug="gone")
    gone.delete()  # soft-deleted: hidden by the default manager
    Note.objects.create(title="Private")  # class Karni: sitemap = False
    PageSeo.objects.create(path="/about/", noindex=True)
    found = listed()
    assert "http://testserver/" in found and "http://testserver/projects/" in found
    assert "http://testserver/projects/wedding/" in found
    for left_out in ("/about/", "/projects/draft/", "/projects/gone/", "/old-about/", "/bare/"):
        assert f"http://testserver{left_out}" not in found, left_out
    assert not any("/notes/" in url or "/robots.txt" in url or "/web/" in url for url in found)
    body = Client().get("/sitemap.xml").content.decode()
    assert f"<lastmod>{timezone.localdate():%Y-%m-%d}</lastmod>" in body


def test_status_and_publication_dates_decide_without_a_declaration() -> None:
    now = timezone.now()
    live = Article.objects.create(title="Live", status="published", published_at=now)
    Article.objects.create(title="Draft", status="draft", published_at=now)
    Article.objects.create(title="Later", status="published", published_at=now + timedelta(days=2))
    Article.objects.create(title="Undated", status="published")
    rows = list(sitemaps.public_rows(Article, {}))
    assert rows == [live]


def test_a_declaration_chooses_the_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    Service.objects.create(title="Web", slug="web", order=1)
    Service.objects.create(title="Print", slug="print", order=2)
    hidden = Service.objects.create(title="Old", slug="old", published=False)
    spec = {"filter": {"order__lte": 5}, "exclude": {"slug": "print"}, "priority": 0.8}
    assert [row.slug for row in sitemaps.public_rows(Service, spec)] == ["old", "web"]
    assert hidden in sitemaps.public_rows(Service, {"filter": {}})
    section = sitemaps.ModelSitemap(Service, spec)
    assert section.priority == 0.8 and section.lastmod(hidden) == hidden.updated_at


def test_a_wrong_declaration_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from karni.exceptions import KarniImproperlyConfigured

    monkeypatch.setattr(Note.Karni, "sitemap", {"filters": {}}, raising=False)
    with pytest.raises(KarniImproperlyConfigured, match="SITE019"):
        sitemaps.model_spec(Note)

    class Plain:
        class Karni:
            sitemap: dict[str, Any] = {"filter": {}}

    with pytest.raises(KarniImproperlyConfigured, match="no get_absolute_url"):
        sitemaps.model_spec(Plain)


def test_addresses_use_the_sites_own_address(settings: Settings) -> None:
    settings.KARNI_SITE_URL = "https://www.example.com/"
    Project.objects.create(title="Wedding cake", slug="wedding")
    found = listed()
    assert "https://www.example.com/" in found
    assert "https://www.example.com/projects/wedding/" in found


def test_a_large_section_turns_the_sitemap_into_an_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for slug in ("a", "b", "c"):
        Project.objects.create(title=slug, slug=slug)
    monkeypatch.setattr(sitemaps.ModelSitemap, "limit", 2)
    index = Client().get("/sitemap.xml").content.decode()
    assert "<sitemapindex" in index
    entries = re.findall(r"<loc>([^<]+)</loc>", index)
    assert "http://testserver/sitemap-testapp-project.xml" in entries
    assert "http://testserver/sitemap-testapp-project.xml?p=2" in entries
    assert listed("/sitemap-testapp-project.xml?p=2") == ["http://testserver/projects/c/"]
    assert Client().get("/sitemap-nothing.xml").status_code == 404


def test_the_sections_are_a_setting(settings: Settings) -> None:
    settings.KARNI_SITE_SITEMAPS = "tests.test_sitemaps.only_pages"
    Project.objects.create(title="Wedding cake", slug="wedding")
    assert "http://testserver/projects/wedding/" not in listed()


def only_pages() -> dict[str, Any]:
    return {"pages": sitemaps.PagesSitemap()}


# robots.txt


def robots() -> str:
    response = Client().get("/robots.txt")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    return response.content.decode()


def test_robots_closes_the_site_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DJANGO_ENV", raising=False)
    assert robots() == "User-agent: *\nDisallow: /\n"
    monkeypatch.setenv("DJANGO_ENV", "dev")
    assert not seo_views.indexing_allowed()


def test_robots_opens_the_site_in_production_and_names_the_sitemap(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setenv("DJANGO_ENV", "prod")
    assert robots() == "User-agent: *\nAllow: /\n\nSitemap: http://testserver/sitemap.xml\n"
    settings.KARNI_SITE_ROBOTS_DISALLOW = ["/search/", "/basket/"]
    settings.KARNI_SITE_URL = "https://www.example.com"
    assert robots() == (
        "User-agent: *\nDisallow: /search/\nDisallow: /basket/\n\n"
        "Sitemap: https://www.example.com/sitemap.xml\n"
    )


def test_the_setting_decides_in_every_environment(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setenv("DJANGO_ENV", "prod")
    settings.KARNI_SITE_ALLOW_INDEXING = False
    assert robots() == "User-agent: *\nDisallow: /\n"
    monkeypatch.setenv("DJANGO_ENV", "dev")
    settings.KARNI_SITE_ALLOW_INDEXING = True
    assert "Allow: /" in robots()


def test_a_row_hidden_in_the_admin_is_left_out() -> None:
    Project.objects.create(title="Wedding cake", slug="wedding")
    Project.objects.create(title="Market stall", slug="market")
    PageSeo.objects.create(path="/projects/wedding/", noindex=True)
    found = listed()
    assert "http://testserver/projects/market/" in found
    assert "http://testserver/projects/wedding/" not in found
    PageSeo.objects.create(route="seo:project", noindex=True)
    assert not any("/projects/m" in url for url in listed())


def test_the_sitemap_reads_each_section_once(django_assert_max_num_queries: Any) -> None:
    """One query for the admin's hidden pages, a count and a read per model: no repeats."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    for index in range(3):
        Project.objects.create(title=f"Project {index}", slug=f"p{index}")
    PageSeo.objects.create(path="/about/", noindex=True)
    listed()  # the first request stores what rendering stores
    with CaptureQueriesContext(connection) as queries:
        found = listed()
    assert "http://testserver/projects/p2/" in found
    statements = [query["sql"] for query in queries.captured_queries]
    hidden = [sql for sql in statements if "karni_site_pageseo" in sql and "noindex" in sql]
    assert len(hidden) == 1, hidden
    assert len(statements) == len(set(statements)), statements


def test_karni_technical_routes_are_not_pages(settings: Settings) -> None:
    from karni_site import routes

    settings.ROOT_URLCONF = "tests.technical_urls"
    names = [name for name, _ in routes.site_pages()]
    assert "home" in names and "pricing" in names and "status" in names
    for technical in ("readyz", "healthz", "karni-welcome"):
        assert not [n for n in names if technical in n], technical
    # A project extends the one list.
    settings.KARNI_SITE_TECHNICAL_ROUTES = ["status"]
    assert "status" not in [name for name, _ in routes.site_pages()]
