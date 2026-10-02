"""Structured logging configuration for Karni projects.

Builds a Django ``LOGGING`` dict wired to structlog (with django-structlog's
request middleware emitting into the same pipeline) and configures structlog
itself. Production renders one JSON object per line; development renders
colorized, human-readable console lines.
"""

from __future__ import annotations

from typing import Any

import structlog


def build_logging(json: bool) -> dict[str, Any]:
    """Return a Django ``LOGGING`` dict and configure structlog to match.

    ``json=True`` renders every log line as a JSON object (production);
    ``json=False`` renders colorized console output (development). Both stdlib
    logging records (Django, Celery, third parties) and structlog-native
    events flow through the same ``ProcessorFormatter``, so every line shares
    one format. Calling this function also runs :func:`structlog.configure`,
    which is idempotent — the last call wins.

    ``karni_settings()`` calls this automatically with the profile's
    ``KARNI_JSON_LOGS`` value unless the project already defines ``LOGGING``.

    Override / escape hatch: set ``KARNI_JSON_LOGS`` in your settings to flip
    the renderer per profile; define your own ``LOGGING`` (before calling
    ``karni_settings()``, as a keyword override, or after the call) to take
    over logging completely — Karni then leaves both ``LOGGING`` and the
    structlog configuration untouched; or call ``build_logging()`` yourself
    and mutate the returned dict (add handlers, change levels) before
    assigning it to ``LOGGING``.

    :param json: render log lines as JSON when True, console lines when False.
    :returns: a dict suitable for Django's ``LOGGING`` setting.
    """
    renderer: Any
    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Processors applied to stdlib log records before rendering, and shared by
    # structlog-native loggers so both pipelines produce identical fields.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": [
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    renderer,
                ],
                "foreign_pre_chain": shared_processors,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "structlog",
            },
        },
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {
            "django": {"level": "INFO"},
            "django.server": {"level": "INFO"},
            "django_structlog": {"level": "INFO"},
            "celery": {"level": "INFO"},
        },
    }
