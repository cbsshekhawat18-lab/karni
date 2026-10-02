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
  factories inside generated ones, and by the N+1 scaling check of
  :mod:`karni.testing.performance`.
* generated — :class:`FactoryBuilder` declares a value for every field
  that needs one.

**Generated values** (:class:`FactoryBuilder`; every rule is an overridable
method):

======================================  ===============================================
Field                                   Value
======================================  ===============================================
auto / defaulted / non-editable         left to the model (``id``, ``created_at``,
                                        ``created_by``, ``deleted_at`` …)
``choices``                             cycles through the choice values
Char / Slug / Text                      ``"<field>-<n>"`` (unique, within ``max_length``)
Email / URL / IP                        ``user<n>@example.com`` / ``https://example.com/<n>``
                                        / ``10.x.y.z``
integers / float / decimal              a sequence inside the type's range, the field's
                                        Min/MaxValueValidators and ``max_digits``
date / datetime / time / duration       today / now / now / a sequence of minutes
UUID / JSON / binary / file / image     ``uuid4()`` / ``{"n": <n>}`` / ``b""`` / a small file
nullable + blank non-relation field     ``None`` (nullable but not blank: a value)
ForeignKey / OneToOneField              the target's factory (``factory_for(target)``);
                                        a nullable FK stays ``None`` on a cycle or below
                                        :attr:`FactoryBuilder.max_depth`
ManyToManyField                         empty, or ``create(M, tags=[t1, t2])`` /
                                        ``create(M, tags=3)`` (creates three)
user model ``password``                 :data:`DEFAULT_PASSWORD`, hashed
anything else that is required          an error *when used* naming the fix — pass the
                                        field, or write an explicit factory
======================================  ===============================================

Unique fields get sequence-based values; unique constraints over FKs hold
because every related row is new. Constraints over choices/booleans alone
need an explicit factory.

Override / escape hatches: keyword overrides on every call (including
factory-boy's ``venue__city="Pune"`` and ``tags__through_defaults={...}``);
an explicit factory in ``<app>/factories.py``; or subclass
:class:`FactoryBuilder` and call :func:`auto_factory` with it. Phase 13 seeds
build on this module.
"""

from __future__ import annotations

import datetime
import decimal
import ipaddress
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from importlib import import_module
from typing import Any, Final

import factory
from django.apps import apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone
from django.utils.module_loading import module_has_submodule
from factory.django import DjangoModelFactory

__all__ = [
    "DEFAULT_PASSWORD",
    "AutoFactory",
    "AutoSubFactory",
    "FactoryBuilder",
    "auto_factory",
    "build",
    "clear_cache",
    "create",
    "create_batch",
    "explicit_factories",
    "factory_for",
]

DEFAULT_PASSWORD: Final = "karni-password"
"""Password of every user created by a generated factory (tests can log in with it)."""

SKIP: Final = object()
"""Returned by :meth:`FactoryBuilder.declaration` for fields left to the model."""

#: Models being created, outermost first — cycle and depth guard for FKs.
_CHAIN: ContextVar[tuple[type[models.Model], ...]] = ContextVar("karni_factory_chain", default=())

ModelRef = type[models.Model] | str


def _model(model: ModelRef) -> type[models.Model]:
    if isinstance(model, str):
        return apps.get_model(model)
    if not (isinstance(model, type) and issubclass(model, models.Model)):
        raise TypeError(f"expected a model class or 'app_label.Model', got {model!r}")
    if model._meta.abstract:
        raise ImproperlyConfigured(
            f"{model.__name__} is abstract; factories need a concrete model."
        )
    return model


class AutoFactory(DjangoModelFactory):
    """Base of every generated factory: tracks the creation chain for FK cycles."""

    class Meta:
        abstract = True
        skip_postgeneration_save = True

    @classmethod
    def _generate(cls, strategy: Any, params: dict[str, Any]) -> Any:
        model = cls._meta.get_model_class()
        token = _CHAIN.set((*_CHAIN.get(), model))
        try:
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
                raise ImproperlyConfigured(
                    f"Cannot generate {path}: a required relation loops back. Pass an existing "
                    "row for that field, or define an explicit factory in <app>/factories.py."
                )
        token = _CHAIN.set((*chain, self.model))
        try:
            return super().evaluate(instance, step, extra)
        finally:
            _CHAIN.reset(token)


def _m2m_hook(name: str, target: type[models.Model]) -> Callable[..., None]:
    def hook(obj: models.Model, create: bool, extracted: Any, **kwargs: Any) -> None:
        if not create or extracted is None:
            return
        if isinstance(extracted, int) and not isinstance(extracted, bool):
            extracted = factory_for(target).create_batch(extracted)
        getattr(obj, name).set(list(extracted), through_defaults=kwargs.get("through_defaults"))

    hook.__name__ = f"set_{name}"
    return hook


def _missing_value(model: type[models.Model], field: models.Field[Any, Any]) -> Any:
    def fail() -> Any:
        raise ImproperlyConfigured(
            f"karni.testing.factories cannot generate {model.__name__}.{field.name} "
            f"({type(field).__name__}); pass it (create({model.__name__}, {field.name}=...)) or "
            "define an explicit factory in <app>/factories.py."
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


_INT_RANGES: Final[tuple[tuple[type[models.Field[Any, Any]], int, int], ...]] = (
    (models.PositiveSmallIntegerField, 0, 32767),
    (models.PositiveBigIntegerField, 0, 9223372036854775807),
    (models.PositiveIntegerField, 0, 2147483647),
    (models.SmallIntegerField, 0, 32767),
    (models.BigIntegerField, 0, 9223372036854775807),
    (models.IntegerField, 0, 2147483647),
)


class FactoryBuilder:
    """Turns a model into a factory-boy factory. Subclass to change any rule.

    :attr:`max_depth` bounds how deep nullable FKs are filled (required FKs
    are always created). :meth:`declaration` decides per field; the
    ``*_value`` methods produce the declarations.
    """

    max_depth: int = 3

    def build(self, model: type[models.Model]) -> type[DjangoModelFactory]:
        """A new ``AutoFactory`` subclass for ``model``."""
        attrs: dict[str, Any] = {
            "Meta": type("Meta", (), {"model": model, "skip_postgeneration_save": True}),
            "__module__": __name__,
            "__doc__": f"Generated factory for {model._meta.label} (karni.testing.factories).",
        }
        for field in model._meta.concrete_fields:
            value = self.declaration(model, field)
            if value is not SKIP:
                attrs[field.name] = value
        for m2m in model._meta.many_to_many:
            attrs[m2m.name] = factory.PostGeneration(_m2m_hook(m2m.name, m2m.related_model))
        return type(f"{model.__name__}AutoFactory", (AutoFactory,), attrs)

    def declaration(self, model: type[models.Model], field: models.Field[Any, Any]) -> Any:
        """The declaration for ``field``, or :data:`SKIP` to leave it to the model."""
        if field.auto_created or not field.editable:
            return SKIP
        if field.primary_key and (field.has_default() or isinstance(field, models.AutoField)):
            return SKIP
        if issubclass(model, AbstractBaseUser) and field.name == "password":
            return factory.django.Password(DEFAULT_PASSWORD)
        if field.is_relation:
            return self.relation_value(model, field)
        if field.has_default():
            return SKIP
        if field.null and field.blank:
            return None
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

    def text_value(self, field: Any, stem: str) -> Any:
        """``"<stem>-<n>"`` within ``max_length`` (the counter is kept, the stem cut)."""
        max_length = field.max_length or 255

        def make(n: int) -> str:
            suffix = f"-{n}"
            return stem[: max(max_length - len(suffix), 0)] + suffix

        return factory.Sequence(make)

    def number_value(self, field: models.Field[Any, Any], low: float, high: float) -> Any:
        """A sequence inside ``[low, high]`` and the field's Min/MaxValueValidators."""
        low, high = _bounds(field, low, high)
        if isinstance(field, models.FloatField):
            return factory.Sequence(lambda n: float(low + n % max(int(high - low), 1)))
        start, span = int(low), max(int(high) - int(low) + 1, 1)
        return factory.Sequence(lambda n: start + n % span)

    def decimal_value(self, field: models.DecimalField[Any]) -> Any:
        places = field.decimal_places or 0
        whole = max((field.max_digits or 10) - places, 0)
        low, high = _bounds(field, 0, 10**whole - 1 if whole else 0)
        quantum = decimal.Decimal(1).scaleb(-places)
        span = max(int(high) - int(low) + 1, 1)
        return factory.Sequence(lambda n: (decimal.Decimal(int(low) + n % span)).quantize(quantum))

    def value(self, model: type[models.Model], field: Any) -> Any:
        """The declaration for a required, non-relation field without a default."""
        name = field.name
        if isinstance(field, models.EmailField):
            return factory.Sequence(lambda n: f"user{n}@example.com")
        if isinstance(field, models.URLField):
            return factory.Sequence(lambda n: f"https://example.com/{n}")
        if isinstance(field, models.GenericIPAddressField):
            if field.protocol.lower() == "ipv6":
                return factory.Sequence(lambda n: str(ipaddress.IPv6Address(0x20010DB8 << 96 | n)))
            return factory.Sequence(lambda n: str(ipaddress.IPv4Address(0x0A000000 + n % 2**24)))
        if isinstance(field, models.SlugField):
            return self.text_value(field, name.replace("_", "-"))
        if isinstance(field, models.CharField | models.TextField):
            return self.text_value(field, name)
        if isinstance(field, models.BooleanField):
            return False
        if isinstance(field, models.DecimalField):
            return self.decimal_value(field)
        if isinstance(field, models.FloatField):
            return self.number_value(field, 0, 1_000_000)
        for kind, low, high in _INT_RANGES:
            if isinstance(field, kind):
                return self.number_value(field, low, high)
        if isinstance(field, models.DateTimeField):
            return factory.LazyFunction(timezone.now)
        if isinstance(field, models.DateField):
            return factory.LazyFunction(datetime.date.today)
        if isinstance(field, models.TimeField):
            return factory.LazyFunction(
                lambda: datetime.datetime.now().time().replace(microsecond=0)
            )
        if isinstance(field, models.DurationField):
            return factory.Sequence(lambda n: datetime.timedelta(minutes=n))
        if isinstance(field, models.UUIDField):
            return factory.LazyFunction(uuid.uuid4)
        if isinstance(field, models.JSONField):
            return factory.Sequence(lambda n: {"n": n})
        if isinstance(field, models.BinaryField):
            return b""
        if isinstance(field, models.ImageField):
            return self.image_value(field)
        if isinstance(field, models.FileField):
            if field.blank:
                return SKIP
            return factory.django.FileField(filename=f"{name}.txt", data=b"karni")
        return _missing_value(model, field)

    def image_value(self, field: Any) -> Any:
        if field.blank:
            return SKIP
        try:
            import PIL  # noqa: F401
        except ImportError:
            return factory.django.FileField(filename=f"{field.name}.png", data=b"karni")
        return factory.django.ImageField(filename=f"{field.name}.png")


# --- resolution -------------------------------------------------------------------------------

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
