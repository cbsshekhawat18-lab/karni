"""karni.dotenv.load_dotenv: host runs read .env; already-set variables win."""

from __future__ import annotations

from pathlib import Path

import pytest

from karni.dotenv import load_dotenv


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.py").write_text("")
    return tmp_path


def _settings(project: Path) -> Path:
    return project / "config" / "settings.py"


def test_loads_missing_variables(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARNI_TEST_DOTENV_A", raising=False)
    (project / ".env").write_text("KARNI_TEST_DOTENV_A=from-file\n")
    assert load_dotenv(_settings(project)) == project / ".env"
    import os

    assert os.environ["KARNI_TEST_DOTENV_A"] == "from-file"
    monkeypatch.delenv("KARNI_TEST_DOTENV_A")


def test_existing_variables_win(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARNI_TEST_DOTENV_B", "from-environment")
    (project / ".env").write_text("KARNI_TEST_DOTENV_B=from-file\n")
    load_dotenv(_settings(project))
    import os

    assert os.environ["KARNI_TEST_DOTENV_B"] == "from-environment"


def test_missing_file_is_a_no_op(project: Path) -> None:
    assert load_dotenv(_settings(project)) is None


def test_disabled_by_setting(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KARNI_TEST_DOTENV_C", raising=False)
    monkeypatch.setenv("KARNI_DOTENV", "false")
    (project / ".env").write_text("KARNI_TEST_DOTENV_C=x\n")
    assert load_dotenv(_settings(project)) is None
    import os

    assert "KARNI_TEST_DOTENV_C" not in os.environ
