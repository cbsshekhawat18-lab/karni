"""``karni context`` — the token-efficiency mechanism.

Backend inventory comes from ``manage.py karni_context``; COMPONENTS/HOOKS
come from @karni/ui's build-generated dist/manifest.json. Absent manifest →
those lines are omitted entirely (never stale, never guessed). The first line
is KIND, the project's kind (:mod:`karni_cli.kinds`). Lines are read
statically from the project tree (no Django): KIND, APPS, the local apps in
the ``# karni:apps`` block that live in this project, PAGES, the files
under ``frontend/src/pages/``, and SITE, the routes of every local urls.py
that config/urls.py includes (the public site, webhooks), and DESIGN, the
designer's pages ``karni import design`` imported (``.karni/design.json``), and CATALOG,
a line per module and built-in feature with whether the project has it
(:func:`catalog_lines`, experimental). Together with
``karni rules`` this is enough for an agent to start work without reading
files.

``--with-history [PATH]`` appends a ``HISTORY:`` block from any history
provider that detects a store (``karni.agent.history``), capped at ~300
tokens; with no store the output is byte-identical to plain ``karni context``.
stdout stays machine-clean in every mode: no tips, no warnings.

Slices (experimental), for a project too large to read at once:
``--summary`` prints one line per app (models, viewsets, pages and their
counts), ``--app LABEL`` one app in full and ``--model NAME`` one model in
depth (``manage.py karni_context`` with the same flags, :mod:`karni.introspect`).
``--max-tokens N`` cuts the output at whole sections (:func:`cut_sections`)
and ends it with a ``LEFT OUT:`` line naming what was cut and the command
that shows it. Without these flags the output is what it always was.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import typer

from karni_cli import history
from karni_cli import project as project_mod
from karni_cli.kinds import project_kind
from karni_cli.project import CliError, require_project
from karni_cli.settings_edit import MARKER
from karni_cli.urls_edit import routes

#: Mirrors karni.agent.history.HISTORY_TOKEN_CAP (that module enforces it); a
#: constant here keeps `karni context --help` free of provider discovery.
HISTORY_TOKEN_CAP = 300

_PAGE_SUFFIXES = (".tsx", ".ts", ".jsx", ".js")
_QUOTED = re.compile(r"""["']([^"']+)["']""")


def find_manifest(project: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for base in (project / "frontend", project):
        candidate = base / "node_modules" / "@karni" / "ui" / "dist" / "manifest.json"
        if candidate.is_file():
            return candidate
    return None


def manifest_lines(manifest_path: Path) -> list[str]:
    try:
        data = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    lines: list[str] = []
    if data.get("components"):
        lines.append("COMPONENTS: " + " ".join(sorted(data["components"])))
    if data.get("hooks"):
        lines.append("HOOKS: " + " ".join(sorted(data["hooks"])))
    return lines


def apps_line(project: Path) -> str | None:
    """Local apps wired in the ``# karni:apps`` block, as ``label(path/)``."""
    settings = project / "config" / "settings.py"
    if not settings.is_file():
        return None
    lines = settings.read_text().splitlines()
    end = next((i for i, line in enumerate(lines) if MARKER in line), None)
    if end is None:
        return None
    start = next(
        (i for i in range(end, -1, -1) if "INSTALLED_APPS" in lines[i] and "[" in lines[i]), end
    )
    names: list[str] = []
    for line in lines[start : end + 1]:
        code = line.split("#", 1)[0]
        names += _QUOTED.findall(code)
    found = []
    for name in names:
        module = name.split(".apps.", 1)[0]
        path = Path(*module.split("."))
        if (project / path).is_dir():
            found.append(f"{module.rsplit('.', 1)[-1]}({path.as_posix()}/)")
    return "APPS: " + " ".join(found) if found else None


def pages_line(project: Path) -> str | None:
    pages = project / "frontend" / "src" / "pages"
    if not pages.is_dir():
        return None
    found = sorted(
        path.relative_to(pages).with_suffix("").as_posix()
        for path in pages.rglob("*")
        if path.suffix in _PAGE_SUFFIXES and not path.name.endswith((".test.tsx", ".test.ts"))
    )
    return "PAGES: " + " ".join(found) if found else None


def site_line(project: Path) -> str | None:
    """Routes of the local urls.py modules that config/urls.py includes, as ``app(/ /about/)``.

    Read statically: a ``path("<prefix>", include("<module>.urls"))`` line in
    config/urls.py whose module lives in the project, then every
    ``path("<route>", ...)`` line of that module's urls.py.
    """
    config = project / "config" / "urls.py"
    if not config.is_file():
        return None
    found: list[str] = []
    for prefix, _, include in routes(config.read_text()):
        if not include or not include.endswith(".urls"):
            continue
        module = include.removesuffix(".urls")
        urls = project.joinpath(*module.split(".")) / "urls.py"
        if not urls.is_file():
            continue
        paths = [f"/{prefix}{route}" for route, _, _ in routes(urls.read_text())]
        found.append(f"{module.rsplit('.', 1)[-1]}({' '.join(paths)})")
    return "SITE: " + " ".join(found) if found else None


def design_line(project: Path) -> str | None:
    """The design ``karni import design`` imported, from ``.karni/design.json``.

    ``DESIGN: ../design in website (7 page(s), editable, content map
    content/design-map.json)``: where a site from a designer's pages stands, so
    an agent picks up the site-from-design procedure where it was left.
    """
    record_file = project / ".karni" / "design.json"
    try:
        record = json.loads(record_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    editable = record.get("editable") or {}
    parts = [f"{len(record.get('pages') or [])} page(s)"]
    if isinstance(editable, dict) and editable.get("enabled"):
        parts.append("editable")
        if editable.get("map"):
            parts.append(f"content map {editable['map']}")
    return f"DESIGN: {record.get('source', '?')} in {record.get('app', '?')} ({', '.join(parts)})"


def catalog_lines(project: Path, backend_output: str = "") -> list[str]:
    """Experimental. The ``CATALOG:`` block: one line per module and built-in feature.

    Each line names the entry, whether the project has it (a module is
    added when its app is in the ``# karni:apps`` block, a feature is on
    when the backend's ``FEATURES:`` line names it) and its purpose, from
    the module catalog (:mod:`karni_cli.catalog`). Read without a
    subprocess. ``[]`` when the catalog cannot be read.
    """
    from karni_cli import catalog

    try:
        loaded = catalog.load(project, ask_project=False)
    except CliError:
        return []
    found = next((ln for ln in backend_output.split("\n") if ln.startswith("FEATURES:")), None)
    on = set(found.removeprefix("FEATURES:").split()) if found is not None else None
    lines = ["CATALOG: karni modules show NAME for options. Modules: karni add NAME."]
    for manifest in loaded.modules:
        state = "added" if manifest.name in loaded.added else "not added"
        lines.append(f"  {manifest.name} module, {state}: {manifest.purpose}")
    for manifest in loaded.features:
        state = "" if on is None else (", on" if manifest.name in on else ", off")
        lines.append(f"  {manifest.name} feature{state}: {manifest.purpose}")
    return lines


def with_catalog(text: str, lines: list[str]) -> str:
    """``text`` with the CATALOG block before ``BASES:``, in place of the ``FEATURES:`` line."""
    sections = [line for line in text.split("\n") if not line.startswith("FEATURES:")]
    insert_at = next(
        (i for i, line in enumerate(sections) if line.startswith("BASES:")), len(sections)
    )
    sections[insert_at:insert_at] = lines
    return "\n".join(sections)


def assemble(backend_output: str, ui_lines: list[str]) -> str:
    """Merge UI lines into the backend sections, keeping the documented order
    (MODELS, VIEWSETS, COMPONENTS, HOOKS, PAGES, SITE, MODULES, BASES)."""
    sections = [line for line in backend_output.split("\n") if line.strip()]
    insert_at = next(
        (i for i, line in enumerate(sections) if line.startswith(("MODULES:", "BASES:"))),
        len(sections),
    )
    sections[insert_at:insert_at] = ui_lines
    return "\n".join(sections)


def build_context_text(
    project: Path,
    *,
    docker: bool | None = None,
    service: str = "django",
    manifest: Path | None = None,
) -> str:
    """The full inventory: KIND, APPS, MODELS, VIEWSETS, COMPONENTS, HOOKS, PAGES, SITE, MODULES,
    CATALOG, BASES.

    Raises :class:`CliError` when the backend inventory command fails, or the
    project's kind is not one Karni knows.
    """
    kind_of = project_kind(project)
    kind = kind_of.context_line() if kind_of is not None else None
    proc = project_mod.run_manage(project, ["karni_context"], docker=docker, service=service)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise CliError(f"manage.py karni_context failed (exit {proc.returncode}).", code="C009")
    found = find_manifest(project, manifest)
    ui_lines = manifest_lines(found) if found else []
    ui_lines += [
        line for line in (pages_line(project), site_line(project), design_line(project)) if line
    ]
    text = with_catalog(assemble(proc.stdout, ui_lines), catalog_lines(project, proc.stdout))
    apps = apps_line(project)
    return "\n".join(line for line in (kind, apps, text) if line)


#: Experimental. Characters per token in the ``--max-tokens`` estimate (as the history cap).
CHARS_PER_TOKEN = 4
_UNRECOGNIZED = "unrecognized arguments"


def estimate_tokens(text: str) -> int:
    """Experimental. About how many tokens ``text`` takes: one per :data:`CHARS_PER_TOKEN`."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def split_sections(text: str) -> list[str]:
    """Experimental. ``text`` as sections: a line, with the indented lines under it."""
    sections: list[str] = []
    for line in text.split("\n"):
        if sections and (not line or line[:1].isspace()):
            sections[-1] += "\n" + line
        else:
            sections.append(line)
    return sections


def _section_name(section: str) -> str:
    head = section.split(":", 1)[0]
    if head == "MODEL":
        return f"MODEL {section.split(':', 1)[1].split()[0]}" if " " in section else head
    return head


def cut_sections(text: str, max_tokens: int, command: str) -> str:
    """Experimental. ``text`` cut at whole sections to about ``max_tokens`` tokens.

    The sections are kept in order while they fit, with room for a last
    ``LEFT OUT:`` line that names each section cut, their tokens and
    ``command``, which prints them. ``text`` comes back unchanged when it fits.
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    sections = split_sections(text)
    kept: list[str] = []
    for index, section in enumerate(sections):
        left = sections[index:]
        note = (
            f"LEFT OUT: {' '.join(_section_name(s) for s in left)} "
            f"(~{estimate_tokens(chr(10).join(left))} tokens). {command} prints them."
        )
        rest = sections[index + 1 :]
        later = (
            f"LEFT OUT: {' '.join(_section_name(s) for s in rest)} "
            f"(~{estimate_tokens(chr(10).join(rest))} tokens). {command} prints them."
        )
        if estimate_tokens("\n".join([*kept, section, later])) > max_tokens:
            return "\n".join([*kept, note])
        kept.append(section)
    return "\n".join(kept)


def slice_args(apps: list[str], models: list[str], summary: bool) -> list[str]:
    """The ``manage.py karni_context`` argv of a slice."""
    args = ["karni_context"]
    if summary:
        args.append("--summary")
    for label in apps:
        args += ["--app", label]
    for name in models:
        args += ["--model", name]
    return args


def _apps_for(project: Path, labels: list[str]) -> str | None:
    """The ``APPS:`` line cut to ``labels`` (all of them when ``labels`` is empty)."""
    line = apps_line(project)
    if line is None or not labels:
        return line
    found = [part for part in line.removeprefix("APPS: ").split() if part.split("(")[0] in labels]
    return "APPS: " + " ".join(found) if found else None


def build_slice_text(
    project: Path,
    *,
    apps: list[str],
    models: list[str],
    summary: bool,
    docker: bool | None = None,
    service: str = "django",
) -> str:
    """Experimental. ``KIND``, the ``APPS`` line cut to the slice, then the backend's slice.

    Raises :class:`CliError` ``C580`` when the project's karni predates the
    slices, ``C009`` when the backend command fails (an unknown name: its
    ``E470`` message is on stderr).
    """
    kind_of = project_kind(project)
    kind = kind_of.context_line() if kind_of is not None else None
    proc = project_mod.run_manage(
        project, slice_args(apps, models, summary), docker=docker, service=service
    )
    if proc.returncode != 0 and _UNRECOGNIZED in (proc.stderr or ""):
        raise CliError(
            "The project's karni has no context slices (--summary, --app, --model): it "
            "predates them. Upgrade karni in the project (pip install -U karni), or run "
            "karni context without them.",
            code="C580",
        )
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise CliError(f"manage.py karni_context failed (exit {proc.returncode}).", code="C009")
    apps_shown = _apps_for(project, apps) if (summary or apps) else None
    body = "\n".join(line for line in proc.stdout.split("\n") if line.strip())
    return "\n".join(line for line in (kind, apps_shown, body) if line)


def _command(apps: list[str], models: list[str], summary: bool) -> str:
    """The ``karni context`` command a cut output points at (the same, without --max-tokens)."""
    parts = ["karni context"]
    if summary:
        parts.append("--summary")
    parts += [f"--app {label}" for label in apps]
    parts += [f"--model {name}" for name in models]
    return " ".join(parts)


_WITH_HISTORY_HELP = (
    "Append what a history provider (e.g. Gigai Chronicle) recorded about PATH under a "
    "HISTORY: heading. Without PATH, append the project's recorded decisions, from the "
    f"providers that offer them. The block is capped at ~{HISTORY_TOKEN_CAP} tokens "
    f"(~{4 * HISTORY_TOKEN_CAP} characters) and cut at line boundaries, with a last line "
    "naming the command for the full brief. With no history store detected, it prints the "
    "plain inventory and nothing else."
)


def context(
    path: str | None = typer.Argument(
        None,
        metavar="PATH",
        help="File to brief, relative to the cwd (needs --with-history).",
        show_default=False,
    ),
    with_history: bool = typer.Option(False, "--with-history", help=_WITH_HISTORY_HELP),
    docker: bool | None = typer.Option(None, "--docker/--no-docker"),
    service: str = typer.Option("django", "--service", envvar="KARNI_COMPOSE_SERVICE"),
    manifest: Path | None = typer.Option(None, "--manifest", help="Explicit manifest.json path"),
    apps: list[str] = typer.Option(
        [],
        "--app",
        metavar="LABEL",
        help="Only this app, in full: every model with its fields, the relations in and out, "
        "its viewsets with route and access, its roles and pages (repeatable). Experimental.",
        show_default=False,
    ),
    models: list[str] = typer.Option(
        [],
        "--model",
        metavar="NAME",
        help="One model in depth: Name or app_label.Name. Every field, the relations that "
        "point at it, its viewsets and pages (repeatable). Experimental.",
        show_default=False,
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        help="One line per app: its models, viewsets and pages, with their counts. Experimental.",
    ),
    max_tokens: int | None = typer.Option(
        None,
        "--max-tokens",
        min=1,
        metavar="N",
        help="Cut the output at whole sections to about N tokens (4 characters each). The last "
        "line names what was left out and the command that prints it. Experimental.",
        show_default=False,
    ),
) -> None:
    """Print a compact machine-readable project inventory.

    On a large project read one area at a time: --summary first, then --app or --model.

    Example: karni context --app catalog --max-tokens 1500
    """
    if path is not None and not with_history:
        raise typer.BadParameter("PATH is only used with --with-history.", param_hint="PATH")
    if summary and models:
        raise typer.BadParameter("--summary lists the apps: use it without --model.")
    project = require_project()
    sliced = summary or bool(apps) or bool(models)
    try:
        target = history.target(project, path) if path is not None else None
        if sliced:
            text = build_slice_text(
                project, apps=apps, models=models, summary=summary, docker=docker, service=service
            )
        else:
            text = build_context_text(project, docker=docker, service=service, manifest=manifest)
    except CliError as exc:
        sys.stderr.write(f"{exc}\n")
        raise typer.Exit(1) from None
    if with_history:
        block = history.block(project, target)
        if block:
            text = f"{text}\n{block}"
    if max_tokens is not None:
        text = cut_sections(text, max_tokens, _command(apps, models, summary))
    typer.echo(text)
