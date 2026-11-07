"""``karni check --seo``: every page as a visitor and a search engine get it, checked.

It renders the site through Django's test client, in process, against the
project's own database: no server, no network. That is a choice. A page's
title, description and images come from the database (the admin's entries,
the page's row, the client's edits, the site's settings) and from template
inheritance, so only a rendered page shows what a search engine reads.
Reading the templates would miss those and report template variables as
problems. The cost: the pages need a migrated database with their content,
and rendering a page stores its template's defaults, as a visit would.

Pages: ``/``, every address in sitemap.xml, every named URL without
arguments, and every page of the site they link to, up to
``KARNI_SITE_SEO_MAX_PAGES``. Paths matching ``KARNI_SITE_SEO_IGNORE`` are
never requested.

Findings, one line each:

* ``SITE010`` a page without a title, ``SITE011`` a title two pages share;
* ``SITE012`` a page without a description, or with the placeholder
  ``karni make site`` and ``karni make view`` write
  (:data:`PLACEHOLDER_DESCRIPTION`), ``SITE013`` one two pages share;
* ``SITE014`` an ``<img>`` without ``alt``, ``SITE015`` without ``width``
  and ``height``;
* ``SITE016`` an image much larger than the page shows it: without smaller
  copies (``srcset``), wider than ``KARNI_SITE_SEO_PIXEL_RATIO`` times its
  ``width``, wider than the widest copy Karni makes, or heavier than
  ``KARNI_SITE_SEO_IMAGE_BYTES``. It reads the HTML, not the layout, so an
  image without a ``width`` is judged by its file alone;
* ``SITE017`` a link, image, stylesheet or script of the site that answers
  an error;
* ``SITE018`` sitemap.xml missing, a page the site links to that it leaves
  out, or an address in it that does not answer 200 or asks not to be
  indexed;
* ``SITE007`` a menu item whose page, row or model is gone (a view that was
  renamed or replaced): the menu leaves it out, so the site loses the link
  without a word.

Duplicates are counted among the pages search engines may index (no
``noindex``, a canonical link to themselves).

An upload the pages show without its smaller copies gets them first, made
in this process (:func:`karni_site.renditions.made_inline`), and the run
names those images: in development no Celery worker may have made them yet,
and the check judges the copies the site serves once one has. The site
itself keeps queueing them. ``KARNI_SITE_QUEUE_RENDITIONS = False`` makes
none here either.

The crawl's own requests are not logged: the request log, the query log
and Django's request warnings of every page would bury the findings
(:func:`quiet_requests`), and the development capture under ``.karni/``
keeps the developer's requests, not the crawl's. An error a request logs is
counted, and the run prints one line with the first of them.

Override / escape hatch: the settings above, ``KARNI_SITE_SITEMAP_EXCLUDE``
for a page deliberately left out of the sitemap, ``KARNI_SITE_SEO_QUIET``
for the loggers held back, or :class:`SeoCrawl` with another client, for a
test: ``SeoCrawl(client).run()``.
"""

from __future__ import annotations

import logging
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from django.conf import settings
from karni.testing.pages import PageParser

from karni_site import conf, imagesize, renditions

__all__ = [
    "PLACEHOLDER_DESCRIPTION",
    "Img",
    "SeoCrawl",
    "SeoParser",
    "quiet_requests",
    "run_checks",
]

#: The description ``karni make site`` and ``karni make view`` write, to be replaced per page.
#: karni-cli writes the same text (karni_cli.generators.site.PLACEHOLDER_DESCRIPTION).
PLACEHOLDER_DESCRIPTION = "One sentence that search engines show under this page's title."

TITLE_CODE = "SITE010"
SAME_TITLE_CODE = "SITE011"
DESCRIPTION_CODE = "SITE012"
SAME_DESCRIPTION_CODE = "SITE013"
ALT_CODE = "SITE014"
SIZE_CODE = "SITE015"
WEIGHT_CODE = "SITE016"
LINK_CODE = "SITE017"
SITEMAP_CODE = "SITE018"
MENU_CODE = "SITE007"
_HTML = ("text/html", "application/xhtml+xml")
_WEB = ("", "http", "https")
_MAX_HOPS = 10
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@dataclass(frozen=True)
class Img:
    """An ``<img>`` as written: the attributes the checks read, and its line."""

    src: str
    alt: str | None
    width: str | None
    height: str | None
    srcset: str | None
    line: int


class SeoParser(PageParser):
    """:class:`~karni.testing.pages.PageParser` that also reads robots, canonical and img sizes."""

    def __init__(self) -> None:
        super().__init__()
        self.robots: str = ""
        self.canonical: str | None = None
        self.imgs: list[Img] = []
        self.pages: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        super().handle_starttag(tag, attrs)
        values = dict(attrs)
        if tag == "meta" and (values.get("name") or "").strip().lower() == "robots":
            self.robots = (values.get("content") or "").lower()
        elif tag == "link" and "canonical" in (values.get("rel") or "").lower().split():
            if self.canonical is None:
                self.canonical = (values.get("href") or "").strip()
        elif tag == "img":
            self.imgs.append(
                Img(
                    (values.get("src") or "").strip(),
                    (values["alt"] or "") if "alt" in values else None,
                    values.get("width"),
                    values.get("height"),
                    values.get("srcset"),
                    self.getpos()[0],
                )
            )
        elif tag in ("a", "area") and values.get("href"):
            self.pages.append(str(values["href"]).strip())


@dataclass
class Page:
    """One requested page: what it answered and what it holds."""

    path: str
    status: int
    html: bool = False
    title: str | None = None
    description: str | None = None
    noindex: bool = False
    canonical: str | None = None
    imgs: list[Img] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    location: str | None = None

    @property
    def indexable(self) -> bool:
        return self.status == 200 and self.html and not self.noindex


def _body(response: Any) -> bytes:
    """A response's bytes, streamed or not."""
    if getattr(response, "streaming", False):
        data = b"".join(response.streaming_content)
        response.close()
        return data
    return bytes(response.content)


def _number(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class SeoCrawl:
    """Requests the site's pages through ``client`` and collects the findings."""

    def __init__(self, client: Any = None) -> None:
        if client is None:
            from django.test import Client

            client = Client(raise_request_exception=False)
        self.client = client
        self.failures: list[str] = []
        #: The uploads whose smaller copies the crawl made, because none were there.
        self.made: list[str] = []
        self.pages: dict[str, Page] = {}
        self.outcomes: dict[str, str | None] = {}
        self.sizes: dict[str, tuple[tuple[int, int] | None, int]] = {}
        self.ignore = [re.compile(str(p)) for p in conf.get("KARNI_SITE_SEO_IGNORE") or ()]
        self.limit = int(conf.get("KARNI_SITE_SEO_MAX_PAGES") or 500)
        self.hosts = {"testserver"}
        configured = conf.get("KARNI_SITE_URL")
        if configured:
            self.hosts.add((urlsplit(str(configured)).hostname or "").lower())
        self.hosts |= {
            str(host).lstrip(".").lower()
            for host in getattr(settings, "ALLOWED_HOSTS", [])
            if host not in ("*", "")
        }

    # plumbing

    def fail(self, code: str, message: str) -> None:
        line = f"{code}: {message}"
        if line not in self.failures:
            self.failures.append(line)

    def get(self, path: str) -> Any:
        return self.client.get(path, secure=True)

    def local(self, raw: str, base: str) -> str | None:
        """The path and query ``raw`` reaches on this site, or ``None`` (elsewhere, not a page)."""
        raw = raw.strip()
        if not raw or raw.startswith("#") or urlsplit(raw).scheme.lower() not in _WEB:
            return None
        parts = urlsplit(urljoin(base, raw))
        if parts.netloc and (parts.hostname or "").lower() not in self.hosts:
            return None
        path = parts.path or "/"
        if any(pattern.search(path) for pattern in self.ignore):
            return None
        return path + (f"?{parts.query}" if parts.query else "")

    # pages

    def visit(self, path: str) -> Page:
        found = self.pages.get(path)
        if found is not None:
            return found
        response = self.get(path)
        page = Page(path, response.status_code)
        self.pages[path] = page
        if 300 <= response.status_code < 400:
            page.location = str(response.get("Location") or "") or None
            return page
        content_type = str(response.get("Content-Type") or "").split(";")[0].strip().lower()
        if response.status_code != 200 or content_type not in _HTML:
            return page
        parser = SeoParser()
        parser.feed(_body(response).decode(response.charset or "utf-8", errors="replace"))
        parser.close()
        page.html = True
        page.title = parser.title
        page.description = parser.description
        page.noindex = "noindex" in parser.robots
        page.canonical = parser.canonical
        page.imgs = parser.imgs
        base = f"https://testserver{path}"
        page.links = [link.url for link in parser.links]
        own = self.local(parser.canonical or "", base) if parser.canonical else path
        if own is not None and urlsplit(own).path != urlsplit(path).path:
            page.noindex = True  # its canonical names another page: that one is indexed
        self._pending.extend(
            target for href in parser.pages if (target := self.local(href, base)) is not None
        )
        return page

    # links and files

    def link_outcome(self, target: str, hops: int = 0) -> str | None:
        """Why ``target`` is broken, else ``None``. Each target is requested once."""
        if target in self.outcomes:
            return self.outcomes[target]
        self.outcomes[target] = None
        response = self.get(target)
        status = response.status_code
        problem: str | None = None
        if 300 <= status < 400:
            location = str(response.get("Location") or "")
            hop = self.local(location, f"https://testserver{target}")
            if hop is not None and hops < _MAX_HOPS:
                inner = self.link_outcome(hop, hops + 1)
                problem = None if inner is None else f"redirects to {hop}, which {inner}"
            elif hop is not None:
                problem = "redirects too many times"
        elif status == 404 and self.file_bytes(target) is not None:
            problem = None
        elif status >= 400:
            problem = f"answers {status}"
        self.outcomes[target] = problem
        return problem

    def file_bytes(self, target: str) -> bytes | None:
        """The bytes of a static or media file the test client does not serve, or ``None``."""
        path = unquote(urlsplit(target).path)
        static_url = str(getattr(settings, "STATIC_URL", "") or "")
        media_url = str(getattr(settings, "MEDIA_URL", "") or "")
        if static_url.startswith("/") and path.startswith(static_url):
            from django.contrib.staticfiles import finders

            name = path[len(static_url) :]
            found = finders.find(name)
            if isinstance(found, list):
                found = found[0] if found else None
            if found:
                with open(found, "rb") as handle:
                    return handle.read()
            try:
                from django.contrib.staticfiles.storage import staticfiles_storage

                with staticfiles_storage.open(name, "rb") as handle:
                    return bytes(handle.read())
            except Exception:  # noqa: BLE001 - not collected either
                return None
        if media_url.startswith("/") and path.startswith(media_url):
            from django.core.files.storage import default_storage

            try:
                with default_storage.open(path[len(media_url) :], "rb") as handle:
                    return bytes(handle.read())
            except Exception:  # noqa: BLE001 - not in the storage
                return None
        return None

    def image_facts(self, target: str) -> tuple[tuple[int, int] | None, int]:
        """``(width and height, bytes)`` of an image of the site, ``(None, 0)`` when unknown."""
        if target in self.sizes:
            return self.sizes[target]
        data = self.file_bytes(target)
        if data is None:
            response = self.get(target)
            data = _body(response) if response.status_code == 200 else b""
        facts = (imagesize.image_size(data[: imagesize.HEADER_BYTES]) if data else None, len(data))
        self.sizes[target] = facts
        return facts

    # the checks

    def check_images(self, page: Page) -> None:
        widths = [int(w) for w in conf.get("KARNI_SITE_IMAGE_WIDTHS") or ()]
        widest = max(widths) if widths else None
        ratio = float(conf.get("KARNI_SITE_SEO_PIXEL_RATIO") or 2)
        limit = int(conf.get("KARNI_SITE_SEO_IMAGE_BYTES") or 0)
        base = f"https://testserver{page.path}"
        for img in page.imgs:
            where = f"{page.path}: <img src={img.src or '(none)'!r}> (line {img.line})"
            if img.alt is None:
                self.fail(
                    ALT_CODE,
                    f'{where} has no alt. Describe it in alt="...", or alt="" if it decorates.',
                )
            if _number(img.width) is None or _number(img.height) is None:
                self.fail(
                    SIZE_CODE,
                    f"{where} has no width and height, so the page jumps when it loads. Use "
                    "{% image %} for an upload, or write the image's pixel size.",
                )
            target = self.local(img.src, base)
            if target is None or img.src.startswith("data:"):
                continue
            declared = _number(img.width)
            described = [
                _number(part.split()[1][:-1])
                for part in (img.srcset or "").split(",")
                if len(part.split()) == 2 and part.split()[1].endswith("w")
            ]
            options = [w for w in described if w]
            if len(options) >= 2:
                if declared and min(options) > declared * ratio:
                    self.fail(
                        WEIGHT_CODE,
                        f"{where}: its smallest copy is {min(options)} pixels wide, shown "
                        f"{declared} wide. Add smaller copies to its srcset.",
                    )
                continue
            size, weight = self.image_facts(target)
            reasons: list[str] = []
            if size and declared and size[0] > declared * ratio:
                reasons.append(f"{size[0]} pixels wide, shown {declared} wide")
            elif size and widest and size[0] > widest:
                reasons.append(f"{size[0]} pixels wide with no smaller copies (srcset)")
            if limit and weight > limit:
                reasons.append(f"{weight // 1000} kB")
            if reasons:
                self.fail(
                    WEIGHT_CODE,
                    f"{where} is {' and '.join(reasons)}. Serve smaller copies: {{% image %}} "
                    "for an upload, a srcset for a design's image.",
                )

    def check_links(self, page: Page) -> None:
        base = f"https://testserver{page.path}"
        for raw in dict.fromkeys(page.links):
            target = self.local(raw, base)
            if target is None:
                continue
            problem = self.link_outcome(target)
            if problem is not None:
                self.fail(LINK_CODE, f"{page.path} links to {target}, which {problem}.")

    def check_texts(self, pages: list[Page]) -> None:
        for page in pages:
            if not page.title:
                self.fail(
                    TITLE_CODE,
                    f"{page.path} has no <title>. Give it {{% block title %}}, a row with a "
                    "title, or an entry in the admin's Page titles and descriptions.",
                )
            if not page.description:
                self.fail(
                    DESCRIPTION_CODE,
                    f'{page.path} has no <meta name="description">. Give it '
                    "{% block description %}, a row with a description, or an entry in the "
                    "admin.",
                )
            elif _placeholder(page.description):
                self.fail(
                    DESCRIPTION_CODE,
                    f"{page.path} still has the placeholder description karni make site and "
                    "karni make view write. Write one sentence about this page in its "
                    "{% block description %}, its row's description, or the admin's Page "
                    "titles and descriptions.",
                )
        indexable = [page for page in pages if page.indexable]
        for code, attribute, what in (
            (SAME_TITLE_CODE, "title", "title"),
            (SAME_DESCRIPTION_CODE, "description", "description"),
        ):
            groups: dict[str, list[str]] = {}
            for page in indexable:
                value = " ".join(str(getattr(page, attribute) or "").split())
                if value and not (attribute == "description" and _placeholder(value)):
                    groups.setdefault(value, []).append(page.path)
            for value, paths in groups.items():
                if len(paths) > 1:
                    self.fail(
                        code,
                        f"{len(paths)} pages share the {what} {value!r}: {', '.join(paths)}. "
                        f"Give each page its own {what}.",
                    )

    # the sitemap

    def sitemap_paths(self) -> set[str] | None:
        """Every path sitemap.xml lists (an index followed), or ``None`` when it does not answer."""
        from django.urls import NoReverseMatch, reverse

        try:
            start = reverse("karni_site:sitemap")
        except NoReverseMatch:
            start = "/sitemap.xml"
        found: set[str] = set()
        pending = [start]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            response = self.get(current)
            if response.status_code != 200:
                if current == start:
                    return None
                continue
            try:
                root = ElementTree.fromstring(_body(response))
            except ElementTree.ParseError:
                return None
            for loc in root.iter(f"{_SITEMAP_NS}loc"):
                path = self.local(loc.text or "", "https://testserver/")
                if path is None:
                    continue
                if root.tag == f"{_SITEMAP_NS}sitemapindex":
                    pending.append(path)
                else:
                    found.add(path)
        return found

    def check_sitemap(self, listed: set[str] | None) -> None:
        if listed is None:
            self.fail(
                SITEMAP_CODE,
                '/sitemap.xml does not answer. Add path("", include("karni_site.urls")) to '
                "config/urls.py (karni make site does).",
            )
            return
        from django.urls import Resolver404, resolve

        from karni_site.sitemaps import excluded

        for path in sorted(listed):
            page = self.pages.get(path)
            if page is None:
                continue
            if page.status != 200:
                self.fail(
                    SITEMAP_CODE,
                    f"sitemap.xml lists {path}, which answers {page.status}. List only pages "
                    "that answer 200.",
                )
            elif page.html and page.noindex:
                self.fail(
                    SITEMAP_CODE,
                    f"sitemap.xml lists {path}, which asks not to be indexed (noindex, or a "
                    "canonical link to another page).",
                )
        for path, page in self.pages.items():
            if not page.indexable or path in listed or "?" in path:
                continue
            try:
                name = resolve(urlsplit(path).path).view_name
            except Resolver404:
                name = ""
            if excluded(name, path):
                continue
            self.fail(
                SITEMAP_CODE,
                f"{path} is a page of the site that sitemap.xml leaves out. Give its row "
                "get_absolute_url() and a public filter (class Karni: sitemap), or list it in "
                "KARNI_SITE_SITEMAP_EXCLUDE when it should stay out.",
            )

    # the run

    def run(self) -> list[str]:
        with renditions.made_inline() as made:
            failures = self._run()
        self.made = list(dict.fromkeys(made))
        return failures

    def _run(self) -> list[str]:
        from karni_site.routes import site_pages

        self._pending: deque[str] = deque(["/"])
        listed = self.sitemap_paths()
        self._pending.extend(sorted(listed or ()))
        self._pending.extend(path for _, path in site_pages())
        while self._pending and len(self.pages) < self.limit:
            path = self._pending.popleft()
            if path in self.pages or self.local(path, "https://testserver/") is None:
                continue
            page = self.visit(path)
            if page.location:
                hop = self.local(page.location, f"https://testserver{path}")
                if hop is not None:
                    self._pending.append(hop)
        pages = [page for page in self.pages.values() if page.html]
        self.check_texts(pages)
        for page in pages:
            self.check_images(page)
            self.check_links(page)
        self.check_sitemap(listed)
        self.check_menus()
        return self.failures

    def check_menus(self) -> None:
        """Each shown menu item that points at a page, row or model that is gone."""
        from karni_site import menus
        from karni_site.models import MenuItem

        items = MenuItem.objects.filter(enabled=True).select_related("menu", "content_type")
        for item in items.order_by("menu__name", "order"):
            try:
                menus.target(item)
            except menus.NoTarget as exc:
                label = item.title or item.route or item.url or f"item {item.pk}"
                self.fail(
                    MENU_CODE,
                    f"menu {item.menu.name!r}, item {label!r}: {exc}, so the menu leaves it out. "
                    "Choose its page again in the admin's Menus (a renamed or replaced view, "
                    "such as detail pages that became one view), or delete the item.",
                )


class _Held(logging.Handler):
    """Keeps the errors the held-back loggers log, to count them, and prints nothing."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.errors: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a record that cannot format still counts
            message = str(record.msg)
        event = getattr(record, "msg", None)
        if isinstance(event, dict):  # a structlog event dict
            message = str(event.get("event") or message)
        self.errors.append(" ".join(message.split())[:300])


@contextmanager
def quiet_requests() -> Iterator[list[str]]:
    """Hold back the request logs of the loggers ``KARNI_SITE_SEO_QUIET`` names.

    Below ``ERROR`` nothing they log is written. Errors are kept, not
    written, in the list this yields, so the run can say how many there were.
    """
    held = _Held()
    saved: list[tuple[logging.Logger, int, bool, list[logging.Handler]]] = []
    for name in conf.get("KARNI_SITE_SEO_QUIET") or ():
        logger = logging.getLogger(str(name))
        saved.append((logger, logger.level, logger.propagate, list(logger.handlers)))
        logger.setLevel(logging.ERROR)
        logger.propagate = False
        logger.handlers = [held]
    try:
        yield held.errors
    finally:
        for logger, level, propagate, handlers in saved:
            logger.setLevel(level)
            logger.propagate = propagate
            logger.handlers = handlers


def _placeholder(description: str) -> bool:
    """Whether ``description`` is :data:`PLACEHOLDER_DESCRIPTION` (spacing aside)."""
    return " ".join(description.split()) == PLACEHOLDER_DESCRIPTION


def run_checks() -> list[str]:
    """The ``karni.checks.seo`` hook: every finding of :class:`SeoCrawl`, code first."""
    from django.apps import apps
    from django.test.utils import override_settings

    if not apps.is_installed("karni_site"):
        sys.stdout.write(
            "karni check --seo: no public site to check. karni_site is not in "
            "INSTALLED_APPS. Add it with `karni add site`.\n"
        )
        return []
    hosts = [*getattr(settings, "ALLOWED_HOSTS", []), "testserver"]
    crawl = SeoCrawl()
    with override_settings(ALLOWED_HOSTS=hosts, KARNI_DEBUG_CAPTURE=False):
        with quiet_requests() as errors:
            failures = crawl.run()
    if errors:
        sys.stdout.write(
            f"karni check --seo: the pages' requests logged {len(errors)} error(s), not "
            f"shown here, the first: {errors[0]}. The findings below name the pages: open "
            "one with `karni serve` to see the whole error.\n"
        )
    if crawl.made:
        sys.stdout.write(
            f"karni check --seo: made the smaller copies of {len(crawl.made)} upload(s) the "
            f"pages show, which had none because no Celery worker had made them yet: "
            f"{', '.join(crawl.made[:10])}{' ...' if len(crawl.made) > 10 else ''}. In "
            "production a worker makes them when an image is uploaded.\n"
        )
    return failures
