"""Experimental. Recipes: ready-made app specs that a new app starts from.

A recipe is a folder::

    <name>/
      recipe.toml   what it is: name, title, purpose, use_when, usually_changed
      karni.yaml    the spec, with app.recipe naming the recipe
      files/        optional: the recipe's own domain code, seeds and tests, each at the
                    path it takes in the project (files/shop/models.py is shop/models.py)

:class:`RecipeToml` is the format of ``recipe.toml`` (published as
``docs/assets/karni-recipe.schema.json``, regenerate it with
``python -m karni_cli.recipes > docs/assets/karni-recipe.schema.json``).

Where recipes come from, in this order:

1. **Built in**: the folders next to this file (``karni_cli/recipes/<name>/``),
   package data of karni-cli.
2. **Installed**: the ``karni.recipes`` entry point group of the environment
   karni-cli runs in. The entry point's name is the recipe's name, and its
   value is the package that is the recipe's folder::

       [project.entry-points."karni.recipes"]
       helpdesk = "acme_recipes.helpdesk"

   A built-in recipe wins over an installed one of the same name, and the
   other one is reported.

``blank`` is not a recipe. It names the **blank start**, where an app starts
when no recipe fits: a spec with the version and the app's name, nothing
else (:func:`blank_spec`).

:func:`match` ranks the recipes for a one-line request by plain word overlap
with each recipe's ``use_when`` and ``purpose``. No language model is
involved, and the same request gives the same ranking.

Override / escape hatch: a recipe of your own is a folder and an entry point,
and :func:`load` takes the folders to read for a tool (or a test) that
supplies its own.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import EntryPoint, entry_points
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

__all__ = [
    "BLANK",
    "ENTRY_POINT_GROUP",
    "FILES_DIR",
    "MATCH_LIMIT",
    "MATCH_THRESHOLD",
    "NAME",
    "PURPOSE_MAX",
    "RECIPE_FILE",
    "RECIPE_SCHEMA_URL",
    "SPEC_FILE",
    "STOPWORDS",
    "Loaded",
    "Match",
    "Recipe",
    "RecipeError",
    "RecipeToml",
    "app_name",
    "blank_spec",
    "builtin_root",
    "json_schema",
    "karni_owned",
    "load",
    "match",
    "parse",
    "read_folder",
    "words",
]

#: Experimental. The entry point group third-party recipes are found in.
ENTRY_POINT_GROUP: Final = "karni.recipes"
#: Experimental. The file that says what a recipe is.
RECIPE_FILE: Final = "recipe.toml"
#: Experimental. The recipe's spec.
SPEC_FILE: Final = "karni.yaml"
#: Experimental. The folder of the recipe's own files, at their paths in the project.
FILES_DIR: Final = "files"
#: Experimental. The name of the blank start. No recipe takes it.
BLANK: Final = "blank"
#: Experimental. How many recipes :func:`match` returns at most.
MATCH_LIMIT: Final = 3
#: Experimental. The lowest score :func:`match` returns: one word of a ``use_when`` phrase,
#: or two words of the purpose.
MATCH_THRESHOLD: Final = 2
#: Experimental. Where the JSON Schema of ``recipe.toml`` is published.
RECIPE_SCHEMA_URL: Final = (
    "https://cbsshekhawat18-lab.github.io/karni/assets/karni-recipe.schema.json"
)
#: Experimental. The longest purpose, as for a module's manifest.
PURPOSE_MAX: Final = 80
#: Experimental. What a recipe's name looks like.
NAME: Final = r"^[a-z][a-z0-9_-]*$"

_STOPWORDS_TEXT: Final = """
    a about all an and any app application apps are as at be build built but by can could
    create do for from get has have help i in into is it its just let like make me my need
    new of on one or our please run should simple small so some something that the their
    them then there these this to tool up us use want we what where which who will with
    would you your
"""
#: Experimental. Words that say nothing about which app is meant. They never count in
#: :func:`match`.
STOPWORDS: Final = frozenset(_STOPWORDS_TEXT.split())

_WORD: Final = re.compile(r"[a-z0-9]+")
_Line = Annotated[str, StringConstraints(min_length=1, pattern=r"^[^\n]+$")]


class RecipeError(ValueError):
    """Experimental. A recipe that cannot be used: the message names the folder and each problem."""


class RecipeToml(BaseModel):
    """Experimental. ``recipe.toml``: what a recipe is, and when to start from it."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(
        pattern=NAME,
        description="The recipe's name: its folder's name, or its entry point's. Lowercase "
        "letters, digits, - and _. blank is taken by the blank start.",
    )
    title: _Line = Field(description="A short human name, e.g. Online shop.")
    purpose: Annotated[_Line, StringConstraints(max_length=PURPOSE_MAX)] = Field(
        description=f"What the app does, in one line of at most {PURPOSE_MAX} characters."
    )
    use_when: list[_Line] = Field(
        min_length=1,
        description="Plain phrases of what someone asks for when this recipe fits, e.g. "
        '["online shop", "sell products", "checkout"]. karni recipes list --match ranks '
        "recipes by the words a request shares with them.",
    )
    usually_changed: list[_Line] = Field(
        default_factory=list,
        description="What people usually change in the spec after starting from it, in plain "
        'words, e.g. ["the product fields", "the currency"].',
    )


def json_schema() -> dict[str, Any]:
    """Experimental. The JSON Schema of ``recipe.toml``, as published at :data:`RECIPE_SCHEMA_URL`."""
    from karni_cli.spec.schema import _tidy

    body = _tidy(RecipeToml.model_json_schema())
    body.pop("description", None)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": RECIPE_SCHEMA_URL,
        "title": "recipe.toml",
        "description": (
            "Experimental. What a Karni recipe is: a ready-made karni.yaml and when to start "
            "from it. Generated by python -m karni_cli.recipes. Never edit it by hand."
        ),
        **body,
    }


@dataclass(frozen=True)
class Recipe:
    """Experimental. One recipe: its ``recipe.toml``, where it came from, and its files."""

    name: str
    title: str
    purpose: str
    use_when: tuple[str, ...]
    usually_changed: tuple[str, ...]
    #: ``built in``, or ``entry point <name> (<distribution> <version>)``.
    source: str
    folder: Traversable = field(repr=False)
    #: The recipe's own files under ``files/``, as the paths they take in the project.
    files: tuple[str, ...] = ()

    def spec(self) -> str:
        """Experimental. The recipe's ``karni.yaml``, as written."""
        return self.folder.joinpath(SPEC_FILE).read_text(encoding="utf-8")

    def to_dict(self, *, spec: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "purpose": self.purpose,
            "use_when": list(self.use_when),
            "usually_changed": list(self.usually_changed),
            "source": self.source,
            "files": list(self.files),
            "spec": self.spec() if spec else None,
        }


@dataclass
class Loaded:
    """Experimental. Every recipe found, by name, and the problems of those left out."""

    recipes: dict[str, Recipe] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    #: The recipes left out because they cannot be used, by name, with the problem.
    broken: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> Recipe | None:
        return self.recipes.get(name)

    def require(self, name: str) -> Recipe | None:
        """Experimental. The recipe ``name`` (``None`` for the blank start).

        :raises CliError: ``C421`` when it is there but cannot be used, ``C420``
            when there is none of that name (naming the closest names).
        """
        from karni_cli.project import CliError

        if name == BLANK:
            return None
        recipe = self.recipes.get(name)
        if recipe is not None:
            return recipe
        if name in self.broken:
            raise CliError(f"The recipe {name!r} cannot be used: {self.broken[name]}", code="C421")
        names = [*sorted(self.recipes), BLANK]
        closest = difflib.get_close_matches(name, names, n=MATCH_LIMIT)
        near = (
            f": the closest {'is' if len(closest) == 1 else 'are'} {', '.join(closest)}"
            if closest
            else ""
        )
        raise CliError(
            f"There is no recipe {name!r}{near} (there are: {', '.join(names)}).", code="C420"
        )


@dataclass(frozen=True)
class Match:
    """Experimental. A recipe ranked for a request: its score and the words that gave it."""

    recipe: Recipe
    score: int
    matched: tuple[str, ...]


# reading ----------------------------------------------------------------------------


def parse(text: str, source: str) -> RecipeToml:
    """Experimental. ``recipe.toml``'s text checked against :class:`RecipeToml`.

    :raises RecipeError: naming ``source`` and every problem, each with its key.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RecipeError(f"{source}: {RECIPE_FILE} is not TOML ({exc}).") from None
    try:
        found = RecipeToml.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(top)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise RecipeError(f"{source}: {RECIPE_FILE}: {problems}.") from None
    if found.name == BLANK:
        raise RecipeError(f"{source}: name: {BLANK!r} is the blank start, not a recipe name.")
    return found


def _files(folder: Traversable) -> tuple[str, ...]:
    root = folder.joinpath(FILES_DIR)
    if not root.is_dir():
        return ()
    found: list[str] = []

    def walk(node: Traversable, prefix: str) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            if child.name == "__pycache__" or child.name.startswith("."):
                continue
            rel = f"{prefix}{child.name}"
            if child.is_dir():
                walk(child, rel + "/")
            else:
                found.append(rel)

    walk(root, "")
    return tuple(found)


#: Paths of a project that karni build writes itself, so no recipe file may take them.
_BUILD_FILES: Final = frozenset(
    {SPEC_FILE, ".karni/build.json", "config/settings.py", "frontend/src/routes.tsx"}
)


def karni_owned(rel: str) -> bool:
    """Experimental. Whether ``karni build`` owns the project path ``rel`` (so a recipe file cannot).

    ``<app>/karni/``, ``<app>/tests/karni/``, ``frontend/src/pages/karni/``,
    ``.karni/``, karni.yaml, and the files with a ``karni:spec`` block.
    """
    parts = rel.split("/")
    return (
        rel in _BUILD_FILES
        or parts[0] == ".karni"
        or (len(parts) > 2 and parts[1] == "karni")
        or (len(parts) > 3 and parts[1:3] == ["tests", "karni"])
        or rel.startswith("frontend/src/pages/karni/")
    )


def read_folder(folder: Traversable, *, name: str, source: str) -> Recipe:
    """Experimental. The recipe in ``folder``, whose name must be ``name``.

    :raises RecipeError: for a missing or invalid ``recipe.toml``, a name that
        is not ``name``, a missing ``karni.yaml``, or a file at a path karni build
        owns (:func:`karni_owned`).
    """
    manifest = folder.joinpath(RECIPE_FILE)
    if not manifest.is_file():
        raise RecipeError(f"{source}: no {RECIPE_FILE}.")
    found = parse(manifest.read_text(encoding="utf-8"), source)
    if found.name != name:
        raise RecipeError(
            f"{source}: name: {found.name!r} is not {name!r}, the name it is found under."
        )
    if not folder.joinpath(SPEC_FILE).is_file():
        raise RecipeError(f"{source}: no {SPEC_FILE}.")
    files = _files(folder)
    owned = [rel for rel in files if karni_owned(rel)]
    if owned:
        raise RecipeError(
            f"{source}: {FILES_DIR}/{owned[0]}: karni build writes {owned[0]} itself. A recipe's "
            "files go where the project owns the code: <app>/models.py, viewsets.py, seeds.py "
            "and tests of its own."
        )
    return Recipe(
        name=found.name,
        title=found.title,
        purpose=found.purpose,
        use_when=tuple(found.use_when),
        usually_changed=tuple(found.usually_changed),
        source=source,
        folder=folder,
        files=files,
    )


def builtin_root() -> Traversable:
    """Experimental. Where the built-in recipes are: the folders of this package."""
    return resources.files(__name__)


def _builtin(root: Traversable) -> Iterable[tuple[str, Traversable, str]]:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.is_dir() and child.joinpath(RECIPE_FILE).is_file():
            yield child.name, child, f"built in ({child.name})"


def _entry_points() -> list[EntryPoint]:
    return sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda point: point.name)


def _installed(problems: list[str]) -> Iterable[tuple[str, Traversable, str]]:
    for point in _entry_points():
        dist = point.dist
        source = f"entry point {point.name}" + (f" ({dist.name} {dist.version})" if dist else "")
        try:
            folder = resources.files(point.value)
        except (ImportError, TypeError, ValueError) as exc:
            problems.append(f"{source}: {point.value!r} cannot be read ({exc}).")
            continue
        yield point.name, folder, source


def load(builtin: Traversable | Path | None = None, *, installed: bool = True) -> Loaded:
    """Experimental. Every recipe: the built-in ones, then the installed ones.

    ``builtin`` replaces the folder of built-in recipes, and ``installed=False``
    leaves the entry points out. A recipe that cannot be used is left out, and
    its problem is in :attr:`Loaded.problems`.
    """
    loaded = Loaded()
    sources = list(_builtin(builtin_root() if builtin is None else builtin))
    if installed:
        sources += list(_installed(loaded.problems))
    for name, folder, source in sources:
        if name in loaded.recipes:
            loaded.problems.append(
                f"{source}: a recipe named {name!r} is there already "
                f"({loaded.recipes[name].source}), so this one is left out."
            )
            continue
        try:
            loaded.recipes[name] = read_folder(folder, name=name, source=source)
        except RecipeError as exc:
            loaded.problems.append(str(exc))
            loaded.broken.setdefault(name, str(exc))
    return loaded


# the blank start --------------------------------------------------------------------


def app_name(project: Path | None) -> str:
    """Experimental. The app's name for the blank start: the project's, else this folder's."""
    if project is None:
        return Path.cwd().resolve().name
    from karni_cli.spec.export import _project_name

    return _project_name(project)


def blank_spec(app_name: str) -> str:
    """Experimental. The blank start: a spec with the version and the app's name, nothing else."""
    from karni_cli.spec import emit, schema

    header = [f"yaml-language-server: $schema={schema.SCHEMA_URL}"]
    return emit.dump({"version": 1, "app": {"name": app_name}}, header=header)


# matching ---------------------------------------------------------------------------


def _stem(word: str) -> str:
    """The singular of a plural, by the plain English rules (bookings: booking)."""
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("zzes"):
        return word[:-3]
    if word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """Experimental. The words of ``text`` :func:`match` compares, in order, each once.

    Lowercase, letters and digits only, the plural made singular, and the
    :data:`STOPWORDS` left out.
    """
    found: list[str] = []
    for raw in _WORD.findall(text.lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        word = _stem(raw)
        if word not in found:
            found.append(word)
    return found


def match(
    recipes: Iterable[Recipe],
    request: str,
    *,
    limit: int = MATCH_LIMIT,
    threshold: int = MATCH_THRESHOLD,
) -> list[Match]:
    """Experimental. The recipes that fit ``request`` best, by plain word overlap.

    Each word of the request scores 2 when a ``use_when`` phrase of the recipe
    has it, else 1 when its purpose has it. Recipes scoring at least
    ``threshold`` come back, the highest first (then by name), at most
    ``limit`` of them. An empty list means none fits: start from the blank
    start.
    """
    asked = words(request)
    ranked: list[Match] = []
    for recipe in recipes:
        wanted = {word for phrase in recipe.use_when for word in words(phrase)}
        described = set(words(recipe.purpose))
        score, matched = 0, []
        for word in asked:
            if word in wanted:
                score += 2
            elif word in described:
                score += 1
            else:
                continue
            matched.append(word)
        if score >= threshold:
            ranked.append(Match(recipe, score, tuple(matched)))
    ranked.sort(key=lambda found: (-found.score, found.recipe.name))
    return ranked[:limit]
