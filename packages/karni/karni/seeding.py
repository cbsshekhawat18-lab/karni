"""``karni seed``: realistic, deterministic demo data inferred from the models.

::

    karni seed                         # 10 rows per model, seed 0
    karni seed --count 20 --seed 42    # the same 20 rows on every machine
    karni seed --reset                 # wipe the project's tables first
    karni seed --model events.Event    # only these models

(``manage.py karni_seed`` underneath; :func:`seed` is the importable form.)

**What gets seeded.** Every concrete model of the project's own apps, plus
the user model, plus any model a seeder names — ordered so a model's
relation targets are seeded before it. Values come from the same engine as
the test factories (:mod:`karni.testing.values`): a field called ``email``
gets an email at example.com, ``price`` gets money, ``starts_at`` a
near-future datetime; optional fields are mostly filled. Relations point at
rows seeded earlier in the run (or existing rows), so the data is connected;
to-many relations get a few rows each; one-to-one targets are used once.
Unique fields and constraints hold (values embed the row's number; a clash
on a multi-field constraint is retried).

**A demo login.** The first user is ``demo@example.com`` with the password
``karni-password`` (:data:`karni.testing.factories.DEFAULT_PASSWORD`),
staff and superuser, holding every role the API's ``access`` declarations
name; about half of the rows owned through a user FK are the demo user's —
so every screen has data the moment you log in. Users are matched by their
login field, so re-running never duplicates them and ``--reset`` never
deletes them.

**Determinism.** ``--seed`` (default 0) seeds every random choice, UUID
primary keys are drawn from it, integer sequences are reset by ``--reset``,
``created_at``/``updated_at``-style timestamps are backdated from it, and
relative dates are anchored at the start of the current day — so the same
seed gives the same rows, byte for byte, on the same day. (Generated files
and rows created by a field's custom default function are the exceptions.)

**Per-model overrides** live in ``<app>/seeds.py`` (``karni make seeder
<Model>`` writes one)::

    import factory

    from karni.seeding import Seeder

    from events.models import Event


    class EventSeeder(Seeder):
        class Meta:
            model = Event
            count = 30  # rows per run (default: --count; 0 skips the model)

        status = factory.Iterator(["published", "published", "draft"])
        title = factory.Faker("catch_phrase")

Every class attribute other than ``Meta`` overrides one field (a value or
any factory-boy declaration); everything else stays inferred. An explicit
factory in ``<app>/factories.py`` is the base when there is one.

Override / escape hatches: override :meth:`Seeder.seed` for full control of
a model's rows (``context.create(n, **values)``, ``context.pick(Model)``,
``context.random``); subclass :class:`SeedBuilder` (or the value engine) and
pass ``builder=`` to :func:`seed`; ``--model`` narrows the run. Listeners
(:mod:`karni.events`) fire for seeded rows as for any save.
"""

from __future__ import annotations

import datetime as dt
import inspect
import math
import random
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Final

import factory
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, models, transaction
from django.utils import timezone
from django.utils.module_loading import module_has_submodule
from factory.declarations import BaseDeclaration
from factory.random import reseed_random

from karni.errorcodes import KarniError
from karni.testing.factories import DEFAULT_PASSWORD, FactoryBuilder, auto_factory, factory_for
from karni.testing.values import ValueInference

__all__ = [
    "DEFAULT_COUNT",
    "DEFAULT_SEED",
    "DEMO_LOGIN",
    "SeedBuilder",
    "SeedContext",
    "SeedError",
    "SeedReport",
    "Seeder",
    "clear_cache",
    "seed",
    "seed_plan",
    "seeders",
]

DEFAULT_COUNT: Final = 10
DEFAULT_SEED: Final = 0
DEMO_LOGIN: Final = "demo@example.com"
"""The demo user's login (``demo`` when the user model does not log in by email)."""

#: Share of optional (nullable + blank) fields and nullable relations that get a value.
FILL_RATE: Final = 0.85
#: Share of user-FK picks that land on the demo user.
DEMO_SHARE: Final = 0.5
#: Rows a run reads from an existing table to pick relation targets from.
POOL_LIMIT: Final = 200
#: Attempts per row before a database constraint clash is reported.
ATTEMPTS: Final = 10


class SeedError(KarniError):
    """A model cannot be seeded; the message names the model and the fix."""


class Seeder:
    """Per-model seed settings and field overrides, discovered from ``<app>/seeds.py``.

    ``Meta.model`` names the model; ``Meta.count`` pins its rows per run
    (``None`` = ``--count``, ``0`` = skip it). Any other class attribute is a
    field override. Override :meth:`seed` for full control.
    """

    class Meta:
        model: Any = None
        count: int | None = None

    @classmethod
    def target(cls) -> type[models.Model] | None:
        model = getattr(cls.Meta, "model", None)
        if isinstance(model, str):
            return apps.get_model(model)
        return model

    @classmethod
    def row_count(cls, default: int) -> int:
        count = getattr(cls.Meta, "count", None)
        return default if count is None else int(count)

    @classmethod
    def declarations(cls) -> dict[str, Any]:
        """The field overrides: every public non-method attribute of the subclasses."""
        found: dict[str, Any] = {}
        for klass in reversed(cls.__mro__):
            if not issubclass(klass, Seeder) or klass is Seeder:
                continue
            for name, value in vars(klass).items():
                if name.startswith("_") or name == "Meta":
                    continue
                if inspect.isfunction(value) or isinstance(value, classmethod | staticmethod):
                    continue
                found[name] = value
        return found

    def seed(self, context: SeedContext) -> list[Any]:
        """Create this model's rows (default: ``context.count`` inferred rows)."""
        return context.create()


class SeedBuilder(FactoryBuilder):
    """The test :class:`~karni.testing.factories.FactoryBuilder`, tuned for demo data.

    Optional fields are mostly filled (:data:`FILL_RATE`); defaulted choice
    fields vary instead of all taking the default; UUID primary keys and
    datetime/UUID fields with a callable default are drawn from the seed, so
    runs reproduce.
    """

    fill_optional = FILL_RATE

    def declaration(self, model: type[models.Model], field: Any) -> Any:
        random = self.values.fake.random
        if field.primary_key and isinstance(field, models.UUIDField):
            return factory.LazyFunction(lambda: uuid.UUID(int=random.getrandbits(128), version=4))
        reproducible = (
            field.has_default()
            and field.editable
            and not field.auto_created
            and not field.is_relation
            and not field.primary_key
        )
        if reproducible and field.choices:
            return self.choice_value(field)
        if (
            reproducible
            and callable(field.default)
            and isinstance(field, models.DateField | models.TimeField | models.UUIDField)
        ):
            return self.value(model, field)
        return super().declaration(model, field)


# --- discovery -----------------------------------------------------------------------------

_SEEDERS: dict[type[models.Model], type[Seeder]] | None = None


def seeders() -> dict[type[models.Model], type[Seeder]]:
    """Every seeder in installed apps' ``seeds`` modules (``<Model>Seeder`` wins)."""
    global _SEEDERS
    if _SEEDERS is None:
        found: dict[type[models.Model], type[Seeder]] = {}
        for config in apps.get_app_configs():
            if config.module is None or not module_has_submodule(config.module, "seeds"):
                continue
            module = import_module(f"{config.name}.seeds")
            by_model: dict[type[models.Model], list[type[Seeder]]] = {}
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, Seeder)
                    and obj.__module__ == module.__name__
                    and (model := obj.target()) is not None
                ):
                    by_model.setdefault(model, []).append(obj)
            for model, candidates in by_model.items():
                named = [c for c in candidates if c.__name__ == f"{model.__name__}Seeder"]
                found.setdefault(model, (named or candidates)[0])
        _SEEDERS = found
    return _SEEDERS


def clear_cache() -> None:
    """Forget discovered seeders (after adding a ``seeds`` module at runtime)."""
    global _SEEDERS
    _SEEDERS = None


def _seedable(model: type[models.Model]) -> bool:
    meta = model._meta
    return not (
        meta.abstract or meta.proxy or not meta.managed or meta.auto_created or meta.swapped
    )


def _project_models() -> list[type[models.Model]]:
    from karni.testing._source import project_app_configs

    return [
        model
        for config in project_app_configs(infer_root=True)
        for model in config.get_models()
        if _seedable(model)
    ]


def _resolve(model: Any) -> type[models.Model]:
    if isinstance(model, str):
        try:
            return apps.get_model(model)
        except (LookupError, ValueError) as exc:
            raise SeedError(
                f"--model {model}: no such model (use app_label.Model).", code="E614"
            ) from exc
    return model  # type: ignore[no-any-return]


def _edges(model: type[models.Model], members: set[Any], *, hard_only: bool) -> set[Any]:
    found: set[Any] = set()
    for relation in model._meta.concrete_fields:
        target = relation.related_model
        if relation.is_relation and target in members and target is not model:
            if not (hard_only and relation.null):
                found.add(target)
    if not hard_only:
        found |= {m2m.related_model for m2m in model._meta.many_to_many} & (members - {model})
    return found


def _order(chosen: Iterable[type[models.Model]]) -> list[type[models.Model]]:
    members = set(chosen)
    for hard_only in (False, True):
        pending = {model: _edges(model, members, hard_only=hard_only) for model in members}
        ordered: list[type[models.Model]] = []
        while pending:
            ready = sorted(
                (model for model, needs in pending.items() if not needs),
                key=lambda model: model._meta.label,
            )
            if not ready:
                break
            for model in ready:
                ordered.append(model)
                del pending[model]
            for needs in pending.values():
                needs.difference_update(ready)
        if not pending:
            return ordered
    cycle = ", ".join(sorted(model._meta.label for model in pending))
    raise SeedError(
        f"Required relations loop between {cycle}: no seeding order exists. Make one of the "
        "foreign keys nullable, or seed one model yourself in a Seeder.seed() override.",
        code="E611",
    )


def seed_plan(models_: Sequence[Any] | None = None) -> list[type[models.Model]]:
    """The models a run seeds, relation targets first (``models_`` narrows it)."""
    if models_:
        chosen = {_resolve(model) for model in models_}
    else:
        chosen = {get_user_model(), *_project_models(), *seeders()}
    return _order(model for model in chosen if _seedable(model))


# --- the run -----------------------------------------------------------------------------


@dataclass
class SeedReport:
    """What a run did: rows per model, the demo login, the seed, the time."""

    seed: int | str
    count: int
    rows: dict[str, int] = field(default_factory=dict)
    reused: dict[str, int] = field(default_factory=dict)
    demo: str | None = None
    demo_password: str | None = None
    roles: list[str] = field(default_factory=list)
    reset: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def render(self) -> str:
        lines = []
        if self.reset:
            lines.append(f"Reset {len(self.reset)} table(s): {', '.join(self.reset)}")
        lines.append(
            f"Seeded {len(self.rows)} model(s) with seed {self.seed} "
            f"(count {self.count}) in {self.seconds:.1f}s:"
        )
        width = max((len(label) for label in self.rows), default=0)
        for label, total in self.rows.items():
            reused = self.reused.get(label, 0)
            note = f"  ({reused} existing)" if reused else ""
            lines.append(f"  {label:<{width}}  {total:>4}{note}")
        if self.demo:
            roles = f", roles: {', '.join(self.roles)}" if self.roles else ""
            secret = f" / {self.demo_password}" if self.demo_password else " (existing user)"
            lines.append(f"Log in as {self.demo}{secret} (staff{roles}).")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "count": self.count,
            "rows": self.rows,
            "reused": self.reused,
            "demo": self.demo,
            "roles": self.roles,
            "reset": self.reset,
            "seconds": round(self.seconds, 3),
        }


class _Pick(BaseDeclaration):
    """A relation value drawn from the run's pool of target rows."""

    def __init__(self, run: _Run, target: type[models.Model], relation: Any) -> None:
        super().__init__()
        self.run, self.target, self.relation = run, target, relation

    def evaluate(self, instance: Any, step: Any, extra: dict[str, Any]) -> Any:
        if extra:  # a nested override (venue__city=...) creates the row it describes
            return factory_for(self.target).create(**extra)
        return self.run.pick(self.target, self.relation)


@dataclass
class SeedContext:
    """What :meth:`Seeder.seed` works with for one model."""

    model: type[models.Model]
    #: Rows this run should create for the model.
    count: int
    #: The factory rows are created with (inferred values + the seeder's overrides).
    factory: type[Any]
    run: _Run
    #: Fields the seeder declares (left alone by the run's to-many sampling).
    declared: frozenset[str] = frozenset()

    @property
    def random(self) -> Any:
        """The run's seeded ``random.Random``."""
        return self.run.random

    def create(self, count: int | None = None, **values: Any) -> list[Any]:
        """Create ``count`` rows (default :attr:`count`); ``values`` override fields."""
        total = self.count if count is None else count
        return [self.run.create_one(self, values) for _ in range(total)]

    def pick(self, model: type[models.Model]) -> Any:
        """A row of ``model`` from this run's pool (``None`` when there is none)."""
        pool = self.run.pool(model)
        return self.random.choice(pool) if pool else None


class _Run:
    def __init__(
        self,
        *,
        count: int,
        seed_value: int | str,
        now: dt.datetime | None,
        builder: FactoryBuilder | None,
    ) -> None:
        self.count = count
        self.seed_value = seed_value
        anchor = now or timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.values = builder.values if builder is not None else ValueInference(now=anchor)
        self.builder = builder if builder is not None else SeedBuilder(self.values)
        self.random = self.values.fake.random
        self.anchor = self.values.now()
        self.user_model = get_user_model()
        self.pools: dict[type[models.Model], list[Any]] = {}
        self.used_one_to_one: dict[Any, set[Any]] = {}
        self.demo: Any = None
        self.plan: set[type[models.Model]] = set()
        self.report = SeedReport(seed_value, count)

    # --- pools -----------------------------------------------------------------------

    def pool(self, model: type[models.Model]) -> list[Any]:
        if model not in self.pools:
            self.pools[model] = list(model._default_manager.order_by("pk")[:POOL_LIMIT])
        return self.pools[model]

    def pick(self, target: type[models.Model], relation: Any) -> Any:
        if relation.null and self.random.random() >= FILL_RATE:
            return None
        pool = self.pool(target)
        if relation.one_to_one:
            used = self.used_one_to_one.setdefault(relation, set())
            free = [row for row in pool if row.pk not in used]
            if not free:
                return None if relation.null else factory_for(target).create()
            chosen = free[0]
            used.add(chosen.pk)
            return chosen
        if not pool:
            return None if relation.null else factory_for(target).create()
        if target is self.user_model and self.demo is not None:
            if self.random.random() < DEMO_SHARE:
                return self.demo
        return self.random.choice(pool)

    # --- factories -------------------------------------------------------------------

    def factory(self, model: type[models.Model], seeder: type[Seeder] | None) -> type[Any]:
        from karni.testing.factories import explicit_factories

        explicit = explicit_factories().get(model)
        base = explicit or auto_factory(model, builder=self.builder)
        attrs: dict[str, Any] = {"__module__": __name__}
        pk = model._meta.pk
        if explicit is not None and isinstance(pk, models.UUIDField):
            attrs[pk.name] = self.builder.declaration(model, pk)  # drawn from the seed
        for relation in model._meta.concrete_fields:
            if relation.is_relation and relation.editable and not relation.auto_created:
                target = relation.related_model
                if target is not None and target._meta.label != "contenttypes.ContentType":
                    attrs[relation.name] = _Pick(self, target, relation)
        if seeder is not None:
            attrs.update(seeder.declarations())
        meta: dict[str, Any] = {"model": model, "skip_postgeneration_save": True}
        if model is self.user_model:
            attrs["_create"] = classmethod(_get_or_create_user)
        attrs["Meta"] = type("Meta", (), meta)
        seeded: Any = type(f"{model.__name__}SeedFactory", (base,), attrs)
        start = 0 if model is self.user_model else model._base_manager.count()
        seeded.reset_sequence(start, force=True)
        return seeded

    def create_one(self, context: SeedContext, values: dict[str, Any]) -> Any:
        problem: Exception | None = None
        for _attempt in range(ATTEMPTS):
            try:
                with transaction.atomic():
                    row = context.factory.create(**values)
            except IntegrityError as exc:
                problem = exc
                continue
            except ImproperlyConfigured as exc:
                raise SeedError(
                    f"{context.model._meta.label}: {exc} For seeding, override Seeder.seed() "
                    f"(karni make seeder {context.model.__name__}) and pass the row yourself.",
                    code="E613",
                ) from exc
            self.after_create(context, row, values)
            return row
        raise SeedError(
            f"{context.model._meta.label}: {ATTEMPTS} attempts in a row hit a database "
            f"constraint ({problem}). Give the clashing fields distinct values in a Seeder "
            f"(karni make seeder {context.model.__name__}), e.g. a factory.Sequence.",
            code="E612",
        )

    def after_create(self, context: SeedContext, row: Any, values: dict[str, Any]) -> None:
        label = context.model._meta.label
        pool = self.pools.setdefault(context.model, [])
        pool.append(row)
        if getattr(row, "_karni_seed_reused", False):
            self.report.reused[label] = self.report.reused.get(label, 0) + 1
            return
        # A per-row stream: what happens after the INSERT never shifts the values of
        # later rows, whether this row was created now or matched an existing one.
        rng = random.Random(f"{self.seed_value}:{label}:{len(pool)}")
        overridden = set(values) | context.declared
        for m2m in context.model._meta.many_to_many:
            through = m2m.remote_field.through
            target = m2m.related_model
            if m2m.name in overridden or not through._meta.auto_created:
                continue
            if target not in self.plan:  # never e.g. random groups/permissions for users
                continue
            targets = self.pool(target)
            size = rng.randint(0, min(3, len(targets)))
            if size:
                getattr(row, m2m.name).set(rng.sample(targets, size))
        self.backdate(row, rng)

    def backdate(self, row: Any, rng: random.Random) -> None:
        """Deterministic ``auto_now_add`` / ``auto_now`` timestamps (they would be "now")."""
        stamps: dict[str, Any] = {}
        created = self.anchor - dt.timedelta(minutes=rng.randint(60, 60 * 24 * 60))
        for model_field in type(row)._meta.concrete_fields:
            if not isinstance(model_field, models.DateField):
                continue
            value: Any
            if getattr(model_field, "auto_now_add", False):
                value = created
            elif getattr(model_field, "auto_now", False):
                span = int((self.anchor - created).total_seconds() // 60)
                value = created + dt.timedelta(minutes=rng.randint(0, max(span, 0)))
            else:
                continue
            if not isinstance(model_field, models.DateTimeField):
                value = value.date()
            stamps[model_field.name] = value
        if stamps:
            type(row)._base_manager.filter(pk=row.pk).update(**stamps)
            for name, value in stamps.items():
                setattr(row, name, value)

    # --- users -----------------------------------------------------------------------

    def demo_values(self) -> dict[str, Any]:
        model = self.user_model
        login = model.USERNAME_FIELD
        login_field = model._meta.get_field(login)
        values: dict[str, Any] = {
            login: DEMO_LOGIN if isinstance(login_field, models.EmailField) else "demo"
        }
        names = {f.name for f in model._meta.concrete_fields}
        extras = {
            "is_staff": True,
            "is_superuser": True,
            "email_verified": True,
            "first_name": "Demo",
            "last_name": "User",
            "is_active": True,
        }
        values.update({name: value for name, value in extras.items() if name in names})
        return values

    def roles(self) -> list[str]:
        """Every role a routed viewset's ``access`` names (the demo user gets them all)."""
        from karni.api.routers import resolve_router
        from karni.testing.performance import _role_names

        found: set[str] = set()
        for _prefix, viewset, _basename in getattr(resolve_router(), "registry", ()):
            declaration = getattr(viewset, "access", None)
            for slot in ("read", "write", "create"):
                predicate = getattr(declaration, slot, None)
                if predicate is not None:
                    found |= _role_names(predicate)
            for extra in getattr(viewset, "get_extra_actions", list)():
                override = getattr(extra, "kwargs", {}).get("access")
                if override is not None:
                    found |= _role_names(override)
        return sorted(found)

    # --- the run ---------------------------------------------------------------------

    def reset(self, plan: list[type[models.Model]]) -> None:
        from django.core.management.color import no_style

        project = {model for model in _project_models()}
        wiped = [model for model in reversed(plan) if model in project]
        for model in wiped:
            model._base_manager.all().delete()
        tables = {model._meta.db_table for model in wiped}
        tables |= {
            m2m.remote_field.through._meta.db_table
            for model in wiped
            for m2m in model._meta.many_to_many
        }
        sequences = [s for s in connection.introspection.sequence_list() if s["table"] in tables]
        with connection.cursor() as cursor:
            for statement in connection.ops.sequence_reset_by_name_sql(no_style(), sequences):
                cursor.execute(statement)
        self.report.reset = [model._meta.label for model in wiped]  # deletion order

    def run(self, plan: list[type[models.Model]], *, reset: bool) -> SeedReport:
        reseed_random(self.seed_value)
        self.plan = set(plan)
        if reset:
            self.reset(plan)
        registry = seeders()
        for model in plan:
            seeder_class = registry.get(model)
            default = self.count
            if model is self.user_model:
                default = max(3, math.ceil(self.count / 4))
            count = seeder_class.row_count(default) if seeder_class else default
            if count <= 0:
                continue
            declared = frozenset(seeder_class.declarations()) if seeder_class else frozenset()
            context = SeedContext(model, count, self.factory(model, seeder_class), self, declared)
            if model is self.user_model:
                self.demo = context.create(1, **self.demo_values())[0]
                context.count -= 1
                self.seed_demo_roles()
            rows = (seeder_class or Seeder)().seed(context)
            label = model._meta.label
            self.report.rows[label] = len(rows) + (1 if model is self.user_model else 0)
        return self.report

    def seed_demo_roles(self) -> None:
        from karni.accounts.permissions import assign_role

        roles = self.roles()
        for role in roles:
            assign_role(self.demo, role)
        self.report.demo = getattr(self.demo, self.user_model.USERNAME_FIELD)
        reused = getattr(self.demo, "_karni_seed_reused", False)
        self.report.demo_password = None if reused else DEFAULT_PASSWORD
        self.report.roles = roles


def _get_or_create_user(cls: Any, model_class: Any, *args: Any, **kwargs: Any) -> Any:
    """Users are matched by their login field: re-runs reuse them (and never duplicate)."""
    login = model_class.USERNAME_FIELD
    existing = model_class._base_manager.filter(**{login: kwargs.get(login)}).first()
    if existing is not None:
        existing._karni_seed_reused = True
        return existing
    manager = cls._get_manager(model_class)
    return manager.create(*args, **kwargs)


def seed(
    *,
    count: int = DEFAULT_COUNT,
    seed: int | str = DEFAULT_SEED,
    reset: bool = False,
    models: Sequence[Any] | None = None,
    now: dt.datetime | None = None,
    builder: FactoryBuilder | None = None,
) -> SeedReport:
    """Seed demo rows (see the module docstring); returns what was done.

    :param count: rows per model (a seeder's ``Meta.count`` wins).
    :param seed: the random seed — the same seed gives the same rows.
    :param reset: delete the project models' rows (and reset their id
        sequences) first; users are never deleted.
    :param models: only these models (classes or ``"app.Model"`` labels).
    :param now: the anchor relative dates use (default: the start of today).
    :param builder: a :class:`SeedBuilder` (or any FactoryBuilder) to infer with.
    :raises SeedError: naming the model and the fix.
    """
    started = time.perf_counter()
    plan = seed_plan(models)
    run = _Run(count=count, seed_value=seed, now=now, builder=builder)
    with transaction.atomic():
        report = run.run(plan, reset=reset)
    report.seconds = time.perf_counter() - started
    return report
