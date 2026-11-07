"""Experimental. The build: ``karni plan``'s changes applied, idempotently, in a fixed order.

1. **The plan.** The spec is validated and planned exactly as ``karni plan``
   does (:func:`karni_cli.spec.plan.plan_project`), with what
   ``.karni/build.json`` says Karni manages. The plan's changes decide
   everything that follows: the modules to add, the entities renamed,
   created and removed, the tables to seed. The files are the spec rendered
   (:mod:`karni_cli.builder.render`), so a rebuild gives the same bytes.
2. **The guard.** Nothing is written when the plan asks for what build does
   not do: a model the project wrote by hand in the way (``C275``), a key
   type switch (``C272``), a module removal (``C271``, ``karni remove`` comes
   with the module catalog), or a risky change without
   ``--allow-destructive`` (``C270``, each named with its rows).
3. **The ownership check.** Every Karni-owned file and block is compared with
   its recorded sha256. One edited by hand stops the build (``C273``), with
   its changed lines and three ways on: move the change into the project's
   file, ``--force`` (a ``.orig`` backup is kept), or ``--adopt <file>``.
4. **The steps.** ``modules`` (``karni add``), ``files`` (after ``karni new
   --recipe``, the recipe's own files over build's stubs, by the stub rule of
   :mod:`karni_cli.recipes.apply`), ``migrations``
   (``manage.py karni_makemigrations``: renames first), ``migrate``, ``seed``
   (only tables this build created that the spec's ``seed`` counts, only while
   empty), ``types``, ``test``
   and ``check``. The first failure stops the build with its code, what was
   done and what to do next. The steps not run yet are remembered on this
   machine, so the next ``karni build`` continues from there.

A build with nothing to write and nothing left to run writes nothing and
says so in one line.

Override / escape hatch: :data:`STEP_RUNNERS` maps each step after the files
to its function, so a tool (or a test) can replace one.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from karni_cli import project as project_mod
from karni_cli.builder import layout, output, record, render
from karni_cli.builder.record import HandEdit, Record
from karni_cli.generators.core import Workspace
from karni_cli.project import CliError
from karni_cli.spec import plan as plan_mod
from karni_cli.spec import schema
from karni_cli.spec.normal import normalise

__all__ = ["STEP_RUNNERS", "Options", "Result", "Step", "build"]

#: The lines of a failed step's output a build shows.
_TAIL: Final = 15


@dataclass(frozen=True)
class Options:
    """Experimental. ``karni build``'s options."""

    dry_run: bool = False
    allow_destructive: bool = False
    force: bool = False
    adopt: tuple[str, ...] = ()
    docker: bool | None = None
    service: str = "django"


@dataclass
class Step:
    """Experimental. One step and how it went."""

    name: str
    status: str = "pending"
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "summary": self.summary}


@dataclass
class Result:
    """Experimental. What a build did (its text and ``--json`` output)."""

    file: str
    status: str = "built"
    issues: list[dict[str, Any]] = field(default_factory=list)
    plan: plan_mod.Plan | None = None
    code: str | None = None
    message: str | None = None
    files: list[dict[str, str]] = field(default_factory=list)
    hand_edits: list[HandEdit] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=lambda: [Step(name) for name in output.STEPS])
    next: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in ("built", "nothing to build", "dry run")

    def step(self, name: str) -> Step:
        return next(step for step in self.steps if step.name == name)

    def as_dict(self) -> dict[str, Any]:
        return output.checked(
            {
                "version": output.BUILD_VERSION,
                "file": self.file,
                "valid": self.status != "invalid",
                "issues": self.issues,
                "status": self.status,
                "code": self.code,
                "message": self.message,
                "plan": plan_mod.checked_output(self.plan.as_dict()) if self.plan else None,
                "files": self.files,
                "hand_edits": [
                    {
                        "path": edit.name,
                        "lines": list(edit.lines),
                        "diff": list(edit.diff),
                        "unrecorded": edit.unrecorded,
                    }
                    for edit in self.hand_edits
                ],
                "adopted": self.adopted,
                "steps": [step.as_dict() for step in self.steps],
                "next": self.next,
            }
        )

    def text(self, verbose: bool = False) -> str:
        """The terminal output: the plan, a line per step, how it ended.

        The plan is one line, with each risky change under it: ``verbose``
        (and a dry run) prints every change, as ``karni plan`` does.
        """
        lines: list[str] = []
        if self.status == "nothing to build":
            lines.append(self.message or f"Nothing to build: the project matches {self.file}.")
            lines += self._adopted_lines()
            return "\n".join(lines) + "\n"
        width = max(len(name) for name in output.STEPS)
        if self.plan is not None and self.plan.changes:
            if verbose or self.status == "dry run":
                lines += self.plan.text().rstrip("\n").splitlines()
            else:
                lines.append(f"{'plan':<{width}}  {self.plan.brief()} (--verbose lists each)")
                lines += [change.line() for change in self.plan.risky]
        for edit in self.hand_edits:
            lines.append(f"{edit.name}: edited by hand ({edit.shown_lines()})")
            lines += [f"    {row}" for row in edit.diff]
        if self.status == "dry run":
            lines += [f"would {f['action']} {f['path']} ({f['owner']})" for f in self.files]
            lines.append("(dry run: nothing written)")
            return "\n".join(lines) + "\n"
        for step in self.steps:
            if step.status == "pending" and self.status in ("refused", "invalid"):
                continue
            mark = {"failed": "FAILED", "skipped": "skipped", "pending": "not run"}.get(
                step.status, ""
            )
            summary = step.summary if step.status != "failed" else step.summary.splitlines()[0]
            lines.append(f"{step.name:<{width}}  {' '.join(p for p in (mark, summary) if p)}")
            if step.status == "failed":
                lines += [f"    {row}" for row in step.summary.splitlines()[1:]]
        lines += self._adopted_lines()
        if self.code:
            lines.append(f"error {self.code}: {self.message}")
        elif self.status == "built":
            lines.append(self.message or f"Built: the project matches {self.file}.")
        if self.next:
            lines.append(f"next: {self.next}")
        return "\n".join(lines) + "\n"

    def _adopted_lines(self) -> list[str]:
        if not self.adopted:
            return []
        return [f"adopted (the project's now, karni build leaves it): {', '.join(self.adopted)}"]


class Stop(Exception):
    """A step (or the guard) stopping the build with a code, a message and what to do next."""

    def __init__(self, code: str, message: str, next_: str | None = None, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next = next_
        self.detail = detail


# the build ------------------------------------------------------------------------


def build(root: Path, spec: schema.Spec, facts: dict[str, Any], file: str, opts: Options) -> Result:
    """Experimental. Build ``spec`` into the project at ``root`` (the spec is valid)."""
    result = Result(file)
    try:
        rec = record.load(root)
        adopted_now = _adopt(root, rec, opts.adopt)
    except CliError as exc:
        return _refused(result, Stop(exc.code or "C274", exc.message))
    pending = record.pending(root)
    plan = plan_mod.plan_project(spec, facts, root, file=file, managed=rec.managed())
    counter = plan_mod.manage_counter(root, docker=opts.docker, service=opts.service)
    plan_mod.apply_counts(plan, counter)
    result.plan = plan
    result.adopted = sorted(rec.adopted)
    try:
        _guard(plan, opts)
        inputs, created = _inputs(spec, facts, plan, rec)
        ws = Workspace(root)
        module_lines = _plan_modules(ws, plan)
        _plan_extras(ws, feature_extras(spec))
        rendered = render.render(ws, inputs)
        _recipe_files(ws, rec)
        deletes = _deletions(root, rec, rendered)
        edits = _hand_edits(root, rec, rendered, deletes)
    except Stop as stop:
        return _refused(result, stop)
    except CliError as exc:
        return _refused(result, Stop(exc.code or "C275", exc.message))
    result.hand_edits = edits
    if edits and not opts.force:
        first = edits[0]
        return _refused(
            result,
            Stop(
                "C273",
                f"{_names(edits)} {'was' if len(edits) == 1 else 'were'} edited by hand, so "
                "karni build wrote nothing.",
                _ways_on(first),
            ),
        )
    try:
        _guard_risky(plan, opts)
    except Stop as stop:
        return _refused(result, stop)
    changes = ws.changes()
    result.files = _files(ws, changes, deletes, rendered)
    if opts.dry_run:
        result.status = "dry run"
        return result
    new_record = _record(spec, plan, rec, rendered, inputs)
    if not changes and not deletes and not pending:
        if new_record.text() != _record_text(root):
            _save_record(root, new_record)
        result.status = "nothing to build"
        for step in result.steps:
            step.status, step.summary = "skipped", "nothing to do"
        left = len(plan.not_managed)
        result.message = (
            f"Nothing to build: the project matches {file}."
            if not plan.changes
            else f"Nothing to build: karni plan's {left} change{'s are' if left != 1 else ' is'} "
            f"in the project's own code (karni plan marks {'them' if left != 1 else 'it'} "
            "not managed)."
        )
        if adopted_now:
            result.message += f" Adopted {', '.join(adopted_now)}."
        return result
    # write: backups first, then every file, then the record
    for edit in edits:
        _backup(root, edit)
    for path, _before, after in changes:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    for rel in deletes:
        with contextlib.suppress(FileNotFoundError):
            (root / rel).unlink()
    _save_record(root, new_record)
    if changes or deletes:
        state = _merge(pending, _state(plan, inputs, created, facts, module_lines))
    else:
        state = pending
    record.save_pending(root, state)
    result = _steps(root, result, state, opts, written=bool(changes or deletes))
    unwritten = _recipe_not_written(rec, spec)
    if unwritten and result.status == "built":
        base = result.message or f"Built: the project matches {file}."
        result.message = f"{base} {unwritten}"
    return result


def _refused(result: Result, stop: Stop) -> Result:
    result.status = "refused"
    result.code, result.message, result.next = stop.code, stop.message, stop.next
    return result


def _names(edits: list[HandEdit]) -> str:
    return ", ".join(edit.name for edit in edits)


def _ways_on(edit: HandEdit) -> str:
    where = _move_to(edit.name)
    return (
        f"three ways on: 1. move the change into {where}, then karni build. "
        f"2. karni build --force replaces it (your copy is kept as {_backup_name(edit.name)}). "
        f"3. karni build --adopt {edit.name.split(' ')[0]} makes it the project's: karni build "
        "stops managing it."
    )


def _move_to(name: str) -> str:
    """Where the change to a Karni-owned file belongs instead."""
    parts = name.split("/")
    if name == layout.SETTINGS_BLOCK:
        return "karni.yaml (roles, features, module options), or settings.py outside the block"
    if name in layout.ROUTES_BLOCKS:
        return "karni.yaml's pages, or a route of your own outside the block"
    if "/karni/models.py" in name:
        return f"{parts[0]}/models.py (the subclass of each class), or karni.yaml"
    if "/karni/api.py" in name:
        return f"{parts[0]}/viewsets.py (the subclass of each viewset), or karni.yaml"
    if "/karni/seeds.py" in name:
        return f"{parts[0]}/seeds.py (the subclass of each seeder), or karni.yaml's seed"
    if "/tests/karni/" in name:
        return f"a test of your own in {parts[0]}/tests/"
    if "/pages/karni/" in name:
        return "a page of your own in frontend/src/pages/ (and kind code in karni.yaml's pages)"
    return "a file of your own"


# the guard ------------------------------------------------------------------------


def _guard(plan: plan_mod.Plan, opts: Options) -> None:
    for change in plan.changes:
        if change.area == "entities" and change.action == "add" and not change.managed:
            raise Stop(
                "C275",
                f"karni.yaml adds {change.target}, and {change.reason}.",
                "rename the entity in karni.yaml, or remove the project's model (karni spec "
                "export shows how the spec sees the project)",
            )
    switched = [c for c in plan.changes if c.area == "entities" and c.target.endswith(" pk")]
    for change in switched:
        if change.risky:
            raise Stop(
                "C272",
                f"karni.yaml switches the key type of {change.target.split(' ')[0]} "
                f"({change.detail}). Switching it on a table with rows is a data migration "
                "karni build does not write.",
                "put pk back in karni.yaml (docs/models.md#choosing-the-key-type explains the "
                "migration to write by hand)",
            )
    removed = [c for c in plan.changes if c.area == "modules" and c.action == "remove"]
    if removed:
        names = ", ".join(c.target for c in removed)
        raise Stop(
            "C271",
            f"karni.yaml no longer lists the module{'s' if len(removed) > 1 else ''} {names}, and "
            "karni build does not remove modules (karni remove comes with the module catalog).",
            "put the module back in karni.yaml, or remove it by hand: its app from the karni:apps "
            "block, its dependency from pyproject.toml, then migrate it to zero first",
        )


def _guard_risky(plan: plan_mod.Plan, opts: Options) -> None:
    """``C270``: after the hand-edit check, whose cause comes first."""
    risky = [c for c in plan.risky if c.managed]
    if risky and not opts.allow_destructive:
        shown = " / ".join(change.line().strip().lstrip("! ") for change in risky)
        raise Stop(
            "C270",
            f"{len(risky)} risky change{'s' if len(risky) != 1 else ''}: {shown}.",
            "check each one (karni plan shows the rows), then karni build --allow-destructive, "
            "or change karni.yaml (a rename keeps its rows with was:)",
        )


# what Karni manages after this build ---------------------------------------------


def _inputs(
    spec: schema.Spec, facts: dict[str, Any], plan: plan_mod.Plan, rec: Record
) -> tuple[render.Inputs, list[str]]:
    """The render's inputs, and the tables this build creates (to seed)."""
    pk = str(facts["settings"].get("KARNI_PK") or "uuid")
    managed = set(rec.entities)
    renames = {
        new: old for new, old in plan.entity_renames.items() if old in managed or new in managed
    }
    for new, old in renames.items():
        managed.discard(old)
        managed.add(new)
    created: list[str] = []
    removed: set[str] = set()
    for change in plan.changes:
        if change.area != "entities" or not change.managed:
            continue
        if change.action == "add":
            managed.add(change.target)
            created.append(change.target)
        elif change.action == "remove":
            managed.discard(change.target)
            removed.add(change.target)
    pages = _pages(spec, plan, rec, renames)
    inputs = render.Inputs(
        spec=spec,
        pk=pk,
        entities=managed,
        pages=pages,
        adopted=set(rec.adopted),
        renames=renames,
        removed=removed,
    )
    return inputs, created


def _pages(
    spec: schema.Spec, plan: plan_mod.Plan, rec: Record, renames: dict[str, str]
) -> set[str]:
    """The pages Karni writes: those it wrote before, and every spec page the project lacks."""
    back = {old: new for new, old in renames.items()}
    owned: set[str] = set()
    for key in rec.pages:
        page, _, kind = key.rpartition(":")
        owned.add(f"{back.get(page, page)}:{kind}")
    labels = {
        name: f"{app}.{name}"
        for app, application in spec.apps.items()
        for name in application.entities
    }
    current_names = {
        name: f"{app}.{name}"
        for app, application in plan.current.get("apps", {}).items()
        for name in application["entities"]
    }

    def ident(name: str, names: dict[str, str]) -> str:
        if not name[:1].isupper():
            return name
        return name if "." in name else names.get(name, name)

    theirs = set()
    for entry in plan.current.get("pages", []):
        for name, kinds in entry.items():
            label = ident(name, current_names)
            label = back.get(label, label)
            theirs |= {f"{label}:{kind}" for kind in schema.page_kind_names(kinds)}
    theirs -= owned
    found = set()
    for entry in spec.pages:
        for name, kinds in entry.items():
            for kind in schema.page_kind_names(kinds):
                key = f"{ident(name, labels)}:{kind}"
                # The scaffold's home page is the project's. Any other dashboard is built.
                if kind == "code" or (kind == "dashboard" and name == "home") or key in theirs:
                    continue
                found.add(key)
    return found


def _plan_modules(ws: Workspace, plan: plan_mod.Plan) -> list[str]:
    from karni_cli.commands.add import plan_module

    lines: list[str] = []
    for change in plan.changes:
        if change.area == "modules" and change.action == "add":
            plan_module(ws, change.target)
            _plan_module_urls(ws, change.target)
            lines.append(change.target)
    return lines


#: The import that shows a Karni extra is installed. Only features with an ``extra`` in
#: their manifest need one.
EXTRA_IMPORTS: dict[str, str] = {"2fa": "django_otp", "social-token": "cryptography"}


def feature_extras(spec: schema.Spec) -> list[str]:
    """The extras of ``karni`` the spec's switched-on features need (``2fa``, ``social-token``)."""
    from karni_cli import catalog as modules_catalog

    found: list[str] = []
    for entry in modules_catalog.load().features:
        extra = getattr(entry, "extra", "") or ""
        if "[" not in extra or not getattr(spec.features, entry.name, None):
            continue
        name = extra.split("[", 1)[1].rstrip("]")
        if name not in found:
            found.append(name)
    return sorted(found)


def _plan_extras(ws: Workspace, extras: list[str]) -> None:
    """Name each extra a feature needs on the ``karni`` dependency, as ``karni add`` does a module."""
    from karni_cli.commands.add import add_extra_text

    for extra in extras:
        text = ws.read("pyproject.toml")
        updated = add_extra_text(text, extra) if text is not None else None
        if updated is not None:
            ws.write("pyproject.toml", updated)


def _recipe_files(ws: Workspace, rec: Record) -> list[str]:
    """The recipe's own files over build's stubs, when ``karni new --recipe`` left one to write."""
    name = rec.recipe
    if not name:
        return []
    from karni_cli import recipes
    from karni_cli.recipes import apply

    try:
        recipe = recipes.load().require(name)
    except CliError as exc:
        raise CliError(
            f"{layout.RECORD} or the spec names the recipe {name!r}, whose own files this build writes "
            f'over its stubs: {exc.message} Install it, or delete "{apply.RECORD_KEY}" from '
            f"{layout.RECORD} to build without them.",
            code=exc.code,
        ) from None
    return apply.stage(ws, recipe) if recipe is not None else []


def _recipe_not_written(rec: Record, spec: schema.Spec) -> str:
    """Say so when the spec names a recipe whose domain code this build did not write.

    Only ``karni new --recipe`` writes a recipe's own models, viewsets, seeds and tests. A
    karni.yaml started from a recipe in an existing project (the /new-app flow) names it in
    ``app.recipe`` and gets the spec alone.
    """
    from karni_cli import recipes

    name = spec.app.recipe
    if not name or rec.recipe or rec.entities or name not in recipes.load().recipes:
        return ""
    return (
        f"The recipe {name}'s own code (its model methods, actions, seeders and tests) was not "
        f"written: only karni new --recipe {name} writes it. karni recipes show {name} --files "
        "prints it to copy from."
    )


def _plan_module_urls(ws: Workspace, module: str) -> None:
    """The module's URL include (its manifest's ``wiring.urls``) at config/urls.py's marker.

    ``karni add`` prints the line for you to place. A build places it, so the
    code it generates (a protected file's download path, a webhook) works at
    once. ``karni remove`` takes it out again. A config/urls.py without the
    ``# karni:urls`` marker is left alone.
    """
    from karni_cli.commands.add import find_manifest
    from karni_cli.generators.pysource import Import, ensure_imports
    from karni_cli.urls_edit import add_route, has_marker, routes

    manifest, _loaded = find_manifest(ws.root, module)
    entry = manifest.wiring.urls if manifest is not None else ""
    text = ws.read(_URLS)
    if not entry or text is None or not has_marker(text):
        return
    included = re.search(r"""include\(\s*["']([^"']+)["']""", entry)
    if included and any(found == included.group(1) for _r, _n, found in routes(text)):
        return
    text = ensure_imports(ws, _URLS, text, [Import("django.urls", "include")])
    added = add_route(text, f"{entry},", filename=_URLS, manual="")
    if added is not None:
        ws.write(_URLS, added)


#: The project's root URLconf, where a module's include goes.
_URLS: Final = "config/urls.py"


def _deletions(root: Path, rec: Record, rendered: render.Output) -> list[str]:
    """Karni-owned files the record lists that this build no longer writes."""
    return sorted(
        rel
        for rel in rec.files
        if rel not in rendered.files and rel not in rec.adopted and (root / rel).is_file()
    )


def _hand_edits(
    root: Path, rec: Record, rendered: render.Output, deletes: list[str]
) -> list[HandEdit]:
    found: list[HandEdit] = []
    for rel, text in rendered.files.items():
        on_disk = _read(root / rel)
        if on_disk is None:
            continue  # missing: written again
        recorded = rec.files.get(rel)
        if recorded is None:
            if on_disk != text:
                found.append(record.hand_edit(rel, on_disk, text, unrecorded=True))
        elif record.digest(on_disk) != recorded:
            found.append(record.hand_edit(rel, on_disk, text))
    for rel in deletes:
        on_disk = _read(root / rel) or ""
        if record.digest(on_disk) != rec.files[rel]:
            found.append(record.hand_edit(rel, on_disk, ""))
    for name, block in rendered.blocks.items():
        host = name.split(" ", 1)[0]
        current = render.read_block(_read(root / host), name)
        recorded = rec.blocks.get(name)
        if current is None:
            if recorded is not None:  # the markers are gone: the block was removed by hand
                found.append(record.hand_edit(name, "", block))
            continue
        if recorded is None:
            if current != block:
                found.append(record.hand_edit(name, current, block, unrecorded=True))
        elif record.digest(current) != recorded:
            found.append(record.hand_edit(name, current, block))
    return found


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError):
        return None


def _backup_name(name: str) -> str:
    return f"{name.split(' ')[0]}.orig"


def _backup(root: Path, edit: HandEdit) -> None:
    """Keep the edited file next to it as ``<file>.orig`` (``.orig.1``, ... when one exists)."""
    source = root / edit.name.split(" ")[0]
    if not source.is_file():
        return
    target = root / _backup_name(edit.name)
    number = 0
    while target.exists():
        number += 1
        target = root / f"{_backup_name(edit.name)}.{number}"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _files(
    ws: Workspace,
    changes: list[tuple[Path, str | None, str]],
    deletes: list[str],
    rendered: render.Output,
) -> list[dict[str, str]]:
    owned = set(rendered.files)
    hosts = {name.split(" ", 1)[0] for name in rendered.blocks}
    out = []
    for path, before, _after in changes:
        rel = ws.rel(path)
        owner = "karni" if rel in owned or rel in hosts else "project"
        out.append(
            {"path": rel, "action": "create" if before is None else "modify", "owner": owner}
        )
    out += [{"path": rel, "action": "delete", "owner": "karni"} for rel in deletes]
    return out


def _adopt(root: Path, rec: Record, names: tuple[str, ...]) -> list[str]:
    """Record ``--adopt``: each name must be a Karni-owned file or block of the record."""
    added = []
    owned = set(rec.owned)
    for raw in names:
        name = Path(raw).as_posix().removeprefix("./")
        if (root / raw).is_absolute():
            with contextlib.suppress(ValueError):
                name = (root / raw).resolve().relative_to(root.resolve()).as_posix()
        matches = [n for n in owned if n == name or n.split(" ", 1)[0] == name]
        if not matches:
            raise CliError(
                f"--adopt {raw}: karni build does not own it (its record, {layout.RECORD}, lists "
                "the files and blocks it does). A file of the project's is the project's already.",
                code="C274",
            )
        for match in matches:
            if match not in rec.adopted:
                rec.adopted.append(match)
                added.append(match)
    return added


def _record(
    spec: schema.Spec,
    plan: plan_mod.Plan,
    rec: Record,
    rendered: render.Output,
    inputs: render.Inputs,
) -> Record:
    files = {rel: record.digest(text) for rel, text in rendered.files.items()}
    files |= {rel: digest for rel, digest in rec.files.items() if rel in rec.adopted}
    blocks = {name: record.digest(text) for name, text in rendered.blocks.items()}
    blocks |= {name: digest for name, digest in rec.blocks.items() if name in rec.adopted}
    return Record(
        spec=record.digest(json.dumps(normalise(spec), sort_keys=True)),
        entities=sorted(inputs.entities),
        pages=sorted(inputs.pages),
        files=files,
        blocks=blocks,
        adopted=sorted(rec.adopted),
    )


def _record_text(root: Path) -> str | None:
    return _read(root / layout.RECORD)


def _save_record(root: Path, rec: Record) -> None:
    path = root / layout.RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rec.text(), encoding="utf-8")


# the steps ------------------------------------------------------------------------


def _state(
    plan: plan_mod.Plan,
    inputs: render.Inputs,
    created: list[str],
    facts: dict[str, Any],
    modules: list[str],
) -> dict[str, Any]:
    """What the steps after the files need, remembered until they all ran."""
    entities = {
        f"{app}.{name}": entity
        for app, application in inputs.spec.apps.items()
        for name, entity in application.entities.items()
    }
    apps = sorted({label.split(".", 1)[0] for label in inputs.entities | inputs.removed})
    databases = sorted(
        {
            entity.database
            for label, entity in entities.items()
            if label in inputs.entities
            and entity.database not in (None, "default")
            and not entity.external
        }
    )
    renames: dict[str, list[list[str]]] = {"models": [], "fields": []}
    for new, old in inputs.renames.items():
        renames["models"].append([new.split(".")[0], old.split(".")[1], new.split(".")[1]])
    # the renames this plan applies (a was: stays in the spec after its rename is done)
    applied = {c.target for c in plan.changes if c.area == "fields" and c.action == "rename"}
    for (label, new_field), old_field in plan.field_renames.items():
        if label in inputs.entities and f"{label}.{new_field}" in applied:
            app, name = label.split(".", 1)
            renames["fields"].append([app, name, old_field, new_field])
    # demo rows only where the spec's seed names a count: rows nobody asked for would mix with
    # the ones the app's users (and its tests) create in the database the app runs on
    seed = [
        label
        for label in created
        if not entities[label].external and (_seed_count(inputs.spec, label) or 0) > 0
    ]
    unseeded = [label for label in created if not entities[label].external and label not in seed]
    return {
        "steps": list(output.STEPS[2:]),
        "modules": modules,
        "extras": feature_extras(inputs.spec),
        "apps": apps,
        "databases": databases,
        "renames": renames,
        "seed": seed,
        "unseeded": unseeded,
        "user": str(facts.get("user_model") or ""),
    }


def _merge(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """A new build's steps, plus what a build that stopped early had not done yet."""
    if not old:
        return new
    left = set(old.get("steps") or [])
    merged = dict(new)

    def union(key: str, when: bool = True) -> list[Any]:
        found = list(old.get(key) or []) if when else []
        return found + [item for item in new.get(key) or [] if item not in found]

    merged["modules"] = union("modules")
    merged["extras"] = union("extras")
    merged["apps"] = sorted(set(union("apps")))
    merged["databases"] = sorted(set(union("databases")))
    merged["seed"] = union("seed", "seed" in left)
    merged["unseeded"] = union("unseeded", "seed" in left)
    old_renames = old.get("renames") or {} if "migrations" in left else {}
    merged["renames"] = {
        kind: [*(old_renames.get(kind) or []), *(new["renames"].get(kind) or [])]
        for kind in ("models", "fields")
    }
    return merged


def _seed_count(spec: schema.Spec, label: str) -> int | None:
    name = label.split(".", 1)[1]
    return spec.seed.get(label, spec.seed.get(name))


def _steps(
    root: Path, result: Result, state: dict[str, Any], opts: Options, *, written: bool
) -> Result:
    karni = [f for f in result.files if f["owner"] == "karni"]
    theirs = [f["path"] for f in result.files if f["owner"] == "project"]
    modules = list(state.get("modules") or [])
    result.step("modules").status = "done" if modules else "skipped"
    result.step("modules").summary = (
        ", ".join(f"karni add {name}" for name in modules) if modules else "no module to add"
    )
    files = result.step("files")
    if written:
        files.status = "done"
        files.summary = f"{len(result.files)} written: {len(karni)} Karni's" + (
            f", {len(theirs)} the project's ({', '.join(theirs)})" if theirs else ""
        )
    else:
        files.status, files.summary = "skipped", "already written by the build that stopped"
    current = "modules"
    try:
        _require_extras(root, list(state.get("extras") or []))
        if modules:
            _guidance(root, modules, opts)
            state["modules"] = []
            record.save_pending(root, state)
        for name in list(state.get("steps") or []):
            current = name
            step = result.step(name)
            runner = STEP_RUNNERS[name]
            summary = runner(root, state, opts)
            step.status = "skipped" if summary.startswith("skipped: ") else "done"
            step.summary = summary.removeprefix("skipped: ")
            state["steps"] = [s for s in state["steps"] if s != name]
            record.save_pending(root, state if state["steps"] else None)
    except Stop as stop:
        failed = result.step(current)
        failed.status = "failed"
        failed.summary = f"({stop.code}) {stop.message}" + (
            f"\n{stop.detail}" if stop.detail else ""
        )
        result.status = "failed"
        result.code, result.message = stop.code, stop.message
        done = [s.name for s in result.steps if s.status == "done"]
        result.next = (
            f"{stop.next}. Then run karni build again: it continues from {failed.name}"
            if stop.next
            else f"fix it, then run karni build again: it continues from {failed.name}"
        ) + (f" (done: {', '.join(done)})." if done else ".")
        return result
    record.save_pending(root, None)
    result.status = "built"
    left = len(result.plan.not_managed) if result.plan else 0
    if left:
        result.message = (
            f"Built. karni plan's {left} other change{'s are' if left != 1 else ' is'} in the "
            f"project's own code (karni plan marks {'them' if left != 1 else 'it'} not managed)."
        )
    return result


def _manage(root: Path, args: list[str], opts: Options, database: str | None = "connect") -> Any:
    return project_mod.run_manage(
        root,
        args,
        docker=opts.docker,
        service=opts.service,
        database=database,  # type: ignore[arg-type]
    )


#: System check warnings Django prints on every command: noise in a failed step's output.
_WARNING = re.compile(r"^(System check identified|WARNINGS:|\s*HINT:|\S+: \(\w+\.W\d+\))")


def _tail(proc: Any) -> str:
    """The last lines of a failed command's output, without the system check warnings."""
    lines = [
        line
        for line in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines()
        if line.strip() and not _WARNING.match(line)
    ]
    return "\n".join(lines[-_TAIL:])


def _require_extras(root: Path, extras: list[str]) -> None:
    """Stop early, with the install line, when a feature's extra is not importable."""
    for extra in extras:
        name = EXTRA_IMPORTS.get(extra)
        if name is not None and project_mod.project_has_module(root, name) is False:
            raise Stop(
                "C841",
                f"karni[{extra}] is in pyproject.toml now (a feature in karni.yaml needs it), but "
                f"the project's interpreter cannot import {name}.",
                "install it: uv pip install -r pyproject.toml (or docker compose build), then "
                "karni build again: it continues from here",
            )


def _guidance(root: Path, modules: list[str], opts: Options) -> None:
    """``karni add``'s last part: the module installed, and its agent guidance recorded."""
    from karni_cli.commands.add import record_guidance

    for name in modules:
        app = f"karni_{name.replace('-', '_')}"
        if project_mod.project_has_module(root, app) is False:
            raise Stop(
                "C276",
                f"karni-{name} is in pyproject.toml now, but the project's interpreter cannot "
                f"import {app}.",
                "install it: uv pip install -r pyproject.toml (or docker compose build)",
            )
        with _quiet():
            record_guidance(root, name)


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        yield


@contextlib.contextmanager
def _env(**values: str) -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _migrations(root: Path, state: dict[str, Any], opts: Options) -> str:
    apps = list(state.get("apps") or [])
    if not apps:
        return "skipped: no app of Karni's"
    args = ["karni_makemigrations", *apps, "--no-input"]
    renames = state.get("renames") or {}
    if renames.get("models") or renames.get("fields"):
        args += ["--renames", json.dumps(renames)]
    proc = _manage(root, args, opts, database="load")
    if proc.returncode != 0:
        raise Stop(
            "C277",
            "makemigrations failed.",
            "read the lines above: a required field added to a table with rows needs a default, "
            "or to be added as optional first (str?), filled, then made required",
            _tail(proc),
        )
    written = re.findall(r"(\S+/migrations/\S+\.py)", proc.stdout or "")
    shown = sorted({_short(root, path) for path in written})
    return ", ".join(shown) if shown else "skipped: no model change"


def _short(root: Path, path: str) -> str:
    candidate = Path(path) if Path(path).is_absolute() else root / path
    with contextlib.suppress(ValueError):
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    return path


def _migrate(root: Path, state: dict[str, Any], opts: Options) -> str:
    applied: list[str] = []
    for alias in ["default", *(state.get("databases") or [])]:
        args = ["migrate", "--no-input"] + ([] if alias == "default" else ["--database", alias])
        proc = _manage(root, args, opts)
        if proc.returncode != 0:
            raise Stop("C278", f"migrate failed on the database {alias}.", None, _tail(proc))
        count = (proc.stdout or "").count("... OK")
        if count:
            applied.append(f"{count} on {alias}")
    return f"applied {', '.join(applied)}" if applied else "skipped: nothing to apply"


def _seed(root: Path, state: dict[str, Any], opts: Options) -> str:
    labels = list(state.get("seed") or [])
    if not labels:
        if state.get("unseeded"):
            return (
                "skipped: seed in karni.yaml names none of the new tables, so they start empty "
                "(karni seed fills them with demo rows)"
            )
        return "skipped: no table created"
    counter = plan_mod.manage_counter(root, docker=opts.docker, service=opts.service)
    answer = counter([{"model": label} for label in labels])
    rows = answer.get("rows") or []
    if answer.get("error") or len(rows) != len(labels):
        raise Stop(
            "C279",
            "the new tables could not be counted, so nothing was seeded.",
            None,
            str(answer.get("error") or ""),
        )
    empty = [label for label, count in zip(labels, rows, strict=True) if count == 0]
    if not empty:
        return "skipped: the tables it created hold rows already"
    args = ["karni_seed"]
    for label in ([state["user"]] if state.get("user") else []) + empty:
        args += ["--model", label]
    proc = _manage(root, args, opts)
    if proc.returncode != 0:
        raise Stop("C279", "karni seed failed.", None, _tail(proc))
    seeded = re.findall(
        r"^\s+(\S+\.\S+)\s+(\d+)(?:\s+\(bulk, ([\d.]+)s)?", proc.stdout or "", re.MULTILINE
    )
    # a large seed count went in bulk (karni.bulk_seeding, experimental): say so, with its time
    shown = ", ".join(
        f"{label.split('.', 1)[1]} {count}" + (f" in bulk ({seconds}s)" if seconds else "")
        for label, count, seconds in seeded
        if label in empty
    )
    login = re.search(r"Log in as (\S+ / \S+)", proc.stdout or "")
    return (shown or ", ".join(empty)) + (f" (demo login {login.group(1)})" if login else "")


def _types(root: Path, state: dict[str, Any], opts: Options) -> str:
    from karni_cli.commands.types import SchemaFailed, write_types

    if not (root / "frontend").is_dir():
        return "skipped: no frontend/"
    try:
        write_types(root, docker=opts.docker, service=opts.service)
    except SchemaFailed as exc:
        raise Stop(
            "C280",
            "karni types failed: the API schema did not print.",
            None,
            "\n".join(exc.output.strip().splitlines()[-_TAIL:]),
        ) from None
    except CliError as exc:
        raise Stop("C280", f"karni types failed ({exc.code}).", None, exc.message) from None
    return "frontend/src/api/types.ts and hooks.ts"


def _test(root: Path, state: dict[str, Any], opts: Options) -> str:
    snapshot = root / "tests" / "openapi.snapshot.json"
    before = _read(snapshot)
    probe = project_mod.run_python(
        root, ["-c", "import pytest"], docker=opts.docker, service=opts.service
    )
    if probe.returncode != 0:
        raise Stop(
            "C281",
            "pytest is not installed in the project's interpreter.",
            "install the dev group: pip install pytest pytest-django (or uv sync)",
        )
    # the spec changed the API on purpose: the contract snapshot follows it
    with _env(KARNI_UPDATE_SNAPSHOTS="1"):
        proc = project_mod.run_python(
            root,
            ["-m", "pytest", "-q", "-p", "no:cacheprovider"],
            docker=opts.docker,
            service=opts.service,
            database="connect",
        )
    if proc.returncode != 0:
        raise Stop(
            "C281", "the project's tests fail.", "karni test shows them in full", _tail(proc)
        )
    last = (proc.stdout or "").strip().splitlines()[-1:] or ["passed"]
    summary = last[0].strip("= ")
    if _read(snapshot) != before:
        summary += ", tests/openapi.snapshot.json updated (the API changed: commit it)"
    return summary


_UNSERVED = re.compile(r"karni\.E533: .*? links to (\S+?), which no page")


def _unserved_routes(out: str) -> list[str]:
    """The routes of ``karni check``'s output when E533 is the only finding, else ``[]``."""
    if any(
        "karni.E" in line and "karni.E533" not in line and "karni.E702" not in line
        for line in out.splitlines()
    ):
        return []
    return sorted(set(_UNSERVED.findall(out)))


def _check(root: Path, state: dict[str, Any], opts: Options) -> str:
    from karni_cli.commands.check import run_checks

    passed, out = run_checks(root, docker=opts.docker, service=opts.service)
    if not passed:
        routes = _unserved_routes(out)
        if routes:
            raise Stop(
                "C851",
                "The menu links to pages of your own that are not written yet: "
                f"{', '.join(routes)}.",
                "a `code` page in karni.yaml is yours to write: add its route to "
                "frontend/src/routes.tsx (karni make page <name> --kind blank starts one), "
                "then run karni build again",
            )
        tail = "\n".join(out.strip().splitlines()[-_TAIL:])
        raise Stop("C282", "karni check fails.", "karni check shows every finding", tail)
    return "ok"


#: Experimental. Each step after the files, by name: ``(root, state, options) -> summary``.
#: A summary that starts with ``skipped: `` marks the step skipped.
STEP_RUNNERS: dict[str, Callable[[Path, dict[str, Any], Options], str]] = {
    "migrations": _migrations,
    "migrate": _migrate,
    "seed": _seed,
    "types": _types,
    "test": _test,
    "check": _check,
}
