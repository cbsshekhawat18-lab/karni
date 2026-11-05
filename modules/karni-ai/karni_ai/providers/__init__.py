"""Language model providers.

:mod:`karni_ai.providers.base` defines the :class:`Provider` contract (one
structured answer for a JSON schema, with its token usage) and
:func:`get_provider`. The shipped providers are :mod:`.anthropic` and
:mod:`.openai` (their SDKs are extras) and :mod:`.test`, a deterministic
provider for test suites, CI and local work.
"""

from __future__ import annotations

from karni_ai.providers.base import (
    PROVIDER_SHORTCUTS,
    Provider,
    StructuredAnswer,
    StructuredRequest,
    Usage,
    get_provider,
    provider_spec,
)

__all__ = [
    "PROVIDER_SHORTCUTS",
    "Provider",
    "StructuredAnswer",
    "StructuredRequest",
    "Usage",
    "get_provider",
    "provider_spec",
]
