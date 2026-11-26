"""What parts contribute to the people contract: facts, merge, erase, duplicates.

A part declares its contributions in ``<app>/people.py``, which
:class:`karni.people.apps.PeopleConfig` imports at startup for every
installed app::

    # helpdesk/people.py
    from karni import people

    from helpdesk.models import SupportProfile, Ticket

    people.register_fact(
        "open_tickets", people.count_of(Ticket, filter=Q(status="open")), label="Open tickets"
    )


    @people.merge_hook(SupportProfile)
    def merge_support(keep, drop):
        ...  # both people had a profile: fold drop's into keep's, then delete drop's


    people.erasable(Ticket, fields={"contact_name": "", "contact_email": ""})

**Facts** (:func:`register_fact`) are SQL expressions over a person: a
count, a sum, a latest date. ``Person.objects.with_facts(...)`` annotates
them, so the CRM's segments, the person page and a customers list filter and
order on them without knowing which part contributed them. :func:`count_of`,
:func:`sum_of`, :func:`latest_of` and :func:`exists_of` build the usual
ones as correlated subqueries (one row per person, whatever the joins).

**Merge hooks** (:func:`merge_hook`) decide what happens to a model's rows
when two people (or two organisations) become one. Without a hook, rows
that point at the dropped record are moved to the kept one. A one-to-one
profile that both records have needs a hook, or the merge is refused
naming the model (``E251``).

**Erase hooks** (:func:`erase_hook`, :func:`erasable`) anonymise a part's
rows for a person who asked for their data to be deleted: an order keeps its
amounts and loses the name.

**Duplicate rules** (:func:`register_duplicate_rule`) find people that look
like the same human. Core ships two; a CRM adds phone, name with
organisation and domain.

Override / escape hatch: every registration takes ``replace=True`` to swap
a contribution; :func:`unregister_fact` removes one;
``KARNI_PEOPLE_AUTODISCOVER = False`` stops the ``people.py`` import, and a
part then calls these functions from its own ``AppConfig.ready()``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

from django.apps import apps
from django.db import models
from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils.module_loading import module_has_submodule

from karni.exceptions import KarniImproperlyConfigured, KarniValueError

if TYPE_CHECKING:
    from django.db.models import QuerySet

__all__ = [
    "FACT_KINDS",
    "DuplicateRule",
    "Fact",
    "annotate_facts",
    "autodiscover",
    "count_of",
    "duplicate_rules",
    "erasable",
    "erase_hook",
    "erase_hooks",
    "exists_of",
    "fact",
    "facts",
    "latest_of",
    "merge_hook",
    "merge_hooks",
    "register_duplicate_rule",
    "register_fact",
    "sum_of",
    "unregister_fact",
]

#: What a fact's value is, for screens that format it.
FACT_KINDS: Final = ("count", "number", "money", "date", "datetime", "boolean", "text")

#: The person facts, by name, in registration order.
_FACTS: dict[str, Fact] = {}
#: Merge hooks by model.
_MERGE_HOOKS: dict[type[models.Model], Callable[[Any, Any], None]] = {}
#: Erase hooks, in registration order: ``(name, hook)``.
_ERASE_HOOKS: dict[str, Callable[[Any], None]] = {}
#: Duplicate rules by name.
_DUPLICATE_RULES: dict[str, DuplicateRule] = {}

ModelRef = type[models.Model] | str


def _model(model: ModelRef) -> type[models.Model]:
    if isinstance(model, str):
        return apps.get_model(model)
    return model


def _caller_app(depth: int = 2) -> str:
    """The app label of the module that called a registration (for the record only)."""
    import sys

    try:
        frame = sys._getframe(depth)
    except ValueError:
        return ""
    module = str(frame.f_globals.get("__name__", ""))
    config = apps.get_containing_app_config(module) if module else None
    return config.label if config is not None else ""


# facts --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    """One person fact: a name, how to compute it, and what it means.

    ``expression`` is a callable returning a Django expression evaluated
    against ``Person`` (``OuterRef("pk")`` is the person). It is called when a
    queryset is annotated, never at registration, so it may reference any
    model. ``kind`` says how screens format it, ``source`` the app that
    contributed it.
    """

    name: str
    expression: Callable[[], Any]
    label: str
    kind: str = "number"
    source: str = ""
    description: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "source": self.source,
            "description": self.description,
        }


def register_fact(
    name: str,
    expression: Callable[[], Any] | Any,
    *,
    label: str = "",
    kind: str = "number",
    description: str = "",
    source: str = "",
    replace: bool = False,
) -> Fact:
    """Register the person fact ``name`` (``E257`` for a bad or taken name).

    ``expression`` is a Django expression over ``Person``, or a callable that
    returns one (the builders below return callables). ``name`` must be a
    Python identifier that is not a field of Person, so it can be an
    annotation, a filter (``orders__gte=3``) and an ordering.
    """
    from karni.people.models import Person

    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
        raise KarniValueError(
            f"A person fact needs a name that is a Python identifier, such as total_spent; "
            f"got {name!r}.",
            code="E257",
        )
    taken = {f.name for f in Person._meta.get_fields()} | {
        f.attname for f in Person._meta.concrete_fields
    }
    if name in taken or "__" in name:
        raise KarniValueError(
            f"The person fact {name!r} has the name of a Person field or a lookup. Name it "
            "after what it counts, e.g. orders or total_spent.",
            code="E257",
        )
    if name in _FACTS and not replace:
        raise KarniValueError(
            f"The person fact {name!r} is registered twice (by {_FACTS[name].source or 'an app'} "
            "first). Give the second one another name, or pass replace=True to swap it.",
            code="E257",
        )
    if kind not in FACT_KINDS:
        raise KarniValueError(
            f"The person fact {name!r} has kind {kind!r}. Kinds: {', '.join(FACT_KINDS)}.",
            code="E257",
        )
    built = expression if callable(expression) else (lambda: expression)
    found = Fact(
        name=name,
        expression=built,
        label=label or name.replace("_", " ").capitalize(),
        kind=kind,
        source=source or _caller_app(),
        description=description,
    )
    _FACTS[name] = found
    return found


def fact(
    name: str, *, label: str = "", kind: str = "number", description: str = ""
) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
    """:func:`register_fact` as a decorator over a function that builds it."""

    def decorate(function: Callable[[], Any]) -> Callable[[], Any]:
        register_fact(
            name,
            function,
            label=label,
            kind=kind,
            description=description,
            source=_caller_app(),
        )
        return function

    return decorate


def unregister_fact(name: str) -> None:
    """Remove the person fact ``name`` (nothing when it is not registered)."""
    _FACTS.pop(name, None)


def facts() -> dict[str, Fact]:
    """The registered person facts, by name, in registration order."""
    return dict(_FACTS)


def annotate_facts(queryset: QuerySet[Any], names: Iterable[str] | None = None) -> QuerySet[Any]:
    """``queryset`` of Person with the facts ``names`` (``None``: all) annotated.

    An unknown name is ``E257``.
    """
    chosen = list(_FACTS) if names is None else list(dict.fromkeys(names))
    unknown = [name for name in chosen if name not in _FACTS]
    if unknown:
        raise KarniValueError(
            f"No person fact named {', '.join(unknown)}. Registered facts: "
            f"{', '.join(_FACTS) or 'none'}.",
            code="E257",
        )
    if not chosen:
        return queryset
    return queryset.annotate(**{name: _FACTS[name].expression() for name in chosen})


def _related(model: ModelRef, path: str, filter: Q | None) -> QuerySet[Any]:
    rows = _model(model)._default_manager.filter(**{path: OuterRef("pk")})
    return rows.filter(filter) if filter is not None else rows


def count_of(
    model: ModelRef, path: str = "person", *, filter: Q | None = None
) -> Callable[[], Any]:
    """How many live rows of ``model`` point at the person through ``path``."""

    def build() -> Any:
        rows = _related(model, path, filter).order_by().values(path)
        counted = rows.annotate(total=Count("pk")).values("total")
        return Coalesce(Subquery(counted, output_field=models.IntegerField()), 0)

    return build


def sum_of(
    model: ModelRef, field_name: str, path: str = "person", *, filter: Q | None = None
) -> Callable[[], Any]:
    """The sum of ``field_name`` over the person's live rows of ``model`` (or 0)."""

    def build() -> Any:
        target = _model(model)._meta.get_field(field_name)
        rows = _related(model, path, filter).order_by().values(path)
        summed = rows.annotate(total=Sum(field_name)).values("total")
        output = models.DecimalField(
            max_digits=getattr(target, "max_digits", None) or 19,
            decimal_places=getattr(target, "decimal_places", None) or 4,
        )
        if isinstance(target, models.IntegerField | models.FloatField):
            output = target.__class__()
        return Coalesce(Subquery(summed, output_field=output), 0, output_field=output)

    return build


def latest_of(
    model: ModelRef, field_name: str, path: str = "person", *, filter: Q | None = None
) -> Callable[[], Any]:
    """The latest ``field_name`` (a date) of the person's live rows, or ``None``."""

    def build() -> Any:
        target = _model(model)._meta.get_field(field_name)
        rows = _related(model, path, filter).order_by().values(path)
        latest = rows.annotate(last=Max(field_name)).values("last")
        return Subquery(latest, output_field=target.__class__())

    return build


def exists_of(
    model: ModelRef, path: str = "person", *, filter: Q | None = None
) -> Callable[[], Any]:
    """Whether the person has a live row of ``model`` (with ``filter``)."""

    def build() -> Any:
        return Exists(_related(model, path, filter))

    return build


# merge hooks -----------------------------------------------------------------------------


def merge_hook(
    model: ModelRef, *, replace: bool = False
) -> Callable[[Callable[[Any, Any], None]], Callable[[Any, Any], None]]:
    """Register what a merge does with ``model``'s rows (``E257`` when taken).

    The hook is called as ``hook(keep, drop)`` with the two people (or the
    two organisations) inside the merge's transaction, before Karni moves the
    rows that still point at ``drop``. A one-to-one profile hook folds
    ``drop``'s profile into ``keep``'s and deletes ``drop``'s: a deleted
    profile stays with the dropped record. A hook for a model with a foreign
    key resolves what would clash (a row each for the same slot) and leaves
    the rest to be moved.
    """

    def decorate(function: Callable[[Any, Any], None]) -> Callable[[Any, Any], None]:
        target = _model(model)
        if target in _MERGE_HOOKS and not replace and _MERGE_HOOKS[target] is not function:
            raise KarniImproperlyConfigured(
                f"{target._meta.label} has a merge hook already "
                f"({_MERGE_HOOKS[target].__module__}.{_MERGE_HOOKS[target].__qualname__}). Pass "
                "replace=True to swap it.",
                code="E257",
            )
        _MERGE_HOOKS[target] = function
        return function

    return decorate


def merge_hooks() -> dict[type[models.Model], Callable[[Any, Any], None]]:
    """The registered merge hooks, by model."""
    return dict(_MERGE_HOOKS)


# erase hooks -----------------------------------------------------------------------------


def erase_hook(
    name: str | None = None, *, replace: bool = False
) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
    """Register ``hook(person)``: anonymise a part's rows of a person (``E257``).

    Hooks run in registration order inside ``people.erase``'s transaction,
    before the person's own row is anonymised. ``name`` defaults to the
    function's dotted path.
    """

    def decorate(function: Callable[[Any], None]) -> Callable[[Any], None]:
        key = name or f"{function.__module__}.{function.__qualname__}"
        if key in _ERASE_HOOKS and not replace and _ERASE_HOOKS[key] is not function:
            raise KarniImproperlyConfigured(
                f"An erase hook named {key!r} is registered already. Pass replace=True to "
                "swap it, or give this one another name.",
                code="E257",
            )
        _ERASE_HOOKS[key] = function
        return function

    return decorate


def erase_hooks() -> dict[str, Callable[[Any], None]]:
    """The registered erase hooks, by name, in the order they run."""
    return dict(_ERASE_HOOKS)


def erasable(
    model: ModelRef,
    *,
    fields: Mapping[str, Any],
    path: str = "person",
    history: bool = True,
) -> Callable[[Any], None]:
    """Register an erase hook writing ``fields`` on the person's rows of ``model``.

    ``people.erasable(Order, fields={"name": "", "email": ""})`` blanks the
    name and email of every order of the person (soft-deleted rows too) and,
    with ``history``, removes those values from the rows' change history.
    """
    target = _model(model)
    values = dict(fields)

    def hook(person: Any) -> None:
        from karni.people.services import redact_history

        rows = target._base_manager.filter(**{path: person})
        ids = list(rows.values_list("pk", flat=True))
        if not ids:
            return
        target._base_manager.filter(pk__in=ids).update(**values)
        if history:
            redact_history(target, ids, fields=list(values))

    hook.__qualname__ = f"erasable.{target._meta.label}"
    erase_hook(f"{target._meta.label}.{path}", replace=True)(hook)
    return hook


# duplicate rules -------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateRule:
    """A way two people may be the same human: ``find(queryset)`` yields groups.

    ``find`` takes the live people to look at and returns lists of person
    keys that this rule says belong together (two or more each).
    """

    name: str
    describe: str
    find: Callable[[Any], Iterable[list[Any]]]
    source: str = field(default="")


def register_duplicate_rule(
    name: str,
    find: Callable[[Any], Iterable[list[Any]]],
    *,
    describe: str = "",
    replace: bool = False,
) -> DuplicateRule:
    """Add a rule ``people.duplicates()`` applies (``E257`` when it is taken)."""
    if name in _DUPLICATE_RULES and not replace:
        raise KarniImproperlyConfigured(
            f"A duplicate rule named {name!r} is registered already. Pass replace=True to swap it.",
            code="E257",
        )
    rule = DuplicateRule(name=name, describe=describe or name, find=find, source=_caller_app())
    _DUPLICATE_RULES[name] = rule
    return rule


def duplicate_rules() -> dict[str, DuplicateRule]:
    """The registered duplicate rules, by name."""
    return dict(_DUPLICATE_RULES)


# startup ---------------------------------------------------------------------------------


def register_builtin_hooks() -> None:
    """Karni's own merge hooks and duplicate rules (memberships, addresses, emails, names)."""
    from karni.people import services
    from karni.people.models import Address, Membership

    merge_hook(Membership, replace=True)(services.merge_memberships)
    merge_hook(Address, replace=True)(services.merge_addresses)
    register_duplicate_rule(
        "email_tag",
        services.duplicates_by_email_tag,
        describe="The same email apart from a +tag (ana+shop@example.com and ana@example.com)",
        replace=True,
    )
    register_duplicate_rule(
        "name_without_email",
        services.duplicates_by_name,
        describe="The same full name, where at least one of them has no email",
        replace=True,
    )


def autodiscover() -> list[str]:
    """Import ``<app>/people.py`` of every installed app; returns the modules imported."""
    imported: list[str] = []
    for config in apps.get_app_configs():
        if config.name in ("karni", "karni.people") or config.module is None:
            continue
        if module_has_submodule(config.module, "people"):
            name = f"{config.name}.people"
            import_module(name)
            imported.append(name)
    return imported
