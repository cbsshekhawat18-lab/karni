"""The Anthropic provider: the Messages API with a JSON-schema output format.

One ``messages.create`` call with ``output_config={"format": {"type":
"json_schema", "schema": ...}}``. The schema goes through the SDK's own
``anthropic.transform_schema`` first, which moves the constraints the API does
not take (lengths, patterns, bounds) into the descriptions. Karni validates
the answer against the full schema afterwards anyway.

The ``anthropic`` SDK is an extra (``pip install "karni-ai[anthropic]"``),
imported at the first call. ``ANTHROPIC_API_KEY`` and ``ANTHROPIC_MODEL`` are
read per call. There is no default model. A declined answer
(``stop_reason == "refusal"``) or one cut off at ``max_tokens`` is AI007, with
the tokens it used.

Override / escape hatch: subclass and override :meth:`request_params` (to add
``thinking``, ``output_config.effort`` or a beta) or :meth:`http_client`,
then point ``KARNI_AI_PROVIDER`` at the subclass.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from karni.exceptions import KarniImproperlyConfigured

from karni_ai import conf
from karni_ai.exceptions import ProviderError
from karni_ai.providers.base import Provider, StructuredAnswer, StructuredRequest, Usage

__all__ = ["AnthropicProvider"]

_INSTALL = 'pip install "karni-ai[anthropic]"'


def _sdk() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"The anthropic provider needs the anthropic SDK. Install the extra: {_INSTALL}.",
            code="AI003",
        ) from exc
    return anthropic


def _installed() -> bool:
    try:
        _sdk()
    except KarniImproperlyConfigured:
        return False
    return True


class AnthropicProvider(Provider):
    """Experimental. Claude through the Anthropic Messages API (structured outputs)."""

    name: ClassVar[str] = "anthropic"

    def model(self) -> str:
        return str(conf.get("ANTHROPIC_MODEL") or "").strip()

    def api_key(self) -> str:
        return str(conf.get("ANTHROPIC_API_KEY") or "").strip()

    def problems(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if not _installed():
            found.append(("AI003", f"the anthropic SDK is not installed: {_INSTALL}"))
        if not self.api_key():
            found.append(("AI004", "ANTHROPIC_API_KEY is not set (set it in the environment)"))
        if not self.model():
            found.append(
                ("AI005", "ANTHROPIC_MODEL is not set: there is no default model, name one")
            )
        return found

    def http_client(self) -> Any | None:
        """The ``httpx2.Client`` the SDK sends through (``None``: the SDK's own)."""
        return None

    def client(self, request: StructuredRequest) -> Any:
        """The SDK client for one call, with the key, timeout and retries from settings."""
        for code, message in self.problems():
            raise KarniImproperlyConfigured(f"The anthropic provider: {message}.", code=code)
        options: dict[str, Any] = {
            "api_key": self.api_key(),
            "timeout": request.timeout,
            "max_retries": request.max_retries,
        }
        http_client = self.http_client()
        if http_client is not None:
            options["http_client"] = http_client
        return _sdk().Anthropic(**options)

    def request_params(self, request: StructuredRequest) -> dict[str, Any]:
        """The keyword arguments of ``messages.create``."""
        return {
            "model": self.model(),
            "max_tokens": request.max_output_tokens,
            "system": request.instructions,
            "messages": [{"role": "user", "content": request.source}],
            "output_config": {
                "format": {"type": "json_schema", "schema": _sdk().transform_schema(request.schema)}
            },
        }

    def structured(self, request: StructuredRequest) -> StructuredAnswer:
        sdk = _sdk()
        client = self.client(request)
        try:
            message = client.messages.create(**self.request_params(request))
        except sdk.APIStatusError as exc:
            raise ProviderError(
                f"Anthropic answered HTTP {exc.status_code}: {_detail(exc)}", code="AI006"
            ) from exc
        except sdk.APIConnectionError as exc:  # timeouts included
            raise ProviderError(f"Anthropic could not be reached: {exc}", code="AI006") from exc
        usage = _usage(message.usage)
        if message.stop_reason == "refusal":
            raise ProviderError("The model declined to answer.", code="AI007", usage=usage)
        if message.stop_reason == "max_tokens":
            raise ProviderError(
                "The answer was cut off at KARNI_AI_MAX_OUTPUT_TOKENS "
                f"({request.max_output_tokens}). Send a shorter source or raise the limit.",
                code="AI007",
                usage=usage,
            )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProviderError("The answer is not JSON.", code="AI007", usage=usage) from exc
        return StructuredAnswer(data=data, usage=usage, model=str(message.model), raw=text)


def _usage(usage: Any) -> Usage:
    """Every input token the call billed (cache writes and reads included) and its output."""
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    for name in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        input_tokens += int(getattr(usage, name, 0) or 0)
    return Usage(input_tokens, int(getattr(usage, "output_tokens", 0) or 0))


def _detail(exc: Any) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(getattr(exc, "message", "") or exc)
