"""The view every ``{% karni_form %}`` posts to: ``karni_site:form`` at ``forms/<name>/``.

It saves the submission through the form's viewset (:meth:`SiteForm.submit
<karni_site.forms.SiteForm.submit>`), so access, the rate limit, the
honeypot, validation and change history are the API's. Then:

* **Sent** (2xx, the honeypot's 202 too, so a script learns nothing): a
  ``303`` back to the page the form was on, with ``?sent=<form>`` and the
  form's anchor. The tag shows the success message there.
* **Not sent** (invalid, rate-limited, refused): the page the form was on is
  rendered again, by its own view, with the values and the errors next to
  each field, answered ``400``, ``429`` or ``403``. When that page cannot be
  rendered (a page that needs a POST, a page that fails), a plain page with
  the form alone is (``KARNI_SITE_FORM_PAGE_TEMPLATE``).
* **Asked for JSON** (``Accept: application/json``, what ``forms.js``
  sends): ``{"ok", "status", "message", "errors", "redirect"}`` with the
  viewset's status code.

The page is the form's ``karni-next`` field (a path on this site, which the
tag fills with the page's own path), else the ``Referer``, else ``/``.
Django's CSRF check applies to every POST, signed in or not.

Override / escape hatch: route your own view at the same name, or point the
form's ``action`` elsewhere with ``template=``. ``KARNI_SITE_FORM_SENT_PARAM``
renames the query parameter and ``KARNI_SITE_FORM_PAGE_TEMPLATE`` replaces
the plain page.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import PermissionDenied
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    QueryDict,
)
from django.template import loader
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from karni_site import conf
from karni_site.forms import NEXT_FIELD, FormState, Outcome, SiteForm, UnknownForm, resolve_form
from karni_site.forms import messages as form_messages
from karni_site.forms import states as form_states

__all__ = ["render_again", "submit", "success_url", "wants_json"]

logger = logging.getLogger("karni_site")


def wants_json(request: HttpRequest) -> bool:
    """Whether the caller asked for JSON (``forms.js``) rather than a page."""
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _safe_path(request: HttpRequest, url: str | None) -> str | None:
    """``url`` as a path on this site, or ``None`` when it points elsewhere."""
    if not url:
        return None
    if not url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return None
    parts = urlsplit(url)
    path = urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment))
    return path if path.startswith("/") and not path.startswith("//") else None


def page_of(request: HttpRequest) -> str:
    """The page the form was sent from: ``karni-next``, else the ``Referer``, else ``/``."""
    return (
        _safe_path(request, request.POST.get(NEXT_FIELD))
        or _safe_path(request, request.headers.get("Referer"))
        or "/"
    )


def success_url(request: HttpRequest, form: SiteForm) -> str:
    """The page with ``?sent=<form>`` (``KARNI_SITE_FORM_SENT_PARAM``) and its fragment."""
    parts = urlsplit(page_of(request))
    query = QueryDict(parts.query, mutable=True)
    param = conf.get("KARNI_SITE_FORM_SENT_PARAM")
    if param:
        query[param] = form.name
    return urlunsplit(("", "", parts.path, query.urlencode(), parts.fragment))


def _status(outcome: Outcome) -> int:
    if outcome.kind == "invalid":
        return 400
    if outcome.kind == "throttled":
        return 429
    if outcome.kind == "refused":
        return 403
    return outcome.status if outcome.status >= 400 else 500


def render_again(request: HttpRequest, path: str) -> HttpResponse | None:
    """The page at ``path`` rendered by its own view for this request, or ``None``.

    The request is turned into a ``GET`` of that page for the call, so the
    page's view, its ``{% ifactive %}`` and its policy tags behave as on a
    normal visit, and the tag finds the submission in ``request.karni_forms``.
    ``None`` when no view answers the path, the view is this one, it raises,
    or it does not answer ``200``.
    """
    parts = urlsplit(path)
    try:
        match = resolve(parts.path)
    except Resolver404:
        return None
    if match.func is submit or getattr(match.func, "__wrapped__", None) is submit:
        return None
    saved = {
        name: request.__dict__.get(name, _MISSING)
        for name in ("method", "path", "path_info", "GET", "resolver_match")
    }
    request.method = "GET"
    request.path = request.path_info = parts.path
    request.GET = QueryDict(parts.query)
    request.resolver_match = match
    try:
        response = match.func(request, *match.args, **match.kwargs)
        render = getattr(response, "render", None)
        if callable(render) and not getattr(response, "is_rendered", True):
            response = render()
    except (Http404, PermissionDenied):
        return None  # not a page this visitor gets: the plain page shows the form
    except Exception:
        logger.exception("karni_site: the page %s failed to render again for its form", path)
        return None
    finally:
        for name, value in saved.items():
            if value is _MISSING:
                request.__dict__.pop(name, None)
            else:
                request.__dict__[name] = value
    if getattr(response, "status_code", None) != 200 or getattr(response, "streaming", False):
        return None
    return response


_MISSING = object()


def _failure_page(request: HttpRequest, form: SiteForm, outcome: Outcome) -> HttpResponse:
    page = render_again(request, page_of(request))
    if page is None:
        template = loader.get_template(str(conf.get("KARNI_SITE_FORM_PAGE_TEMPLATE")))
        page = HttpResponse(template.render({"form_name": form.name}, request))
    page.status_code = _status(outcome)
    if outcome.retry_after:
        page["Retry-After"] = outcome.retry_after
    return page


@require_POST
def submit(request: HttpRequest, name: str) -> HttpResponse:
    """Save the form ``name`` and answer with a redirect, the page again, or JSON."""
    try:
        form = resolve_form(name)
    except UnknownForm as exc:
        raise Http404(str(exc)) from exc
    outcome = form.submit(request)
    if wants_json(request):
        texts = form_messages()
        body: dict[str, Any] = {
            "ok": outcome.ok,
            "status": outcome.kind,
            "message": str(texts[outcome.kind]),
            "errors": outcome.errors,
        }
        if outcome.ok:
            body["redirect"] = success_url(request, form)
        response = JsonResponse(body, status=outcome.status if outcome.status >= 200 else 500)
        if outcome.retry_after:
            response["Retry-After"] = outcome.retry_after
        return response
    if outcome.ok:
        return HttpResponseRedirect(success_url(request, form), status=303)
    form_states(request)[form.name] = FormState(request.POST, outcome)
    return _failure_page(request, form, outcome)
