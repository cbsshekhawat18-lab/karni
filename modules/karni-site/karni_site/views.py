"""Error pages that cannot fail: ``handler404`` and ``handler500`` for a site.

``karni make site`` sets, in config/urls.py::

    handler404 = "karni_site.views.page_not_found"
    handler500 = "karni_site.views.server_error"

Each renders the site's own page (``404.html``, ``500.html``, extending the
site's layout) with the request, so the layout's links, ``{% ifactive %}``
and the Content-Security-Policy tags work there too. Django's own 500 view
renders without the request. If that page raises while it renders (a
database that is down, a tag that fails), the next template in the list is
tried, and the last is this module's plain page, which needs nothing. A
broken error page never turns into a second error.

Override / escape hatch: ``KARNI_SITE_NOT_FOUND_TEMPLATES`` and
``KARNI_SITE_SERVER_ERROR_TEMPLATES`` list the templates tried, in order.
``template_name=`` on either view replaces the list. Or point
``handler404``/``handler500`` at your own views.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.template import TemplateDoesNotExist, loader
from django.views.decorators.csrf import requires_csrf_token

from karni_site import conf

__all__ = ["page_not_found", "render_first", "server_error"]

logger = logging.getLogger("karni_site")

#: What is sent when no template renders at all.
PLAIN_404 = "<!doctype html><title>Not found</title><h1>Not found</h1>"
PLAIN_500 = "<!doctype html><title>Server error</title><h1>Server error (500)</h1>"


def render_first(
    request: HttpRequest, names: Iterable[str], context: Mapping[str, Any]
) -> str | None:
    """The first of ``names`` that renders with the request, else ``None``.

    A template that is missing is skipped. One that raises while it renders
    is logged (logger ``karni_site``) and skipped.
    """
    for name in names:
        try:
            page = loader.get_template(name)
        except TemplateDoesNotExist:
            continue
        except Exception:  # a template that does not compile is skipped like one that fails
            logger.exception("karni_site: the error page %s does not load", name)
            continue
        try:
            return str(page.render(dict(context), request))
        except Exception:
            logger.exception("karni_site: the error page %s failed to render", name)
    return None


def _names(template_name: str | None, setting: str) -> list[str]:
    return [template_name] if template_name else [str(n) for n in conf.get(setting)]


@requires_csrf_token
def page_not_found(
    request: HttpRequest, exception: Exception | None = None, template_name: str | None = None
) -> HttpResponse:
    """``handler404``: the site's ``404.html`` with the request, or a fallback."""
    message: Any = exception.args[0] if exception is not None and exception.args else None
    reason = message if isinstance(message, str) else type(exception).__name__
    context = {"request_path": quote(request.path), "exception": reason}
    names = _names(template_name, "KARNI_SITE_NOT_FOUND_TEMPLATES")
    content = render_first(request, names, context)
    return HttpResponseNotFound(content if content is not None else PLAIN_404)


@requires_csrf_token
def server_error(request: HttpRequest, template_name: str | None = None) -> HttpResponse:
    """``handler500``: the site's ``500.html`` with the request, or a fallback."""
    context = {"request_path": quote(request.path)}
    content = render_first(
        request, _names(template_name, "KARNI_SITE_SERVER_ERROR_TEMPLATES"), context
    )
    return HttpResponseServerError(content if content is not None else PLAIN_500)
