"""Experimental. Game starters: ready games a new game project starts from.

``karni new "<Name>" --kind game --genre <genre>`` writes one, and ``karni
starters list`` (``--match "<one line>"``, ``show <genre>``) lists them, as
``karni recipes`` does for apps. A starter is data and templates shipped by
the package that owns the game side (karni-game), versioned with it and found
through the ``karni.starters`` entry points. Each names a folder:

    starter.toml   what it is: name, title, purpose, use_when, usually_changed
    game/          the game's own files, written to game/<slug>/
    project/       the project's own files at their paths (games/, content/)

``blank`` is built in: the small game ``--kind game`` writes on its own
(:func:`karni_cli.generators.game.plan_game_first`). Every file a starter
writes is the project's own: its rules, scenes, drawing and content import
everything else from ``@karni/game``. ``__GAME_SLUG__``, ``__GAME_TITLE__``
and ``__KARNI_GAME_SPEC__`` are filled in as the files are written.

Override / escape hatch: a package of your own adds a starter with a
``karni.starters`` entry point naming its folder (a package path or an
``importlib.resources`` traversable).
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import EntryPoint, entry_points
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from karni_cli.project import CliError

__all__ = [
    "BLANK",
    "ENTRY_POINT_GROUP",
    "Loaded",
    "Match",
    "Starter",
    "load",
    "match",
]

#: Experimental. The entry point group a package adds its starters to.
ENTRY_POINT_GROUP: Final = "karni.starters"
#: Experimental. The empty start: the small game ``karni new --kind game`` writes.
BLANK: Final = "blank"
#: Experimental. The file that says what a starter is.
STARTER_FILE: Final = "starter.toml"
#: Experimental. The folders of a starter: the game's files, and the project's.
GAME_DIR: Final = "game"
PROJECT_DIR: Final = "project"
#: Where each starter's install comes from, when its package is not installed.
PACKAGES: Final = {"runner": "karni-game"}
#: Files a starter may not ship yet: every file is text with its placeholders filled in.
BINARY: Final = (".png", ".jpg", ".jpeg", ".webp", ".ogg", ".mp3", ".wav", ".woff2", ".ico")


class _StarterToml(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1, max_length=100)
    use_when: list[str] = Field(default_factory=list)
    usually_changed: list[str] = Field(default_factory=list)
    example: str = ""


@dataclass(frozen=True)
class Starter:
    """Experimental. One starter: what it is, where it comes from and its folder."""

    name: str
    title: str
    purpose: str
    use_when: tuple[str, ...]
    usually_changed: tuple[str, ...]
    source: str
    example: str = ""
    folder: Traversable | Path | None = None

    def _files(self, sub: str) -> list[tuple[str, Traversable]]:
        if self.folder is None:
            return []
        root = self.folder.joinpath(sub)
        found: list[tuple[str, Traversable]] = []

        def walk(node: Traversable, prefix: str) -> None:
            for child in sorted(node.iterdir(), key=lambda item: item.name):
                if child.name in {"node_modules", "__pycache__", "dist", ".DS_Store"}:
                    continue
                rel = f"{prefix}{child.name}"
                if child.is_dir():
                    walk(child, f"{rel}/")
                else:
                    found.append((rel, child))

        if root.is_dir():
            walk(root, "")
        return found

    def game_files(self) -> list[str]:
        """The game's files, by their path in ``game/<slug>/``."""
        return [rel for rel, _ in self._files(GAME_DIR)]

    def project_files(self) -> list[str]:
        """The project's files, by their path in the project."""
        return [rel for rel, _ in self._files(PROJECT_DIR)]

    def render(self, sub: str, *, slug: str, title: str, spec: str) -> dict[str, str]:
        """The files of ``game`` or ``project``, the placeholders filled in.

        :raises CliError: ``C482`` for a file that is not text (images and sounds wait
            for a starter that needs them: the runner draws in code and makes its sounds).
        """
        out: dict[str, str] = {}
        for rel, node in self._files(sub):
            if rel.lower().endswith(BINARY):
                raise CliError(
                    f"The {self.name} starter ({self.source}) has {sub}/{rel}, and a starter's "
                    "files are text for now.",
                    code="C482",
                )
            text = node.read_text(encoding="utf-8")
            out[rel] = (
                text.replace("__GAME_SLUG__", slug)
                .replace("__GAME_TITLE__", title)
                .replace("__KARNI_GAME_SPEC__", spec)
            )
        return out


BLANK_STARTER: Final = Starter(
    name=BLANK,
    title="Blank",
    purpose="The empty start: a small one-tap game, its server side and its tests",
    use_when=("blank", "empty start", "my own game", "from scratch"),
    usually_changed=("everything: the rules in src/rules/, the drawing in src/play.ts",),
    source="built in",
)


@dataclass
class Loaded:
    """Experimental. Every starter, and the problems of those that cannot be used."""

    starters: dict[str, Starter] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def names(self) -> list[str]:
        return sorted(self.starters)

    def require(self, name: str) -> Starter:
        """The starter called ``name``.

        :raises CliError: ``C480``, naming the starters there are, and where a known
            one comes from when its package is not installed.
        """
        found = self.starters.get(name)
        if found is not None:
            return found
        missing = sorted(set(PACKAGES) - set(self.starters))
        where = (
            "; ".join(
                f"{genre} comes with {PACKAGES[genre]} (pip install {PACKAGES[genre]})"
                for genre in missing
            )
            if missing
            else ""
        )
        hint = f" More: {where}." if where else ""
        raise CliError(
            f"There is no starter {name!r} (the genres are: {', '.join(self.names())}).{hint} "
            "karni starters list says what each one is.",
            code="C480",
        )


@dataclass(frozen=True)
class Match:
    """Experimental. A starter ranked for a request: its score and the words that gave it."""

    starter: Starter
    score: int
    matched: tuple[str, ...]


def _entry_points() -> list[EntryPoint]:
    return sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda point: point.name)


def _folder_of(point: EntryPoint) -> Traversable | Path:
    if ":" in point.value:
        loaded = point.load()
        if isinstance(loaded, Path) or hasattr(loaded, "joinpath"):
            return loaded
        raise TypeError(f"{point.value} is not a folder")
    return resources.files(point.value)


def read(folder: Traversable | Path, *, source: str) -> Starter:
    """Experimental. The starter in ``folder``.

    :raises ValueError: naming ``source`` and what is wrong.
    """
    toml = folder.joinpath(STARTER_FILE)
    if not toml.is_file():
        raise ValueError(f"{source}: there is no {STARTER_FILE} in its folder.")
    try:
        data = _StarterToml.model_validate(tomllib.loads(toml.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise ValueError(f"{source}: {STARTER_FILE} is not valid: {exc}") from exc
    if not folder.joinpath(GAME_DIR).is_dir():
        raise ValueError(f"{source}: there is no {GAME_DIR}/ folder of the game's files.")
    return Starter(
        name=data.name,
        title=data.title,
        purpose=data.purpose,
        use_when=tuple(data.use_when),
        usually_changed=tuple(data.usually_changed),
        source=source,
        example=data.example,
        folder=folder,
    )


def load(*, installed: bool = True) -> Loaded:
    """Experimental. The blank start, then every installed starter.

    A starter that cannot be used is left out, and its problem is in
    :attr:`Loaded.problems` (``C482``).
    """
    loaded = Loaded(starters={BLANK: BLANK_STARTER})
    if not installed:
        return loaded
    for point in _entry_points():
        dist = point.dist
        source = f"entry point {point.name}" + (f" ({dist.name} {dist.version})" if dist else "")
        try:
            starter = read(_folder_of(point), source=source)
        except (ImportError, TypeError, ValueError, AttributeError) as exc:
            loaded.problems.append(f"C482: {exc}")
            continue
        if starter.name in loaded.starters:
            loaded.problems.append(
                f"C482: {source}: a starter named {starter.name!r} is there already "
                f"({loaded.starters[starter.name].source}), so this one is left out."
            )
            continue
        loaded.starters[starter.name] = starter
    return loaded


def match(starters: Iterable[Starter], request: str, *, limit: int = 3) -> list[Match]:
    """Experimental. The starters that fit ``request`` best, by the recipes' word overlap.

    Each word of the request scores 4 for a starter's own noun (its name, or a
    use_when phrase of one word), 2 for a word of a use_when phrase and 1 for a
    word of its purpose. Starters scoring 2 or more come back, best first. The
    blank start is the answer when none does.
    """
    from karni_cli import recipes

    asked = recipes.words(request)
    ranked = []
    for starter in starters:
        if starter.name == BLANK:
            continue
        score, matched = recipes.overlap(asked, starter.name, starter.purpose, starter.use_when)
        if score >= recipes.MATCH_THRESHOLD:
            ranked.append(Match(starter, score, matched))
    ranked.sort(key=lambda found: (-found.score, found.starter.name))
    return ranked[:limit]
