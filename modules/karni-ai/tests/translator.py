"""A plain translation service, as a project would write its provider: a job other than
extraction. It reads no schema, takes the target language from the request's metadata,
answers ``{"text": ...}`` and bills characters, not tokens."""

from __future__ import annotations

from typing import ClassVar

from karni_ai.models import AICall
from karni_ai.providers.base import (
    Provider,
    StructuredAnswer,
    StructuredRequest,
    Usage,
    get_provider,
)
from karni_ai.usage import log_call

PATH = "tests.translator.Translator"
CHARACTERS = "characters"


class Translator(Provider):
    """Prefixes the text with the target language: ``[fr] Garden hose``."""

    name: ClassVar[str] = "translator"
    requests: ClassVar[list[StructuredRequest]] = []

    def model(self) -> str:
        return "mt-test"

    def structured(self, request: StructuredRequest) -> StructuredAnswer:
        type(self).requests.append(request)
        text = f"[{request.metadata['target_language']}] {request.source}"
        return StructuredAnswer(
            data={"text": text},
            usage=Usage(len(request.source), len(text), unit=CHARACTERS),
            model=self.model(),
        )


def translate(text: str, target: str, user: object = None) -> tuple[str, AICall]:
    """The project's translation job: the provider, then the call in karni-ai's log."""
    provider = get_provider(PATH)
    answer = provider.structured(
        StructuredRequest(
            instructions="",
            source=text,
            schema={},
            name="translation",
            metadata={"target_language": target},
        )
    )
    call = log_call(
        user=user,
        provider=provider.name,
        model=answer.model,
        resource="testapp.product",
        source="text",
        usage=answer.usage,
        kind="translation",
    )
    return str(answer.data["text"]), call
