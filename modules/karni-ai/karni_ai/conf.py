"""Settings vocabulary for karni-ai: the ``karni.settings`` entry point.

:data:`DEFAULTS` is the module's settings fragment. ``karni_settings()``
merges it into every project that installs karni-ai, after Karni's defaults
and before the project's own settings (new top-level names only).

Import-light by contract: plain data plus django-environ reads, never
``django.conf.settings`` at import time. Module code reads settings through
:func:`get`, so it also works without ``karni_settings()``.

There is no default provider and no default model name. The provider, the
model name and the API key come from settings or the environment only, and
``karni check`` fails (AI001, AI004, AI005) while one is missing. The model
name and the key are the provider's own settings (``ANTHROPIC_MODEL``,
``OPENAI_API_KEY``...), so they never become options in karni.yaml.

Override / escape hatch: define any of these names in the project's
settings.py, or set the environment variable.
"""

from __future__ import annotations

from typing import Any

import environ
from django.conf import settings

env = environ.Env()

DEFAULTS: dict[str, Any] = {
    # The provider: "anthropic", "openai", "test" (deterministic, no network),
    # or the dotted path of a karni_ai.providers.base.Provider subclass. Empty
    # until a project sets it: karni check fails (AI001) without one.
    "KARNI_AI_PROVIDER": env("KARNI_AI_PROVIDER", default=""),
    # Whole seconds one provider call may take before it fails (AI006).
    "KARNI_AI_TIMEOUT": env.int("KARNI_AI_TIMEOUT", default=60),
    # Retries of a provider call that failed on a rate limit, an overload or the network.
    "KARNI_AI_MAX_RETRIES": env.int("KARNI_AI_MAX_RETRIES", default=1),
    # The most tokens one answer may use. A longer answer is cut off (AI007).
    "KARNI_AI_MAX_OUTPUT_TOKENS": env.int("KARNI_AI_MAX_OUTPUT_TOKENS", default=16000),
    # Rows kept from one answer. The rest are left out, with a problem.
    "KARNI_AI_MAX_ROWS": env.int("KARNI_AI_MAX_ROWS", default=50),
    # The longest source text, in characters. A longer one is refused (AI010).
    "KARNI_AI_MAX_SOURCE_CHARS": env.int("KARNI_AI_MAX_SOURCE_CHARS", default=100_000),
    # The largest PDF upload, in bytes (AI010).
    "KARNI_AI_MAX_UPLOAD_BYTES": env.int("KARNI_AI_MAX_UPLOAD_BYTES", default=10 * 1024 * 1024),
    # The most pages read from one PDF (AI010).
    "KARNI_AI_MAX_PDF_PAGES": env.int("KARNI_AI_MAX_PDF_PAGES", default=50),
    # Whole seconds a URL fetch may take: connecting, redirects and reading (AI012).
    "KARNI_AI_FETCH_TIMEOUT": env.int("KARNI_AI_FETCH_TIMEOUT", default=10),
    # The largest response a URL fetch reads, in bytes (AI012).
    "KARNI_AI_FETCH_MAX_BYTES": env.int("KARNI_AI_FETCH_MAX_BYTES", default=5 * 1024 * 1024),
    # Redirects a URL fetch follows, each checked like the first address (AI011).
    "KARNI_AI_FETCH_MAX_REDIRECTS": env.int("KARNI_AI_FETCH_MAX_REDIRECTS", default=3),
    # The ports a URL may name (AI011).
    "KARNI_AI_FETCH_PORTS": env.list("KARNI_AI_FETCH_PORTS", cast=int, default=[80, 443]),
    # The dotted path of the class that fetches a URL (karni_ai.services.fetch.Fetcher).
    "KARNI_AI_FETCHER": env("KARNI_AI_FETCHER", default="karni_ai.services.fetch.Fetcher"),
    # The dotted path of the class that runs an extraction (karni_ai.extraction.Extractor).
    "KARNI_AI_EXTRACTOR": env("KARNI_AI_EXTRACTOR", default="karni_ai.extraction.Extractor"),
    # Prices per million tokens, by model name: {"<model>": {"input": "1.00",
    # "output": "4.00"}}. A model missing from the table logs no cost.
    "KARNI_AI_PRICES": {},
    # Tokens one user may spend in a calendar month (None: no budget, AI013).
    "KARNI_AI_MONTHLY_TOKENS_PER_USER": env.int("KARNI_AI_MONTHLY_TOKENS_PER_USER", default=None),
    # Tokens the whole project may spend in a calendar month (None: no budget, AI014).
    "KARNI_AI_MONTHLY_TOKENS": env.int("KARNI_AI_MONTHLY_TOKENS", default=None),
    # The anthropic provider: the API key and the model name (no default).
    "ANTHROPIC_API_KEY": env("ANTHROPIC_API_KEY", default=""),
    "ANTHROPIC_MODEL": env("ANTHROPIC_MODEL", default=""),
    # The openai provider: the API key and the model name (no default).
    "OPENAI_API_KEY": env("OPENAI_API_KEY", default=""),
    "OPENAI_MODEL": env("OPENAI_MODEL", default=""),
}
"""The karni-ai settings fragment (``karni.settings`` entry point)."""


def get(name: str) -> Any:
    """``settings.<name>`` if the project defines it, else the module default.

    :raises KeyError: when ``name`` is not a karni-ai setting and the project
        does not define it either.
    """
    return getattr(settings, name, DEFAULTS[name])


def load_class(name: str, base: type[Any]) -> type[Any]:
    """The class the dotted-path setting ``name`` names, a subclass of ``base`` (else AI016)."""
    from django.utils.module_loading import import_string
    from karni.exceptions import KarniImproperlyConfigured

    path = str(get(name))
    try:
        found = import_string(path)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"{name} {path!r} cannot be imported: {exc}", code="AI016"
        ) from exc
    if not (isinstance(found, type) and issubclass(found, base)):
        raise KarniImproperlyConfigured(
            f"{name} must name a {base.__module__}.{base.__qualname__} subclass, not {path!r}.",
            code="AI016",
        )
    return found
