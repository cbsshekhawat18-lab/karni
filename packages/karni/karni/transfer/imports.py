"""The importer: every row through the generated serializer, in one transaction.

The dry run **is** the run: every row is created or updated inside a
transaction that is rolled back at the end, so the preview's counts and
errors are exactly what the commit will do — uniqueness, ``clean()``, the
database's own constraints and the scope check on created rows included.
Each row runs in its own savepoint, so a failing row is reported and skipped
while the rest go through.

Permissions, all from the viewset's ``access`` declaration (or, for a model
without a routed viewset, the roles' grants directly): creating a row needs
the ``create`` gate, and the row it makes must lie inside that predicate's
scope — "you cannot import rows into another branch"; updating needs the
``write`` gate and the existing row is looked up through the write scope,
so a row that exists elsewhere is "not yours", never silently overwritten;
a field the role may not write is refused by the serializer naming the
roles that may (P3); a relation is resolved by natural key among the rows
the user may read (P2).

Ids: a row is matched by its key (``Karni.import_key`` or the natural key).
The ``id`` column matches existing rows only with ``match_ids`` (an export
from one environment must not update unrelated rows in another), and a
created row keeps the id it gives only with ``keep_ids`` (legacy data),
after which the database sequence is moved past the largest id.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Final

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.color import no_style
from django.db import IntegrityError, connections, router, transaction
from django.db.models import Model, Q
from rest_framework import serializers

from karni.api.access import (
    Access,
    Unscoped,
    apply_rows,
    owner_fields,
    rows_or_exempt,
    target_read_scope,
)
from karni.exceptions import KarniValueError
from karni.meta import import_options, owner_field
from karni.rows import RowFilter
from karni.transfer.fields import ColumnSpec, column_specs, importable

__all__ = ["ImportResult", "Importer", "RowProblem", "advance_sequences"]

#: Row problems kept per run (the counts are always exact).
MAX_PROBLEMS: Final = 200
_PROGRESS_EVERY: Final = 25


@dataclass(frozen=True)
class RowProblem:
    """One thing wrong with one row: its line number in the file, the field, the message."""

    row: int
    field: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass
class ImportResult:
    """What a run did (or, for a dry run, would do)."""

    rows_total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    problems: list[RowProblem] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> int:
        return self.unchanged + self.errors

    def problem(self, row: int, name: str, message: str) -> None:
        if len(self.problems) < MAX_PROBLEMS:
            self.problems.append(RowProblem(row, name, message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_total": self.rows_total,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "skipped": self.skipped,
        }


class _RowFailed(Exception):
    """Raised inside a row's savepoint to roll that row back and report it."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _messages(errors: Any) -> list[tuple[str, str]]:
    """Flatten DRF's error dict into ``(field, message)`` pairs."""
    found: list[tuple[str, str]] = []
    if isinstance(errors, dict):
        for name, detail in errors.items():
            if isinstance(detail, dict):
                found.extend((f"{name}.{sub}", msg) for sub, msg in _messages(detail))
            elif isinstance(detail, list | tuple):
                found.extend((str(name), str(item)) for item in detail)
            else:
                found.append((str(name), str(detail)))
    elif isinstance(errors, list | tuple):
        found.extend(("", str(item)) for item in errors)
    else:
        found.append(("", str(errors)))
    return [(name if name != "non_field_errors" else "", message) for name, message in found]


class Importer:
    """Rows of a file into ``model`` for the user behind ``request``.

    ``view`` is the routed ``BaseViewSet`` serving the model when there is
    one (its ``access`` declaration gates and scopes the import); without a
    viewset the roles' grants do. ``serializer_class`` defaults to the
    viewset's (or the generated one) — the same validation the API runs.

    ``match_ids`` and ``keep_ids`` (experimental) are the two id options of
    an upload: match existing rows by the ``id`` column, and keep the ids of
    created rows (:attr:`write_pk`). Both are off by default.

    Override / escape hatches: :attr:`skip_blank`, :attr:`write_pk`,
    :attr:`match_ids`, :meth:`readable`, :meth:`get_serializer`,
    :meth:`may_create`, :meth:`may_update` and :meth:`write_queryset` are
    what a trusted caller changes (:mod:`karni.transfer.loading` runs the
    same row logic with full access and explicit blanks).
    """

    #: A blank cell (``None`` or an empty string) leaves the field alone. The
    #: content loader sets this ``False``: an explicit null or empty string in
    #: a content file is written.
    skip_blank: bool = True
    #: Appended when a relation's target is not found: the user may lack the
    #: right to see it. A caller with full access sets it to ``""``.
    not_visible_note: str = " (or it is not visible to you)"
    #: A created row keeps the primary key its row gives. It is off for uploads,
    #: where an unknown id creates a new row. The content loader turns it on,
    #: because a row keyed by its id must keep that id to be found again.
    write_pk: bool = False
    #: Experimental. A row whose key matches nothing (or a model without a key) is
    #: matched to an existing row by its ``id`` column. Off, the ``id`` column never
    #: matches: an export from another environment cannot update unrelated rows.
    match_ids: bool = False

    def __init__(
        self,
        model: type[Model],
        request: Any,
        *,
        view: Any | None = None,
        serializer_class: type[serializers.BaseSerializer[Any]] | None = None,
        match_ids: bool | None = None,
        keep_ids: bool | None = None,
    ) -> None:
        from karni.api.access import routed_view
        from karni.api.serializers import build_serializer

        if match_ids is not None:
            self.match_ids = match_ids
        if keep_ids is not None:
            self.write_pk = keep_ids
        #: Rows created with the id the file gave (their sequence moves on at the end).
        self.kept_ids = 0
        self.model = model
        self.request = request
        self.user = getattr(request, "user", None)
        self.view = view if view is not None else routed_view(model, request)
        self.options = import_options(model)
        if serializer_class is not None:
            self.serializer_class = serializer_class
        elif self.view is not None:
            self.serializer_class = self.view.get_serializer_class()
        else:
            self.serializer_class = build_serializer(model)
        self.context: dict[str, Any] = {"request": request}
        if self.view is not None:
            self.context["view"] = self.view
        self.specs: list[ColumnSpec] = column_specs(
            model, self.serializer_class(context=self.context)
        )

    # gates and scopes

    def _declaration(self) -> Access | Unscoped | None:
        return self.view.get_access() if self.view is not None else None

    def _key(self, action: str) -> str:
        return f"{self.model._meta.label_lower}:{action}"

    def may_create(self) -> bool:
        declaration = self._declaration()
        if isinstance(declaration, Unscoped):
            return True
        if isinstance(declaration, Access):
            return bool(declaration.create.bind(self.view, "create").allows(self.request))
        from karni.accounts.roles import user_can

        return user_can(self.user, self._key("add"))

    def may_update(self) -> bool:
        declaration = self._declaration()
        if isinstance(declaration, Unscoped):
            return True
        if isinstance(declaration, Access):
            return bool(declaration.write.bind(self.view, "update").allows(self.request))
        from karni.accounts.roles import user_can

        return user_can(self.user, self._key("change"))

    def _rows(self, slot: str, action: str, permission: str) -> RowFilter:
        declaration = self._declaration()
        if isinstance(declaration, Unscoped):
            return True
        if isinstance(declaration, Access):
            return rows_or_exempt(
                self.view, declaration.slot(slot).bind(self.view, action), self.request
            )
        from karni.accounts.roles import rows_for

        return rows_for(self.user, self.model, permission)

    def write_queryset(self) -> Any:
        """The rows the user may change — where an import looks existing rows up."""
        return apply_rows(
            self.model._default_manager.all(), self._rows("write", "update", "change")
        )

    def readable(self, target: type[Model]) -> Any:
        """The rows of ``target`` a relation cell may name: what the user may read."""
        return target_read_scope(target._default_manager.all(), self.request)[0]

    def get_serializer(
        self, instance: Any | None, data: dict[str, Any]
    ) -> serializers.BaseSerializer[Any]:
        """The serializer one row is validated and saved with (partial for an update)."""
        return self.serializer_class(
            instance=instance, data=data, partial=instance is not None, context=self.context
        )

    def _stamps(self) -> dict[str, Any]:
        """Owner fields stamped on created rows, as the API's ``perform_create`` does."""
        if self.user is None or not getattr(self.user, "is_authenticated", False):
            return {}
        declaration = self._declaration()
        names: tuple[str, ...]
        if self.view is not None and isinstance(declaration, Access | Unscoped):
            names = owner_fields(declaration, self.model)
        else:
            owner = owner_field(self.model)
            names = (owner,) if owner and _user_fk(self.model, owner) else ()
        return dict.fromkeys(names, self.user)

    # the mapping

    def importable(self) -> list[ColumnSpec]:
        return importable(self.specs)

    def validate_mapping(
        self, headers: Sequence[str], mapping: Mapping[str, Any]
    ) -> dict[str, str]:
        """``header → field`` for the mapped headers; unknown or unwritable fields are refused."""
        allowed = {spec.name: spec for spec in self.importable()}
        found: dict[str, str] = {}
        used: dict[str, str] = {}
        for header, target in mapping.items():
            name = str(target or "").strip()
            if not name:
                continue
            if header not in headers:
                raise KarniValueError(f"The file has no column {header!r}.", code="E801")
            if name not in allowed:
                readable = {spec.name for spec in self.specs}
                why = "cannot be written by your role" if name in readable else "does not exist"
                raise KarniValueError(
                    f"Column {header!r} is mapped to {name!r}, which {why} on "
                    f"{self.model.__name__}. Importable fields: {', '.join(sorted(allowed))}.",
                    code="E801",
                )
            if name in used:
                raise KarniValueError(
                    f"Columns {used[name]!r} and {header!r} both map to {name!r}.", code="E801"
                )
            used[name] = header
            found[header] = name
        if not found:
            raise KarniValueError("Map at least one column to a field.", code="E801")
        self.check_id_options()
        return found

    def check_id_options(self) -> None:
        """Refuse ``keep_ids`` for a user who may create rows only inside a scope.

        Inserting a chosen id fails when any row has it, so for a scoped user
        it would tell which ids exist outside their scope. Keeping ids is for
        a role that may create rows anywhere (a data migration). Override to
        change the rule.
        """
        if self.write_pk and self._rows("create", "create", "add") is not True:
            raise KarniValueError(
                f"Keeping ids needs a role that may create {self.model._meta.verbose_name} "
                "rows anywhere, and yours may create them only inside its scope. Import "
                "without keep ids (each row gets a new id), or ask someone whose role may "
                "create every row.",
                code="E801",
            )

    def suggest_mapping(self, headers: Sequence[str]) -> dict[str, str]:
        """Headers matched to importable fields by name or label (case, spaces, dashes aside)."""
        by_norm: dict[str, str] = {}
        for spec in self.importable():
            by_norm.setdefault(_norm(spec.name), spec.name)
            by_norm.setdefault(_norm(spec.label), spec.name)
        suggested: dict[str, str] = {}
        taken: set[str] = set()
        for header in headers:
            name = by_norm.get(_norm(header))
            if name is not None and name not in taken:
                suggested[header] = name
                taken.add(name)
            else:
                suggested[header] = ""
        return suggested

    # the run

    def run(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        mapping: Mapping[str, str],
        *,
        dry_run: bool,
        progress: Callable[[int, int], None] | None = None,
        label: str = "",
        meta: dict[str, Any] | None = None,
    ) -> ImportResult:
        """Create or update one row per line; roll everything back when ``dry_run``."""
        from karni.audit.capture import change_batch

        result = ImportResult(rows_total=len(rows))
        mapped = self.validate_mapping(headers, mapping)
        columns = [
            (index, mapped[header]) for index, header in enumerate(headers) if header in mapped
        ]
        relation_specs = {
            spec.name: spec for spec in self.specs if spec.kind in ("relation", "relations")
        }
        may_create, may_update = self.may_create(), self.may_update()
        self.check_id_options()
        self.kept_ids = 0
        batch_id: int | None = None
        with transaction.atomic():
            batch = (
                nullcontext()
                if dry_run
                else change_batch(
                    "import", label, {**(meta or {}), "model": self.model._meta.label}
                )
            )
            with batch as opened:
                if opened is not None:
                    batch_id = int(opened.pk)
                for position, raw in enumerate(rows):
                    line = position + 2  # the header is line 1
                    values = {name: raw[index] for index, name in columns if index < len(raw)}
                    self._one(line, values, relation_specs, may_create, may_update, result)
                    if progress is not None and (position + 1) % _PROGRESS_EVERY == 0:
                        progress(position + 1, len(rows))
            if dry_run:
                transaction.set_rollback(True)
            elif self.kept_ids:
                advance_sequences([self.model])
        if progress is not None:
            progress(len(rows), len(rows))
        result.batch_id = batch_id  # type: ignore[attr-defined]
        if not dry_run and self.options.after is not None:
            self.options.after(result)
        return result

    def _one(
        self,
        line: int,
        values: dict[str, Any],
        relation_specs: dict[str, ColumnSpec],
        may_create: bool,
        may_update: bool,
        result: ImportResult,
        *,
        match: Sequence[str] = (),
    ) -> tuple[str, Any | None]:
        """One row: ``("created" | "updated" | "unchanged" | "error", the row or None)``.

        ``match`` names more fields whose (resolved) values narrow the lookup
        of the existing row besides the key: a composite key, or a child
        matched among one parent's children rather than across the table.
        """
        values = dict(values)
        if self.skip_blank:
            values = {name: value for name, value in values.items() if not _blank(value)}
        if self.options.transform is not None:
            values = dict(self.options.transform(values))
        problems: list[tuple[str, str]] = []
        for name, spec in relation_specs.items():
            if name in values and not _blank(values[name]):
                values[name] = self._resolve(spec, values[name], problems)
        if problems:
            result.errors += 1
            for name, message in problems:
                result.problem(line, name, message)
            return "error", None
        try:
            existing = self._existing(values, match)
        except KarniValueError as exc:
            result.errors += 1
            result.problem(line, getattr(exc, "field", None) or self.options.key or "", str(exc))
            return "error", None
        pk_field = self.model._meta.pk
        given_pk = values.pop(pk_field.name, None)  # the key matched, never update the pk
        if existing is None and not may_create:
            result.errors += 1
            result.problem(line, "", f"you may not add {self.model._meta.verbose_name} rows.")
            return "error", None
        if existing is not None and not may_update:
            result.errors += 1
            result.problem(line, "", f"you may not change {self.model._meta.verbose_name} rows.")
            return "error", None
        serializer = self.get_serializer(existing, values)
        if not serializer.is_valid():
            result.errors += 1
            for name, message in _messages(serializer.errors):
                result.problem(line, name, message)
            return "error", None
        if existing is not None and self._unchanged(existing, serializer.validated_data):
            result.unchanged += 1
            return "unchanged", existing
        extras: dict[str, Any] = {}
        if existing is None:
            extras = self._stamps()
            if self.write_pk and not _blank(given_pk):
                try:
                    extras[pk_field.attname] = pk_field.to_python(given_pk)
                except DjangoValidationError as exc:
                    result.errors += 1
                    result.problem(line, pk_field.name, f"{given_pk!r}: {exc.messages[0]}")
                    return "error", None
                self.kept_ids += 1
        try:
            with transaction.atomic():
                saved = serializer.save(**extras)
                if existing is None:
                    rows = self._rows("create", "create", "add")
                    inside = rows is True or (
                        rows is not False
                        and apply_rows(
                            self.model._default_manager.filter(pk=saved.pk), rows
                        ).exists()
                    )
                    if not inside:
                        result.problem(line, "", "the row would be outside your scope.")
                        raise _RowFailed
        except _RowFailed:
            result.errors += 1
            return "error", None
        except serializers.ValidationError as exc:
            result.errors += 1
            for name, message in _messages(exc.detail):
                result.problem(line, name, message)
            return "error", None
        except (DjangoValidationError, IntegrityError) as exc:
            result.errors += 1
            result.problem(line, "", str(exc).splitlines()[0])
            return "error", None
        result.touched.append(str(saved.pk))
        if existing is None:
            result.created += 1
            return "created", saved
        result.updated += 1
        return "updated", saved

    def _existing(self, values: dict[str, Any], match: Sequence[str] = ()) -> Any | None:
        """The row ``values`` updates: by its key first, by its id only when asked.

        A key (``Karni.import_key``, else the natural key) that matches no row
        in the write scope creates one, unless a row outside the scope holds
        it (it is unique). The ``id`` column is read only with
        :attr:`match_ids`, or when the key is the primary key: an id that
        matches nothing in the scope is refused (or, with :attr:`write_pk`,
        created with that id), and nothing is looked up outside the scope, so
        the answer never tells whether an id exists. Both refusals read the
        same: "not found or not in your scope".
        """
        key = self.options.key
        pk_name = self.model._meta.pk.name
        if key and key in values:
            found = self._find(values, key, match)
            if found is not None or key == pk_name:
                return self._by_id(values[key], found)
            model_field = self.model._meta.get_field(key)
            if not match and getattr(model_field, "unique", False):
                value = _plain(values[key])
                if self.model._default_manager.filter(**{key: value}).exists():
                    raise KarniValueError(self.not_in_scope(key, value))
            if not (self.match_ids and pk_name in values):
                return None
        elif not (self.match_ids and pk_name in values):
            return None
        return self._by_id(values[pk_name], self._find(values, pk_name, ()))

    def _find(self, values: dict[str, Any], lookup: str, match: Sequence[str]) -> Any | None:
        """The row in the write scope whose ``lookup`` (and ``match`` fields) ``values`` give."""
        value = _plain(values[lookup])
        conditions = {lookup: value}
        for name in match:
            conditions[name] = _plain(values.get(name))
        try:
            return self.write_queryset().filter(**conditions).first()
        except (ValueError, DjangoValidationError) as exc:
            raise KarniValueError(f"{lookup}: {value!r} is not a valid value.") from exc

    def _by_id(self, value: Any, found: Any | None) -> Any | None:
        """A row matched by id: found, created with that id (``keep_ids``), or refused."""
        if found is not None or self.write_pk:
            return found
        pk_name = self.model._meta.pk.name
        refused = KarniValueError(
            self.not_in_scope(pk_name, _plain(value))
            + " Leave the id empty to add the row with a new id."
        )
        refused.field = pk_name  # type: ignore[attr-defined]
        raise refused

    def not_in_scope(self, lookup: str, value: Any) -> str:
        """The refusal for a key or id the write scope does not hold, existing or not."""
        return (
            f"{self.model._meta.verbose_name} with {lookup} {value!r}: not found or not in "
            "your scope, so the row is not imported."
        )

    def _resolve(self, spec: ColumnSpec, value: Any, problems: list[tuple[str, str]]) -> Any:
        """A natural-key cell (a pk cell for a target without one) → the target's pk(s).

        Looked up among the rows the user may read.
        """
        from django.apps import apps

        if isinstance(value, Model):
            return value.pk  # a row the caller resolved (a nested child's parent)
        target = apps.get_model(spec.target) if spec.target else None
        if target is None:
            return value
        if spec.kind == "relations":
            parts = (
                [p.strip() for p in str(value).split("|")] if not isinstance(value, list) else value
            )
            return [
                self._lookup(target, spec, part, problems) for part in parts if not _blank(part)
            ]
        return self._lookup(target, spec, value, problems)

    def _lookup(
        self, target: type[Model], spec: ColumnSpec, value: Any, problems: list[tuple[str, str]]
    ) -> Any:
        readable = self.readable(target)
        # A target with a natural key is named by it alone: a numeric name ("2024",
        # a SKU) is never read as a primary key. Karni.import_lookup = {"venue": "id"}
        # makes the column carry ids instead.
        if spec.lookup:
            conditions = Q(**{spec.lookup: value})
        elif _pk_like(target, value):
            conditions = Q(pk=value)
        else:
            problems.append(
                (spec.name, f"{value!r} is not a valid {target._meta.verbose_name} id.")
            )
            return value
        try:
            matches = list(readable.filter(conditions).values_list("pk", flat=True)[:2])
        except (ValueError, DjangoValidationError):
            matches = []
        if not matches:
            how = spec.lookup or "id"
            problems.append(
                (
                    spec.name,
                    f"no {target._meta.verbose_name} with {how} {value!r}{self.not_visible_note}.",
                )
            )
            return value
        if len(matches) > 1:
            problems.append(
                (spec.name, f"{value!r} matches more than one {target._meta.verbose_name}.")
            )
            return value
        return matches[0]

    def _unchanged(self, instance: Any, validated: dict[str, Any]) -> bool:
        for name, value in validated.items():
            try:
                model_field = self.model._meta.get_field(name)
            except Exception:  # noqa: BLE001 - a serializer-only field: assume changed
                return False
            if getattr(model_field, "many_to_many", False):
                current = {str(pk) for pk in getattr(instance, name).values_list("pk", flat=True)}
                wanted = {str(getattr(item, "pk", item)) for item in value}
                if current != wanted:
                    return False
            elif getattr(model_field, "is_relation", False):
                if str(getattr(instance, model_field.attname)) != str(getattr(value, "pk", value)):
                    return False
            elif getattr(instance, name) != value:
                return False
        return True


def _plain(value: Any) -> Any:
    """A lookup value: a resolved relation's primary key, anything else as given."""
    return value.pk if isinstance(value, Model) else value


def advance_sequences(models: Sequence[type[Model]]) -> None:
    """Move each model's id sequence past its largest id, after rows were written with ids.

    A row inserted with an explicit integer id leaves PostgreSQL's sequence
    where it was, so the next insert without an id would collide. This sets
    it to the largest id (``setval``, Django's ``sequence_reset_sql``). SQLite
    and UUID keys need nothing, and get no statement.
    """
    by_alias: dict[str, list[type[Model]]] = {}
    for model in models:
        by_alias.setdefault(router.db_for_write(model) or "default", []).append(model)
    for alias, group in by_alias.items():
        connection = connections[alias]
        statements = connection.ops.sequence_reset_sql(no_style(), group)
        if statements:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)


def _pk_like(model: type[Model], value: Any) -> bool:
    try:
        model._meta.pk.to_python(value)
    except (DjangoValidationError, ValueError, TypeError):
        return False
    return True


def _user_fk(model: type[Model], name: str) -> bool:
    from django.contrib.auth import get_user_model

    try:
        relation = model._meta.get_field(name)
    except Exception:  # noqa: BLE001
        return False
    return bool(
        getattr(relation, "many_to_one", False) and relation.related_model is get_user_model()
    )


def _norm(text: str) -> str:
    return "".join(
        ch
        for ch in str(text).lower().replace("-", "_").replace(" ", "_")
        if ch.isalnum() or ch == "_"
    )
