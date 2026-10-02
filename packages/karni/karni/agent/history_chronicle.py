"""Built-in history provider for Gigai Chronicle (MIT, local-only).

Karni never imports Chronicle and never depends on it. This module only looks
for a ``.chronicle/`` directory and, when one exists and ``chronicle`` is on
PATH, shells out to it. Every failure means "no brief": no store, no binary,
exit 3 (not a chronicle project) or any other non-zero exit, a timeout, output
that is not the documented JSON, or an honestly empty pack. The provider then
returns ``None``; it never raises and never prints, and Chronicle's stderr is
discarded.

Chronicle's CLI contract used here (``--json`` envelope ``apiVersion`` 1)::

    chronicle context <repo-relative file> --json --limit N
      {"apiVersion": 1, "command": "context", "file": str, "empty": bool,
       "prompts": [{"eventId", "ts", "session", "text", "churn"}],
       "knowledge": [{"kind", "text", "eventId", "session", "ts", "role", "confidence"}],
       "markdown": str}
    chronicle knowledge --type decision --json
      {"apiVersion": 1, "command": "knowledge", "count": int, "items": [...]}

Exit codes: 0 ok, 1 failure, 2 usage, 3 not a chronicle project.

Escape hatch: register your own instance under the ``karni.history_providers``
entry-point name ``gigai-chronicle`` (for example
``ChronicleProvider(timeout=15.0)``); it replaces this default.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

#: The store directory Chronicle walks up to find (its ``findChronicleDir``).
STORE_DIR = ".chronicle"
#: Chronicle's "not a chronicle project" exit status.
EXIT_NOT_A_PROJECT = 3
API_VERSION = 1

#: Chronicle's prompt-list section; moved last so a capped brief keeps the
#: decisions / failed approaches, which matter most before an edit.
_PROMPTS_SECTION = "## what shaped"
_SPACES = re.compile(r"[ \t]{2,}")


class ChronicleProvider:
    name = "gigai-chronicle"

    def __init__(
        self, executable: str = "chronicle", *, timeout: float = 5.0, limit: int = 5
    ) -> None:
        self.executable = executable
        #: Seconds before Chronicle is abandoned (the brief is then empty).
        self.timeout = timeout
        #: Max shaping prompts requested (Chronicle's ``--limit``; its default is 8).
        self.limit = limit

    # --- protocol ------------------------------------------------------------------

    def store(self, project_root: Path) -> Path | None:
        """The nearest ``.chronicle/`` at or above ``project_root`` (Chronicle's walk-up)."""
        current = Path(project_root).resolve()
        for candidate in (current, *current.parents):
            if (candidate / STORE_DIR).is_dir():
                return candidate / STORE_DIR
        return None

    def detect(self, project_root: Path) -> bool:
        return self.store(project_root) is not None

    def context(self, project_root: Path, path: str) -> str | None:
        store = self.store(project_root)
        if store is None:
            return None
        repo = store.parent
        try:
            absolute = Path(os.path.normpath(Path(project_root).resolve() / path))
            target = absolute.relative_to(repo)
        except ValueError:
            return None
        if target == Path("."):
            return None
        payload = self._run(
            repo, ["context", target.as_posix(), "--json", "--limit", str(self.limit)], "context"
        )
        if payload is None or payload.get("empty") is True:
            return None
        markdown = payload.get("markdown")
        brief = (
            brief_from_markdown(markdown)
            if isinstance(markdown, str)
            else brief_from_pack(payload.get("prompts"), payload.get("knowledge"))
        )
        return brief or None

    def project_context(self, project_root: Path) -> str | None:
        """The project's recorded decisions, newest first (no file named)."""
        store = self.store(project_root)
        if store is None:
            return None
        args = ["knowledge", "--type", "decision", "--json"]
        payload = self._run(store.parent, args, "knowledge")
        if payload is None:
            return None
        return brief_from_decisions(payload.get("items")) or None

    def full_command(self, project_root: Path, path: str | None) -> str:
        if path is None:
            return "chronicle knowledge --type decision"
        return f"chronicle context {shlex.quote(path)}"

    # --- the one place Chronicle runs ----------------------------------------------

    def _run(self, repo: Path, args: list[str], command: str) -> dict[str, Any] | None:
        executable = shutil.which(self.executable)
        if executable is None:
            return None
        try:
            proc = subprocess.run(
                [executable, *args],
                cwd=repo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        if proc.returncode != 0:  # 3 = not a chronicle project; 1/2 = failure/usage
            return None
        return parse_envelope(proc.stdout, command)


# --- pure helpers (tested without a binary) --------------------------------------------


def parse_envelope(stdout: str, command: str) -> dict[str, Any] | None:
    """The ``--json`` payload for ``command``, or ``None`` if it is not one.

    Chronicle prints exactly one JSON line; the last non-empty line is tried
    too, in case anything precedes it.
    """
    lines = [line for line in stdout.splitlines() if line.strip()]
    for candidate in (stdout, lines[-1] if lines else ""):
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("apiVersion") == API_VERSION
            and payload.get("command") == command
        ):
            return payload
        return None
    return None


def brief_from_markdown(markdown: str) -> str:
    """Chronicle's paste-ready brief, compacted for an agent.

    Drops the title, the italic boilerplate paragraphs, horizontal rules and
    blank lines; collapses runs of spaces; and moves the "What shaped this
    file" prompt list after the decision/memory sections. Unknown structure is
    kept as-is, so a future Chronicle format degrades to "longer", not "wrong".
    """
    kept: list[str] = []
    in_italic = False
    for raw in markdown.splitlines():
        text = raw.strip()
        if in_italic:
            in_italic = bool(text) and not text.endswith("_")
            continue
        if not text or text == "---" or text.startswith("# "):
            continue
        if text.startswith("_") and not text.startswith("__"):
            in_italic = not (len(text) > 1 and text.endswith("_"))
            continue
        kept.append(_SPACES.sub(" ", raw.rstrip()))
    preamble: list[str] = []
    sections: list[list[str]] = []
    for line in kept:
        if line.startswith("## "):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
        else:
            preamble.append(line)
    prompts = [s for s in sections if s[0].lower().startswith(_PROMPTS_SECTION)]
    others = [s for s in sections if not s[0].lower().startswith(_PROMPTS_SECTION)]
    ordered = preamble + [line for section in (*others, *prompts) for line in section]
    return "\n".join(ordered)


def _when(ts: object) -> str:
    return str(ts)[:10] if isinstance(ts, str) else ""


def brief_from_pack(prompts: object, knowledge: object) -> str:
    """A brief from the structured pack, for a payload without ``markdown``."""
    lines: list[str] = []
    items = [k for k in knowledge if isinstance(k, dict)] if isinstance(knowledge, list) else []
    if items:
        lines.append("## Decisions & TODOs")
        for item in items:
            if isinstance(item.get("text"), str) and item["text"].strip():
                lines.append(f"- [{item.get('kind', 'note')}] {item['text'].strip()}")
    shaped = [p for p in prompts if isinstance(p, dict)] if isinstance(prompts, list) else []
    if shaped:
        lines.append("## What shaped this file")
        for i, prompt in enumerate(shaped, start=1):
            text = prompt.get("text")
            quoted = '"' + " ".join(text.split()) + '"' if isinstance(text, str) else "(no text)"
            lines.append(f"{i}. {_when(prompt.get('ts'))} {prompt.get('churn', '')} — {quoted}")
    return "\n".join(_SPACES.sub(" ", line) for line in lines)


def brief_from_decisions(items: object) -> str:
    """``chronicle knowledge`` decisions as a newest-first list."""
    decisions = [
        item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, dict)
        and item.get("kind", "decision") == "decision"
        and isinstance(item.get("text"), str)
        and item["text"].strip()
    ]
    if not decisions:
        return ""
    decisions.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    lines = ["Recorded decisions (newest first):"]
    for item in decisions:
        when = _when(item.get("ts"))
        text = " ".join(item["text"].split())
        lines.append(f"- {when} {text}" if when else f"- {text}")
    return "\n".join(lines)
