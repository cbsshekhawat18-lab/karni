"""Tests for karni.conf.sentry: the same privacy on sentry-sdk 2 and 3."""

from __future__ import annotations

import inspect
from typing import Any

import environ
import pytest

from karni.conf.sentry import SENTRY_3_DATA_COLLECTION, maybe_init_sentry, privacy_options

sentry_sdk = pytest.importorskip("sentry_sdk")


def test_sentry_sdk_2_gets_the_one_switch() -> None:
    assert privacy_options("2.0.0") == {"send_default_pii": False}
    assert privacy_options("2.75.0") == {"send_default_pii": False}


def test_sentry_sdk_3_gets_data_collection_and_no_removed_option() -> None:
    options = privacy_options("3.0.1")
    assert "send_default_pii" not in options
    collection = options["data_collection"]
    assert collection["user_info"] is False
    assert collection["cookies"] == {"mode": "off"}
    assert collection["http_bodies"] == ["incoming_request"]
    assert collection["gen_ai"] == {"inputs": False, "outputs": False}
    assert collection["mcp"] == {"inputs": False, "outputs": False}


def test_each_call_gets_its_own_copy() -> None:
    privacy_options("3.0.1")["data_collection"]["user_info"] = True
    assert SENTRY_3_DATA_COLLECTION["user_info"] is False


def test_a_version_that_is_not_a_number_is_treated_as_sentry_sdk_2() -> None:
    assert privacy_options("unknown") == {"send_default_pii": False}


def test_the_installed_sdk_accepts_the_options_karni_passes() -> None:
    """The check that failed a release: an option the installed SDK removed."""
    accepted = inspect.signature(sentry_sdk.consts.ClientConstructor.__init__).parameters
    for name in privacy_options(sentry_sdk.VERSION):
        assert name in accepted, f"sentry-sdk {sentry_sdk.VERSION} has no option {name!r}"
    for name in ("dsn", "integrations", "traces_sample_rate", "environment"):
        assert name in accepted


def test_no_dsn_means_no_init(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: calls.append(options))
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    maybe_init_sentry(environ.Env())
    assert calls == []


def test_a_dsn_inits_the_installed_sdk_with_its_privacy_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: calls.append(options))
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.invalid/1")
    monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.25")
    monkeypatch.setenv("DJANGO_ENV", "prod")
    maybe_init_sentry(environ.Env())
    assert len(calls) == 1
    options = calls[0]
    assert options["dsn"] == "https://public@sentry.invalid/1"
    assert options["traces_sample_rate"] == 0.25
    assert options["environment"] == "prod"
    assert len(options["integrations"]) == 2
    for name, value in privacy_options(sentry_sdk.VERSION).items():
        assert options[name] == value
