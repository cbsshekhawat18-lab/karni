"""The project's kind: a public site, an app, or both (``[tool.karni] kind``).

``karni new --kind site|app|site+app`` records the kind in pyproject.toml,
next to the ``baseline`` ``karni upgrade`` reads:

* ``site``: a public website. A site app on the karni-site module, edited in
  the admin by staff and the ``editor`` role, nobody signs up. The staff app
  (``frontend/``) is optional (``karni new --no-staff-app``).
* ``app``: an API and a React staff app, what ``karni new`` always made.
* ``site+app``: both.

``karni context`` prints it (``KIND:``) and the agent files state it with
the stack it implies (``karni rules sync``), so an agent never chooses the
technology. ``karni add site`` turns an app into a site+app.

A project made before kinds has none recorded. :func:`project_kind` infers
one from what the project has: ``karni_site`` in the ``# karni:apps`` block
is a site, ``frontend/package.json`` a staff app.

Override / escape hatch: ``kind`` in ``[tool.karni]`` is the project's to
edit (one of :data:`KINDS`), then ``karni rules sync`` rewrites the agent
files. :func:`set_kind_text` is the edit ``karni add site`` makes.
"""

from __future__ import annotations

import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import tomlkit

from karni_cli.project import CliError
from karni_cli.settings_edit import block_entries

__all__ = [
    "DEFAULT",
    "KINDS",
    "ProjectKind",
    "adopt_site_text",
    "adoption_note",
    "project_kind",
    "recorded_kind",
    "set_kind_text",
    "summary",
]

KINDS: Final = ("site", "app", "site+app")
#: What ``karni new`` makes when nobody says, and nobody can be asked.
DEFAULT: Final = "app"
PYPROJECT: Final = "pyproject.toml"
SETTINGS: Final = Path("config") / "settings.py"
SITE_APP: Final = "karni_site"

_SUMMARIES: Final = {
    "site": "a public website the client edits in the admin (a designer's pages, forms)",
    "app": "an API and a React app for signed-in users (screens, roles, workflows)",
    "site+app": "both: a public website and an app for signed-in users",
}


def summary(kind: str) -> str:
    """One line for ``karni new``'s question."""
    return _SUMMARIES[kind]


def has_site(kind: str) -> bool:
    return kind in ("site", "site+app")


def _invalid(value: object) -> CliError:
    return CliError(
        f"pyproject.toml has kind = {value!r} under [tool.karni], which is not a kind Karni "
        f"knows. Set it to one of {', '.join(KINDS)}.",
        code="C112",
    )


def recorded_kind(text: str | None) -> str | None:
    """``[tool.karni] kind`` in pyproject.toml ``text``, or ``None`` when it has none."""
    if not text:
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    tool = data.get("tool", {})
    karni = tool.get("karni", {}) if isinstance(tool, dict) else {}
    value = karni.get("kind") if isinstance(karni, dict) else None
    if value is None:
        return None
    if value not in KINDS:
        raise _invalid(value)
    return str(value)


def set_kind_text(text: str, kind: str) -> str:
    """pyproject.toml ``text`` with ``kind`` under ``[tool.karni]`` (the table is added if absent)."""
    if kind not in KINDS:
        raise _invalid(kind)
    doc = tomlkit.parse(text)
    tool = doc.get("tool")
    if tool is None:
        tool = tomlkit.table(is_super_table=True)
        doc["tool"] = tool
    karni = tool.get("karni")
    if karni is None:
        karni = tomlkit.table()
        tool["karni"] = karni
    karni["kind"] = kind
    return tomlkit.dumps(doc)


def _inferred(root: Path) -> str:
    settings = root / SETTINGS
    site = False
    if settings.is_file():
        try:
            site = SITE_APP in block_entries(settings.read_text(encoding="utf-8"))
        except (OSError, CliError):
            site = False
    staff_app = (root / "frontend" / "package.json").is_file()
    if site:
        return "site+app" if staff_app else "site"
    return "app"


def adopt_site_text(text: str, root: Path) -> tuple[str, str, str] | None:
    """pyproject.toml ``text`` once the project has a site: ``(text, before, after)``.

    An app becomes a site+app, a project with no kind recorded gets the one it
    has now. ``None`` when the recorded kind has a site already.
    """
    before = recorded_kind(text)
    if before is not None and has_site(before):
        return None
    staff_app = (root / "frontend" / "package.json").is_file()
    after = "site+app" if before == "app" or (before is None and staff_app) else "site"
    return set_kind_text(text, after), before or "none recorded", after


def adoption_note(before: str, after: str) -> str:
    """What ``karni add site`` (and ``karni make site``) say when the kind changes, and the way back."""
    back = (
        f'set kind = "{before}" under [tool.karni] again'
        if before in KINDS
        else "remove kind from [tool.karni]"
    )
    return (
        f"kind: {before} -> {after} (kind under [tool.karni] in pyproject.toml), so `karni "
        "context` and the agent files describe the site too. To go back, "
        f"{back} and run `karni rules sync`. The site's files stay until you delete them: "
        "the site app and its include in config/urls.py, and karni-site (karni-site in "
        "pyproject.toml, karni_site with its middleware and context processor in "
        "config/settings.py)."
    )


@dataclass(frozen=True)
class ProjectKind:
    """A project's kind, whether pyproject.toml records it, and whether it has a staff app."""

    kind: str
    recorded: bool
    staff_app: bool

    @property
    def site(self) -> bool:
        return has_site(self.kind)

    @property
    def app(self) -> bool:
        return self.kind in ("app", "site+app")

    def context_line(self) -> str:
        """The ``KIND:`` line of ``karni context``."""
        parts = []
        if self.site:
            parts.append("public site (Django templates on karni-site, edited in the admin)")
        if self.app:
            parts.append("API + React app in frontend/")
        elif self.staff_app:
            parts.append("staff app in frontend/")
        else:
            parts.append("no staff app")
        note = "" if self.recorded else ", inferred: no kind in [tool.karni]"
        return f"KIND: {self.kind}{note} ({'; '.join(parts)})"

    def agent_lines(self) -> list[str]:
        """The paragraph AGENTS.md and the other adapters open with: the kind and its stack."""
        recorded = (
            f"kind `{self.kind}` in pyproject.toml"
            if self.recorded
            else f"kind `{self.kind}`, inferred: set `kind` under `[tool.karni]` in pyproject.toml"
        )
        stack = (
            "The stack is set, so never ask which technology to use: Python 3.12, Django 5.2, "
            "PostgreSQL, Redis and Celery"
        )
        site = (
            "Django views and templates that keep the designer's own HTML and CSS, in a site "
            "app on the karni-site module (`karni context` names it under SITE)"
        )
        procedure = "A designer's pages: `karni rules --procedure site-from-design`."
        if self.kind == "app":
            text = (
                f"An app ({recorded}). {stack}, a REST API on Django REST framework, and a React "
                "18 + TypeScript app in `frontend/` on @karni/ui. Screens go in "
                "`frontend/src/pages/` (`karni make page`). A public website joins with `karni "
                "add site` (rule K309)."
            )
        elif self.kind == "site":
            staff = (
                "Staff also have the React staff app in `frontend/` (@karni/ui), for the "
                "requests a form collects."
                if self.staff_app
                else "There is no React staff app: staff work in the admin, the requests a form "
                "collects included."
            )
            text = (
                f"A public website ({recorded}). {stack}, and {site}. The client edits every "
                "text, image, menu and page title in the admin, as staff or with the `editor` "
                f"role. Nobody signs up. {staff} Pages: `karni make view` (rule K309). "
                f"{procedure}"
            )
        else:
            text = (
                f"A public website and an app ({recorded}). {stack}. The site is {site}, "
                "edited in the admin. The app is a REST API on Django REST framework and a "
                "React 18 + TypeScript app in `frontend/` on @karni/ui. Site pages: `karni "
                "make view` (rule K309). App screens: `karni make page`. "
                f"{procedure}"
            )
        return textwrap.wrap(text, width=88, break_long_words=False, break_on_hyphens=False)


def project_kind(root: Path) -> ProjectKind | None:
    """The kind ``root`` records in pyproject.toml, else the one its files show.

    ``None`` without a pyproject.toml: a directory with a manage.py and no
    project file is not a project Karni made, and its kind is not guessed.
    """
    pyproject = root / PYPROJECT
    if not pyproject.is_file():
        return None
    text = pyproject.read_text(encoding="utf-8")
    recorded = recorded_kind(text)
    staff_app = (root / "frontend" / "package.json").is_file()
    if recorded is not None:
        return ProjectKind(recorded, True, staff_app)
    return ProjectKind(_inferred(root), False, staff_app)
