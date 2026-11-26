"""Optional Sentry initialisation for Karni projects."""

from __future__ import annotations

from typing import Any

import environ

from karni.exceptions import KarniImportError

#: What sentry-sdk 3 is told to leave out, so it sends what sentry-sdk 2 sent
#: with ``send_default_pii=False``: no signed-in user, no cookies, no prompts
#: or answers of AI calls, and of the HTTP bodies only the incoming request's
#: (with the SDK's own scrubbing of passwords, tokens and keys).
SENTRY_3_DATA_COLLECTION: dict[str, Any] = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_bodies": ["incoming_request"],
    "gen_ai": {"inputs": False, "outputs": False},
    "mcp": {"inputs": False, "outputs": False},
}


def privacy_options(sdk_version: str) -> dict[str, Any]:
    """Return the ``sentry_sdk.init`` options that keep personal data out.

    sentry-sdk 2 has one switch, ``send_default_pii``. sentry-sdk 3 removed
    it, collects more by default (the signed-in user, cookies, AI prompts)
    and takes a ``data_collection`` dict instead. Karni sends the same on
    both: nothing that identifies a person unless the project asks for it.

    Override / escape hatch: call ``sentry_sdk.init`` yourself in
    ``settings.py`` with ``SENTRY_DSN`` unset, as :func:`maybe_init_sentry`
    describes.

    :param sdk_version: ``sentry_sdk.VERSION``, for example ``"3.0.1"``.
    """
    major = sdk_version.split(".", 1)[0]
    if major.isdigit() and int(major) >= 3:
        return {"data_collection": {**SENTRY_3_DATA_COLLECTION}}
    return {"send_default_pii": False}


def maybe_init_sentry(env: environ.Env) -> None:
    """Initialise the Sentry SDK when ``SENTRY_DSN`` is set; otherwise do nothing.

    Reads ``SENTRY_DSN`` and ``SENTRY_TRACES_SAMPLE_RATE`` (default ``0.0``)
    from the environment and initialises ``sentry_sdk`` with the Django and
    Celery integrations. ``sentry-sdk`` is an optional dependency, imported
    lazily only when a DSN is present, so core installs never require it.
    Works with sentry-sdk 2 and 3; personal data stays out on both
    (:func:`privacy_options`).

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

    options: dict[str, Any] = {
        "dsn": dsn,
        "integrations": [DjangoIntegration(), CeleryIntegration()],
        "traces_sample_rate": env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        "environment": env("DJANGO_ENV", default="dev"),
    }
    options.update(privacy_options(sentry_sdk.VERSION))
    sentry_sdk.init(**options)
