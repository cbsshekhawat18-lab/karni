"""Zero-boilerplate Django admin: no project ever writes ``admin.py`` again.

At startup (``KarniAdminConfig.ready``), :func:`autodiscover` walks every
concrete model, skips the ones that are already registered or excluded, and
registers a derived admin class built from :class:`karni.admin.base.KarniModelAdmin`
(a django-unfold ``ModelAdmin`` by default). A model with zero admin code
appears fully configured: sensible ``list_display``, filters, search, date
hierarchy, read-only audit fields, N+1-free changelists, autocomplete widgets
and — for :class:`karni.models.SoftDeleteModel` subclasses — soft-delete-aware
views and actions.

Override / escape hatches, weakest to strongest:

* settings: ``KARNI_ADMIN_AUTODISCOVER`` (bool, default True),
  ``KARNI_ADMIN_EXCLUDE`` (app labels or ``"app_label.ModelName"`` strings),
  ``KARNI_ADMIN_LIST_DISPLAY_MAX`` / ``KARNI_ADMIN_LIST_FILTER_MAX`` /
  ``KARNI_ADMIN_SEARCH_MAX`` (derivation caps), ``KARNI_ADMIN_SITE`` (dotted
  path to the target site) and ``KARNI_ADMIN_BASE`` (dotted path to the class
  ``KarniModelAdmin`` extends, default ``"unfold.admin.ModelAdmin"``).
* per model: an inner ``class AdminMeta`` (mirrors ``APIMeta``) with any of
  ``exclude``, ``register``, ``list_display``, ``list_filter``,
  ``search_fields``, ``read_only``, ``date_hierarchy``, ``ordering``,
  ``inline_on`` and the catch-all ``extra`` dict of ``ModelAdmin`` attributes.
* per project: register the model yourself in an ``admin.py`` — autodiscover
  never touches an already-registered model — or subclass ``KarniModelAdmin``
  and override its ``derive_*`` hooks.

Known v0.1 scope limits (documented, not bugs): third-party apps that
self-register (celery beat/results, the JWT token blacklist, ``auth.Group``)
keep their stock, non-unfold admins — a re-registration pass is future work;
``RelatedOnlyFieldListFilter`` entries cost one DISTINCT subquery per FK on
the changelist; and every ``BaseModel`` without another date field gets a
``created_at`` date-hierarchy drilldown.

This module imports neither Django models nor django-unfold at import time
(it is imported while the app registry is still populating); the re-exported
classes are provided lazily via module ``__getattr__``.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.admin.sites import AdminSite
    from django.db import models

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ADMIN_EXCLUDE",
    "KarniAdminMixin",
    "KarniModelAdmin",
    "SoftDeleteAdminMixin",
    "SoftDeleteListFilter",
    "autodiscover",
]

DEFAULT_ADMIN_EXCLUDE: tuple[str, ...] = (
    "sessions",
    "contenttypes",
    "admin",
    "auth.Permission",
    "django_celery_results.ChordCounter",
)
"""Fallback for the ``KARNI_ADMIN_EXCLUDE`` setting (kept in sync with
``karni.conf.base``). Override / escape hatch: set ``KARNI_ADMIN_EXCLUDE`` in
``settings.py`` or the environment (comma-separated)."""

_LAZY_IMPORTS: dict[str, str] = {
    "KarniAdminMixin": "karni.admin.base",
    "KarniModelAdmin": "karni.admin.base",
    "SoftDeleteAdminMixin": "karni.admin.soft_delete",
    "SoftDeleteListFilter": "karni.admin.soft_delete",
}


def __getattr__(name: str) -> Any:
    """Lazily resolve the re-exported admin classes.

    Keeps this package importable at app-populate time: neither Django models
    nor the ``KARNI_ADMIN_BASE`` class (django-unfold by default) are imported
    until an attribute is actually used.
    """
    module_path = _LAZY_IMPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    """Include the lazily provided names in ``dir(karni.admin)``."""
    return sorted({*globals(), *_LAZY_IMPORTS})


def _is_excluded(model: type[models.Model], exclude: frozenset[str]) -> bool:
    """Whether ``KARNI_ADMIN_EXCLUDE`` or the model's ``AdminMeta`` skips it.

    Matches the model's ``app_label`` and its ``app_label.ModelName`` label
    (case-insensitively for the latter). ``AdminMeta.exclude = True`` skips a
    single model; ``AbstractBaseUser`` subclasses are skipped unless their
    ``AdminMeta`` sets ``register = True`` (the default Karni user is
    registered explicitly by ``karni.accounts.admin`` instead).
    """
    from django.contrib.auth.base_user import AbstractBaseUser

    from karni.admin.derive import admin_meta

    opts = model._meta
    lowered = {entry.lower() for entry in exclude}
    if opts.app_label in exclude or opts.label in exclude or opts.label_lower in lowered:
        return True
    meta = admin_meta(model)
    if bool(getattr(meta, "exclude", False)):
        return True
    if issubclass(model, AbstractBaseUser) and not bool(getattr(meta, "register", False)):
        return True
    return False


def autodiscover(site: AdminSite | None = None) -> None:
    """Register a derived admin for every unregistered, non-excluded model.

    ``site`` defaults to the ``KARNI_ADMIN_SITE`` setting resolved once per
    call (``"django.contrib.admin.site"`` unless overridden); the
    registered-check, the registrations and the autocomplete second pass all
    use that one site object. Idempotent: models already registered on the
    site — by a project ``admin.py``, a third-party app or a previous call —
    are left untouched, so calling it twice never raises ``AlreadyRegistered``.

    The second pass assigns ``autocomplete_fields`` on the admins *this*
    function created (never on explicit registrations), and only for relations
    whose target model is registered on the same site with non-empty
    ``search_fields`` at fixup time — anything else keeps Django's default
    widget rather than failing ``admin.E039``/``admin.E040`` checks.

    Override / escape hatch: pass your own ``site``, set
    ``KARNI_ADMIN_AUTODISCOVER = False`` and call this manually, or steer
    individual models via ``KARNI_ADMIN_EXCLUDE`` / ``AdminMeta``.
    """
    from django.apps import apps as django_apps
    from django.conf import settings
    from django.utils.module_loading import import_string

    from karni.admin.base import build_model_admin
    from karni.admin.derive import derive_autocomplete_fields
    from karni.admin.inlines import build_inline, collect_inlines

    if site is None:
        site_path: str = getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
        site = import_string(site_path)

    exclude = frozenset(getattr(settings, "KARNI_ADMIN_EXCLUDE", DEFAULT_ADMIN_EXCLUDE))
    all_models = django_apps.get_models()
    inline_map = collect_inlines(all_models)

    for model in all_models:
        if site.is_registered(model):
            # Explicit registrations (project admin.py, third-party apps,
            # earlier autodiscover calls) always win; log the skip so a
            # surprising "why is my model not a Karni admin" is one DEBUG
            # log-level away from its answer.
            logger.debug(
                "autodiscover: %s is already registered on site %r; skipping.",
                model._meta.label,
                site.name,
            )
            continue
        if _is_excluded(model, exclude):
            continue
        inlines = [build_inline(child, fk_name) for child, fk_name in inline_map.get(model, [])]
        site.register(model, build_model_admin(model, inlines=inlines))

    # Second pass: with every registration done, targets are known, so the
    # karni-created admins can safely point FK/M2M fields at autocomplete
    # endpoints. Recomputed from scratch on every call (idempotent).
    for model, model_admin in list(site._registry.items()):
        if not getattr(model_admin, "_karni_generated", False):
            continue
        if not getattr(model_admin, "_karni_autocomplete_managed", False):
            continue
        type(model_admin).autocomplete_fields = derive_autocomplete_fields(model, site)
