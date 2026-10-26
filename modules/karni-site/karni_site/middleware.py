"""``karni_site.middleware.RedirectMiddleware``: the redirects a client manages in the admin.

By default it looks a request up only when the site answered 404, so a
page that exists is never redirected and costs nothing. With
``KARNI_SITE_REDIRECTS_BEFORE_VIEWS = True`` every request is looked up
before the view runs (one cache read each), so a redirect also replaces a
page that still exists.

``karni make site`` (and ``karni add site``) put it in the
``# karni:middleware`` block of config/settings.py. ``karni check``
reports it missing (``SITE005``).

Override / escape hatch: the setting above, or subclass and override
:meth:`RedirectMiddleware.redirect`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponseBase

from karni_site import conf
from karni_site.redirects import redirect_for

__all__ = ["RedirectMiddleware"]


class RedirectMiddleware:
    """Answers a request with the admin's redirect for its address, if there is one."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def redirect(self, request: HttpRequest) -> HttpResponseBase | None:
        return redirect_for(request)

    def __call__(self, request: HttpRequest) -> Any:
        before = bool(conf.get("KARNI_SITE_REDIRECTS_BEFORE_VIEWS"))
        if before:
            found = self.redirect(request)
            if found is not None:
                return found
        response = self.get_response(request)
        if not before and response.status_code == 404:
            found = self.redirect(request)
            if found is not None:
                return found
        return response
