"""Karni's machine-readable changelog, as karni-cli reads it, and version selection.

The data and its schema live in Karni (``packages/karni/karni/changelog``).
That package is stdlib only, so the CLI loads it by path and never imports
Karni or Django: from the monorepo source when run from a checkout, else from
the copy bundled into the wheel (``karni_cli/_changelog``, see hatch_build.py).
The CLI therefore knows every change up to its own release, whichever karni
the project has installed. That is what lets ``karni upgrade`` run *before*
the project raises its karni pin.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable, Sequence
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version

from karni_cli.project import CliError

if TYPE_CHECKING:
    from karni.changelog import Change

_MODULE_NAME = "karni_cli._bundled_karni_changelog"


def source_dir() -> Path | None:
    """The changelog package: the monorepo source, else the wheel's bundled copy."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni" / "karni" / "changelog"
        if (candidate / "__init__.py").is_file():
            return candidate
    packaged = resources.files("karni_cli") / "_changelog"
    with resources.as_file(packaged) as path:
        if (path / "__init__.py").is_file():
            return path
    return None


def module() -> ModuleType:
    """``karni.changelog``, loaded by path under a private name."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    directory = source_dir()
    if directory is None:
        raise CliError(
            "Karni's changelog is missing from this karni-cli install "
            "(karni_cli/_changelog). Reinstall karni-cli."
        )
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, directory / "__init__.py")
    if spec is None or spec.loader is None:  # pragma: no cover - importlib contract
        raise CliError(f"Cannot load Karni's changelog from {directory}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = loaded
    try:
        spec.loader.exec_module(loaded)
    except Exception:
        del sys.modules[_MODULE_NAME]
        raise
    return loaded


def load(directory: Path | None = None) -> list[Change]:
    """Every recorded change, oldest release first (see ``karni.changelog.load``)."""
    changelog = module()
    try:
        return list(changelog.changes(directory or source_dir()))
    except changelog.ChangelogError as exc:
        raise CliError(str(exc)) from None


def docs_url(anchor: str) -> str:
    """The published link to a migration note (Karni's single ``DOCS_BASE_URL``)."""
    return str(module().docs_url(anchor))


def parse(version: str, what: str) -> Version:
    try:
        return Version(version)
    except InvalidVersion:
        raise CliError(f"{what} {version!r} is not a version number (e.g. 0.2.0).") from None


def newest_release(changes: Iterable[Change]) -> str:
    """The default ``--to``: the newest release that recorded a change."""
    releases = {change.release for change in changes}
    return max(releases, key=Version) if releases else "0"


def horizon(changes: Iterable[Change]) -> Version:
    """The newest version this changelog knows anything about (a release or a removal)."""
    versions = [Version(c.release) for c in changes] + [
        Version(c.removed_in) for c in changes if c.removed_in
    ]
    return max(versions, default=Version("0"))


def select(changes: Sequence[Change], current: str, target: str) -> list[Change]:
    """The changes to apply moving ``current`` -> ``target``, in the order to apply them.

    A change is selected when its replacement exists in the target
    (``release <= target``) and the project has not yet passed the release
    where the old form breaks (``current < breaks_in``). So a deprecation is
    picked up by every upgrade from before its removal, including one from
    the very release that deprecated it, and moving to that release fixes
    the warnings before they break anything. Order: by the release that
    breaks, then the release that introduced, then file order.
    """
    now, then = Version(current), Version(target)
    picked = [
        change
        for change in changes
        if Version(change.release) <= then and now < Version(change.breaks_in)
    ]
    return sorted(picked, key=lambda c: (Version(c.breaks_in), Version(c.release)))
