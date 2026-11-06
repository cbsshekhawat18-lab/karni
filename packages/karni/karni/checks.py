"""Django system checks for Karni's model layer.

Registered from :class:`karni.apps.KarniAppConfig`, so problems surface on
boot (``runserver``, ``migrate``, ``check``) instead of at request time.
Silence one deliberately with Django's ``SILENCED_SYSTEM_CHECKS``
(``karni_settings()`` starts it as an empty list, so ``+=`` works).
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


@checks.register(checks.Tags.urls, checks.Tags.caches)
def check_api_cache(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E410: a cached viewset reads a model no write Karni sees can invalidate.

    Runs while ``KARNI_API_CACHE`` is on. A model that is external, unmanaged
    or on another database is written by someone else, so its rows change
    without a signal and a cached response that read them stays stale until
    its TTL ends. ``Cache(ttl=...)`` on the viewset accepts that bound, and
    ``Uncached(reason=...)`` opts the viewset out.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    from karni.api.caching import Cache, Uncached, cache_enabled, cannot_invalidate, dependencies
    from karni.api.routers import DEFAULT_ROUTER_FACTORY, resolve_router
    from karni.api.viewsets import BaseViewSet

    if not cache_enabled():
        return []
    try:
        import_string(getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY))
    except ImportError:
        return []  # check_viewsets reports it (E128)
    messages: list[checks.CheckMessage] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        declared = getattr(viewset, "cache", None)
        if isinstance(declared, Uncached) or (isinstance(declared, Cache) and declared.ttl):
            continue
        found = [
            f"{model._meta.label} ({why})"
            for model in sorted(dependencies(viewset), key=lambda m: m._meta.label)
            if (why := cannot_invalidate(model)) is not None
        ]
        if found:
            messages.append(
                check_error(
                    "E410",
                    f"{viewset.__name__} is cached, but it reads {', '.join(found)}. Karni "
                    "sees no write to such a model, so a cached response would stay stale "
                    "for the whole KARNI_API_CACHE_TTL.",
                    hint=_fix("E410"),
                    obj=viewset,
                )
            )
    return messages


@checks.register(checks.Tags.caches)
def check_api_cache_backend(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W580: with DEBUG off, cached responses must live in a cache every process shares."""
    from django.conf import settings

    from karni.api.caching import cache_alias, cache_enabled

    if settings.DEBUG or not cache_enabled():
        return []
    alias = cache_alias()
    backend = str((getattr(settings, "CACHES", None) or {}).get(alias, {}).get("BACKEND", ""))
    if not backend.endswith(".LocMemCache"):
        return []
    return [
        check_warning(
            "W580",
            f"KARNI_API_CACHE is on and CACHES[{alias!r}] is {backend}, which is private to "
            "each process: a write handled by one worker does not reach the responses another "
            "worker has cached.",
            hint=_fix("W580"),
            obj=backend,
        )
    ]


@checks.register(checks.Tags.urls)
def check_open_writes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W102: a routed viewset any self-registered user may write to, every row.

    Reported while ``KARNI_ACCOUNTS_REGISTRATION`` is true for every routed
    :class:`~karni.api.viewsets.BaseViewSet` whose ``write`` predicate
    :func:`~karni.api.access.admits_every_user`: ``Authenticated()`` or
    ``Public()``, not narrowed with ``&`` by ``HasRole``, ``Granted``,
    ``Owned`` or ``Can``. ``create`` is not inspected: ``create=Authenticated()``
    with an ``Owned()`` write is the user-generated-content pattern. A viewset
    that does not resolve (E101, E128) is reported by :func:`check_viewsets`.
    Only the declared ``access`` attribute is read: a ``get_access()`` override
    computes its declaration per request, so it is not inspected. Silence it
    with ``'karni.W102'`` in ``SILENCED_SYSTEM_CHECKS`` when every signed-in
    user is trusted.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    from karni.api.access import Access, admits_every_user
    from karni.api.routers import DEFAULT_ROUTER_FACTORY, resolve_router
    from karni.api.viewsets import BaseViewSet

    if not getattr(settings, "KARNI_ACCOUNTS_REGISTRATION", True):
        return []
    try:
        import_string(getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY))
    except ImportError:
        return []
    messages: list[checks.CheckMessage] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        declaration = getattr(viewset, "access", None)
        if not isinstance(declaration, Access) or not admits_every_user(declaration.write):
            continue
        model = viewset.model or getattr(viewset.queryset, "model", None)
        rows = model.__name__ if model is not None else "row"
        messages.append(
            check_warning(
                "W102",
                f"{viewset.__name__} lets any self-registered user change and delete every "
                f"{rows} (write={declaration.write!r} while KARNI_ACCOUNTS_REGISTRATION is "
                "True).",
                hint=_fix("W102"),
                obj=viewset,
            )
        )
    return messages


#: The opt-out marker of ``karni.W530``: ``# karni: allow(public-integer-key): <reason>``.
PUBLIC_INTEGER_KEY_RULE = "public-integer-key"


def has_integer_key(model: type[Any]) -> bool:
    """Whether ``model``'s primary key is an integer (an ``AutoField`` or ``IntegerField``)."""
    from django.db import models

    pk = model._meta.pk
    if isinstance(pk, models.OneToOneField) and pk.related_model is not None:
        return has_integer_key(pk.related_model)
    return isinstance(pk, models.AutoField | models.IntegerField)


def _key_marker(viewset: type[Any]) -> tuple[bool, str]:
    """``(silenced, note)`` from a ``public-integer-key`` marker above the viewset class."""
    from karni.testing._source import class_marker_lines, find_allow

    marked = class_marker_lines(viewset)
    if marked is None:
        return False, ""
    allow = find_allow(marked[0], PUBLIC_INTEGER_KEY_RULE, marked[1])
    if allow is None:
        return False, ""
    if allow.reason:
        return True, ""
    return False, (
        f" The marker on line {allow.line} has no reason, so it does not silence this: "
        f"write `# karni: allow({PUBLIC_INTEGER_KEY_RULE}): <why the ids may be public>`."
    )


@checks.register(checks.Tags.urls)
def check_public_integer_keys(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W530 (experimental): anyone may read a resource whose ids can be guessed.

    Reported for every routed :class:`~karni.api.viewsets.BaseViewSet`
    whose model has an integer primary key (``BigIntBaseModel``, an
    ``AutoField``), whose detail route looks rows up by that key, and whose
    ``read`` predicate admits anonymous callers
    (:func:`~karni.api.access.admits_anyone`). Integer ids are sequential, so
    a visitor can count the rows and walk the detail URLs. Only the declared
    ``access`` attribute is read (a ``get_access()`` override is computed
    per request), and ``Unscoped`` is not inspected. Silence it for one
    viewset with ``# karni: allow(public-integer-key): <reason>`` above the
    class, or for the project with ``'karni.W530'`` in
    ``SILENCED_SYSTEM_CHECKS``.
    """
    from django.conf import settings
    from django.utils.module_loading import import_string

    from karni.api.access import Access, admits_anyone
    from karni.api.routers import DEFAULT_ROUTER_FACTORY, resolve_router
    from karni.api.viewsets import BaseViewSet

    try:
        import_string(getattr(settings, "KARNI_API_ROUTER", DEFAULT_ROUTER_FACTORY))
    except ImportError:
        return []
    messages: list[checks.CheckMessage] = []
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        declaration = getattr(viewset, "access", None)
        if not isinstance(declaration, Access) or not admits_anyone(declaration.read):
            continue
        model = viewset.model or getattr(viewset.queryset, "model", None)
        if model is None or not has_integer_key(model):
            continue
        lookup = str(getattr(viewset, "lookup_field", "pk") or "pk")
        if lookup not in ("pk", model._meta.pk.name, model._meta.pk.attname):
            continue
        silenced, note = _key_marker(viewset)
        if silenced:
            continue
        messages.append(
            check_warning(
                "W530",
                f"{viewset.__name__} lets anyone read {model.__name__} rows by an integer id "
                f"(read={declaration.read!r}), so a visitor can count them and walk "
                f"/{_prefix}/1/, /{_prefix}/2/, ...{note}",
                hint=_fix("W530"),
                obj=viewset,
            )
        )
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
                f"Delete it and the serializer_class line on {viewset.__name__}. Tune the "
                f"generated serializer with APIMeta on {model.__name__}. Keep "
                "serializer_class only for custom fields or validation."
            ),
            obj=viewset,
        )
    ]


@checks.register(checks.Tags.models)
def check_dashboards(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E133: every ``Karni.dashboard`` declaration names real fields and values."""
    from karni.dashboard import dashboard_spec

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            try:
                dashboard_spec(model)
            except KarniError as exc:
                messages.append(_as_check(exc, model))
    return messages


@checks.register(checks.Tags.models)
def check_global_search(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E430: every ``Karni.search`` declaration names text fields and a real title."""
    from karni.global_search import search_declaration

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            try:
                search_declaration(model)
            except KarniError as exc:
                messages.append(_as_check(exc, model))
    return messages


@checks.register(checks.Tags.urls)
def check_global_search_routes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W591: a model declares ``Karni.search`` but no routed ``BaseViewSet`` serves it.

    Search reaches a model through its list endpoint (the access) and links
    each hit to its resource, so such a model never appears in it.
    """
    from karni.api.global_search import search_targets
    from karni.global_search import search_declaration, searchable_models

    try:
        served = {target.model for target in search_targets()}
    except Exception:  # noqa: BLE001 - router problems are karni.E128's to report
        return []
    labels = {config.label for config in app_configs} if app_configs is not None else None
    messages: list[checks.CheckMessage] = []
    for model in searchable_models():
        if model in served or (labels is not None and model._meta.app_label not in labels):
            continue
        try:
            if search_declaration(model) is None:
                continue
        except KarniError:
            continue  # E430's to report
        messages.append(
            check_warning(
                "W591",
                f"{model.__name__} declares Karni.search, but no routed BaseViewSet serves it, "
                "so cross-model search never finds it: search reads a model through its list "
                "endpoint and links each hit to it.",
                hint=_fix("W591"),
                obj=model,
            )
        )
    return messages


@checks.register(checks.Tags.urls)
def check_aggregations(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E380 / W570 / E280: every aggregation declaration (experimental) fits its model.

    A model's ``class Karni: aggregate`` and a routed viewset's ``aggregation``
    must name fields, relation paths or declared expressions, with buckets
    only on dates (E380). An expression neither list uses is a warning (W570).
    A ``Karni.label_field``, which labels the groups of a relation, must name a
    field of its model (E280).
    """
    from karni.aggregation import Aggregation, aggregation_of
    from karni.api.routers import resolve_router
    from karni.api.viewsets import BaseViewSet
    from karni.meta import karni_option, label_field

    found: list[tuple[str, Any, Any, Any]] = []
    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if karni_option(model, "label_field"):
                try:
                    label_field(model)
                except KarniError as exc:
                    messages.append(_as_check(exc, model))
            try:
                declared = aggregation_of(model)
            except KarniError as exc:
                messages.append(_as_check(exc, model))
                continue
            if declared is not None:
                found.append((f"{model.__name__}.Karni.aggregate", declared, model, model))
    seen: set[type[Any]] = set()
    for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
        if viewset in seen or not (isinstance(viewset, type) and issubclass(viewset, BaseViewSet)):
            continue
        seen.add(viewset)
        declared = viewset.__dict__.get("aggregation")
        model = viewset.model or getattr(viewset.queryset, "model", None)
        if isinstance(declared, Aggregation) and model is not None:
            found.append((f"{viewset.__name__}.aggregation", declared, model, viewset))
    for owner, declared, model, obj in found:
        for problem in declared.problems(model):
            messages.append(check_error("E380", f"{owner}: {problem}.", hint=_fix("E380"), obj=obj))
        for name in declared.unused_expressions():
            messages.append(
                check_warning(
                    "W570",
                    f"{owner}: the expression {name!r} is in neither group_by nor values.",
                    hint=_fix("W570"),
                    obj=obj,
                )
            )
    return messages


@checks.register(checks.Tags.models)
def check_layouts(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E550 to E553: every ``Karni.field_groups`` and ``Karni.column_sets`` (experimental).

    A malformed declaration, a group or column set naming a field the model
    does not have, and a field in two groups, each reported with the model,
    the group or set, and the field (:mod:`karni.layout`).
    """
    from karni.layout import layout_errors

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            messages.extend(_as_check(exc, model) for exc in layout_errors(model))
    return messages


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


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


@checks.register()
def check_call_time_settings(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E508: a setting assigned where it cannot take effect.

    ``karni_settings()`` computes other settings from the ones in
    :data:`karni.conf.CALL_TIME_SETTINGS` during the call. One reassigned
    after the call changes none of them, so startup fails and names it
    instead of running half-configured. Also reported: ``KARNI_ADMIN_LOGO``
    set while ``UNFOLD`` has no ``SITE_LOGO`` entry, which happens when
    ``UNFOLD`` is replaced after the call.
    """
    from django.conf import settings

    from karni.conf import CALL_TIME_SETTINGS, settings_changed_after_call

    module = getattr(settings, "SETTINGS_MODULE", None)
    messages: list[checks.CheckMessage] = []
    for name, (before, after) in settings_changed_after_call(module).items():
        messages.append(
            check_error(
                "E508",
                f"{name} is assigned after karni_settings() in {module} ({_short(before)} during "
                f"the call, {_short(after)} now). karni_settings() computed "
                f"{CALL_TIME_SETTINGS[name]} from it during the call, so the new value changes "
                "none of them.",
                hint=f"Move the assignment above the karni_settings(globals()) line, or pass it "
                f"as karni_settings(globals(), {name}=...).",
                obj=name,
            )
        )
    logo = getattr(settings, "KARNI_ADMIN_LOGO", None)
    unfold = getattr(settings, "UNFOLD", None)
    if logo and isinstance(unfold, dict) and "SITE_LOGO" not in unfold:
        messages.append(
            check_error(
                "E508",
                f"KARNI_ADMIN_LOGO is {_short(logo)}, but UNFOLD has no 'SITE_LOGO' entry, so the "
                "admin shows no logo. UNFOLD was replaced after karni_settings(), which drops the "
                "entries Karni put there.",
                hint="Change UNFOLD in place (UNFOLD['SITE_TITLE'] = ...) instead of replacing it, "
                "or add 'SITE_LOGO': karni.conf.admin_logo.site_logo and 'SITE_ICON': "
                "karni.conf.admin_logo.site_icon to your UNFOLD.",
                obj="KARNI_ADMIN_LOGO",
            )
        )
    return messages


_REQUEST_ID_MIDDLEWARE = "karni.tracing.RequestIdMiddleware"
_STRUCTLOG_MIDDLEWARE = "django_structlog.middlewares.RequestMiddleware"


@checks.register()
def check_request_id_middleware(
    app_configs: Any = None, **kwargs: Any
) -> list[checks.CheckMessage]:
    """karni.W920: ``RequestIdMiddleware`` must come before django-structlog's middleware.

    Removing it altogether is the documented opt-out and is not flagged.
    """
    from django.conf import settings

    middleware = [str(entry) for entry in getattr(settings, "MIDDLEWARE", None) or []]
    if _REQUEST_ID_MIDDLEWARE not in middleware or _STRUCTLOG_MIDDLEWARE not in middleware:
        return []
    if middleware.index(_REQUEST_ID_MIDDLEWARE) < middleware.index(_STRUCTLOG_MIDDLEWARE):
        return []
    return [
        check_warning(
            "W920",
            f"{_REQUEST_ID_MIDDLEWARE} comes after {_STRUCTLOG_MIDDLEWARE} in MIDDLEWARE: "
            "the request's first log lines carry a different (possibly client-chosen) id "
            "than its response, tasks and change history.",
            hint=f"Move {_REQUEST_ID_MIDDLEWARE} above {_STRUCTLOG_MIDDLEWARE}.",
            obj="MIDDLEWARE",
        )
    ]


_TERMS_MIDDLEWARE = "karni.accounts.terms.TermsGateMiddleware"
_AUTHENTICATION_MIDDLEWARE = "django.contrib.auth.middleware.AuthenticationMiddleware"


def _is_terms_gate(entry: str) -> bool:
    """Whether a ``MIDDLEWARE`` entry is the terms gate or a subclass of it."""
    if entry == _TERMS_MIDDLEWARE:
        return True
    from django.utils.module_loading import import_string

    from karni.accounts.terms import TermsGateMiddleware

    try:
        found = import_string(entry)
    except ImportError:
        return False
    return isinstance(found, type) and issubclass(found, TermsGateMiddleware)


@checks.register()
def check_terms_middleware(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E248: while ``KARNI_TERMS`` requires acceptance, its gate runs after authentication.

    ``karni_settings()`` lists ``TermsGateMiddleware`` in ``MIDDLEWARE``. A
    project that replaces ``MIDDLEWARE`` after the call loses it, and the gate
    then refuses nobody. Listed before ``AuthenticationMiddleware`` it cannot
    see a session user. A subclass counts as the gate.
    """
    from django.conf import settings

    from karni.accounts.terms import gate_on

    if not gate_on():
        return []
    middleware = [str(entry) for entry in getattr(settings, "MIDDLEWARE", None) or []]
    gate = next((index for index, entry in enumerate(middleware) if _is_terms_gate(entry)), None)
    fix = (
        f"Add '{_TERMS_MIDDLEWARE}' to MIDDLEWARE after '{_AUTHENTICATION_MIDDLEWARE}', or extend "
        "MIDDLEWARE instead of replacing it."
    )
    if gate is None:
        return [
            check_error(
                "E248",
                "KARNI_TERMS requires acceptance, but MIDDLEWARE has no TermsGateMiddleware: "
                "nobody is asked to accept the terms.",
                hint=fix,
                obj="MIDDLEWARE",
            )
        ]
    if _AUTHENTICATION_MIDDLEWARE in middleware and gate < middleware.index(
        _AUTHENTICATION_MIDDLEWARE
    ):
        return [
            check_error(
                "E248",
                f"{middleware[gate]} comes before {_AUTHENTICATION_MIDDLEWARE} in MIDDLEWARE, so "
                "the terms gate cannot see a user signed in by session.",
                hint=f"Move {middleware[gate]} below {_AUTHENTICATION_MIDDLEWARE}.",
                obj="MIDDLEWARE",
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


@checks.register(checks.Tags.models)
def check_tree_models(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E344 / E345: a tree model whose manager or ``parent`` cannot carry the walks."""
    from django.db import models

    from karni.models import TreeModel

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if not issubclass(model, TreeModel):
                continue
            manager = model._default_manager
            if not callable(getattr(manager, "descendants", None)):
                messages.append(
                    check_error(
                        "E344",
                        f"{model.__name__} inherits TreeModel, but its default manager "
                        f"'{manager.name}' ({type(manager).__name__}) has no tree walks, so "
                        f"{model.__name__}.objects.descendants() and the tree endpoints fail.",
                        hint=_fix("E344"),
                        obj=model,
                    )
                )
            parent = model._meta.get_field("parent")
            if not (
                isinstance(parent, models.ForeignKey)
                and parent.related_model is model
                and parent.null
            ):
                messages.append(
                    check_error(
                        "E345",
                        f"{model.__name__}.parent is {type(parent).__name__}, not a nullable "
                        f"ForeignKey to {model.__name__}, so no walk can follow it.",
                        hint=_fix("E345"),
                        obj=model,
                    )
                )
    return messages


@checks.register(checks.Tags.models)
def check_tree_scopes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E490 / W620: every ``tree:<path>`` of ``KARNI_ROLES`` ends at a tree model.

    E490 is a path that does not reach a tree model from the model an explicit
    key names, or from any model a wildcard matches. W620 is a role grant
    whose members get no node: the user model has no attribute named after
    the path's last step, the node a role grant of the scope reaches
    (experimental, :mod:`karni.accounts.tree_scope`).
    """
    import fnmatch

    from django.contrib.auth import get_user_model

    from karni.accounts.grants import user_key
    from karni.accounts.roles import declared_roles, permission_keys
    from karni.accounts.tree_scope import resolve_path, tree_path

    try:
        specs = declared_roles()
        keys = permission_keys()
    except Exception:  # noqa: BLE001 - KARNI_ROLES itself is validated elsewhere
        return []
    user_model = get_user_model()
    messages: list[checks.CheckMessage] = []
    for spec in specs:
        for pattern, scope in spec.grants.items():
            kind, _, path = str(scope).partition(":")
            if kind != "tree" or not path:
                continue
            glob = "*:*" if pattern == "*" else pattern
            matched = list(
                dict.fromkeys(
                    model for key, model in keys.items() if fnmatch.fnmatchcase(key, glob)
                )
            )
            if not matched:
                continue  # a pattern that matches nothing is E206
            where = f"KARNI_ROLES[{spec.slug!r}] grants {pattern!r} with scope 'tree:{path}'"
            fits = [model for model in matched if tree_path(model, path) is not None]
            if not fits:
                if len(matched) == 1:
                    why = f"{matched[0].__name__} has no path {path!r} to a tree model."
                    try:
                        resolve_path(matched[0], path)
                    except KarniError as exc:
                        why = exc.message
                    text = f"{where}: {why}"
                else:
                    text = (
                        f"{where}, but none of the {len(matched)} models it matches has a path "
                        f"{path!r} to a tree model."
                    )
                messages.append(check_error("E490", text, hint=_fix("E490"), obj=matched[0]))
            elif not hasattr(user_model, user_key("tree", path)):
                messages.append(
                    check_warning(
                        "W620",
                        f"{where}, but {user_model.__name__} has no attribute "
                        f"{user_key('tree', path)!r}, so the role gives its members no node and "
                        "no row.",
                        hint=_fix("W620"),
                        obj=fits[0],
                    )
                )
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

# External tables, SQL views and a second database, E270-E276 / W541 / W542 (karni.db.checks).
from karni.db import checks as _db_checks  # noqa: E402,F401
from karni.fields import checks as _field_checks  # noqa: E402,F401


@checks.register(checks.Tags.models)
def check_taxonomies(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E571 / E572: a taxonomy whose target is not a tree, or whose field does not fit.

    E571 is a ``class Karni: taxonomies`` key whose many-to-many points at a
    model that is not a :class:`karni.models.TreeModel`. E572 is a key the
    model adopts (it declares a field of that name) whose field is not a
    many-to-many to the declared target (experimental, :mod:`karni.taxonomy`).
    """
    from karni.taxonomy import taxonomies

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    messages: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if model._meta.proxy:
                continue
            for taxonomy in taxonomies(model).values():
                found = taxonomy.problem()
                if found is not None:
                    code, message = found
                    messages.append(check_error(code, message, hint=_fix(code), obj=model))
    return messages


@checks.register(checks.Tags.urls)
def check_api_versions(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E590 / E591 / W660: the API version settings (experimental).

    E590 is a bad ``KARNI_API_VERSION`` or ``KARNI_API_VERSIONS``, E591 a bad
    ``KARNI_API_UNVERSIONED``, and W660 a version past its sunset date.
    """
    from karni.api.versions import problems

    return [
        check_error(code, message, hint=hint, obj="settings")
        if code.startswith("E")
        else check_warning(code, message, hint=hint, obj="settings")
        for code, message, hint in problems()
    ]
