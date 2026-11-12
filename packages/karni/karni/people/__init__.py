"""Experimental. The people contract: one record of each person and organisation, in every part.

A project that holds several parts (a shop, a CRM, bookings, courses) keeps
one :class:`~karni.people.models.Person` per human and one
:class:`~karni.people.models.Organisation` per company, and every part
points at them. Turn it on with ``KARNI_PEOPLE = True`` (``karni build``
writes it when karni.yaml points at ``people.Person``)::

    from karni import people

    person = people.resolve(email="ana@example.com", name="Ana Lima", source="shop")
    people.resolve(user=request.user)           # the signed-in person, linked once verified

    people.register_fact("orders", people.count_of(Order))  # in <app>/people.py
    Person.objects.with_facts("orders").filter(orders__gte=3)

    plan = people.merge_plan(keep, drop)       # the preview
    people.merge(keep, drop)                   # E250 to E252 when refused
    people.erase(person)                       # each part's erase hook, then the person

What is here: :func:`resolve` (find or create by account or email),
:func:`link_account` (an account is linked only once its email is
verified), the person facts registry (:func:`register_fact` and the
builders :func:`count_of`, :func:`sum_of`, :func:`latest_of`,
:func:`exists_of`), :func:`duplicates`, :func:`merge_plan` and
:func:`merge` with :func:`merge_hook`, :func:`erase` with
:func:`erase_hook` and :func:`erasable`, the family events
(:mod:`karni.people.events`), ``/api/people/`` and ``/api/organisations/``
(:mod:`karni.people.viewsets`), the admin, global search and the shared
seed pool (:func:`pool`).

The contract is versioned: :data:`CONTRACT` is its version, which a part's
recipe names in ``requires``. It is Experimental until the six recipes use
it (docs/stability.md); a breaking change after that warns for one minor
release first.

Override / escape hatch: ``KARNI_PEOPLE_RESOLVER`` (a :class:`Resolver`
subclass), the hook registries, ``KARNI_PEOPLE_LINK_ON_VERIFY``,
``KARNI_PEOPLE_API`` and ``KARNI_PEOPLE_MERGE_SKIP``. See docs/people.md.

The names are imported lazily (PEP 562): this package is imported while the
app registry is still loading, before its models exist.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from karni.people.registry import (
        Fact,
        count_of,
        duplicate_rules,
        erasable,
        erase_hook,
        exists_of,
        fact,
        facts,
        latest_of,
        merge_hook,
        register_duplicate_rule,
        register_fact,
        sum_of,
        unregister_fact,
    )
    from karni.people.seeds import pool
    from karni.people.services import (
        DuplicateGroup,
        MergePlan,
        MergeRefused,
        Resolver,
        duplicates,
        erase,
        get_resolver,
        link_account,
        merge,
        merge_plan,
        redact_history,
        resolve,
    )

#: Experimental. The version of the people contract. A breaking change raises it.
CONTRACT: Final = 1

__all__ = [
    "CONTRACT",
    "DuplicateGroup",
    "Fact",
    "MergePlan",
    "MergeRefused",
    "Resolver",
    "count_of",
    "duplicate_rules",
    "duplicates",
    "erasable",
    "erase",
    "erase_hook",
    "exists_of",
    "fact",
    "facts",
    "get_resolver",
    "latest_of",
    "link_account",
    "merge",
    "merge_hook",
    "merge_plan",
    "pool",
    "redact_history",
    "register_duplicate_rule",
    "register_fact",
    "resolve",
    "sum_of",
    "unregister_fact",
]

_REGISTRY = (
    "Fact",
    "count_of",
    "duplicate_rules",
    "erasable",
    "erase_hook",
    "exists_of",
    "fact",
    "facts",
    "latest_of",
    "merge_hook",
    "register_duplicate_rule",
    "register_fact",
    "sum_of",
    "unregister_fact",
)
_LAZY: Final[dict[str, str]] = {
    **{name: "karni.people.registry" for name in _REGISTRY},
    "pool": "karni.people.seeds",
    **{
        name: "karni.people.services"
        for name in (
            "DuplicateGroup",
            "MergePlan",
            "MergeRefused",
            "Resolver",
            "duplicates",
            "erase",
            "get_resolver",
            "link_account",
            "merge",
            "merge_plan",
            "redact_history",
            "resolve",
        )
    },
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*__all__, *globals()])
