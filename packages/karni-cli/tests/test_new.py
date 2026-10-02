from __future__ import annotations

from pathlib import Path

import pytest

from karni_cli.main import app
from karni_cli.project import CliError
from karni_cli.scaffold import derive_slug, resolve_template, validate_name

from .conftest import TEMPLATE


def test_new_generates_project(runner, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = runner.invoke(app, ["new", "My App", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "my_app"
    for expected in ("manage.py", "config/settings.py", "docker-compose.yml", "AGENTS.md"):
        assert (project / expected).exists(), expected
    assert "# karni:apps" in (project / "config" / "settings.py").read_text()
    # next steps must print the SLUG, not the input name
    assert "cd my_app" in result.output


def test_slug_rules() -> None:
    assert derive_slug("My App") == "my_app"
    assert validate_name("acme-board") == "acme_board"
    with pytest.raises(CliError):
        validate_name("my.app")
    with pytest.raises(CliError):
        validate_name("1weird")


def test_repo_walk_resolution(monkeypatch) -> None:
    monkeypatch.delenv("KARNI_TEMPLATES", raising=False)
    assert resolve_template() == TEMPLATE
