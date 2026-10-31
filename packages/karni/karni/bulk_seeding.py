"""Experimental. Volume seeding: realistic row counts for performance work, inserted in bulk.

::

    karni seed --volume 100000                      # 100,000 rows per model
    karni seed --volume 100000 --model shop.Order   # only these models (and what they need)

(``manage.py karni_seed --volume``; :func:`karni.seeding.seed` with
``volume=`` is the importable form.)

**What a volume run does.** The models are seeded in the order
:func:`karni.seeding.seed_plan` gives (the targets of a relation before the
model that points at them). Each model's rows are built with the same
factories the demo seed uses, so the inferred values and every
``<app>/seeds.py`` override apply, then written with ``bulk_create`` in
batches (:data:`DEFAULT_BATCH_SIZE`, ``KARNI_SEED_BATCH_SIZE`` or
``--batch-size``). A foreign key is drawn from the target's existing rows
(up to :data:`KEY_POOL_LIMIT` keys), a one-to-one uses each target once, a
relation to the model itself points at rows of earlier batches (so a tree
gets depth), and a many-to-many gets zero to three targets per row. The
timestamps ``auto_now_add`` and ``auto_now`` set are spread over the last 60
days, as in the demo seed. The user model is seeded the demo way, with
``max(3, N / 100)`` users and the demo login.

**Large seed counts take the same path.** A model whose demo run would
create :func:`bulk_threshold` rows or more (``KARNI_SEED_BULK_THRESHOLD``,
default :data:`BULK_THRESHOLD`), for instance from a large ``seed`` count of
``karni.yaml``, is inserted in bulk by a plain ``karni seed`` too.

**Bulk rows skip save().** ``bulk_create`` sends no ``post_save`` and writes
no change history (``Karni.audit``): listeners do not run for volume rows. A
seeder that overrides :meth:`karni.seeding.Seeder.seed` keeps full control:
its model is seeded row by row, through that method.

**Demo rows never mix with real data.** A seed run records how many rows
each table holds once it is done, per database, in
``.karni/local/seeded.json`` (:class:`Ledger`). ``karni seed --volume``
refuses (``E473``) when a table holds another number of rows than the
ledger recorded, because someone else wrote to it, unless ``--reset`` wipes
the tables first or ``--force`` adds rows anyway. A table the ledger has
never seen must be empty.

Override / escape hatches: subclass :class:`BulkSeeder` (``rows``,
``insert``, ``pick_key``, ...) and pass ``bulk=`` to
:func:`karni.seeding.seed`; ``KARNI_SEED_BULK_THRESHOLD`` and
``KARNI_SEED_BATCH_SIZE`` move the numbers; ``KARNI_SEED_LEDGER`` moves the
ledger (a path) or turns it off (``False``: a volume run then needs empty
tables, like the demo seed).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import math
import os
import random
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import factory
from django.conf import settings
from django.db import IntegrityError, models, transaction
from factory.declarations import BaseDeclaration

if TYPE_CHECKING:
    from karni.seeding import Seeder, _Run

__all__ = [
    "BULK_THRESHOLD",
    "DEFAULT_BATCH_SIZE",
    "KEY_POOL_LIMIT",
    "LEDGER_FILE",
    "BulkSeeder",
    "Ledger",
    "batch_size",
    "bulk_threshold",
    "time_class",
    "volume_users",
]

#: Rows per model from which a demo seed run inserts in bulk (``KARNI_SEED_BULK_THRESHOLD``).
BULK_THRESHOLD: Final = 1000
#: Rows per ``bulk_create`` (``KARNI_SEED_BATCH_SIZE``).
DEFAULT_BATCH_SIZE: Final = 2000
#: Target keys a relation draws from.
KEY_POOL_LIMIT: Final = 100_000
#: Many-to-many targets per row, at most.
M2M_FANOUT: Final = 3
#: Distinct values of a free-text field in a bulk run (:meth:`BulkSeeder.pooled`).
TEXT_POOL: Final = 1000
#: Where the ledger lives, relative to the project root (``KARNI_SEED_LEDGER`` moves it).
LEDGER_FILE: Final = Path(".karni") / "local" / "seeded.json"
#: Measured rows per second of the bulk path on a laptop, for :func:`time_class`.
ROWS_PER_SECOND: Final = 4000


def bulk_threshold() -> int:
    """Experimental. ``KARNI_SEED_BULK_THRESHOLD``, else :data:`BULK_THRESHOLD`."""
    value = getattr(settings, "KARNI_SEED_BULK_THRESHOLD", None)
    return int(value) if value else BULK_THRESHOLD


def batch_size() -> int:
    """Experimental. ``KARNI_SEED_BATCH_SIZE``, else :data:`DEFAULT_BATCH_SIZE`."""
    value = getattr(settings, "KARNI_SEED_BATCH_SIZE", None)
    return int(value) if value else DEFAULT_BATCH_SIZE


def volume_users(volume: int) -> int:
    """Experimental. Users a volume run makes: one per hundred rows, at least three."""
    return max(3, math.ceil(volume / 100))


def time_class(rows: int) -> str:
    """Experimental. How long seeding ``rows`` takes in words: ``seconds``, ``minutes``, ..."""
    seconds = rows / ROWS_PER_SECOND
    if seconds < 15:
        return "seconds"
    if seconds < 90:
        return "about a minute"
    if seconds < 15 * 60:
        return "minutes"
    return "an hour or more"


# the ledger


class Ledger:
    """Experimental. How many rows each table held when a seed run finished, per database.

    ``.karni/local/seeded.json`` (machine-local, never committed). A table
    whose row count differs from the recorded one holds rows the seeder did
    not create. ``KARNI_SEED_LEDGER = False`` turns it off: then no table
    counts as seeded.
    """

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, dict[str, int]] = {}
        if path is None:
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        found = loaded.get("databases") if isinstance(loaded, dict) else None
        if isinstance(found, dict):
            self.data = {
                str(name): {str(k): int(v) for k, v in tables.items()}
                for name, tables in found.items()
                if isinstance(tables, dict)
            }

    @classmethod
    def from_settings(cls) -> Ledger:
        from karni.testing._source import project_root

        setting = getattr(settings, "KARNI_SEED_LEDGER", True)
        if setting is False or setting is None:
            return cls(None)
        path = Path(setting) if isinstance(setting, str | Path) else LEDGER_FILE
        return cls(path if path.is_absolute() else project_root() / path)

    @staticmethod
    def database(alias: str = "default") -> str:
        """The database a count belongs to: vendor, name, host and port."""
        from django.db import connections

        conf = connections[alias].settings_dict
        where = f"{conf.get('HOST') or ''}:{conf.get('PORT') or ''}"
        return f"{connections[alias].vendor}:{conf.get('NAME')}@{where}"

    def seeded(self, model: type[models.Model]) -> int | None:
        """The rows the last seed run left in ``model``'s table, ``None`` when none recorded it."""
        return self.data.get(self.database(), {}).get(model._meta.label)

    def foreign(self, plan: Iterable[type[models.Model]]) -> dict[str, tuple[int, int]]:
        """Tables holding rows no seed run left: ``label -> (rows, recorded)``, users aside."""
        from django.contrib.auth import get_user_model

        user = get_user_model()
        found: dict[str, tuple[int, int]] = {}
        for model in plan:
            if model is user:
                continue
            total = model._base_manager.count()
            recorded = self.seeded(model) or 0
            if total and total != recorded:
                found[model._meta.label] = (total, recorded)
        return found

    def record(self, plan: Iterable[type[models.Model]]) -> bool:
        """Store each table's row count now; ``False`` when the file cannot be written."""
        if self.path is None:
            return True
        tables = self.data.setdefault(self.database(), {})
        for model in plan:
            tables[model._meta.label] = model._base_manager.count()
        directory = self.path.parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
            ignore = directory / ".gitignore"
            if directory.name == "local" and not ignore.is_file():
                ignore.write_text("# Machine-local karni state. Never commit it.\n*\n")
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".seeded-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"databases": self.data}, handle, indent=2, sort_keys=True)
                os.replace(tmp, self.path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError:
            return False
        return True


# the bulk path


class _KeyPick(BaseDeclaration):
    """A relation value drawn from the target's keys, as a key-only instance."""

    def __init__(self, seeder: BulkSeeder, target: type[models.Model], relation: Any) -> None:
        super().__init__()
        self.seeder, self.target, self.relation = seeder, target, relation

    def evaluate(self, instance: Any, step: Any, extra: dict[str, Any]) -> Any:
        return self.seeder.pick_key(self.target, self.relation)


class _Pooled(BaseDeclaration):
    """The inner value for the first ``size`` rows, then one of those again (text is costly)."""

    def __init__(self, inner: Any, size: int, rng: random.Random) -> None:
        super().__init__()
        self.inner, self.size, self.random = inner, size, rng
        self.pool: list[Any] = []

    def evaluate(self, instance: Any, step: Any, extra: dict[str, Any]) -> Any:
        if len(self.pool) >= self.size:
            return self.random.choice(self.pool)
        value = (
            self.inner.evaluate_pre(instance, step, extra)
            if isinstance(self.inner, BaseDeclaration)
            else self.inner
        )
        self.pool.append(value)
        return value


class BulkSeeder:
    """Experimental. Builds a model's rows with the run's factory and writes them in batches.

    One per run (:class:`karni.seeding._Run` makes it). Override any method
    and pass ``bulk=YourBulkSeeder`` to :func:`karni.seeding.seed`.
    """

    def __init__(self, run: _Run, *, batch: int | None = None) -> None:
        self.run = run
        self.batch = batch or batch_size()
        self.random = random.Random(f"{run.seed_value}:bulk")
        self.keys: dict[type[models.Model], list[Any]] = {}
        self.stubs: dict[tuple[type[models.Model], Any], Any] = {}
        self.free: dict[Any, list[Any]] = {}
        self.current: type[models.Model] | None = None

    # keys

    def target_keys(self, target: type[models.Model]) -> list[Any]:
        """The keys a relation to ``target`` draws from (the rows that exist, up to the limit)."""
        if target not in self.keys:
            self.keys[target] = list(
                target._base_manager.order_by("pk").values_list("pk", flat=True)[:KEY_POOL_LIMIT]
            )
        return self.keys[target]

    def stub(self, target: type[models.Model], key: Any) -> Any:
        found = self.stubs.get((target, key))
        if found is None:
            found = target(pk=key)
            found._state.adding = False
            self.stubs[(target, key)] = found
        return found

    def pick_key(self, target: type[models.Model], relation: Any) -> Any:
        """A key-only instance of ``target`` for ``relation`` (``None`` for some optional ones)."""
        from karni.seeding import DEMO_SHARE, FILL_RATE

        if relation.null and self.random.random() >= FILL_RATE:
            return None
        if relation.one_to_one:
            free = self.free.get(relation)
            if free is None:
                taken = set(
                    relation.model._base_manager.exclude(
                        **{f"{relation.attname}__isnull": True}
                    ).values_list(relation.attname, flat=True)
                )
                free = self.free[relation] = [k for k in self.target_keys(target) if k not in taken]
                free.reverse()
            return self.stub(target, free.pop()) if free else None
        keys = self.target_keys(target)
        if not keys:
            return None
        if target is self.run.user_model and self.run.demo is not None:
            if self.random.random() < DEMO_SHARE:
                return self.run.demo
        return self.stub(target, self.random.choice(keys))

    # the factory

    def factory(self, model: type[models.Model], seeder: type[Seeder] | None) -> type[Any]:
        """The run's factory for ``model`` with relations drawn from keys and fresh UUID keys."""
        base = self.run.factory(model, seeder)
        declared = seeder.declarations() if seeder is not None else {}
        attrs: dict[str, Any] = {"__module__": __name__}
        for relation in model._meta.concrete_fields:
            if not (relation.is_relation and relation.editable and not relation.auto_created):
                continue
            target = relation.related_model
            if target is None or relation.name in declared:
                continue
            if target._meta.label == "contenttypes.ContentType":
                continue
            attrs[relation.name] = _KeyPick(self, target, relation)
        inherited = getattr(base._meta, "declarations", {})
        for text in model._meta.concrete_fields:
            if self.pooled(model, text) and text.name not in declared and text.name in inherited:
                attrs[text.name] = _Pooled(inherited[text.name], TEXT_POOL, self.random)
        pk = model._meta.pk
        if isinstance(pk, models.UUIDField) and pk.name not in declared:
            stream = self.run.values.fake.random
            attrs[pk.name] = factory.LazyFunction(
                lambda: uuid.UUID(int=stream.getrandbits(128), version=4)
            )
        attrs["Meta"] = type("Meta", (), {"model": model, "skip_postgeneration_save": True})
        return type(f"{model.__name__}BulkFactory", (base,), attrs)

    def pooled(self, model: type[models.Model], field: Any) -> bool:
        """Whether ``field``'s values repeat from a pool of :data:`TEXT_POOL`: free text only.

        Text is the costly value to make. A unique field, a field with
        choices, a slug and an email or URL keep a value of their own per row.
        """
        return (
            isinstance(field, models.CharField | models.TextField)
            and not isinstance(field, models.SlugField | models.EmailField | models.URLField)
            and not field.unique
            and not field.choices
            and not field.primary_key
            and not self.run.builder.is_unique(model, field)
        )

    # rows

    def rows(self, model: type[models.Model], made: type[Any], count: int) -> list[Any]:
        """``count`` unsaved rows of ``model``."""
        return [made.build() for _ in range(count)]

    def fresh_keys(self, model: type[models.Model], rows: list[Any]) -> None:
        """Replace a UUID key an earlier run already used (one query per batch)."""
        pk = model._meta.pk
        if not isinstance(pk, models.UUIDField):
            return
        pending = rows
        attempt = 0
        while pending:  # a replacement can be taken too: ask again until none is
            keys = [row.pk for row in pending]
            used = set(model._base_manager.filter(pk__in=keys).values_list("pk", flat=True))
            pending = [row for row in pending if row.pk in used]
            attempt += 1
            for row in pending:
                row.pk = uuid.uuid5(row.pk, str(attempt))

    def insert(self, model: type[models.Model], rows: list[Any]) -> list[Any]:
        """``bulk_create`` in a savepoint; a clash retries the rows one by one."""
        self.fresh_keys(model, rows)
        try:
            with transaction.atomic():
                created = model._base_manager.bulk_create(rows)
        except IntegrityError:
            created = [self.insert_one(model, row) for row in rows]
        missing = [row for row in created if row.pk is None]
        if missing:  # a backend that returns no keys from a bulk insert
            latest = model._base_manager.order_by("-pk").values_list("pk", flat=True)
            for row, key in zip(reversed(created), latest[: len(created)], strict=False):
                row.pk = key
        return created

    def insert_one(self, model: type[models.Model], row: Any) -> Any:
        from karni.seeding import ATTEMPTS, SeedError

        problem: Exception | None = None
        for _attempt in range(ATTEMPTS):
            try:
                with transaction.atomic():
                    row.save(force_insert=True)
                return row
            except IntegrityError as exc:
                problem = exc
                row = self.current_factory.build()
                self.stamp([row], *self.current_stamps)
                self.fresh_keys(model, [row])
        raise SeedError(
            f"{model._meta.label}: {ATTEMPTS} attempts in a row hit a database constraint "
            f"({problem}). Give the clashing fields distinct values in a Seeder (karni make "
            f"seeder {model.__name__}), e.g. a factory.Sequence.",
            code="E612",
        )

    def many_to_many(
        self, model: type[models.Model], rows: list[Any], declared: Iterable[str]
    ) -> None:
        """Zero to three targets per row on each many-to-many the run seeds, in bulk."""
        skip = set(declared)
        for m2m in model._meta.many_to_many:
            through = m2m.remote_field.through
            target = m2m.related_model
            if m2m.name in skip or not through._meta.auto_created or target not in self.run.plan:
                continue
            keys = self.target_keys(target) if target is not model else [row.pk for row in rows]
            if not keys:
                continue
            source = m2m.m2m_field_name()
            other = m2m.m2m_reverse_field_name()
            links = []
            for row in rows:
                for key in self.random.sample(
                    keys, self.random.randint(0, min(M2M_FANOUT, len(keys)))
                ):
                    links.append(through(**{f"{source}_id": row.pk, f"{other}_id": key}))
            for start in range(0, len(links), self.batch):
                through._base_manager.bulk_create(
                    links[start : start + self.batch], ignore_conflicts=True
                )

    @contextlib.contextmanager
    def backdated(self, model: type[models.Model]) -> Iterator[list[models.Field[Any, Any]]]:
        """``auto_now``/``auto_now_add`` off while the rows carry spread timestamps of their own."""
        stamped = [
            f
            for f in model._meta.concrete_fields
            if isinstance(f, models.DateField)
            and (getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False))
        ]
        saved = [(f, f.auto_now, f.auto_now_add) for f in stamped]  # type: ignore[attr-defined]
        try:
            for f in stamped:
                f.auto_now = f.auto_now_add = False  # type: ignore[attr-defined]
            yield stamped
        finally:
            for f, now, now_add in saved:
                f.auto_now, f.auto_now_add = now, now_add  # type: ignore[attr-defined]

    def stamp(
        self, rows: list[Any], fields: list[models.Field[Any, Any]], saved: dict[str, bool]
    ) -> None:
        anchor = self.run.anchor
        for row in rows:
            created = anchor - dt.timedelta(minutes=self.random.randint(60, 60 * 24 * 60))
            for f in fields:
                value: Any = created
                if saved[f.name]:  # auto_now: some time after creation
                    span = int((anchor - created).total_seconds() // 60)
                    value = created + dt.timedelta(minutes=self.random.randint(0, max(span, 0)))
                if not isinstance(f, models.DateTimeField):
                    value = value.date()
                setattr(row, f.attname, value)

    def seed_model(self, model: type[models.Model], count: int, seeder: type[Seeder] | None) -> int:
        """Write ``count`` rows of ``model`` in batches; the rows written."""
        made = self.factory(model, seeder)
        self.current_factory = made
        declared = seeder.declarations() if seeder is not None else {}
        self_relations = [
            f
            for f in model._meta.concrete_fields
            if f.is_relation and f.related_model is model and f.name not in declared
        ]
        written = 0
        auto_now = {
            f.name: bool(getattr(f, "auto_now", False))
            for f in model._meta.concrete_fields
            if isinstance(f, models.DateField)
        }
        with self.backdated(model) as stamped:
            self.current_stamps = (stamped, auto_now)
            while written < count:
                size = min(self.batch, count - written)
                rows = self.rows(model, made, size)
                self.stamp(rows, stamped, auto_now)
                created = self.insert(model, rows)
                written += len(created)
                if self_relations:  # later batches point at these rows: a tree gets depth
                    self.target_keys(model).extend(row.pk for row in created)
                self.many_to_many(model, created, declared)
                for relation in model._meta.related_objects:
                    if relation.one_to_one:
                        self.free.pop(relation.field, None)
        self.keys.pop(model, None)
        return written
