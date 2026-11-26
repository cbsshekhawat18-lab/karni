"""The version range a project holds Karni and its modules at.

Karni's packages are released in lockstep, and a module's own range on karni
is its minor (``karni>=0.8,<0.9``). A project that lists them bare gets the
newest of each on every install, so one ``pip install -U`` for a module's extra
can move karni itself. This module writes the same range into a project:

* ``karni new`` writes ``karni`` at the range of this karni-cli's own version
  (the template takes it as ``karni_range``, so no version is written in it);
* ``karni add`` writes a module at the range the project holds ``karni`` at
  (:func:`project_range`), and a project that lists ``karni`` bare at the
  line of its ``[tool.karni] baseline``;
* ``karni upgrade`` writes the range of the release it moves to
  (:func:`with_ranges`), also for a project that listed them bare.

A development install of this karni-cli (a ``.dev`` or ``+local`` version) is
written as its line with the ``.dev0`` floor, so a checkout satisfies it.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from karni_cli.project import compose_service_running, venv_python

__all__ = [
    "Line",
    "cli_line",
    "compatible_range",
    "first_party",
    "project_line",
    "requirement_text",
    "spec_text",
    "with_ranges",
]

KARNI = "karni"


@dataclass(frozen=True)
class Line:
    """A release line: ``0.7`` (before 1.0 a minor is a line, from 1.0 on a major is)."""

    major: int
    minor: int
    development: bool = False

    @property
    def text(self) -> str:
        return f"{self.major}.{self.minor}"

    def range(self) -> str:
        floor = f"{self.major}.{self.minor}" + (".0.dev0" if self.development else "")
        ceiling = f"0.{self.minor + 1}" if self.major == 0 else str(self.major + 1)
        return f">={floor},<{ceiling}"


def compatible_range(version: str) -> Line | None:
    """The line ``version`` belongs to, ``None`` for text that is not a release number."""
    try:
        parsed = Version(version)
    except InvalidVersion:
        return None
    if len(parsed.release) < 2:  # "0+unknown": a source tree that was never installed
        return None
    return Line(
        parsed.release[0],
        parsed.release[1],
        development=parsed.is_devrelease or parsed.is_prerelease or bool(parsed.local),
    )


def cli_line() -> Line | None:
    """The line of this karni-cli: what a new project is written for."""
    from karni_cli import __version__

    return compatible_range(__version__)


def first_party() -> frozenset[str]:
    """The distributions Karni releases in lockstep: karni and the modules of its catalog."""
    from karni_cli import catalog

    names = {KARNI, "karni-cli"}
    names.update(canonicalize_name(m.distribution) for m in catalog.load(ask_project=False).modules)
    return frozenset(names)


def spec_text(spec: SpecifierSet) -> str:
    """A range as the packages write theirs: the floor first (``>=0.8,<0.9``)."""
    return ",".join(sorted((str(item) for item in spec), key=lambda text: (text[0] == "<", text)))


def requirement_text(requirement: Requirement, spec: SpecifierSet) -> str:
    """``requirement`` held at ``spec``, extras and marker kept, the floor written first."""
    held = Requirement(str(requirement))
    held.specifier = SpecifierSet()
    marker = f" ; {held.marker}" if held.marker else ""
    held.marker = None
    return f"{held}{spec_text(spec)}{marker}"


def _requirements(text: str) -> list[Requirement]:
    try:
        deps = tomllib.loads(text).get("project", {}).get("dependencies", [])
    except tomllib.TOMLDecodeError:
        return []
    found = []
    for dep in deps:
        try:
            found.append(Requirement(str(dep)))
        except InvalidRequirement:
            continue
    return found


def baseline(text: str) -> str | None:
    """``[tool.karni] baseline`` of a pyproject.toml text."""
    try:
        value = tomllib.loads(text).get("tool", {}).get("karni", {}).get("baseline")
    except tomllib.TOMLDecodeError:
        return None
    return str(value) if value else None


def project_line(text: str) -> tuple[SpecifierSet, str] | None:
    """What a module added to this project is held at: ``(range, where it came from)``.

    The range ``karni`` has in ``[project].dependencies``. A project that lists
    ``karni`` bare is held at the line of its ``[tool.karni] baseline``, and one
    without either at this karni-cli's own line. ``None`` when none is known.
    """
    for requirement in _requirements(text):
        if canonicalize_name(requirement.name) == KARNI and str(requirement.specifier):
            return requirement.specifier, "the range karni has in pyproject.toml"
    recorded = baseline(text)
    line = compatible_range(recorded) if recorded else None
    if line is not None and (line.major, line.minor) != (0, 0):
        return SpecifierSet(line.range()), f"the line of the project's baseline ({recorded})"
    own = cli_line()
    if own is not None:
        return SpecifierSet(own.range()), "the release of this karni-cli"
    return None


def with_ranges(text: str, line: Line) -> tuple[str, list[tuple[str, str]]]:
    """pyproject.toml ``text`` with karni and each first-party module held at ``line``.

    Returns the text and ``(before, after)`` per requirement that changed. A
    third-party package, a requirement that is not first-party, and one that
    already has the range are left as they are. Extras and markers are kept.
    """
    document = tomlkit.parse(text)
    try:
        deps = document["project"]["dependencies"]
    except (KeyError, TypeError):
        return text, []
    ours = first_party()
    changed: list[tuple[str, str]] = []
    for index, dep in enumerate(list(deps)):
        try:
            requirement = Requirement(str(dep))
        except InvalidRequirement:
            continue
        name = canonicalize_name(requirement.name)
        if name not in ours or name == "karni-cli":
            continue
        written = requirement_text(requirement, SpecifierSet(line.range()))
        if written != str(dep):
            changed.append((str(dep), written))
            deps[index] = written
    return (tomlkit.dumps(document) if changed else text), changed


def installed_in(project: Path) -> dict[str, str] | None:
    """The release versions of karni and its modules in the project's interpreter.

    Asked as ``python -m karni.versions`` (the CLI never imports project code).
    ``None`` when no interpreter answers.
    """
    python = venv_python(project)
    if python is not None:
        command = [str(python), "-m", "karni.versions"]
    elif compose_service_running(project, "django"):
        command = ["docker", "compose", "exec", "-T", "django", "python", "-m", "karni.versions"]
    else:
        return None
    try:
        proc = subprocess.run(
            command,
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(name): str(version) for name, version in data.items()}


def unpinned(text: str) -> list[str]:
    """The karni distributions pyproject.toml lists without a version range."""
    ours = first_party()
    return sorted(
        requirement.name
        for requirement in _requirements(text)
        if canonicalize_name(requirement.name) in ours and not str(requirement.specifier)
    )


def doctor_lines(project: Path) -> list[str]:
    """What ``karni doctor`` says about the version line: installed, this CLI, pyproject.toml."""
    from karni_cli import __version__

    lines: list[str] = []
    installed = installed_in(project)
    own = cli_line()
    if installed is None:
        lines.append("not checked: no interpreter answered (karni doctor shows how commands run)")
    elif "karni" not in installed:
        lines.append("karni is not a release here (a checkout), so nothing is compared")
    else:
        reference = compatible_range(installed["karni"])
        everything = {**installed, "karni-cli": __version__}
        off = {
            name: version
            for name, version in everything.items()
            if reference is not None
            and (compatible_range(version) or reference).text != reference.text
            and not (name == "karni-cli" and compatible_range(version) is None)
        }
        shown = ", ".join(f"{name} {version}" for name, version in sorted(everything.items()))
        if off:
            names = ", ".join(f"{name} {version}" for name, version in sorted(off.items()))
            lines.append(
                f"NOT one line (karni.W521): {names} is not on karni's {reference.text if reference else '?'}"
            )
            lines.append(f"installed: {shown}")
        else:
            lines.append(f"one line ({shown})")
    try:
        bare = unpinned((project / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        bare = []
    if bare:
        floor = own.range() if own is not None else ">=0.8,<0.9"
        lines.append(
            f"pyproject.toml lists {', '.join(bare)} without a range, so an install takes the "
            f"newest of each. Pin them (karni{floor}) or run `karni upgrade`, which writes it"
        )
    return lines
