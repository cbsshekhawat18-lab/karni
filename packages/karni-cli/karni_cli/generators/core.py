"""Shared machinery for ``karni make``: the virtual workspace, app resolution, output.

Every generator works against a :class:`Workspace` — an in-memory overlay of
the project tree. Generators read through it, plan their writes into it, and
only :meth:`Workspace.commit` touches the disk, after every generator in the
chain has succeeded. So a failing step (an existing target without
``--force``, an unsupported layout) writes nothing, and ``--dry-run`` shows
exactly what a real run would write.

Universal rules (docs/cli.md "Generators"):

* never overwrite an existing target without ``--force``;
* edit existing files only through marker comments or AST-located appends;
* never import Django — anything that needs it runs through the project
  interpreter (:func:`karni_cli.project.run_manage`).
"""

from __future__ import annotations

import difflib
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import typer

from karni_cli.project import CliError, require_project
from karni_cli.settings_edit import MARKER, block_entries

#: Ruff's default line length — what a project without ``[tool.ruff]`` gets.
DEFAULT_LINE_LENGTH = 88

SETTINGS = Path("config") / "settings.py"
FRONTEND = Path("frontend")

#: Import sections in ruff/isort order.
FUTURE, STDLIB, THIRD_PARTY, FIRST_PARTY, LOCAL = range(5)


@dataclass
class _Entry:
    before: str | None
    after: str


class Workspace:
    """An in-memory overlay of ``root``: reads see planned writes; disk is untouched until commit.

    :param root: the directory generators write under (the project, or the
        cwd for ``make module`` outside a project).
    :param force: overwrite existing targets instead of refusing.
    """

    def __init__(self, root: Path, *, force: bool = False) -> None:
        self.root = root.resolve()
        self.force = force
        self.notes: list[str] = []
        self._files: dict[Path, _Entry] = {}
        self._line_length: int | None = None

    # --- paths ----------------------------------------------------------------

    def path(self, rel: str | Path) -> Path:
        candidate = Path(rel)
        return candidate if candidate.is_absolute() else self.root / candidate

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    # --- reading --------------------------------------------------------------

    def read(self, rel: str | Path) -> str | None:
        """Planned content, else disk content, else ``None``."""
        path = self.path(rel)
        if path in self._files:
            return self._files[path].after
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def exists(self, rel: str | Path) -> bool:
        return self.read(rel) is not None

    def is_dir(self, rel: str | Path) -> bool:
        """A directory on disk, or one a planned file will create."""
        path = self.path(rel)
        if path.is_dir():
            return True
        return any(path in planned.parents for planned in self._files)

    def module_exists(self, module: str) -> bool:
        """``a.b`` exists under the root as ``a/b.py`` or a directory ``a/b/``."""
        base = self.root.joinpath(*module.split("."))
        return self.exists(base.with_suffix(".py")) or self.is_dir(base)

    # --- writing --------------------------------------------------------------

    def create(self, rel: str | Path, content: str) -> None:
        """Plan a new file; an existing one is an error unless ``--force``."""
        path = self.path(rel)
        if self.exists(path) and path not in self._files and not self.force:
            raise CliError(f"{self.rel(path)} already exists — pass --force to overwrite it.")
        self._record(path, content)

    def create_skeleton(self, files: dict[Path, str]) -> None:
        """Plan a multi-file skeleton (an app, a module) that never truncates user code.

        Without ``--force`` any existing file is an error; with it, existing
        files are kept and only the missing ones are created.
        """
        existing = [path for path in files if self.exists(path)]
        if existing and not self.force:
            shown = ", ".join(self.rel(path) for path in existing[:3])
            raise CliError(
                f"{shown} already exist{'s' if len(existing) == 1 else ''} — pass --force "
                "to create only the missing files (existing ones are kept)."
            )
        for path, content in files.items():
            if path in existing:
                self.note(f"kept     {self.rel(path)} (exists)")
            else:
                self.create(path, content)

    def write(self, rel: str | Path, content: str) -> None:
        """Plan the new content of a file being edited (or created by an edit)."""
        self._record(self.path(rel), content)

    def refuse_existing(self, what: str) -> None:
        """Raise unless ``--force``: ``what`` (e.g. "class Event in events/models.py") exists."""
        if not self.force:
            raise CliError(f"{what} already exists — pass --force to replace it.")

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def _record(self, path: Path, content: str) -> None:
        if path in self._files:
            self._files[path].after = content
            return
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        self._files[path] = _Entry(before, content)

    # --- project facts ----------------------------------------------------------

    @property
    def line_length(self) -> int:
        """The project's ruff line length (``[tool.ruff] line-length``, default 88)."""
        if self._line_length is None:
            self._line_length = DEFAULT_LINE_LENGTH
            text = self.read("pyproject.toml")
            if text:
                try:
                    ruff = tomllib.loads(text).get("tool", {}).get("ruff", {})
                except tomllib.TOMLDecodeError:
                    ruff = {}
                value = ruff.get("line-length")
                if isinstance(value, int) and value > 0:
                    self._line_length = value
        return self._line_length

    def import_section(self, module: str, level: int = 0) -> int:
        """The ruff/isort section of ``module`` as seen from the project root."""
        if level:
            return LOCAL
        top = module.split(".", 1)[0]
        if top == "__future__":
            return FUTURE
        if top in sys.stdlib_module_names:
            return STDLIB
        if self.module_exists(module):
            return FIRST_PARTY
        return THIRD_PARTY

    # --- output -------------------------------------------------------------------

    def changes(self) -> list[tuple[Path, str | None, str]]:
        return [
            (path, entry.before, entry.after)
            for path, entry in self._files.items()
            if entry.before != entry.after
        ]

    def commit(self, *, dry_run: bool) -> None:
        """Write (or, with ``dry_run``, show) every planned change, then the notes."""
        for path, before, after in self.changes():
            rel = self.rel(path)
            verb = "create" if before is None else "modify"
            if dry_run:
                typer.echo(f"would {verb} {rel}")
                diff = difflib.unified_diff(
                    (before or "").splitlines(keepends=True),
                    after.splitlines(keepends=True),
                    fromfile="/dev/null" if before is None else f"a/{rel}",
                    tofile=f"b/{rel}",
                )
                typer.echo("".join(diff).rstrip("\n"))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(after, encoding="utf-8")
            typer.echo(f"{'created' if before is None else 'modified':<9}{rel}")
        if not self.changes():
            typer.echo("nothing to change")
        for note in self.notes:
            typer.echo(note)
        if dry_run:
            typer.echo("(dry run: nothing written)")


# --- shared command options ---------------------------------------------------------

APP_OPTION = typer.Option(
    None, "--app", help="Target app label (default: the project's only local app)."
)
FORCE_OPTION = typer.Option(False, "--force", help="Overwrite / replace existing targets.")
DRY_RUN_OPTION = typer.Option(
    False, "--dry-run", help="Print the files and diff it would write; write nothing."
)


def project_workspace(force: bool) -> Workspace:
    """A workspace over the project found from the cwd (manage.py)."""
    return Workspace(require_project(), force=force)


# --- apps -----------------------------------------------------------------------------


@dataclass(frozen=True)
class App:
    """A local app wired into the ``# karni:apps`` block."""

    label: str
    module: str
    path: Path

    def file(self, *parts: str) -> Path:
        return self.path.joinpath(*parts)


def local_apps(ws: Workspace) -> list[App]:
    """Entries of the ``# karni:apps`` block whose package lives in the project."""
    text = ws.read(SETTINGS)
    if text is None:
        return []
    found: list[App] = []
    for entry in block_entries(text):
        module = entry.split(".apps.", 1)[0]
        path = ws.root.joinpath(*module.split("."))
        if ws.is_dir(path):
            found.append(App(module.rsplit(".", 1)[-1], module, path))
    return found


def resolve_app(ws: Workspace, name: str | None) -> App:
    """``--app NAME`` (label or module path), else the project's only local app."""
    apps = local_apps(ws)
    listing = ", ".join(app.label for app in apps)
    if name is not None:
        for app in apps:
            if name in (app.label, app.module):
                return app
        if not apps:
            raise CliError(f"No local app {name!r} — create it first: karni make app {name}")
        raise CliError(f"No local app {name!r} (local apps: {listing}) — or: karni make app {name}")
    if len(apps) == 1:
        return apps[0]
    if not apps:
        raise CliError(
            "This project has no local app yet (none in the `# karni:apps` block of "
            "config/settings.py) — create one first: karni make app <name>"
        )
    raise CliError(f"Several local apps ({listing}) — choose one with --app <label>.")


def require_settings(ws: Workspace) -> str:
    text = ws.read(SETTINGS)
    if text is None:
        raise CliError(f"{SETTINGS.as_posix()} not found — run inside a Karni project.")
    if MARKER not in text:
        raise CliError(
            f"No `{MARKER}` block in {SETTINGS.as_posix()} — karni make finds local apps "
            "there. Add one (see the scaffold's settings.py) and list your apps in it."
        )
    return text


def require_frontend(ws: Workspace) -> Path:
    path = ws.path(FRONTEND)
    if not ws.is_dir(path):
        raise CliError("No frontend/ directory in this project — pages and components live there.")
    return path


def split_csv(values: Iterable[str] | None) -> list[str]:
    """``["a,b", "c"]`` → ``["a", "b", "c"]`` (repeatable and comma-separated options)."""
    out: list[str] = []
    for value in values or ():
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out
