"""Celery application factory for Karni projects.

Projects wire Celery with a single call in ``config/celery.py``::

    from karni.celery import create_celery_app

    app = create_celery_app()

and re-export it from ``config/__init__.py`` so tasks load with Django::

    from config.celery import app as celery_app

    __all__ = ("celery_app",)

The factory reads every Celery option from the project's Django settings
using the ``CELERY_`` namespace (``CELERY_BROKER_URL`` -> ``broker_url`` and
so on), which is how Karni's defaults from :mod:`karni.conf` reach the app:

- ``CELERY_BROKER_URL`` defaults to ``REDIS_URL``,
- ``CELERY_RESULT_BACKEND`` defaults to ``"django-db"`` (django-celery-results),
- ``CELERY_BEAT_SCHEDULER`` defaults to
  ``"django_celery_beat.schedulers:DatabaseScheduler"`` (django-celery-beat).

Every one of those is a plain Django setting, so a project overrides any of
them by assigning the ``CELERY_*`` name in its ``settings.py``. For behaviour
the settings namespace cannot express, pass keyword overrides to
:func:`create_celery_app` (they take precedence over the Django settings), or
skip the factory entirely and build your own :class:`celery.Celery` instance —
nothing in Karni depends on this factory.
"""

from __future__ import annotations

from typing import Any

from celery import Celery

__all__ = ["create_celery_app"]

#: Fallback Celery main-module name when neither the ``name`` argument nor the
#: ``PROJECT_NAME`` environment variable is provided.
_DEFAULT_NAME = "karni"

#: The Django settings prefix the factory configures Celery with.
_NAMESPACE = "CELERY"


def _default_name() -> str:
    """Return the default app name from the ``PROJECT_NAME`` env var.

    Reads through the shared django-environ ``env`` from
    :mod:`karni.conf.base` (imported lazily so importing this module stays
    side-effect free) and falls back to ``"karni"``. Override by passing an
    explicit ``name`` to :func:`create_celery_app` or by exporting
    ``PROJECT_NAME``.
    """
    from karni.conf.base import env

    return env.str("PROJECT_NAME", default=_DEFAULT_NAME)


def _namespaced(key: str) -> str:
    """Return ``key`` spelled as its namespaced Django setting name.

    ``"task_time_limit"`` becomes ``"CELERY_TASK_TIME_LIMIT"``; a key that
    already carries the prefix (any case) is normalised rather than
    double-prefixed.
    """
    prefix = f"{_NAMESPACE}_"
    bare = key[len(prefix) :] if key.upper().startswith(prefix) else key
    return f"{prefix}{bare.upper()}"


def create_celery_app(name: str | None = None, **overrides: Any) -> Celery:
    """Create a Celery app configured from Django settings and return it.

    ``DJANGO_SETTINGS_MODULE`` must already be set when this is called — the
    entrypoint that imports ``config/celery.py`` (``manage.py``, ``wsgi.py``,
    ``asgi.py`` or the ``celery -A config`` command) is responsible for that.
    This factory never sets or modifies it; setting it here would silently
    mask a misconfigured entrypoint, and Celery's Django fixup only activates
    when the variable is present at app-creation time.

    What the factory does, in order:

    1. Instantiates :class:`celery.Celery` named ``name``, falling back to the
       ``PROJECT_NAME`` environment variable and then ``"karni"``.
    2. Loads configuration from ``django.conf:settings`` with the ``CELERY_``
       namespace — lazily, so importing ``config/celery.py`` never forces the
       Django settings to evaluate early. Every ``CELERY_*`` Django setting
       (including Karni's defaults from :mod:`karni.conf`) configures the app,
       and any of them can be overridden from the project's ``settings.py``.
    3. Applies ``**overrides``. Keys are new-style lowercase Celery setting
       names (for example ``task_always_eager=True``) and take precedence
       over both Karni's defaults and the project's ``CELERY_*`` settings.
       They are applied via ``app.conf.update`` and re-asserted under their
       namespaced spelling once the configuration finalises (Celery's
       ``on_after_configure`` signal), because namespaced lookups consult the
       ``CELERY_*`` names first and would otherwise shadow a plain-key
       override with the Django settings value.
    4. Calls ``app.autodiscover_tasks()`` so every installed Django app's
       ``tasks`` module is discovered lazily from ``INSTALLED_APPS``.

    The factory registers no tasks of its own and touches no global state
    beyond Celery's default current-app bookkeeping.

    :param name: Main name for the Celery app. Defaults to the
        ``PROJECT_NAME`` environment variable, then ``"karni"``.
    :param overrides: Lowercase Celery settings applied on top of the Django
        settings, e.g. ``create_celery_app(task_default_queue="high")``.
    :returns: The configured :class:`celery.Celery` application.
    """
    app = Celery(name or _default_name())
    app.config_from_object("django.conf:settings", namespace=_NAMESPACE)
    if overrides:
        app.conf.update(**overrides)

        def _reapply_overrides(
            sender: Celery | None = None,
            source: Any = None,
            **_kwargs: Any,
        ) -> None:
            """Re-assert factory overrides over namespaced Django settings."""
            source.update({_namespaced(key): value for key, value in overrides.items()})

        # weak=False: the receiver is a local closure and must outlive this
        # function. The signal is per-app, so nothing leaks across apps.
        app.on_after_configure.connect(_reapply_overrides, weak=False)
    app.autodiscover_tasks()
    return app
