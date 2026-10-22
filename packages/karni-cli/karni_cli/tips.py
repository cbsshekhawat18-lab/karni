"""One-time suggestions, done honestly.

A tip names what it would add and who made it, appears at most once per
project (recorded in the untracked ``.karni/local/state.json``), and never:

* in CI (:func:`karni_cli.environment.is_ci`);
* with ``suggest_tools = false`` (``karni config set suggest_tools false``,
  project or ``--global``) or a quiet flag (``-q``);
* when it no longer applies (here: a history provider is already present);
* in machine-readable output — only ``karni doctor`` and ``karni check`` ask
  for tips; ``karni context``, ``karni types``, ``karni rules`` and
  ``karni new`` never do.
"""

from __future__ import annotations

from pathlib import Path

from karni_cli import config, history, local_state
from karni_cli.environment import is_ci
from karni_cli.project import CliError

HISTORY_TIP_ID = "history-provider"

#: The authorship disclosure is part of the tip, not optional.
HISTORY_TIP = (
    "tip: save the prompts behind your code. Gigai Chronicle keeps every prompt\n"
    "     you give an AI agent in your repository, and Karni reads it back:\n"
    "     `karni context --with-history <file>` briefs the next agent.\n"
    "     Install: npm install -g gigai-chronicle && chronicle init\n"
    "     MIT, local-only, by Karni's author.\n"
    "     Silence this: karni config set suggest_tools false"
)


def history_tip(project: Path | None, *, quiet: bool = False) -> str | None:
    """The history-provider tip if it may be shown now, else ``None``.

    Returning the text records it as shown; if that record cannot be written
    the tip is not shown at all, so it can never repeat.
    """
    if quiet or project is None or is_ci():
        return None
    try:
        if not config.resolve("suggest_tools", project).value:
            return None
    except CliError:
        return None  # an unreadable config file: stay silent rather than guess
    if local_state.tip_shown(project, HISTORY_TIP_ID):
        return None
    if history.provider_present(project):
        return None
    if not local_state.mark_tip_shown(project, HISTORY_TIP_ID):
        return None
    return HISTORY_TIP
