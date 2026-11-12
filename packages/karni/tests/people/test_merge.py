"""Merging two people across two parts: the preview, the merge, its refusals and its record."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings

from karni import people
from karni.audit.models import ChangeBatch, ChangeLog
from karni.exceptions import KarniValueError
from karni.people import registry
from karni.people.models import Address, Membership, Organisation, Person
from karni.people.services import MergeRefused
from tests.helpdeskapp.models import Note, SupportProfile, Ticket
from tests.loyaltyapp.models import LoyaltyCard, Visit
from tests.people.conftest import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def without_hook() -> Iterator[Any]:
    """Take one model's merge hook away for the test, then put it back."""
    taken: dict[Any, Any] = {}

    def remove(model: Any) -> None:
        taken[model] = registry._MERGE_HOOKS.pop(model)

    yield remove
    registry._MERGE_HOOKS.update(taken)


def _moves(plan: Any) -> dict[str, tuple[str, int]]:
    return {f"{m.model}.{m.field}": (m.kind, m.rows) for m in plan.moves}


def test_the_plan_previews_every_part_without_changing_anything(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    plan = people.merge_plan(keep, drop)
    assert plan.allowed and plan.refusals == []
    moves = _moves(plan)
    assert moves["loyaltyapp.LoyaltyCard.person"] == ("hook", 1)
    assert moves["helpdeskapp.SupportProfile.person"] == ("hook", 1)
    assert moves["loyaltyapp.Visit.person"] == ("foreign_key", 1)
    assert moves["helpdeskapp.Ticket.person"] == ("foreign_key", 2)
    assert moves["helpdeskapp.Note.subject"] == ("generic", 1)
    assert moves["people.Membership.person"] == ("hook", 2)
    assert moves["people.Address.person"] == ("hook", 1)
    assert plan.fills == {"phone": "+44 20 7946 0001"}
    assert Ticket.objects.filter(person=drop).count() == 2  # nothing moved yet
    assert plan.as_dict()["moves"][0].keys() == {"model", "field", "kind", "rows"}


def test_merging_moves_every_row_of_every_part(family: dict[str, Any]) -> None:
    keep, drop, org, other = family["keep"], family["drop"], family["org"], family["other"]
    people.merge(keep, drop)

    # the two parts' rows now point at the kept person
    assert Visit.objects.filter(person=keep).count() == 3
    assert Ticket.objects.filter(person=keep).count() == 3
    assert not Visit.objects.filter(person=drop).exists()
    # each part's merge hook combined the profiles
    card = LoyaltyCard.objects.get(person=keep)
    assert (card.points, card.nickname) == (15, "Annie")
    assert SupportProfile.objects.get(person=keep).plan == "priority"
    assert not LoyaltyCard.objects.filter(person=drop).exists()
    # a note on the dropped person, by content type and id, moved too
    note = Note.objects.get()
    assert note.subject == keep
    # one membership per organisation, the title kept; one default billing address
    memberships = {m.organisation_id: m.title for m in Membership.objects.filter(person=keep)}
    assert memberships == {org.pk: "Owner", other.pk: "Buyer"}
    assert Address.objects.filter(person=keep).count() == 2
    assert Address.objects.filter(person=keep, is_default_billing=True).get().line1 == "1 Mill Lane"
    # the person facts read the merged person
    merged = Person.objects.with_facts("visits", "open_tickets").get(pk=keep.pk)
    assert (merged.visits, merged.open_tickets) == (3, 2)
    # the kept person filled its blanks, the dropped one says where it went
    keep.refresh_from_db()
    assert keep.phone == "+44 20 7946 0001"
    gone = Person._base_manager.get(pk=drop.pk)
    assert gone.merged_into_id == keep.pk and gone.deleted_at is not None
    assert not Person.objects.filter(pk=drop.pk).exists()


def test_a_merge_is_one_change_batch_with_every_moved_row(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    tickets = set(Ticket.objects.filter(person=drop).values_list("pk", flat=True))
    people.merge(keep, drop)
    batch = ChangeBatch.objects.get(kind="people.merge")
    assert batch.meta == {"kept": str(keep.pk), "removed": str(drop.pk)}
    ticket_type = ContentType.objects.get_for_model(Ticket)
    moved = ChangeLog.objects.filter(batch=batch, content_type=ticket_type)
    assert {entry.object_id for entry in moved} == {str(pk) for pk in tickets}
    assert all(e.diff == {"person": [str(drop.pk), str(keep.pk)]} for e in moved)
    person_type = ContentType.objects.get_for_model(Person)
    assert ChangeLog.objects.filter(batch=batch, content_type=person_type).exists()


def test_a_merge_publishes_the_merged_event(family: dict[str, Any]) -> None:
    seen: list[dict[str, Any]] = []

    def collect(sender: Any, payload: dict[str, Any], **kwargs: Any) -> None:
        seen.append(payload)

    people.events.person_merged.connect(collect, dispatch_uid="test-merged", weak=False)
    try:
        people.merge(family["keep"], family["drop"])
    finally:
        people.events.person_merged.disconnect(dispatch_uid="test-merged")
    assert seen[0]["kept"] == str(family["keep"].pk)
    assert seen[0]["removed"] == str(family["drop"].pk)
    assert seen[0]["person"] == str(family["keep"].pk)


def test_two_profiles_without_a_hook_are_refused_naming_the_model(
    family: dict[str, Any], without_hook: Any
) -> None:
    without_hook(SupportProfile)
    plan = people.merge_plan(family["keep"], family["drop"])
    assert [r.code for r in plan.refusals] == ["E251"]
    assert "helpdeskapp.SupportProfile" in plan.refusals[0].message
    with pytest.raises(MergeRefused) as caught:
        people.merge(family["keep"], family["drop"])
    assert caught.value.code == "E251" and caught.value.status == 409
    assert Ticket.objects.filter(person=family["drop"]).count() == 2  # nothing moved


def test_a_unique_clash_without_a_hook_is_refused_and_rolled_back(
    family: dict[str, Any], without_hook: Any
) -> None:
    without_hook(Membership)
    with pytest.raises(MergeRefused) as caught:
        people.merge(family["keep"], family["drop"])
    assert caught.value.code == "E251" and "people.Membership" in str(caught.value)
    assert Visit.objects.filter(person=family["drop"]).count() == 1
    assert Person.objects.filter(pk=family["drop"].pk).exists()


def test_two_accounts_are_refused() -> None:
    first = Person.objects.create(email="yara@example.com", user=make_user("yara@example.com"))
    second = Person.objects.create(email="yara@example.org", user=make_user("yara@example.org"))
    with pytest.raises(MergeRefused) as caught:
        people.merge(first, second)
    assert caught.value.code == "E250"


def test_the_account_moves_to_the_kept_person() -> None:
    user = make_user("zoe@example.com")
    with_account = Person.objects.create(email="zoe@example.com", user=user)
    guest = Person.objects.create(given_name="Zoe", family_name="Zhang")
    plan = people.merge(guest, with_account)
    guest.refresh_from_db()
    assert guest.user_id == user.pk and guest.email == "zoe@example.com"
    assert plan.fills["email"] == "zoe@example.com"
    assert people.resolve(user=user).pk == guest.pk


def test_records_a_merge_does_not_take(family: dict[str, Any]) -> None:
    keep, drop = family["keep"], family["drop"]
    assert [r.code for r in people.merge_plan(keep, keep).refusals] == ["E252"]
    with pytest.raises(KarniValueError) as caught:
        people.merge_plan(keep, family["org"])
    assert caught.value.code == "E252"
    people.merge(keep, drop)
    with pytest.raises(MergeRefused) as refused:
        people.merge(keep, drop)
    assert refused.value.code == "E252"


def test_organisations_merge_the_same_way(family: dict[str, Any]) -> None:
    org, other = family["org"], family["other"]
    person = family["keep"]
    person.organisation = other
    person.save()
    copy = Organisation.objects.create(name="Fernwood Design Ltd", phone="+44 20 7946 0100")
    Membership.objects.create(person=family["drop"], organisation=copy, title="Founder")
    people.merge(org, other)
    person.refresh_from_db()
    assert person.organisation_id == org.pk
    # Ana's second record was a member of both: one membership is left, its title kept
    assert Membership.objects.filter(organisation=org).count() == 2
    assert Membership.objects.get(organisation=org, person=family["drop"]).title == "Owner"
    assert not Membership.objects.filter(organisation=other).exists()
    assert Organisation._base_manager.get(pk=other.pk).merged_into_id == org.pk
    people.merge(org, copy)
    org.refresh_from_db()
    assert org.phone == "+44 20 7946 0100"


def test_a_skipped_model_keeps_pointing_at_the_merged_record(family: dict[str, Any]) -> None:
    with override_settings(KARNI_PEOPLE_MERGE_SKIP=["helpdeskapp.Note"]):
        people.merge(family["keep"], family["drop"])
    assert Note.objects.get().object_id == str(family["drop"].pk)
