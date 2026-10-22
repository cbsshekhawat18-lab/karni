"""Machine-local CLI state: ``.karni/local/state.json`` in the project.

Never committed: ``.karni/local/`` carries its own ``.gitignore`` (``*``), so
it stays untracked in any project without touching the root ``.gitignore``
(the scaffold's ``.gitignore`` lists it too). Holds what must not be shared
with the team — e.g. that a one-time tip was already shown on this machine.
Unreadable or corrupt state reads as empty; a failed write is reported to the
caller, never raised.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCAL_DIR = Path(".karni") / "local"
STATE_FILE = "state.json"
GITIGNORE = "# Machine-local karni state (karni_cli.local_state). Never commit it.\n*\n"


def state_path(project: Path) -> Path:
    return project / LOCAL_DIR / STATE_FILE


def read_state(project: Path) -> dict[str, Any]:
    try:
        data = json.loads(state_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(project: Path, state: dict[str, Any]) -> bool:
    """Write ``state`` atomically (creating the self-ignoring directory); False on failure."""
    directory = project / LOCAL_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.is_file():
            ignore.write_text(GITIGNORE, encoding="utf-8")
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, directory / STATE_FILE)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except (OSError, TypeError, ValueError):
        return False
    return True


def tip_shown(project: Path, tip: str) -> bool:
    shown = read_state(project).get("tips_shown")
    return isinstance(shown, dict) and tip in shown


def mark_tip_shown(project: Path, tip: str) -> bool:
    state = read_state(project)
    shown = state.get("tips_shown")
    if not isinstance(shown, dict):
        shown = {}
    shown[tip] = datetime.now(UTC).isoformat(timespec="seconds")
    state["tips_shown"] = shown
    return write_state(project, state)
