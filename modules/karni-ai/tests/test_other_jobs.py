"""Jobs other than extraction: a project's translation provider (tests/translator.py) takes
its parameters from the request's metadata, its calls are logged with their own kind and
unit, and the cost and the token budgets never mix units."""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from pytest_django import Settings

from karni_ai.exceptions import ExtractionRefused
from karni_ai.models import AICall
from karni_ai.providers.base import TOKENS, StructuredRequest, Usage
from karni_ai.usage import check_budget, cost_of, log_call, spent
from tests.translator import CHARACTERS, Translator, translate

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_translator() -> None:
    Translator.requests = []


def test_a_translation_job_passes_its_parameters_to_its_provider() -> None:
    text, _call = translate("Garden hose", "fr")
    assert text == "[fr] Garden hose"
    (request,) = Translator.requests
    assert request.metadata == {"target_language": "fr"}
    assert request.source == "Garden hose"  # the parameter no longer travels in the source


def test_the_request_and_the_usage_are_as_before_without_the_new_fields() -> None:
    request = StructuredRequest(instructions="i", source="s", schema={})
    assert request.metadata == {}
    assert [f.name for f in dataclasses.fields(request)][-1] == "metadata"
    assert Usage(3, 4) == Usage(3, 4, unit=TOKENS) and Usage(3, 4).total == 7


@pytest.mark.parametrize("name", ["anthropic", "openai"])
def test_the_shipped_providers_ignore_the_metadata(name: str) -> None:
    pytest.importorskip(name)
    from karni_ai.providers.base import get_provider

    plain = StructuredRequest(instructions="i", source="s", schema={"type": "object"})
    tagged = dataclasses.replace(plain, metadata={"target_language": "fr"})
    provider: Any = get_provider(name)
    assert provider.request_params(tagged) == provider.request_params(plain)


def test_the_call_is_logged_with_its_kind_and_unit(client_for: Any, editor: Any) -> None:
    _text, call = translate("Garden hose", "fr", user=editor)
    call.refresh_from_db()
    assert (call.kind, call.source, call.unit) == ("translation", "text", CHARACTERS)
    assert (call.input_tokens, call.output_tokens) == (11, 16)
    (listed,) = client_for(editor).get("/api/ai/").json()["results"]
    assert (listed["kind"], listed["unit"]) == ("translation", CHARACTERS)


def test_the_admin_shows_the_job_and_each_count_with_its_unit() -> None:
    from django.contrib.auth import get_user_model
    from django.test import Client

    translate("Garden hose", "fr")
    log_call(user=None, provider="test", model="test", resource="products", source="text",
             usage=Usage(812, 96))  # fmt: skip
    client = Client()
    client.force_login(get_user_model().objects.create_superuser(email="r@example.com"))
    page = client.get("/admin/karni_ai/aicall/").content.decode()
    for shown in ("translation", "11 characters", "16 characters", "extraction", "812 tokens"):
        assert shown in page, shown
    only = client.get("/admin/karni_ai/aicall/", {"kind": "translation"}).context["cl"]
    assert [call.kind for call in only.result_list] == ["translation"]


def test_units_never_mix_in_the_cost(settings: Settings) -> None:
    usage = Usage(1_000_000, 500_000, unit=CHARACTERS)
    settings.KARNI_AI_PRICES = {"mt-test": {"unit": CHARACTERS, "input": "20.00", "output": "0"}}
    assert cost_of("mt-test", usage) == Decimal("20.000000")
    settings.KARNI_AI_PRICES = {"mt-test": {"input": "20.00", "output": "0"}}  # per token
    assert cost_of("mt-test", usage) is None
    assert cost_of("mt-test", Usage(1_000_000, 0)) == Decimal("20.000000")


def test_units_never_mix_in_the_token_budgets(settings: Settings, editor: Any) -> None:
    settings.KARNI_AI_MONTHLY_TOKENS = 100
    settings.KARNI_AI_MONTHLY_TOKENS_PER_USER = 100
    for _ in range(3):
        translate("A long paragraph of plain text to translate. " * 10, "fr", user=editor)
    assert spent() == 0 and spent(editor) == 0
    assert spent(unit=CHARACTERS) > 100
    check_budget(editor)  # characters never use up a token budget
    log_call(
        user=editor,
        provider="test",
        model="test",
        resource="products",
        source="text",
        usage=Usage(60, 40),
    )
    assert spent(editor) == 100
    with pytest.raises(ExtractionRefused) as refused:
        check_budget(editor)
    assert refused.value.code == "AI013"


def test_a_call_written_without_them_is_an_extraction_in_tokens() -> None:
    call = AICall.objects.create(provider="test", model="test", resource="products", source="pdf")
    assert (call.kind, call.unit) == ("extraction", TOKENS)


@pytest.mark.django_db(transaction=True)
def test_the_migration_leaves_old_calls_as_extractions_in_tokens(
    request: pytest.FixtureRequest,
) -> None:
    if request.config.getoption("nomigrations", default=False):
        pytest.skip("runs karni_ai's migrations, which --no-migrations turns off")
    before, after = [("karni_ai", "0001_initial")], [("karni_ai", "0002_call_kind_and_unit")]
    executor = MigrationExecutor(connection)
    try:
        executor.migrate(before)
        executor.loader.build_graph()
        old = executor.loader.project_state(before).apps.get_model("karni_ai", "AICall")
        row = old.objects.create(
            provider="openai", model="m", resource="products", source="url", input_tokens=7
        )
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        executor.loader.build_graph()
        new = executor.loader.project_state(after).apps.get_model("karni_ai", "AICall")
        found = new.objects.get(pk=row.pk)
        assert (found.kind, found.unit, found.source, found.input_tokens) == (
            "extraction",
            TOKENS,
            "url",
            7,
        )
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
