"""sitemap.xml: the site's pages and the rows that have pages of their own.

:func:`sitemaps` (``KARNI_SITE_SITEMAPS``'s default) returns the sections
``/sitemap.xml`` lists, as Django sitemaps (``django.contrib.sitemaps``,
which needs nothing in ``INSTALLED_APPS`` here):

* ``pages``: every named URL that takes no argument, as
  :func:`karni_site.routes.site_pages` lists them (never the admin's, the
  API's, the static files' or the health checks'), less the redirects
  (``RedirectView``), karni_site's own addresses, the pages hidden from
  search engines in the admin (*Page titles and descriptions*, ``noindex``)
  and what ``KARNI_SITE_SITEMAP_EXCLUDE`` names;
* one section per model whose rows have a page (``get_absolute_url``),
  unless its ``class Karni: sitemap = False``. Rows come from the default
  manager, so scopes apply and soft-deleted rows stay out. A model's
  ``class Karni: sitemap = {"filter": {...}}`` chooses the public rows.
  Without one, the first boolean field ``KARNI_SITE_PUBLISHED_FIELDS``
  names (``published``, ``is_public``...) must be true, a ``status`` with a
  ``published`` choice must be it, and a ``published_at`` must have passed.

``class Karni: sitemap`` takes ``True``, ``False`` or a dict of
``filter`` and ``exclude`` (lookups), ``lastmod`` (a field, default
``updated_at`` when the model has it), ``changefreq`` and ``priority``.

Addresses are absolute: on ``KARNI_SITE_URL`` when it is set, else on the
request's host. One request reads each section's rows once (a section keeps
its paginator) and the admin's hidden pages once for every section.

Override / escape hatch: ``KARNI_SITE_SITEMAP_EXCLUDE``,
``KARNI_SITE_PUBLISHED_FIELDS``, ``class Karni: sitemap``, or
``KARNI_SITE_SITEMAPS`` naming your own ``() -> {name: Sitemap}`` function
(which can call this one and add to it).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit

from django.contrib.sitemaps import Sitemap
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import Paginator
from django.db import models
from django.urls import Resolver404, resolve
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic.base import RedirectView
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import karni_option

from karni_site import conf

__all__ = [
    "HiddenPages",
    "ModelSitemap",
    "PagesSitemap",
    "SiteSitemap",
    "excluded",
    "model_spec",
    "public_rows",
    "sitemaps",
]

DECLARATION_CODE = "SITE019"
_SPEC_KEYS = frozenset({"filter", "exclude", "lastmod", "changefreq", "priority"})
_OWN_NAMESPACES = ("karni_site:", "admin:", "karni:")


class HiddenPages:
    """The pages the admin hides from search engines, read once for every section that asks."""

    def __init__(self) -> None:
        self._found: tuple[set[str], set[str]] | None = None

    def get(self) -> tuple[set[str], set[str]]:
        """``(URL names, paths)``: :func:`_hidden`, the first time only."""
        if self._found is None:
            self._found = _hidden()
        return self._found


class SiteSitemap(Sitemap):
    """A sitemap section whose addresses are on ``KARNI_SITE_URL`` when it is set.

    It keeps its paginator, so the rows are counted and read once however
    often the view asks how many pages the section has. Django's own builds a
    new one, and queries again, each time.
    """

    @cached_property
    def paginator(self) -> Paginator:  # type: ignore[override]
        return Paginator(self._items(), self.limit)

    def _configured(self) -> Any:
        url = conf.get("KARNI_SITE_URL")
        return urlsplit(str(url)) if url else None

    def get_protocol(self, protocol: str | None = None) -> str:
        configured = self._configured()
        return str(configured.scheme) if configured else str(super().get_protocol(protocol))

    def get_domain(self, site: Any = None) -> str:
        configured = self._configured()
        if configured:
            return str(configured.netloc) + configured.path.rstrip("/")
        return str(super().get_domain(site))


def excluded(name: str, path: str) -> bool:
    """Whether ``KARNI_SITE_SITEMAP_EXCLUDE`` names this URL name or path."""
    patterns = [str(p) for p in conf.get("KARNI_SITE_SITEMAP_EXCLUDE") or ()]
    return any(fnmatchcase(name, p) or fnmatchcase(path, p) for p in patterns)


def _is_redirect(path: str) -> bool:
    try:
        match = resolve(path)
    except Resolver404:
        return True
    view_class = getattr(match.func, "view_class", None)
    return isinstance(view_class, type) and issubclass(view_class, RedirectView)


def _hidden() -> tuple[set[str], set[str]]:
    """URL names and paths the admin hides from search engines (``noindex``)."""
    from karni_site.models import PageSeo

    routes: set[str] = set()
    paths: set[str] = set()
    for route, path in PageSeo.objects.filter(noindex=True).values_list("route", "path"):
        if route:
            routes.add(route)
        if path:
            paths.add(path)
    return routes, paths


class PagesSitemap(SiteSitemap):
    """The site's own pages: named URLs without arguments."""

    def __init__(self, hidden: HiddenPages | None = None) -> None:
        self.hidden = hidden or HiddenPages()

    def items(self) -> list[str]:
        from karni_site.routes import site_pages

        hidden_routes, hidden_paths = self.hidden.get()
        found: list[str] = []
        for name, path in site_pages():
            if name.startswith(_OWN_NAMESPACES) or path in found:
                continue
            if name in hidden_routes or path in hidden_paths or excluded(name, path):
                continue
            if _is_redirect(path):
                continue
            found.append(path)
        return found

    def location(self, item: str) -> str:
        return item


def model_spec(model: type[models.Model]) -> dict[str, Any] | None:
    """What ``class Karni: sitemap`` says for ``model``, or ``None`` when it is left out."""
    declared = karni_option(model, "sitemap")
    if declared is False:
        return None
    if declared is None or declared is True:
        return {} if hasattr(model, "get_absolute_url") else None
    if not isinstance(declared, Mapping) or set(declared) - _SPEC_KEYS:
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.sitemap is {declared!r}. It is True, False or a dict of "
            f"{', '.join(sorted(_SPEC_KEYS))}: "
            'sitemap = {"filter": {"published": True}, "lastmod": "updated_at"}.',
            code=DECLARATION_CODE,
        )
    if not hasattr(model, "get_absolute_url"):
        raise KarniImproperlyConfigured(
            f"{model.__name__}.Karni.sitemap lists its rows, but {model.__name__} has no "
            "get_absolute_url(), so a row has no address. Add the method, or remove sitemap.",
            code=DECLARATION_CODE,
        )
    return dict(declared)


def _field(model: type[models.Model], name: str) -> Any | None:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def public_rows(model: type[models.Model], spec: Mapping[str, Any]) -> models.QuerySet[Any]:
    """The rows of ``model`` the sitemap lists (the default manager, then the filters)."""
    rows = model._default_manager.all()
    if "filter" in spec:
        rows = rows.filter(**dict(spec["filter"] or {}))
    else:
        for name in conf.get("KARNI_SITE_PUBLISHED_FIELDS") or ():
            if isinstance(_field(model, str(name)), models.BooleanField):
                rows = rows.filter(**{str(name): True})
                break
        status = _field(model, "status")
        choices = {str(value) for value, _ in getattr(status, "flatchoices", None) or ()}
        if status is not None and "published" in choices:
            rows = rows.filter(status="published")
        for name in ("published_at", "publish_at", "published_on"):
            found = _field(model, name)
            if isinstance(found, models.DateField):
                now = (
                    timezone.now()
                    if isinstance(found, models.DateTimeField)
                    else timezone.localdate()
                )
                rows = rows.filter(**{f"{name}__isnull": False, f"{name}__lte": now})
                break
    if spec.get("exclude"):
        rows = rows.exclude(**dict(spec["exclude"]))
    if not rows.ordered:
        rows = rows.order_by("pk")
    return rows


def _hidden_row(row: Any, routes: set[str], paths: set[str]) -> bool:
    """Whether the admin hides this row's page from search engines (by path or URL name)."""
    location = str(row.get_absolute_url())
    if location in paths:
        return True
    try:
        return bool(routes) and resolve(location).view_name in routes
    except Resolver404:
        return False


class ModelSitemap(SiteSitemap):
    """The rows of one model that have a page of their own."""

    def __init__(
        self,
        model: type[models.Model],
        spec: Mapping[str, Any],
        hidden: HiddenPages | None = None,
    ) -> None:
        self.model = model
        self.spec = dict(spec)
        self.hidden = hidden or HiddenPages()
        self.changefreq = self.spec.get("changefreq")
        self.priority = self.spec.get("priority")
        self._lastmod = self.spec.get("lastmod") or (
            "updated_at" if _field(model, "updated_at") is not None else None
        )

    def items(self) -> Any:
        rows = public_rows(self.model, self.spec)
        hidden_routes, hidden_paths = self.hidden.get()
        if not hidden_routes and not hidden_paths:
            return rows
        return [row for row in rows if not _hidden_row(row, hidden_routes, hidden_paths)]

    def location(self, item: Any) -> str:
        return str(item.get_absolute_url())

    def lastmod(self, item: Any) -> Any:
        return getattr(item, self._lastmod, None) if self._lastmod else None


def _section(model: type[models.Model]) -> str:
    return f"{model._meta.app_label}-{model._meta.model_name}"


def model_sitemaps(
    models_: Iterable[type[models.Model]] | None = None, hidden: HiddenPages | None = None
) -> dict[str, Sitemap]:
    """One section per model whose rows have pages, ``app_label-model`` by name."""
    from karni_site.routes import linkable_models

    shared = hidden or HiddenPages()
    found: dict[str, Sitemap] = {}
    for model in models_ if models_ is not None else linkable_models():
        spec = model_spec(model)
        if spec is not None:
            found[_section(model)] = ModelSitemap(model, spec, shared)
    return found


def sitemaps() -> dict[str, Sitemap]:
    """``KARNI_SITE_SITEMAPS``'s default: the site's pages, then each model's rows."""
    hidden = HiddenPages()
    return {"pages": PagesSitemap(hidden), **model_sitemaps(hidden=hidden)}
