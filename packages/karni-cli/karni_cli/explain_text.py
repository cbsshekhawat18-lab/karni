"""``karni explain -``: recognise a Karni failure in a pasted traceback or log line.

The catalogue is Karni's (:mod:`karni.errorcodes.failures`, stdlib only),
loaded by path from the monorepo source or the copy bundled into this wheel,
so it needs neither Django nor a project. The CLI adds what only it knows:
its own ``C`` codes (:func:`karni_cli.errorcodes.lookup`), the agent rules
(``K`` codes, architecture and ESLint ids) and the project root, which makes
frames under it project frames and shows them relative to it.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from karni_cli import agent_data
from karni_cli.errorcodes import failures_module, lookup
from karni_cli.project import CliError, find_project

__all__ = ["diagnose_text", "render"]


def _rules(project: Path | None) -> list[dict[str, Any]]:
    try:
        return agent_data.load(project).rules
    except CliError:
        return []


def diagnose_text(text: str, project: Path | None = None) -> Any:
    """The :class:`~karni.errorcodes.failures.Diagnosis` of ``text``.

    ``project`` defaults to the project around the working directory (else the
    working directory itself is the root).
    """
    module = failures_module()
    if module is None:
        raise CliError(
            "This karni-cli has no failure catalogue (karni/errorcodes/failures.py); "
            "the install is incomplete.",
            code="C005",
        )
    root = project or find_project() or Path.cwd()
    cached = functools.lru_cache(maxsize=None)(lookup)
    return module.diagnose(text, root=root, lookup=cached, rules=_rules(project or find_project()))


def render(text: str, *, as_json: bool = False, project: Path | None = None) -> str:
    """What ``karni explain -`` prints for ``text`` (``--json``: the diagnosis as JSON)."""
    if not text.strip():
        raise CliError(
            "Nothing to explain: stdin was empty. Pipe the traceback or log line in "
            "(karni explain - < traceback.txt), give a code (karni explain E104), or name a "
            "captured failure (karni explain --failure last).",
            code="C340",
        )
    diagnosis = diagnose_text(text, project)
    if as_json:
        return json.dumps(diagnosis.as_dict(), indent=2, ensure_ascii=False)
    return str(diagnosis.render())
