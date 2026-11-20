"""Experimental. The parts of a project: the lasting record of each recipe added, and its upgrade.

Each part a project holds has a folder of its own::

    .karni/recipes/<name>/
      karni.yaml     the recipe's spec fragment as it was added (the base of an upgrade)
      record.json    {"version": 1, "recipe": "<name>", "recipe_version": "1.0.0",
                      "source": "built in (booking)",
                      "files": {"bookings/models.py": "<sha256>", ...}}

``record.json`` names every file of the recipe's that ``karni build`` wrote,
with the sha256 of what it wrote. Both files are committed with the project.

:func:`add` merges a recipe into karni.yaml (:func:`karni_cli.recipes.compose.merge`),
keeps its fragment and names it in ``.karni/build.json``, so the next build
writes its files by the stub rule (:mod:`karni_cli.recipes.apply`), migrates
and seeds only its new tables. :func:`remove` is the reverse for the spec and
the record, and deletes the part's files the project never changed: the ones
it changed stay on disk for the project to delete.
:func:`upgrade` replaces each of the part's files the project did not change
(its hash still matches) with the recipe's newer one, writes
``<file>.recipe-<version>`` beside each one it did change, and updates the
spec keys of the part the project left as they were added.

Override / escape hatch: every function takes the project root and returns
what it would write or did, so a tool can run the steps itself; the record is
plain JSON a project may edit.
"""

from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli.builder import layout, record
from karni_cli.project import CliError
from karni_cli.recipes import Loaded, Recipe, apply, compose
from karni_cli.spec import edit, emit
from karni_cli.spec.source import YamlError, load

__all__ = [
    "BASE_FILE",
    "PARTS_DIR",
    "RECORD_FILE",
    "PartRecord",
    "Removed",
    "Upgrade",
    "add",
    "bases",
    "diff_paths",
    "load_record",
    "remove",
    "save_record",
    "spec_text",
    "start",
    "upgrade",
    "write_base",
]

#: Experimental. Where each part's record lives, in the project.
PARTS_DIR: Final = ".karni/recipes"
#: Experimental. The recipe's fragment as it was added.
BASE_FILE: Final = "karni.yaml"
#: Experimental. The part's record: version, source and the hash of each file written.
RECORD_FILE: Final = "record.json"
#: The version of record.json. It moves only for a breaking change.
_RECORD_VERSION: Final = 1


@dataclass
class PartRecord:
    """Experimental. ``.karni/recipes/<name>/record.json``."""

    name: str
    recipe_version: str = ""
    source: str = ""
    files: dict[str, str] = field(default_factory=dict)

    def text(self) -> str:
        data = {
            "version": _RECORD_VERSION,
            "recipe": self.name,
            "recipe_version": self.recipe_version,
            "source": self.source,
            "files": dict(sorted(self.files.items())),
        }
        return json.dumps(data, indent=2) + "\n"


def _folder(root: Path, name: str) -> Path:
    return root / PARTS_DIR / name


def recipe_version(recipe: Recipe) -> str:
    """Experimental. The recipe's ``version``, or karni-cli's for a recipe that has none."""
    if recipe.version:
        return recipe.version
    from karni_cli import __version__

    return str(__version__)


def write_base(root: Path, recipe: Recipe) -> None:
    """Experimental. Keep the recipe's fragment as added: the base of a later upgrade."""
    folder = _folder(root, recipe.name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / BASE_FILE).write_text(recipe.spec(), encoding="utf-8")
    current = load_record(root, recipe.name) or PartRecord(recipe.name)
    current.recipe_version = recipe_version(recipe)
    current.source = recipe.source
    save_record(root, current)


def bases(root: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    """Experimental. The fragment each part was added with, by name (a part without one is left out)."""
    found: dict[str, dict[str, Any]] = {}
    for name in names:
        path = _folder(root, name) / BASE_FILE
        if not path.is_file():
            continue
        try:
            data = load(path.read_text(encoding="utf-8")).data
        except YamlError:
            continue
        if isinstance(data, dict):
            found[name] = data
    return found


def load_record(root: Path, name: str) -> PartRecord | None:
    """Experimental. The part's record, or ``None`` when it has none."""
    path = _folder(root, name) / RECORD_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(
            f"{path.relative_to(root)} cannot be read ({exc}). Restore it from version control.",
            code="C285",
        ) from None
    files = data.get("files") if isinstance(data, dict) else None
    return PartRecord(
        name,
        str(data.get("recipe_version") or ""),
        str(data.get("source") or ""),
        {str(k): str(v) for k, v in (files or {}).items()},
    )


def save_record(root: Path, part: PartRecord) -> None:
    """Experimental. Write the part's record."""
    folder = _folder(root, part.name)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / RECORD_FILE).write_text(part.text(), encoding="utf-8")


def record_files(root: Path, recipe: Recipe, written: Mapping[str, str]) -> None:
    """Experimental. Record the sha256 of each of the recipe's files a build wrote."""
    current = load_record(root, recipe.name) or PartRecord(recipe.name)
    current.recipe_version = current.recipe_version or recipe_version(recipe)
    current.source = current.source or recipe.source
    current.files |= {rel: record.digest(text) for rel, text in written.items()}
    save_record(root, current)


# karni.yaml -----------------------------------------------------------------------


def _at(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for key in path:
        node = node.get(key) if isinstance(node, Mapping) else None
    return node


def _header(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line[1:].strip())
    return lines


def spec_text(text: str, data: dict[str, Any], changed: list[tuple[str, ...]]) -> str:
    """Experimental. karni.yaml's ``text`` with ``data``, keeping the layout where it can.

    Each changed key is set in the text (:func:`karni_cli.spec.edit.set_value`),
    so comments elsewhere stay. When that cannot give ``data`` exactly (a key
    to delete, a layout the editor cannot place a key in), the whole file is
    written again from ``data``, with its header comment kept.
    """
    try:
        before = load(text).data
    except YamlError:
        before = None
    if isinstance(before, dict) and not _deleted(before, data):
        try:
            out = text
            for path in diff_paths(before, data) or changed:
                value = _at(data, path)
                if value is None:
                    raise edit.EditError("a key to delete")
                out = edit.set_value(out, path, copy.deepcopy(value))
            if load(out).data == data:
                return out
        except (edit.EditError, YamlError):
            pass
    return emit.dump(data, header=_header(text))


def _deleted(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """Whether a key of ``before`` is gone from ``after`` (the editor only sets keys)."""
    for key, value in before.items():
        if key not in after:
            return True
        if (
            isinstance(value, Mapping)
            and isinstance(after[key], Mapping)
            and _deleted(value, after[key])
        ):
            return True
    return False


def _spec_data(text: str, file: str) -> dict[str, Any]:
    try:
        data = load(text).data
    except YamlError as exc:
        raise CliError(f"{file} is not valid YAML: {exc.message}.", code="C211") from None
    if not isinstance(data, dict):
        raise CliError(f"{file} is not a mapping.", code="C212")
    return data


def _fragment(recipe: Recipe) -> dict[str, Any]:
    return _spec_data(recipe.spec(), f"the recipe {recipe.name}'s karni.yaml")


def _pending(root: Path, name: str, *, add: bool) -> None:
    rec = record.load(root)
    names = [n for n in rec.recipes if n != name]
    if add:
        names.append(name)
    rec.recipes = names
    path = root / layout.RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rec.text(), encoding="utf-8")


def add(root: Path, spec_file: Path, recipe: Recipe, loaded: Loaded) -> compose.Merged:
    """Experimental. Merge ``recipe`` into the project's karni.yaml and record it (no build).

    :raises CliError: the merge's refusals (``C442`` to ``C447``), before anything is written.
    """
    text = spec_file.read_text(encoding="utf-8")
    data = _spec_data(text, spec_file.name)
    present = compose.installed(data)
    merged = compose.merge(
        data,
        recipe,
        _fragment(recipe),
        bases=bases(root, present),
        parts={name: loaded.recipes[name] for name in present if name in loaded.recipes},
    )
    spec_file.write_text(spec_text(text, merged.data, merged.changed), encoding="utf-8")
    write_base(root, recipe)
    _pending(root, recipe.name, add=True)
    return merged


def diff_paths(before: Any, after: Any, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """Experimental. The keys whose values differ, as deep as both sides are mappings."""
    if isinstance(before, Mapping) and isinstance(after, Mapping) and path != ("pages",):
        found: list[tuple[str, ...]] = []
        for key in after:
            if key not in before:
                found.append((*path, str(key)))
            else:
                found += diff_paths(before[key], after[key], (*path, str(key)))
        return found
    return [] if before == after else [path]


def start(root: Path, spec_file: Path, recipe: Recipe, *, name: str, kind: str) -> compose.Merged:
    """Experimental. A new project's karni.yaml from its first recipe, and the part's record.

    The recipe's text is kept (its comments and layout), with the project's
    name and kind and what the merge adds: ``app.recipes``, ``app.currency``,
    the part's route, money fields in the project's currency.
    """
    from karni_cli.upgrades.v0_6.recipe_list import recipes_key

    blank = {"version": 1, "app": {"name": name, "kind": kind}}
    fragment = _fragment(recipe)
    merged = compose.merge(blank, recipe, fragment)
    text = recipe.spec()
    text = recipes_key(text) or text
    text = edit.set_values(text, [(("app", "name"), name), (("app", "kind"), kind)])
    written = spec_text(text, merged.data, diff_paths(load(text).data, merged.data))
    spec_file.write_text(written, encoding="utf-8")
    write_base(root, recipe)
    _pending(root, recipe.name, add=True)
    return merged


@dataclass
class Removed:
    """Experimental. What ``karni recipes remove`` did with the part's files."""

    #: The part's files the project never changed (their recorded sha256): deleted.
    deleted: list[str] = field(default_factory=list)
    #: The part's files the project changed: kept, for the project to delete or keep.
    kept: list[str] = field(default_factory=list)


def remove(root: Path, spec_file: Path, name: str) -> tuple[compose.Merged, Removed]:
    """Experimental. Take the part ``name`` out of karni.yaml, its record and its files.

    A file of the part's the project never changed (its recorded sha256) is
    deleted: its app is leaving, and its tests would import models that are
    gone. A file the project changed stays, and is listed. Adding the recipe
    again writes the deleted files again.

    :raises CliError: ``C448`` when the project does not hold the part.
    """
    text = spec_file.read_text(encoding="utf-8")
    data = _spec_data(text, spec_file.name)
    base = bases(root, [name]).get(name)
    if base is None:
        from karni_cli import recipes

        found = recipes.load().get(name)
        base = _fragment(found) if found is not None else {}
    merged = compose.unmerge(data, name, base)
    part = load_record(root, name)
    done = Removed()
    for rel, digest in sorted((part.files if part else {}).items()):
        path = root / rel
        if not path.is_file():
            continue
        if record.digest(path.read_text(encoding="utf-8")) == digest:
            path.unlink()
            done.deleted.append(rel)
        else:
            done.kept.append(rel)
    spec_file.write_text(spec_text(text, merged.data, merged.changed), encoding="utf-8")
    shutil.rmtree(_folder(root, name), ignore_errors=True)
    _pending(root, name, add=False)
    return merged, done


@dataclass
class Upgrade:
    """Experimental. What ``karni recipes upgrade`` did for one part."""

    name: str
    old: str
    new: str
    replaced: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    spec_updated: list[str] = field(default_factory=list)
    spec_kept: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"{self.name}: {self.old or 'unrecorded'} -> {self.new}"]
        out += [f"  replaced {rel} (unchanged in the project)" for rel in self.replaced]
        out += [f"  added {rel}" for rel in self.added]
        out += [
            f"  kept {rel}: the project changed it. The recipe's new file is "
            f"{rel}.recipe-{self.new}: merge what you want by hand."
            for rel in self.kept
        ]
        out += [f"  karni.yaml {key}: updated" for key in self.spec_updated]
        out += [
            f"  karni.yaml {key}: kept, the project changed it (compare with "
            f"{PARTS_DIR}/{self.name}/{BASE_FILE})"
            for key in self.spec_kept
        ]
        if len(out) == 1:
            out.append("  nothing to change")
        return out


def _part_keys(fragment: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """The spec keys a part owns: its entities, its own roles and its seed counts."""
    keys: list[tuple[str, ...]] = []
    for label, app in (fragment.get("apps") or {}).items():
        for name in (app or {}).get("entities") or {}:
            keys.append(("apps", str(label), "entities", str(name)))
    for slug in fragment.get("roles") or {}:
        if slug not in compose.FAMILY_ROLES:
            keys.append(("roles", str(slug)))
    return keys


def _as_merged(value: Any) -> Any:
    """A fragment's entity as the merge writes it (money reads the project's currency)."""
    if isinstance(value, Mapping) and isinstance(value.get("fields"), Mapping):
        return {**value, "fields": compose._money(value["fields"])}
    return value


def _set(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = data
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = copy.deepcopy(value)


def upgrade(root: Path, spec_file: Path, recipe: Recipe) -> Upgrade:
    """Experimental. Bring the part ``recipe.name`` to the recipe's current files and fragment.

    :raises CliError: ``C449`` when the project holds no record of the part.
    """
    part = load_record(root, recipe.name)
    base = bases(root, [recipe.name]).get(recipe.name)
    if part is None or base is None:
        raise CliError(
            f"The project holds no record of the recipe {recipe.name} ({PARTS_DIR}/"
            f"{recipe.name}/ is missing), so karni-cli cannot tell its files from the "
            "project's. Fix: compare with karni recipes show "
            f"{recipe.name} --files and copy what you want by hand.",
            code="C449",
        )
    new_version = recipe_version(recipe)
    report = Upgrade(recipe.name, part.recipe_version, new_version)
    for rel, text in apply.contents(recipe).items():
        path = root / rel
        recorded = part.files.get(rel)
        on_disk = path.read_text(encoding="utf-8") if path.is_file() else None
        if on_disk == text:
            part.files[rel] = record.digest(text)
            continue
        if on_disk is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            part.files[rel] = record.digest(text)
            report.added.append(rel)
        elif recorded is not None and record.digest(on_disk) == recorded:
            path.write_text(text, encoding="utf-8")
            part.files[rel] = record.digest(text)
            report.replaced.append(rel)
        else:
            (root / f"{rel}.recipe-{new_version}").write_text(text, encoding="utf-8")
            report.kept.append(rel)
    text = spec_file.read_text(encoding="utf-8")
    data = _spec_data(text, spec_file.name)
    fresh = _fragment(recipe)
    changed: list[tuple[str, ...]] = []
    for key in _part_keys(fresh):
        new_value = _as_merged(_at(fresh, key))
        old_value = _as_merged(_at(base, key))
        mine = _at(data, key)
        if new_value == old_value or mine == new_value:
            continue
        shown = ".".join(key)
        if (mine is None and old_value is None) or mine == old_value:
            _set(data, key, new_value)
            changed.append(key)
            report.spec_updated.append(shown)
        else:
            report.spec_kept.append(shown)
    if changed:
        spec_file.write_text(spec_text(text, data, changed), encoding="utf-8")
    part.recipe_version = new_version
    part.source = recipe.source
    save_record(root, part)
    folder = _folder(root, recipe.name)
    (folder / BASE_FILE).write_text(recipe.spec(), encoding="utf-8")
    return report
