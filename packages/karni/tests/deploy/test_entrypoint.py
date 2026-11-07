"""The production image's entrypoint: the deploy checks gate the container's command."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import pytest

from karni.deploy import entrypoint

PACKAGE = Path(__file__).resolve().parents[2]
STARTED = [sys.executable, "-c", "print('command started')"]


def _python(code: str) -> str:
    return f"{sys.executable} -c {code!r}"


def _run_module(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """``python -m karni.deploy.entrypoint <STARTED>`` in a child process, as Docker runs it."""
    return subprocess.run(
        [sys.executable, "-m", "karni.deploy.entrypoint", *STARTED],
        env={**os.environ, **env},
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_a_failing_check_refuses_to_start_the_command() -> None:
    result = _run_module({"KARNI_DEPLOY_CHECK_COMMAND": _python("raise SystemExit(1)")})
    assert result.returncode == 1
    assert "command started" not in result.stdout
    assert "the deploy checks failed (E520)" in result.stderr
    assert "KARNI_SKIP_DEPLOY_CHECK=1" in result.stderr


def test_a_passing_check_replaces_the_process_with_the_command() -> None:
    result = _run_module({"KARNI_DEPLOY_CHECK_COMMAND": _python("raise SystemExit(0)")})
    assert result.returncode == 0, result.stderr
    assert "command started" in result.stdout
    assert "starting" in result.stderr


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_the_escape_hatch_starts_without_the_checks_and_says_so(value: str) -> None:
    result = _run_module(
        {
            "KARNI_SKIP_DEPLOY_CHECK": value,
            # Would refuse, but must not even run.
            "KARNI_DEPLOY_CHECK_COMMAND": _python("raise SystemExit(1)"),
        }
    )
    assert result.returncode == 0, result.stderr
    assert "command started" in result.stdout
    warnings = [line for line in result.stderr.splitlines() if line.startswith("WARNING")]
    assert len(warnings) >= 3
    assert "did NOT run (E520)" in result.stderr


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_other_values_do_not_skip(value: str) -> None:
    assert not entrypoint.skip_requested({"KARNI_SKIP_DEPLOY_CHECK": value})


def test_the_real_deploy_checks_refuse_development_settings() -> None:
    """karni_check --deploy against the test settings (DEBUG on, a weak key) fails the gate."""
    command = [
        sys.executable,
        "-m",
        "django",
        "karni_check",
        "--deploy",
        "--settings=tests.settings",
    ]

    def run(argv: Sequence[str]) -> int:
        return subprocess.run(
            list(argv), cwd=PACKAGE, capture_output=True, check=False, timeout=120
        ).returncode

    out = io.StringIO()
    status = entrypoint.gate(
        {"KARNI_DEPLOY_CHECK_COMMAND": " ".join(command)}, ["gunicorn"], run=run, stderr=out
    )
    assert status != 0
    assert "`gunicorn` does not start" in out.getvalue()


def test_the_default_check_command_is_karni_check_deploy() -> None:
    assert entrypoint.check_command({})[1:] == ["manage.py", "karni_check", "--deploy"]
    assert entrypoint.check_command(
        {"KARNI_DEPLOY_CHECK_COMMAND": "python manage.py check --deploy"}
    ) == ["python", "manage.py", "check", "--deploy"]


def test_main_without_a_command_returns_the_gate_status() -> None:
    def never(file: str, args: list[str]) -> NoReturn:
        raise AssertionError("nothing to start")

    assert entrypoint.main([], environ={}, run=lambda argv: 3, execvp=never) == 3
    assert entrypoint.main([], environ={}, run=lambda argv: 0, execvp=never) == 0


def test_a_missing_check_command_is_a_refusal() -> None:
    out = io.StringIO()
    status = entrypoint.gate(
        {"KARNI_DEPLOY_CHECK_COMMAND": "/nonexistent/karni-check"}, ["gunicorn"], stderr=out
    )
    assert status == 127
