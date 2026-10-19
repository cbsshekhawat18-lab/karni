"""Django system checks for Karni's model layer.

Registered from :class:`karni.apps.KarniAppConfig`, so problems surface on
boot (``runserver``, ``migrate``, ``check``) instead of at request time.
Silence one deliberately with Django's ``SILENCED_SYSTEM_CHECKS``.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from django.core.exceptions import ImproperlyConfigured

from karni.errorcodes import KarniError
from karni.errorcodes import get as registry_entry
from karni.exceptions import check_error, check_warning


@checks.register(checks.Tags.models)
def check_soft_delete_managers(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E001: a soft-delete model whose default manager shows deleted rows.

    The default manager must run the scope pipeline
    (:class:`karni.managers.ScopedManagerMixin`) without ``soft_delete``
    lifted. One way to break this is to compose another mixin before
    ``SoftDeleteModel`` (e.g. ``class X(TimestampedModel, SoftDeleteModel)``).
    The earlier mixin's plain ``objects`` and ``Meta`` then win, and deleted
    rows silently reappear in every query, relation and API response. They
    would also miss every future scope, such as ``tenant``.
    """
    from karni.managers import ScopedManagerMixin
    from karni.models import SoftDeleteModel
    from karni.scopes import SOFT_DELETE

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    errors: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if not issubclass(model, SoftDeleteModel):
                continue
            manager = model._default_manager
            if isinstance(manager, ScopedManagerMixin) and SOFT_DELETE not in manager._karni_lifted:
                continue
            errors.append(
                check_error(
                    "E001",
                    f"{model.__name__} inherits SoftDeleteModel, but its default manager "
                    f"'{manager.name}' ({type(manager).__name__}) does not apply Karni's "
                    "'soft_delete' scope, so deleted rows appear in every query, relation "
                    "and API response.",
                    hint=(
                        "Inherit karni.models.BaseModel, or list SoftDeleteModel first among "
                        "the Karni mixins, or declare objects = SoftDeleteManager() (any "
                        "manager built on karni.managers.ScopedManagerMixin) with "
                        "'class Meta(SoftDeleteModel.Meta)'."
                    ),
                    obj=model,
                )
            )
    return errors


@checks.register(checks.Tags.models)
def check_scopes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E002 / karni.W001: the scope registry and ``KARNI_SCOPES``.

    E002 reports a scope that fails to load or register, or a malformed
    ``KARNI_SCOPES``. W001 reports a registered scope that ``KARNI_SCOPES``
    leaves out, and that is therefore off. Silence W001 when that is
    deliberate.
    """
    from django.conf import settings

    from karni.scopes import SETTING, registry

    try:
        active = {scope.name for scope in registry.active()}
        registered = registry.names()
    except ImproperlyConfigured as exc:
        return [
            check_error(
                "E002",
                getattr(exc, "message", str(exc)),
                hint="Fix the scope or the KARNI_SCOPES setting the message names.",
            )
        ]
    if getattr(settings, SETTING, None) is None:
        return []
    return [
        check_warning(
            "W001",
            f"Scope {name!r} is registered but not listed in {SETTING}, so it is off "
            "and filters nothing.",
            hint=(
                f"Add {name!r} to {SETTING} (or unset {SETTING} to run every scope), or "
                "add 'karni.W001' to SILENCED_SYSTEM_CHECKS if disabling it is deliberate."
            ),
        )
        for name in registered
        if name not in active
    ]


def _fix(code: str) -> str:
    entry = registry_entry(code)
    return entry.fix if entry is not None else "See the linked page."


def _as_check(exc: KarniError, obj: Any = None) -> checks.CheckMessage:
    return check_error(exc.code, exc.message, hint=_fix(exc.code), obj=obj)


@checks.register(checks.Tags.urls)
def check_viewsets(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E101 / E1xx / W101: every routed viewset, validated at boot.

    E101 reports a routed viewset without an ``access`` declaration (it would
    deny every request). Every other declaration problem (``access``,
    pagination, budgets, cache, hints) is reported under its own code, so it
    surfaces on ``runserver`` / ``migrate`` / ``check`` instead of on the
    first request. W101 reports a hand-written serializer that adds nothing to
    the one Karni generates.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    from karni.api.access import missing_access_text, validate_access
    from karni.api.routers import DEFAULT_ROUTER_FACTORY, resolve_router
    from karni.api.viewsets import BaseViewSet

    dotted = getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY)
    try:
        import_string(dotted)
    except ImportError as exc:
        return [
            check_error(
                "E128",
                f"KARNI_API_ROUTER = {dotted!r} cannot be imported ({exc}), so no API "
                "route is served.",
                hint=_fix("E128"),
            )
        ]
    router = resolve_router()
    messages: list[checks.CheckMessage] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(router, "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        if getattr(viewset, "access", None) is None:
            messages.append(
                check_error(
                    "E101",
                    missing_access_text(viewset),
                    hint=_fix("E101"),
                    obj=viewset,
                )
            )
            continue
        model = viewset.model or getattr(viewset.queryset, "model", None)
        try:
            validate_access(viewset, model)
        except KarniError as exc:
            messages.append(_as_check(exc, viewset))
        if model is not None:
            messages.extend(_duplicate_serializer(viewset, model))
    return messages


def _duplicate_serializer(viewset: type[Any], model: type[Any]) -> list[checks.CheckMessage]:
    """W101 when ``serializer_class`` is a plain ModelSerializer copy of the model."""
    from rest_framework import serializers

    declared = viewset.__dict__.get("serializer_class")
    if not (isinstance(declared, type) and issubclass(declared, serializers.ModelSerializer)):
        return []
    if declared.__module__.startswith("karni."):
        return []
    meta = getattr(declared, "Meta", None)
    if getattr(meta, "model", None) is not model:
        return []
    own = [
        name
        for klass in declared.__mro__
        if not klass.__module__.startswith(("rest_framework", "karni.", "builtins"))
        for name, value in vars(klass).items()
        if name != "Meta" and not name.startswith("__") and callable(value)
    ]
    if getattr(declared, "_declared_fields", None) or own:
        return []
    return [
        check_warning(
            "W101",
            f"{declared.__name__} duplicates the serializer Karni generates from "
            f"{model.__name__}: it declares no fields or methods of its own.",
            hint=(
                f"Delete it and the serializer_class line on {viewset.__name__}; tune the "
                f"generated serializer with APIMeta on {model.__name__}. Keep "
                "serializer_class only for custom fields or validation."
            ),
            obj=viewset,
        )
    ]


@checks.register(checks.Tags.admin)
def check_admin_scope(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E210: an admin that opts out of row scope must say why.

    Viewsets are validated at class definition (``validate_access``); admin
    classes are only instantiated at registration, so they are checked here.
    """
    from karni.admin.base import KarniAdminMixin
    from karni.scoping import admin_site

    messages: list[checks.CheckMessage] = []
    for model, model_admin in admin_site()._registry.items():
        if not isinstance(model_admin, KarniAdminMixin) or not model_admin.scope_exempt:
            continue
        reason = getattr(model_admin, "scope_exempt_reason", "")
        if isinstance(reason, str) and reason.strip():
            continue
        messages.append(
            check_error(
                "E210",
                f"{type(model_admin).__name__} ({model._meta.label_lower}) sets scope_exempt = "
                "True "
                "without a scope_exempt_reason.",
                hint=_fix("E210"),
                obj=type(model_admin),
            )
        )
    return messages


@checks.register(checks.Tags.caches)
def check_throttle_cache(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W501: with DEBUG off, throttle counters must live in a cache every worker shares.

    DRF keeps its rate-limit counters in the ``default`` cache. A per-process
    backend (locmem, dummy) multiplies every limit by the number of workers,
    so a login throttle of 10/min becomes 10/min *per worker*.
    """
    from django.conf import settings

    if settings.DEBUG:
        return []
    backend = str((getattr(settings, "CACHES", None) or {}).get("default", {}).get("BACKEND", ""))
    if backend.endswith((".LocMemCache", ".DummyCache")):
        return [
            check_warning(
                "W501",
                f"CACHES['default'] is {backend}, which is private to each process: the "
                "auth throttles (login, register, password reset) are enforced per worker, "
                "not per client.",
                hint="Use a backend every worker shares (Redis, the database cache) in "
                "production, or silence karni.W501 for a single-process deployment.",
                obj=backend,
            )
        ]
    return []


@checks.register()
def check_schedules(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E404 / E405 / E406: every ``<app>/schedules.py`` declaration, at boot.

    Declarations raise when imported; importing them here reports the problem
    when the web process starts, not only when beat does.
    """
    from karni.schedule import ScheduleError, discover

    try:
        discover()
    except ScheduleError as exc:
        return [_as_check(exc)]
    return []
