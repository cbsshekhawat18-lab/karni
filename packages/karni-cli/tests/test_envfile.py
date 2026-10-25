"""``karni_cli.envfile``: the project's .env read the way the project reads it."""

from __future__ import annotations

from pathlib import Path

import pytest

from karni_cli import envfile


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("KARNI_DOTENV", "A", "B", "C", "D", "E"):
        monkeypatch.delenv(name, raising=False)


def test_read_follows_django_environ(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# a comment\n"
        "A=1\n"
        "export B=two words\n"
        "C='single # kept'\n"
        'D="double \\"quoted\\""\n'
        "A=last wins\n"
        "not a variable\n"
        "E=\n"
    )
    assert envfile.read(tmp_path) == {
        "A": "last wins",
        "B": "two words",
        "C": "single # kept",
        "D": 'double "quoted"',
        "E": "",
    }


def test_the_environment_wins_and_karni_dotenv_false_skips_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("A=file\nB=file\n")
    monkeypatch.setenv("A", "shell")
    assert envfile.lookup(tmp_path, "A") == envfile.Value("shell", "environment")
    assert envfile.lookup(tmp_path, "B") == envfile.Value("file", ".env")
    assert envfile.lookup(tmp_path, "C") is None
    monkeypatch.setenv("KARNI_DOTENV", "false")
    assert envfile.read(tmp_path) == {} and envfile.lookup(tmp_path, "B") is None


def test_no_env_file_is_empty(tmp_path: Path) -> None:
    assert envfile.read(tmp_path) == {}
