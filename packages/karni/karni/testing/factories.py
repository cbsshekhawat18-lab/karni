"""Automatic factory-boy factories for any model — Karni's test-data foundation.

No project code is needed to create valid rows::

    from karni.testing.factories import build, create, create_batch, factory_for

    event = create(Event)                      # required fields filled, FKs created
    events = create_batch(Event, 5, venue=v)   # any field can be overridden
    draft = build(Event)                       # unsaved (related rows unsaved too)
    EventFactory = factory_for(Event)          # a factory.django.DjangoModelFactory

**Resolution.** :func:`factory_for` returns the model's *explicit* factory
when a project defines one, otherwise a generated one (cached per model):

* explicit — any ``DjangoModelFactory`` subclass defined in an installed
  app's ``<app>/factories.py`` whose ``Meta.model`` is the model (when one
  module defines several, the one named ``<Model>Factory`` wins, else the
  first defined). Explicit factories are used everywhere: as related-object
  factories inside generated ones, by ``karni seed`` and by the N+1 scaling
  check of :mod:`karni.testing.performance`. Derive them from
  :class:`ModelFactory` and declare only what differs — every other field
  keeps its generated declaration::

      class EventFactory(ModelFactory):
          class Meta:
              model = Event

          status = "published"

* generated — :class:`FactoryBuilder` declares a value for every field
  that needs one.

**Generated values** (:class:`FactoryBuilder` decides *which* fields get a
value; :mod:`karni.testing.values` decides *what* value — by field name, then
type — and is the same engine ``karni seed`` uses):

======================================  ===============================================
Field                                   Value
======================================  ===============================================
auto / defaulted / non-editable         left to the model (``id``, ``created_at``,
                                        ``created_by``, ``deleted_at`` …)
``choices``                             cycles through the choice values
a known name (``email``, ``price``,     a realistic value: ``email`` an address at
``starts_at``, ``city`` …)              example.com, ``price`` money, ``starts_at`` a
                                        near-future datetime (:data:`~karni.testing.
                                        values.NAME_RULES`)
any other field                         a realistic value for its type, inside
                                        ``max_length``, the type's range, the
                                        Min/MaxValueValidators and ``max_digits``
unique field / unique constraint        the value embeds the row's sequence number
nullable + blank non-relation field     ``None`` (nullable but not blank: a value)
file / image                            a small file (left empty when ``blank``)
ForeignKey / OneToOneField              the target's factory (``factory_for(target)``);
                                        a nullable FK stays ``None`` on a cycle or below
                                        :attr:`FactoryBuilder.max_depth`
ManyToManyField                         empty, or ``create(M, tags=[t1, t2])`` /
                                        ``create(M, tags=3)`` (creates three)
user model ``password``                 :data:`DEFAULT_PASSWORD`, hashed once per process
anything else that is required          an error *when used* naming the fix — pass the
                                        field, or write an explicit factory
======================================  ===============================================

Random choices come from Faker's shared generator: the ``karni`` pytest
plugin reseeds it per test, so a failing test reproduces.

Override / escape hatches: keyword overrides on every call (including
factory-boy's ``venue__city="Pune"`` and ``tags__through_defaults={...}``);
an explicit factory in ``<app>/factories.py``; or subclass
:class:`FactoryBuilder` (structure) / :class:`~karni.testing.values.
ValueInference` (values) and call :func:`auto_factory` with
``FactoryBuilder(values=...)``.
"""

from __future__ import annotations

import decimal
from collections.abc import Callable
from contextvars import ContextVar
from functools import lru_cache
from importlib import import_module
from typing import Any, Final

import factory
from django.apps import apps
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.hashers import make_password
from django.core import validators
from django.db import models
from django.utils.module_loading import module_has_submodule
from factory.base import FactoryMetaClass
from factory.declarations import BaseDeclaration
from factory.django import DjangoModelFactory

from karni.exceptions import KarniImproperlyConfigured, KarniTypeError
from karni.testing.values import MISSING, ValueInference, unique_field_names

__all__ = [
    "DEFAULT_PASSWORD",
    "AutoFactory",
    "AutoSubFactory",
    "FactoryBuilder",
    "ModelFactory",
    "auto_factory",
    "build",
    "clear_cache",
    "create",
    "create_batch",
    "explicit_factories",
    "factory_for",
    "hashed_password",
]

DEFAULT_PASSWORD: Final = "karni-password"
"""Password of every user created by a generated factory (tests can log in with it)."""

SKIP: Final = object()
"""Returned by :meth:`FactoryBuilder.declaration` for fields left to the model."""

#: Models being created, outermost first — cycle and depth guard for FKs.
_CHAIN: ContextVar[tuple[type[models.Model], ...]] = ContextVar("karni_factory_chain", default=())

#: A fixed salt: generated users share one hash per password (hashed once, deterministic).
_SALT: Final = "karnigeneratedusers0001"

ModelRef = type[models.Model] | str


def _model(model: ModelRef) -> type[models.Model]:
    if isinstance(model, str):
        return apps.get_model(model)
    if not (isinstance(model, type) and issubclass(model, models.Model)):
        raise KarniTypeError(
            f"expected a model class or 'app_label.Model', got {model!r}", code="E609"
        )
    if model._meta.abstract:
        raise KarniImproperlyConfigured(
            f"{model.__name__} is abstract; factories need a concrete model.", code="E609"
        )
    return model


@lru_cache(maxsize=64)
def _hash(raw: str, hashers: tuple[str, ...]) -> str:
    return make_password(raw, salt=_SALT)


def hashed_password(raw: str | None) -> str:
    """``make_password(raw)`` with a fixed salt, computed once per password and hasher setup.

    Generated users (tests and ``karni seed``) all share it: hashing with the
    production hasher costs ~0.3 s, and a fixed salt keeps seeded rows
    byte-for-byte reproducible. ``None`` gives an unusable password.
    """
    if raw is None:
        return make_password(None)
    return _hash(raw, tuple(settings.PASSWORD_HASHERS))


class AutoFactory(DjangoModelFactory):
    """Base of every generated factory: tracks the creation chain for FK cycles."""

    class Meta:
        abstract = True
        skip_postgeneration_save = True

    @classmethod
    def _generate(cls, strategy: Any, params: dict[str, Any]) -> Any:
        from karni.lifecycle import any_initial_state

        model = cls._meta.get_model_class()
        token = _CHAIN.set((*_CHAIN.get(), model))
        try:
            # Test data and seeds may start a row in any declared state
            # (StateField's initial rule is for application writes).
            with any_initial_state("karni.testing factory (test data / seed)"):
                return super()._generate(strategy, params)
        finally:
            _CHAIN.reset(token)


class AutoSubFactory(factory.SubFactory):
    """A ``SubFactory`` resolved lazily through :func:`factory_for`, with cycle/depth guards.

    A nullable relation becomes ``None`` when its model is already being
    created up the chain or the chain is :attr:`FactoryBuilder.max_depth`
    deep; a required one on a cycle raises (pass an instance instead).
    Explicit nested overrides (``venue__name="x"``) always create.
    """

    def __init__(self, model: type[models.Model], *, nullable: bool, max_depth: int) -> None:
        super().__init__(AutoFactory)
        self.model = model
        self.nullable = nullable
        self.max_depth = max_depth

    def get_factory(self) -> type[DjangoModelFactory]:
        return factory_for(self.model)

    def evaluate(self, instance: Any, step: Any, extra: dict[str, Any]) -> Any:
        chain = _CHAIN.get()
        if not extra:
            if self.nullable and (self.model in chain or len(chain) >= self.max_depth):
                return None
            if self.model in chain:
                path = " -> ".join(model.__name__ for model in (*chain, self.model))
                raise KarniImproperlyConfigured(
                    f"Cannot generate {path}: a required relation loops back. Pass an existing "
                    "row for that field, or define an explicit factory in <app>/factories.py.",
                    code="E611",
                )
        token = _CHAIN.set((*chain, self.model))
        try:
            return super().evaluate(instance, step, extra)
        finally:
            _CHAIN.reset(token)


class OptionalValue(BaseDeclaration):
    """``inner`` with probability ``rate``, else ``None`` (optional fields in seeds)."""

    def __init__(self, inner: Any, rate: float, values: ValueInference) -> None:
        super().__init__()
        self.inner, self.rate, self.values = inner, rate, values

    def evaluate(self, instance: Any, step: Any, extra: dict[str, Any]) -> Any:
        if self.values.fake.random.random() >= self.rate:
            return None
        if isinstance(self.inner, BaseDeclaration):
            return self.inner.evaluate_pre(instance, step, extra)
        return self.inner


def _m2m_hook(name: str, target: type[models.Model]) -> Callable[..., None]:
    def hook(obj: models.Model, create: bool, extracted: Any, **kwargs: Any) -> None:
        if not create or extracted is None:
            return
        if isinstance(extracted, int) and not isinstance(extracted, bool):
            extracted = factory_for(target).create_batch(extracted)
        elif isinstance(extracted, models.Model):
            # One row, e.g. the user an `own` path through a many-to-many
            # (owner_field = "workspace__members") makes the owner.
            extracted = [extracted]
        getattr(obj, name).set(list(extracted), through_defaults=kwargs.get("through_defaults"))

    hook.__name__ = f"set_{name}"
    return hook


def _missing_value(model: type[models.Model], field: models.Field[Any, Any]) -> Any:
    def fail() -> Any:
        raise KarniImproperlyConfigured(
            f"karni.testing.factories cannot generate {model.__name__}.{field.name} "
            f"({type(field).__name__}); pass it (create({model.__name__}, {field.name}=...)) or "
            "define an explicit factory in <app>/factories.py.",
            code="E610",
        )

    return factory.LazyFunction(fail)


def _bounds(field: models.Field[Any, Any], low: float, high: float) -> tuple[float, float]:
    for validator in field.validators:
        if isinstance(validator, validators.MinValueValidator) and not callable(
            validator.limit_value
        ):
            low = max(low, validator.limit_value)
        elif isinstance(validator, validators.MaxValueValidator) and not callable(
            validator.limit_value
        ):
            high = min(high, validator.limit_value)
    return low, high


#: Ranges of the ``number_value`` compatibility hook (used when a subclass overrides it).
_LEGACY_INT_RANGES: Final[tuple[tuple[type[models.Field[Any, Any]], int, int], ...]] = (
    (models.PositiveSmallIntegerField, 0, 32767),
    (models.PositiveBigIntegerField, 0, 9223372036854775807),
    (models.PositiveIntegerField, 0, 2147483647),
    (models.SmallIntegerField, 0, 32767),
    (models.BigIntegerField, 0, 9223372036854775807),
    (models.IntegerField, 0, 2147483647),
)


class FactoryBuilder:
    """Turns a model into a factory-boy factory. Subclass to change any rule.

    :param values: the value engine (default :class:`~karni.testing.values.
        ValueInference`), shared with ``karni seed``.

    :attr:`max_depth` bounds how deep nullable FKs are filled (required FKs
    are always created). :attr:`fill_optional` is the probability that a
    nullable + blank field gets a value instead of ``None`` (``0`` for tests,
    raised by seeding). :meth:`declaration` decides per field;
    :meth:`relation_value`, :meth:`choice_value` and :meth:`value` produce
    the declarations.
    """

    max_depth: int = 3
    fill_optional: float = 0.0

    def __init__(self, values: ValueInference | None = None) -> None:
        self.values = values if values is not None else ValueInference()
        self._unique: dict[type[models.Model], frozenset[str]] = {}

    def build(self, model: type[models.Model]) -> type[DjangoModelFactory]:
        """A new ``AutoFactory`` subclass for ``model``."""
        attrs: dict[str, Any] = {
            "Meta": type("Meta", (), {"model": model, "skip_postgeneration_save": True}),
            "__module__": __name__,
            "__doc__": f"Generated factory for {model._meta.label} (karni.testing.factories).",
            **self.declarations(model),
        }
        return type(f"{model.__name__}AutoFactory", (AutoFactory,), attrs)

    def declarations(self, model: type[models.Model]) -> dict[str, Any]:
        """Every field declaration of the generated factory (M2M hooks included)."""
        found: dict[str, Any] = {}
        for field in model._meta.concrete_fields:
            value = self.declaration(model, field)
            if value is not SKIP:
                found[field.name] = value
        for m2m in model._meta.many_to_many:
            found[m2m.name] = factory.PostGeneration(_m2m_hook(m2m.name, m2m.related_model))
        return found

    def is_unique(self, model: type[models.Model], field: models.Field[Any, Any]) -> bool:
        """True when ``field`` is unique or part of a unique constraint."""
        names = self._unique.get(model)
        if names is None:
            names = self._unique[model] = unique_field_names(model)
        return field.name in names

    def declaration(self, model: type[models.Model], field: models.Field[Any, Any]) -> Any:
        """The declaration for ``field``, or :data:`SKIP` to leave it to the model."""
        if field.auto_created or not field.editable:
            return SKIP
        if field.primary_key and (field.has_default() or isinstance(field, models.AutoField)):
            return SKIP
        if issubclass(model, AbstractBaseUser) and field.name == "password":
            return factory.django.Password(DEFAULT_PASSWORD, transform=hashed_password)
        if field.is_relation:
            return self.relation_value(model, field)
        if field.has_default():
            return SKIP
        if field.null and field.blank:
            if not self.fill_optional:
                return None
            filled = self.choice_value(field) if field.choices else self.value(model, field)
            if filled is SKIP:
                return None
            return OptionalValue(filled, self.fill_optional, self.values)
        if field.choices:
            return self.choice_value(field)
        return self.value(model, field)

    def relation_value(self, model: type[models.Model], field: Any) -> Any:
        """FK/O2O: the target's factory (``ContentType``: the model's own content type)."""
        target = field.related_model
        if field.has_default():
            return SKIP
        if target._meta.label == "contenttypes.ContentType":
            from django.contrib.contenttypes.models import ContentType

            return factory.LazyFunction(lambda: ContentType.objects.get_for_model(model))
        return AutoSubFactory(target, nullable=field.null, max_depth=self.max_depth)

    def choice_value(self, field: models.Field[Any, Any]) -> Any:
        """Cycle through the field's (flattened) choice values."""
        values = [value for value, _label in field.flatchoices]
        if not field.blank:
            values = [value for value in values if value not in validators.EMPTY_VALUES] or values
        return factory.Iterator(values)

    def value(self, model: type[models.Model], field: Any) -> Any:
        """The declaration for a required, non-relation, non-choice field without a default.

        Files and images get a small file (none when ``blank``); everything
        else comes from :attr:`values` (name rules, then the type).
        """
        legacy = self._legacy_value(model, field)
        if legacy is not None:
            return legacy
        if isinstance(field, models.ImageField):
            return self.image_value(field)
        if isinstance(field, models.FileField):
            if field.blank:
                return SKIP
            return factory.django.FileField(filename=f"{field.name}.txt", data=b"karni")
        declaration = self.values.declaration(model, field, unique=self.is_unique(model, field))
        if declaration is MISSING:
            return _missing_value(model, field)
        return declaration

    def image_value(self, field: Any) -> Any:
        if field.blank:
            return SKIP
        try:
            import PIL  # noqa: F401
        except ImportError:
            return factory.django.FileField(filename=f"{field.name}.png", data=b"karni")
        return factory.django.ImageField(filename=f"{field.name}.png")

    # compatibility value hooks
    # Phase 12a's per-type hooks. Overriding one still replaces that type's values
    # (and bypasses name rules for it); new code overrides ValueInference instead.

    def text_value(self, field: Any, stem: str) -> Any:
        """Compatibility hook: ``"<stem>-<n>"``; used only when a subclass overrides it."""
        max_length = field.max_length or 255

        def make(n: int) -> str:
            suffix = f"-{n}"
            return stem[: max(max_length - len(suffix), 0)] + suffix

        return factory.Sequence(make)

    def number_value(self, field: models.Field[Any, Any], low: float, high: float) -> Any:
        """Compatibility hook: a sequence in ``[low, high]``; used only when overridden."""
        low, high = _bounds(field, low, high)
        if isinstance(field, models.FloatField):
            return factory.Sequence(lambda n: float(low + n % max(int(high - low), 1)))
        start, span = int(low), max(int(high) - int(low) + 1, 1)
        return factory.Sequence(lambda n: start + n % span)

    def decimal_value(self, field: models.DecimalField[Any]) -> Any:
        """Compatibility hook: a sequence within ``max_digits``; used only when overridden."""
        places = field.decimal_places or 0
        whole = max((field.max_digits or 10) - places, 0)
        low, high = _bounds(field, 0, 10**whole - 1 if whole else 0)
        quantum = decimal.Decimal(1).scaleb(-places)
        span = max(int(high) - int(low) + 1, 1)
        return factory.Sequence(lambda n: (decimal.Decimal(int(low) + n % span)).quantize(quantum))

    def _legacy_value(self, model: type[models.Model], field: Any) -> Any:
        """The compatibility hooks, only when a subclass overrides them."""
        cls = type(self)
        if cls.text_value is not FactoryBuilder.text_value:
            if isinstance(field, models.SlugField):
                return self.text_value(field, field.name.replace("_", "-"))
            if isinstance(field, models.CharField | models.TextField) and not isinstance(
                field, models.EmailField | models.URLField
            ):
                return self.text_value(field, field.name)
        if cls.decimal_value is not FactoryBuilder.decimal_value:
            if isinstance(field, models.DecimalField):
                return self.decimal_value(field)
        if cls.number_value is not FactoryBuilder.number_value:
            if isinstance(field, models.FloatField):
                return self.number_value(field, 0, 1_000_000)
            for kind, low, high in _LEGACY_INT_RANGES:
                if isinstance(field, kind):
                    return self.number_value(field, low, high)
        return None


# explicit factories that keep the generated declarations


class _AutoFillMeta(FactoryMetaClass):  # type: ignore[misc]
    """Fills every field a :class:`ModelFactory` subclass does not declare."""

    def __new__(mcs, class_name: str, bases: tuple[type, ...], attrs: dict[str, Any]) -> Any:
        meta = attrs.get("Meta")
        model = getattr(meta, "model", None)
        if model is not None and not getattr(meta, "abstract", False):
            declared = set(attrs)
            builder: FactoryBuilder | None = attrs.get("_builder")
            for base in bases:
                base_meta = getattr(base, "_meta", None)
                if base_meta is not None:
                    declared |= set(base_meta.base_declarations) | set(base_meta.parameters)
                builder = builder or getattr(base, "_builder", None)
            params = attrs.get("Params")
            if params is not None:
                declared |= {name for name in vars(params) if not name.startswith("_")}
            fill = (builder or FactoryBuilder()).declarations(_model(model))
            for name, declaration in fill.items():
                if name not in declared:
                    attrs[name] = declaration
        return super().__new__(mcs, class_name, bases, attrs)


class ModelFactory(AutoFactory, metaclass=_AutoFillMeta):
    """Base for explicit factories: declare only what differs, the rest is generated.

    ::

        # events/factories.py — picked up automatically
        class EventFactory(ModelFactory):
            class Meta:
                model = Event

            status = "published"
            title = factory.Faker("catch_phrase")

    Override / escape hatch: set ``_builder = MyBuilder()`` on the class to
    generate the undeclared fields with another :class:`FactoryBuilder`.
    """

    class Meta:
        abstract = True
        skip_postgeneration_save = True


# resolution

_EXPLICIT: dict[type[models.Model], type[DjangoModelFactory]] | None = None
_GENERATED: dict[type[models.Model], type[DjangoModelFactory]] = {}


def _factory_model(candidate: type[DjangoModelFactory]) -> type[models.Model] | None:
    if candidate._meta.abstract:
        return None
    model = candidate._meta.get_model_class()
    return model if isinstance(model, type) and issubclass(model, models.Model) else None


def explicit_factories() -> dict[type[models.Model], type[DjangoModelFactory]]:
    """Every explicit factory, discovered once from installed apps' ``factories`` modules."""
    global _EXPLICIT
    if _EXPLICIT is None:
        found: dict[type[models.Model], type[DjangoModelFactory]] = {}
        for config in apps.get_app_configs():
            if config.module is None or not module_has_submodule(config.module, "factories"):
                continue
            module = import_module(f"{config.name}.factories")
            by_model: dict[type[models.Model], list[type[DjangoModelFactory]]] = {}
            for obj in vars(module).values():
                if (
                    isinstance(obj, type)
                    and issubclass(obj, DjangoModelFactory)
                    and obj.__module__ == module.__name__
                    and (model := _factory_model(obj)) is not None
                ):
                    by_model.setdefault(model, []).append(obj)
            for model, candidates in by_model.items():
                named = [c for c in candidates if c.__name__ == f"{model.__name__}Factory"]
                found.setdefault(model, (named or candidates)[0])
        _EXPLICIT = found
    return _EXPLICIT


def auto_factory(
    model: ModelRef, builder: FactoryBuilder | None = None
) -> type[DjangoModelFactory]:
    """A generated factory for ``model`` (ignores explicit ones; cached for the default builder)."""
    resolved = _model(model)
    if builder is not None:
        return builder.build(resolved)
    generated = _GENERATED.get(resolved)
    if generated is None:
        generated = _GENERATED[resolved] = FactoryBuilder().build(resolved)
    return generated


def factory_for(model: ModelRef) -> type[DjangoModelFactory]:
    """The factory for ``model``: explicit from ``<app>/factories.py``, else generated."""
    resolved = _model(model)
    return explicit_factories().get(resolved) or auto_factory(resolved)


def create(model: ModelRef, **overrides: Any) -> Any:
    """Create and save one ``model`` row (``overrides`` win over generated values)."""
    return factory_for(model).create(**overrides)


def create_batch(model: ModelRef, size: int, **overrides: Any) -> list[Any]:
    """Create and save ``size`` rows."""
    return list(factory_for(model).create_batch(size, **overrides))


def build(model: ModelRef, **overrides: Any) -> Any:
    """An unsaved ``model`` instance."""
    return factory_for(model).build(**overrides)


def clear_cache() -> None:
    """Forget discovered and generated factories (after adding a ``factories`` module)."""
    global _EXPLICIT
    _EXPLICIT = None
    _GENERATED.clear()
