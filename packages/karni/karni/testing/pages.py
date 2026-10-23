"""Page test helper: a public site's pages answer, carry a title, a description and alt text,
and link only to URLs that exist.

::

    import pytest
    from karni.testing import assert_pages


    @pytest.mark.django_db
    def test_pages(client):
        assert_pages(client, ["/", "/about/"])

**assert_pages(client, urls)** requests each URL with ``client`` (a Django
test client, signed in or not) and checks, in one call:

* **status**: the page answers 200. A redirect is reported with its status
  and ``Location``. ``follow=True`` checks the page it ends on instead.
* **title**: the HTML has a non-empty ``<title>``. A ``<title>`` inside an
  inline ``<svg>`` names the drawing, not the page, so it does not count.
* **description**: the HTML has a ``<meta name="description">`` with a
  non-empty ``content``.
* **alt**: every ``<img>`` has an ``alt`` attribute. ``alt=""`` counts as
  present, so a decorative image passes.
* **links**: every same-site URL in an ``href``, ``src``, ``srcset`` or
  ``poster`` attribute answers 200, or redirects to a URL that answers 200.
  Relative paths and absolute URLs on the test host are same-site.
  ``mailto:``, ``tel:``, ``javascript:`` and ``data:`` URLs, fragments and
  other hosts are not requested. Each distinct URL is requested once per
  call, and a listed page that answered 200 is not requested again as a
  link.
* **not_found**: an unknown URL (:data:`NOT_FOUND_URL`) answers 404.

Django's test client serves no static files: Karni's settings add no static
route, and ``DEBUG`` is off in tests. A URL under ``STATIC_URL`` that answers
404 is therefore looked up with the staticfiles finders, the lookup
``runserver`` and ``collectstatic`` use, so a mistyped ``{% static %}`` path
still fails. A URL under ``MEDIA_URL`` that answers 404 is looked up in the
default storage when it is the file system. Without
``django.contrib.staticfiles`` a static URL is listed in the report's
``skipped`` instead.

Every problem is reported, one line per page and problem, in one
``KarniAssertionError`` (``E618``). The return value is a
:class:`PagesReport`: the pages and links checked, and what was skipped.

Override / escape hatches:

* ``follow=True`` checks the page a redirect ends on.
* ``check_links=False``, ``require_title=False``,
  ``require_description=False`` and ``require_alt=False`` turn a check off.
* ``not_found_url=None`` skips the 404 check, and another URL replaces
  :data:`NOT_FOUND_URL`.
* ``ignore=[r"^/admin/"]`` lists regular expressions searched in a link's
  path and query. A matching link is not requested.
* ``hosts=["www.example.com"]`` names more hosts that count as the site.
* ``parser=`` takes a :class:`PageParser` subclass, which decides what a
  page's HTML yields (a lazy-loading ``data-src`` as a link, for example).

:meth:`karni.testing.APITestCase.assert_pages` is the method form.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, ClassVar, Final
from urllib.parse import unquote, urljoin, urlsplit

from karni.exceptions import KarniAssertionError, KarniValueError

__all__ = [
    "NOT_FOUND_URL",
    "Image",
    "Link",
    "PageParser",
    "PagesReport",
    "assert_pages",
]

#: The URL :func:`assert_pages` expects a 404 for. No site routes it.
NOT_FOUND_URL: Final = "/karni-assert-pages-404/"
#: The host name Django's test client sends.
TEST_HOST: Final = "testserver"
#: Content types parsed as HTML.
HTML_TYPES: Final = frozenset({"text/html", "application/xhtml+xml"})
#: URL schemes that are requested. Every other scheme (mailto:, tel:, ...) is not a page.
WEB_SCHEMES: Final = frozenset({"", "http", "https"})


# parsing


@dataclass(frozen=True)
class Image:
    """An ``<img>``: its ``src``, its ``alt`` (``None`` when the attribute is missing) and line."""

    src: str
    alt: str | None
    line: int


@dataclass(frozen=True)
class Link:
    """A URL in a page: the raw attribute value, the tag and attribute holding it, its line."""

    url: str
    tag: str
    attribute: str
    line: int


class PageParser(HTMLParser):
    """What :func:`assert_pages` reads from a page: title, description, images and links.

    After ``feed()`` and ``close()``:

    * ``title`` is ``None`` without a ``<title>`` element, else its text with
      whitespace collapsed.
    * ``description`` is ``None`` without a ``<meta name="description">``,
      else its stripped ``content``.
    * ``images`` lists every ``<img>``.
    * ``links`` lists every URL in an attribute that :attr:`link_attributes`
      names.
    * ``base`` is the first ``<base href>``.

    Override / escape hatch: subclass it and pass ``parser=`` to
    :func:`assert_pages`. :attr:`link_attributes` maps a tag to the
    attributes that hold a URL (a ``srcset`` value is split into its URLs),
    and :attr:`skip_rels` lists ``<link rel>`` values that name no resource
    to request.
    """

    link_attributes: ClassVar[Mapping[str, tuple[str, ...]]] = {
        "a": ("href",),
        "area": ("href",),
        "link": ("href",),
        "img": ("src", "srcset"),
        "source": ("src", "srcset"),
        "script": ("src",),
        "iframe": ("src",),
        "video": ("src", "poster"),
        "audio": ("src",),
        "track": ("src",),
        "embed": ("src",),
    }
    skip_rels: ClassVar[frozenset[str]] = frozenset({"preconnect", "dns-prefetch"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.images: list[Image] = []
        self.links: list[Link] = []
        self.base: str | None = None
        self._title_parts: list[str] | None = None
        self._svg_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        line = self.getpos()[0]
        if tag == "svg":
            self._svg_depth += 1
        elif tag == "title":
            if self._svg_depth == 0 and self.title is None and self._title_parts is None:
                self._title_parts = []
        elif tag == "meta":
            name = (values.get("name") or "").strip().lower()
            if name == "description" and self.description is None:
                self.description = (values.get("content") or "").strip()
        elif tag == "base":
            if self.base is None and values.get("href"):
                self.base = values["href"]
        elif tag == "img":
            alt = (values["alt"] or "") if "alt" in values else None
            self.images.append(Image((values.get("src") or "").strip(), alt, line))
        if tag == "link":
            rels = set((values.get("rel") or "").lower().split())
            if rels & self.skip_rels:
                return
        for attribute in self.link_attributes.get(tag, ()):
            value = values.get(attribute)
            if not value:
                continue
            urls = self.srcset_urls(value) if attribute.endswith("srcset") else [value]
            self.links.extend(Link(url.strip(), tag, attribute, line) for url in urls)

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
        elif tag == "title":
            self._end_title()

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)

    def close(self) -> None:
        super().close()
        self._end_title()

    def _end_title(self) -> None:
        if self._title_parts is not None:
            self.title = " ".join("".join(self._title_parts).split())
            self._title_parts = None

    @staticmethod
    def srcset_urls(value: str) -> list[str]:
        """The URLs of a ``srcset`` value (``"a.png 1x, b.png 2x"`` gives both)."""
        return [part.split()[0] for part in value.split(",") if part.split()]


# the report


@dataclass
class PagesReport:
    """What :func:`assert_pages` checked, what it skipped and what failed."""

    #: The URLs checked as pages, in the order given.
    pages: list[str] = field(default_factory=list)
    #: Every distinct same-site link target checked (path and query).
    links: list[str] = field(default_factory=list)
    #: Checks turned off, and links not requested, each with the reason.
    skipped: list[str] = field(default_factory=list)
    #: One line per page and problem.
    failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"assert_pages: {len(self.failures)} problem(s) ({len(self.pages)} page(s) and "
            f"{len(self.links)} link(s) checked)"
        ]
        lines += [f"  - {failure}" for failure in self.failures]
        return "\n".join(lines)


class _Stopped(Exception):
    """A request raised: the run records it and stops."""


#: The outcome of a link whose request is under way (a redirect back to it is a loop).
_PENDING: Final = "pending"


def _staticfiles_installed() -> bool:
    from django.apps import apps

    return apps.is_installed("django.contrib.staticfiles")


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _close(response: Any) -> None:
    if getattr(response, "streaming", False):
        response.close()


def _body(response: Any) -> str:
    if getattr(response, "streaming", False):
        raw = b"".join(response.streaming_content)
        response.close()
    else:
        raw = response.content
    return bytes(raw).decode(response.charset or "utf-8", errors="replace")


def _redirect(response: Any) -> str | None:
    """The ``Location`` of a redirect response, else ``None``."""
    if 300 <= response.status_code < 400:
        location = response.get("Location")
        return str(location) if location else None
    return None


def _host(value: str) -> str:
    return value.rsplit(":", 1)[0].lower() if value.count(":") == 1 else value.lower()


# the run


class _Pages:
    def __init__(
        self,
        client: Any,
        *,
        follow: bool,
        check_links: bool,
        require_title: bool,
        require_description: bool,
        require_alt: bool,
        not_found_url: str | None,
        ignore: Iterable[str | re.Pattern[str]],
        hosts: Iterable[str],
        parser: type[PageParser],
    ) -> None:
        self.client = client
        self.follow = follow
        self.check_links = check_links
        self.require_title = require_title
        self.require_description = require_description
        self.require_alt = require_alt
        self.not_found_url = not_found_url
        self.ignore = [re.compile(pattern) for pattern in ignore]
        self.parser = parser
        defaults = getattr(client, "defaults", {}) or {}
        host = str(defaults.get("HTTP_HOST") or defaults.get("SERVER_NAME") or TEST_HOST)
        self.origin = f"http://{host}/"
        self.hosts = {TEST_HOST, _host(host), *(_host(name) for name in hosts)}
        self.report = PagesReport()
        #: Link target -> why it is broken (``None``: it answers).
        self.outcomes: dict[str, str | None] = {}
        self.noted: set[str] = set()
        self.error: BaseException | None = None

    # plumbing

    def get(self, url: str, *, follow: bool = False) -> Any:
        try:
            return self.client.get(url, follow=follow)
        except Exception as exc:
            self.error = exc
            raise _Stopped(f"GET {url} raised {type(exc).__name__}: {_first_line(exc)}") from exc

    def fail(self, page: str, message: str) -> None:
        self.report.failures.append(f"{page}: {message}")

    def skip(self, message: str) -> None:
        if message not in self.noted:
            self.noted.add(message)
            self.report.skipped.append(message)

    def resolve(self, raw: str, base: str) -> tuple[str, str]:
        """``(kind, target)``: ``internal`` with the path and query, ``external`` or ``none``."""
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            return "none", raw
        if urlsplit(raw).scheme.lower() not in WEB_SCHEMES:
            return "none", raw
        parts = urlsplit(urljoin(base, raw))
        if (parts.hostname or "").lower() not in self.hosts:
            return "external", raw
        target = parts.path or "/"
        if parts.query:
            target += f"?{parts.query}"
        return "internal", target

    # the checks

    def run(self, urls: list[str]) -> PagesReport:
        for flag, name in (
            (self.require_title, "title (require_title=False)"),
            (self.require_description, "description (require_description=False)"),
            (self.require_alt, "alt (require_alt=False)"),
            (self.check_links, "links (check_links=False)"),
        ):
            if not flag:
                self.skip(name)
        if self.not_found_url is None:
            self.skip("not_found (not_found_url=None)")
        try:
            found: list[tuple[str, str, list[Link]]] = []
            for url in urls:
                page = self.check_page(url)
                if page is not None:
                    found.append((url, *page))
            if self.not_found_url is not None:
                self.check_not_found(self.not_found_url)
            if self.check_links:
                for url, base, links in found:
                    self.check_page_links(url, base, links)
        except _Stopped as exc:
            self.report.failures.append(
                f"{exc}. The remaining pages and links were not checked, because the error "
                "may have left the test's database transaction unusable."
            )
        return self.report

    def check_page(self, url: str) -> tuple[str, list[Link]] | None:
        """Request ``url`` as a page and check its HTML. Returns ``(base URL, links)``."""
        self.report.pages.append(url)
        response = self.get(url, follow=self.follow)
        chain = list(getattr(response, "redirect_chain", None) or [])
        final = urljoin(urljoin(self.origin, url), chain[-1][0]) if chain else url
        if response.status_code != 200:
            _close(response)
            location = _redirect(response)
            if location:
                self.fail(
                    url,
                    f"answered {response.status_code}, a redirect to {location}, expected 200. "
                    "List the URL it redirects to, or pass follow=True to check that page.",
                )
            else:
                self.fail(url, f"answered {response.status_code}, expected 200.")
            return None
        if not chain:
            kind, target = self.resolve(url, self.origin)
            if kind == "internal":
                self.outcomes[target] = None
        content_type = str(response.get("Content-Type") or "")
        if content_type.split(";")[0].strip().lower() not in HTML_TYPES:
            _close(response)
            self.skip(
                f"{url}: answered {content_type or 'no Content-Type'}, not HTML, so its title, "
                "description, images and links were not checked"
            )
            return None
        parser = self.parser()
        parser.feed(_body(response))
        parser.close()
        self.check_html(url, parser)
        base = urljoin(self.origin, final)
        if parser.base:
            base = urljoin(base, parser.base)
        return base, parser.links

    def check_html(self, url: str, parser: PageParser) -> None:
        if self.require_title and not parser.title:
            missing = "no <title>" if parser.title is None else "an empty <title>"
            self.fail(
                url,
                f"{missing}. Browser tabs and search results show the title. Give the page "
                "one, in {% block title %} for a page that extends the site's base.html.",
            )
        if self.require_description and not parser.description:
            missing = (
                'no <meta name="description">'
                if parser.description is None
                else 'a <meta name="description"> with an empty content attribute'
            )
            self.fail(
                url,
                f"{missing}. Search results show it under the title. Give the page one "
                "sentence, in {% block description %} for a page that extends the site's "
                "base.html.",
            )
        if self.require_alt:
            bare = [image for image in parser.images if image.alt is None]
            if bare:
                listed = ", ".join(
                    f"{image.src or '(no src)'} (line {image.line})" for image in bare
                )
                self.fail(
                    url,
                    f"{len(bare)} <img> without an alt attribute: {listed}. Screen readers "
                    "read the alt text and search engines index it. Describe each image in "
                    'alt="...", or write alt="" when it is decorative.',
                )

    def check_not_found(self, url: str) -> None:
        response = self.get(url)
        _close(response)
        if response.status_code == 404:
            return
        location = _redirect(response)
        answered = f"answered {response.status_code}" + (
            f", a redirect to {location}" if location else ""
        )
        self.fail(
            url,
            f"a URL the site does not have {answered}, expected 404. A route answers every URL "
            "(a catch-all pattern or view), so search engines index missing pages as real ones. "
            "Raise Http404 for paths the site does not have, or pass not_found_url=None.",
        )

    def check_page_links(self, page: str, base: str, links: list[Link]) -> None:
        lines: dict[str, list[int]] = {}
        for link in links:
            kind, target = self.resolve(link.url, base)
            if kind == "none":
                continue
            if kind == "external":
                self.skip(f"{target}: another host, not requested")
                continue
            pattern = next((p for p in self.ignore if p.search(target)), None)
            if pattern is not None:
                self.skip(f"{target}: matches ignore={pattern.pattern!r}, not requested")
                continue
            lines.setdefault(target, [])
            if link.line not in lines[target]:
                lines[target].append(link.line)
        for target, at in lines.items():
            problem = self.link_outcome(target)
            if problem is not None:
                where = ("line " if len(at) == 1 else "lines ") + ", ".join(map(str, at))
                self.fail(page, f"links to {target} ({where}), {problem}.")

    def link_outcome(self, target: str) -> str | None:
        """Why ``target`` is broken, else ``None``. Each target is requested once per call."""
        if target not in self.report.links:
            self.report.links.append(target)
        if target in self.outcomes:
            outcome = self.outcomes[target]
            return "which redirects in a loop" if outcome is _PENDING else outcome
        self.outcomes[target] = _PENDING
        problem = self.request_link(target)
        self.outcomes[target] = problem
        return problem

    def request_link(self, target: str) -> str | None:
        response = self.get(target)
        _close(response)
        status = response.status_code
        if status == 200:
            return None
        location = _redirect(response)
        if location is not None:
            kind, hop = self.resolve(location, urljoin(self.origin, target))
            if kind != "internal":
                self.skip(f"{location}: another host (a redirect from {target}), not requested")
                return None
            problem = self.link_outcome(hop)
            return None if problem is None else f"which redirects to {hop}, {problem}"
        if status == 404:
            missing = self.missing_file(target)
            if missing is not None:
                return missing or None
        return f"which answered {status}"

    def missing_file(self, url: str) -> str | None:
        """For a static or media URL, ``""`` when the file exists, else why not.

        ``None`` when ``url`` is neither a static nor a media URL.
        """
        from django.conf import settings

        path = unquote(urlsplit(url).path)
        static_url = str(settings.STATIC_URL or "")
        if static_url.startswith("/") and path.startswith(static_url):
            name = path[len(static_url) :]
            if not _staticfiles_installed():
                self.skip(
                    f"{url}: Django serves no static files in tests and "
                    "django.contrib.staticfiles is not installed, so it was not checked"
                )
                return ""
            if self.static_file_exists(name):
                return ""
            return (
                f"which is not a file in any app's static/ directory, STATICFILES_DIRS or "
                f"STATIC_ROOT (the test client serves no static files, so Karni looked for "
                f"{name} with the staticfiles finders)"
            )
        media_url = str(settings.MEDIA_URL or "")
        if media_url.startswith("/") and path.startswith(media_url):
            from django.core.files.storage import FileSystemStorage, default_storage

            name = path[len(media_url) :]
            if not isinstance(default_storage, FileSystemStorage):
                self.skip(
                    f"{url}: the default storage is not the file system, so it was not checked"
                )
                return ""
            if default_storage.exists(name):
                return ""
            return f"which is not a file in the default storage (MEDIA_ROOT has no {name})"
        return None

    @staticmethod
    def static_file_exists(name: str) -> bool:
        from django.contrib.staticfiles import finders
        from django.contrib.staticfiles.storage import staticfiles_storage

        if finders.find(name):
            return True
        try:
            return bool(staticfiles_storage.exists(name))
        except Exception:  # noqa: BLE001 - no STATIC_ROOT: the finders have answered
            return False


def assert_pages(
    client: Any,
    urls: Iterable[str],
    *,
    follow: bool = False,
    check_links: bool = True,
    require_title: bool = True,
    require_description: bool = True,
    require_alt: bool = True,
    not_found_url: str | None = NOT_FOUND_URL,
    ignore: Iterable[str | re.Pattern[str]] = (),
    hosts: Iterable[str] = (),
    parser: type[PageParser] | None = None,
) -> PagesReport:
    """Assert that every page in ``urls`` passes the page checks (see the module docstring).

    :param client: a Django test client (``client`` in pytest-django, ``self.client``).
    :param urls: the pages to check: paths such as ``"/"`` and ``"/about/"``.
    :param follow: follow a page's redirects and check the page it ends on.
    :param check_links: request every same-site link and require it to answer.
    :param require_title: require a non-empty ``<title>``.
    :param require_description: require a non-empty ``<meta name="description">``.
    :param require_alt: require an ``alt`` attribute on every ``<img>``.
    :param not_found_url: a URL that must answer 404. ``None`` skips the check.
    :param ignore: regular expressions searched in a link's path and query. A
        matching link is not requested.
    :param hosts: more host names whose absolute URLs count as the site's own.
    :param parser: the :class:`PageParser` subclass that reads each page (default
        :class:`PageParser`).
    :raises AssertionError: listing every problem, one line per page and problem (``E618``).
    """
    __tracebackhide__ = True  # pytest shows the report, not this function's source
    pages = list(urls)
    if not pages:
        raise KarniValueError(
            "assert_pages was given no URLs, so it would check nothing and pass. Pass the "
            'site\'s pages, for example assert_pages(client, ["/", "/about/"]).',
            code="E619",
        )
    run = _Pages(
        client,
        follow=follow,
        check_links=check_links,
        require_title=require_title,
        require_description=require_description,
        require_alt=require_alt,
        not_found_url=not_found_url,
        ignore=ignore,
        hosts=hosts,
        parser=parser or PageParser,
    )
    report = run.run(pages)
    if report.failures:
        raise KarniAssertionError(report.render(), code="E618") from run.error
    return report
