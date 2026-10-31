"""Build-failing checks for ``karni check``: the provider, its model name and its key are set.

karni-ai has no default provider and no default model, and its key comes
from the environment only. While the module is in ``INSTALLED_APPS``,
``karni check`` fails with one line per missing piece:

* AI001: ``KARNI_AI_PROVIDER`` is not set;
* AI002: it names nothing that loads as a provider;
* AI003: the provider's SDK (an extra) is not installed;
* AI004: the provider's API key is not set (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``);
* AI005: the provider's model name is not set (``ANTHROPIC_MODEL``, ``OPENAI_MODEL``).

The ``test`` provider needs none of them, so CI and local work run without a key.
"""

from __future__ import annotations

__all__ = ["run_checks"]


def run_checks() -> list[str]:
    from django.apps import apps
    from karni.exceptions import KarniImproperlyConfigured

    from karni_ai.providers.base import get_provider

    if not apps.is_installed("karni_ai"):
        return []  # installed in the environment, not in this project
    try:
        provider = get_provider()
    except KarniImproperlyConfigured as exc:
        return [f"{exc.code}: {exc.message}"]
    return [
        f"{code}: the {provider.name} provider: {message}." for code, message in provider.problems()
    ]
