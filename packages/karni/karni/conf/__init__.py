"""Karni settings assembly.

The single public entry point is :func:`karni_settings`, which turns a
project's ``settings.py`` into roughly thirty lines::

    from karni.conf import karni_settings

    karni_settings(globals())

    # Project-specific settings below — anything assigned here wins.
    INSTALLED_APPS += ["myapp"]

Profiles: ``DJANGO_ENV=dev`` (default) or ``DJANGO_ENV=prod`` select the
:data:`karni.conf.dev.DEV` or :data:`karni.conf.prod.PROD` overlay on top of
:data:`karni.conf.base.BASE`.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, MutableMapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from karni.conf.admin_logo import logo_paths, site_icon, site_logo
from karni.conf.base import (
    ALLAUTH_MIDDLEWARE,
    BASE,
    OTP_MIDDLEWARE,
    SOCIAL_APPS,
    TWOFA_APPS,
    _caches,
    _storages,
    env,
)
from karni.conf.dev import DEV
from karni.conf.logging import build_logging
from karni.conf.prod import PROD
from karni.conf.sentry import maybe_init_sentry
from karni.exceptions import KarniImproperlyConfigured

__all__ = ["CALL_TIME_SETTINGS", "env", "karni_settings", "settings_changed_after_call"]

_PROFILES: dict[str, dict[str, Any]] = {"dev": DEV, "prod": PROD}

# Settings that are ordered lists Karni must extend rather than replace when
# the project has already defined them.
_LIST_MERGED_SETTINGS = ("INSTALLED_APPS", "MIDDLEWARE", "DATABASE_ROUTERS")

#: Entry-point group through which installed Karni modules ship their default
#: settings ("the settings fragment"). A staged exception to the
#: three-occurrences rule: the group ships with its first producer
#: (karni-payments) because `karni add` is contracted to rely on it.
_SETTINGS_FRAGMENT_GROUP = "karni.settings"

#: Settings ``karni_settings()`` reads during the call to compute other settings,
#: with what it computes from each. Assigned after the call, such a setting
#: changes nothing it fed, so the system check ``karni.E508`` reports it (see
#: :func:`settings_changed_after_call`). Assign it before the call or pass it
#: as a keyword override. ``KARNI_ADMIN_LOGO`` is not listed: the admin reads
#: it on every request (:func:`karni.conf.admin_logo.site_logo`), so it works
#: wherever it is assigned.
CALL_TIME_SETTINGS: dict[str, str] = {
    "KARNI_AUTH_MODE": (
        "CSRF_TRUSTED_ORIGINS and CORS_ALLOW_CREDENTIALS (session mode), and django-otp's "
        "middleware with KARNI_2FA"
    ),
    "KARNI_2FA": "INSTALLED_APPS and MIDDLEWARE (django-otp)",
    "KARNI_SOCIAL_AUTH": (
        "INSTALLED_APPS, MIDDLEWARE, AUTHENTICATION_BACKENDS and TEMPLATES (django-allauth)"
    ),
    "KARNI_SOCIAL_PROVIDERS": "INSTALLED_APPS (one django-allauth provider app each)",
    "KARNI_FRONTEND_URL": "CSRF_TRUSTED_ORIGINS (session mode)",
    "KARNI_AUTH_THROTTLE_RATES": "REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']",
    "KARNI_JSON_LOGS": "LOGGING and the structlog renderer",
    "KARNI_CACHE": "CACHES",
    "KARNI_STORAGE": "STORAGES",
}

#: Per settings module (its ``__name__``): the namespace and a copy of each
#: :data:`CALL_TIME_SETTINGS` value the call used, for karni.E508.
_consumed: dict[str, tuple[MutableMapping[str, Any], dict[str, Any]]] = {}

_CONTRIB_ADMIN = "django.contrib.admin"
_AUTHENTICATION_MIDDLEWARE = "django.contrib.auth.middleware.AuthenticationMiddleware"
_REQUEST_CONTEXT_PROCESSOR = "django.template.context_processors.request"
_DJANGO_TEMPLATES_BACKEND = "django.template.backends.django.DjangoTemplates"


def _dedupe(items: Iterable[str]) -> list[str]:
    """Return ``items`` with duplicates removed, keeping first occurrences."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _append_missing(target: list[str], entries: Iterable[str]) -> None:
    """Append each of ``entries`` to ``target`` unless already present."""
    for entry in entries:
        if entry not in target:
            target.append(entry)


def _unfold_before_admin(apps: list[str], user_entries: Sequence[str]) -> list[str]:
    """Move Karni-appended unfold entries to just before ``django.contrib.admin``.

    When the project supplies its own ``INSTALLED_APPS`` containing
    ``django.contrib.admin``, the plain append would leave ``unfold`` *after*
    contrib.admin, which breaks its template override and fails validation.
    Only entries Karni appended are moved — anything the user listed
    themselves keeps its position (and is caught by validation if wrong).

    Override / escape hatch: list ``unfold`` before ``django.contrib.admin``
    in your own ``INSTALLED_APPS`` to control the position yourself.
    """
    if _CONTRIB_ADMIN not in apps:
        return apps
    user_set = set(user_entries)
    admin_index = apps.index(_CONTRIB_ADMIN)
    moved = [
        app
        for app in apps[admin_index:]
        if isinstance(app, str)
        and (app == "unfold" or app.startswith("unfold."))
        and app not in user_set
    ]
    if not moved:
        return apps
    remaining = [app for app in apps if app not in moved]
    insert_at = remaining.index(_CONTRIB_ADMIN)
    return [*remaining[:insert_at], *moved, *remaining[insert_at:]]


_fragment_entry_points: tuple[metadata.EntryPoint, ...] | None = None


def _settings_fragment_entry_points() -> tuple[metadata.EntryPoint, ...]:
    """Return the installed ``karni.settings`` entry points, sorted by name.

    The scan is cached module-level: installed distributions cannot change
    within a running process, and ``karni_settings()`` may be called more
    than once (tests, multi-namespace setups). Tests monkeypatch this
    function to inject fake entry points.
    """
    global _fragment_entry_points
    if _fragment_entry_points is None:
        _fragment_entry_points = tuple(
            sorted(
                metadata.entry_points(group=_SETTINGS_FRAGMENT_GROUP),
                key=lambda entry_point: entry_point.name,
            )
        )
    return _fragment_entry_points


def _merge_settings_fragments(merged: dict[str, Any]) -> None:
    """Merge every installed module's settings fragment into ``merged``.

    A fragment is a plain dict of defaults exposed through the
    ``karni.settings`` entry-point group (e.g. ``payments =
    "karni_payments.conf:DEFAULTS"``) — this is how ``karni add`` "applies a
    settings fragment" without ever editing ``settings.py``: the fragment
    ships *in* the module. Fragments must be import-light and must not touch
    ``django.conf.settings`` at import time; per-profile values read
    ``os.environ["DJANGO_ENV"]`` inside the fragment instead.

    Semantics (amendment G7):

    * applied in entry-point-name order, after BASE and the profile overlay
      and before ``**overrides`` / the namespace's own names — so projects
      always win over modules;
    * each fragment dict is deep-copied, so mutating the resulting settings
      never corrupts the module's ``DEFAULTS``;
    * fragments may only introduce **new** top-level names. A key already
      present in the merged defaults (BASE, the profile overlay or an
      earlier fragment) raises ``ImproperlyConfigured`` naming the entry
      point — there is no deep merge in v0.1;
    * a fragment that fails to load, or is not a dict, raises
      ``ImproperlyConfigured`` naming the entry point, so a broken module is
      debuggable instead of silently skipped.

    Override / escape hatch: fragment values obey the normal precedence —
    define the same name in your settings module (or pass it as an override)
    and your value wins; modules should read settings through their own
    accessor (``conf.get``) so they also work without ``karni_settings()``.
    """
    for entry_point in _settings_fragment_entry_points():
        try:
            fragment = entry_point.load()
        except Exception as exc:
            raise KarniImproperlyConfigured(
                f"Karni settings fragment {entry_point.name!r} "
                f"({entry_point.value}) failed to load: {exc}",
                code="E503",
            ) from exc
        if not isinstance(fragment, dict):
            raise KarniImproperlyConfigured(
                f"Karni settings fragment {entry_point.name!r} ({entry_point.value}) "
                f"must be a dict of settings, got {type(fragment).__name__}.",
                code="E503",
            )
        collisions = sorted(set(fragment) & set(merged))
        if collisions:
            raise KarniImproperlyConfigured(
                f"Karni settings fragment {entry_point.name!r} ({entry_point.value}) "
                f"redefines existing setting(s): {', '.join(collisions)}. Fragments "
                "may only introduce new top-level names.",
                code="E503",
            )
        merged.update(copy.deepcopy(fragment))


def _apply_feature_wiring(
    merged: dict[str, Any],
    *,
    auth_mode: str,
    social: bool,
    twofa: bool,
    providers: Iterable[str],
) -> None:
    """Extend the merged defaults with social-auth and 2FA apps/middleware.

    Mutates ``merged`` (the deep-copied defaults) before it is applied to the
    namespace, so every addition still obeys setdefault semantics and the
    list-merge rules for ``INSTALLED_APPS`` / ``MIDDLEWARE``.
    """
    apps = list(merged.get("INSTALLED_APPS", []))
    middleware = list(merged.get("MIDDLEWARE", []))

    if social:
        _append_missing(apps, SOCIAL_APPS)
        _append_missing(
            apps, (f"allauth.socialaccount.providers.{provider}" for provider in providers)
        )
        _append_missing(middleware, [ALLAUTH_MIDDLEWARE])
        merged.setdefault("SITE_ID", 1)
        merged.setdefault(
            "AUTHENTICATION_BACKENDS",
            [
                "django.contrib.auth.backends.ModelBackend",
                "allauth.account.auth_backends.AuthenticationBackend",
            ],
        )
        merged.setdefault("ACCOUNT_USER_MODEL_USERNAME_FIELD", None)
        merged.setdefault("ACCOUNT_LOGIN_METHODS", {"email"})
        merged.setdefault("ACCOUNT_SIGNUP_FIELDS", ["email*"])

    if twofa:
        _append_missing(apps, TWOFA_APPS)
        # django-otp's middleware only participates in session auth; JWT
        # requests carry no OTP-verified session, so installing it there
        # would be dead weight (the 2FA login gate works in both modes).
        if auth_mode == "session" and OTP_MIDDLEWARE not in middleware:
            try:
                index = middleware.index(_AUTHENTICATION_MIDDLEWARE) + 1
            except ValueError:
                index = len(middleware)
            middleware.insert(index, OTP_MIDDLEWARE)

    merged["INSTALLED_APPS"] = apps
    merged["MIDDLEWARE"] = middleware


def _ensure_request_context_processor(templates: Any) -> None:
    """Add the ``request`` context processor to Django template backends.

    django-allauth requires it; this touches the final ``TEMPLATES`` value
    (including a user-supplied one) but only ever *adds* the one processor,
    and only when ``KARNI_SOCIAL_AUTH`` is enabled.
    """
    if not isinstance(templates, list):
        return
    for backend in templates:
        if not isinstance(backend, dict) or backend.get("BACKEND") != _DJANGO_TEMPLATES_BACKEND:
            continue
        options = backend.setdefault("OPTIONS", {})
        if not isinstance(options, dict):
            continue
        processors = options.setdefault("context_processors", [])
        if isinstance(processors, list) and _REQUEST_CONTEXT_PROCESSOR not in processors:
            processors.append(_REQUEST_CONTEXT_PROCESSOR)


def _apply_session_mode_origins(namespace: MutableMapping[str, Any]) -> None:
    """Derive cookie-auth CORS/CSRF settings for session mode.

    The SPA at ``KARNI_FRONTEND_URL`` must be able to send credentials and
    pass CSRF origin checks, so its origin is appended to
    ``CSRF_TRUSTED_ORIGINS`` and ``CORS_ALLOW_CREDENTIALS`` defaults to True.

    Override / escape hatch: define either setting yourself — the origin is
    only appended when missing and ``CORS_ALLOW_CREDENTIALS`` is a plain
    setdefault.
    """
    frontend = str(namespace.get("KARNI_FRONTEND_URL", "") or "")
    parts = urlsplit(frontend)
    if parts.scheme and parts.netloc:
        origin = f"{parts.scheme}://{parts.netloc}"
        trusted = list(namespace.get("CSRF_TRUSTED_ORIGINS", []))
        if origin not in trusted:
            trusted.append(origin)
        namespace["CSRF_TRUSTED_ORIGINS"] = trusted
    namespace.setdefault("CORS_ALLOW_CREDENTIALS", True)


#: Folders a relative value of which is read from the project root, not the cwd.
_PROJECT_RELATIVE_ROOTS = ("MEDIA_ROOT", "STATIC_ROOT")


def _project_root(namespace: MutableMapping[str, Any]) -> Path | None:
    """``BASE_DIR``, else the folder above the settings package, else ``None``."""
    if namespace.get("BASE_DIR"):
        return Path(str(namespace["BASE_DIR"])).resolve()
    file = namespace.get("__file__")
    return Path(str(file)).resolve().parent.parent if file else None


def _anchor_file_roots(namespace: MutableMapping[str, Any], predefined: set[str]) -> None:
    """Read a relative ``MEDIA_ROOT`` / ``STATIC_ROOT`` Karni set from the project root.

    The dev profile's ``data/media`` (or ``MEDIA_ROOT=data/media`` in
    ``.env``) is then ``<project>/data/media`` whatever folder a command
    runs from. A value defined in the settings module before the call is
    left as written, and so is anything without a known project root.
    """
    root = _project_root(namespace)
    if root is None:
        return
    for name in _PROJECT_RELATIVE_ROOTS:
        value = namespace.get(name)
        if name in predefined or not isinstance(value, str | Path) or not str(value):
            continue
        if not Path(value).is_absolute():
            namespace[name] = str(root / value)


def _ensure_sqlite_dir(databases: Any) -> None:
    """Create the folder of a file-backed SQLite database (``sqlite:///data/db.sqlite3``).

    A fresh project pointed at SQLite would otherwise fail its first
    ``migrate`` with "unable to open database file". In-memory and URI
    databases are left alone.
    """
    if not isinstance(databases, dict):
        return
    for config in databases.values():
        if not isinstance(config, dict) or not str(config.get("ENGINE", "")).endswith("sqlite3"):
            continue
        name = str(config.get("NAME") or "")
        if not name or name == ":memory:" or name.startswith("file:"):
            continue
        Path(name).parent.mkdir(parents=True, exist_ok=True)


def _record_consumed(namespace: MutableMapping[str, Any], used: Iterable[str]) -> None:
    """Keep a copy of each call-time input ``used``, keyed by the settings module's name.

    A plain mapping without ``__name__`` (a test namespace) is not recorded.
    """
    module = namespace.get("__name__")
    if not isinstance(module, str):
        return
    _consumed[module] = (namespace, {name: copy.deepcopy(namespace.get(name)) for name in used})


def settings_changed_after_call(module: str | None) -> dict[str, tuple[Any, Any]]:
    """Call-time inputs the settings module ``module`` reassigned after ``karni_settings()``.

    Maps each setting of :data:`CALL_TIME_SETTINGS` whose value in the module
    now differs from the value the call computed other settings from, to
    ``(value during the call, value now)``. Empty when ``module`` never
    called ``karni_settings()``. ``override_settings`` in tests changes
    ``django.conf.settings``, not the module, so it is never reported.
    """
    if module is None or module not in _consumed:
        return {}
    namespace, used = _consumed[module]
    return {
        name: (before, namespace.get(name))
        for name, before in used.items()
        if namespace.get(name) != before
    }


def karni_settings(
    namespace: MutableMapping[str, Any],
    *,
    env_name: str | None = None,
    **overrides: Any,
) -> None:
    """Apply Karni's default Django settings into ``namespace`` in one call.

    Merges :data:`~karni.conf.base.BASE`, then the profile overlay
    (:data:`~karni.conf.dev.DEV` or :data:`~karni.conf.prod.PROD`), then the
    settings fragments of installed Karni modules (``karni.settings`` entry
    points, see :func:`_merge_settings_fragments`), then ``**overrides``, and
    writes the result into ``namespace`` with ``setdefault`` semantics. The
    defaults are deep-copied on every call, so mutating the resulting
    settings (e.g. ``INSTALLED_APPS += [...]``) never leaks between
    projects, test namespaces or module state.

    Precedence, weakest first:

    1. ``BASE`` defaults (mostly environment-driven via django-environ),
    2. the profile overlay (``env_name`` or the ``DJANGO_ENV`` env var,
       default ``"dev"``),
    3. installed modules' settings fragments (``karni.settings`` entry
       points — new top-level names only; a collision with BASE/profile
       raises ``ImproperlyConfigured`` naming the entry point),
    4. ``**overrides`` keyword arguments (these clobber BASE, the profile
       and fragments, but never a name the namespace already defines),
    5. names already defined in ``namespace`` before the call — never
       overwritten,
    6. anything assigned in the settings module after the call — always wins.

    Special cases:

    * ``INSTALLED_APPS`` / ``MIDDLEWARE`` / ``DATABASE_ROUTERS``: when the
      namespace already defines them, Karni appends only its missing entries
      after the project's own, deduplicated and preserving the project's
      order, instead of replacing the list — except ``unfold``, which is
      inserted immediately *before* ``django.contrib.admin`` (its templates
      must override the admin's). So a project's own database routers come
      before :class:`karni.db.DatabaseRouter` and win.
    * ``KARNI_SOCIAL_AUTH`` / ``KARNI_2FA``: when enabled (in the namespace,
      as an override or via env), the allauth / django-otp apps, middleware
      and companion settings are added to the defaults before merging.
      django-otp's ``OTPMiddleware`` is installed only in session auth mode.
    * ``KARNI_AUTH_THROTTLE_RATES``: merged into
      ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` unless the project
      supplied its own ``REST_FRAMEWORK`` (whole-value replacement then
      applies and the project owns the rates).
    * Session auth mode: the ``KARNI_FRONTEND_URL`` origin is appended to
      ``CSRF_TRUSTED_ORIGINS`` and ``CORS_ALLOW_CREDENTIALS`` defaults to
      True, so cookie-based SPA auth works out of the box.
    * ``LOGGING``: built via :func:`karni.conf.logging.build_logging` from the
      final ``KARNI_JSON_LOGS`` value (console output in dev, JSON in prod)
      unless the namespace already defines ``LOGGING``, in which case Karni
      touches neither ``LOGGING`` nor the structlog configuration.
    * Sentry: :func:`karni.conf.sentry.maybe_init_sentry` runs at the end and
      is a no-op unless the ``SENTRY_DSN`` env var is set.
    * ``env``: the django-environ reader Karni reads its defaults with is
      left in the namespace (Django ignores lower-case names), so a setting
      added after the call reads the environment the same way:
      ``FEATURE_X = env.bool("FEATURE_X", default=False)``. It is also
      importable: ``from karni.conf import env``.
    * ``SILENCED_SYSTEM_CHECKS``: starts as an empty list, so a project
      extends it (``SILENCED_SYSTEM_CHECKS += ["karni.W967"]``) instead of
      hitting a NameError.
    * ``KARNI_CACHE`` / ``KARNI_STORAGE``: ``CACHES`` / ``STORAGES`` follow
      their final value (namespace, override or environment) unless the
      project supplies ``CACHES`` / ``STORAGES`` itself.
    * ``KARNI_ADMIN_LOGO``: ``UNFOLD["SITE_LOGO"]`` and ``["SITE_ICON"]``
      default to resolvers that read the setting on every admin request, so
      it works wherever it is assigned. A bad value raises ``E303`` here.

    The settings in :data:`CALL_TIME_SETTINGS` are read during the call.
    Assigning one after the call cannot change what was computed from it, so
    the system check ``karni.E508`` fails startup and names the setting.

    :param namespace: the target namespace, normally ``globals()`` of the
        project's settings module (any mutable mapping works).
    :param env_name: force a profile (``"dev"`` or ``"prod"``) instead of
        reading the ``DJANGO_ENV`` environment variable.
    :param overrides: setting-name keyword arguments applied over the merged
        defaults (whole-value replacement — e.g. passing ``REST_FRAMEWORK``
        replaces the entire dict).
    :raises ImproperlyConfigured: when the profile name is unknown, or when
        an installed module's settings fragment fails to load, is not a
        dict, or redefines an existing default (the message names the
        offending ``karni.settings`` entry point).
    """
    profile: str = env_name or env("DJANGO_ENV", default="dev")
    if profile not in _PROFILES:
        raise KarniImproperlyConfigured(
            f"Unknown Karni settings profile {profile!r}. Expected one of "
            f"{sorted(_PROFILES)}. Set the DJANGO_ENV environment variable or "
            "pass env_name= to karni_settings().",
            code="E502",
        )

    # Deep-copy so callers mutating nested defaults never corrupt BASE/DEV/PROD.
    merged: dict[str, Any] = copy.deepcopy(BASE)
    merged.update(copy.deepcopy(_PROFILES[profile]))
    _merge_settings_fragments(merged)
    merged.update(overrides)

    def final(name: str) -> Any:
        """Final value of a flag: namespace beats overrides beats defaults."""
        return namespace[name] if name in namespace else merged.get(name)

    auth_mode = str(final("KARNI_AUTH_MODE") or "jwt")
    _apply_feature_wiring(
        merged,
        auth_mode=auth_mode,
        social=bool(final("KARNI_SOCIAL_AUTH")),
        twofa=bool(final("KARNI_2FA")),
        providers=final("KARNI_SOCIAL_PROVIDERS") or [],
    )

    # Whole-value replacement: a project-supplied REST_FRAMEWORK (predefined
    # or passed as an override) owns its throttle rates untouched.
    rest_framework_is_karni = (
        "REST_FRAMEWORK" not in namespace and "REST_FRAMEWORK" not in overrides
    )
    # CACHES and STORAGES follow KARNI_CACHE / KARNI_STORAGE defined before the
    # call too, not only the environment BASE read them from.
    used = ["KARNI_AUTH_MODE", "KARNI_2FA", "KARNI_SOCIAL_AUTH"]
    for flag, derived, build in (
        ("KARNI_CACHE", "CACHES", _caches),
        ("KARNI_STORAGE", "STORAGES", _storages),
    ):
        if derived not in namespace and derived not in overrides:
            merged[derived] = build(env, str(final(flag) or "") or None)
            used.append(flag)
    if bool(final("KARNI_SOCIAL_AUTH")):
        used.append("KARNI_SOCIAL_PROVIDERS")
    if auth_mode == "session":
        used.append("KARNI_FRONTEND_URL")
    if rest_framework_is_karni:
        used.append("KARNI_AUTH_THROTTLE_RATES")
    if "LOGGING" not in namespace and "LOGGING" not in merged:
        used.append("KARNI_JSON_LOGS")

    for key in _LIST_MERGED_SETTINGS:
        defaults = merged.pop(key, None)
        if defaults is None:
            continue
        if key in namespace:
            user_entries = list(namespace[key])
            merged_list = _dedupe([*user_entries, *defaults])
            if key == "INSTALLED_APPS":
                merged_list = _unfold_before_admin(merged_list, user_entries)
            namespace[key] = merged_list
        else:
            namespace[key] = _dedupe(defaults)

    predefined = set(namespace)
    for key, value in merged.items():
        namespace.setdefault(key, value)
    # The reader behind every env-backed default, for settings added after the call.
    namespace.setdefault("env", env)
    _anchor_file_roots(namespace, predefined)

    if rest_framework_is_karni:
        rates = namespace["REST_FRAMEWORK"].setdefault("DEFAULT_THROTTLE_RATES", {})
        auth_rates = namespace.get("KARNI_AUTH_THROTTLE_RATES") or {}
        if isinstance(rates, dict) and isinstance(auth_rates, dict):
            rates.update(auth_rates)

    if bool(final("KARNI_SOCIAL_AUTH")):
        _ensure_request_context_processor(namespace.get("TEMPLATES"))

    if auth_mode == "session":
        _apply_session_mode_origins(namespace)

    if "LOGGING" not in namespace:
        namespace["LOGGING"] = build_logging(
            json=bool(namespace.get("KARNI_JSON_LOGS", profile == "prod"))
        )

    # KARNI_ADMIN_LOGO → UNFOLD["SITE_LOGO"/"SITE_ICON"], read per request so
    # the setting works after the call too; explicit UNFOLD keys win.
    logo_paths(namespace.get("KARNI_ADMIN_LOGO"))  # E303 now, not at the first admin page
    unfold = namespace.get("UNFOLD")
    if isinstance(unfold, dict):
        unfold.setdefault("SITE_LOGO", site_logo)
        unfold.setdefault("SITE_ICON", site_icon)
        # The admin is light only: a project's own UNFOLD dict gets it too.
        unfold.setdefault("THEME", "light")
        # The user menu: Change password and "Show the getting started guide".
        unfold.setdefault("ACCOUNT", {"navigation": "karni.admin.guide.account_links"})

    _ensure_sqlite_dir(namespace.get("DATABASES"))
    _record_consumed(namespace, used)
    maybe_init_sentry(env)
