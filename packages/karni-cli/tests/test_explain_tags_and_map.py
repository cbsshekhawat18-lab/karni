"""karni explain: karni-site's template tags and the content map's keys, from their sources."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from karni_cli import templateref
from karni_cli.design import extract, mapref
from karni_cli.main import app
from karni_cli.project import CliError

from .conftest import REPO_ROOT, require_modules

runner = CliRunner()


@pytest.mark.parametrize("written", ["image", "{% image %}", "{% image obj.photo alt='' %}"])
def test_explain_a_template_tag(written: str) -> None:
    require_modules("karni-site")
    result = runner.invoke(app, ["explain", written])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("image  (a karni-site template tag: {% load karni_site %})")
    assert "Write:  {% image obj.photo alt=obj.title width=800 %}" in result.output
    assert result.output.rstrip().endswith("/public-site/#seo-by-default")


def test_explain_karni_seo_is_a_tag_not_a_setting() -> None:
    require_modules("karni-site")
    result = runner.invoke(app, ["explain", "karni_seo", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "karni_seo" and data["kind"] == "tag"
    assert "get_absolute_url()" in data["text"]
    assert data["url"].endswith("/public-site/#seo-by-default")


def test_explain_a_filter_and_an_end_tag() -> None:
    require_modules("karni-site")
    assert runner.invoke(app, ["explain", "|highlight"]).output.startswith("highlight  (")
    assert runner.invoke(app, ["explain", "{% endeditable %}"]).output.startswith("editable  (")


def test_explain_an_unknown_tag_names_the_fix() -> None:
    require_modules("karni-site")
    result = runner.invoke(app, ["explain", "{% nope %}"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C374"
    # a plain word that is no tag is still an unknown code
    result = runner.invoke(app, ["explain", "nope"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C204"
    assert "a template tag (image)" in str(result.exception)


def test_tags_come_from_the_project_without_a_karni_site_beside_the_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pipx karni-cli: the project interpreter, which has karni-site, answers."""
    require_modules("karni-site")
    monkeypatch.setattr(templateref, "tag_reference", lambda: None)
    (tmp_path / "manage.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("karni_cli.project.venv_python", lambda root: Path(sys.executable))
    calls: list[list[str]] = []
    real_run = subprocess.run

    def run(command: list[str], **kwargs: Any) -> Any:
        calls.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(templateref.subprocess, "run", run)
    result = runner.invoke(app, ["explain", "get_menu"])
    assert result.exit_code == 0, result.output
    assert calls and calls[0][1:4] == ["-m", "karni_site.tagref", "--explain"]
    assert result.output.startswith("get_menu  (a karni-site template tag")
    assert "/public-site/#everything-the-client-edits" in result.output


def test_explain_the_content_map() -> None:
    result = runner.invoke(app, ["explain", "map"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("The content map")
    for level in mapref.LEVELS:
        assert f"map.{level}.<key>" in result.output or level == "map"
    assert result.output.rstrip().endswith("/design-content/#the-content-map")


def test_explain_one_map_key_and_a_key_of_two_levels() -> None:
    one = runner.invoke(app, ["explain", "map.items"])
    assert one.exit_code == 0, one.output
    assert one.output.startswith('"items"  (a content map key: where a model\'s items are')
    both = runner.invoke(app, ["explain", "map.key", "--json"])
    assert [entry["level"] for entry in json.loads(both.output)] == ["model", "source"]
    exact = runner.invoke(app, ["explain", "map.value.by", "--json"])
    assert [entry["name"] for entry in json.loads(exact.output)] == ["by"]


def test_explain_an_unknown_map_key_names_the_fix() -> None:
    result = runner.invoke(app, ["explain", "map.nope"])
    assert isinstance(result.exception, CliError) and result.exception.code == "C375"


def test_extract_accepts_exactly_the_keys_mapref_lists() -> None:
    assert extract._SOURCE_KEYS == mapref.names("source")
    assert extract._VALUE_KEYS == mapref.names("value")
    by = next(key for key in mapref.KEYS if key.level == "value" and key.name == "by")
    assert all(f'"{value}"' in by.text for value in extract.BY_VALUES)
    origin = next(key for key in mapref.KEYS if key.level == "key" and key.name == "from")
    assert all(f'"{value}"' in origin.text for value in extract.FROM_VALUES)


def test_the_docs_show_the_tables_the_sources_render() -> None:
    require_modules("karni-site")
    content = (REPO_ROOT / "docs" / "design-content.md").read_text(encoding="utf-8")
    assert "\n".join(mapref.markdown()) in content
    site = (REPO_ROOT / "docs" / "public-site.md").read_text(encoding="utf-8")
    reference = templateref.tag_reference()
    assert reference is not None and "\n".join(reference.markdown()) in site
