"""System checks for the typed field layer (``karni.E960``-``E970``, ``W964``-``W967``).

Registered through :mod:`karni.checks`, so they run on ``runserver``,
``migrate`` and ``check``:

* ``E960`` a ``FloatField`` holds money (a field named price, amount, total,
  cost, fee, subtotal, tax, balance, ...): binary floats cannot store cents;
* ``E961`` a ``MoneyField``'s ``currency_field`` is not a currency field of
  the model;
* ``E963`` a field declaration that cannot work (``populate_from``, a
  ``SearchField`` source, ...);
* ``E964`` / ``W964`` a database in ``DATABASES`` cannot run a field at all
  (an ``ArrayField`` on SQLite) / runs it without a PostgreSQL guarantee;
* ``W965`` a foreign key on a financial or audited model cascades: deleting
  the referenced row would silently delete money or history;
* ``W967`` a column a viewset searches, filters or orders by has no index;
* ``E968`` a ``LiveUniqueConstraint`` on a model without soft delete;
* ``E970`` a ``class Karni`` option of the field layer is malformed.

Override / escape hatch: each warning names its declaration-level opt-out;
``SILENCED_SYSTEM_CHECKS`` silences any of them project-wide
(``karni_settings()`` starts it as an empty list, so ``+=`` works).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from django.apps import apps
from django.core import checks
from django.db import models

from karni.exceptions import check_error, check_warning
from karni.meta import karni_option

__all__ = [
    "FINANCIAL_MODEL_WORDS",
    "MONEY_WORDS",
    "check_backends",
    "check_cascades",
    "check_field_declarations",
    "check_money_floats",
    "check_usage_indexes",
    "is_financial",
    "money_name",
]

#: Name parts that mark a numeric field as money (``unit_price``, ``total_amount``).
MONEY_WORDS = frozenset(
    {
        "price",
        "prices",
        "amount",
        "amounts",
        "total",
        "totals",
        "subtotal",
        "cost",
        "costs",
        "fee",
        "fees",
        "tax",
        "taxes",
        "balance",
        "salary",
        "wage",
        "wages",
        "revenue",
        "budget",
        "charge",
        "payment",
        "refund",
        "payout",
        "fare",
        "money",
        "deposit",
        "discount",
    }
)

#: Model name parts that mark a model as financial for ``karni.W965``.
FINANCIAL_MODEL_WORDS = frozenset(
    {
        "payment",
        "invoice",
        "refund",
        "payout",
        "charge",
        "transaction",
        "ledger",
        "receipt",
        "settlement",
        "wallet",
        "transfer",
        "credit",
        "debit",
    }
)

_E970_HINT = (
    'Map each field to the reason: not_money = {"field": "<what it is>"}, '
    'cascade = {"field": "<why the cascade is deliberate>"}.'
)

_SPLIT = re.compile(r"[_\W]+|(?<=[a-z0-9])(?=[A-Z])")


def _parts(name: str) -> set[str]:
    return {part.lower() for part in _SPLIT.split(name) if part}


def money_name(name: str) -> bool:
    """True when a field name says it holds money (``price``, ``total_amount``, ``tax``)."""
    return bool(_parts(name) & MONEY_WORDS)


def _models(app_configs: Any) -> list[type[models.Model]]:
    configs = app_configs if app_configs is not None else apps.get_app_configs()
    return [
        model
        for config in configs
        for model in config.get_models()
        if not (model._meta.proxy or model._meta.swapped)
    ]


def _reasons(model: type[models.Model], option: str) -> tuple[dict[str, str], list[str]]:
    """``Karni.<option>`` as ``{field: reason}`` plus problems (E970)."""
    declared = karni_option(model, option, None)
    if declared is None:
        return {}, []
    if isinstance(declared, Mapping):
        found = {str(name): str(reason) for name, reason in declared.items()}
        blank = sorted(name for name, reason in found.items() if not reason.strip())
        problems = (
            [
                f"{model.__name__}.Karni.{option} gives no reason for {', '.join(blank)}: "
                f'write {{"{blank[0]}": "<why this is deliberate>"}}.'
            ]
            if blank
            else []
        )
        return found, problems
    if isinstance(declared, str) or not isinstance(declared, Iterable):
        return {}, [
            f"{model.__name__}.Karni.{option} must map field names to reasons, e.g. "
            f'{{"field": "why"}}, got {declared!r}.'
        ]
    names = [str(name) for name in declared]
    return {name: "" for name in names}, [
        f"{model.__name__}.Karni.{option} lists {', '.join(names)} without reasons: write "
        f'{{"{names[0] if names else "field"}": "<why this is deliberate>"}}.'
    ]


@checks.register(checks.Tags.models)
def check_money_floats(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E960: a ``FloatField`` named like money."""
    messages: list[checks.CheckMessage] = []
    for model in _models(app_configs):
        allowed, problems = _reasons(model, "not_money")
        messages.extend(check_error("E970", text, hint=_E970_HINT, obj=model) for text in problems)
        for field in model._meta.local_fields:
            if not isinstance(field, models.FloatField) or field.name in allowed:
                continue
            if not money_name(field.name):
                continue
            messages.append(
                check_error(
                    "E960",
                    f"{model.__name__}.{field.name} is a FloatField, but its name says it "
                    "holds money. A binary float cannot store most cent values exactly "
                    "(0.1 + 0.2 != 0.3), so totals drift and reconciliations fail.",
                    hint=(
                        f'Replace it with `{field.name} = MoneyField(currency="EUR")`, or '
                        'currency_field="currency" for a currency per row (from karni.fields '
                        "import MoneyField), then run karni make migration. A rate is "
                        "PercentField. If it really is not money, declare "
                        f'`class Karni: not_money = {{"{field.name}": "<what it is>"}}`.'
                    ),
                    obj=model,
                )
            )
    return messages


@checks.register(checks.Tags.models)
def check_field_declarations(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E961 / E963 / E968 / E970: declarations the database cannot honour."""
    from karni.fields.base import is_soft_deletable
    from karni.fields.constraints import LiveUniqueConstraint
    from karni.fields.indexes import append_only_columns
    from karni.fields.iso import CurrencyField
    from karni.fields.money import MoneyField
    from karni.fields.search import SearchField
    from karni.fields.text import SlugField

    messages: list[checks.CheckMessage] = []
    for model in _models(app_configs):
        names = {field.name: field for field in model._meta.get_fields()}
        for field in model._meta.local_fields:
            if isinstance(field, MoneyField) and field.currency_field:
                head = field.currency_field.split("__", 1)[0]
                target = names.get(head)
                plain = "__" not in field.currency_field
                if target is None or (plain and not isinstance(target, CurrencyField)):
                    messages.append(
                        check_error(
                            "E961",
                            f"{model.__name__}.{field.name} = MoneyField(currency_field="
                            f'"{field.currency_field}"), but {model.__name__} has no '
                            f"CurrencyField {field.currency_field!r}: the amount's currency "
                            "would be unknown.",
                            hint=(
                                f"Add `{field.currency_field} = CurrencyField()` to "
                                f'{model.__name__}, or use MoneyField(currency="EUR") for one '
                                "fixed currency."
                            ),
                            obj=model,
                        )
                    )
            if isinstance(field, SlugField) and field.populate_from:
                head = field.populate_from.split("__", 1)[0]
                if head not in names:
                    messages.append(
                        check_error(
                            "E963",
                            f"{model.__name__}.{field.name} = SlugField(populate_from="
                            f'"{field.populate_from}"), but {model.__name__} has no field '
                            f"{head!r} to build the slug from.",
                            hint='Name an existing field, e.g. populate_from="title".',
                            obj=model,
                        )
                    )
            if isinstance(field, SearchField):
                missing = [name for name in field.sources if name not in names]
                if missing:
                    messages.append(
                        check_error(
                            "E963",
                            f"{model.__name__}.{field.name} = SearchField(sources=...) names "
                            f"{', '.join(missing)}, which {model.__name__} does not have.",
                            hint="List fields of the same model (no relations): the column "
                            "is generated from them.",
                            obj=model,
                        )
                    )
        for constraint in model._meta.constraints:
            if isinstance(constraint, LiveUniqueConstraint) and not is_soft_deletable(model):
                messages.append(
                    check_error(
                        "E968",
                        f"{model.__name__}.Meta.constraints has LiveUniqueConstraint "
                        f"{constraint.name!r}, but {model.__name__} is not soft-deletable "
                        "(no deleted_at): there are no deleted rows to exempt.",
                        hint="Use models.UniqueConstraint, or inherit karni.models.BaseModel "
                        "(or SoftDeleteModel).",
                        obj=model,
                    )
                )
        columns = append_only_columns(model)
        local = {field.name: field for field in model._meta.local_concrete_fields}
        bad = [
            name
            for name in columns
            if not isinstance(local.get(name), models.DateField | models.IntegerField)
        ]
        if bad:
            messages.append(
                check_error(
                    "E970",
                    f"{model.__name__}.Karni.append_only names {', '.join(bad)}, which "
                    f"{model.__name__} does not have as a date, time or integer column.",
                    hint="Write `append_only = True` (every auto_now_add timestamp) or list "
                    'the columns that only grow, e.g. append_only = ["created_at"].',
                    obj=model,
                )
            )
    return messages


def is_financial(model: type[models.Model]) -> bool:
    """A model holding money: a MoneyField, a money-named decimal, a payments-like name."""
    from karni.fields.money import MoneyField

    declared = karni_option(model, "financial", None)
    if declared is not None:
        return bool(declared)
    for field in model._meta.local_fields:
        if isinstance(field, MoneyField):
            return True
        if isinstance(field, models.DecimalField) and money_name(field.name):
            return True
    return bool(_parts(model.__name__) & FINANCIAL_MODEL_WORDS)


@checks.register(checks.Tags.models)
def check_cascades(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W965: CASCADE on a foreign key of a financial or audited model."""
    messages: list[checks.CheckMessage] = []
    for model in _models(app_configs):
        audited = bool(karni_option(model, "audit", False))
        financial = is_financial(model)
        if not (audited or financial):
            continue
        deliberate, problems = _reasons(model, "cascade")
        messages.extend(check_error("E970", text, hint=_E970_HINT, obj=model) for text in problems)
        what = " and ".join(
            word for word, flag in (("financial", financial), ("audited", audited)) if flag
        )
        for field in model._meta.local_fields:
            remote = getattr(field, "remote_field", None)
            if remote is None or getattr(remote, "on_delete", None) is not models.CASCADE:
                continue
            if field.name in deliberate:
                continue
            target = remote.model
            target_name = target if isinstance(target, str) else target.__name__
            messages.append(
                check_warning(
                    "W965",
                    f"{model.__name__}.{field.name} is on_delete=CASCADE, and {model.__name__} "
                    f"is {what}: hard-deleting a {target_name} silently deletes its "
                    f"{model.__name__} rows{' and their history' if audited else ''}.",
                    hint=(
                        f"Use on_delete=models.PROTECT (refuse the delete while rows exist) "
                        "or SET_NULL with null=True, then karni make migration. If the cascade "
                        f'is deliberate, say why: `class Karni: cascade = {{"{field.name}": '
                        '"<why>"}`.'
                    ),
                    obj=model,
                )
            )
    return messages


def _model_databases(model: type[models.Model]) -> list[Any]:
    from django.db import connections, router

    return [connections[alias] for alias in connections if router.allow_migrate_model(alias, model)]


@checks.register(checks.Tags.models)
def check_backends(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E964 / W964: a field (or guarantee) the configured database cannot honour."""
    from karni.fields.base import KarniField
    from karni.fields.constraints import LiveUniqueConstraint

    messages: list[checks.CheckMessage] = []
    for model in _models(app_configs):
        karni_fields: list[Any] = [f for f in model._meta.local_fields if isinstance(f, KarniField)]
        live_unique = [c for c in model._meta.constraints if isinstance(c, LiveUniqueConstraint)]
        if not (karni_fields or live_unique):
            continue
        for connection in _model_databases(model):
            where = f"DATABASES[{connection.alias!r}] ({connection.vendor})"
            for field in karni_fields:
                problem = field.backend_problem(connection)
                if problem is None:
                    continue
                level, text = problem
                label = f"{model.__name__}.{field.name} ({type(field).__name__})"
                if level == "error":
                    messages.append(
                        check_error(
                            "E964",
                            f"{label} cannot work on {where}: {text}.",
                            hint="Point this database at PostgreSQL, or replace the field "
                            f"with {field.plain_django or 'a portable field'}.",
                            obj=model,
                        )
                    )
                else:
                    messages.append(
                        check_warning(
                            "W964",
                            f"{label} on {where} runs without {text}.",
                            hint="Fine for tests and local development. Use PostgreSQL in "
                            "production (silence karni.W964 where that is deliberate).",
                            obj=model,
                        )
                    )
            if live_unique and not connection.features.supports_partial_indexes:
                names = ", ".join(c.name for c in live_unique)
                messages.append(
                    check_warning(
                        "W964",
                        f"{model.__name__}: {where} has no partial indexes, so "
                        f"LiveUniqueConstraint {names} is not created and uniqueness is not "
                        "enforced by the database.",
                        hint="Use PostgreSQL or SQLite, or enforce it in Model.clean().",
                        obj=model,
                    )
                )
    return messages


@checks.register(checks.Tags.urls)
def check_usage_indexes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W967: a column a routed viewset searches, filters or orders by has no index."""
    from karni.fields.usage import covering_index, suggestion, usage_requirements

    try:
        from karni.api.routers import resolve_router

        registry = getattr(resolve_router(), "registry", ())
    except Exception:  # noqa: BLE001 - router problems are karni.E128's to report
        return []
    configs = {config.label for config in app_configs} if app_configs is not None else None
    viewsets = []
    for _prefix, viewset, _basename in registry:
        model = getattr(viewset, "model", None)
        if model is None or (configs is not None and model._meta.app_label not in configs):
            continue
        viewsets.append(viewset)
    uncovered = [
        requirement
        for requirement in usage_requirements(viewsets)
        if covering_index(requirement.model, requirement.field, requirement.kind) is None
    ]
    searched: dict[tuple[Any, str], list[str]] = {}
    for requirement in uncovered:
        if requirement.kind == "search":
            key = (requirement.model, requirement.declared_by)
            searched.setdefault(key, []).append(requirement.field)
    messages: list[checks.CheckMessage] = []
    for requirement in uncovered:
        model = requirement.model
        if requirement.kind == "search":
            names = searched.pop((model, requirement.declared_by), None)
            if names is None:
                continue  # reported with the first searched column of this declaration
            columns = ", ".join(f"{model.__name__}.{name}" for name in names)
            text = (
                f"{requirement.declared_by} searches {columns}, which no index covers: every "
                f"?search= reads all of {model._meta.db_table}."
            )
            fix = suggestion(requirement, names)
        else:
            verb = "filters by" if requirement.kind == "filter" else "orders by"
            text = (
                f"{requirement.declared_by} {verb} {model.__name__}.{requirement.field}, which "
                f"no index covers: every such list request reads all of "
                f"{model._meta.db_table}."
            )
            fix = suggestion(requirement)
        messages.append(
            check_warning(
                "W967",
                text,
                hint=f"{_sentence(fix)}, then karni make migration. For a table small enough "
                'to scan, silence it instead: SILENCED_SYSTEM_CHECKS = ["karni.W967"].',
                obj=model,
            )
        )
    return messages


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]
