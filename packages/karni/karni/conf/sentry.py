"""Optional Sentry initialisation for Karni projects."""

from __future__ import annotations

import environ

from karni.exceptions import KarniImportError


def maybe_init_sentry(env: environ.Env) -> None:
    """Initialise the Sentry SDK when ``SENTRY_DSN`` is set; otherwise do nothing.

    Reads ``SENTRY_DSN`` and ``SENTRY_TRACES_SAMPLE_RATE`` (default ``0.0``)
    from the environment and initialises ``sentry_sdk`` with the Django and
    Celery integrations. ``sentry-sdk`` is an optional dependency, imported
    lazily only when a DSN is present, so core installs never require it.

    ``karni_settings()`` calls this automatically on every invocation.

    Override / escape hatch: leave ``SENTRY_DSN`` empty to disable Sentry
    entirely, or skip/replace this behaviour by calling ``sentry_sdk.init``
    yourself in ``settings.py`` *before* ``karni_settings()`` runs with
    ``SENTRY_DSN`` unset (Karni never re-initialises an SDK you configured —
    with the env var empty this function is a no-op).

    :param env: the shared :class:`environ.Env` reader
        (``karni.conf.base.env``).
    :raises ImportError: when ``SENTRY_DSN`` is set but ``sentry-sdk`` is not
        installed; install the ``karni[sentry]`` extra.
    """
    dsn: str = env("SENTRY_DSN", default="")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise KarniImportError(
            "SENTRY_DSN is set but sentry-sdk is not installed. "
            "Install the Sentry extra: pip install 'karni[sentry]'",
            code="E501",
        ) from exc

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        environment=env("DJANGO_ENV", default="dev"),
        send_default_pii=False,
    )
