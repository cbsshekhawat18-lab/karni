"""The provider contract: one structured answer for a JSON schema, with the tokens it used.

A provider turns a :class:`StructuredRequest` (instructions, the source text,
the JSON Schema the answer must follow) into a :class:`StructuredAnswer` (the
decoded JSON, the :class:`Usage` and the model that answered). It knows
nothing about Django models, imports or budgets: :mod:`karni_ai.extraction`
does that around it.

Implementations:

* :meth:`Provider.structured` asks the model and returns the answer, raising
  :class:`karni_ai.exceptions.ProviderError` (AI006 for a failed call, AI007
  for an answer that cannot be used: declined, cut off, not JSON);
* :meth:`Provider.problems` lists what keeps it from working in this project
  (a missing SDK, key or model name), for ``karni check``;
* :attr:`Provider.name` is the short name the usage log records.

The model name and the API key are read per call through
:func:`karni_ai.conf.get`, never from code, so ``override_settings`` works in
tests and nothing is checked at boot.

Override / escape hatch: set ``KARNI_AI_PROVIDER`` to ``"anthropic"``,
``"openai"``, ``"test"`` or the dotted path of your own :class:`Provider`
subclass. The instance is cached per value and the cache is reset whenever a
``KARNI_AI_*`` setting changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from django.test.signals import setting_changed
from django.utils.module_loading import import_string
from karni.exceptions import KarniImproperlyConfigured

from karni_ai import conf

__all__ = [
    "PROVIDER_SHORTCUTS",
    "Provider",
    "StructuredAnswer",
    "StructuredRequest",
    "Usage",
    "get_provider",
    "provider_spec",
]


@dataclass(frozen=True)
class Usage:
    """Experimental. The tokens one provider call used, as the provider reported them."""

    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class StructuredRequest:
    """Experimental. What a provider is asked.

    ``instructions`` is the system prompt, ``source`` the text to read (data,
    never instructions), ``schema`` the JSON Schema the answer must follow and
    ``name`` a short identifier of that schema (some APIs require one).
    """

    instructions: str
    source: str
    schema: dict[str, Any]
    name: str = "extraction"
    max_output_tokens: int = 16000
    timeout: float = 60.0
    max_retries: int = 1


@dataclass(frozen=True)
class StructuredAnswer:
    """Experimental. A provider's answer: the decoded JSON, its usage and the model that gave it."""

    data: Any
    usage: Usage
    model: str
    raw: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Provider(ABC):
    """Experimental. A language model behind one API.

    Subclass it to use a provider Karni does not ship: give it a unique
    ``name``, implement :meth:`structured` (and :meth:`problems` when it needs
    settings), and point ``KARNI_AI_PROVIDER`` at its dotted path.
    """

    name: ClassVar[str]
    """The short name the usage log records (``anthropic``)."""

    def model(self) -> str:
        """The model name this provider asks, from settings (``""`` when not set)."""
        return ""

    @abstractmethod
    def structured(self, request: StructuredRequest) -> StructuredAnswer:
        """Ask the model for JSON following ``request.schema``.

        :raises karni_ai.exceptions.ProviderError: AI006 when the call fails,
            AI007 when the answer is declined, cut off or not JSON.
        """

    def problems(self) -> list[tuple[str, str]]:
        """``(code, message)`` for each setting or package this provider lacks (``karni check``)."""
        return []


PROVIDER_SHORTCUTS: dict[str, str] = {
    "anthropic": "karni_ai.providers.anthropic.AnthropicProvider",
    "openai": "karni_ai.providers.openai.OpenAIProvider",
    "test": "karni_ai.providers.test.TestProvider",
}
"""Experimental. The names ``KARNI_AI_PROVIDER`` takes besides a dotted path."""

_cache: dict[str, Provider] = {}


def provider_spec() -> str:
    """``KARNI_AI_PROVIDER`` as set, stripped (``""`` when it is not)."""
    return str(conf.get("KARNI_AI_PROVIDER") or "").strip()


def get_provider(spec: str | None = None) -> Provider:
    """Experimental. The provider ``KARNI_AI_PROVIDER`` names (or ``spec``), cached per value.

    :raises KarniImproperlyConfigured: AI001 when nothing is set, AI002 when
        the value is neither a shortcut nor a ``Provider`` subclass.
    """
    value = (spec if spec is not None else provider_spec()).strip()
    if not value:
        raise KarniImproperlyConfigured(
            "KARNI_AI_PROVIDER is not set, and karni-ai has no default provider. Set it to "
            "'anthropic', 'openai' or 'test' (no network), or to the dotted path of a "
            "karni_ai.providers.base.Provider subclass.",
            code="AI001",
        )
    cached = _cache.get(value)
    if cached is not None:
        return cached
    path = PROVIDER_SHORTCUTS.get(value, value)
    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"KARNI_AI_PROVIDER {value!r} cannot be imported: {exc}", code="AI002"
        ) from exc
    if not (isinstance(provider_class, type) and issubclass(provider_class, Provider)):
        raise KarniImproperlyConfigured(
            f"KARNI_AI_PROVIDER {value!r} must name a karni_ai.providers.base.Provider subclass.",
            code="AI002",
        )
    instance = provider_class()
    _cache[value] = instance
    return instance


def _reset_cache(sender: object, setting: str, **kwargs: Any) -> None:
    if setting.startswith("KARNI_AI"):
        _cache.clear()


setting_changed.connect(_reset_cache, dispatch_uid="karni_ai.providers.cache_reset")
