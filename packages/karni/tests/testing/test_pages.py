"""assert_pages: a public site's pages, their title, description, alt text and links, in one call.

The site is ``tests/testing/pages_urls.py``: ``/`` and ``/about/`` pass, every
other page fails one check.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, ClassVar

import pytest
from django.test import Client, override_settings

from karni.exceptions import KarniAssertionError, KarniValueError
from karni.testing import APITestCase, assert_pages
from karni.testing import pages as pages_module
from karni.testing.pages import NOT_FOUND_URL, PageParser, PagesReport
from tests.testing.pages_urls import STATIC_DIR

STATIC_NOT_FOUND = (
    "which is not a file in any app's static/ directory, STATICFILES_DIRS or STATIC_ROOT"
)


class RecordingClient(Client):
    """A test client that records every URL it requests."""

    def __init__(self, **defaults: Any) -> None:
        super().__init__(**defaults)
        self.requested: list[str] = []

    def get(self, path: str, *args: Any, **kwargs: Any) -> Any:
        self.requested.append(path)
        return super().get(path, *args, **kwargs)


@pytest.fixture(autouse=True)
def site(settings: Any, tmp_path: Path) -> None:
    settings.ROOT_URLCONF = "tests.testing.pages_urls"
    settings.STATICFILES_DIRS = [STATIC_DIR]
    settings.MEDIA_ROOT = str(tmp_path)


def failures(urls: list[str], **options: Any) -> list[str]:
    """The failure lines assert_pages raises for ``urls``."""
    with pytest.raises(KarniAssertionError) as caught:
        assert_pages(Client(), urls, **options)
    message = str(caught.value)
    assert message.startswith("E618: assert_pages: ")
    return [line[4:] for line in message.splitlines() if line.startswith("  - ")]


# pages that pass


def test_pages_that_pass_return_the_report() -> None:
    report = assert_pages(Client(), ["/", "/about/"])
    assert isinstance(report, PagesReport)
    assert report.pages == ["/", "/about/"]
    assert report.failures == []
    # Relative, absolute and fragment links to /about/ are one link. The stylesheet
    # and logo are found by the staticfiles finders, the redirect ends on /about/.
    assert report.links == [
        "/static/testsite/site.css",
        "/",
        "/about/",
        "/old-about/",
        "/static/testsite/logo.svg",
    ]
    assert report.skipped == [
        "https://example.org/partner/: another host, not requested",
        "//cdn.example.net/app.js: another host, not requested",
    ]


def test_each_url_is_requested_once_and_other_hosts_never() -> None:
    client = RecordingClient()
    assert_pages(client, ["/", "/about/"])
    counts = Counter(client.requested)
    assert counts == {
        "/": 1,
        "/about/": 1,
        NOT_FOUND_URL: 1,
        "/static/testsite/site.css": 1,
        "/old-about/": 1,
        "/static/testsite/logo.svg": 1,
    }
    assert not any("example" in url for url in client.requested)


@override_settings(ROOT_URLCONF="tests.testing.pages_urls", STATICFILES_DIRS=[STATIC_DIR])
class AssertPagesMethodTests(APITestCase):
    def test_the_method_uses_the_test_client(self) -> None:
        assert self.assert_pages(["/about/"]).pages == ["/about/"]
        with pytest.raises(KarniAssertionError, match="/no-title/: no <title>"):
            self.assert_pages(["/no-title/"], client=Client())


# each failure kind


def test_a_page_that_does_not_answer_200() -> None:
    assert failures(["/gone/", "/sign-in-first/"]) == [
        "/gone/: answered 410, expected 200.",
        "/sign-in-first/: answered 302, a redirect to /about/, expected 200. List the URL it "
        "redirects to, or pass follow=True to check that page.",
    ]
    report = assert_pages(Client(), ["/sign-in-first/"], follow=True)
    assert report.pages == ["/sign-in-first/"]
    assert "/" in report.links  # the links of /about/, the page it ends on


def test_a_missing_or_empty_title() -> None:
    lines = failures(["/no-title/", "/empty-title/", "/svg-title/"])
    assert [line.split(".")[0] for line in lines] == [
        "/no-title/: no <title>",
        "/empty-title/: an empty <title>",
        "/svg-title/: no <title>",  # an <svg>'s <title> names the drawing
    ]
    assert "{% block title %}" in lines[0]


def test_a_missing_or_empty_description() -> None:
    lines = failures(["/no-description/", "/empty-description/"])
    assert [line.split(". ")[0] for line in lines] == [
        '/no-description/: no <meta name="description">',
        '/empty-description/: a <meta name="description"> with an empty content attribute',
    ]
    assert "{% block description %}" in lines[0]


def test_an_image_without_alt() -> None:
    # alt="" (decorative) and a bare alt attribute count as present.
    assert failures(["/no-alt/"]) == [
        "/no-alt/: 1 <img> without an alt attribute: /static/testsite/logo.svg (line 10). Screen "
        "readers read the alt text and search engines index it. Describe each image in "
        'alt="...", or write alt="" when it is decorative.'
    ]


def test_broken_internal_links() -> None:
    lines = failures(["/broken/"])
    assert lines[0] == "/broken/: links to /missing/ (lines 9, 13), which answered 404."
    assert lines[1].startswith(
        f"/broken/: links to /static/testsite/missing.css (line 10), {STATIC_NOT_FOUND}"
    )
    assert lines[2:] == [
        "/broken/: links to /moved/ (line 11), which redirects to /missing/, which answered 404.",
        "/broken/: links to /loop/ (line 12), which redirects to /loop/, which redirects in a "
        "loop.",
    ]


def test_an_unknown_url_that_does_not_answer_404(settings: Any) -> None:
    settings.ROOT_URLCONF = "tests.testing.pages_catchall_urls"
    assert failures(["/about/"]) == [
        f"{NOT_FOUND_URL}: a URL the site does not have answered 200, expected 404. A route "
        "answers every URL (a catch-all pattern or view), so search engines index missing "
        "pages as real ones. Raise Http404 for paths the site does not have, or pass "
        "not_found_url=None."
    ]
    assert assert_pages(Client(), ["/about/"], not_found_url=None).skipped == [
        "not_found (not_found_url=None)"
    ]


def test_every_problem_is_reported_in_one_error() -> None:
    lines = failures(["/", "/gone/", "/no-title/", "/no-alt/", "/broken/"])
    assert [line.split(":")[0] for line in lines] == [
        "/gone/",
        "/no-title/",
        "/no-alt/",
        "/broken/",
        "/broken/",
        "/broken/",
        "/broken/",
    ]


def test_a_page_that_raises_stops_the_run_and_chains_the_error() -> None:
    with pytest.raises(KarniAssertionError) as caught:
        assert_pages(Client(), ["/no-title/", "/raises/", "/about/"])
    message = str(caught.value)
    assert "/no-title/: no <title>" in message
    assert "GET /raises/ raised ValueError: the template needs a value. The remaining pages" in (
        message
    )
    assert isinstance(caught.value.__cause__, ValueError)


# what is not checked


def test_links_to_other_hosts_and_external_redirects_are_not_requested() -> None:
    client = RecordingClient()
    with pytest.raises(KarniAssertionError):
        assert_pages(client, ["/broken/"])
    assert "/away/" in client.requested  # the link is ours, its redirect target is not
    assert not any(url.startswith("http") for url in client.requested)


def test_a_page_that_is_not_html_is_listed_as_skipped() -> None:
    report = assert_pages(Client(), ["/robots.txt"])
    assert report.skipped == [
        "/robots.txt: answered text/plain, not HTML, so its title, description, images and "
        "links were not checked"
    ]


def test_media_files_are_looked_up_in_the_default_storage(tmp_path: Path) -> None:
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "kept.png").write_bytes(b"png")
    assert failures(["/media-page/"]) == [
        "/media-page/: links to /media/photos/lost.png (line 10), which is not a file in the "
        "default storage (MEDIA_ROOT has no photos/lost.png)."
    ]


def test_static_links_are_skipped_without_staticfiles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pages_module, "_staticfiles_installed", lambda: False)
    report = assert_pages(Client(), ["/about/"])
    assert report.skipped == [
        "/static/testsite/site.css: Django serves no static files in tests and "
        "django.contrib.staticfiles is not installed, so it was not checked"
    ]


def test_no_urls_is_an_error() -> None:
    with pytest.raises(KarniValueError, match="E619: assert_pages was given no URLs"):
        assert_pages(Client(), [])


# escape hatches


def test_each_check_can_be_turned_off() -> None:
    report = assert_pages(
        Client(),
        ["/no-title/", "/empty-description/", "/no-alt/", "/broken/"],
        require_title=False,
        require_description=False,
        require_alt=False,
        check_links=False,
    )
    assert report.links == []
    assert report.skipped == [
        "title (require_title=False)",
        "description (require_description=False)",
        "alt (require_alt=False)",
        "links (check_links=False)",
    ]


def test_ignore_hosts_and_a_parser_subclass() -> None:
    assert failures(["/elsewhere/"]) == [
        "/elsewhere/: links to /admin-only/ (line 10), which answered 404."
    ]

    class LazyImages(PageParser):
        link_attributes: ClassVar = {**PageParser.link_attributes, "img": ("src", "data-src")}

    lines = failures(
        ["/elsewhere/"], ignore=[r"^/admin-only/"], hosts=["www.example.com"], parser=LazyImages
    )
    assert len(lines) == 1
    assert lines[0].startswith(
        f"/elsewhere/: links to /static/testsite/lazy.png (line 11), {STATIC_NOT_FOUND}"
    )
    report = assert_pages(
        Client(), ["/elsewhere/"], ignore=[r"^/admin-only/", r"lazy"], hosts=["www.example.com"]
    )
    # The absolute link on the real domain is checked as /about/.
    assert report.links == ["/about/"]
    assert report.skipped == ["/admin-only/: matches ignore='^/admin-only/', not requested"]


def test_the_parser_reads_title_description_images_and_links() -> None:
    parser = PageParser()
    parser.feed(
        "<html><head><TITLE>  Two\n words </TITLE>"
        '<meta name="Description" content=" Said once. ">'
        '<meta name="description" content="Said twice.">'
        '<link rel="dns-prefetch" href="//fonts.example.net">'
        '<base href="/docs/"></head><body>'
        '<svg><title>Not the page</title></svg><img src="a.png" alt>'
        '<picture><source srcset="b.webp 1x, c.webp 2x"><img src="d.png" alt="D"></picture>'
        '<video src="e.mp4" poster="f.jpg"></video></body></html>'
    )
    parser.close()
    assert parser.title == "Two words"
    assert parser.description == "Said once."
    assert parser.base == "/docs/"
    assert [(image.src, image.alt) for image in parser.images] == [("a.png", ""), ("d.png", "D")]
    assert [link.url for link in parser.links] == [
        "a.png",
        "b.webp",
        "c.webp",
        "d.png",
        "e.mp4",
        "f.jpg",
    ]
