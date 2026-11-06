"""The system check warnings print as one line for ``karni <command>`` (``karni.check_output``)."""

from __future__ import annotations

import io
from collections.abc import Iterator

import pytest
from django.core import checks
from django.core.checks.registry import registry
from django.core.management.base import BaseCommand, OutputWrapper, SystemCheckError

from karni import check_output


@pytest.fixture
def three_warnings() -> Iterator[None]:
    def warn(app_configs: object, **kwargs: object) -> list[checks.CheckMessage]:
        return [
            checks.Warning("first thing is odd.", hint="Fix it.", id="karni.W101"),
            checks.Warning("a second.", hint="Fix it too.", id="karni.W965"),
            checks.Warning("a third.", id="karni.W965"),
        ]

    registry.register(warn)
    yield
    registry.registered_checks.discard(warn)


@pytest.fixture
def short(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = BaseCommand.check
    monkeypatch.setenv(check_output.ENV, "short")
    check_output.connect()
    yield
    BaseCommand.check = original


def _run() -> str:
    command = BaseCommand()
    command.stderr = OutputWrapper(io.StringIO())
    command.check()
    return command.stderr._out.getvalue()


def test_the_full_text_stays_without_the_variable(three_warnings: None) -> None:
    text = _run()
    assert "WARNINGS:" in text and "HINT: Fix it." in text and "(karni.W101)" in text


def test_the_warnings_become_one_line_with_the_variable(three_warnings: None, short: None) -> None:
    text = _run()
    assert "WARNINGS:" not in text and "HINT" not in text
    assert text.count("\n") <= 1 and text.startswith("System check identified ")
    assert "karni.W101" in text and "`karni check` lists them in full." in text


def test_an_error_is_never_shortened(short: None) -> None:
    def fail(app_configs: object, **kwargs: object) -> list[checks.CheckMessage]:
        return [checks.Error("it is broken.", id="karni.E101")]

    registry.register(fail)
    try:
        with pytest.raises(SystemCheckError, match="it is broken"):
            _run()
    finally:
        registry.registered_checks.discard(fail)


def test_a_text_that_is_not_a_check_listing_is_left_alone() -> None:
    assert check_output.shorten("System check identified no issues (0 silenced).") is None
    assert check_output.shorten("System check identified some issues:\n\nWARNINGS:\nodd") is None
