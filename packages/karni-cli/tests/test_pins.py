"""Karni and its modules are held at one range: karni new, karni add, karni upgrade, karni doctor."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from cookiecutter.main import cookiecutter

from karni_cli import pins
from karni_cli.commands import new as new_command
from karni_cli.commands.add import add_dependency_text
from tests.conftest import TEMPLATE


def _deps(text: str) -> list[str]:
    return list(tomllib.loads(text)["project"]["dependencies"])


def _project(deps: list[str], baseline: str = "0.0.0") -> str:
    listed = "".join(f'    "{dep}",\n' for dep in deps)
    return (
        f'[project]\nname = "x"\ndependencies = [\n{listed}]\n\n'
        f'[tool.karni]\nbaseline = "{baseline}"\nkind = "app"\n'
    )


def test_a_line_is_a_minor_before_one_and_a_major_after() -> None:
    line = pins.compatible_range("0.7.3")
    assert line is not None and line.range() == ">=0.7,<0.8"
    major = pins.compatible_range("1.4.0")
    assert major is not None and major.range() == ">=1.4,<2"
    assert pins.compatible_range("0+unknown") is None
    assert pins.compatible_range("nonsense") is None


def test_a_development_version_is_written_with_the_dev_floor() -> None:
    for version in ("0.8.0.dev2", "0.8.0+local", "0.8.0rc1"):
        line = pins.compatible_range(version)
        assert line is not None and line.range() == ">=0.8.0.dev0,<0.9"


def test_the_template_writes_the_range_it_is_given(tmp_path: Path) -> None:
    def render(**extra: str) -> list[str]:
        cookiecutter(
            str(TEMPLATE),
            no_input=True,
            extra_context={"project_name": "Pinned", **extra},
            output_dir=str(tmp_path / extra.get("karni_range", "bare")),
        )
        folder = tmp_path / extra.get("karni_range", "bare") / "pinned"
        return _deps((folder / "pyproject.toml").read_text())

    assert render(karni_range=">=0.7,<0.8")[0] == "karni>=0.7,<0.8"
    assert render()[0] == "karni"  # the template alone knows no version


def test_karni_new_gives_the_template_its_own_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("karni_cli.__version__", "0.9.2")
    assert new_command._karni_range() == ">=0.9,<0.10"
    monkeypatch.setattr("karni_cli.__version__", "0+unknown")
    assert new_command._karni_range() == ""


def test_a_module_is_added_at_the_range_karni_has() -> None:
    text = _project(["karni>=0.6,<0.7", "gunicorn"])
    updated = add_dependency_text(text, "karni-site[images]")
    assert updated is not None
    assert _deps(updated)[-1] == "karni-site[images]>=0.6,<0.7"


def test_a_project_with_bare_names_is_held_at_its_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("karni_cli.__version__", "0.9.0")
    updated = add_dependency_text(_project(["karni"], baseline="0.6.0"), "karni-ai")
    assert updated is not None and _deps(updated)[-1] == "karni-ai>=0.6,<0.7"
    unknown = add_dependency_text(_project(["karni"]), "karni-ai")  # baseline 0.0.0: not recorded
    assert unknown is not None and _deps(unknown)[-1] == "karni-ai>=0.9,<0.10"


def test_a_third_party_module_and_a_listed_one_are_left_alone() -> None:
    text = _project(["karni>=0.7,<0.8", "karni-site"])
    third = add_dependency_text(text, "karni-someone-elses")
    assert third is not None and _deps(third)[-1] == "karni-someone-elses"
    assert add_dependency_text(text, "karni-site") is None  # already there, bare as it is


def test_karni_add_says_the_range_and_when_to_upgrade(
    runner, generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    pyproject = generated_project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('"karni",', '"karni>=0.5,<0.6",'))
    monkeypatch.setattr("karni_cli.__version__", "0.7.0")
    result = runner.invoke(app, ["add", "payments"])
    assert result.exit_code == 0, result.output
    assert (
        "written as karni-payments>=0.5,<0.6, the range karni has in pyproject.toml"
        in result.output
    )
    assert "The newest release is 0.7." in result.output and "karni upgrade" in result.output
    assert "karni-payments>=0.5,<0.6" in pyproject.read_text()


def test_karni_add_at_the_newest_line_says_no_more(
    runner, generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    pyproject = generated_project / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('"karni",', '"karni>=0.7,<0.8",'))
    monkeypatch.setattr("karni_cli.__version__", "0.7.4")
    result = runner.invoke(app, ["add", "payments"])
    assert "written as karni-payments>=0.7,<0.8" in result.output
    assert "karni upgrade" not in result.output


def test_upgrade_writes_the_range_of_the_release_and_keeps_extras() -> None:
    text = _project(["karni", "karni-site[images]>=0.5,<0.6", "karni-someone-elses>=1", "gunicorn"])
    line = pins.compatible_range("0.7.0")
    assert line is not None
    updated, changed = pins.with_ranges(text, line)
    assert _deps(updated) == [
        "karni>=0.7,<0.8",
        "karni-site[images]>=0.7,<0.8",
        "karni-someone-elses>=1",
        "gunicorn",
    ]
    assert changed == [
        ("karni", "karni>=0.7,<0.8"),
        ("karni-site[images]>=0.5,<0.6", "karni-site[images]>=0.7,<0.8"),
    ]
    assert pins.with_ranges(updated, line) == (updated, [])  # a second run changes nothing


def test_karni_upgrade_pins_a_project_that_listed_them_bare(
    runner, generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from karni_cli.main import app

    monkeypatch.chdir(generated_project)
    pyproject = generated_project / "pyproject.toml"
    bare = pyproject.read_text()
    assert _deps(bare)[0] == "karni"
    dry = runner.invoke(app, ["upgrade", "--from", "0.7.0", "--to", "0.7.0", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "karni -> karni>=0.7,<0.8" in dry.output
    assert pyproject.read_text() == bare
    result = runner.invoke(app, ["upgrade", "--from", "0.7.0", "--to", "0.7.0", "--allow-dirty"])
    assert result.exit_code == 0, result.output
    assert _deps(pyproject.read_text())[0] == "karni>=0.7,<0.8"
    again = runner.invoke(app, ["upgrade", "--from", "0.7.0", "--to", "0.7.0", "--allow-dirty"])
    assert "now holds" not in again.output  # nothing left to write
    assert _deps(pyproject.read_text())[0] == "karni>=0.7,<0.8"


def test_doctor_names_a_package_off_the_line_and_a_bare_name(
    generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("karni_cli.__version__", "0.7.0")
    monkeypatch.setattr(
        pins, "installed_in", lambda project: {"karni": "0.7.1", "karni-site": "0.6.2"}
    )
    lines = pins.doctor_lines(generated_project)
    assert lines[0].startswith("NOT one line (karni.W521): karni-site 0.6.2")
    assert any("lists karni without a range" in line and "karni upgrade" in line for line in lines)
    monkeypatch.setattr(pins, "installed_in", lambda project: {"karni": "0.7.1"})
    assert pins.doctor_lines(generated_project)[0] == "one line (karni 0.7.1, karni-cli 0.7.0)"
    monkeypatch.setattr(pins, "installed_in", lambda project: {})
    assert "a checkout" in pins.doctor_lines(generated_project)[0]


def test_a_cli_off_the_line_is_named(
    generated_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("karni_cli.__version__", "0.8.0")
    monkeypatch.setattr(pins, "installed_in", lambda project: {"karni": "0.7.1"})
    assert "karni-cli 0.8.0" in pins.doctor_lines(generated_project)[0]


def test_nothing_unpinned_is_reported_when_all_have_ranges() -> None:
    assert pins.unpinned(_project(["karni>=0.7,<0.8", "karni-site>=0.7,<0.8"])) == []
    assert pins.unpinned(_project(["karni", "karni-site>=0.7,<0.8", "psycopg"])) == ["karni"]
