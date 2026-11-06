"""Pre-publish checks for a release tag (run by .github/workflows/release.yml).

Karni versions every published package in lockstep: one tag ``vX.Y.Z``
publishes karni, karni-cli and karni-payments to PyPI and @karni/ui and
@karni/payments-ui to npm, all at ``X.Y.Z``. This script refuses the release,
and names the fix, when:

- a package's version differs from the tag;
- a package's repository URL is not the repository publishing it (npm
  provenance is verified against that URL, so a mismatch fails at publish
  time, after the Python packages are already out);
- a package directory's LICENSE copy differs from the root LICENSE;
- karni-payments' or @karni/payments-ui's range on core excludes the release.

Usage::

    python .github/ci/check_release.py --tag v0.2.0 --repo owner/karni
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_PACKAGES = (
    "packages/karni",
    "packages/karni-cli",
    "modules/karni-payments",
    "modules/karni-approvals",
    "modules/karni-impersonation",
    "modules/karni-site",
    "modules/karni-charts",
    "modules/karni-reports",
    "modules/karni-ai",
    "modules/karni-storage",
)
MODULES = (
    "modules/karni-payments",
    "modules/karni-approvals",
    "modules/karni-impersonation",
    "modules/karni-site",
    "modules/karni-charts",
    "modules/karni-reports",
    "modules/karni-ai",
    "modules/karni-storage",
)
#: The modules that ship a React package in ui/.
UI_MODULES = (
    "modules/karni-payments",
    "modules/karni-approvals",
    "modules/karni-impersonation",
    "modules/karni-charts",
    "modules/karni-reports",
    "modules/karni-ai",
    "modules/karni-storage",
)
NPM_PACKAGES = ("packages/karni-ui", *(f"{module}/ui" for module in UI_MODULES))
#: Every PyPI upload step passes these besides its own ``packages-dir``: a re-run
#: skips files PyPI already has, a PYPI_API_TOKEN secret replaces trusted
#: publishing, and attestations follow whichever of the two is in use.
UPLOAD_ACTION = "pypa/gh-action-pypi-publish@release/v1"
UPLOAD_WITH: dict[str, object] = {
    "skip-existing": True,
    "password": "${{ secrets.PYPI_API_TOKEN }}",
    "attestations": "${{ steps.auth.outputs.attest }}",
}
#: The jobs that upload to PyPI, one step per project, core first.
PYPI_JOBS = (
    (".github/workflows/release.yml", "publish-pypi"),
    (".github/workflows/pypi-from-release.yml", "publish"),
)
#: The shell loops that name every package: (workflow, job, loop variable, "python" or "npm",
#: and whether the loop names directories or the projects' file-name prefixes).
LOOPS = (
    (".github/workflows/release.yml", "build-python", "d", "python", "directories"),
    (".github/workflows/release.yml", "publish-pypi", "project", "python", "projects"),
    (".github/workflows/pypi-from-release.yml", "publish", "project", "python", "projects"),
    (".github/workflows/release.yml", "build-npm", "d", "npm", "directories"),
    (".github/workflows/release.yml", "publish-npm", "d", "npm", "directories"),
)
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)$")


def _pyproject(directory: str) -> dict[str, object]:
    with (ROOT / directory / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    assert isinstance(project, dict)
    return project


def _package_json(directory: str) -> dict[str, object]:
    data = json.loads((ROOT / directory / "package.json").read_text())
    assert isinstance(data, dict)
    return data


def check_versions(version: str) -> list[str]:
    problems = []
    for directory in PYTHON_PACKAGES:
        found = _pyproject(directory).get("version")
        if found != version:
            problems.append(
                f"{directory}/pyproject.toml has version {found!r}, the tag says {version!r}. "
                f'Set [project] version = "{version}" in every package (lockstep), then re-tag.'
            )
    for directory in NPM_PACKAGES:
        found = _package_json(directory).get("version")
        if found != version:
            problems.append(
                f'{directory}/package.json has "version": {found!r}, the tag says {version!r}. '
                f'Set "version": "{version}" in every package (lockstep), then re-tag.'
            )
    return problems


def _version_attribute(init: Path) -> tuple[str, str] | None:
    """How ``init`` sets ``__version__`` at module level, read without importing it.

    ``("distribution", "karni-ai")`` for ``_metadata.version("karni-ai")`` (or a
    bare ``version(...)``), ``("literal", "0.5.0")`` for a string, ``("other",
    source)`` for anything else, ``None`` when nothing sets it.
    """
    for node in ast.parse(init.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return "literal", value.value
        func = value.func if isinstance(value, ast.Call) else None
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if (
            isinstance(value, ast.Call)
            and called == "version"
            and len(value.args) == 1
            and isinstance(value.args[0], ast.Constant)
            and isinstance(value.args[0].value, str)
        ):
            return "distribution", value.args[0].value
        return "other", ast.unparse(value)
    return None


def check_version_attributes(version: str) -> list[str]:
    """Each Python package's ``__version__`` is its own distribution's version."""
    problems = []
    for directory in PYTHON_PACKAGES:
        name = str(_pyproject(directory).get("name"))
        init = f"{directory}/{name.replace('-', '_')}/__init__.py"
        fix = (
            f"Set it from the distribution: `from importlib import metadata as _metadata` and "
            f'`__version__ = _metadata.version("{name}")`.'
        )
        if not (ROOT / init).is_file():
            problems.append(f"{init} is missing: the import package of {name} is not there.")
            continue
        found = _version_attribute(ROOT / init)
        if found is None:
            problems.append(f"{init} defines no __version__. {fix}")
        elif found[0] == "literal" and found[1] != version:
            problems.append(
                f"{init} has __version__ = {found[1]!r}, the tag says {version!r}. {fix}"
            )
        elif found[0] == "distribution" and found[1] != name:
            problems.append(
                f"{init} reads the version of {found[1]!r}, not of its own distribution "
                f"{name!r}. {fix}"
            )
        elif found[0] == "other":
            problems.append(
                f"{init} sets __version__ = {found[1]}, which this check cannot read. {fix}"
            )
    return problems


def _file_prefix(directory: str) -> str:
    """``karni_cli`` for packages/karni-cli: how its sdist and wheel names start."""
    return str(_pyproject(directory).get("name")).replace("-", "_")


def _job_steps(workflow: str, job: str) -> list[dict[str, object]]:
    import yaml

    data = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))
    steps = (data.get("jobs") or {}).get(job, {}).get("steps") or []
    return [step for step in steps if isinstance(step, dict)]


def check_workflows() -> list[str]:
    """Every package is in every build and upload list, and every upload step is alike."""
    problems = []
    expected = {
        ("python", "directories"): list(PYTHON_PACKAGES),
        ("python", "projects"): [_file_prefix(directory) for directory in PYTHON_PACKAGES],
        ("npm", "directories"): list(NPM_PACKAGES),
    }
    for workflow, job, variable, kind, names in LOOPS:
        want = expected[(kind, names)]
        loop = re.compile(rf"\bfor {variable} in ([^;\n]+); do")
        found = [
            match[1].split()
            for step in _job_steps(workflow, job)
            for match in loop.finditer(str(step.get("run") or ""))
        ]
        if found != [want]:
            problems.append(
                f"{workflow} job {job}: the `for {variable} in ...` loop lists {found}, "
                f"expected one loop over {want} (check_release.py lists the release)."
            )
    for workflow, job in PYPI_JOBS:
        steps = [step for step in _job_steps(workflow, job) if step.get("uses") == UPLOAD_ACTION]
        names = [step.get("name") for step in steps]
        want_names = [_pyproject(directory).get("name") for directory in PYTHON_PACKAGES]
        if names != want_names:
            problems.append(
                f"{workflow} job {job} uploads {names}, expected one {UPLOAD_ACTION} step per "
                f"project in this order: {want_names}."
            )
        for step, directory in zip(steps, PYTHON_PACKAGES, strict=False):
            want = {"packages-dir": f"pypi/{_file_prefix(directory)}/", **UPLOAD_WITH}
            if step.get("with") != want:
                problems.append(
                    f"{workflow} job {job} step {step.get('name')!r} has with: "
                    f"{step.get('with')}, expected {want}. Every upload step passes the same "
                    "skip-existing, password and attestations."
                )
    return problems


def check_repository(repo: str) -> list[str]:
    https = f"https://github.com/{repo}"
    problems = []
    for directory in PYTHON_PACKAGES:
        urls = _pyproject(directory).get("urls") or {}
        found = urls.get("Repository") if isinstance(urls, dict) else None
        if found != https:
            problems.append(
                f"{directory}/pyproject.toml [project.urls] Repository is {found!r}, but "
                f"this release is published from {https}. Set Repository = {https!r}."
            )
    for directory in NPM_PACKAGES:
        repository = _package_json(directory).get("repository")
        found = repository.get("url") if isinstance(repository, dict) else repository
        if found != f"git+{https}.git":
            problems.append(
                f'{directory}/package.json "repository.url" is {found!r}; npm provenance '
                f'verifies it against the publishing repository. Set it to "git+{https}.git".'
            )
    return problems


def check_licenses() -> list[str]:
    root = (ROOT / "LICENSE").read_bytes()
    return [
        f"{directory}/LICENSE differs from the root LICENSE (or is missing). "
        f"Copy it: cp LICENSE {directory}/LICENSE"
        for directory in (*PYTHON_PACKAGES, *NPM_PACKAGES)
        if not (ROOT / directory / "LICENSE").is_file()
        or (ROOT / directory / "LICENSE").read_bytes() != root
    ]


def check_module_ranges(version: str) -> list[str]:
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    problems = []
    for module in MODULES:
        for requirement in _pyproject(module).get("dependencies") or []:
            assert isinstance(requirement, str)
            match = re.match(r"^karni(?![\w-])(?:\[[^\]]*\])?\s*(?P<spec>[^;]*)", requirement)
            if match and not SpecifierSet(match["spec"].strip()).contains(Version(version)):
                problems.append(
                    f"{module} requires {requirement!r}, which excludes karni "
                    f"{version}. Widen the range in its pyproject.toml (docs/modules.md)."
                )
        if module not in UI_MODULES:
            continue  # no npm package (karni-site), so no peer range to check
        if module not in UI_MODULES:  # karni-site ships no React package
            continue
        peers = _package_json(f"{module}/ui").get("peerDependencies") or {}
        spec = peers.get("@karni/ui") if isinstance(peers, dict) else None
        if isinstance(spec, str) and not _caret_allows(spec, version):
            problems.append(
                f"{module}/ui peers on @karni/ui {spec!r}, which excludes {version}. "
                f'Set "@karni/ui": "^{version}" in {module}/ui/package.json.'
            )
    return problems


def _caret_allows(spec: str, version: str) -> bool:
    """npm caret semantics for 0.x (``^0.2.0`` = ``>=0.2.0 <0.3.0``) and >=1."""
    if not spec.startswith("^"):
        return True
    low = tuple(int(part) for part in re.findall(r"\d+", spec)[:3])
    got = tuple(int(part) for part in re.findall(r"\d+", version)[:3])
    if got < low:
        return False
    return got[:2] == low[:2] if low[0] == 0 else got[0] == low[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="the pushed tag, e.g. v0.2.0")
    parser.add_argument("--repo", required=True, help="owner/name of the publishing repository")
    args = parser.parse_args(argv)
    match = TAG.match(args.tag)
    if not match:
        print(f"Tag {args.tag!r} is not a release tag. Tag releases as vX.Y.Z (or vX.Y.ZrcN).")
        return 1
    version = match["version"]
    problems = [
        *check_versions(version),
        *check_version_attributes(version),
        *check_repository(args.repo),
        *check_licenses(),
        *check_module_ranges(version),
        *check_workflows(),
    ]
    for problem in problems:
        print(f"release check: {problem}")
    if not problems:
        print(f"release check: {version} from {args.repo} — all packages consistent.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
