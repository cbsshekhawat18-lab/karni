"""Every external URL and address Karni publishes, in one place.

Error messages, deprecation warnings, the changelog, the CLI, the docs site,
the package metadata and the README all point at these. Change them here,
then run ``python -m karni.links sync`` to rewrite the files that cannot
import Python (``pyproject.toml``, ``package.json``, ``mkdocs.yml``, the
Markdown pages); ``python -m karni.links check`` (run by the test suite)
fails while any of them still carries an old value.

Stdlib only: ``karni.errorcodes`` imports this module, and karni-cli
bundles both so ``karni explain`` works without Django or a project.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Final

__all__ = [
    "DOCS_BASE_URL",
    "ISSUES_URL",
    "REPO_SLUG",
    "REPO_URL",
    "SECURITY_ADVISORY_URL",
    "SUPPORT_EMAIL",
    "docs_page",
]

#: ``owner/name`` on GitHub.
REPO_SLUG: Final[str] = "cbsshekhawat18-lab/karni"
#: The repository.
REPO_URL: Final[str] = f"https://github.com/{REPO_SLUG}"
#: The documentation site; ends with a slash. Pages are ``DOCS_BASE_URL + "page/"``.
DOCS_BASE_URL: Final[str] = "https://cbsshekhawat18-lab.github.io/karni/"
#: Where bugs go.
ISSUES_URL: Final[str] = f"{REPO_URL}/issues"
#: Private vulnerability reports.
SECURITY_ADVISORY_URL: Final[str] = f"{REPO_URL}/security/advisories/new"
#: The maintainer's address for security reports that cannot use GitHub.
SUPPORT_EMAIL: Final[str] = "cbsshekhawat18@gmail.com"


def docs_page(page: str, anchor: str = "") -> str:
    """``docs/<page>.md#anchor`` as the published URL (``…/page/#anchor``)."""
    path = page.removesuffix(".md").strip("/")
    url = f"{DOCS_BASE_URL}{path}/" if path else DOCS_BASE_URL
    return f"{url}#{anchor}" if anchor else url


# The files that carry these values literally, and the pattern each one uses.
# `sync` rewrites them; `check` reports the ones that drifted.

_PYPROJECT_URLS = {
    "Homepage": lambda: REPO_URL,
    "Documentation": lambda: DOCS_BASE_URL,
    "Repository": lambda: REPO_URL,
    "Issues": lambda: ISSUES_URL,
    "Changelog": lambda: f"{REPO_URL}/tree/main/docs/migrations",
}

_PACKAGE_JSON = {
    "packages/karni-ui/package.json": "packages/karni-ui",
    "modules/karni-payments/ui/package.json": "modules/karni-payments/ui",
}

_MKDOCS = {
    "site_url": lambda: DOCS_BASE_URL,
    "repo_url": lambda: REPO_URL,
    "repo_name": lambda: REPO_SLUG,
}


def repo_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "mkdocs.yml").is_file() and (parent / "packages").is_dir():
            return parent
    return None


def _sync_pyproject(path: Path, dry_run: bool) -> list[str]:
    text = path.read_text()
    out = text
    for key, value in _PYPROJECT_URLS.items():
        out = re.sub(rf'^{key} = "[^"]*"$', f'{key} = "{value()}"', out, flags=re.M)
    return _write(path, text, out, dry_run)


def _sync_package_json(path: Path, subdir: str, dry_run: bool) -> list[str]:
    text = path.read_text()
    data = json.loads(text)
    data["repository"] = {"type": "git", "url": f"git+{REPO_URL}.git", "directory": subdir}
    data["homepage"] = f"{REPO_URL}/tree/main/{subdir}#readme"
    data["bugs"] = {"url": ISSUES_URL}
    out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return _write(path, text, out, dry_run)


def _sync_mkdocs(path: Path, dry_run: bool) -> list[str]:
    text = path.read_text()
    out = text
    for key, value in _MKDOCS.items():
        out = re.sub(rf"^{key}: .*$", f"{key}: {value()}", out, flags=re.M)
    return _write(path, text, out, dry_run)


def _write(path: Path, before: str, after: str, dry_run: bool) -> list[str]:
    if before == after:
        return []
    if not dry_run:
        path.write_text(after)
    return [str(path)]


def _sync_eslint_docs(path: Path, dry_run: bool) -> list[str]:
    text = path.read_text()
    out = re.sub(
        r'^export const DOCS_BASE_URL = "[^"]*";$',
        f'export const DOCS_BASE_URL = "{DOCS_BASE_URL}";',
        text,
        flags=re.M,
    )
    return _write(path, text, out, dry_run)


def sync(root: Path, *, dry_run: bool = False) -> list[str]:
    """Rewrite the metadata files from these constants; returns the files that changed."""
    changed: list[str] = []
    for rel in ("packages/karni", "packages/karni-cli", "modules/karni-payments"):
        changed += _sync_pyproject(root / rel / "pyproject.toml", dry_run)
    for rel, subdir in _PACKAGE_JSON.items():
        changed += _sync_package_json(root / rel, subdir, dry_run)
    changed += _sync_mkdocs(root / "mkdocs.yml", dry_run)
    changed += _sync_eslint_docs(root / "packages/karni-ui/eslint-plugin/lib/docs.js", dry_run)
    return changed


# Prose (Markdown, YAML, HTML, templates) links to the site and repository by
# URL. A Karni-looking URL that is not the configured one is stale.
_PROSE_GLOBS = (
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "docs/**/*.md",
    "docs/**/*.html",
    "docs/**/*.txt",
    ".github/**/*.yml",
    "packages/*/README.md",
    "modules/*/README.md",
    "modules/*/ui/README.md",
    "templates/**/*.md",
    "examples/*/README.md",
)
_KARNI_URL = re.compile(
    r"https://(?:[\w.-]+\.github\.io/karni/?|github\.com/[\w.-]+/karni(?:[/#.)]|$))"
)


def stale_prose(root: Path) -> list[str]:
    """``file:line: url`` for every Karni site or repository URL that differs from the constants."""
    stale: list[str] = []
    for glob in _PROSE_GLOBS:
        for path in sorted(root.glob(glob)):
            if "node_modules" in path.parts or "site" in path.parts[:1]:
                continue
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                for match in _KARNI_URL.finditer(line):
                    url = match.group(0).rstrip("/#.)")
                    if not (url.startswith(DOCS_BASE_URL.rstrip("/")) or url.startswith(REPO_URL)):
                        stale.append(f"{path.relative_to(root)}:{number}: {url}")
    return stale


def rewrite_prose(root: Path, old: str, new: str) -> list[str]:
    """Replace ``old`` with ``new`` in every prose file; returns the files that changed."""
    changed: list[str] = []
    for glob in _PROSE_GLOBS:
        for path in sorted(root.glob(glob)):
            if "node_modules" in path.parts:
                continue
            text = path.read_text(errors="replace")
            changed += _write(path, text, text.replace(old, new), dry_run=False)
    return changed


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = repo_root()
    if root is None:
        print("karni.links: not inside the Karni repository", file=sys.stderr)
        return 2
    if args == ["sync"]:
        for path in sync(root):
            print(f"updated {path}")
        for entry in stale_prose(root):
            print(f"still stale (prose; use `sync --rewrite OLD NEW`): {entry}")
        return 0
    if len(args) == 4 and args[:2] == ["sync", "--rewrite"]:
        for path in [*sync(root), *rewrite_prose(root, args[2], args[3])]:
            print(f"updated {path}")
        return 0
    if args == ["check"]:
        stale = [f"stale: {path}" for path in sync(root, dry_run=True)] + [
            f"stale: {entry}" for entry in stale_prose(root)
        ]
        for line in stale:
            print(f"{line} (run `python -m karni.links sync`)")
        return 1 if stale else 0
    print("usage: python -m karni.links [check|sync|sync --rewrite OLD NEW]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
