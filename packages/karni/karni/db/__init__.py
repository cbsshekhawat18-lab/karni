"""External tables, SQL views and a second database, as models Karni accepts (experimental).

Three keys of a model's ``class Karni`` (:mod:`karni.meta`)::

    from django.db import models


    class Sale(models.Model):
        id = models.IntegerField(primary_key=True)
        region = models.CharField(max_length=40)
        amount = models.DecimalField(max_digits=12, decimal_places=2)

        class Meta:
            managed = False
            db_table = 'reporting"."sales'   # schema "reporting", table "sales" (PostgreSQL)

        class Karni:
            external = True                  # another system owns the table or view
            database = "warehouse"           # reads, writes and migrations go to this alias
            writable = False                 # the default: the API and the admin only read

* ``external = True`` together with ``Meta.managed = False``: the table or
  view belongs to another system. The model may inherit plain
  ``django.db.models.Model`` (the ``model-base`` rule accepts it), needs no
  UUID, soft delete or audit fields, and Karni never runs DDL for it. The
  API answers its writes with 405 and the admin shows it read-only, unless
  ``writable = True``.
* ``database = "<alias>"``: :class:`DatabaseRouter` sends the model's reads,
  writes and migrations to that ``DATABASES`` alias. It applies to external
  models and to models Karni manages there.

The checks (:mod:`karni.db.checks`): ``E270`` external without
``managed = False``, ``E271`` an unknown alias, ``E275`` a value of the
wrong type, ``E276`` a relation across databases, ``W541`` ``writable``
without ``external``, ``W542`` the router missing from ``DATABASE_ROUTERS``.
``karni check`` also compares every external model with its table or view
when the database answers (``E272`` to ``E274``, ``W540`` when it does not).

Override / escape hatch: routers listed before :class:`DatabaseRouter` in
``DATABASE_ROUTERS`` win (Django asks each router in turn and takes the first
answer). Subclass the router to change one decision. ``BaseViewSet.is_read_only``
and ``KarniModelAdmin.is_read_only`` decide read-only per viewset or admin.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.db import DEFAULT_DB_ALIAS, models
from django.db.backends.utils import split_identifier

from karni.meta import karni_option

__all__ = [
    "DatabaseRouter",
    "database_for",
    "external_models",
    "is_external",
    "is_read_only",
    "routed_aliases",
    "split_table",
]


def _declaring(model: type[models.Model] | Any) -> Any:
    """The model whose ``class Karni`` speaks for ``model``.

    An auto-created many-to-many table follows the model that declares the
    field, and a historical model (a migration's ``apps``) the registered model
    of the same label, since migration state keeps no ``class Karni``.
    """
    meta = getattr(model, "_meta", None)
    if meta is None:
        return model
    owner = getattr(meta, "auto_created", False)
    if isinstance(owner, type):
        return _declaring(owner)
    if getattr(model, "__module__", "") == "__fake__":
        try:
            return apps.get_model(meta.app_label, meta.model_name)
        except LookupError:
            return model
    return model


def is_external(model: type[models.Model] | Any) -> bool:
    """Experimental. Whether ``class Karni: external = True``: another system owns the table."""
    return bool(karni_option(_declaring(model), "external", False))


def is_read_only(model: type[models.Model] | Any) -> bool:
    """Experimental. Whether Karni only reads ``model``: external and not ``Karni.writable``."""
    declaring = _declaring(model)
    return is_external(declaring) and not bool(karni_option(declaring, "writable", False))


def database_for(model: type[models.Model] | Any) -> str | None:
    """Experimental. The ``DATABASES`` alias ``class Karni: database`` names, else ``None``."""
    alias = karni_option(_declaring(model), "database", None)
    return alias if isinstance(alias, str) and alias else None


def external_models() -> list[type[models.Model]]:
    """Experimental. Every installed external model (proxies and abstract models aside)."""
    return [
        model
        for model in apps.get_models()
        if is_external(model) and not model._meta.proxy and not model._meta.auto_created
    ]


def routed_aliases() -> frozenset[str]:
    """Experimental. The aliases other than ``default`` that some model's ``Karni.database`` names.

    Only the models routed there migrate on such an alias.
    """
    return frozenset(
        alias
        for model in apps.get_models()
        if (alias := database_for(model)) is not None and alias != DEFAULT_DB_ALIAS
    )


def split_table(db_table: str) -> tuple[str | None, str]:
    """Experimental. ``(schema, table)`` from a ``Meta.db_table``: ``'reporting"."sales'``.

    The schema is ``None`` for a plain name. Django quotes ``db_table`` as one
    identifier, so ``'reporting"."sales'`` becomes ``"reporting"."sales"`` in
    SQL: the table ``sales`` in the PostgreSQL schema ``reporting``.
    """
    schema, table = split_identifier(db_table)
    return (schema or None), table


def _registered(app_label: str, model_name: str | None) -> type[models.Model] | None:
    if not model_name:
        return None
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None


class DatabaseRouter:
    """Experimental. Routes each model to the alias its ``class Karni: database`` names.

    ``karni_settings()`` lists it in ``DATABASE_ROUTERS``, after any router the
    project listed first. A project with one database is unaffected: every
    answer is ``None`` (no opinion) for a model that declares nothing.

    * reads and writes: the declared alias;
    * relations: refused between models on different aliases (``E276`` reports
      such a field at startup);
    * migrations: a model Karni manages migrates only on its own alias, an
      external model never. On an alias some model names, nothing else
      migrates: a ``RunPython`` or ``RunSQL`` meant for it passes
      ``hints={"model_name": "<model>"}``.

    Override / escape hatch: list your own router before this one, or
    subclass it and override one method.
    """

    def db_for_read(self, model: type[models.Model], **hints: Any) -> str | None:
        return database_for(model)

    def db_for_write(self, model: type[models.Model], **hints: Any) -> str | None:
        return database_for(model)

    def allow_relation(self, obj1: models.Model, obj2: models.Model, **hints: Any) -> bool | None:
        first, second = database_for(type(obj1)), database_for(type(obj2))
        if first is None and second is None:
            return None
        return _alias(obj1, first) == _alias(obj2, second)

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        model = _registered(app_label, model_name)
        if model is None:
            return False if db in routed_aliases() else None
        if is_external(model):
            return False
        declared = database_for(model)
        if declared is not None:
            return db == declared
        return False if db in routed_aliases() else None


def _alias(obj: models.Model, declared: str | None) -> str:
    return declared or getattr(obj._state, "db", None) or DEFAULT_DB_ALIAS
