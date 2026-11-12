"""Experimental. The people contract's operations: resolve, link, duplicates, merge, erase.

``people.resolve(...)`` is the one call a part makes when it meets someone:
a checkout, a booking, a web-to-lead form, an enrolment. It finds the person
by account or email and creates one when there is none, so one email is
one person in every part. :class:`Resolver` does the work, and
``KARNI_PEOPLE_RESOLVER`` swaps it.

An account is linked to a person only once its email is verified
(:func:`link_account`): a sign-up confirmed by email, a sign-in with an
email code, a social sign-in with a verified address. Before that, the
person stays a guest, so nobody takes over a guest's orders by typing their
email.

:func:`merge_plan` previews and :func:`merge` performs the merge of two
people (or two organisations): every foreign key and one-to-one to the
model, in every installed app, found through the models' meta, and every
``GenericForeignKey`` that points at it, is moved to the kept row, in one
transaction, with every moved row recorded in one audit ``ChangeBatch``.

:func:`erase` anonymises a person on request: each part's erase hook first,
then the person's own row, addresses and memberships, and the values in
their change history.

Override / escape hatch: subclass :class:`Resolver` and point
``KARNI_PEOPLE_RESOLVER`` at it; register merge and erase hooks
(:mod:`karni.people.registry`); ``KARNI_PEOPLE_MERGE_SKIP`` lists models a
merge leaves alone (``"app_label.Model"``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, models, router, transaction
from django.db.models.functions import Concat, Lower, Trim
from django.utils import timezone

from karni.conflicts import KarniConflict
from karni.exceptions import KarniImproperlyConfigured, KarniValueError
from karni.imports import import_setting

__all__ = [
    "DEFAULT_RESOLVER",
    "DuplicateGroup",
    "MergePlan",
    "MergeRefused",
    "Move",
    "Refusal",
    "Resolver",
    "duplicates",
    "erase",
    "get_resolver",
    "link_account",
    "merge",
    "merge_plan",
    "redact_history",
    "resolve",
]

DEFAULT_RESOLVER: Final = "karni.people.services.Resolver"
#: What a value in an erased row's change history becomes.
ERASED_VALUE: Final = "[erased]"
#: Apps a merge never moves rows of: the change history keeps its record's id.
_NEVER_MOVED: Final = frozenset({"karni_audit", "admin"})


class MergeRefused(KarniConflict):
    """Experimental. A merge Karni will not do (HTTP 409): ``E250`` to ``E252``."""


# resolve and link -------------------------------------------------------------------------


def _email_of(user: Any) -> str:
    from karni.people.models import normalize_email

    field_name = getattr(user, "EMAIL_FIELD", "email")
    return normalize_email(getattr(user, field_name, "") or "")


def _verified(user: Any) -> bool:
    """Whether ``user``'s email is proven: ``email_verified`` (Karni's single source of truth)."""
    return bool(getattr(user, "email_verified", False))


def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


class Resolver:
    """Experimental. How a part finds or creates the person it meets (``people.resolve``).

    Override / escape hatch: subclass it, override :meth:`find`,
    :meth:`create` or :meth:`fill`, and set ``KARNI_PEOPLE_RESOLVER`` to its
    dotted path.
    """

    def resolve(
        self,
        *,
        user: Any = None,
        email: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        create: bool = True,
        source: str = "",
        given_name: str | None = None,
        family_name: str | None = None,
    ) -> Any:
        """The person for ``user`` or ``email`` (created when missing and ``create``).

        With a ``user``, the person linked to that account wins. Otherwise the
        live person with the email (the account's email when no ``email`` is
        given). An account is linked to the person it finds or creates only
        when the account's email is verified and matches. Blank details on
        the person are filled from ``name`` and ``phone``; known ones are
        never overwritten. ``None`` when nothing is found and ``create`` is
        False. ``E253`` without a user or an email.
        """
        from karni.people.models import Person, normalize_email

        address = normalize_email(email) if email else ""
        anonymous = user is None or not getattr(user, "is_authenticated", False)
        if anonymous:
            user = None
        if user is None and not address:
            raise KarniValueError(
                "people.resolve() needs a user or an email: one email is one person, so "
                "a person cannot be found or created from a name alone.",
                code="E253",
            )
        if user is not None and not address:
            address = _email_of(user)
        with transaction.atomic(using=router.db_for_write(Person)):
            person = self.find(user=user, email=address)
            if person is None:
                if not create:
                    return None
                person = self.create(
                    email=address,
                    name=name or "",
                    phone=phone or "",
                    source=source,
                    given_name=given_name,
                    family_name=family_name,
                )
            else:
                self.fill(
                    person,
                    name=name or "",
                    phone=phone or "",
                    given_name=given_name,
                    family_name=family_name,
                )
            if user is not None and person.user_id is None:
                link_account(user, person=person, strict=False)
        return person

    def find(self, *, user: Any = None, email: str = "") -> Any:
        """The live person linked to ``user``, else the live person with ``email``, else ``None``.

        The row is locked for the rest of the transaction where the database
        can (PostgreSQL), so two checkouts with one email do not race.
        """
        from karni.people.models import Person

        rows = Person.objects.select_for_update()
        if user is not None:
            linked = rows.filter(user=user).first()
            if linked is not None:
                return linked
        if email:
            return rows.filter(email=email).first()
        return None

    def create(
        self,
        *,
        email: str,
        name: str,
        phone: str,
        source: str,
        given_name: str | None = None,
        family_name: str | None = None,
    ) -> Any:
        """Create the person. A concurrent create of the same email returns that one instead."""
        from karni.people.models import Person

        given, family = _split_name(name)
        person = Person(
            email=email,
            given_name=(given_name if given_name is not None else given)[:150],
            family_name=(family_name if family_name is not None else family)[:150],
            phone=phone[:40],
            source=source[:64],
        )
        try:
            with transaction.atomic(using=router.db_for_write(Person)):
                person.save()
        except IntegrityError:
            existing = Person.objects.filter(email=email).first() if email else None
            if existing is None:
                raise
            return existing
        return person

    def fill(
        self,
        person: Any,
        *,
        name: str,
        phone: str,
        given_name: str | None = None,
        family_name: str | None = None,
    ) -> None:
        """Fill the person's blank names and phone from what the part knows. Never overwrites."""
        given, family = _split_name(name)
        given = given_name if given_name is not None else given
        family = family_name if family_name is not None else family
        changed: list[str] = []
        if not person.given_name and not person.family_name and (given or family):
            person.given_name, person.family_name = given[:150], family[:150]
            changed += ["given_name", "family_name"]
        if not person.phone and phone:
            person.phone = phone[:40]
            changed.append("phone")
        if changed:
            person.save(update_fields=changed)

    def link(self, user: Any, person: Any) -> bool:
        """Link ``user`` to ``person``; ``False`` when either is linked elsewhere already."""
        from karni.people.models import Person

        if person.user_id is not None:
            return bool(person.user_id == user.pk)
        if Person.objects.filter(user=user).exclude(pk=person.pk).exists():
            return False
        person.user = user
        if not person.email:
            person.email = _email_of(user)
        if not person.given_name and not person.family_name:
            person.given_name = str(getattr(user, "first_name", "") or "")[:150]
            person.family_name = str(getattr(user, "last_name", "") or "")[:150]
        person.save()
        return True


def get_resolver() -> Resolver:
    """Experimental. The :class:`Resolver` ``KARNI_PEOPLE_RESOLVER`` names (a class or a path)."""
    value = getattr(settings, "KARNI_PEOPLE_RESOLVER", DEFAULT_RESOLVER) or DEFAULT_RESOLVER
    resolver = import_setting("KARNI_PEOPLE_RESOLVER", value) if isinstance(value, str) else value
    if isinstance(resolver, type):
        resolver = resolver()
    if not callable(getattr(resolver, "resolve", None)):
        raise KarniImproperlyConfigured(
            f"KARNI_PEOPLE_RESOLVER is {value!r}, which has no resolve() method. Point it at a "
            "subclass of karni.people.services.Resolver.",
            code="E253",
        )
    return resolver  # type: ignore[no-any-return]


def resolve(
    user: Any = None,
    email: str | None = None,
    name: str | None = None,
    phone: str | None = None,
    create: bool = True,
    *,
    source: str = "",
    given_name: str | None = None,
    family_name: str | None = None,
) -> Any:
    """Experimental. Find or create the person a part meets (see :meth:`Resolver.resolve`).

    ``source`` records the part that created a new person (its app label).
    """
    return get_resolver().resolve(
        user=user,
        email=email,
        name=name,
        phone=phone,
        create=create,
        source=source,
        given_name=given_name,
        family_name=family_name,
    )


def link_account(user: Any, *, person: Any = None, strict: bool = True, create: bool = True) -> Any:
    """Experimental. Link ``user`` to its person once its email is verified; returns the person.

    ``person`` defaults to the live person with the account's email; with
    ``create`` one is made when there is none, else nothing is linked and
    ``None`` comes back. Refused (``E258``) when the account's email is not
    verified, when ``person`` has another email, or when it has another
    account; with ``strict=False`` a refusal returns ``None`` instead. An
    account already linked keeps its person. One query when there is
    nothing to link. Publishes ``people.person.linked``.
    """
    from django.db.models import Q

    from karni.people.events import publish
    from karni.people.models import Person

    def refuse(message: str) -> None:
        if strict:
            raise KarniValueError(message, code="E258")

    email = _email_of(user)
    if not _verified(user) or not email:
        refuse(
            f"The account {getattr(user, 'pk', user)} has no verified email, and an account is "
            "linked to a person only after its email is verified. Verify the email first."
        )
        return None
    found = list(Person.objects.filter(Q(user=user) | Q(email=email))[:2])
    for candidate in found:
        if candidate.user_id == user.pk:
            return candidate
    if person is None:
        person = next((candidate for candidate in found if candidate.email == email), None)
        if person is None and not create:
            return None
    with transaction.atomic(using=router.db_for_write(Person)):
        if person is None:
            person = Person(email=email, source="accounts")
        elif person.pk is not None:
            person = Person.objects.select_for_update().filter(pk=person.pk).first() or person
        if person.email and person.email != email:
            refuse(
                f"Person {person.pk} has the email {person.email}, and the account's verified "
                f"email is {email}. Link the account to the person with its email."
            )
            return None
        if not get_resolver().link(user, person):
            refuse(
                f"Person {person.pk} is linked to another account already. Merge the accounts "
                "first, by hand."
            )
            return None
        publish("people.person.linked", subject=person, person=person, user=user)
    return person


# duplicates ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateGroup:
    """Experimental. People one rule says may be the same human, oldest first."""

    rule: str
    people: tuple[Any, ...]


def _tagless(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local.split('+', 1)[0]}@{domain}" if domain else email


def duplicates_by_email_tag(people: Any) -> list[list[Any]]:
    """The same email apart from a ``+tag`` in the local part."""
    tagged = people.filter(email__contains="+").values_list("pk", "email")
    groups: dict[str, list[Any]] = defaultdict(list)
    for pk, email in tagged:
        groups[_tagless(email)].append(pk)
    if not groups:
        return []
    for pk, email in people.filter(email__in=list(groups)).values_list("pk", "email"):
        groups[email].append(pk)
    return [keys for keys in groups.values() if len(keys) > 1]


def duplicates_by_name(people: Any) -> list[list[Any]]:
    """The same full name, where at least one of the people has no email."""
    named = people.exclude(given_name="", family_name="").annotate(
        _key=Lower(Trim(Concat("given_name", models.Value(" "), "family_name")))
    )
    keys = (
        named.values("_key")
        .annotate(total=models.Count("pk"), blank=models.Count("pk", filter=models.Q(email="")))
        .filter(total__gt=1, blank__gt=0)
        .values_list("_key", flat=True)
    )
    groups: dict[str, list[Any]] = defaultdict(list)
    for pk, key in named.filter(_key__in=list(keys)).values_list("pk", "_key"):
        groups[key].append(pk)
    return [found for found in groups.values() if len(found) > 1]


def duplicates(
    people: Any = None, *, rules: Sequence[str] | None = None, person: Any = None
) -> list[DuplicateGroup]:
    """Experimental. Groups of live people that may be the same human, by each rule.

    Email is the identity, so two live people never share one: the rules
    look for what an email check misses (``email_tag``,
    ``name_without_email``, and whatever parts register). ``people`` narrows
    the rows looked at, ``rules`` the rules applied, and ``person`` keeps
    only the groups that include that person.
    """
    from karni.people.models import Person
    from karni.people.registry import duplicate_rules

    queryset = people if people is not None else Person.objects.all()
    registered = duplicate_rules()
    chosen = list(registered) if rules is None else list(rules)
    unknown = [name for name in chosen if name not in registered]
    if unknown:
        raise KarniValueError(
            f"No duplicate rule named {', '.join(unknown)}. Rules: {', '.join(registered)}.",
            code="E257",
        )
    found: list[tuple[str, list[Any]]] = []
    for name in chosen:
        for keys in registered[name].find(queryset):
            if person is None or person.pk in keys:
                found.append((name, list(keys)))
    rows = Person.objects.in_bulk([key for _, keys in found for key in keys])
    groups: list[DuplicateGroup] = []
    for name, keys in found:
        members = sorted(
            (rows[key] for key in dict.fromkeys(keys) if key in rows),
            key=lambda row: (row.created_at, str(row.pk)),
        )
        if len(members) > 1:
            groups.append(DuplicateGroup(rule=name, people=tuple(members)))
    return groups


# merge -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    """Experimental. Rows a merge moves from the dropped record to the kept one.

    ``kind`` is ``"foreign_key"``, ``"one_to_one"``, ``"generic"`` or
    ``"hook"`` (a merge hook decides). ``rows`` counts the rows that point
    at the dropped record now.
    """

    model: str
    field: str
    kind: str
    rows: int

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "field": self.field, "kind": self.kind, "rows": self.rows}


@dataclass(frozen=True)
class Refusal:
    """Experimental. Why a merge cannot happen: a code and a sentence."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class MergePlan:
    """Experimental. What :func:`merge` would do: the preview a merge screen shows."""

    keep: Any
    drop: Any
    moves: list[Move] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    #: Fields of ``keep`` that take ``drop``'s value because ``keep``'s is blank.
    fills: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return not self.refusals

    def as_dict(self) -> dict[str, Any]:
        return {
            "keep": str(self.keep.pk),
            "drop": str(self.drop.pk),
            "allowed": self.allowed,
            "moves": [move.as_dict() for move in self.moves],
            "refusals": [refusal.as_dict() for refusal in self.refusals],
            "fills": {name: _plain(value) for name, value in self.fills.items()},
        }


def _plain(value: Any) -> Any:
    if isinstance(value, models.Model):
        return str(value.pk)
    return value


def _skipped() -> frozenset[str]:
    return frozenset(getattr(settings, "KARNI_PEOPLE_MERGE_SKIP", ()) or ())


def _relations(model: type[models.Model]) -> list[Any]:
    """Every concrete foreign key and one-to-one of an installed model that points at ``model``."""
    skipped = _skipped()
    found: list[Any] = []
    for other in apps.get_models():
        if other._meta.app_label in _NEVER_MOVED or other._meta.label in skipped:
            continue
        if other._meta.proxy or not other._meta.managed:
            continue
        for relation in other._meta.concrete_fields:
            if relation.is_relation and relation.related_model is model and relation.many_to_one:
                found.append(relation)
            elif relation.is_relation and relation.related_model is model and relation.one_to_one:
                found.append(relation)
    return found


def _generic_relations(model: type[models.Model]) -> list[GenericForeignKey]:
    """Every ``GenericForeignKey`` of an installed model (it may point at ``model``)."""
    skipped = _skipped()
    found: list[GenericForeignKey] = []
    for other in apps.get_models():
        if other._meta.app_label in _NEVER_MOVED or other._meta.label in skipped:
            continue
        found.extend(
            gfk for gfk in other._meta.private_fields if isinstance(gfk, GenericForeignKey)
        )
    return found


def _generic_rows(gfk: GenericForeignKey, record: Any) -> Any:
    content_type = ContentType.objects.get_for_model(type(record), for_concrete_model=False)
    object_field = gfk.model._meta.get_field(gfk.fk_field)
    value = (
        str(record.pk)
        if isinstance(object_field, models.CharField | models.TextField)
        else record.pk
    )
    return gfk.model._base_manager.filter(
        **{gfk.ct_field: content_type, gfk.fk_field: value}
    ), object_field


def _label(model: type[models.Model]) -> str:
    return str(model._meta.label)


_FILLED: Final[dict[str, tuple[str, ...]]] = {
    "people.Person": (
        "given_name",
        "family_name",
        "phone",
        "organisation",
        "time_zone",
        "language",
    ),
    "people.Organisation": ("domain", "phone"),
}


def merge_plan(keep: Any, drop: Any) -> MergePlan:
    """Experimental. What merging ``drop`` into ``keep`` would do, without doing it.

    ``keep`` and ``drop`` are two people or two organisations. The plan lists
    the rows that would move, by model and field, the blank fields ``keep``
    would take from ``drop``, and every reason the merge would be refused.
    """
    from karni.people.models import Organisation, Person
    from karni.people.registry import merge_hooks

    plan = MergePlan(keep=keep, drop=drop)
    model = type(keep)
    if model not in (Person, Organisation) or type(drop) is not model:
        raise KarniValueError(
            "people.merge() takes two people or two organisations, of the same kind.",
            code="E252",
        )
    noun = model._meta.verbose_name
    if keep.pk == drop.pk:
        plan.refusals.append(Refusal("E252", f"A {noun} cannot be merged into itself."))
    for record, role in ((keep, "kept"), (drop, "dropped")):
        if record.deleted_at is not None or record.merged_into_id is not None:
            plan.refusals.append(
                Refusal(
                    "E252",
                    f"The {role} {noun} {record.pk} is deleted or merged already. Merge live "
                    f"{model._meta.verbose_name_plural} only.",
                )
            )
    if model is Person and keep.user_id is not None and drop.user_id is not None:
        plan.refusals.append(
            Refusal(
                "E250",
                f"Both people have an account ({keep.user_id} and {drop.user_id}). Accounts are "
                "merged first, by hand: delete or unlink one of them, then merge the people.",
            )
        )
    hooks = merge_hooks()
    for relation in _relations(model):
        other = relation.model
        moved = other._base_manager.filter(**{relation.name: drop})
        count = moved.count()
        if not count:
            continue
        if other in hooks:
            plan.moves.append(Move(_label(other), relation.name, "hook", count))
            continue
        if relation.one_to_one:
            if other._base_manager.filter(**{relation.name: keep}).exists():
                plan.refusals.append(
                    Refusal(
                        "E251",
                        f"Both {model._meta.verbose_name_plural} have a {_label(other)}, and "
                        f"{_label(other)} has no merge hook to combine them. Register one with "
                        f"people.merge_hook({other.__name__}) in "
                        f"{other._meta.app_label}/people.py.",
                    )
                )
                continue
            plan.moves.append(Move(_label(other), relation.name, "one_to_one", count))
        else:
            plan.moves.append(Move(_label(other), relation.name, "foreign_key", count))
    for gfk in _generic_relations(model):
        rows, _ = _generic_rows(gfk, drop)
        count = rows.count()
        if count:
            plan.moves.append(Move(_label(gfk.model), gfk.name, "generic", count))
    for name in _FILLED[_label(model)]:
        attname = model._meta.get_field(name).attname
        if not getattr(keep, attname) and getattr(drop, attname):
            plan.fills[name] = getattr(drop, name)
    if model is Person:
        if not keep.email and drop.email:
            plan.fills["email"] = drop.email
        if keep.user_id is None and drop.user_id is not None:
            plan.fills["user"] = drop.user
    return plan


def _history(model: type[models.Model], ids: Iterable[Any], name: str, old: Any, new: Any) -> None:
    """One change-log entry per moved row, in the current batch: ``{name: [old, new]}``."""
    from karni.audit.capture import current_batch_id
    from karni.audit.models import ChangeLog
    from karni.middleware import get_current_user
    from karni.tracing import get_request_id

    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    actor = get_current_user()
    batch = current_batch_id()
    request_id = get_request_id() or ""
    ChangeLog.objects.bulk_create(
        [
            ChangeLog(
                content_type=content_type,
                object_id=str(pk),
                actor_id=getattr(actor, "pk", None),
                action=ChangeLog.Action.UPDATE,
                diff={name: [str(old), str(new)]},
                batch_id=batch,
                request_id=request_id,
            )
            for pk in ids
        ]
    )


def _move(model: type[models.Model], rows: Any, name: str, keep: Any, drop: Any) -> int:
    ids = list(rows.values_list("pk", flat=True))
    if not ids:
        return 0
    try:
        with transaction.atomic(using=router.db_for_write(model)):
            model._base_manager.filter(pk__in=ids).update(**{name: keep})
    except IntegrityError as exc:
        raise MergeRefused(
            f"Moving {_label(model)}.{name} from {drop.pk} to {keep.pk} breaks a unique rule of "
            f"{_label(model)} (both have a row for the same thing). Register a merge hook with "
            f"people.merge_hook({model.__name__}) that decides which row stays. ({exc})",
            code="E251",
            details={"model": _label(model), "field": name},
        ) from exc
    _history(model, ids, name, drop.pk, keep.pk)
    return len(ids)


def merge(keep: Any, drop: Any) -> MergePlan:
    """Experimental. Merge ``drop`` into ``keep`` (two people, or two organisations).

    In one transaction, with both rows locked: the plan is made again and
    refused with :class:`MergeRefused` (``E250`` to ``E252``, HTTP 409) when
    it has a refusal; merge hooks run; every row that still points at
    ``drop`` is moved to ``keep``; ``keep`` takes ``drop``'s values where
    its own are blank (an account included); ``drop`` gets ``merged_into``
    and is soft-deleted. Every moved row and both records' changes are in
    one audit ``ChangeBatch`` (kind ``people.merge``). Publishes
    ``people.person.merged`` or ``people.organisation.merged``. Returns the plan.
    """
    from karni.audit.capture import change_batch
    from karni.people.events import publish
    from karni.people.models import Person
    from karni.people.registry import merge_hooks

    model = type(keep)
    using = router.db_for_write(model)
    with transaction.atomic(using=using):
        locked = model._base_manager.select_for_update().in_bulk([keep.pk, drop.pk])
        keep = locked.get(keep.pk, keep)
        drop = locked.get(drop.pk, drop)
        plan = merge_plan(keep, drop)
        if plan.refusals:
            first = plan.refusals[0]
            raise MergeRefused(
                " ".join(refusal.message for refusal in plan.refusals),
                code=first.code,
                details=plan.as_dict(),
            )
        noun = model._meta.model_name
        meta = {"kept": str(keep.pk), "removed": str(drop.pk)}
        with change_batch("people.merge", f"{noun} {drop.pk} into {keep.pk}", meta):
            hooks = merge_hooks()
            for hooked in dict.fromkeys(r.model for r in _relations(model) if r.model in hooks):
                hooks[hooked](keep, drop)
            for relation in _relations(model):
                rows = relation.model._base_manager.filter(**{relation.name: drop})
                if relation.one_to_one:
                    deleted = getattr(relation.model, "deleted_at", None)
                    if deleted is not None:
                        rows = rows.filter(deleted_at__isnull=True)
                _move(relation.model, rows, relation.name, keep, drop)
            for gfk in _generic_relations(model):
                rows, object_field = _generic_rows(gfk, drop)
                ids = list(rows.values_list("pk", flat=True))
                if ids:
                    value = (
                        str(keep.pk)
                        if isinstance(object_field, models.CharField | models.TextField)
                        else keep.pk
                    )
                    gfk.model._base_manager.filter(pk__in=ids).update(**{gfk.fk_field: value})
                    _history(gfk.model, ids, gfk.fk_field, drop.pk, keep.pk)
            fills = dict(plan.fills)
            user = fills.pop("user", None)
            email = fills.pop("email", None)
            drop.merged_into = keep
            if model is Person:
                drop.user = None
            drop.save()
            drop.delete()
            for name, value in fills.items():
                setattr(keep, name, value)
            if email:
                keep.email = email
            if user is not None:
                keep.user = user
            keep.save()
        publish(
            f"people.{noun}.merged",
            subject=keep,
            person=keep if model is Person else None,
            kept=keep,
            removed=drop,
        )
    return plan


def merge_memberships(keep: Any, drop: Any) -> None:
    """Karni's merge hook for Membership: one membership per organisation and person."""
    from karni.people.models import Membership, Person

    if isinstance(keep, Person):
        mine = dict(Membership.objects.filter(person=keep).values_list("organisation_id", "pk"))
        theirs = Membership.objects.filter(person=drop, organisation_id__in=list(mine))
        clash = "organisation_id"
    else:
        mine = dict(Membership.objects.filter(organisation=keep).values_list("person_id", "pk"))
        theirs = Membership.objects.filter(organisation=drop, person_id__in=list(mine))
        clash = "person_id"
    for membership in theirs:
        kept = Membership.objects.get(pk=mine[getattr(membership, clash)])
        if not kept.title and membership.title:
            kept.title = membership.title
            kept.save(update_fields=["title"])
        membership.delete()


def merge_addresses(keep: Any, drop: Any) -> None:
    """Karni's merge hook for Address: the kept record's defaults stay the defaults."""
    from karni.people.models import Address, Person

    owner = "person" if isinstance(keep, Person) else "organisation"
    for flag in Address.DEFAULT_FLAGS:
        if Address.objects.filter(**{owner: keep, flag: True}).exists():
            for address in Address.objects.filter(**{owner: drop, flag: True}):
                setattr(address, flag, False)
                address.save(update_fields=[flag])


# erase -------------------------------------------------------------------------------


def redact_history(
    model: type[models.Model], ids: Iterable[Any], *, fields: Sequence[str] | None = None
) -> int:
    """Experimental. Replace values in the change history of ``model``'s rows ``ids``.

    Every old and new value of ``fields`` (``None``: every field) becomes
    ``[erased]``. Returns the number of entries changed. What erase hooks
    use so an erased name does not live on in the history.
    """
    from karni.audit.models import ChangeLog

    keys = [str(pk) for pk in ids]
    if not keys:
        return 0
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    changed: list[Any] = []
    for entry in ChangeLog.objects.filter(content_type=content_type, object_id__in=keys):
        if not isinstance(entry.diff, dict):
            continue
        diff = dict(entry.diff)
        touched = False
        for name, values in diff.items():
            if fields is not None and name not in fields:
                continue
            if isinstance(values, list):
                redacted = [None if value is None else ERASED_VALUE for value in values]
                if redacted != values:
                    diff[name] = redacted
                    touched = True
        if touched:
            entry.diff = diff
            changed.append(entry)
    if changed:
        ChangeLog.objects.bulk_update(changed, ["diff"])
    return len(changed)


#: Person fields erase blanks, with the value each takes.
_ERASED_FIELDS: Final[dict[str, Any]] = {
    "given_name": "",
    "family_name": "",
    "email": "",
    "phone": "",
    "time_zone": "",
    "language": "",
    "organisation": None,
    "user": None,
}
#: Address fields erase blanks.
_ERASED_ADDRESS: Final[dict[str, Any]] = {
    "label": "",
    "line1": "",
    "line2": "",
    "city": "",
    "region": "",
    "postcode": "",
    "country": "",
    "is_default_billing": False,
    "is_default_shipping": False,
}


def erase(person: Any) -> Any:
    """Experimental. Erase a person's data on their request; returns the erased person.

    In one transaction: every registered erase hook runs (each part
    anonymises its rows: an order keeps its amounts and loses the name);
    the person's addresses are blanked and deleted and its memberships
    deleted; the person keeps its key (rows that point at it still resolve)
    and loses every detail, is unlinked from its account, gets
    ``erased_at`` and is soft-deleted; and the change history of the person
    and its addresses keeps no value. The rows are written with
    ``QuerySet.update()``, so no listener sees the old values and the
    history gets one entry per row that says what was erased, without the
    values. The user account itself is not deleted: that is the accounts'
    own flow. Erasing an erased person does nothing. Publishes
    ``people.person.erased``.
    """
    from karni.audit.capture import change_batch
    from karni.people.events import publish
    from karni.people.models import ERASED, Address, Membership, Person
    from karni.people.registry import erase_hooks

    if not isinstance(person, Person):
        raise KarniValueError("people.erase() takes a Person.", code="E252")
    using = router.db_for_write(Person)
    with transaction.atomic(using=using):
        person = Person._base_manager.select_for_update().get(pk=person.pk)
        if person.erased_at is not None:
            return person
        now = timezone.now()
        with change_batch("people.erase", f"person {person.pk}", {"person": str(person.pk)}):
            for hook in erase_hooks().values():
                hook(person)
            addresses = list(
                Address._base_manager.filter(person=person).values_list("pk", flat=True)
            )
            Address._base_manager.filter(pk__in=addresses).update(**_ERASED_ADDRESS, deleted_at=now)
            redact_history(Address, addresses)
            _history_erased(Address, addresses, list(_ERASED_ADDRESS))
            memberships = list(
                Membership._base_manager.filter(person=person).values_list("pk", flat=True)
            )
            Membership._base_manager.filter(pk__in=memberships).update(title="", deleted_at=now)
            Person._base_manager.filter(pk=person.pk).update(
                **_ERASED_FIELDS,
                display_name=ERASED,
                erased_at=now,
                deleted_at=person.deleted_at or now,
            )
            redact_history(Person, [person.pk])
            _history_erased(Person, [person.pk], [*_ERASED_FIELDS, "display_name"])
        person.refresh_from_db()
        publish("people.person.erased", subject=person, person=person)
    return person


def _history_erased(model: type[models.Model], ids: Sequence[Any], names: Sequence[str]) -> None:
    """One entry per erased row: each erased field, its values replaced by ``[erased]``."""
    from karni.audit.capture import current_batch_id
    from karni.audit.models import ChangeLog
    from karni.middleware import get_current_user
    from karni.tracing import get_request_id

    if not ids:
        return
    content_type = ContentType.objects.get_for_model(model, for_concrete_model=False)
    actor = get_current_user()
    ChangeLog.objects.bulk_create(
        [
            ChangeLog(
                content_type=content_type,
                object_id=str(pk),
                actor_id=getattr(actor, "pk", None),
                action=ChangeLog.Action.DELETE,
                diff={name: [ERASED_VALUE, None] for name in names},
                batch_id=current_batch_id(),
                request_id=get_request_id() or "",
            )
            for pk in ids
        ]
    )
