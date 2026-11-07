"""Every link in the READMEs and docs/ that points inside the repository resolves.

A link to a missing file or to a ``#fragment`` the target does not define is a
dead end for the reader. mkdocs reports a missing anchor at INFO level only,
so ``mkdocs build --strict`` passes with it. This test fails instead (A6-02).

Targets resolve against the linking file's directory. A fragment must be a
heading's id or an explicit ``<a id>``, ``id="..."`` or ``{#id}``. Pages under
docs/ are read on the site, so their headings get the ids mkdocs gives them
(Python-Markdown's ``toc`` slugs). A link from a file outside docs/ is
followed on GitHub, which slugs headings its own way, so either id counts.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path
from urllib.parse import unquote

import pytest

from tests.conftest import REPO_ROOT

DOCS = REPO_ROOT / "docs"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="needs the repository checkout (docs/)")

LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
ATTR_ID = re.compile(r"\{[^}]*#([\w:.-]+)[^}]*\}\s*$")
HTML_ID = re.compile(r"""<[a-zA-Z][^>]*?\b(?:id|name)=["']([^"']+)["']""")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+)(?:.+?)(?<!`)\1(?!`)")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//")


def _prose(path: Path, *, spans: bool = False) -> list[str]:
    """The file's lines with fenced blocks blanked, and code spans too unless ``spans``."""
    lines, fence = [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        match = FENCE.match(line)
        if match and (not fence or match[1][0] == fence[0] and len(match[1]) >= len(fence)):
            fence = "" if fence else match[1]
            lines.append("")
        elif fence:
            lines.append("")
        else:
            lines.append(line if spans else CODE_SPAN.sub(lambda span: " " * len(span[0]), line))
    return lines


def _heading_text(markdown: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", markdown)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("*", "")  # emphasis. An underscore stays (snake_case names).


def site_slug(heading: str) -> str:
    """Python-Markdown's ``toc`` slugify, which mkdocs uses for heading ids."""
    value = unicodedata.normalize("NFKD", _heading_text(heading))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def github_slug(heading: str) -> str:
    """GitHub's heading id: punctuation dropped, each space a hyphen, nothing collapsed."""
    value = re.sub(r"[^\w\- ]", "", _heading_text(heading).strip().lower())
    return value.replace(" ", "-")


@cache
def anchors(path: Path, *, github: bool = False) -> frozenset[str]:
    """Every fragment a link may name in ``path``, on the site or (``github``) on GitHub."""
    found: set[str] = set()
    seen: dict[str, int] = {}
    raw = path.read_text(encoding="utf-8")
    for line in _prose(path, spans=True):
        match = HEADING.match(line)
        if not match:
            continue
        title = match[2]
        explicit = ATTR_ID.search(title)
        if explicit:
            found.add(explicit[1])
            continue
        slug = site_slug(title)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(f"{slug}_{count}" if count else slug)
        if github:
            found.add(github_slug(title) + (f"-{count}" if count else ""))
    found.update(HTML_ID.findall(raw))
    found.update(re.findall(r"\{[^}\n]*#([\w:.-]+)[^}\n]*\}", raw))
    return frozenset(found)


def link_problems(files: list[Path], root: Path = REPO_ROOT) -> list[str]:
    """``file:line: target: what is wrong`` for every in-repository link that does not resolve."""
    problems = []
    for path in files:
        github = DOCS not in path.parents  # read on GitHub, not on the site
        for number, line in enumerate(_prose(path), 1):
            targets = [match[1] for match in LINK.finditer(line)]
            targets += [match[1] for match in REFERENCE.finditer(line)]
            for target in targets:
                target = target.strip("<>")
                if SCHEME.match(target):
                    continue
                file_part, _, fragment = target.partition("#")
                file_part = unquote(file_part.split("?", 1)[0])
                where = f"{path.relative_to(root)}:{number}: {target}"
                destination = (path.parent / file_part).resolve() if file_part else path
                if not destination.exists():
                    problems.append(f"{where}: no such file")
                elif destination.is_dir() and fragment:
                    index = destination / "index.md"
                    if index.is_file() and fragment not in anchors(index, github=github):
                        problems.append(f"{where}: no anchor #{fragment} in {index.name}")
                elif (
                    fragment
                    and destination.suffix == ".md"
                    and fragment not in anchors(destination, github=github)
                ):
                    problems.append(
                        f"{where}: {destination.relative_to(root)} has no anchor #{fragment}"
                    )
    return problems


def documentation() -> list[Path]:
    """The README, the docs/ pages (not docs/seo/, which is not published) and every package README."""
    pages = [
        path for path in sorted(DOCS.rglob("*.md")) if "seo" not in path.relative_to(DOCS).parts
    ]
    readmes = [
        REPO_ROOT / "README.md",
        *sorted(REPO_ROOT.glob("packages/*/README.md")),
        *sorted(REPO_ROOT.glob("modules/*/README.md")),
        *sorted(REPO_ROOT.glob("modules/*/ui/README.md")),
    ]
    return [path for path in (*readmes, *pages) if path.is_file()]


def test_every_in_repository_link_resolves() -> None:
    problems = link_problems(documentation())
    assert problems == [], "\n".join(problems)


def test_the_check_names_a_missing_file_and_a_missing_anchor(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "deploy.md").write_text('# Deploy\n\n## 12. Health checks\n\n<a id="probes"></a>\n')
    (docs / "settings.md").write_text(
        "See [deploy](deploy.md#health-checks), [probes](deploy.md#probes),\n"
        "[the checks](deploy.md#12-health-checks), [gone](missing.md) and\n"
        "`[not a link](nowhere.md)`.\n\n```md\n[nor this](nowhere.md)\n```\n"
    )
    files = [docs / "settings.md"]
    assert link_problems(files, root=tmp_path) == [
        "docs/settings.md:1: deploy.md#health-checks: docs/deploy.md has no anchor #health-checks",
        "docs/settings.md:2: missing.md: no such file",
    ]


def test_the_slugs_match_what_mkdocs_and_github_write() -> None:
    markdown = pytest.importorskip("markdown")
    headings = [
        "12. Health checks",
        "`object_permission_classes`",
        "Accounts & auth",
        "**Bold** step",
    ]
    page = markdown.Markdown(extensions=["toc"])
    page.convert("\n\n".join(f"## {heading}" for heading in headings))
    assert [item["id"] for item in page.toc_tokens] == [site_slug(h) for h in headings]
    assert github_slug("Accounts & auth") == "accounts--auth"
