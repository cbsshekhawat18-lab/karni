"""``karni check`` fails while the provider, its model name or its key is missing."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from karni_ai import checks


def test_the_test_provider_needs_nothing_else() -> None:
    assert checks.run_checks() == []


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"KARNI_AI_PROVIDER": ""}, ["AI001"]),
        ({"KARNI_AI_PROVIDER": "nowhere.Provider"}, ["AI002"]),
        (
            {"KARNI_AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": ""},
            ["AI004", "AI005"],
        ),
        (
            {"KARNI_AI_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": ""},
            ["AI005"],
        ),
        (
            {"KARNI_AI_PROVIDER": "openai", "OPENAI_API_KEY": "", "OPENAI_MODEL": "m"},
            ["AI004"],
        ),
        (
            {"KARNI_AI_PROVIDER": "openai", "OPENAI_API_KEY": "k", "OPENAI_MODEL": "m"},
            [],
        ),
    ],
)
def test_each_missing_piece_is_one_failure(settings: dict[str, str], expected: list[str]) -> None:
    with override_settings(**settings):
        failures = checks.run_checks()
    assert [failure.split(":", 1)[0] for failure in failures] == expected


def test_the_message_names_the_setting() -> None:
    with override_settings(KARNI_AI_PROVIDER="openai", OPENAI_API_KEY="", OPENAI_MODEL=""):
        failures = checks.run_checks()
    assert "OPENAI_API_KEY" in failures[0] and "no default model" in failures[1]


def test_a_missing_sdk_is_ai003(monkeypatch: Any) -> None:
    import builtins

    real_import = builtins.__import__

    def no_anthropic(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    with override_settings(
        KARNI_AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
    ):
        failures = checks.run_checks()
    assert failures and failures[0].startswith("AI003") and "karni-ai[anthropic]" in failures[0]


def test_nothing_is_checked_when_the_app_is_not_in_the_project() -> None:
    from django.apps import apps

    with override_settings(KARNI_AI_PROVIDER=""):
        apps.set_available_apps(["django.contrib.auth", "django.contrib.contenttypes"])
        try:
            assert checks.run_checks() == []
        finally:
            apps.unset_available_apps()
