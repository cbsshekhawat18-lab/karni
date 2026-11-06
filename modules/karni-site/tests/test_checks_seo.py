"""karni check --seo: every page rendered through the test client, each finding with its code."""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import include, path
from pytest_django import Settings

from karni_site import checks_seo
from karni_site.models import PageSeo
from tests import seo_urls
from tests.seo_helpers import jpeg, seo_site, upload  # noqa: F401
from tests.testapp.models import Project

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("seo_site")]


@pytest.fixture
def bare(monkeypatch: pytest.MonkeyPatch) -> Any:
    def fill(markup: str) -> None:
        monkeypatch.setattr(seo_urls, "BARE", markup)

    return fill


@pytest.fixture
def projects(django_capture_on_commit_callbacks: Any) -> list[Project]:
    with django_capture_on_commit_callbacks(execute=True):
        return [
            Project.objects.create(
                title="Wedding cake",
                slug="wedding",
                summary="Three tiers of sponge for a summer wedding.",
                photo=upload("cake.jpg", 2000, 1000),
            ),
            Project.objects.create(
                title="Market stall",
                slug="market",
                summary="Bread and buns for the Saturday market.",
                photo=upload("stall.jpg", 1600, 1200),
            ),
        ]


def codes(failures: list[str]) -> list[str]:
    return sorted({failure.split(":", 1)[0] for failure in failures})


def test_a_site_built_with_the_tags_passes(projects: list[Project]) -> None:
    crawl = checks_seo.SeoCrawl()
    assert crawl.run() == []
    assert {"/", "/about/", "/projects/", "/projects/wedding/", "/projects/market/"} <= set(
        crawl.pages
    )


def test_a_page_without_title_description_alt_or_size(bare: Any) -> None:
    default_storage.save("huge.jpg", ContentFile(jpeg(3000, 1500)))
    bare(
        "<!doctype html><html><head></head><body>"
        '<img src="/media/huge.jpg">'
        '<img src="/media/huge.jpg" width="400" height="200" alt="">'
        '<a href="/nowhere/">Lost</a> <a href="/old-about/">Moved</a>'
        "</body></html>"
    )
    failures = checks_seo.SeoCrawl().run()
    assert codes(failures) == ["SITE010", "SITE012", "SITE014", "SITE015", "SITE016", "SITE017"]
    by_code = {f.split(":", 1)[0]: [x for x in failures if x.startswith(f[:7])] for f in failures}
    assert by_code["SITE010"] == [
        "SITE010: /bare/ has no <title>. Give it {% block title %}, a row with a title, or an "
        "entry in the admin's Page titles and descriptions."
    ]
    assert by_code["SITE012"][0].startswith('SITE012: /bare/ has no <meta name="description">')
    assert by_code["SITE014"] == [
        "SITE014: /bare/: <img src='/media/huge.jpg'> (line 1) has no alt. Describe it in "
        'alt="...", or alt="" if it decorates.'
    ]
    assert len(by_code["SITE015"]) == 1
    weights = by_code["SITE016"]
    assert any("is 3000 pixels wide with no smaller copies (srcset)" in w for w in weights)
    assert any("is 3000 pixels wide, shown 400 wide" in w for w in weights)
    # A redirect to a page that answers is not broken.
    assert by_code["SITE017"] == ["SITE017: /bare/ links to /nowhere/, which answers 404."]


def test_shared_titles_and_descriptions(projects: list[Project]) -> None:
    for project in projects:
        project.title = "Our work"
        project.summary = "Everything we baked."
        project.save()
    failures = checks_seo.SeoCrawl().run()
    assert codes(failures) == ["SITE011", "SITE013"]
    assert failures[0] == (
        "SITE011: 2 pages share the title 'Our work | Crumb & Co': /projects/market/, "
        "/projects/wedding/. Give each page its own title."
    )


def test_the_generated_placeholder_description_asks_to_be_written(
    projects: list[Project],
) -> None:
    """Pages karni make site and karni make view write share it: one clear SITE012 each."""
    for project in projects:
        project.summary = checks_seo.PLACEHOLDER_DESCRIPTION
        project.save()
    failures = checks_seo.SeoCrawl().run()
    assert codes(failures) == ["SITE012"]  # not SITE013 "2 pages share the description"
    assert sorted(failures) == [
        f"SITE012: /projects/{slug}/ still has the placeholder description karni make site "
        "and karni make view write. Write one sentence about this page in its "
        "{% block description %}, its row's description, or the admin's Page titles and "
        "descriptions."
        for slug in ("market", "wedding")
    ]


def test_a_hidden_page_is_not_a_duplicate(projects: list[Project]) -> None:
    for project in projects:
        project.summary = "Everything we baked."
        project.save()
    PageSeo.objects.create(path="/projects/market/", noindex=True)
    assert checks_seo.SeoCrawl().run() == []


def test_a_large_image_without_copies(settings: Settings) -> None:
    settings.KARNI_SITE_QUEUE_RENDITIONS = False
    Project.objects.create(
        title="Late upload",
        slug="late",
        summary="A big photo.",
        photo=upload("late.jpg", 2400, 1200),
    )
    failures = checks_seo.SeoCrawl().run()
    assert codes(failures) == ["SITE016"]
    assert "/projects/: <img src='/media/projects/late.jpg'>" in failures[0]
    assert "2400 pixels wide, shown 400 wide" in failures[0]


def test_the_check_makes_the_copies_no_worker_made(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    # An upload whose copies were never made: its on_commit (the queue) never ran.
    late = Project.objects.create(
        title="Late upload",
        slug="late",
        summary="A big photo.",
        photo=upload("late.jpg", 2400, 1200),
    )
    from django.core.files.storage import default_storage

    from karni_site import renditions

    assert not default_storage.exists(renditions.manifest_name(late.photo.name))
    crawl = checks_seo.SeoCrawl()
    assert crawl.run() == []
    assert crawl.made == [late.photo.name]
    assert default_storage.exists(renditions.manifest_name(late.photo.name))
    # The hook says which it made and why.
    renditions.forget(late.photo.name)
    other = Project.objects.create(
        title="Second", slug="second", summary="Another photo.", photo=upload("two.jpg", 2400, 1200)
    )
    assert checks_seo.run_checks() == []
    out = capsys.readouterr().out
    assert "made the smaller copies of 1 upload(s)" in out and other.photo.name in out
    assert "no Celery worker had made them yet" in out


def test_the_sitemap_and_the_pages_must_agree(settings: Settings, projects: list[Project]) -> None:
    # A draft the list still links to, and a sitemap that names a page that is gone.
    projects[1].published = False
    projects[1].save()
    settings.KARNI_SITE_SITEMAPS = "tests.test_checks_seo.with_a_gone_page"
    failures = checks_seo.SeoCrawl().run()
    assert failures == [
        "SITE018: sitemap.xml lists /projects/gone/, which answers 404. List only pages that "
        "answer 200.",
        "SITE018: /projects/market/ is a page of the site that sitemap.xml leaves out. Give its "
        "row get_absolute_url() and a public filter (class Karni: sitemap), or list it in "
        "KARNI_SITE_SITEMAP_EXCLUDE when it should stay out.",
    ]
    settings.KARNI_SITE_SITEMAP_EXCLUDE = [*settings.KARNI_SITE_SITEMAP_EXCLUDE, "/projects/*"]
    settings.KARNI_SITE_SITEMAPS = "karni_site.sitemaps.sitemaps"
    assert checks_seo.SeoCrawl().run() == []


def with_a_gone_page() -> dict[str, Any]:
    from karni_site.sitemaps import SiteSitemap, sitemaps

    class Gone(SiteSitemap):
        def items(self) -> list[str]:
            return ["/projects/gone/"]

        def location(self, item: str) -> str:
            return item

    return {**sitemaps(), "gone": Gone()}


def test_a_menu_item_whose_page_is_gone(projects: list[Project]) -> None:
    from karni_site.models import Menu, MenuItem

    menu = Menu.objects.create(name="footer")
    MenuItem.objects.create(menu=menu, title="About", route="website:about", order=0)
    # Seeded while a project had a page of its own, before they became one view.
    MenuItem.objects.create(menu=menu, title="The cake", route="website:project_wedding", order=1)
    MenuItem.objects.create(menu=menu, title="Off", route="website:gone", enabled=False, order=2)
    failures = checks_seo.SeoCrawl().run()
    (menu_failure,) = [f for f in failures if f.startswith("SITE007")]
    assert "menu 'footer', item 'The cake': no page is named 'website:project_wedding'" in (
        menu_failure
    )
    assert "Choose its page again in the admin's Menus" in menu_failure


def test_a_site_without_the_sitemap(settings: Settings) -> None:
    urlconf = ModuleType("seo_urls_without_karni_site")
    urlconf.urlpatterns = [path("", include(seo_urls.seo))]  # type: ignore[attr-defined]
    settings.ROOT_URLCONF = urlconf
    failures = checks_seo.SeoCrawl().run()
    assert failures[-1] == (
        'SITE018: /sitemap.xml does not answer. Add path("", include("karni_site.urls")) to '
        "config/urls.py (karni make site does)."
    )


def test_the_hook_runs_with_the_projects_hosts(
    settings: Settings, projects: list[Project], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.ALLOWED_HOSTS = ["www.example.com"]
    assert checks_seo.run_checks() == []
    from django.apps import apps

    monkeypatch.setattr(apps, "is_installed", lambda name: False)
    assert checks_seo.run_checks() == []


def test_the_hook_says_when_there_is_no_site(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.apps import apps

    monkeypatch.setattr(apps, "is_installed", lambda name: False)
    checks_seo.run_checks()
    assert "no public site to check" in capsys.readouterr().out


def test_the_page_limit_and_ignored_paths(settings: Settings, projects: list[Project]) -> None:
    settings.KARNI_SITE_SEO_MAX_PAGES = 2
    assert len(checks_seo.SeoCrawl().pages) == 0
    crawl = checks_seo.SeoCrawl()
    crawl.run()
    assert len(crawl.pages) == 2
    settings.KARNI_SITE_SEO_MAX_PAGES = 500
    settings.KARNI_SITE_SEO_IGNORE = [r"^/web/", r"^/projects/"]
    crawl = checks_seo.SeoCrawl()
    crawl.run()
    assert not any(page.startswith("/projects/") for page in crawl.pages)


def test_the_crawls_request_logs_are_held_back(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.INFO), checks_seo.quiet_requests() as errors:
        logging.getLogger("django_structlog.middlewares.request").info("request_started")
        logging.getLogger("karni.queries").warning("GET / 200: 7 queries, 6 duplicated")
        logging.getLogger("django.request").warning("Not Found: /old/")
        logging.getLogger("django.request").error("Internal Server Error: /broken/")
        logging.getLogger("karni_site").warning("a module's own warning still shows")
    shown = [record.getMessage() for record in caplog.records]
    assert shown == ["a module's own warning still shows"]
    assert errors == ["Internal Server Error: /broken/"]
    # Afterwards every logger is as it was.
    with caplog.at_level(logging.INFO):
        logging.getLogger("django_structlog.middlewares.request").info("request_finished")
    assert caplog.records[-1].getMessage() == "request_finished"


def test_the_hook_summarises_the_errors_the_pages_logged(
    settings: Settings,
    projects: list[Project],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import logging

    real = checks_seo.SeoCrawl.get
    logged: list[str] = []

    def get(self: checks_seo.SeoCrawl, path: str) -> Any:
        if path == "/about/" and not logged:
            logged.append(path)
            logging.getLogger("django.request").error("Internal Server Error: /about/")
        return real(self, path)

    monkeypatch.setattr(checks_seo.SeoCrawl, "get", get)
    assert checks_seo.run_checks() == []
    out = capsys.readouterr().out
    assert (
        "karni check --seo: the pages' requests logged 1 error(s), not shown here, the first: "
        "Internal Server Error: /about/."
    ) in out
    # Nothing logged: nothing said.
    monkeypatch.setattr(checks_seo.SeoCrawl, "get", real)
    checks_seo.run_checks()
    assert "logged" not in capsys.readouterr().out
