from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / "templates" / "project"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def generated_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real cookiecutter render of the repo template."""
    from cookiecutter.main import cookiecutter

    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    cookiecutter(
        str(TEMPLATE),
        no_input=True,
        extra_context={"project_name": "Acme Board"},
        output_dir=str(tmp_path),
    )
    project = tmp_path / "acme_board"
    assert project.is_dir()
    return project


@pytest.fixture(autouse=True)
def _no_ambient_templates_env(monkeypatch: pytest.MonkeyPatch):
    if "KARNI_TEMPLATES" in os.environ:
        monkeypatch.delenv("KARNI_TEMPLATES")
