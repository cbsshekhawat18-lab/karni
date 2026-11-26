"""The experimental mark is shown once per feature, in the places docs/stability.md names.

``scripts/experimental.toml`` lists the features that are experimental now
(docs/stability.md#experimental-names). For each one it names:

- ``docs``: the docs sections that describe it (``page.md`` for a whole page,
  ``page.md#anchor`` for a section, a package README the same way). Each
  opens with the note: ``!!! warning "Experimental"`` (or ``> **Experimental.**``
  in a README) right under its heading, or a heading that ends in
  ``(experimental)``.
- ``marks``: its public entry points (``path`` for a module's docstring or a
  file's first doc comment, ``path::name`` for one class, function or export),
  each starting with ``Experimental.``.

The run fails when a feature has no note at one of its sections, no line in
docs/stability.md's "Experimental now" list, or an entry point without the
mark, and when the word is anywhere else in a tracked file: in a docstring,
a comment, a help text, a setting's description, a table row or another docs
section. The ``[allow]`` table lists the few places where the word is not the
mark (a manifest's ``status`` value, a third party's own feature).

    python scripts/check_experimental.py          # exit 1 and list each problem
    python scripts/check_experimental.py --root DIR

CI runs it, and ``packages/karni-cli/tests/test_experimental_marks.py`` runs it
on every test run.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = "scripts/experimental.toml"
STABILITY = "docs/stability.md"
WORD = re.compile(r"experimental", re.I)
MARK = re.compile(r"\bExperimental\.")
#: Where the word is not a mark: an anchor that holds it (a link to the rule or to a
#: section of an experimental feature, or the old anchor a graduated heading keeps).
ANCHOR = re.compile(r"(#|\bid=\")[\w./-]*experimental[\w-]*", re.I)
NOTE = '!!! warning "Experimental"'
README_NOTE = "> **Experimental.**"
#: Generated or historical text: what a release changed, written once.
HISTORY = ("CHANGELOG.md", "docs/migrations/*", "packages/karni/karni/changelog/*")
TEXT = (
    ".py", ".ts", ".tsx", ".mts", ".mjs", ".js", ".css", ".html", ".md", ".toml",
    ".yml", ".yaml", ".json", ".txt", ".cfg",
)  # fmt: skip


@dataclass(frozen=True)
class Feature:
    name: str
    docs: tuple[str, ...]
    marks: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    features: tuple[Feature, ...]
    #: path glob -> regular expressions of the lines where the word is allowed.
    allow: tuple[tuple[str, re.Pattern[str]], ...]


def load(root: Path = ROOT) -> Config:
    data = tomllib.loads((root / CONFIG_PATH).read_text(encoding="utf-8"))
    features = tuple(
        Feature(f["name"], tuple(f["docs"]), tuple(f.get("marks", ()))) for f in data["feature"]
    )
    allow = tuple((a["path"], re.compile(a["line"])) for a in data.get("allow", ()))
    return Config(features, allow)


# --- docs sections ----------------------------------------------------------


def mkdocs_slug(heading: str) -> str:
    """The anchor mkdocs (Python-Markdown's toc) gives a heading."""
    text = re.sub(r"[^\w\s-]", "", heading.replace("`", "")).strip().lower()
    return re.sub(r"[-\s]+", "-", text)


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading in a README."""
    text = heading.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def headings(lines: list[str], readme: bool) -> list[tuple[int, int, str]]:
    """(line index, level, anchor) of each heading outside code blocks."""
    found: list[tuple[int, int, str]] = []
    seen: dict[str, int] = {}
    fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        match = None if fence else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if not match:
            continue
        base = (github_slug if readme else mkdocs_slug)(match.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        found.append((i, len(match.group(1)), base if count == 0 else f"{base}_{count}"))
    return found


def note_lines(lines: list[str], start: int) -> range | None:
    """The note right under the heading at ``start`` (or at the page's top), else None."""
    i = start + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].strip() in (NOTE,):
        j = i + 1
        while j < len(lines) and (lines[j].startswith("    ") or not lines[j].strip()):
            if not lines[j].strip() and j + 1 < len(lines) and not lines[j + 1].startswith("    "):
                break
            j += 1
        return range(i, j)
    if i < len(lines) and lines[i].startswith(README_NOTE):
        j = i
        while j < len(lines) and lines[j].startswith(">"):
            j += 1
        return range(i, j)
    if start >= 0 and lines[start].rstrip().lower().endswith("(experimental)"):
        return range(start, start + 1)
    return None


def page_top(lines: list[str]) -> int:
    """The line index of the page's title (its first heading after the front matter)."""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return i
    return -1


def section_notes(root: Path, ref: str) -> tuple[range | None, str]:
    """The note lines of one docs section, and a problem when it is missing."""
    rel, _, anchor = ref.partition("#")
    path = root / rel
    if not path.is_file():
        return None, f"{ref}: no such file"
    lines = path.read_text(encoding="utf-8").splitlines()
    readme = not rel.startswith("docs/")
    if not anchor:
        top = page_top(lines)
        found = note_lines(lines, top)
        return found, "" if found else f"{ref}: the page does not open with the note"
    for index, _, slug in headings(lines, readme):
        if slug == anchor:
            found = note_lines(lines, index)
            return found, "" if found else f"{ref}: the section does not open with the note"
    return None, f"{ref}: no heading has this anchor"


# --- entry points -------------------------------------------------------------


def python_docstring(source: str, name: str) -> str | None:
    tree = ast.parse(source)
    if not name:
        return ast.get_docstring(tree, clean=False)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name.rsplit(".", 1)[-1]
        ):
            return ast.get_docstring(node, clean=False)
    return None


def ts_doc(source: str, name: str) -> str | None:
    if not name:
        match = re.match(r"\s*/\*\*(.*?)\*/", source, re.S)
        return match.group(1) if match else None
    pattern = (
        r"/\*\*((?:(?!\*/).)*)\*/\s*export\s+(?:default\s+)?(?:async\s+)?"
        rf"(?:function|const|class|type|interface)\s+{re.escape(name)}\b"
    )
    match = re.search(pattern, source, re.S)
    return match.group(1) if match else None


def starts_with_mark(doc: str) -> bool:
    text = re.sub(r"^[\s*]+", "", doc)
    return text.startswith("Experimental.")


def check_mark(root: Path, ref: str) -> str:
    rel, _, name = ref.partition("::")
    path = root / rel
    if not path.is_file():
        return f"{ref}: no such file"
    source = path.read_text(encoding="utf-8")
    doc = python_docstring(source, name) if rel.endswith(".py") else ts_doc(source, name)
    if doc is None:
        return f"{ref}: no docstring or doc comment"
    if not starts_with_mark(doc):
        return f"{ref}: the docstring does not start with 'Experimental.'"
    return ""


# --- the scan -------------------------------------------------------------------


def tracked(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [f for f in result.stdout.splitlines() if f.endswith(TEXT)]


def matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def stability_lines(root: Path) -> range:
    """The 'Experimental names' section of docs/stability.md: the word belongs there."""
    lines = (root / STABILITY).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == "## Experimental names")
    end = next(
        (i for i, line in enumerate(lines) if i > start and line.startswith("## ")), len(lines)
    )
    return range(start, end)


def experimental_now(root: Path) -> str:
    """The text of the 'Experimental now' list in docs/stability.md."""
    text = (root / STABILITY).read_text(encoding="utf-8")
    return text.split("Experimental now:", 1)[1].split("\nStable since", 1)[0]


def problems(root: Path = ROOT, config: Config | None = None) -> list[str]:
    config = config or load(root)
    found: list[str] = []
    allowed_lines: dict[str, set[int]] = {}
    marks_per_file: dict[str, int] = {}
    listed = experimental_now(root)
    for feature in config.features:
        first = feature.docs[0].removeprefix("docs/")
        if not re.search(rf"\]\((?:[^)\s]*/)?{re.escape(first)}\)", listed):
            found.append(f"{feature.name}: no line in {STABILITY}'s 'Experimental now' links {first}")
        for ref in feature.docs:
            lines, problem = section_notes(root, ref)
            if problem:
                found.append(f"{feature.name}: {problem}")
            elif lines is not None:
                allowed_lines.setdefault(ref.partition("#")[0], set()).update(lines)
        for ref in feature.marks:
            problem = check_mark(root, ref)
            if problem:
                found.append(f"{feature.name}: {problem}")
            rel = ref.partition("::")[0]
            marks_per_file[rel] = marks_per_file.get(rel, 0) + 1
    allowed_lines.setdefault(STABILITY, set()).update(stability_lines(root))
    for rel in tracked(root):
        if rel == CONFIG_PATH or matches(rel, HISTORY):
            continue
        path = root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if not WORD.search(text):
            continue
        rules = [line for glob, line in config.allow if fnmatch.fnmatch(rel, glob)]
        own = allowed_lines.get(rel, set())
        marks = 0
        for number, line in enumerate(text.splitlines()):
            if number in own:
                continue
            rest = ANCHOR.sub("", line)
            if any(rule.search(rest) for rule in rules):
                continue
            if not WORD.search(rest):
                continue
            if rel in marks_per_file and MARK.search(rest):
                marks += len(MARK.findall(rest))
                continue
            found.append(f"{rel}:{number + 1}: the mark outside the places the rule names")
        expected = marks_per_file.get(rel)
        if expected is not None and marks > expected:
            found.append(
                f"{rel}: {marks} marks, but {CONFIG_PATH} names {expected} entry point(s) here"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    found = problems(args.root)
    if found:
        print("\n".join(found), file=sys.stderr)
        print(
            f"\n{len(found)} problem(s). The rule: docs/stability.md#where-the-mark-is-shown. "
            f"The features and their places: {CONFIG_PATH}.",
            file=sys.stderr,
        )
        return 1
    count = len(load(args.root).features)
    print(f"The experimental mark is where the rule puts it ({count} features).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
