"""``karni new <name>``: scaffold a project of a kind from templates/project.

The kind (:mod:`karni_cli.kinds`) is what the project is: ``site`` (a public
website the client edits in the admin), ``app`` (an API and a React app) or
``site+app``. ``--kind`` names it, an interactive run asks, and a run nobody
can answer makes an app (a site with ``--design``). It is recorded as
``kind`` under ``[tool.karni]`` in pyproject.toml. A kind with a site gets
the site app (``karni make site``'s code, karni-site wired), and the
template's settings for a site: registration off, the roles staff and
editor. ``--no-staff-app`` leaves ``frontend/`` out of a site.

``--design <dir>`` builds the site from a designer's pages, as an agent
would by hand: ``karni design analyze --map content/design-map.json`` (the
content that repeats, as proposed models and a draft content map), then
``karni import design --editable --map`` (the site app, everything the
client sees editable except what becomes rows, the staff app and the admin
themed from the design's CSS). It prints the rest of the site-from-design
procedure as the next steps.

``--recipe <name>`` (experimental) starts the app from a recipe
(:mod:`karni_cli.recipes`): the project as above, the recipe's karni.yaml
with this project's name, the recipe named in ``.karni/build.json``, then
``karni build``, which writes the recipe's own files (its domain code, seeds
and tests) over its stubs and runs the migrations, the seed, the tests and
``karni check``. Without an interpreter that has Django and karni for the
project, or without its database, it stops after karni.yaml and says to run
``karni build``.

The template carries no agent guidance files: AGENTS.md is generated
afterwards by the same code as ``karni rules sync``, and it states the kind
and its stack. No tool-specific agent file is written (they are deprecated
since 0.5.0). The production stack
(docker-compose.prod.yml, the Caddyfile, .env.prod.example) is written the
same way, by ``karni make deploy compose``'s code.

@karni/ui is resolved like the template: ``KARNI_UI_SRC`` > the monorepo
checkout's ``packages/karni-ui`` > the npm release. A local source becomes
``"@karni/ui": "file:<abs path>"`` in frontend/package.json (installed as a
packed copy via the scaffold's ``.npmrc``), and its ``dist/`` is built here
when missing — package.json ``exports`` point into dist/. The build writes only
git-ignored paths (``npm ci`` never rewrites package-lock.json), so scaffolding
from a checkout leaves its working tree clean. A project without a staff app
needs none of it.

Last, the project becomes a git repository with one commit of everything
``karni new`` wrote (:func:`init_repository`), so the procedures' "commit
content/" and ``karni upgrade``'s clean-tree rule work from the start.
``--no-git`` skips it, and a project made inside an existing repository is
left to that repository, as before.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
import typer

from karni_cli import agent_data, kinds, scaffold, toolchain
from karni_cli.adapters import MODULES_DIR, sync
from karni_cli.brand import print_mark
from karni_cli.generators import deploy
from karni_cli.generators.naming import require_snake
from karni_cli.project import CliError
from karni_cli.scaffold import resolve_template, validate_name

if TYPE_CHECKING:
    from karni_cli.recipes import Recipe

#: The site app a kind with a site gets (``--site-app`` names another).
SITE_APP = "website"
#: Where ``--design`` writes the draft content map, relative to the project.
CONTENT_MAP = Path("content") / "design-map.json"
PROCEDURE = "site-from-design"
#: The step that makes the admin's first account. A site has no sign-up: nobody else can.
ADMIN_ACCOUNT = "  karni createsuperuser  # the first admin account"
SITE_ADMIN_ACCOUNT = (
    f"{ADMIN_ACCOUNT}: nobody signs up on the site, so nobody can sign in before it. The "
    "client's own account is a user the admin gives the staff role (or editor, for the "
    "content only)"
)
#: The procedure's steps ``karni new --design`` runs itself (1-based).
DONE_STEPS = (2, 3)


#: The message of the commit ``karni new`` makes.
FIRST_COMMIT = "Create the project with karni new"


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True, text=True, check=False
    )


def init_repository(project: Path) -> str:
    """Make ``project`` a git repository with a first commit, and say what happened.

    Nothing is done inside an existing repository (the project is part of
    it), or without git on PATH. When the commit cannot be made (no
    ``user.name`` or ``user.email``, a hook refusing it), the repository
    stays, with the files unstaged, and the message says how to finish.
    """
    if shutil.which("git") is None:
        return (
            "git is not installed, so the project is not a git repository. Install git, then "
            f"run `git init && git add -A && git commit -m {FIRST_COMMIT!r}` in it."
        )
    outer = _git(project, "rev-parse", "--show-toplevel")
    if outer.returncode == 0:
        return (
            f"The project is inside the git repository at {outer.stdout.strip()}: no new "
            "repository. Commit it there."
        )
    init = _git(project, "init", "-q")
    if init.returncode != 0:
        return f"git init failed in {project}: {init.stderr.strip()}"
    _git(project, "add", "-A")
    commit = _git(project, "commit", "-q", "-m", FIRST_COMMIT)
    if commit.returncode != 0:
        _git(project, "reset", "-q")
        reason = (commit.stderr or commit.stdout).strip().splitlines()
        return (
            f"Made {project} a git repository, but the first commit failed ("
            f"{reason[-1] if reason else 'no reason given'}). Set your name and email "
            "(`git config --global user.name ...` and `user.email ...`), then run "
            f"`git add -A && git commit -m {FIRST_COMMIT!r}` there."
        )
    sha = _git(project, "rev-parse", "--short", "HEAD").stdout.strip()
    return (
        f"Made {project} a git repository with a first commit ({sha}) of everything karni new "
        "wrote. --no-git skips it."
    )


def write_agent_adapters(project: Path) -> int:
    """Generate AGENTS.md into a freshly rendered project. Returns the count of files."""
    result = sync(project, agent_data.load(project))
    return len(result.written) + len(result.unchanged)


def record_site_guidance(project: Path) -> None:
    """karni-site's agent guidance, recorded quietly when this interpreter can read it.

    ``karni add site`` records it through the project's interpreter, which a
    project ``karni new`` just made does not have yet. The next steps say to
    run ``karni add site`` once it is installed when this finds nothing.
    """
    from karni_cli.commands.add import _read_agents_fragment, record_module_fragment

    fragment = _read_agents_fragment(project, "karni_site")
    if fragment is not None:
        record_module_fragment(project, "site", fragment)


def prepare_ui_source(source: Path) -> None:
    """Make sure a local @karni/ui has the dist/ a ``file:`` install ships."""
    install = " ".join(scaffold.ui_install_command(source)[:2])
    rebuild = f"(cd {source} && {install} && npm run build)"
    if not scaffold.ui_dist_missing(source):
        if scaffold.ui_dist_stale(source):
            typer.echo(
                f"warning: {source}/dist is older than its sources. Rebuild it with "
                f"{rebuild} before `npm install` in frontend/.",
                err=True,
            )
        return
    steps = " && ".join(" ".join(argv) for argv in scaffold.ui_build_commands(source))
    typer.echo(
        f"Building @karni/ui in {source} (dist/ is missing and file: installs ship dist/): "
        f"{steps}. This writes node_modules/ and dist/ there, both git-ignored. Files git "
        "tracks, package-lock.json included, are left as they are."
    )
    failure = scaffold.build_ui_dist(source)
    if failure is not None:
        typer.echo(
            f"warning: could not build @karni/ui: {failure}\n"
            f"Build it yourself before `npm install` in frontend/: {rebuild}",
            err=True,
        )


def _baseline_release() -> str:
    """The newest release this karni-cli's changelog knows: what the scaffold is written for."""
    from karni_cli.upgrades import changelog

    try:
        return changelog.newest_release(changelog.load())
    except Exception:  # noqa: BLE001 - a missing changelog never blocks `karni new`
        from karni_cli import __version__

        return __version__


def interactive() -> bool:
    """Whether someone can answer a question here (both ends are a terminal)."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask_kind(design: bool) -> str:
    choices = ["site", "site+app"] if design else list(kinds.KINDS)
    default = "site" if design else kinds.DEFAULT
    typer.echo("What kind of project is it?")
    for kind in choices:
        typer.echo(f"  {kind:<9} {kinds.summary(kind)}")
    return str(typer.prompt("Kind", default=default, type=click.Choice(choices)))


def choose_kind(kind: str | None, design: Path | None, *, ask: bool) -> str:
    """``--kind``, else the answer to the question, else app (site with ``--design``)."""
    if kind is None:
        if ask:
            return _ask_kind(design is not None)
        return "site" if design is not None else kinds.DEFAULT
    if kind not in kinds.KINDS:
        raise CliError(
            f"--kind {kind!r} is not a kind. Use one of {', '.join(kinds.KINDS)}: site for a "
            "public website, app for an API and a React app, site+app for both.",
            code="C106",
        )
    if design is not None and not kinds.has_site(kind):
        raise CliError(
            f"--design builds a public website from a designer's pages, and kind {kind!r} has "
            "none. Pass --kind site or --kind site+app (or leave --kind out: --design makes a "
            "site).",
            code="C106",
        )
    return kind


def choose_staff_app(kind: str, staff_app: bool | None, *, ask: bool) -> bool:
    """Whether ``frontend/`` is made: always for an app, a choice for a site (default yes)."""
    if kind != "site":
        if staff_app is False:
            raise CliError(
                f"--no-staff-app leaves frontend/ out, and kind {kind!r} is an app whose screens "
                "live there. Use --kind site for a website without one.",
                code="C106",
            )
        return True
    if staff_app is not None:
        return staff_app
    if ask:
        return bool(
            typer.confirm(
                "Add the staff app too (frontend/: a React app where staff work with what the "
                "site's forms collect)? Without it, staff work in the admin",
                default=True,
            )
        )
    return True


def _design_folder(design: Path) -> Path:
    if not design.is_dir():
        raise CliError(
            f"{design} is not a directory. Pass the folder that holds the design's HTML pages "
            "(index.html, about.html, ...).",
            code="C111",
        )
    if not any(path.suffix.lower() in (".html", ".htm") for path in design.rglob("*")):
        raise CliError(f"{design} has no .html page.", code="C111")
    return design.resolve()


def _relative(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def _make_site(project: Path, site_app: str) -> None:
    """The site app, as ``karni make site <site_app>`` writes it."""
    from karni_cli.generators import site as site_gen
    from karni_cli.generators.core import Workspace

    ws = Workspace(project)
    site_gen.plan(ws, site_app, next_step=False)
    ws.commit(dry_run=False)
    record_site_guidance(project)


def _site_from_design(project: Path, design: Path, site_app: str) -> None:
    """Steps 2 and 3 of the site-from-design procedure, on the new project."""
    from karni_cli.commands import import_design
    from karni_cli.commands.design import analyze_design
    from karni_cli.generators.core import Workspace

    label = _relative(design, project)
    typer.echo("")
    typer.echo(f"$ karni design analyze {label} --app {site_app} --map {CONTENT_MAP.as_posix()}")
    analysis = analyze_design(design, site_app, map_file=project / CONTENT_MAP, label=label)
    typer.echo("")
    typer.echo(
        f"$ karni import design {label} --app {site_app} --editable --map {CONTENT_MAP.as_posix()}"
    )
    import_design.run(
        Workspace(project),
        design,
        site_app,
        editable=True,
        content_map=project / CONTENT_MAP,
        guidance=False,
    )
    record_site_guidance(project)
    typer.echo("")
    typer.echo(analysis.render())
    typer.echo("")
    typer.echo(f"wrote the draft map {CONTENT_MAP.as_posix()}.")


def _setup_lines(slug: str, project: Path, staff_app: bool, site: bool) -> list[str]:
    without_docker = (
        '  # Without Docker: README.md, "Using a local Karni checkout" (a virtualenv with '
        "`pip install -e . pytest pytest-django`, and `karni doctor` for the database)"
    )
    lines = [f"  cd {slug}", "  cp .env.example .env", "  docker compose up -d", without_docker]
    if staff_app:
        lines.append(
            "  (cd frontend && npm install)  # editor, lint, type-check and `karni check` on "
            "the host"
        )
        lines.append(
            f"  # npm install needs npm {toolchain.NPM_FLOOR} or later. "
            "On npm 10 (Node 20 and 22), run `npx npm@11 install` there instead"
        )
    if site and not (project / MODULES_DIR / "site.md").is_file():
        lines.append(
            "  karni add site  # once karni-site is installed: records its agent guidance in "
            "AGENTS.md"
        )
    return lines


def _new_app_lines() -> list[str]:
    """The last lines of ``karni new``: build the app with an agent, /new-app."""
    return [
        "Then build the app with your agent: describe it in one line, and give the line to",
        "  /new-app <the app in one line>",
        (
            "  (in a tool without slash commands, the prompt: Run `karni rules --procedure "
            "new-app` and follow every step for: <the app in one line>)"
        ),
    ]


def _procedure_lines(project: Path, design: Path, site_app: str) -> list[str]:
    """The site-from-design steps after the ones ``karni new`` ran, with this project's names."""
    found = agent_data.load(project).procedure(PROCEDURE)
    if found is None:  # an older karni in the project: point at the command instead
        return [f"  karni rules --procedure {PROCEDURE}"]
    design_label = _relative(design, project)
    lines = []
    for number, step in enumerate(found["steps"], start=1):
        if number == 1 or number in DONE_STEPS:
            continue
        text = str(step).replace("<design folder>", design_label).replace("<site app>", site_app)
        lines.append(f"  {number}. {text}")
    return lines


def choose_recipe(
    recipe: str | None, *, kind: str | None, design: Path | None, staff_app: bool | None
) -> tuple[Recipe | None, str | None]:
    """The recipe ``--recipe`` names and the kind it gives, checked before anything is written.

    ``(None, None)`` without ``--recipe``, and ``(None, kind)`` for the blank
    start, which goes with any kind and option.

    :raises CliError: ``C420`` (with the closest names) or ``C421`` for a
        recipe that is not there or cannot be used, ``C440`` for an option a
        recipe cannot go with.
    """
    if recipe is None:
        return None, None
    from karni_cli import recipes
    from karni_cli.spec.source import load

    if recipe == recipes.BLANK:
        return None, kind
    clash = (
        "--design builds a public site from a designer's pages"
        if design is not None
        else "--kind site has no React app for the recipe's pages"
        if kind == "site"
        else "--no-staff-app leaves out the React app the recipe's pages live in"
        if staff_app is False
        else None
    )
    if clash is not None:
        raise CliError(
            f"--recipe {recipe} makes an app from the recipe's karni.yaml, and {clash}. Leave "
            "that option out (--kind app or site+app go with a recipe).",
            code="C440",
        )
    found = recipes.load().require(recipe)
    if found is None:  # pragma: no cover - require returns None only for the blank start
        return None, kind
    data = load(found.spec()).data
    app = data.get("app") if isinstance(data, dict) else None
    given = app.get("kind") if isinstance(app, dict) else None
    return found, kind or (str(given) if given else kinds.DEFAULT)


def write_recipe_spec(project: Path, name: str, kind: str, recipe: Recipe | None) -> Path:
    """karni.yaml from ``recipe`` (the blank start when ``None``) with this project's name and kind.

    A recipe is also named in ``.karni/build.json``, so the first ``karni
    build`` writes its own files (:mod:`karni_cli.recipes.apply`).
    """
    from karni_cli import recipes
    from karni_cli.builder import layout, record
    from karni_cli.spec import edit

    path = project / recipes.SPEC_FILE
    if recipe is None:
        path.write_text(recipes.blank_spec(name), encoding="utf-8")
        return path
    text = edit.set_values(
        recipe.spec(),
        [(("app", "name"), name), (("app", "kind"), kind), (("app", "recipe"), recipe.name)],
    )
    path.write_text(text, encoding="utf-8")
    pending = project / layout.RECORD
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(record.Record(recipe=recipe.name).text(), encoding="utf-8")
    return path


def build_blocker(project: Path) -> str | None:
    """Why ``karni build`` cannot run in the new project now (``None``: it can).

    It needs an interpreter with Django and karni for the project (its
    ``.venv``, the active virtualenv, or the one running karni-cli) and a
    database it can open (the probe of :mod:`karni_cli.database`).
    """
    from karni_cli import database
    from karni_cli import project as project_mod

    python = project_mod.venv_python(project)
    if python is None:
        return (
            "no interpreter here has Django and karni for the project (no .venv in it, no "
            "active virtualenv)"
        )
    if not database.enabled():
        return None
    finding = database.probe(project, python, "connect")
    if finding is None:
        return None
    if finding.problem == "driver":
        return f"the database driver for {finding.engine} does not load ({finding.error})"
    where = f" ({finding.address})" if finding.address else ""
    return f"the database{where} cannot be reached ({finding.error})"


def _recipe_line(recipe: Recipe | None, spec: Path) -> str:
    if recipe is None:
        return f"Blank start: wrote {spec.name} with the version and the app's name, nothing else."
    from karni_cli.builder import layout

    return (
        f"Recipe {recipe.name} ({recipe.title}): wrote {spec.name} (app.recipe: {recipe.name}) "
        f"and named the recipe in {layout.RECORD}. The first karni build writes its own files "
        f"over its stubs: {', '.join(recipe.files) or 'none'}."
    )


def _run_build(project: Path) -> None:
    """``karni build`` in the new project, as if run there. Raises ``typer.Exit(1)`` when it stops."""
    from karni_cli.commands.build import build as build_command

    typer.echo("")
    typer.echo("$ karni build")
    with contextlib.chdir(project):
        build_command(
            spec=None,
            dry_run=False,
            allow_destructive=False,
            force=False,
            adopt=None,
            as_json=False,
            docker=None,
            service="django",
        )


def _recipe_next(picked: Recipe | None, blocker: str | None, setup: list[str]) -> None:
    typer.echo("Next steps:")
    for line in setup:
        typer.echo(line)
    if picked is None:
        typer.echo(
            "  # write in karni.yaml what the app needs, then karni plan --questions and karni build"
        )
    elif blocker is not None:
        typer.echo(
            "  karni build  # karni.yaml and the recipe's own files, the migrations, demo data, "
            "the tests and karni check"
        )
        typer.echo(f"karni build did not run here: {blocker}.")
        typer.echo("next: karni build")
    else:
        changed = "; ".join(picked.usually_changed) or "what the app needs"
        typer.echo(
            f"  # change karni.yaml ({changed}), then karni build. karni recipes show "
            f"{picked.name} says what each one is."
        )


def new(
    name: str = typer.Argument(..., help="Project name (slug is derived from it)"),
    output_dir: Path = typer.Option(Path("."), "--output-dir", "-o"),
    domain: str = typer.Option("example.com", "--domain", help="Production domain for Caddy"),
    kind: str | None = typer.Option(
        None,
        "--kind",
        metavar="[site|app|site+app]",
        help=(
            "What the project is: site (a public website the client edits in the admin), app "
            "(an API and a React app for signed-in users) or site+app. Asked when run in a "
            "terminal, else app (site with --design)."
        ),
        show_default=False,
    ),
    design: Path | None = typer.Option(
        None,
        "--design",
        help=(
            "A designer's folder of static pages (index.html, css/, img/): the site is built "
            "from it (karni design analyze, karni import design --editable), and the next steps "
            "are the rest of the site-from-design procedure. Implies a kind with a site."
        ),
    ),
    staff_app: bool | None = typer.Option(
        None,
        "--staff-app/--no-staff-app",
        help=(
            "The React staff app in frontend/. An app always has it. A site has it unless "
            "--no-staff-app, and then staff work in the admin."
        ),
        show_default=False,
    ),
    site_app: str = typer.Option(
        SITE_APP, "--site-app", help="The label of the site app a kind with a site gets."
    ),
    git: bool = typer.Option(
        True,
        "--git/--no-git",
        help="Make the project a git repository with a first commit of what karni new wrote. "
        "Skipped inside an existing repository and when git is not installed.",
    ),
    recipe: str | None = typer.Option(
        None,
        "--recipe",
        help=(
            "Experimental. Start the app from a recipe (karni recipes list, or blank): its "
            "karni.yaml with this name, then karni build, which also writes the recipe's own "
            "domain code, seeds and tests and runs the tests and karni check. Without the "
            "project's interpreter or database it stops after karni.yaml: run karni build next."
        ),
        show_default=False,
    ),
) -> None:
    """Create a project: a public website, an app, or both.

    Every kind has the API, the admin, PostgreSQL, Redis, Celery, the
    security defaults and the production stack. A site (--kind site) also has
    a site app at / on the karni-site module, where the client edits every
    text, image, menu and page title in the admin, registration off and the
    roles staff and editor. An app (--kind app) has the React app in
    frontend/. A site+app has both.

    With --design, the site is built from a designer's pages, and the next
    steps say what is left: the models, the real content and the loops
    (karni rules --procedure site-from-design).

    With --recipe (experimental), the app starts from a recipe's karni.yaml,
    and karni build makes it: the models and the API, the recipe's own
    domain code, seeds and tests, the migrations, demo data, the tests and
    karni check.

    Example: karni new "Crumb Bakery" --kind site --design ../design

    Example: karni new "Corner Shop" --recipe shop
    """
    from cookiecutter.main import cookiecutter  # lazy: heavy import

    slug = validate_name(name)
    require_snake(site_app, "Site app name")
    picked, recipe_kind = choose_recipe(recipe, kind=kind, design=design, staff_app=staff_app)
    source = _design_folder(design) if design is not None else None
    ask = interactive()
    chosen = choose_kind(recipe_kind or kind, source, ask=ask)
    with_staff_app = choose_staff_app(chosen, staff_app, ask=ask)
    site = kinds.has_site(chosen)
    print_mark()
    template = resolve_template()
    ui_source = scaffold.resolve_ui_source() if with_staff_app else None
    if ui_source is not None:
        prepare_ui_source(ui_source)
    project = output_dir / slug
    cookiecutter(
        str(template),
        no_input=True,
        extra_context={
            "project_name": name,
            "domain": domain,
            "karni_ui": (ui_spec := scaffold.ui_spec(ui_source, project)),
            "karni_ui_mount": scaffold.ui_mount_target(ui_spec),
            "karni_baseline": _baseline_release(),
            "kind": chosen,
            "staff_app": "yes" if with_staff_app else "no",
        },
        output_dir=str(output_dir),
    )
    if not with_staff_app:
        shutil.rmtree(project / "frontend")
    if source is not None:
        _site_from_design(project, source, site_app)
    elif site:
        _make_site(project, site_app)
    # The production stack: the same files `karni make deploy compose` writes.
    deploy.write_new_project(project, domain=domain, staff_app=with_staff_app)
    write_agent_adapters(project)
    typer.echo("")
    typer.echo(
        f"Created {project}: kind {chosen} (recorded under [tool.karni] in pyproject.toml), "
        f"the agent instructions in AGENTS.md, and the production stack in "
        f"{deploy.COMPOSE_FILE} (docs/deploy.md)."
    )
    if git:
        typer.echo(init_repository(project))
    if not with_staff_app:
        typer.echo("No staff app (frontend/): staff work in the admin.")
    elif ui_source is not None:
        typer.echo(f"@karni/ui: {ui_spec} (local checkout)")
    else:
        typer.echo(
            f"@karni/ui: {scaffold.UI_REGISTRY_SPEC} from npm "
            "(KARNI_UI_SRC=/path/to/Karni/packages/karni-ui uses a checkout instead)"
        )
    if recipe is not None:
        typer.echo(_recipe_line(picked, write_recipe_spec(project, name, chosen, picked)))
        blocker = build_blocker(project) if picked is not None else None
        if picked is not None and blocker is None:
            try:
                _run_build(project)
            except typer.Exit:
                typer.echo(f"The project is in {project}: run karni build there again.")
                raise
        _recipe_next(picked, blocker, _setup_lines(slug, project, with_staff_app, site))
        return
    typer.echo("Next steps:")
    for line in _setup_lines(slug, project, with_staff_app, site):
        typer.echo(line)
    if source is not None:
        typer.echo("  karni migrate && karni test  # the page test covers every page")
        typer.echo(SITE_ADMIN_ACCOUNT if chosen == "site" else ADMIN_ACCOUNT)
        typer.echo(
            f"Then the rest of the {PROCEDURE} procedure (`karni rules --procedure {PROCEDURE}` "
            "prints all of it). karni new ran steps 2 and 3, the analysis and the import, so "
            "it goes on at step 4:"
        )
        for line in _procedure_lines(project, source, site_app):
            typer.echo(line)
        return
    if site:
        typer.echo("  karni migrate")
        typer.echo(SITE_ADMIN_ACCOUNT if chosen == "site" else ADMIN_ACCOUNT)
        typer.echo(
            f"  # pages: karni import design <design folder> --app {site_app} --editable for a "
            f"designer's pages (karni rules --procedure {PROCEDURE}), or karni make view <name> "
            f"--app {site_app}"
        )
    typer.echo("  karni check")
    for line in _new_app_lines():
        typer.echo(line)
