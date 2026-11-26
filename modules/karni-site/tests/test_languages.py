"""A site in two languages under i18n_patterns (tests/i18n_urls.py): menus per language, a
sitemap of every language's addresses, and SEO checks that compare within one language.

A one-language site behaves as before: test_menus.py, test_sitemaps.py and
test_checks_seo.py run unchanged.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template
from django.test import Client, RequestFactory
from django.urls import resolve
from django.utils import translation
from pytest_django import Settings

from karni_site import caching, checks_seo, languages
from karni_site.models import Menu, MenuItem, PageSeo
from karni_site.sitemaps import PagesSitemap, model_sitemaps
from tests.i18n_helpers import two_languages  # noqa: F401
from tests.testapp.models import Service

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("two_languages")]

LOOP = (
    "{% load karni_site %}{% get_menu name as items %}"
    "{% for item in items %}[{{ item.title }}|{{ item.url }}"
    "{% if item.current %}|current{% endif %}{% if item.active %}|active{% endif %}"
    "{% for child in item.children %}({{ child.title }}|{{ child.url }}"
    "{% if child.current %}|current{% endif %}){% endfor %}]{% endfor %}"
)


def render(path: str, name: str) -> str:
    """The menu ``name`` on the page at ``path``, in the page's language."""
    with translation.override(translation.get_language_from_path(path)):
        request = RequestFactory().get(path)
        request.resolver_match = resolve(path)
        return Template(LOOP).render(Context({"request": request, "name": name}))


def nav(html: str) -> str:
    found = re.search(r"<nav>(.*?)</nav>", html, re.S)
    assert found is not None, html
    return found.group(1)


@pytest.fixture
def buoys() -> Service:
    return Service.objects.create(title="Buoys", slug="buoys")


def test_the_site_is_in_two_languages(settings: Settings) -> None:
    assert languages.in_addresses()
    assert languages.default_language() == "en"
    assert languages.language_of("/fr/about/") == "fr"
    assert languages.is_language_root("/fr/") and not languages.is_language_root("/fr/about/")
    settings.LANGUAGES = [("en", "English")]
    assert not languages.in_addresses() and languages.language_of("/fr/about/") == ""


def test_a_menu_is_built_and_marked_in_the_page_language(buoys: Service) -> None:
    menu = Menu.objects.create(name="footer")
    MenuItem.objects.create(menu=menu, title="Home", route="website:home", order=0)
    MenuItem.objects.create(
        menu=menu,
        content_type=ContentType.objects.get_for_model(Service),
        object_id=str(buoys.pk),
        order=1,
    )
    about = MenuItem.objects.create(menu=menu, title="About", route="website:about", order=2)
    about.children_from = ContentType.objects.get_for_model(Service)
    about.save()
    # The French page asks first: the English one still gets its own links and marks.
    assert render("/fr/services/buoys/", "footer") == (
        "[Home|/fr/][Buoys|/fr/services/buoys/|current|active]"
        "[About|/fr/about/|active(Buoys|/fr/services/buoys/|current)]"
    )
    assert render("/en/services/buoys/", "footer") == (
        "[Home|/en/][Buoys|/en/services/buoys/|current|active]"
        "[About|/en/about/|active(Buoys|/en/services/buoys/|current)]"
    )
    # A language's home page is home: it stands for no section of the site.
    assert render("/fr/about/", "footer").startswith("[Home|/fr/][")


def test_a_seeded_menu_follows_its_seed_in_the_default_language_only(buoys: Service) -> None:
    client = Client()
    french = nav(client.get("/fr/about/").content.decode())
    assert french == (
        "[Home|/fr/][About us|/fr/about/|current|active(Buoys|/fr/services/buoys/)]"
        "[Contact|/fr/contact/]"
    )
    menu = Menu.objects.get(name="main")
    titles = list(menu.items.order_by("order").values_list("title", flat=True))
    assert titles == ["Home", "About us", "Contact"]  # the default language's seed
    version, digest = caching.version("menus"), menu.seeded["digest"]
    english = nav(client.get("/en/about/").content.decode())
    assert english == (
        "[Home|/en/][About us|/en/about/|current|active(Buoys|/en/services/buoys/)]"
        "[Contact|/en/contact/]"
    )
    for path in ("/fr/", "/en/", "/fr/contact/"):
        client.get(path)
    menu.refresh_from_db()
    # No visitor of another language makes the menu follow its seed again.
    assert (caching.version("menus"), menu.seeded["digest"]) == (version, digest)
    assert list(menu.items.order_by("order").values_list("title", flat=True)) == titles


def locations(client: Client) -> list[str]:
    body = client.get("/sitemap.xml").content.decode()
    return [loc.removeprefix("http://testserver") for loc in re.findall(r"<loc>(.*?)</loc>", body)]


def test_the_sitemap_lists_every_language(buoys: Service, settings: Settings) -> None:
    client = Client()
    assert locations(client) == [
        "/en/",
        "/fr/",
        "/en/about/",
        "/fr/about/",
        "/en/contact/",
        "/fr/contact/",
        "/en/services/buoys/",
        "/fr/services/buoys/",
    ]
    # Hidden by path, or excluded by path, in one language: the other keeps its address.
    PageSeo.objects.create(path="/fr/about/", noindex=True)
    PageSeo.objects.create(path="/en/services/buoys/", noindex=True)
    settings.KARNI_SITE_SITEMAP_EXCLUDE = ["/fr/contact/"]
    assert locations(client) == [
        "/en/",
        "/fr/",
        "/en/about/",
        "/en/contact/",
        "/fr/services/buoys/",
    ]
    # By URL name: every language.
    PageSeo.objects.create(route="website:home", noindex=True)
    assert "/en/" not in locations(client) and "/fr/" not in locations(client)


def test_an_address_that_does_not_change_with_the_language_is_listed_once(
    monkeypatch: pytest.MonkeyPatch, buoys: Service
) -> None:
    monkeypatch.setattr(Service, "get_absolute_url", lambda self: f"/buoys/{self.slug}/")
    section = model_sitemaps([Service])["testapp-service"]
    urls = section.get_urls(site=type("S", (), {"domain": "testserver"})(), protocol="http")
    assert [url["location"] for url in urls] == ["http://testserver/buoys/buoys/"]


def test_the_seo_check_passes_a_site_in_two_languages(buoys: Service) -> None:
    # "Contact", and each service's title and description, are the same in both languages.
    crawl = checks_seo.SeoCrawl()
    assert crawl.run() == []
    assert {"/en/contact/", "/fr/contact/", "/fr/services/buoys/"} <= set(crawl.pages)


def test_titles_and_descriptions_are_compared_within_one_language(buoys: Service) -> None:
    PageSeo.objects.create(route="website:about", title="Our tides")
    PageSeo.objects.create(route="website:contact", title="Our tides")
    failures = checks_seo.SeoCrawl().run()
    assert sorted(f for f in failures if f.startswith("SITE011")) == [
        "SITE011: 2 pages share the title 'Our tides': /en/about/, /en/contact/. "
        "Give each page its own title.",
        "SITE011: 2 pages share the title 'Our tides': /fr/about/, /fr/contact/. "
        "Give each page its own title.",
    ]


class _OneLanguage(PagesSitemap):
    i18n = False


def one_language_sitemaps() -> dict[str, Any]:
    """A section list of a project's own that lists one language only."""
    return {"pages": _OneLanguage(), **model_sitemaps()}


def test_a_page_left_out_of_the_sitemap_gets_the_advice_that_fits(
    settings: Settings, buoys: Service
) -> None:
    settings.KARNI_SITE_SITEMAPS = "tests.test_languages.one_language_sitemaps"
    failures = [f for f in checks_seo.SeoCrawl().run() if f.startswith("SITE018")]
    assert failures and all("/fr/" in failure.split(" is a page")[0] for failure in failures)
    about = next(f for f in failures if f.startswith("SITE018: /fr/about/"))
    assert "Its address in the default language, /en/about/, is listed" in about
    assert "needs i18n = True" in about
    assert "get_absolute_url" not in about.split("needs i18n")[0]
