"""The providers: resolution, the test provider, and both real ones over mocked HTTP (no network).

The anthropic and openai providers run their real SDKs against an
``httpx2.MockTransport``, so each test sees the exact request the SDK sends
and parses a response shaped like the API's. No key, no network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.test import override_settings
from karni.exceptions import KarniImproperlyConfigured

from karni_ai.exceptions import ProviderError
from karni_ai.providers.base import StructuredRequest, Usage, get_provider
from karni_ai.providers.test import TestProvider

httpx2 = pytest.importorskip("httpx2")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "title": "product",
                "properties": {
                    "name": {"type": "string", "maxLength": 120, "title": "Name"},
                    "price": {"type": "string", "pattern": "^\\d+(\\.\\d{1,2})?$"},
                    "stock": {"type": "integer", "minimum": 0},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rows"],
    "additionalProperties": False,
}

REQUEST = StructuredRequest(
    instructions="Return the products.",
    source="<source>\nName: Hose\n</source>",
    schema=SCHEMA,
    name="product_rows",
    max_output_tokens=512,
    timeout=5,
    max_retries=0,
)

Handler = Callable[[Any], Any]


def _mocked(provider_class: type, handler: Handler) -> Any:
    class Mocked(provider_class):
        def http_client(self) -> Any:
            return httpx2.Client(transport=httpx2.MockTransport(handler))

    return Mocked()


# resolution


def test_shortcuts_resolve_and_are_cached() -> None:
    with override_settings(KARNI_AI_PROVIDER="test"):
        provider = get_provider()
        assert isinstance(provider, TestProvider) and get_provider() is provider
    assert get_provider("anthropic").name == "anthropic"
    assert get_provider("openai").name == "openai"


@pytest.mark.parametrize(
    ("spec", "code"),
    [("", "AI001"), ("   ", "AI001"), ("no.such.Thing", "AI002"), ("karni_ai.conf.get", "AI002")],
)
def test_bad_provider_settings(spec: str, code: str) -> None:
    with override_settings(KARNI_AI_PROVIDER=spec), pytest.raises(KarniImproperlyConfigured) as exc:
        get_provider()
    assert exc.value.code == code


def test_a_dotted_path_names_a_custom_provider() -> None:
    path = "karni_ai.providers.test.TestProvider"
    with override_settings(KARNI_AI_PROVIDER=path):
        assert get_provider().name == "test"


# the test provider


def test_the_test_provider_reads_field_value_lines() -> None:
    source = "Name: Hose\nStock: 4\nTags: a, b\nColour: green\n\nNAME: Rake\nnot a field line"
    answer = TestProvider().structured(
        StructuredRequest(instructions="", source=source, schema=SCHEMA)
    )
    assert answer.data == {
        "rows": [{"name": "Hose", "stock": 4, "tags": ["a", "b"]}, {"name": "Rake"}]
    }
    assert answer.model == "test" and answer.usage.input_tokens > 0
    assert answer.usage.output_tokens == -(-len(answer.raw) // 4)


def test_the_test_provider_plays_its_queue_then_reads_again() -> None:
    TestProvider.answer_with({"rows": "wrong"})
    TestProvider.fail_with(ProviderError("down", usage=Usage(1, 0)))
    provider = TestProvider()
    assert provider.structured(REQUEST).data == {"rows": "wrong"}
    with pytest.raises(ProviderError):
        provider.structured(REQUEST)
    assert provider.structured(REQUEST).data == {"rows": [{"name": "Hose"}]}
    assert len(TestProvider.calls) == 3


# anthropic


def _message(text: str, *, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-test-model",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 5,
        },
    }


ANTHROPIC = {"ANTHROPIC_API_KEY": "sk-test-not-real", "ANTHROPIC_MODEL": "claude-test-model"}


@override_settings(**ANTHROPIC)
def test_anthropic_request_and_response_shape() -> None:
    from karni_ai.providers.anthropic import AnthropicProvider

    seen: list[Any] = []

    def handler(request: Any) -> Any:
        seen.append(request)
        return httpx2.Response(200, json=_message('{"rows": [{"name": "Hose"}]}'))

    answer = _mocked(AnthropicProvider, handler).structured(REQUEST)
    assert answer.data == {"rows": [{"name": "Hose"}]}
    assert answer.usage == Usage(125, 30) and answer.model == "claude-test-model"
    (request,) = seen
    assert request.method == "POST" and request.url.path == "/v1/messages"
    assert "sk-test-not-real" in request.headers.get(
        "authorization", request.headers.get("x-api-key", "")
    )
    assert request.headers["anthropic-version"]
    body = json.loads(request.content)
    assert body["model"] == "claude-test-model" and body["max_tokens"] == 512
    assert body["system"] == "Return the products."
    assert body["messages"] == [{"role": "user", "content": REQUEST.source}]
    output = body["output_config"]["format"]
    assert output["type"] == "json_schema"
    row = output["schema"]["properties"]["rows"]["items"]
    assert row["additionalProperties"] is False and row["required"] == ["name"]
    # The SDK moves what the API does not take into the description.
    assert "maxLength" not in row["properties"]["name"]
    assert "120" in row["properties"]["name"]["description"]


@override_settings(**ANTHROPIC)
@pytest.mark.parametrize(
    ("payload", "status", "code", "fragment"),
    [
        (_message("{}", stop="refusal"), 200, "AI007", "declined"),
        (_message('{"rows": [', stop="max_tokens"), 200, "AI007", "cut off"),
        (_message("not json"), 200, "AI007", "not JSON"),
        (
            {"type": "error", "error": {"type": "invalid_request_error", "message": "bad model"}},
            400,
            "AI006",
            "bad model",
        ),
    ],
)
def test_anthropic_failures(payload: dict[str, Any], status: int, code: str, fragment: str) -> None:
    from karni_ai.providers.anthropic import AnthropicProvider

    provider = _mocked(AnthropicProvider, lambda request: httpx2.Response(status, json=payload))
    with pytest.raises(ProviderError) as exc:
        provider.structured(REQUEST)
    assert exc.value.code == code and fragment in exc.value.message
    if status == 200:
        assert exc.value.usage == Usage(125, 30)


@override_settings(**ANTHROPIC)
def test_anthropic_unreachable_is_ai006() -> None:
    from karni_ai.providers.anthropic import AnthropicProvider

    def handler(request: Any) -> Any:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as exc:
        _mocked(AnthropicProvider, handler).structured(REQUEST)
    assert exc.value.code == "AI006" and exc.value.usage == Usage(0, 0)


def test_anthropic_problems_name_the_missing_settings() -> None:
    from karni_ai.providers.anthropic import AnthropicProvider

    with override_settings(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL=""):
        codes = [code for code, _ in AnthropicProvider().problems()]
        assert codes == ["AI004", "AI005"]
        with pytest.raises(KarniImproperlyConfigured) as exc:
            AnthropicProvider().structured(REQUEST)
        assert exc.value.code == "AI004"
    with override_settings(**ANTHROPIC):
        assert AnthropicProvider().problems() == []


# openai


def _response(text: str, *, status: str = "completed", refusal: str = "") -> dict[str, Any]:
    content: list[dict[str, Any]] = (
        [{"type": "refusal", "refusal": refusal}]
        if refusal
        else [{"type": "output_text", "text": text, "annotations": []}]
    )
    return {
        "id": "resp_01",
        "object": "response",
        "created_at": 1767225600,
        "status": status,
        "model": "gpt-test-model",
        "output": [
            {
                "type": "message",
                "id": "msg_01",
                "status": "completed",
                "role": "assistant",
                "content": content,
            }
        ],
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 200,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 40,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 240,
        },
    }


OPENAI = {"OPENAI_API_KEY": "sk-test-not-real", "OPENAI_MODEL": "gpt-test-model"}


@override_settings(**OPENAI)
def test_openai_request_and_response_shape() -> None:
    from karni_ai.providers.openai import OpenAIProvider

    seen: list[Any] = []

    def handler(request: Any) -> Any:
        seen.append(request)
        return httpx2.Response(200, json=_response('{"rows": [{"name": "Hose", "stock": null}]}'))

    answer = _mocked(OpenAIProvider, handler).structured(REQUEST)
    assert answer.data == {"rows": [{"name": "Hose", "stock": None}]}
    assert answer.usage == Usage(200, 40) and answer.model == "gpt-test-model"
    (request,) = seen
    assert request.method == "POST" and request.url.path == "/v1/responses"
    assert request.headers["authorization"] == "Bearer sk-test-not-real"
    body = json.loads(request.content)
    assert body["model"] == "gpt-test-model" and body["max_output_tokens"] == 512
    assert body["instructions"] == "Return the products." and body["input"] == REQUEST.source
    assert body["store"] is False
    text_format = body["text"]["format"]
    assert text_format["type"] == "json_schema" and text_format["strict"] is True
    assert text_format["name"] == "product_rows"
    row = text_format["schema"]["properties"]["rows"]["items"]
    # Strict mode: every property required, the optional ones nullable.
    assert row["required"] == ["name", "price", "stock", "tags"]
    assert row["properties"]["stock"]["anyOf"][1] == {"type": "null"}
    assert row["properties"]["name"] == {
        "type": "string",
        "title": "Name",
        "description": "(maxLength: 120)",
    }
    assert row["properties"]["stock"]["anyOf"][0]["description"] == "(minimum: 0)"


@override_settings(**OPENAI)
@pytest.mark.parametrize(
    ("payload", "status", "code", "fragment"),
    [
        (_response("", refusal="I can't help with that."), 200, "AI007", "declined"),
        (_response('{"rows": [', status="incomplete"), 200, "AI007", "max_output_tokens"),
        (_response("not json"), 200, "AI007", "not JSON"),
        (
            {"error": {"message": "invalid model", "type": "invalid_request_error"}},
            404,
            "AI006",
            "invalid model",
        ),
    ],
)
def test_openai_failures(payload: dict[str, Any], status: int, code: str, fragment: str) -> None:
    from karni_ai.providers.openai import OpenAIProvider

    provider = _mocked(OpenAIProvider, lambda request: httpx2.Response(status, json=payload))
    with pytest.raises(ProviderError) as exc:
        provider.structured(REQUEST)
    assert exc.value.code == code and fragment in exc.value.message
    if status == 200:
        assert exc.value.usage == Usage(200, 40)


def test_strict_schema_keeps_the_strict_subset() -> None:
    from karni_ai.providers.openai import strict_schema

    converted = strict_schema(SCHEMA)
    row = converted["properties"]["rows"]["items"]
    assert converted["required"] == ["rows"] and converted["additionalProperties"] is False
    assert row["properties"]["name"]["type"] == "string"
    assert "pattern" not in row["properties"]["price"]["anyOf"][0]
    assert "pattern" in row["properties"]["price"]["anyOf"][0]["description"]
    assert row["properties"]["tags"]["anyOf"][0]["items"] == {"type": "string"}
