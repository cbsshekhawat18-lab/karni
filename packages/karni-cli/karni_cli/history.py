"""The CLI's side of history providers (``karni.agent.history``).

Providers run in the CLI's own environment, through
:func:`karni_cli.agent_data.history_module` (karni's copy, else the bundled
one). With no module, no provider or no store, every function here answers
"nothing" — Karni behaves exactly as if history did not exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from karni_cli import agent_data
from karni_cli.project import CliError


def target(project: Path, raw: str) -> str:
    """``raw`` (relative to the cwd, or absolute) as a project-relative POSIX path."""
    candidate = Path(raw).expanduser()
    absolute = (candidate if candidate.is_absolute() else Path.cwd() / candidate).resolve()
    try:
        relative = absolute.relative_to(project.resolve())
    except ValueError:
        raise CliError(f"{raw} is outside the project ({project}).", code="C010") from None
    if relative == Path("."):
        raise CliError("--with-history PATH names a file, not the project root.", code="C010")
    return relative.as_posix()


def block(project: Path, path: str | None) -> str | None:
    """The capped ``HISTORY:`` block for ``path`` (or the project), or ``None``."""
    module = agent_data.history_module()
    if module is None:
        return None
    result = module.compose(project, path)
    return result if isinstance(result, str) and result else None


def discovered() -> Any | None:
    """:class:`karni.agent.history.Discovered`, or ``None`` without the module."""
    module = agent_data.history_module()
    return None if module is None else module.discover()


def detected_names(project: Path) -> list[str]:
    module = agent_data.history_module()
    if module is None:
        return []
    return [provider.name for provider in module.detected(project)]


def provider_present(project: Path) -> bool:
    """A provider detects a store here, or a third-party provider is installed."""
    module = agent_data.history_module()
    if module is None:
        return False
    found = module.discover()
    return bool(found.third_party()) or module.store_detected(project, found.providers)
