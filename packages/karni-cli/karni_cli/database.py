"""The database guard: a missing driver or an unreachable database is a Karni error.

Django imports the database driver as it starts. With a PostgreSQL
``DATABASE_URL`` and no psycopg in the project interpreter, every project
command (``karni check`` first, as ``karni new`` suggests) used to end in
Django's 25-line traceback, and a database that is not running did the same
to every command that opens it. The guard reports both as one coded error,
C012 or C013, naming what is missing and the fix.

One guard for every runner: :func:`karni_cli.project.run_python`, and so
``run_manage``, calls :func:`guard` for each command that declares
``database=``. :mod:`karni_cli.db_probe` runs in the interpreter the command
uses (the CLI never imports Django):

- before a command whose output streams to the terminal, because a traceback
  cannot be taken back once it is printed;
- after a command whose output is captured (``karni context``, ``karni
  types``) failed, so a working project pays nothing.

``"load"`` checks that every database backend loads, that is, its driver is
installed. ``"connect"`` also opens a connection, for commands that need the
database (``migrate``, ``seed``, ``serve --local``, ``test``, ...). Only host
runs are checked: under docker compose the image has the driver and the stack
has its own database.

Override / escape hatch: ``KARNI_DB_CHECK=false`` skips the check, and the
command runs exactly as it would without it. A runner opts out with
``database=None``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from karni_cli import db_probe
from karni_cli.project import CliError, DatabaseUse

__all__ = ["ENV", "Finding", "enabled", "error", "guard", "parse", "probe"]

#: ``KARNI_DB_CHECK=false`` (or 0/no/off) turns the guard off.
ENV = "KARNI_DB_CHECK"
_FALSE = frozenset({"0", "false", "no", "off"})
#: Seconds before a probe counts as inconclusive; the command then runs as is.
PROBE_TIMEOUT = 60
#: Engine fragment → the pip requirement that installs its driver.
DRIVERS: tuple[tuple[str, str], ...] = (
    ("postg", '"psycopg[binary]"'),
    ("mysql", "mysqlclient"),
    ("oracle", "oracledb"),
)


@dataclass(frozen=True)
class Finding:
    """What the probe found wrong with one database alias."""

    problem: Literal["driver", "unreachable"]
    alias: str
    engine: str
    error: str
    host: str = ""
    port: str = ""
    name: str = ""

    @property
    def address(self) -> str:
        """``database karni at 127.0.0.1:5432`` (as much of it as the settings give)."""
        server = ":".join(part for part in (self.host, self.port) if part)
        parts = [f"database {self.name}" if self.name else "", f"at {server}" if server else ""]
        return " ".join(part for part in parts if part)


def enabled() -> bool:
    """False when ``KARNI_DB_CHECK`` is set to false, 0, no or off."""
    return os.environ.get(ENV, "").strip().lower() not in _FALSE


def parse(stdout: str) -> Finding | None:
    """The finding in the probe's output; ``None`` for ok, unknown or unreadable output."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(db_probe.MARKER):
            try:
                data = json.loads(line.removeprefix(db_probe.MARKER))
            except ValueError:
                return None
            break
    else:
        return None
    if not isinstance(data, dict):
        return None
    problem = data.get("status")
    if problem not in ("driver", "unreachable"):
        return None
    return Finding(
        problem=problem,
        alias=str(data.get("alias") or "default"),
        engine=str(data.get("engine") or "?"),
        error=str(data.get("error") or ""),
        host=str(data.get("host") or ""),
        port=str(data.get("port") or ""),
        name=str(data.get("name") or ""),
    )


def probe(project: Path, python: Path, use: DatabaseUse) -> Finding | None:
    """Run :mod:`karni_cli.db_probe` with ``python`` in ``project``.

    ``None`` when nothing is wrong, and also when the probe cannot tell (no
    interpreter, settings that do not load, a timeout): the command then runs
    and shows its own error.
    """
    source = Path(db_probe.__file__).read_text(encoding="utf-8")
    try:
        proc = subprocess.run(
            [str(python), "-c", source, use],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse(proc.stdout)


def _requirement(engine: str) -> str:
    return next(
        (req for fragment, req in DRIVERS if fragment in engine), f"<the driver {engine} needs>"
    )


def error(finding: Finding, project: Path, python: Path) -> CliError:
    """The coded error for ``finding``: C012 (driver) or C013 (unreachable)."""
    settings = os.environ.get("DJANGO_SETTINGS_MODULE", db_probe.DEFAULT_SETTINGS)
    where = f"DATABASES[{finding.alias!r}] in {settings}"
    reason = finding.error.rstrip(".")
    skip = f"{ENV}=false skips this check."
    if finding.problem == "driver":
        return CliError(
            f"{where} uses {finding.engine}, but its driver does not load in the project "
            f"interpreter ({python}): {reason}. Django loads the driver as it starts, so "
            "every project command would stop with a traceback.\n"
            f"Install the driver there: {python} -m pip install {_requirement(finding.engine)} "
            "(`pip install -e .` installs all the project's dependencies). Or use Docker: "
            "`karni serve -d` starts the stack, whose image has the driver, and --docker runs "
            f"a project command inside it. {skip}",
            code="C012",
        )
    hints = ""
    if not (project / ".env").is_file() and "DATABASE_URL" not in os.environ:
        hints += "There is no .env: `cp .env.example .env`, then set DATABASE_URL. "
    if finding.host == "db":
        hints += "`db` is the compose service's host name: it resolves only inside docker compose. "
    return CliError(
        f"Cannot connect to {where} ({finding.engine}, {finding.address or 'no address'}): "
        f"{reason}. This command opens the database, so it would stop with a traceback.\n"
        f"{hints}Start the database: `karni serve -d` runs the compose stack with PostgreSQL "
        "(--docker then runs project commands inside it), or start the server DATABASE_URL "
        "names, or point DATABASE_URL at one that runs (sqlite:///db.sqlite3 needs no "
        f"server). {skip}",
        code="C013",
    )


def guard(project: Path, python: Path, use: DatabaseUse) -> None:
    """Raise C012/C013 when the database cannot serve a command that needs it this way."""
    finding = probe(project, python, use)
    if finding is not None:
        raise error(finding, project, python)
