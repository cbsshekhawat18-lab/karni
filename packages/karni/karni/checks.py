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
            messages.extend(_write_only_search(viewset, model))
    return messages


def _write_only_search(viewset: type[Any], model: type[Any]) -> list[checks.CheckMessage]:
    """E131 when ``search_fields`` names a field the API never reads back."""
    write_only = frozenset(getattr(getattr(model, "APIMeta", None), "write_only", None) or ())
    offenders = sorted(
        name
        for name in (getattr(viewset, "search_fields", None) or ())
        if str(name).lstrip("^=@$").split("__", 1)[0] in write_only
    )
    if not offenders:
        return []
    return [
        check_error(
            "E131",
            f"{viewset.__name__}.search_fields names {', '.join(offenders)}, which "
            f"{model.__name__}.APIMeta.write_only keeps out of every response: searching it "
            "would reveal the hidden values by membership.",
            hint=_fix("E131"),
            obj=viewset,
        )
    ]


@checks.register(checks.Tags.models)
def check_field_roles(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E212: every ``Karni.field_roles`` entry names a real field and declared roles."""
    from karni.accounts.roles import declared_roles
    from karni.meta import field_roles

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    try:
        slugs = {spec.slug for spec in declared_roles()}
    except KarniError:
        slugs = set()  # KARNI_ROLES itself is reported by the settings validation
    for config in configs:
        for model in config.get_models():
            try:
                rules = field_roles(model)
            except KarniError as exc:
                messages.append(_as_check(exc, model))
                continue
            if not rules:
                continue
            names = {field.name for field in model._meta.get_fields()}
            for name, rule in rules.items():
                if name not in names:
                    messages.append(
                        check_error(
                            "E212",
                            f"{model.__name__}.Karni.field_roles names {name!r}, which is not a "
                            f"field of {model.__name__}.",
                            hint=_fix("E212"),
                            obj=model,
                        )
                    )
                unknown = sorted({*rule.read, *rule.write} - slugs) if slugs else []
                if unknown:
                    messages.append(
                        check_error(
                            "E212",
                            f"{model.__name__}.Karni.field_roles[{name!r}] names roles not in "
                            f"KARNI_ROLES: {', '.join(unknown)}. A role nobody holds hides the "
                            "field from everyone.",
                            hint=_fix("E212"),
                            obj=model,
                        )
                    )
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


@checks.register(checks.Tags.urls)
def check_welcome_route(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E505: the welcome page must be unreachable with ``DEBUG`` off.

    ``karni.welcome.welcome_urls()`` returns no route when ``DEBUG`` is
    false; this catches a hand-written ``path("", WelcomeView.as_view())``.
    """
    from django.conf import settings
    from django.urls import Resolver404, resolve

    if settings.DEBUG:
        return []
    try:
        match = resolve("/")
    except Resolver404:
        return []
    from karni.welcome.views import WelcomeView

    if getattr(match.func, "view_class", None) is not WelcomeView:
        return []
    return [
        check_error(
            "E505",
            "The Karni welcome page answers / while DEBUG is False: it describes the "
            "project (models, modules, status) to anyone who opens the site.",
            hint=_fix("E505"),
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


@checks.register(checks.Tags.models)
def check_role_scope_paths(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E214: every path a role's grants filter on resolves on the model it covers.

    ``own`` follows ``Karni.owner_field`` (a field or a path, e.g.
    ``workspace__members``), ``related:<key>`` follows ``Karni.scope_paths``,
    and a ``custom:<name>`` scope is called with a stand-in user. Each filter is
    built (not run) on the model's manager, which resolves every lookup. A
    custom scope that cannot be evaluated without a database is skipped.
    """
    from django.contrib.auth import get_user_model
    from django.core.exceptions import FieldError
    from django.db.models import Q

    from karni.accounts.roles import _custom_scopes, declared_roles, expand_grants, permission_keys
    from karni.meta import owner_field, scope_paths

    try:
        specs = declared_roles()
        keys = permission_keys()
    except Exception:  # noqa: BLE001 - KARNI_ROLES itself is validated elsewhere
        return []
    stand_in = _stand_in_user(get_user_model())
    messages: list[checks.CheckMessage] = []
    seen: set[tuple[type, str, str]] = set()
    for spec in specs:
        try:
            grants = expand_grants(spec, keys)
        except KarniError:
            continue  # reported by sync-roles / the settings validation
        for grant in grants:
            model = keys[grant.permission]
            marker = (model, grant.scope, grant.scope_path)
            if grant.scope == "all" or marker in seen:
                continue
            seen.add(marker)
            if grant.scope == "own":
                field = owner_field(model)
                if field is None:
                    continue
                described, scope_fn = f"owner_field {field!r}", None
                path: str | None = field
            elif grant.scope == "related":
                path = scope_paths(model).get(grant.scope_path)
                if path is None:
                    continue
                described, scope_fn = f"scope_paths[{grant.scope_path!r}] = {path!r}", None
            else:
                scope_fn = _custom_scopes.get(grant.scope_path)
                if scope_fn is None:
                    continue  # an unregistered custom scope is reported when it is used
                described, path = f"custom scope {grant.scope_path!r}", None
            try:
                condition: Q | bool = (
                    scope_fn(stand_in, model)
                    if scope_fn is not None
                    else Q(**{f"{path}__isnull": False})
                )
                if isinstance(condition, Q):
                    model._default_manager.filter(condition)
            except FieldError as exc:
                messages.append(
                    check_error(
                        "E214",
                        f"KARNI_ROLES[{spec.slug!r}] grants {grant.permission} through "
                        f"{described}, which does not resolve on {model.__name__}: {exc}",
                        hint=_fix("E214"),
                        obj=model,
                    )
                )
            except Exception:  # noqa: BLE001 - a scope that needs the database is not checkable here
                continue
    return messages


def _stand_in_user(user_model: Any) -> Any:
    """An unsaved user with a primary key, so related filters on it can be built."""
    import uuid

    from django.db import models as dj_models

    pk = user_model._meta.pk
    value: Any = uuid.uuid4() if isinstance(pk, dj_models.UUIDField) else 1
    return user_model(pk=value)


# Registered by importing the modules; each check lives with what it guards:
# lifecycle and limited resources, E986 / E987 / E988 / W980 (karni.guard_checks),
# and the typed field layer, E960-E970 / W964-W967 (karni.fields.checks).
from karni import guard_checks as _guard_checks  # noqa: E402,F401
from karni.fields import checks as _field_checks  # noqa: E402,F401
