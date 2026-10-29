"""``karni load``: a project's real content from a file, created or updated by natural key.

Demo data (:mod:`karni.seeding`) is random and disposable. Content is what a
site is made of: the services, the projects with their galleries, the team.
It lives in a JSON (or YAML) file next to its images, under version control,
and ``karni load content/site.json`` loads it as often as it changes. A
second run with the same file changes nothing and says so.

The file maps model labels to lists of rows::

    {
      "portfolio.Service": [
        {"slug": "design", "title": "Design", "image": "images/design.jpg",
         "selected_work": ["nexus"]}
      ],
      "portfolio.Project": [
        {"slug": "nexus", "title": "Nexus", "services": ["design"],
         "gallery": [{"image": "images/nexus-1.jpg", "alt": "Street view"}]}
      ]
    }

* **Matching.** A row is matched to an existing row by the model's key and
  updated, or created when nothing matches. The key is ``Karni.import_key``,
  else ``Karni.natural_key`` (declared, or the first unique slug, char or
  email field), else the fields of the model's first unique constraint,
  else the primary key. Every row carries its key.
* **Relations** name their target by the target's natural key (or primary
  key): one value for a foreign key, a list for a many-to-many field. A
  foreign key's target comes earlier in the file or already exists. An
  optional many-to-many field is applied once every row of the file exists,
  so two models may point at each other.
* **Files.** A file or image field holds a path relative to the content
  file. It is uploaded when the row has no file yet, or again with
  ``--refresh-files``. An empty string leaves the field alone. Each file is
  checked by the API's serializer field first (an image must open as one),
  a field the model requires needs a file on a new row, and nothing reaches
  the storage until every row is valid.
* **Children.** A list under a reverse relation's accessor (``gallery`` for
  ``ProjectImage.project`` with ``related_name="gallery"``) holds the row's
  children, matched by the parent plus the child's key: its natural key,
  else the rest of a unique constraint that includes the parent. An integer
  key a child row leaves out is its position in the list, counted from 1.
  ``--prune`` deletes the parent's children that the list does not name. A
  row without the list keeps its children.
* **Soft delete.** Rows are matched among all rows, soft-deleted ones
  included, and a soft-deleted row the file lists is restored. ``--prune``
  deletes the way the model deletes (a ``BaseModel`` row is soft-deleted).
* **Validation.** Every row goes through the serializer the API uses (types,
  choices, ``clean()``, uniqueness), in one transaction. One invalid row
  rolls the whole load back, and the error names the file, the model, the
  row's key, the field and the problem. ``--dry-run`` runs everything,
  reports and rolls back. Its report is a diff per model: each row it would
  create, each row it would change with the fields that change (old and new
  value), each file it would upload and each child ``--prune`` would delete.
* **Attribution.** Writes run as ``--as USER`` through
  :func:`karni.middleware.current_user`, so ``created_by``, ``updated_by``
  and owner fields are stamped with that user (or left empty without one),
  and ``karni.audit`` records the load as one batch named after the file.
  ``Karni.after_import`` runs once per model after a load commits.

The loader is trusted like ``migrate``: no ``access`` gate, row scope or
field role applies. The actor attributes the writes and nothing more.

Override / escape hatches: :func:`load_content` is the importable form and
takes ``importer_class=`` (a :class:`ContentImporter` subclass). The row
logic is :class:`karni.transfer.imports.Importer` with the same ``class
Karni`` hooks (``natural_key``, ``import_key``, ``import_lookup``,
``import_transform``, ``after_import``).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File
from django.db import models, transaction
from django.db.models import F, UniqueConstraint
from django.test import RequestFactory
from rest_framework import serializers

from karni.errorcodes import KarniError
from karni.middleware import current_user
from karni.transfer.fields import ColumnSpec
from karni.transfer.imports import MAX_PROBLEMS, Importer, ImportResult, _blank

__all__ = [
    "ContentImporter",
    "LoadError",
    "LoadReport",
    "ModelCounts",
    "Problem",
    "RowChange",
    "find_user",
    "load_content",
    "read_content",
]

#: Rows of one model a dry run lists before it says how many more there are.
DIFF_ROWS: Final = 20

#: Kinds of column a content row sets through the serializer (a relation to one row included).
_SCALAR_KINDS: Final = frozenset(
    {"text", "integer", "decimal", "boolean", "date", "datetime", "choice", "relation", "json"}
)


@dataclass(frozen=True)
class Problem:
    """One thing wrong with one row: the model, the row (its key), the field, the message."""

    model: str
    row: str
    field: str
    message: str

    def render(self) -> str:
        where = f"{self.model} ({self.row})" if self.row else self.model
        if self.field:
            return f"{where}: {self.field}: {self.message}"
        return f"{where}: {self.message}"

    def to_dict(self) -> dict[str, str]:
        return {"model": self.model, "row": self.row, "field": self.field, "message": self.message}


class LoadError(KarniError):
    """The content file cannot be loaded, and nothing was written.

    ``E804``: the file itself (missing, not valid JSON or YAML, the wrong
    shape, an unknown model, a nested model with no key, an unknown
    ``--as`` user). ``E805``: one or more rows were refused, listed in
    :attr:`problems`.
    """

    code = "E804"

    def __init__(
        self, message: str, *, code: str | None = None, problems: list[Problem] | None = None
    ) -> None:
        super().__init__(message, code=code)
        self.problems = list(problems or [])


def _shown(value: Any) -> str:
    """A value for the diff: short, one line."""
    if isinstance(value, models.Model):
        value = value.pk
    if isinstance(value, list | set | tuple):
        value = sorted(str(getattr(item, "pk", item)) for item in value)
    text = repr(value) if not isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57] + "..."


@dataclass
class RowChange:
    """One row in a load's diff: created, updated (with the fields that change) or pruned."""

    row: str
    status: str  # created | updated | pruned
    fields: list[tuple[str, str, str]] = field(default_factory=list)  # (name, before, after)

    def render(self) -> str:
        mark = {"created": "+", "updated": "~", "pruned": "-"}.get(self.status, "?")
        if not self.fields:
            return f"{mark} {self.row}"
        changes = ", ".join(
            f"{name} {before} -> {after}" if before else (f"{name} -> {after}" if after else name)
            for name, before, after in self.fields
        )
        return f"{mark} {self.row}: {changes}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "status": self.status,
            "fields": {name: [before, after] for name, before, after in self.fields},
        }


@dataclass
class ModelCounts:
    """What a load did (or would do) to one model, and the rows behind the numbers."""

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    pruned: int = 0
    files: int = 0
    changes: list[RowChange] = field(default_factory=list)

    def render(self) -> str:
        parts = [
            f"{self.created} created",
            f"{self.updated} updated",
            f"{self.unchanged} unchanged",
        ]
        if self.pruned:
            parts.append(f"{self.pruned} pruned")
        if self.files:
            parts.append(f"{self.files} file(s) uploaded")
        return ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "pruned": self.pruned,
            "files": self.files,
            "changes": [change.to_dict() for change in self.changes],
        }


@dataclass
class LoadReport:
    """What a load did, per model, and every problem it found."""

    path: str
    dry_run: bool
    models: dict[str, ModelCounts] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def changed(self) -> bool:
        """Whether anything was (or, in a dry run, would be) written."""
        return any(c.created or c.updated or c.pruned for c in self.models.values())

    def counts(self, label: str) -> ModelCounts:
        return self.models.setdefault(label, ModelCounts())

    def problem(self, model: str, row: str, name: str, message: str) -> None:
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(Problem(model, row, name, message))

    def render(self) -> str:
        if self.dry_run:
            lines = [f"Dry run of {self.path}, nothing was written:"]
        else:
            lines = [f"Loaded {self.path}:"]
        width = max((len(label) for label in self.models), default=0)
        for label, counts in self.models.items():
            lines.append(f"  {label:<{width}}  {counts.render()}")
            if self.dry_run:
                shown = counts.changes[:DIFF_ROWS]
                lines.extend(f"      {change.render()}" for change in shown)
                if len(counts.changes) > len(shown):
                    lines.append(f"      ... and {len(counts.changes) - len(shown)} more")
        if not self.changed:
            lines.append("Nothing would change." if self.dry_run else "Nothing changed.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "dry_run": self.dry_run,
            "changed": self.changed,
            "models": {label: counts.to_dict() for label, counts in self.models.items()},
            "problems": [problem.to_dict() for problem in self.problems],
            "seconds": round(self.seconds, 3),
        }


class ContentImporter(Importer):
    """The importer with full access: a management command is trusted, like ``migrate``.

    Every row is looked up (soft-deleted ones too, live rows first) and
    every field the API lets a client write may be written. No ``access``
    gate, row scope or field role applies. A blank value in the file is
    written as given. ``actor`` stamps owner fields on created rows.

    Override / escape hatch: pass a subclass as ``importer_class`` to
    :func:`load_content`, and override :meth:`may_create`,
    :meth:`may_update`, :meth:`write_queryset`, :meth:`readable` or
    :meth:`get_serializer` to put any of the checks back.
    """

    skip_blank = False
    not_visible_note = ""
    write_pk = True

    def __init__(self, model: type[models.Model], request: Any, *, actor: Any = None) -> None:
        super().__init__(model, request)
        self.user = actor
        # No request in the serializer context: server-side use, so relation fields
        # resolve against every row and no field role hides a field.
        self.context = {}

    def may_create(self) -> bool:
        return True

    def may_update(self) -> bool:
        return True

    def write_queryset(self) -> Any:
        rows = self.model._base_manager.all()
        if any(f.name == "deleted_at" for f in self.model._meta.concrete_fields):
            rows = rows.order_by(F("deleted_at").asc(nulls_first=True))
        return rows

    def readable(self, target: type[models.Model]) -> Any:
        return target._default_manager.all()

    def _rows(self, slot: str, action: str, permission: str) -> Any:
        return True

    #: The fields the last updated row changes: (name, before, after), for the diff.
    last_changes: list[tuple[str, str, str]]

    def _unchanged(self, instance: Any, validated: dict[str, Any]) -> bool:
        self.last_changes = self.differences(instance, validated)
        return not self.last_changes

    def differences(self, instance: Any, validated: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Every field ``validated`` would change on ``instance``, with both values shown."""
        found: list[tuple[str, str, str]] = []
        for name, value in validated.items():
            model_field = _model_field(self.model, name)
            if model_field is None:
                found.append((name, "", _shown(value)))
            elif getattr(model_field, "many_to_many", False):
                current = {str(pk) for pk in getattr(instance, name).values_list("pk", flat=True)}
                wanted = {str(getattr(item, "pk", item)) for item in value}
                if current != wanted:
                    found.append((name, _shown(current), _shown(wanted)))
            elif getattr(model_field, "is_relation", False):
                before = getattr(instance, model_field.attname)
                after = getattr(value, "pk", value)
                if str(before) != str(after):
                    found.append((name, _shown(before), _shown(after)))
            elif getattr(instance, name) != value:
                found.append((name, _shown(getattr(instance, name)), _shown(value)))
        return found

    def get_serializer(
        self, instance: Any | None, data: dict[str, Any]
    ) -> serializers.BaseSerializer[Any]:
        """The API's serializer, with file fields optional: the loader uploads files itself."""
        serializer = super().get_serializer(instance, data)
        for name, serializer_field in serializer.fields.items():
            if isinstance(serializer_field, serializers.FileField) and name not in data:
                serializer_field.required = False
        return serializer


@dataclass
class _Plan:
    """How one model's rows are read: its importer, its key, and which names mean what."""

    label: str
    model: type[models.Model]
    importer: Importer
    #: Every field a row is matched on (a child's parent foreign key included).
    keys: tuple[str, ...]
    #: The parent foreign key when the rows are nested children.
    parent: str | None
    #: The integer key a child row may leave out (it is then the row's position).
    position_key: str | None
    #: Serializer fields a row sets directly (scalars and foreign keys).
    scalars: frozenset[str]
    #: Fields the serializer publishes that a file cannot set (read-only, unsupported kinds).
    fixed: frozenset[str]
    files: dict[str, ColumnSpec]
    #: The serializer fields that validate an uploaded file, by name.
    file_fields: dict[str, Any]
    #: File fields the model requires (``blank=False``).
    required_files: frozenset[str]
    m2m: dict[str, ColumnSpec]
    relation_specs: dict[str, ColumnSpec]
    #: Reverse foreign keys by accessor name: nested child lists.
    children: dict[str, Any]
    may_create: bool = True
    may_update: bool = True
    result: ImportResult = field(default_factory=ImportResult)

    @property
    def match(self) -> tuple[str, ...]:
        """The key fields besides the importer's own key."""
        return self.keys[1:]


@dataclass
class _Row:
    """One loaded row, kept between the passes."""

    plan: _Plan
    label: str
    index: int
    key_values: dict[str, Any]
    instance: Any
    status: str
    m2m: dict[str, Any]
    files: dict[str, Path]
    changes: list[tuple[str, str, str]] = field(default_factory=list)


def read_content(path: Path) -> Any:
    """The parsed file: JSON, or YAML for ``.yaml`` / ``.yml``.

    PyYAML comes with drf-spectacular, a core dependency. Without it a YAML
    file is refused with the fix.
    """
    if not path.is_file():
        raise LoadError(f"{path}: no such file.")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise LoadError(
                f"{path}: reading YAML needs PyYAML (pip install pyyaml). Install it, or write "
                "the file as JSON."
            ) from exc
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise LoadError(f"{path}: not valid YAML: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoadError(
            f"{path}: not valid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc


def find_user(spec: str) -> Any:
    """The user ``--as`` names: a primary key, an email or a username."""
    from karni.debug.replay import resolve_user
    from karni.exceptions import KarniCommandError

    try:
        return resolve_user(spec)
    except KarniCommandError as exc:
        raise LoadError(
            f"No user {spec!r}: --as takes the primary key, email or username of an existing "
            "user, who is recorded as the actor of the load (created_by, updated_by, owner "
            "fields, the audit batch). Leave --as out to record no actor."
        ) from exc


def _model_field(model: type[models.Model], name: str) -> Any:
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _unique_sets(model: type[models.Model]) -> Iterator[tuple[str, ...]]:
    """Field sets that identify a row: ``unique_together`` and unique constraints on fields.

    A conditional constraint counts (``deleted_at IS NULL`` on a soft-delete
    model is the usual one). Expression constraints do not.
    """
    for names in model._meta.unique_together:
        yield tuple(names)
    for constraint in model._meta.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.fields:
            yield tuple(constraint.fields)


def _keys(model: type[models.Model], declared: str | None, parent: str | None) -> tuple[str, ...]:
    """The fields rows of ``model`` are matched on, the parent foreign key last."""
    tail = (parent,) if parent else ()
    if declared:
        return (declared, *tail)
    for names in _unique_sets(model):
        if parent is None:
            return names
        if parent in names and len(names) > 1:
            return (*(name for name in names if name != parent), parent)
    if parent is not None:
        return ()
    return (model._meta.pk.name,)


class _Loader:
    def __init__(
        self,
        path: Path,
        *,
        actor: Any,
        dry_run: bool,
        refresh_files: bool,
        prune: bool,
        importer_class: type[ContentImporter],
    ) -> None:
        self.path = path
        self.base = path.resolve().parent
        self.actor = actor
        self.dry_run = dry_run
        self.refresh_files = refresh_files
        self.prune = prune
        self.importer_class = importer_class
        self.request: Any = RequestFactory().post("/")
        self.request.user = None  # server-side use: the serializer publishes every field
        self.report = LoadReport(str(path), dry_run)
        self.plans: dict[tuple[type[models.Model], str | None], _Plan] = {}
        self.rows: list[_Row] = []

    # plans

    def plan_for(self, model: type[models.Model], parent: str | None) -> _Plan:
        """The plan for ``model``: a top-level list, or children through the ``parent`` FK."""
        cached = self.plans.get((model, parent))
        if cached is not None:
            return cached
        importer = self.importer_class(model, self.request, actor=self.actor)
        keys = _keys(model, importer.options.key, parent)
        if not keys:
            raise LoadError(
                f"{self.path}: {model._meta.label} rows nested under their {parent} have no "
                f"key to be matched on. Declare class Karni: natural_key = '<field>' on "
                f"{model.__name__}, or a unique constraint on ({parent}, <field>)."
            )
        if keys[0] != importer.options.key:
            importer.options = replace(importer.options, key=keys[0])
        own = [name for name in keys if name != parent]
        position_key = None
        if parent is not None and len(own) == 1:
            if isinstance(model._meta.get_field(own[0]), models.IntegerField):
                position_key = own[0]
        specs = importer.specs
        scalars = {spec.name for spec in specs if spec.writable and spec.kind in _SCALAR_KINDS}
        scalars |= {spec.name for spec in specs if spec.key}
        file_fields: dict[str, Any] = {}
        if any(spec.kind == "file" for spec in specs):
            published = importer.serializer_class(context=importer.context).fields
            file_fields = {
                spec.name: published[spec.name]
                for spec in specs
                if spec.kind == "file" and not published[spec.name].read_only
            }
        files = {spec.name: spec for spec in specs if spec.name in file_fields}
        required_files = {
            name for name in files if not getattr(_model_field(model, name), "blank", True)
        }
        m2m = {spec.name: spec for spec in specs if spec.kind == "relations" and spec.writable}
        fixed = {spec.name for spec in specs} - scalars - set(files) - set(m2m)
        children: dict[str, Any] = {}
        for relation in model._meta.related_objects:
            accessor = relation.get_accessor_name()
            if relation.one_to_many and accessor and accessor not in scalars:
                children[accessor] = relation
        plan = _Plan(
            label=model._meta.label,
            model=model,
            importer=importer,
            keys=keys,
            parent=parent,
            position_key=position_key,
            scalars=frozenset(scalars),
            fixed=frozenset(fixed),
            files=files,
            file_fields=file_fields,
            required_files=frozenset(required_files),
            m2m=m2m,
            relation_specs={
                spec.name: spec for spec in specs if spec.kind in ("relation", "relations")
            },
            children=children,
            may_create=importer.may_create(),
            may_update=importer.may_update(),
        )
        self.plans[(model, parent)] = plan
        self.report.counts(plan.label)
        return plan

    def top_level(self, content: Any) -> list[tuple[_Plan, list[Any]]]:
        if not isinstance(content, Mapping):
            raise LoadError(
                f"{self.path}: the file must hold one object mapping model labels "
                f'("app.Model") to lists of rows, not {type(content).__name__}.'
            )
        found: list[tuple[_Plan, list[Any]]] = []
        for label, rows in content.items():
            try:
                model = apps.get_model(str(label))
            except (LookupError, ValueError) as exc:
                raise LoadError(
                    f"{self.path}: {label!r} is not an installed model. Every top-level key "
                    'is a model label such as "events.Event" (karni context lists them).'
                ) from exc
            if not isinstance(rows, list):
                raise LoadError(
                    f"{self.path}: {model._meta.label} must hold a list of rows, not "
                    f"{type(rows).__name__}."
                )
            found.append((self.plan_for(model, None), rows))
        return found

    # the run

    def run(self) -> LoadReport:
        from karni.audit.capture import change_batch

        started = time.perf_counter()
        plans = self.top_level(read_content(self.path))
        with current_user(self.actor), transaction.atomic():
            batch = (
                nullcontext()
                if self.dry_run
                else change_batch("load", self.path.name, {"file": str(self.path)})
            )
            with batch:
                for plan, rows in plans:
                    self.load_rows(plan, rows, parent=None, parent_label="")
                # A row that failed would turn up again as a missing many-to-many target,
                # so the later passes run only on a clean first pass.
                if not self.report.problems:
                    self.apply_m2m()
                if not self.report.problems:
                    self.attach_files()
            self.count()
            if self.dry_run or self.report.problems:
                transaction.set_rollback(True)
        self.report.seconds = time.perf_counter() - started
        if self.report.problems:
            total = len(self.report.problems)
            more = f" (the first {MAX_PROBLEMS} are listed)" if total >= MAX_PROBLEMS else ""
            listed = "\n".join(f"  {problem.render()}" for problem in self.report.problems)
            raise LoadError(
                f"{self.path}: {total} problem(s){more}, so nothing was loaded. Fix the rows "
                f"and run again.\n{listed}",
                code="E805",
                problems=self.report.problems,
            )
        if not self.dry_run:
            self.after_import()
        return self.report

    def load_rows(
        self, plan: _Plan, rows: list[Any], *, parent: Any, parent_label: str
    ) -> list[Any]:
        """Pass one over a list: scalars, foreign keys and children. Returns the rows' pks."""
        loaded: list[Any] = []
        prefix = f"{parent_label} > " if parent_label else ""
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                self.report.problem(
                    plan.label,
                    f"{prefix}#{index + 1}",
                    "",
                    f"a row must be an object with the model's fields, not {type(raw).__name__}.",
                )
                continue
            values = dict(raw)
            if plan.position_key is not None and plan.position_key not in values:
                values[plan.position_key] = index + 1
            if plan.parent is not None:
                values[plan.parent] = parent.pk
            missing = [name for name in plan.keys if name not in values]
            if missing:
                self.report.problem(
                    plan.label,
                    f"{prefix}#{index + 1}",
                    missing[0],
                    f"every {plan.model._meta.verbose_name} row needs its key "
                    f"({', '.join(name for name in plan.keys if name != plan.parent)}) to be "
                    "matched to an existing row. Declare class Karni: natural_key = '<field>' "
                    "or a unique constraint to use other fields.",
                )
                continue
            key_values = {name: values[name] for name in plan.keys}
            shown = ", ".join(
                f"{name}={value!r}" for name, value in key_values.items() if name != plan.parent
            )
            label = f"{prefix}{shown}"
            if not self.known_names(plan, label, values):
                continue
            files = {name: values.pop(name) for name in list(values) if name in plan.files}
            later = {
                name: values.pop(name)
                for name in list(values)
                if name in plan.m2m and not plan.m2m[name].required
            }
            nested = {name: values.pop(name) for name in list(values) if name in plan.children}
            paths = self.file_paths(plan, label, files)
            if paths is None:
                continue
            status, instance = self.one(plan, label, index, values)
            if instance is None:
                continue
            loaded.append(instance.pk)
            row = _Row(plan, label, index, key_values, instance, status, later, paths)
            if status == "updated":
                row.changes.extend(self.changes_of(plan))
            self.rows.append(row)
            for accessor, child_rows in nested.items():
                self.load_children(plan, label, instance, accessor, child_rows)
        return loaded

    def known_names(self, plan: _Plan, label: str, values: dict[str, Any]) -> bool:
        """Whether every name in the row is something a content file may set."""
        ok = True
        for name in values:
            if name in plan.scalars or name in plan.files or name in plan.m2m:
                continue
            if name == plan.parent:
                continue
            if name in plan.children:
                if not isinstance(values[name], list):
                    self.report.problem(
                        plan.label,
                        label,
                        name,
                        f"children go in a list of rows, not {type(values[name]).__name__}.",
                    )
                    ok = False
                continue
            if name in plan.fixed:
                message = (
                    "cannot be set from a content file: the API publishes it read-only "
                    "(APIMeta.read_only, an owner field, a non-editable field) or its kind "
                    "is not supported."
                )
            else:
                known = sorted(set(plan.scalars) | set(plan.files) | set(plan.m2m))
                message = f"not a field of {plan.model.__name__}. Fields: {', '.join(known)}."
                if plan.children:
                    message += f" Child lists: {', '.join(sorted(plan.children))}."
            self.report.problem(plan.label, label, name, message)
            ok = False
        return ok

    def file_paths(self, plan: _Plan, label: str, files: dict[str, Any]) -> dict[str, Path] | None:
        """The files a row names, resolved against the content file's folder."""
        found: dict[str, Path] = {}
        ok = True
        for name, relative in files.items():
            if _blank(relative):
                continue
            if not isinstance(relative, str):
                self.report.problem(
                    plan.label,
                    label,
                    name,
                    f"a file field holds a path relative to {self.path.name}, not "
                    f"{type(relative).__name__}.",
                )
                ok = False
                continue
            full = self.base / relative
            if not full.is_file():
                self.report.problem(
                    plan.label,
                    label,
                    name,
                    f"no such file {relative!r} (paths are relative to {self.path.name}).",
                )
                ok = False
                continue
            found[name] = full
        return found if ok else None

    def changes_of(self, plan: _Plan) -> list[tuple[str, str, str]]:
        return list(getattr(plan.importer, "last_changes", []) or [])

    def one(self, plan: _Plan, label: str, index: int, values: dict[str, Any]) -> tuple[str, Any]:
        """One row through the importer, its problems relabelled with the row's key."""
        if isinstance(plan.importer, ContentImporter):
            plan.importer.last_changes = []
        seen = len(plan.result.problems)
        errors = plan.result.errors
        status, instance = plan.importer._one(
            index,
            values,
            plan.relation_specs,
            plan.may_create,
            plan.may_update,
            plan.result,
            match=plan.match,
        )
        if status == "error":
            new = plan.result.problems[seen:]
            for problem in new:
                self.report.problem(plan.label, label, problem.field, problem.message)
            if not new and plan.result.errors > errors:
                self.report.problem(plan.label, label, "", "refused (details not kept).")
        elif instance is not None and getattr(instance, "deleted_at", None) is not None:
            if hasattr(instance, "restore"):
                instance.restore()
                status = "updated" if status == "unchanged" else status
        return status, instance

    def load_children(
        self, plan: _Plan, label: str, parent: Any, accessor: str, rows: list[Any]
    ) -> None:
        relation = plan.children[accessor]
        child_plan = self.plan_for(relation.related_model, relation.field.name)
        loaded = self.load_rows(child_plan, rows, parent=parent, parent_label=label)
        if self.prune:
            extra = relation.related_model._default_manager.filter(
                **{relation.field.name: parent.pk}
            ).exclude(pk__in=loaded)
            count = extra.count()
            if count:
                counts = self.report.counts(child_plan.label)
                counts.changes.extend(
                    RowChange(f"{label} > {child}", "pruned") for child in extra[:DIFF_ROWS]
                )
                extra.delete()
                counts.pruned += count

    def apply_m2m(self) -> None:
        """Pass two: optional many-to-many fields, now that every row of the file exists."""
        for row in self.rows:
            if not row.m2m:
                continue
            values = {**row.key_values, **row.m2m}
            status, _ = self.one(row.plan, row.label, row.index, values)
            if status == "updated":
                if row.status != "created":
                    row.changes.extend(self.changes_of(row.plan))
                if row.status == "unchanged":
                    row.status = "updated"

    def attach_files(self) -> None:
        """Pass three: upload the files rows lack (every file with ``--refresh-files``).

        Every upload is checked first (a required file present, each file
        valid for its serializer field, an image readable as one), and
        nothing reaches the storage unless all of them pass. A dry run
        checks and counts, and uploads nothing.
        """
        uploads: list[tuple[_Row, str, Path]] = []
        for row in self.rows:
            for name in sorted(row.plan.required_files):
                if name not in row.files and not getattr(row.instance, name):
                    self.report.problem(
                        row.plan.label,
                        row.label,
                        name,
                        f"this file is required. Give its path, relative to {self.path.name}.",
                    )
            for name, path in row.files.items():
                if getattr(row.instance, name) and not self.refresh_files:
                    continue
                message = self.invalid_file(row.plan, name, path)
                if message:
                    self.report.problem(row.plan.label, row.label, name, message)
                    continue
                uploads.append((row, name, path))
        if self.report.problems:
            return
        for row, name, path in uploads:
            self.report.counts(row.plan.label).files += 1
            if row.status != "created":
                row.changes.append((f"{name} (file)", "", repr(path.name)))
            if row.status == "unchanged":
                row.status = "updated"
            if self.dry_run:
                continue
            with path.open("rb") as handle:
                getattr(row.instance, name).save(path.name, File(handle), save=True)

    def invalid_file(self, plan: _Plan, name: str, path: Path) -> str:
        """Why the API would refuse this file for ``name`` (``""`` when it accepts it)."""
        serializer_field = plan.file_fields.get(name)
        if serializer_field is None:
            return ""
        with path.open("rb") as handle:
            try:
                serializer_field.run_validation(File(handle, name=path.name))
            except serializers.ValidationError as exc:
                detail = exc.detail
                if isinstance(detail, list | tuple) and detail:
                    return f"{path.name}: {detail[0]}"
                return f"{path.name}: {detail}"
            except DjangoValidationError as exc:  # an image field checks with Django's form field
                return f"{path.name}: {exc.messages[0]}"
        return ""

    def count(self) -> None:
        for row in self.rows:
            counts = self.report.counts(row.plan.label)
            if row.status == "created":
                counts.created += 1
                counts.changes.append(RowChange(row.label, "created"))
            elif row.status == "updated":
                counts.updated += 1
                counts.changes.append(RowChange(row.label, "updated", list(row.changes)))
            else:
                counts.unchanged += 1

    def after_import(self) -> None:
        """``Karni.after_import`` once per model, with that model's counts and touched pks."""
        by_model: dict[type[models.Model], list[_Row]] = {}
        for row in self.rows:
            by_model.setdefault(row.plan.model, []).append(row)
        for model, rows in by_model.items():
            after = rows[0].plan.importer.options.after
            if after is None:
                continue
            counts = self.report.counts(model._meta.label)
            result = ImportResult(
                rows_total=len(rows),
                created=counts.created,
                updated=counts.updated,
                unchanged=counts.unchanged,
                touched=[str(row.instance.pk) for row in rows if row.status != "unchanged"],
            )
            after(result)


def load_content(
    path: Path | str,
    *,
    actor: Any = None,
    dry_run: bool = False,
    refresh_files: bool = False,
    prune: bool = False,
    importer_class: type[ContentImporter] = ContentImporter,
) -> LoadReport:
    """Load the content file at ``path`` (see the module docstring) and return what was done.

    :param actor: the user the writes are attributed to (``None``: nobody).
    :param dry_run: run everything inside a transaction and roll it back.
    :param refresh_files: upload every file again, not only the missing ones.
    :param prune: delete children of a listed parent that its list does not name.
    :param importer_class: the :class:`ContentImporter` (or a subclass) rows go through.
    :raises LoadError: ``E804`` for the file, ``E805`` for refused rows. Nothing was written.
    """
    loader = _Loader(
        Path(path),
        actor=actor,
        dry_run=dry_run,
        refresh_files=refresh_files,
        prune=prune,
        importer_class=importer_class,
    )
    return loader.run()
