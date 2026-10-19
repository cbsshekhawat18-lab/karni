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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Final

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
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

__all__ = ["ImportResult", "Importer", "RowProblem"]

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
    """

    def __init__(
        self,
        model: type[Model],
        request: Any,
        *,
        view: Any | None = None,
        serializer_class: type[serializers.BaseSerializer[Any]] | None = None,
    ) -> None:
        from karni.api.access import routed_view
        from karni.api.serializers import build_serializer

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
        key = self.options.key
        if key and key not in used and self.model._meta.pk.name not in used:
            pass  # every row creates; that is allowed, the preview says so
        return found

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
    ) -> None:
        values = {name: value for name, value in values.items() if not _blank(value)}
        if self.options.transform is not None:
            values = dict(self.options.transform(values))
        problems: list[tuple[str, str]] = []
        for name, spec in relation_specs.items():
            if name in values:
                values[name] = self._resolve(spec, values[name], problems)
        if problems:
            result.errors += 1
            for name, message in problems:
                result.problem(line, name, message)
            return
        try:
            existing = self._existing(values)
        except KarniValueError as exc:
            result.errors += 1
            result.problem(line, self.options.key or "", str(exc))
            return
        values.pop(self.model._meta.pk.name, None)  # the key matched; the pk is never written
        if existing is None and not may_create:
            result.errors += 1
            result.problem(line, "", f"you may not add {self.model._meta.verbose_name} rows.")
            return
        if existing is not None and not may_update:
            result.errors += 1
            result.problem(line, "", f"you may not change {self.model._meta.verbose_name} rows.")
            return
        serializer = self.serializer_class(
            instance=existing, data=values, partial=existing is not None, context=self.context
        )
        if not serializer.is_valid():
            result.errors += 1
            for name, message in _messages(serializer.errors):
                result.problem(line, name, message)
            return
        if existing is not None and self._unchanged(existing, serializer.validated_data):
            result.unchanged += 1
            return
        try:
            with transaction.atomic():
                saved = serializer.save(**(self._stamps() if existing is None else {}))
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
            return
        except serializers.ValidationError as exc:
            result.errors += 1
            for name, message in _messages(exc.detail):
                result.problem(line, name, message)
            return
        except (DjangoValidationError, IntegrityError) as exc:
            result.errors += 1
            result.problem(line, "", str(exc).splitlines()[0])
            return
        result.touched.append(str(saved.pk))
        if existing is None:
            result.created += 1
        else:
            result.updated += 1

    def _existing(self, values: dict[str, Any]) -> Any | None:
        key = self.options.key
        pk_name = self.model._meta.pk.name
        if key and key in values:
            lookup, value = key, values[key]
        elif pk_name in values:
            lookup, value = pk_name, values[pk_name]
        else:
            return None
        if isinstance(value, Model):
            value = value.pk
        try:
            found = self.write_queryset().filter(**{lookup: value}).first()
        except (ValueError, DjangoValidationError) as exc:
            raise KarniValueError(f"{lookup}: {value!r} is not a valid value.") from exc
        if found is not None:
            return found
        model_field = self.model._meta.get_field(lookup)
        if getattr(model_field, "unique", False) or model_field.primary_key:
            elsewhere = self.model._default_manager.filter(**{lookup: value}).exists()
            if elsewhere:
                raise KarniValueError(
                    f"a {self.model._meta.verbose_name} with {lookup} {value!r} exists but is "
                    "not in your scope, so it cannot be updated."
                )
        return None

    def _resolve(self, spec: ColumnSpec, value: Any, problems: list[tuple[str, str]]) -> Any:
        """A natural-key (or pk) cell → the target's pk(s), among the rows the user may read."""
        from django.apps import apps

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
        readable, _ = target_read_scope(target._default_manager.all(), self.request)
        conditions = Q(pk=value) if _pk_like(target, value) else Q()
        if spec.lookup:
            conditions = (
                conditions | Q(**{spec.lookup: value}) if conditions else Q(**{spec.lookup: value})
            )
        if not conditions:
            problems.append(
                (spec.name, f"{value!r} is not a valid {target._meta.verbose_name} id.")
            )
            return value
        try:
            matches = list(readable.filter(conditions).values_list("pk", flat=True)[:2])
        except (ValueError, DjangoValidationError):
            matches = []
        if not matches:
            how = f"{spec.lookup} or id" if spec.lookup else "id"
            problems.append(
                (
                    spec.name,
                    f"no {target._meta.verbose_name} with {how} {value!r} (or it is not visible "
                    "to you).",
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
