"""A small public site for the assert_pages suite (``tests/testing/test_pages.py``).

``/`` and ``/about/`` pass every page check. Every other page fails one
check, or answers in a way a check has to handle (a redirect, a 410, plain
text, an exception). Used with ``override_settings(ROOT_URLCONF=__name__,
STATICFILES_DIRS=[STATIC_DIR])``. The stylesheet and logo are files in
``pages_static/testsite/``, found by the staticfiles finders, because the test
client serves no static files.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import path

STATIC_DIR = Path(__file__).resolve().parent / "pages_static"


def html(
    *body: str,
    title: str | None = "A page",
    description: str | None = "One page of the test site.",
) -> str:
    """A page, one element per line, so line numbers in failures are predictable."""
    lines = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">']
    if title is not None:
        lines.append(f"<title>{title}</title>")
    if description is not None:
        lines.append(f'<meta name="description" content="{description}">')
    lines += ["</head>", "<body>", *body, "</body>", "</html>"]
    return "\n".join(lines) + "\n"


def page(*body: str, **head: str | None) -> Callable[[HttpRequest], HttpResponse]:
    content = html(*body, **head)

    def view(request: HttpRequest) -> HttpResponse:
        return HttpResponse(content)

    return view


HOME = page(
    '<link rel="stylesheet" href="/static/testsite/site.css">',
    '<link rel="preconnect" href="https://fonts.example.net">',
    '<link rel="canonical" href="http://testserver/">',
    '<a href="/about/">About</a>',
    '<a href="about/">About, relative</a>',
    '<a href="http://testserver/about/#team">The team</a>',
    '<a href="/old-about/">The old about page</a>',
    '<a href="#top">Top</a>',
    '<a href="mailto:hello@example.com">Mail</a>',
    '<a href="tel:+15550100">Call</a>',
    '<a href="javascript:void(0)">Menu</a>',
    '<a href="https://example.org/partner/">A partner</a>',
    '<script src="//cdn.example.net/app.js"></script>',
    '<img src="/static/testsite/logo.svg" alt="The site\'s logo">',
    '<img src="/static/testsite/logo.svg"'
    ' srcset="/static/testsite/logo.svg 1x, /static/testsite/logo.svg 2x" alt="">',
    "<svg><title>A drawing</title></svg>",
    title="Home",
    description="The test site's home page.",
)
ABOUT = page(
    '<link rel="stylesheet" href="/static/testsite/site.css">',
    '<a href="/">Home</a>',
    title="About",
)


def gone(request: HttpRequest) -> HttpResponse:
    return HttpResponse(html("<p>Gone.</p>"), status=410)


def robots(request: HttpRequest) -> HttpResponse:
    return HttpResponse("User-agent: *\n", content_type="text/plain")


def raises(request: HttpRequest) -> HttpResponse:
    raise ValueError("the template needs a value")


urlpatterns = [
    path("", HOME, name="home"),
    path("about/", ABOUT, name="about"),
    path("old-about/", lambda request: redirect("/about/", permanent=True)),
    path("sign-in-first/", lambda request: redirect("/about/")),
    path("moved/", lambda request: redirect("/missing/")),
    path("loop/", lambda request: redirect("/loop/")),
    path("away/", lambda request: redirect("https://example.org/")),
    path("gone/", gone),
    path("robots.txt", robots),
    path("raises/", raises),
    path("no-title/", page("<p>No title.</p>", title=None)),
    path("empty-title/", page("<p>An empty title.</p>", title="  ")),
    path("svg-title/", page("<svg><title>A drawing</title></svg>", title=None)),
    path("no-description/", page("<p>No description.</p>", description=None)),
    path("empty-description/", page("<p>An empty description.</p>", description="")),
    path(
        "no-alt/",
        page(
            '<img src="/static/testsite/logo.svg" alt="">',
            '<img src="/static/testsite/logo.svg">',
            '<img src="/static/testsite/logo.svg" alt>',
        ),
    ),
    path(
        "broken/",
        page(
            '<a href="/missing/">Missing</a>',
            '<link rel="stylesheet" href="/static/testsite/missing.css">',
            '<a href="/moved/">Moved</a>',
            '<a href="/loop/">Loop</a>',
            '<a href="/missing/">Missing again</a>',
            '<a href="/away/">Away</a>',
        ),
    ),
    path(
        "media-page/",
        page(
            '<img src="/media/photos/kept.png" alt="Kept">',
            '<img src="/media/photos/lost.png" alt="Lost">',
        ),
    ),
    path(
        "elsewhere/",
        page(
            '<a href="https://www.example.com/about/">About, on the real domain</a>',
            '<a href="/admin-only/">Staff</a>',
            '<img data-src="/static/testsite/lazy.png" alt="Lazy">',
        ),
    ),
]
