"""The project's kind: a site, an app, both, a game, or an app with a game (``[tool.karni] kind``).

``karni new --kind site|app|site+app|game|app+game`` records the kind in
pyproject.toml, next to the ``baseline`` ``karni upgrade`` reads:

* ``site``: a public website. A site app on the karni-site module, edited in
  the admin by staff and the ``editor`` role, nobody signs up. The staff app
  (``frontend/``) is optional (``karni new --no-staff-app``).
* ``app``: an API and a React staff app, what ``karni new`` always made.
* ``site+app``: both.
* ``game``: a game first (experimental). The game is the front door: its
  client in ``game/<slug>/``, served at ``/play/<slug>/``, on the karni-game
  module (players, saves, scores, a wallet), with a ``games`` app for the
  game's server hooks and the game declared in ``content/game.yaml``. The
  admin and the API are there as in every kind. The staff app is optional
  (``karni new --staff-app``) and left out by default.
* ``app+game``: an app with a game in it (experimental), what ``--kind game``
  made in 0.6.0: the React app in ``frontend/`` hosts the game on a page.

``karni context`` prints it (``KIND:``) and the agent files state it with
the stack it implies (``karni rules sync``), so an agent never chooses the
technology. ``karni add site`` turns an app into a site+app, and ``karni add
game`` turns an app into an app+game.

A project made before kinds has none recorded. :func:`project_kind` infers
one from what the project has: ``karni_site`` in the ``# karni:apps`` block
is a site, ``frontend/package.json`` a staff app, ``karni_game`` a game, an
app+game when the game lives in the staff app. A project that records
``kind = "game"`` with the layout of 0.6.0 (the game in ``frontend/``, no
``game/<slug>/`` folder) is read as ``app+game``, the name that layout has
now. Nothing in it moves, and ``karni context`` says to record the new name.

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
    "GAME_FOLDER",
    "KINDS",
    "ProjectKind",
    "adopt_game_text",
    "adopt_site_text",
    "adoption_note",
    "game_adoption_note",
    "game_folders",
    "has_game",
    "project_kind",
    "recorded_kind",
    "set_kind_text",
    "summary",
]

KINDS: Final = ("site", "app", "site+app", "game", "app+game")
#: What ``karni new`` makes when nobody says, and nobody can be asked.
DEFAULT: Final = "app"
PYPROJECT: Final = "pyproject.toml"
SETTINGS: Final = Path("config") / "settings.py"
SITE_APP: Final = "karni_site"
GAME_APP: Final = "karni_game"
#: Where a game-first project keeps its games: ``game/<slug>/``, one npm package each.
GAME_FOLDER: Final = "game"

_SUMMARIES: Final = {
    "site": "a public website the client edits in the admin (a designer's pages, forms)",
    "app": "an API and a React app for signed-in users (screens, roles, workflows)",
    "site+app": "both: a public website and an app for signed-in users",
    "game": "a game first: the game at /play/<slug>/, its server, the admin, no staff app",
    "app+game": "an app with a game in it: the app's sign-in, the game on a page of the app",
}


def summary(kind: str) -> str:
    """One line for ``karni new``'s question."""
    return _SUMMARIES[kind]


def has_site(kind: str) -> bool:
    return kind in ("site", "site+app")


def has_game(kind: str) -> bool:
    """Whether a project of ``kind`` has a game (karni-game and @karni/game)."""
    return kind in ("game", "app+game")


def game_folders(root: Path) -> tuple[str, ...]:
    """The slugs of the games in ``root/game/``: each folder with a package.json, sorted."""
    folder = root / GAME_FOLDER
    if not folder.is_dir():
        return ()
    return tuple(sorted(path.parent.name for path in folder.glob("*/package.json")))


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
    site = game = False
    if settings.is_file():
        try:
            entries = block_entries(settings.read_text(encoding="utf-8"))
        except (OSError, CliError):
            entries = []
        site, game = SITE_APP in entries, GAME_APP in entries
    staff_app = (root / "frontend" / "package.json").is_file()
    if site:
        return "site+app" if staff_app else "site"
    if game:
        return "app+game" if staff_app and not game_folders(root) else "game"
    return "app"


def _read_as(recorded: str, root: Path, staff_app: bool) -> str:
    """The kind a recorded one is read as: 0.6.0's ``game`` layout is an ``app+game`` now."""
    if recorded == "game" and staff_app and not game_folders(root):
        return "app+game"
    return recorded


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


def adopt_game_text(text: str) -> tuple[str, str, str] | None:
    """pyproject.toml ``text`` once an app has a game (``karni add game``): ``(text, before, after)``.

    Only an app becomes an app+game. Every other kind keeps its record
    (``None``): a site has no kind with a game yet, and a game has one.
    """
    before = recorded_kind(text)
    if before != "app":
        return None
    return set_kind_text(text, "app+game"), before, "app+game"


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


def game_adoption_note(before: str, after: str) -> str:
    """What ``karni add game`` says when an app becomes an app+game, and the way back."""
    return (
        f"kind: {before} -> {after} (kind under [tool.karni] in pyproject.toml), so `karni "
        "context` and the agent files describe the game too. To go back, set "
        f'kind = "{before}" under [tool.karni] again and run `karni rules sync`.'
    )


@dataclass(frozen=True)
class ProjectKind:
    """A project's kind, whether pyproject.toml records it, its staff app and its games.

    ``recorded_as`` is the value pyproject.toml holds when the kind is read as
    another one (0.6.0's ``game`` layout, read as ``app+game``).
    """

    kind: str
    recorded: bool
    staff_app: bool
    games: tuple[str, ...] = ()
    recorded_as: str | None = None

    @property
    def site(self) -> bool:
        return has_site(self.kind)

    @property
    def app(self) -> bool:
        return self.kind in ("app", "site+app", "app+game")

    @property
    def game(self) -> bool:
        return has_game(self.kind)

    def _played_at(self) -> str:
        if len(self.games) == 1:
            return f"game/{self.games[0]}/ at /play/{self.games[0]}/"
        return "game/<slug>/ at /play/<slug>/"

    def context_line(self) -> str:
        """The ``KIND:`` line of ``karni context``."""
        parts = []
        if self.kind == "game":
            parts.append(
                f"a game first: {self._played_at()}, its server on karni-game: games app, "
                "content/game.yaml"
            )
        if self.kind == "app+game":
            parts.append("a game on karni-game, on a page of the app: content/game.yaml")
        if self.site:
            parts.append("public site (Django templates on karni-site, edited in the admin)")
        if self.app:
            parts.append("API + React app in frontend/")
        elif self.staff_app:
            parts.append("staff app in frontend/")
        else:
            parts.append("no staff app")
        if self.recorded_as is not None:
            note = (
                f', recorded as {self.recorded_as} (the 0.6.0 name): set kind = "{self.kind}" '
                "under [tool.karni]"
            )
        elif self.recorded:
            note = ""
        else:
            note = ", inferred: no kind in [tool.karni]"
        return f"KIND: {self.kind}{note} ({'; '.join(parts)})"

    def _recorded_text(self) -> str:
        if self.recorded_as is not None:
            return (
                f"kind `{self.recorded_as}` in pyproject.toml, read as `{self.kind}`, its name "
                f'since 0.7.0: set `kind = "{self.kind}"` under `[tool.karni]`'
            )
        if self.recorded:
            return f"kind `{self.kind}` in pyproject.toml"
        return f"kind `{self.kind}`, inferred: set `kind` under `[tool.karni]` in pyproject.toml"

    def _game_server(self, hooks: str) -> str:
        return (
            "The server side is the karni-game module: players (guests first), saves, scores, "
            "the wallet, daily content, achievements and remote config, mounted at "
            "`/api/game/`, with its screens in the admin. The game is declared in "
            "`content/game.yaml` (`karni load`) and its server hooks (save migrations, run "
            f"checks) go in {hooks}."
        )

    def agent_lines(self) -> list[str]:
        """The paragraph AGENTS.md and the other adapters open with: the kind and its stack."""
        recorded = self._recorded_text()
        stack = (
            "The stack is set, so never ask which technology to use: Python 3.12, Django 5.2, "
            "PostgreSQL, Redis and Celery"
        )
        site = (
            "Django views and templates that keep the designer's own HTML and CSS, in a site "
            "app on the karni-site module (`karni context` names it under SITE)"
        )
        procedure = "A designer's pages: `karni rules --procedure site-from-design`."
        honest = "Never let the client decide coins, scores or unlocks: the server does."
        if self.kind == "app":
            text = (
                f"An app ({recorded}). {stack}, a REST API on Django REST framework, and a React "
                "18 + TypeScript app in `frontend/` on @karni/ui. Screens go in "
                "`frontend/src/pages/` (`karni make page`). A public website joins with `karni "
                "add site` (rule K309)."
            )
        elif self.kind == "game":
            folder = f"game/{self.games[0]}" if len(self.games) == 1 else "game/<slug>"
            slug = self.games[0] if len(self.games) == 1 else "<slug>"
            staff = (
                "Staff also have the React staff app in `frontend/` on @karni/ui, at `/app/`."
                if self.staff_app
                else "There is no React staff app: staff work in the admin."
            )
            text = (
                f"A game ({recorded}). {stack}, a REST API on Django REST framework, and the "
                f"game itself in `{folder}/`: TypeScript on Vite and the @karni/game client, "
                f"its own npm package, served at `/play/{slug}/` (`npm run dev` there) and "
                "packaged for the game portals (`npm run package`). Its rules are plain "
                f"functions in `{folder}/src/rules/`, tested in `{folder}/tests/`. "
                f"{self._game_server('`games/game.py`')} {staff} {honest}"
            )
        elif self.kind == "app+game":
            hooks = "the `game.py` of an app"
            text = (
                f"An app with a game in it ({recorded}). {stack}, a REST API on Django REST "
                "framework, and a React 18 + TypeScript app in `frontend/` on @karni/ui whose "
                "pages host the game, its code in `frontend/src/game/` on the @karni/game "
                f"client. {self._game_server(hooks)} A project `karni new --kind app+game` "
                "made has the game's page at `/game`, its hooks in `games/game.py`, and "
                "`frontend/portal/`, which builds the game alone for the game portals (`npm "
                f"run game:package`). {honest}"
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
    games = game_folders(root)
    if recorded is not None:
        kind = _read_as(recorded, root, staff_app)
        return ProjectKind(kind, True, staff_app, games, recorded if kind != recorded else None)
    return ProjectKind(_inferred(root), False, staff_app, games)
