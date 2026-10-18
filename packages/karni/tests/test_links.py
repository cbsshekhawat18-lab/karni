"""``karni.links`` is the one place every published URL comes from."""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

from karni import changelog, errorcodes, links

_root = links.repo_root()
assert _root is not None
ROOT: Path = _root


def test_consumers_read_the_links_module() -> None:
    assert errorcodes.DOCS_BASE_URL == links.DOCS_BASE_URL == changelog.DOCS_BASE_URL
    assert links.DOCS_BASE_URL.endswith("/") and links.REPO_URL.endswith(links.REPO_SLUG)
    assert links.docs_page("accounts.md", "roles-as-data") == (
        f"{links.DOCS_BASE_URL}accounts/#roles-as-data"
    )
    assert links.docs_page("") == links.DOCS_BASE_URL


def test_metadata_files_are_in_sync() -> None:
    """pyproject.toml, package.json, mkdocs.yml and the ESLint docs link carry the same values."""
    assert links.sync(ROOT, dry_run=True) == []


def test_prose_carries_no_foreign_karni_urls() -> None:
    """README, SECURITY, docs and templates only link to the configured repository and site."""
    stale = links.stale_prose(ROOT)
    assert stale == [], "\n".join(stale)


def test_check_command_exits_clean() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "karni.links", "check"], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_errorcodes_module_loads_by_path_without_karni(tmp_path: Path) -> None:
    """karni-cli loads the registry by path; the links fallback must work there too."""
    bundle = tmp_path / "errorcodes"
    bundle.mkdir()
    source = Path(errorcodes.__file__)
    bundle.joinpath("__init__.py").write_text(source.read_text())
    bundle.joinpath("links.py").write_text(Path(links.__file__).read_text())
    code = (
        "import importlib.util, sys\n"
        "sys.modules.pop('karni', None); sys.modules.pop('karni.links', None)\n"
        "sys.path = [p for p in sys.path if 'packages/karni' not in p and p]\n"
        f"spec = importlib.util.spec_from_file_location('bundled', {str(bundle / '__init__.py')!r})"
        "\n"
        "m = importlib.util.module_from_spec(spec); sys.modules['bundled'] = m\n"
        "spec.loader.exec_module(m)\n"
        "print(m.DOCS_BASE_URL)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == links.DOCS_BASE_URL, result.stderr


def test_no_literal_base_urls_left_in_python_sources() -> None:
    """The site and repository URLs appear in Python only through karni.links."""
    pattern = re.compile(re.escape(links.DOCS_BASE_URL) + "|" + re.escape(links.REPO_URL))
    offenders = []
    for path in (ROOT / "packages/karni/karni").rglob("*.py"):
        if path.name == "links.py":
            continue
        source = path.read_text()
        prose = set()  # lines inside docstrings and comments: examples, not configuration
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.STRING, tokenize.COMMENT) and (
                token.type == tokenize.COMMENT or token.string.startswith(('"""', "'''"))
            ):
                prose.update(range(token.start[0], token.end[0] + 1))
        for number, line in enumerate(source.splitlines(), 1):
            if number not in prose and pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
