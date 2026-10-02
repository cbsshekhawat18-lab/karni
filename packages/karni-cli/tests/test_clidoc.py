"""docs/cli.md is generated from the typer app: it must never go stale."""

from __future__ import annotations

from karni_cli.clidoc import render

from .conftest import REPO_ROOT


def test_docs_cli_md_is_fresh() -> None:
    docs = (REPO_ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    assert docs == render(), (
        "docs/cli.md is stale — regenerate it: python -m karni_cli.clidoc > docs/cli.md"
    )


def test_every_visible_command_is_documented() -> None:
    text = render()
    for command in ("new", "serve", "migrate", "schedule run", "make model", "make page"):
        assert f"### `karni {command}`" in text or f"#### `karni {command}`" in text, command
    assert "make:model" not in text.split("hidden Laravel-style alias")[0]
    assert "| `status:choice:draft\\|live` |" in text
