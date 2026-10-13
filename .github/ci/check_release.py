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
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_PACKAGES = ("packages/karni", "packages/karni-cli", "modules/karni-payments")
NPM_PACKAGES = ("packages/karni-ui", "modules/karni-payments/ui")
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
    for requirement in _pyproject("modules/karni-payments").get("dependencies") or []:
        assert isinstance(requirement, str)
        match = re.match(r"^karni(?![\w-])\s*(?P<spec>[^;]*)", requirement)
        if match and not SpecifierSet(match["spec"].strip()).contains(Version(version)):
            problems.append(
                f"modules/karni-payments requires {requirement!r}, which excludes karni "
                f"{version}. Widen the range in its pyproject.toml (docs/modules.md)."
            )
    peers = _package_json("modules/karni-payments/ui").get("peerDependencies") or {}
    spec = peers.get("@karni/ui") if isinstance(peers, dict) else None
    if isinstance(spec, str) and not _caret_allows(spec, version):
        problems.append(
            f"@karni/payments-ui peers on @karni/ui {spec!r}, which excludes {version}. "
            f'Set "@karni/ui": "^{version}" in modules/karni-payments/ui/package.json.'
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
        *check_repository(args.repo),
        *check_licenses(),
        *check_module_ranges(version),
    ]
    for problem in problems:
        print(f"release check: {problem}")
    if not problems:
        print(f"release check: {version} from {args.repo} — all packages consistent.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
