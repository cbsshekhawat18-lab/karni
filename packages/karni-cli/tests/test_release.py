"""The release: every package at one version, and the files that publish them.

``.github/ci/check_release.py`` holds the one list of what a tag publishes:
``PYTHON_PACKAGES`` for PyPI and ``NPM_PACKAGES`` for npm. These tests hold the
packages, the workflows and the release docs to that list, and test the checks
the script runs before anything is published.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import subprocess
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


@pytest.mark.parametrize("directory", PYTHON_PACKAGES)
def test_every_package_imports_from_a_source_tree_without_metadata(directory: str) -> None:
    """``python -S`` sees no installed distribution: the package still imports."""
    name = str(_project(directory)["name"]).replace("-", "_")
    proc = subprocess.run(
        [sys.executable, "-S", "-c", f"import {name}; print({name}.__version__)"],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO_ROOT / directory)},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "0+unknown"


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
            "karni-fallback",
            "from importlib import metadata as _metadata\n\ntry:\n"
            '    __version__ = _metadata.version("karni-fallback")\n'
            "except _metadata.PackageNotFoundError:\n"
            '    __version__ = "0+unknown"\n',
        ),
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
    monkeypatch.setattr(check_release, "check_workflows", list)
    monkeypatch.setattr(check_release, "check_changelog", lambda version, **options: [])
    monkeypatch.setattr(
        check_release, "check_version_attributes", lambda version: [f"stale at {version}"]
    )
    assert check_release.main(["--tag", "v0.5.0", "--repo", "owner/karni"]) == 1
    assert "release check: stale at 0.5.0" in capsys.readouterr().out


# The workflows: every package in every list, every PyPI upload step alike (A6-05)


def test_every_package_is_in_every_build_and_upload_list() -> None:
    assert check_release.check_workflows() == []


def _copy_workflows(root: Path) -> None:
    for workflow, *_ in check_release.LOOPS:
        target = root / workflow
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((REPO_ROOT / workflow).read_text())
    for directory in (*check_release.PYTHON_PACKAGES, *check_release.NPM_PACKAGES):
        for manifest in ("pyproject.toml", "package.json"):
            if (REPO_ROOT / directory / manifest).is_file():
                (root / directory).mkdir(parents=True, exist_ok=True)
                (root / directory / manifest).write_text(
                    (REPO_ROOT / directory / manifest).read_text()
                )


def test_the_workflow_check_names_a_missing_package_and_an_unlike_upload_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_workflows(tmp_path)
    release = tmp_path / ".github/workflows/release.yml"
    text = release.read_text()
    # karni-ai drops out of the npm build loop, and karni-site's upload loses skip-existing.
    text = text.replace(
        ' modules/karni-ai/ui modules/karni-storage/ui; do\n            (cd "$d" && npm ci && npm run build && npm publish --dry-run',
        ' modules/karni-storage/ui; do\n            (cd "$d" && npm ci && npm run build && npm publish --dry-run',
        1,
    )
    text = text.replace(
        "packages-dir: pypi/karni_site/\n          skip-existing: true\n",
        "packages-dir: pypi/karni_site/\n",
        1,
    )
    release.write_text(text)
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    problems = check_release.check_workflows()
    assert len(problems) == 2, problems
    loop, step = problems
    assert loop.startswith(".github/workflows/release.yml job build-npm:")
    assert "modules/karni-ai/ui" in loop
    assert step.startswith(".github/workflows/release.yml job publish-pypi step 'karni-site'")
    assert "skip-existing" in step


def test_the_workflow_check_names_a_missing_upload_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_workflows(tmp_path)
    workflow = tmp_path / ".github/workflows/pypi-from-release.yml"
    text = workflow.read_text()
    start = text.index("      - name: karni-reports\n")
    end = text.index("      - name: karni-ai\n")
    workflow.write_text(text[:start] + text[end:])
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    problems = check_release.check_workflows()
    assert problems and problems[0].startswith(
        ".github/workflows/pypi-from-release.yml job publish uploads"
    )
    assert "'karni-reports'" in problems[0]


def test_the_release_check_job_installs_what_the_script_imports() -> None:
    import yaml

    release = yaml.safe_load((REPO_ROOT / ".github/workflows/release.yml").read_text())
    runs = " ".join(str(step.get("run", "")) for step in release["jobs"]["check"]["steps"])
    assert "pip install packaging pyyaml" in runs


# The npm READMEs: an install line installs versions the peer ranges allow (A6-06)

Interval = tuple[tuple[int, ...], tuple[int, ...]]
_NO_UPPER = (10**9,)


def _caret(spec: str) -> Interval:
    """``[low, high)`` of an npm range part: ``^8``, ``^5.1.0``, ``8``, ``>=9.0.0``."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", spec))
    low = (numbers + (0, 0, 0))[:3]
    if spec.startswith(">="):
        return low, _NO_UPPER
    if spec.lstrip("^")[:1].isdigit() and not spec.startswith("^") and len(numbers) == 3:
        return low, (low[0], low[1], low[2] + 1)  # an exact version
    if low[0] == 0 and len(numbers) >= 2:
        return low, (0, low[1] + 1, 0)
    return low, (low[0] + 1, 0, 0)


def _intervals(peer_range: str) -> list[Interval]:
    return [_caret(part.strip()) for part in peer_range.split("||")]


def _within(spec: str, peer_range: str) -> bool:
    low, high = _caret(spec)
    return any(lo <= low and high <= hi for lo, hi in _intervals(peer_range))


def test_the_range_helper_reads_npm_ranges() -> None:
    assert _within("8", "^8.0.0") and not _within("9", "^8.0.0")
    assert _within("^5.1", "^3.0.0 || ^5.1.0") and not _within("5", "^3.0.0 || ^5.1.0")
    assert _within("^4.6.6", "^3.23.0 || ^4.6.6") and not _within("4", "^3.23.0 || ^4.6.6")
    assert _within("^0.5.0", "^0.5.0") and not _within("^0.4.0", "^0.5.0")
    assert _within("10", ">=9.0.0")


def _package_json(directory: str) -> dict[str, object]:
    data = json.loads((REPO_ROOT / directory / "package.json").read_text())
    assert isinstance(data, dict)
    return data


def _peers(directory: str) -> dict[str, str]:
    peers = _package_json(directory).get("peerDependencies") or {}
    assert isinstance(peers, dict)
    return {str(name): str(spec) for name, spec in peers.items()}


def _install_lines(readme: Path) -> list[str]:
    lines, fenced = [], False
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif fenced and re.match(r"^\s*npm (install|i) @karni/", line):
            lines.append(line.strip())
    return lines


def _name_and_spec(word: str) -> tuple[str, str | None]:
    scope, _, rest = word.partition("/") if word.startswith("@") else ("", "", word)
    name, _, spec = rest.partition("@")
    return (f"{scope}/{name}" if scope else name), (spec or None)


NPM_DIRECTORIES: tuple[str, ...] = getattr(check_release, "NPM_PACKAGES", ())


@pytest.mark.parametrize("directory", NPM_DIRECTORIES)
def test_the_readme_install_line_agrees_with_the_peer_ranges(directory: str) -> None:
    """Every peer an install line names carries a version its peer range allows.

    npm installs the latest major of a package named without a version: the
    install then fails ERESOLVE against the peer range (``@tanstack/react-table``
    9 against ``^8``). Karni's own packages share one version, so they need none.
    """
    readme = REPO_ROOT / directory / "README.md"
    name = str(_package_json(directory)["name"])
    peers = _peers(directory)
    if name != "@karni/ui":
        peers = {**_peers("packages/karni-ui"), **peers}
    lines = _install_lines(readme)
    assert lines, f"{readme.relative_to(REPO_ROOT)} has no `npm install {name}` line"
    problems = []
    for line in lines:
        words = [word for word in line.split()[2:] if not word.startswith("-")]
        assert name in [_name_and_spec(word)[0] for word in words], line
        for word in words:
            package, spec = _name_and_spec(word)
            if package == name:
                continue
            if package not in peers:
                problems.append(f"{word}: not a peer of {name}")
            elif spec is None and not package.startswith("@karni/"):
                problems.append(f"{word}: no version, so npm picks the latest major")
            elif spec is not None and not _within(spec, peers[package]):
                problems.append(f"{word}: outside the peer range {peers[package]!r}")
    assert problems == [], f"{readme.relative_to(REPO_ROOT)}: {problems}"


@pytest.mark.parametrize("directory", NPM_DIRECTORIES[1:])
def test_the_readme_names_no_stale_karni_ui_range(directory: str) -> None:
    readme = (REPO_ROOT / directory / "README.md").read_text(encoding="utf-8")
    peer = _peers(directory)["@karni/ui"]
    stale = [
        spec
        for spec in re.findall(r"@karni/ui`?\s*\(?`?(\^\d[\d.]*)", readme)
        if _intervals(spec) != _intervals(peer)
    ]
    assert stale == [], f"{directory}/README.md names @karni/ui {stale}, package.json {peer!r}"


# The release docs agree with the release: every package, no stale counts (A6-03)

COUNT = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b(?: (?:python|npm|pypi))?"
    r" (?:packages|projects|manifests|versions|pyproject\.toml|package\.json)",
    re.IGNORECASE,
)


def _release_names() -> tuple[list[str], list[str]]:
    python = [str(_project(directory)["name"]) for directory in PYTHON_PACKAGES]
    npm = [str(_package_json(directory)["name"]) for directory in NPM_DIRECTORIES]
    return python, npm


def _release_texts() -> dict[str, str]:
    """The prose that describes the release, by where it is."""
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text().split("\non:")[0]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text().split("\n## ")[0]
    stability = (REPO_ROOT / "docs/stability.md").read_text()
    return {
        "docs/releasing.md": (REPO_ROOT / "docs/releasing.md").read_text(),
        ".github/workflows/release.yml (header)": workflow,
        ".github/ci/check_release.py (docstring)": str(check_release.__doc__),
        "CHANGELOG.md (intro)": changelog,
        "docs/stability.md (versioning)": stability.split("## Versioning")[1].split("\n## ")[0],
    }


def _names_in(text: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if re.search(rf"`{re.escape(name)}`|(?<![\w/@-]){re.escape(name)}(?![\w-])", text)
    }


@pytest.mark.parametrize("where", list(_release_texts()) if SCRIPT.is_file() else [])
def test_the_release_prose_counts_no_packages_and_names_all_or_none(where: str) -> None:
    text = _release_texts()[where]
    assert COUNT.findall(text) == [], f"{where}: a count goes stale with the next package"
    python, npm = _release_names()
    named = _names_in(text, [*python[2:], *npm[1:]])  # the modules: core names appear anyway
    modules = {*python[2:], *npm[1:]}
    assert named in (set(), modules), (
        f"{where} names {sorted(named)}, not {sorted(modules - named)}"
    )


def test_the_lockstep_table_is_the_release_list() -> None:
    page = (REPO_ROOT / "docs/releasing.md").read_text()
    section = page.split("## Lockstep versions")[1].split("\n## ")[0]
    rows = re.findall(r"^\| `([^`]+)` \| (PyPI|npm) \| `([^`]+)` \|$", section, re.MULTILINE)
    python, npm = _release_names()
    assert rows == [
        *(
            (name, "PyPI", directory)
            for name, directory in zip(python, PYTHON_PACKAGES, strict=True)
        ),
        *((name, "npm", directory) for name, directory in zip(npm, NPM_DIRECTORIES, strict=True)),
    ]


def test_the_pending_publisher_table_names_every_pypi_project_once() -> None:
    page = (REPO_ROOT / "docs/releasing.md").read_text()
    rows = re.findall(r"^\s*\| PyPI Project Name \| (.+) \|$", page, re.MULTILINE)
    assert len(rows) == 1, rows
    assert re.findall(r"`([^`]+)`", rows[0]) == _release_names()[0]


# The CHANGELOG section of a release: dated in the release commit (A6-09)


def _changelog(root: Path, heading: str) -> None:
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\nIntro.\n\n{heading}\n\n- An entry.\n\n## 0.4.0 (2026-10-22)\n"
    )


@pytest.mark.parametrize(
    ("heading", "version", "allow", "problem"),
    [
        ("## 0.5.0 (2026-11-20)", "0.5.0", False, None),
        ("## 0.5.0 (unreleased)", "0.5.0", True, None),
        ("## 0.5.0 (unreleased)", "0.5.0rc1", False, None),
        ("## 0.5.0 (unreleased)", "0.5.0", False, "still reads `## 0.5.0 (unreleased)`"),
        ("## 0.5.0 (2026-13-01)", "0.5.0", False, "which is not a date"),
        ("## 0.5.0 (Unreleased)", "0.5.0", True, "not this release's section"),
        ("## 0.5.1 (unreleased)", "0.5.0", True, "not this release's section"),
    ],
)
def test_the_release_check_reads_the_changelog_heading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    heading: str,
    version: str,
    allow: bool,
    problem: str | None,
) -> None:
    _changelog(tmp_path, heading)
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    problems = check_release.check_changelog(version, allow_unreleased=allow)
    if problem is None:
        assert problems == []
    else:
        assert len(problems) == 1 and problem in problems[0], problems
        assert "YYYY-MM-DD" in problems[0]


def test_the_changelog_opens_with_the_version_being_built() -> None:
    """Between releases the newest section is ``## X.Y.Z (unreleased)``, X.Y.Z the manifests'."""
    version = str(_project("packages/karni")["version"])
    assert check_release.check_changelog(version, allow_unreleased=True) == []


def test_the_release_steps_date_the_changelog() -> None:
    page = (REPO_ROOT / "docs/releasing.md").read_text()
    steps = page.split("## Cutting a release")[1].split("\n## ")[0]
    assert "(unreleased)" in steps and "(YYYY-MM-DD)" in steps


# Module ranges on core move with every minor (A6-07, karni-storage after the bump)


def test_every_module_range_on_core_includes_the_release() -> None:
    version = str(_project("packages/karni")["version"])
    assert check_release.check_module_ranges(version) == []


def test_the_release_check_names_a_module_pinned_to_the_previous_minor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "modules" / "karni-files"
    (module / "ui").mkdir(parents=True)
    (module / "pyproject.toml").write_text(
        '[project]\nname = "karni-files"\nversion = "0.5.0"\n'
        'dependencies = ["karni[s3]>=0.4,<0.5"]\n'
    )
    (module / "ui" / "package.json").write_text(
        json.dumps({"name": "@karni/files-ui", "peerDependencies": {"@karni/ui": "^0.4.0"}})
    )
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    monkeypatch.setattr(check_release, "MODULES", ("modules/karni-files",))
    monkeypatch.setattr(check_release, "UI_MODULES", ("modules/karni-files",))
    problems = check_release.check_module_ranges("0.5.0")
    assert len(problems) == 2, problems
    assert "'karni[s3]>=0.4,<0.5', which excludes karni 0.5.0" in problems[0]
    assert "@karni/ui '^0.4.0', which excludes 0.5.0" in problems[1]


WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def _load_workflow(path: Path) -> dict[str, object]:
    """Parse a workflow, refusing a key repeated in one mapping (GitHub refuses the file)."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[object, object]:
        keys = [loader.construct_object(key) for key, _ in node.value]
        repeated = sorted({str(key) for key in keys if keys.count(key) > 1})
        assert repeated == [], f"{path.name} line {node.start_mark.line + 1}: {repeated} twice"
        return loader.construct_mapping(node)

    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    loaded = yaml.load(path.read_text(), Loader=Loader)  # a SafeLoader subclass
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_workflow_step_runs_a_script_or_an_action(workflow: Path) -> None:
    """GitHub refuses the whole file, and runs no job, when one step has neither."""
    jobs = _load_workflow(workflow)["jobs"]
    assert isinstance(jobs, dict)
    empty = [
        f"{job}: {step.get('name', f'step {index}')}"
        for job, spec in jobs.items()
        for index, step in enumerate(spec.get("steps", []))
        if "run" not in step and "uses" not in step
    ]
    assert empty == []


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_script_line_is_a_bare_file_path(workflow: Path) -> None:
    """A list entry a merge left inside a `run:` script runs as a command and fails (126)."""
    jobs = _load_workflow(workflow)["jobs"]
    assert isinstance(jobs, dict)
    bare = [
        f"{job}: {step.get('name')}: {line.strip()}"
        for job, spec in jobs.items()
        for step in spec.get("steps", [])
        for line in str(step.get("run", "")).splitlines()
        if (REPO_ROOT / line.strip()).is_file() and not os.access(REPO_ROOT / line.strip(), os.X_OK)
    ]
    assert bare == []
