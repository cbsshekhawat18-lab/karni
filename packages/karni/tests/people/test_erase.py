"""Erasing a person on request, across both parts, and finding possible duplicates."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType

from karni import people
from karni.audit.models import ChangeBatch, ChangeLog
from karni.exceptions import KarniValueError
from karni.people.models import ERASED, Address, Membership, Person
from tests.helpdeskapp.models import Ticket
from tests.loyaltyapp.models import LoyaltyCard, Visit
from tests.people.conftest import make_user

pytestmark = pytest.mark.django_db


def _values_in_history(model: Any, pk: Any) -> set[str]:
    content_type = ContentType.objects.get_for_model(model)
    found: set[str] = set()
    for entry in ChangeLog.objects.filter(content_type=content_type, object_id=str(pk)):
        for values in entry.diff.values():
            found.update(str(value) for value in values if value is not None)
    return found


def test_erasing_a_person_anonymises_every_part(family: dict[str, Any]) -> None:
    person = family["drop"]
    user = make_user("ana+club@example.com")
    Person.objects.filter(pk=person.pk).update(user=user)
    ticket = Ticket.objects.filter(person=person).first()
    assert ticket is not None and "Ana L." in _values_in_history(Ticket, ticket.pk)

    erased = people.erase(person)

    # each part's erase hook ran: the help desk's tickets keep their subject, not the contact
    assert set(
        Ticket.objects.filter(person=person).values_list("contact_name", "contact_email")
    ) == {("", "")}
    assert "Ana L." not in _values_in_history(Ticket, ticket.pk)
    card = LoyaltyCard.objects.get(person=person)
    assert (card.points, card.nickname) == (5, "")
    assert Visit.objects.filter(person=person).count() == 1  # the rows stay, pointing at the key
    # the person keeps its key and loses every detail
    assert (erased.display_name, erased.email, erased.phone) == (ERASED, "", "")
    assert erased.user_id is None and erased.erased_at is not None and erased.deleted_at is not None
    assert not Person.objects.filter(pk=person.pk).exists()
    # addresses and memberships are gone, and no value is left in the history
    assert not Address.objects.filter(person=person).exists()
    assert not Membership.objects.filter(person=person).exists()
    history = _values_in_history(Person, person.pk)
    assert history <= {"[erased]"}, history
    assert ChangeBatch.objects.filter(kind="people.erase").count() == 1
    # the account itself stays: deleting it is the accounts' own flow
    user.refresh_from_db()
    assert user.is_active


def test_erasing_twice_does_nothing(family: dict[str, Any]) -> None:
    people.erase(family["keep"])
    people.erase(family["keep"])
    assert ChangeBatch.objects.filter(kind="people.erase").count() == 1


def test_erase_takes_a_person(family: dict[str, Any]) -> None:
    with pytest.raises(KarniValueError) as caught:
        people.erase(family["org"])
    assert caught.value.code == "E252"


def test_duplicates_find_what_an_email_check_misses(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    groups = people.duplicates()
    by_rule = {group.rule: {p.pk for p in group.people} for group in groups}
    assert by_rule == {"email_tag": {keep.pk, drop.pk}}
    walkin = Person.objects.create(given_name="Ana", family_name="Lima")
    named = people.duplicates(rules=["name_without_email"])
    assert [{p.pk for p in g.people} for g in named] == [{keep.pk, drop.pk, walkin.pk}]
    assert people.duplicates(person=Person.objects.create(email="solo@example.com")) == []
    with pytest.raises(KarniValueError) as caught:
        people.duplicates(rules=["phone"])
    assert caught.value.code == "E257"


def test_a_part_adds_its_own_duplicate_rule(family: dict[str, Any]) -> None:
    from karni.people import registry

    def same_phone(rows: Any) -> list[list[Any]]:
        found: dict[str, list[Any]] = {}
        for pk, phone in rows.exclude(phone="").values_list("pk", "phone"):
            found.setdefault(phone, []).append(pk)
        return [keys for keys in found.values() if len(keys) > 1]

    people.register_duplicate_rule("phone", same_phone, describe="The same phone")
    try:
        twin = Person.objects.create(email="other@example.com", phone="+44 20 7946 0001")
        groups = people.duplicates(rules=["phone"])
        assert [{p.pk for p in g.people} for g in groups] == [{family["drop"].pk, twin.pk}]
        with pytest.raises(Exception) as caught:
            people.register_duplicate_rule("phone", same_phone)
        assert "E257" in str(caught.value)
    finally:
        registry._DUPLICATE_RULES.pop("phone", None)
