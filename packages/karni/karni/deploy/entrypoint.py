"""``python -m karni.deploy.entrypoint <command> [args]``: the deploy gate in front of a command.

The production image (the scaffold's Dockerfile, target ``prod``) uses this as
its ``ENTRYPOINT``, so every container started from it, the web server, the
Celery worker and beat, and the one-shot release step, first runs::

    python manage.py karni_check --deploy

which is Django's ``check --deploy`` plus Karni's deploy checks (``karni.W510``
to ``karni.W520``: DEBUG, SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS,
HSTS, secure cookies, the admin path, CORS, the content security policy, email)
and the project's ``karni.checks`` hooks. When they pass, the process is replaced
by ``<command>`` (``os.execvp``, so signals reach it directly). When they fail,
the command never starts and the container exits with status 1, after the
findings and one ``E520`` line saying what to do.

Escape hatch: ``KARNI_SKIP_DEPLOY_CHECK=1`` (or ``true``, ``yes``, ``on``)
skips the checks for an emergency start. It is logged loudly on every start,
so it is not forgotten. ``KARNI_DEPLOY_CHECK_COMMAND`` replaces the check
command (a shell-style string, e.g. ``python manage.py check --deploy``), and
a Dockerfile or compose file can set another ``entrypoint`` altogether.

With no command, the gate runs alone and its result is the exit status.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import NoReturn, TextIO

__all__ = [
    "CHECK_COMMAND_VARIABLE",
    "SKIP_VARIABLE",
    "check_command",
    "gate",
    "main",
    "skip_requested",
]

#: The error code a refusal (and a skipped check) carries: ``karni explain E520``.
CODE = "E520"
SKIP_VARIABLE = "KARNI_SKIP_DEPLOY_CHECK"
CHECK_COMMAND_VARIABLE = "KARNI_DEPLOY_CHECK_COMMAND"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_PREFIX = "karni deploy gate:"

Runner = Callable[[Sequence[str]], int]


def skip_requested(environ: Mapping[str, str]) -> bool:
    """Whether ``KARNI_SKIP_DEPLOY_CHECK`` asks to start without the checks."""
    return environ.get(SKIP_VARIABLE, "").strip().lower() in _TRUTHY


def check_command(environ: Mapping[str, str]) -> list[str]:
    """``KARNI_DEPLOY_CHECK_COMMAND`` split like a shell would, else ``karni_check --deploy``."""
    configured = environ.get(CHECK_COMMAND_VARIABLE, "").strip()
    if configured:
        return shlex.split(configured)
    return [sys.executable, "manage.py", "karni_check", "--deploy"]


def _run(command: Sequence[str]) -> int:
    try:
        return subprocess.run(list(command), check=False).returncode
    except OSError as exc:
        sys.stderr.write(f"{_PREFIX} could not run {shlex.join(command)}: {exc}\n")
        return 127


def gate(
    environ: Mapping[str, str],
    command: Sequence[str] = (),
    *,
    run: Runner = _run,
    stderr: TextIO | None = None,
) -> int:
    """Run the deploy checks unless skipped: 0 lets ``command`` start, anything else refuses."""
    out = stderr if stderr is not None else sys.stderr
    what = f"`{shlex.join(command)}`" if command else "the container"
    if skip_requested(environ):
        for line in (
            f"{SKIP_VARIABLE} is set: the deploy checks did NOT run ({CODE}).",
            f"{what} starts with a configuration nobody checked. DEBUG, SECRET_KEY,",
            "the hosts, HSTS, the cookies, the admin path, CORS and the content security",
            "policy may all be unsafe.",
            f"Remove {SKIP_VARIABLE} as soon as the emergency is over, then run",
            "`karni check --deploy` with the production environment.",
        ):
            out.write(f"WARNING {_PREFIX} {line}\n")
        out.flush()
        return 0
    checks = check_command(environ)
    out.write(f"{_PREFIX} running {shlex.join(checks)}\n")
    out.flush()
    status = run(checks)
    if status == 0:
        return 0
    out.write(
        f"{_PREFIX} the deploy checks failed ({CODE}), so {what} does not start. Each problem "
        "is listed above with its code and fix: set the production values in the environment "
        f"(.env.prod) and start again. {SKIP_VARIABLE}=1 starts without the checks in an "
        "emergency, and is logged on every start.\n"
    )
    out.flush()
    return status if status > 0 else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    run: Runner = _run,
    execvp: Callable[[str, list[str]], NoReturn] = os.execvp,
) -> int:
    """Gate, then replace this process with ``argv`` (or return the gate's status)."""
    command = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    status = gate(env, command, run=run)
    if status != 0 or not command:
        return status
    sys.stderr.write(f"{_PREFIX} starting {shlex.join(command)}\n")
    sys.stderr.flush()
    sys.stdout.flush()
    execvp(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
