"""``karni_site.middleware.RedirectMiddleware``: the redirects a client manages in the admin.

By default it looks a request up only when the site answered 404, so a
page that exists is never redirected and costs nothing. With
``KARNI_SITE_REDIRECTS_BEFORE_VIEWS = True`` every request is looked up
before the view runs (one cache read each), so a redirect also replaces a
page that still exists.

It also closes the site to search engines while indexing is not allowed
(:func:`karni_site.seo_views.indexing_allowed`): every response gets
``X-Robots-Tag: noindex, nofollow`` (``KARNI_SITE_ROBOTS_TAG``), unless the
view set the header itself. robots.txt alone can be rewritten on the way.

``karni make site`` (and ``karni add site``) put it in the
``# karni:middleware`` block of config/settings.py. ``karni check``
reports it missing (``SITE005``).

Override / escape hatch: the settings above, or subclass and override
:meth:`RedirectMiddleware.redirect` or :meth:`RedirectMiddleware.robots`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponseBase

from karni_site import conf
from karni_site.redirects import redirect_for
from karni_site.seo_views import ROBOTS_HEADER, robots_tag

__all__ = ["RedirectMiddleware"]


class RedirectMiddleware:
    """Answers a request with the admin's redirect for its address, if there is one.

    While search engines may not index the site, it adds ``X-Robots-Tag`` to every response.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def redirect(self, request: HttpRequest) -> HttpResponseBase | None:
        return redirect_for(request)

    def robots(self, request: HttpRequest, response: HttpResponseBase) -> HttpResponseBase:
        """``response`` with the closed site's ``X-Robots-Tag``, unless it has its own."""
        directives = robots_tag()
        if directives and ROBOTS_HEADER not in response:
            response[ROBOTS_HEADER] = directives
        return response

    def __call__(self, request: HttpRequest) -> Any:
        before = bool(conf.get("KARNI_SITE_REDIRECTS_BEFORE_VIEWS"))
        if before:
            found = self.redirect(request)
            if found is not None:
                return self.robots(request, found)
        response = self.get_response(request)
        if not before and response.status_code == 404:
            found = self.redirect(request)
            if found is not None:
                return self.robots(request, found)
        return self.robots(request, response)
