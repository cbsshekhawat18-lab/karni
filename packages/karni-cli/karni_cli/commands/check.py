"""``karni check`` — backend checks plus frontend duplicate detection.

Runs ``manage.py karni_check`` (system checks + ``karni.checks`` hooks,
including the architecture and duplication rules) and, when ``frontend/``
exists, jscpd via the project's own pinned binary driven solely by
``frontend/.jscpd.json``. Both steps always run; the exit code aggregates
both and each step's output is shown.

``--deploy`` passes through to ``karni_check --deploy``: Django's and Karni's
deploy checks run too (``karni.W510`` to ``karni.W520``: DEBUG, SECRET_KEY,
ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, HSTS, secure cookies, the admin path,
CORS, the content security policy, email), each finding printed with its code and
fix, and a warning fails the run. Run it with the production environment.

``--seo`` passes through to ``karni_check --seo``: the modules' SEO checks
run too. karni-site's renders every page of the site through Django's test
client and reports titles, descriptions, images, links and the sitemap
(``SITE010`` to ``SITE018``).

Without ``frontend/node_modules`` (a fresh project before ``npm install``),
the frontend checks cannot run. Outside CI, ``karni check`` then says so,
with the exact command, and runs the backend checks alone: the verdict is
the backend's. In CI, or with ``--frontend``, the missing install fails the
run, so a pipeline that forgot ``npm ci`` never passes unchecked.
``--no-frontend`` skips the frontend checks everywhere.

Outside CI, a clean run may end with one tip on stderr (:mod:`karni_cli.tips`,
at most once per project); ``-q`` suppresses it.

Incremental runs (experimental): the backend's file checks keep their
results in ``.karni/local/check-cache.json`` (:mod:`karni.testing.checkcache`)
and ESLint keeps its own cache in ``.karni/local/eslintcache``, so an
unchanged file is not checked again. ``--no-cache`` turns both off.
``--changed`` checks only the files git reports as changed (the working tree
and the index against ``HEAD``, or against ``REF`` with ``--changed REF``,
plus untracked files): the backend's file checks and ESLint read only those,
while the checks that read the whole project (Django's system checks, the
migrations and routing, jscpd's duplication) still run.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import typer

from karni_cli import local_state, tips, toolchain
from karni_cli import project as project_mod
from karni_cli import suggest as suggest_mod
from karni_cli.environment import is_ci
from karni_cli.project import CliError, require_project

_BARE_IGNORE = re.compile(r"jscpd:ignore-start\s*$")


def frontend_install_message() -> str:
    """What to run when ``frontend/node_modules`` is missing: the folder and the command."""
    return (
        "the frontend checks (eslint and jscpd) need frontend/node_modules, which is "
        "missing. Install it with `(cd frontend && npm install)`, which needs npm "
        f"{toolchain.NPM_FLOOR} or later. On npm 10 (Node 20 and 22) run "
        "`(cd frontend && npx --yes npm@11 install)` instead. `karni doctor` shows the "
        "Node and npm on PATH"
    )


def _frontend_not_installed(project: Path) -> bool:
    frontend = project / "frontend"
    return frontend.is_dir() and not (frontend / "node_modules").is_dir()


def _run(argv: list[str], cwd: Path, capture: list[str] | None) -> int:
    """Run a frontend tool: its output streams through, or is appended to ``capture``."""
    if capture is None:
        return subprocess.run(argv, cwd=cwd, text=True, check=False).returncode
    proc = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    capture.append((proc.stdout or "") + (proc.stderr or ""))
    return proc.returncode


def _say(text: str, capture: list[str] | None) -> None:
    if capture is None:
        typer.echo(text, err=True)
    else:
        capture.append(text)


def _frontend_duplication(project: Path, capture: list[str] | None = None) -> int:
    frontend = project / "frontend"
    if not frontend.is_dir():
        return 0
    jscpd = frontend / "node_modules" / ".bin" / "jscpd"
    if not jscpd.exists():
        _say(
            f"karni check: jscpd not installed. {toolchain.install_hint()}. "
            "Pass --no-frontend to skip the frontend duplication checks.",
            capture,
        )
        return 1
    # Reason-required opt-outs: a bare jscpd:ignore-start (no reason after it)
    # is itself a failure; ignore-end legitimately carries nothing.
    bare = [
        f"{path.relative_to(project)}:{lineno}"
        for path in (frontend / "src").rglob("*.ts*")
        for lineno, line in enumerate(path.read_text().splitlines(), start=1)
        if _BARE_IGNORE.search(line)
    ]
    if bare:
        for location in bare:
            _say(f"[duplicate] {location}: jscpd:ignore-start requires a reason", capture)
        return 1
    return _run([str(jscpd), "--config", ".jscpd.json"], frontend, capture)


#: Experimental. ESLint's cache, next to the backend's check cache (never committed).
ESLINT_CACHE = local_state.LOCAL_DIR / "eslintcache"
_LINTED = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def eslint_args(project: Path, *, cache: bool = True, files: list[str] | None = None) -> list[str]:
    """Experimental. ESLint's arguments: every file, or ``files``, with or without its cache."""
    args = list(files) if files is not None else ["."]
    args += ["--max-warnings", "0"]
    if cache:
        location = project / ESLINT_CACHE
        args += ["--cache", "--cache-strategy", "content", "--cache-location", str(location)]
    return args


def _frontend_lint(
    project: Path,
    capture: list[str] | None = None,
    *,
    cache: bool = True,
    files: list[str] | None = None,
) -> int:
    """``eslint .`` in frontend/ with the project's own binary (the @karni/ui rules live there).

    ``files`` (paths relative to frontend/) lints only those: none, nothing to lint.
    """
    frontend = project / "frontend"
    if not frontend.is_dir() or files == []:
        return 0
    eslint = frontend / "node_modules" / ".bin" / "eslint"
    if not eslint.exists():
        _say(
            f"karni check: eslint not installed. {toolchain.install_hint()}. "
            "Pass --no-frontend to skip the frontend checks.",
            capture,
        )
        return 1
    if cache:
        local_state.ensure_dir(project)
    return _run([str(eslint), *eslint_args(project, cache=cache, files=files)], frontend, capture)


def _git(project: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=project, text=True, capture_output=True, check=False
        )
    except FileNotFoundError:
        raise CliError(
            "karni check --changed asks git which files changed, and git is not installed. "
            "Install git, or run karni check without --changed.",
            code="C581",
        ) from None


def changed_files(project: Path, ref: str | None = None) -> list[str]:
    """Experimental. The project's files git reports as changed, relative to the project.

    Against ``ref`` when given, else the working tree and the index against
    ``HEAD`` (the index alone in a repository without a commit), plus the
    untracked files git does not ignore. Deleted files are left out.

    :raises CliError: ``C581`` outside a git repository, or for a ref git does not know.
    """
    inside = _git(project, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise CliError(
            f"karni check --changed asks git which files changed, and {project} is not in a git "
            "repository. Run git init (and commit), or run karni check without --changed.",
            code="C581",
        )
    base = ref or "HEAD"
    if ref is None and _git(project, ["rev-parse", "--verify", "-q", "HEAD"]).returncode != 0:
        diffs = [["diff", "--name-only", "--relative", "--cached"]]
    else:
        diffs = [["diff", "--name-only", "--relative", base, "--"]]
    found: list[str] = []
    for args in [*diffs, ["ls-files", "--others", "--exclude-standard"]]:
        proc = _git(project, args)
        if proc.returncode != 0:
            raise CliError(
                f"git could not list the files changed against {base}: "
                f"{(proc.stderr or proc.stdout).strip()}. Pass a ref git knows "
                "(a branch, a tag, a commit), or run karni check --changed alone.",
                code="C581",
            )
        found += [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return sorted({name for name in found if (project / name).is_file()})


def _run_backend(project: Path, args: list[str], *, docker: bool | None, service: str) -> int:
    """``manage.py karni_check ARGS``, streamed. ``C582`` when its karni predates ARGS' options."""
    if "--no-cache" not in args and "--changed" not in args:
        return project_mod.run_manage(
            project, args, docker=docker, service=service, capture=False
        ).returncode
    proc = project_mod.run_manage(project, args, docker=docker, service=service)
    if proc.returncode != 0 and "unrecognized arguments" in (proc.stderr or ""):
        raise CliError(
            "The project's karni has no check cache (--changed, --no-cache): it predates them. "
            "Upgrade karni in the project (pip install -U karni), or run karni check without "
            "those flags.",
            code="C582",
        )
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")
    return proc.returncode


def _suggestions_block(project: Path, file: Path, *, docker: bool | None, service: str) -> str:
    """The suggestions block for the end of a run (``""`` for none): never raises.

    The project's own suggestions come from ``file``, which ``manage.py karni_check`` wrote.
    Without it (docker, or a karni that predates suggestions) the backend printed its own.
    """
    core = None
    facts = None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        core = (bool(data["enabled"]), list(data["suggestions"]))
        found = data.get("facts")  # the project's facts, so karni_facts is not started again
        facts = found if isinstance(found, dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        core = None
    finally:
        file.unlink(missing_ok=True)
    try:
        return suggest_mod.render(
            suggest_mod.collect(project, core, docker=docker, service=service, facts=facts)
        )
    except Exception:  # noqa: BLE001 - a suggestion must never break karni check
        return ""


def run_checks(
    project: Path, *, docker: bool | None = None, service: str = "django"
) -> tuple[bool, str]:
    """``karni check``'s backend and frontend checks, captured: ``(passed, output)``.

    ``karni build`` runs it as its last step.
    """
    out: list[str] = []
    try:
        proc = project_mod.run_manage(project, ["karni_check"], docker=docker, service=service)
        out.append((proc.stdout or "") + (proc.stderr or ""))
        backend = proc.returncode
    except CliError as exc:
        out.append(f"error: {exc}")
        backend = 1
    dup = lint = 0
    if _frontend_not_installed(project):
        # The same rule as `karni check`: a note outside CI, a failure in CI.
        if is_ci():
            out.append(
                f"karni check: {frontend_install_message()}. Pass --no-frontend to skip them."
            )
            dup = 1
        else:
            out.append(
                f"karni check: skipped: {frontend_install_message()}. They run once it is "
                "installed, and a missing install fails in CI and with --frontend."
            )
    else:
        dup = _frontend_duplication(project, out)
        lint = _frontend_lint(project, out)
    return not (backend or dup or lint), "\n".join(part.rstrip() for part in out if part.strip())


def check(
    ref: str | None = typer.Argument(
        None,
        metavar="[REF]",
        help="With --changed: the git ref to compare with (a branch, a tag, a commit) instead "
        "of HEAD.",
        show_default=False,
    ),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    frontend: bool | None = typer.Option(
        None,
        "--frontend/--no-frontend",
        help="Run the frontend checks (eslint and jscpd in frontend/). By default they run "
        "when frontend/node_modules is installed, and are skipped with a note when it is not, "
        "except in CI. --frontend fails without it, --no-frontend skips them.",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Do not print the optional tip."),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Print the frontend tools' own output (ESLint, jscpd's report) when they pass too. "
        "By default a pass is one line and only a failure prints their output.",
    ),
    deploy: bool = typer.Option(
        False,
        "--deploy",
        help="Also run the deploy checks (DEBUG, SECRET_KEY, hosts, HSTS, cookies, admin path, "
        "CORS, CSP) and fail on warnings. Run it with the production environment.",
    ),
    seo: bool = typer.Option(
        False,
        "--seo",
        help="Also run the SEO checks: every page of the public site rendered, and missing or "
        "shared titles and descriptions, images without alt, size or smaller copies, broken "
        "links and pages missing from the sitemap reported (karni-site, SITE010 to SITE018).",
    ),
    changed: bool = typer.Option(
        False,
        "--changed",
        help="Only the files git reports as changed: the working tree and the index against "
        "HEAD (or REF), and untracked files. The checks that read the whole project still run. "
        "Experimental.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Check every file again: do not read or write the check cache "
        "(.karni/local/check-cache.json) or ESLint's. Experimental.",
    ),
) -> None:
    """Run architecture and system checks.

    An unchanged file is not checked again: the results of the file checks are
    cached in .karni/local/ (--no-cache turns that off).

    Example: karni check --changed main
    """
    if ref is not None and not changed:
        raise typer.BadParameter("REF is only used with --changed.", param_hint="REF")
    project = require_project()
    args = ["karni_check", *(["--deploy"] if deploy else []), *(["--seo"] if seo else [])]
    if no_cache:
        args.append("--no-cache")
    files: list[str] | None = None
    if changed:
        try:
            files = changed_files(project, ref)
        except CliError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        args += ["--changed", *files]
        typer.echo(f"karni check --changed: {len(files)} changed file(s)", err=True)
    suggestions_file = project / suggest_mod.SUGGESTIONS_FILE
    suggesting = not suggest_mod.turned_off(project)
    if suggesting:
        local_state.ensure_dir(project)
        suggestions_file.unlink(missing_ok=True)
        # An environment variable, not an option: a karni that predates suggestions ignores it.
        os.environ["KARNI_SUGGESTIONS_FILE"] = str(suggest_mod.SUGGESTIONS_FILE)
    try:
        backend = _run_backend(project, args, docker=docker, service=service)
    except CliError as exc:
        # The backend cannot start here (no interpreter, no database driver):
        # say why, and still run the frontend checks.
        typer.echo(f"error: {exc}", err=True)
        backend = 1
    run_frontend = frontend is not False
    dup = lint = 0
    if run_frontend and _frontend_not_installed(project):
        run_frontend = False
        if frontend or is_ci():
            typer.echo(
                f"karni check: {frontend_install_message()}. Pass --no-frontend to skip them.",
                err=True,
            )
            dup = 1
        else:
            typer.echo(
                f"karni check: skipped: {frontend_install_message()}. They run once it is "
                "installed, and a missing install fails in CI and with --frontend.",
                err=True,
            )
    if run_frontend:
        # a pass is one line: jscpd's report table and the tools' banners only on a failure
        captured: list[str] | None = None if verbose else []
        dup = _frontend_duplication(project, capture=captured)
        lint_files = (
            [
                name.removeprefix("frontend/")
                for name in files
                if name.startswith("frontend/") and name.endswith(_LINTED)
            ]
            if files is not None
            else None
        )
        lint = _frontend_lint(project, capture=captured, cache=not no_cache, files=lint_files)
        if captured is not None:
            if dup or lint:
                for part in captured:
                    if part.strip():
                        typer.echo(part.rstrip())
            else:
                typer.echo("frontend checks: ok (ESLint and jscpd, --verbose prints their output)")
    os.environ.pop("KARNI_SUGGESTIONS_FILE", None)
    block = (
        _suggestions_block(project, suggestions_file, docker=docker, service=service)
        if suggesting
        else ""
    )
    if backend or dup or lint:
        sys.stderr.write("karni check: FAILED\n")
        if block:
            typer.echo(block)
    else:
        typer.echo("karni check: ok")
        if block:
            typer.echo(block)
        # Only after a clean run (failures deserve the attention), never in CI,
        # and on stderr so stdout stays exactly the checks' output.
        tip = tips.history_tip(project, quiet=quiet)
        if tip:
            sys.stderr.write(f"\n{tip}\n")
    raise typer.Exit(1 if (backend or dup or lint) else 0)
