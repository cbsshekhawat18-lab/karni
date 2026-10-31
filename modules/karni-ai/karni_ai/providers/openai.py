"""The OpenAI provider: the Responses API with a strict JSON-schema text format.

One ``responses.create`` call with ``text={"format": {"type": "json_schema",
"strict": True, ...}}``. Strict mode needs every property listed in
``required``, so :func:`strict_schema` makes an optional property nullable
instead (a null is read as "not in the source"), and it moves the keywords
strict mode does not take (lengths, patterns, bounds, formats) into the
description. Karni validates the answer against the full schema afterwards.

The ``openai`` SDK is an extra (``pip install "karni-ai[openai]"``), imported
at the first call. ``OPENAI_API_KEY`` and ``OPENAI_MODEL`` are read per call.
There is no default model. A refusal, or an answer cut off at
``max_output_tokens``, is AI007 with the tokens it used.

Override / escape hatch: subclass and override :meth:`request_params` (for
``reasoning`` or ``service_tier``) or :meth:`http_client`, then point
``KARNI_AI_PROVIDER`` at the subclass.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

from karni.exceptions import KarniImproperlyConfigured

from karni_ai import conf
from karni_ai.exceptions import ProviderError
from karni_ai.providers.base import Provider, StructuredAnswer, StructuredRequest, Usage

__all__ = ["OpenAIProvider", "strict_schema"]

_INSTALL = 'pip install "karni-ai[openai]"'

#: The keywords a strict schema keeps; any other is described in words.
_KEPT: Final = frozenset(
    {"type", "properties", "required", "items", "enum", "anyOf", "description", "const"}
)


def _sdk() -> Any:
    try:
        import openai
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"The openai provider needs the openai SDK. Install the extra: {_INSTALL}.",
            code="AI003",
        ) from exc
    return openai


def _installed() -> bool:
    try:
        _sdk()
    except KarniImproperlyConfigured:
        return False
    return True


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Experimental. ``schema`` as OpenAI's strict mode takes it.

    Every object lists all its properties as required and refuses others; a
    property that was optional may be null; keywords outside the strict subset
    move into the description (``maxLength: 120``).
    """
    out: dict[str, Any] = {}
    notes: list[str] = []
    for key, value in schema.items():
        if key == "properties":
            continue
        if key == "items" and isinstance(value, dict):
            out["items"] = strict_schema(value)
        elif key == "anyOf" and isinstance(value, list):
            out["anyOf"] = [strict_schema(part) for part in value]
        elif key in _KEPT:
            out[key] = value
        elif key != "additionalProperties":
            notes.append(f"{key}: {value}")
    if isinstance(schema.get("properties"), dict):
        required = set(schema.get("required") or ())
        properties: dict[str, Any] = {}
        for name, part in schema["properties"].items():
            converted = strict_schema(part)
            if name not in required:
                converted = {"anyOf": [converted, {"type": "null"}]}
            properties[name] = converted
        out["properties"] = properties
        out["required"] = list(properties)
        out["additionalProperties"] = False
    if notes:
        description = str(out.get("description") or "")
        out["description"] = f"{description} ({', '.join(notes)})".strip()
    return out


class OpenAIProvider(Provider):
    """Experimental. OpenAI models through the Responses API (structured outputs)."""

    name: ClassVar[str] = "openai"

    def model(self) -> str:
        return str(conf.get("OPENAI_MODEL") or "").strip()

    def api_key(self) -> str:
        return str(conf.get("OPENAI_API_KEY") or "").strip()

    def problems(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        if not _installed():
            found.append(("AI003", f"the openai SDK is not installed: {_INSTALL}"))
        if not self.api_key():
            found.append(("AI004", "OPENAI_API_KEY is not set (set it in the environment)"))
        if not self.model():
            found.append(("AI005", "OPENAI_MODEL is not set: there is no default model, name one"))
        return found

    def http_client(self) -> Any | None:
        """The ``httpx2.Client`` the SDK sends through (``None``: the SDK's own)."""
        return None

    def client(self, request: StructuredRequest) -> Any:
        """The SDK client for one call, with the key, timeout and retries from settings."""
        for code, message in self.problems():
            raise KarniImproperlyConfigured(f"The openai provider: {message}.", code=code)
        options: dict[str, Any] = {
            "api_key": self.api_key(),
            "timeout": request.timeout,
            "max_retries": request.max_retries,
        }
        http_client = self.http_client()
        if http_client is not None:
            options["http_client"] = http_client
        return _sdk().OpenAI(**options)

    def request_params(self, request: StructuredRequest) -> dict[str, Any]:
        """The keyword arguments of ``responses.create``."""
        return {
            "model": self.model(),
            "instructions": request.instructions,
            "input": request.source,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": request.name,
                    "schema": strict_schema(request.schema),
                    "strict": True,
                }
            },
        }

    def structured(self, request: StructuredRequest) -> StructuredAnswer:
        sdk = _sdk()
        client = self.client(request)
        try:
            response = client.responses.create(**self.request_params(request))
        except sdk.APIStatusError as exc:
            raise ProviderError(
                f"OpenAI answered HTTP {exc.status_code}: {_detail(exc)}", code="AI006"
            ) from exc
        except sdk.APIConnectionError as exc:  # timeouts included
            raise ProviderError(f"OpenAI could not be reached: {exc}", code="AI006") from exc
        raw_usage = getattr(response, "usage", None)
        usage = Usage(
            int(getattr(raw_usage, "input_tokens", 0) or 0),
            int(getattr(raw_usage, "output_tokens", 0) or 0),
        )
        if getattr(response, "status", None) == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "unknown"
            raise ProviderError(
                f"The answer is incomplete ({reason}). With max_output_tokens, raise "
                f"KARNI_AI_MAX_OUTPUT_TOKENS ({request.max_output_tokens}) or send a shorter "
                "source.",
                code="AI007",
                usage=usage,
            )
        for item in getattr(response, "output", None) or ():
            for content in getattr(item, "content", None) or ():
                if getattr(content, "type", "") == "refusal":
                    raise ProviderError(
                        f"The model declined to answer: {getattr(content, 'refusal', '')}",
                        code="AI007",
                        usage=usage,
                    )
        text = str(response.output_text)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise ProviderError("The answer is not JSON.", code="AI007", usage=usage) from exc
        return StructuredAnswer(
            data=data, usage=usage, model=str(getattr(response, "model", "") or ""), raw=text
        )


def _detail(exc: Any) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(getattr(exc, "message", "") or exc)
