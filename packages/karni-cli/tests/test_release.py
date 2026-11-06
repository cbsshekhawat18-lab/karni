"""The release: every package at one version, and the files that publish them.

``.github/ci/check_release.py`` holds the one list of what a tag publishes (10
Python distributions, 8 npm packages). These tests hold the packages, the
workflows and the release docs to that list, and test the checks the script
runs before anything is published.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from types import ModuleType

import pytest

from tests.conftest import REPO_ROOT, require_modules

SCRIPT = REPO_ROOT / ".github" / "ci" / "check_release.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file(), reason="needs the repository checkout (.github/ci/check_release.py)"
)


def _load_check_release() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_release"] = module
    spec.loader.exec_module(module)
    return module


check_release = _load_check_release() if SCRIPT.is_file() else ModuleType("check_release")
PYTHON_PACKAGES: tuple[str, ...] = getattr(check_release, "PYTHON_PACKAGES", ())


def _project(directory: str) -> dict[str, object]:
    with (REPO_ROOT / directory / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert isinstance(project, dict)
    return project


# Version lockstep: __version__ is the distribution's version (A6-04)


@pytest.mark.parametrize("directory", PYTHON_PACKAGES)
def test_every_package_version_attribute_is_its_distribution_version(directory: str) -> None:
    project = _project(directory)
    name = str(project["name"])
    require_modules(name)
    module = importlib.import_module(name.replace("-", "_"))
    assert module.__version__ == metadata.version(name) == project["version"], (
        f"{name}: __version__ {module.__version__!r}, installed {metadata.version(name)!r}, "
        f"{directory}/pyproject.toml {project['version']!r}. If only the installed version "
        "is behind, reinstall (make install-py)."
    )


def test_the_release_check_passes_on_the_checkout() -> None:
    version = str(_project("packages/karni")["version"])
    assert check_release.check_version_attributes(version) == []


def _package(root: Path, name: str, init: str) -> str:
    directory = f"modules/{name}"
    package = root / directory / name.replace("-", "_")
    package.mkdir(parents=True)
    (root / directory / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.5.0"\n'
    )
    (package / "__init__.py").write_text(init)
    return directory


def test_the_release_check_names_a_version_attribute_out_of_lockstep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packages = (
        _package(
            tmp_path,
            "karni-good",
            'from importlib.metadata import version\n\n__version__ = version("karni-good")\n',
        ),
        _package(tmp_path, "karni-stale", '"""A module."""\n\n__version__ = "0.4.0"\n'),
        _package(tmp_path, "karni-missing", '"""A module."""\n'),
        _package(
            tmp_path,
            "karni-borrowed",
            'from importlib.metadata import version\n\n__version__ = version("karni")\n',
        ),
    )
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    monkeypatch.setattr(check_release, "PYTHON_PACKAGES", packages)
    problems = check_release.check_version_attributes("0.5.0")
    assert len(problems) == 3, problems
    stale, missing, borrowed = problems
    assert "karni_stale/__init__.py" in stale and "'0.4.0'" in stale
    assert 'version("karni-stale")' in stale
    assert "karni_missing/__init__.py defines no __version__" in missing
    assert "'karni'" in borrowed and "karni-borrowed" in borrowed


def test_the_release_check_runs_the_version_attribute_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_release, "check_versions", lambda version: [])
    monkeypatch.setattr(check_release, "check_repository", lambda repo: [])
    monkeypatch.setattr(check_release, "check_licenses", list)
    monkeypatch.setattr(check_release, "check_module_ranges", lambda version: [])
    monkeypatch.setattr(
        check_release, "check_version_attributes", lambda version: [f"stale at {version}"]
    )
    assert check_release.main(["--tag", "v0.5.0", "--repo", "owner/karni"]) == 1
    assert "release check: stale at 0.5.0" in capsys.readouterr().out
