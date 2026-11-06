"""No AI tool or company names in Karni's tracked files, outside one exceptions list.

Karni works with any coding agent, so the repository and the packages built
from it name none. ``scripts/tool-names.toml`` holds the names (``[[term]]``,
a regular expression each) and the only places that may carry them
(``[[allow]]``, each with its reason): the karni-ai module and the pages
generated from its settings, the deprecation notes that must name the files
they deprecate, the deprecated adapter code that still writes them until 1.0,
and released history. The same file lists a personal home path, so a
machine's own path is caught too.

    python scripts/check_tool_names.py          # exit 1 and list each hit
    python scripts/check_tool_names.py --root DIR

It reads every file ``git ls-files`` lists, skips binary files, and checks
each line. CI runs it, and ``packages/karni-cli/tests/test_tool_names.py``
runs it on every test run.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts" / "tool-names.toml"
#: The config file names every term on purpose, so it is never scanned.
CONFIG_PATH = "scripts/tool-names.toml"


@dataclass(frozen=True)
class Term:
    name: str
    pattern: re.Pattern[str]
    sample: str


@dataclass(frozen=True)
class Allow:
    path: str
    terms: frozenset[str]
    reason: str
    #: When set, only the lines from the first line matching it onward are allowed.
    after: re.Pattern[str] | None = None

    def covers(self, path: str) -> bool:
        return fnmatch.fnmatchcase(path, self.path)

    def allows(self, term: str) -> bool:
        return "*" in self.terms or term in self.terms


@dataclass(frozen=True)
class Config:
    terms: tuple[Term, ...]
    allow: tuple[Allow, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    term: str
    text: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.term}: {self.text.strip()[:120]}"


def load(path: Path = CONFIG) -> Config:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    terms = tuple(
        Term(entry["name"], re.compile(entry["pattern"]), entry["sample"])
        for entry in data.get("term", [])
    )
    names = {term.name for term in terms}
    allow = []
    for entry in data.get("allow", []):
        listed = frozenset(entry["terms"])
        unknown = listed - names - {"*"}
        if unknown:
            raise SystemExit(f"{path}: {entry['path']}: unknown terms {sorted(unknown)}")
        if not entry.get("reason", "").strip():
            raise SystemExit(f"{path}: {entry['path']}: every exception needs a reason")
        after = entry.get("after")
        allow.append(
            Allow(entry["path"], listed, entry["reason"], re.compile(after) if after else None)
        )
    return Config(terms, tuple(allow))


def scan_text(path: str, text: str, config: Config) -> list[Hit]:
    """The hits in one file's text that no exception allows."""
    rules = [allow for allow in config.allow if allow.covers(path)]
    started = {id(allow): allow.after is None for allow in rules}
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        for allow in rules:
            if not started[id(allow)] and allow.after is not None and allow.after.search(line):
                started[id(allow)] = True
        for term in config.terms:
            if not term.pattern.search(line):
                continue
            if any(started[id(allow)] and allow.allows(term.name) for allow in rules):
                continue
            hits.append(Hit(path, number, term.name, line))
    return hits


def scan(files: Iterable[tuple[str, str]], config: Config) -> list[Hit]:
    hits: list[Hit] = []
    for path, text in files:
        if path == CONFIG_PATH:
            continue
        hits += scan_text(path, text, config)
    return hits


def tracked_files(root: Path) -> list[tuple[str, str]]:
    """``(posix path, text)`` for every tracked text file under ``root``."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.decode("utf-8")
    files = []
    for rel in filter(None, listed.split("\0")):
        path = root / rel
        if not path.is_file():
            continue  # deleted in the working tree
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            continue
        try:
            files.append((rel, data.decode("utf-8")))
        except UnicodeDecodeError:
            continue
    return files


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    config = load(args.config or args.root / CONFIG_PATH)
    files = tracked_files(args.root)
    hits = scan(files, config)
    for hit in hits:
        print(hit.render())
    if hits:
        print(
            f"{len(hits)} AI tool or company names outside the exceptions in {CONFIG_PATH}. "
            "Say 'coding agent' instead, or add an exception with its reason.",
            file=sys.stderr,
        )
        return 1
    print(f"No AI tool or company names outside the exceptions ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
