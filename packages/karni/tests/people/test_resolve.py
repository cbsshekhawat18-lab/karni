"""``people.resolve``, the account link on a verified email, and the people events."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.dispatch import receiver
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from karni import people
from karni.accounts.services import prove_address
from karni.exceptions import KarniValueError
from karni.people import events
from karni.people.models import Person
from karni.people.services import Resolver
from tests.people.conftest import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def published() -> Iterator[list[dict[str, Any]]]:
    """Every people event published during the test, as payloads."""
    found: list[dict[str, Any]] = []

    def collect(sender: Any, payload: dict[str, Any], **kwargs: Any) -> None:
        found.append(payload)

    for spec in events.EVENTS.values():
        spec.signal.connect(collect, dispatch_uid=f"test-{spec.name}", weak=False)
    yield found
    for spec in events.EVENTS.values():
        spec.signal.disconnect(dispatch_uid=f"test-{spec.name}")


def test_one_email_is_one_person(published: list[dict[str, Any]]) -> None:
    first = people.resolve(email="Kemi.Mensah@Example.com", name="Kemi Mensah", source="shop")
    again = people.resolve(email="kemi.mensah@example.com", name="K. M.", phone="+44 20 7946 0003")
    assert first.pk == again.pk and Person.objects.count() == 1
    again.refresh_from_db()
    assert (again.given_name, again.family_name, again.source) == ("Kemi", "Mensah", "shop")
    assert again.phone == "+44 20 7946 0003"  # a blank detail is filled, a known one stays
    created = [p for p in published if p["name"] == "people.person.created"]
    assert len(created) == 1 and created[0]["source"] == "shop"
    assert created[0]["subject"] == {"model": "people.person", "id": str(first.pk)}
    assert set(created[0]) >= {"id", "version", "occurred_at", "actor", "person", "request_id"}


def test_resolve_without_creating_and_without_an_identity() -> None:
    assert people.resolve(email="nobody@example.com", create=False) is None
    with pytest.raises(KarniValueError) as caught:
        people.resolve(name="Only A Name")
    assert caught.value.code == "E253"


def test_an_unverified_account_is_never_linked() -> None:
    user = make_user("lucas@example.com", verified=False)
    person = people.resolve(user=user, source="booking")
    assert person.email == "lucas@example.com" and person.user_id is None


def test_a_guest_becomes_the_account_once_its_email_is_verified(
    published: list[dict[str, Any]],
) -> None:
    guest = people.resolve(email="maya@example.com", name="Maya Okafor", source="shop")
    user = make_user("maya@example.com", verified=False)
    guest.refresh_from_db()
    assert guest.user_id is None
    prove_address(user)  # a sign-in code or a provider that verified the address
    guest.refresh_from_db()
    assert guest.user_id == user.pk
    assert people.resolve(user=user).pk == guest.pk
    linked = [p for p in published if p["name"] == "people.person.linked"]
    assert linked and linked[0]["user"] == str(user.pk)


def test_verifying_links_an_existing_person_only() -> None:
    user = make_user("nikhil@example.com")
    assert not Person.objects.filter(user=user).exists()  # nobody to link: no person made
    person = people.resolve(user=user)
    assert person.user_id == user.pk and person.source == ""


def test_a_save_that_does_not_touch_the_email_costs_nothing() -> None:
    user = make_user("olga@example.com")
    with CaptureQueriesContext(connection) as queries:
        user.save(update_fields=["last_login"])
    assert len(queries) == 1


def test_the_link_can_be_left_to_the_parts() -> None:
    people.resolve(email="pablo@example.com")
    with override_settings(KARNI_PEOPLE_LINK_ON_VERIFY=False):
        user = make_user("pablo@example.com")
    assert Person.objects.get(email="pablo@example.com").user_id is None
    assert people.link_account(user).user_id == user.pk


def test_link_refusals() -> None:
    unverified = make_user("quinn@example.com", verified=False)
    with pytest.raises(KarniValueError) as caught:
        people.link_account(unverified)
    assert caught.value.code == "E258"
    assert people.link_account(unverified, strict=False) is None
    user = make_user("rosa@example.com")
    other = Person.objects.create(email="someone@example.com")
    with pytest.raises(KarniValueError) as caught:
        people.link_account(user, person=other)
    assert caught.value.code == "E258"


def test_a_signed_in_user_with_another_email_keeps_their_own_person() -> None:
    user = make_user("samir@example.com")
    own = people.resolve(user=user)
    assert people.resolve(user=user, email="gift@example.com").pk == own.pk


class TaggingResolver(Resolver):
    """A project's resolver: every new person is marked."""

    def create(self, **kwargs: Any) -> Any:
        kwargs["source"] = f"tagged-{kwargs['source']}"
        return super().create(**kwargs)


def test_the_resolver_is_swappable() -> None:
    with override_settings(KARNI_PEOPLE_RESOLVER="tests.people.test_resolve.TaggingResolver"):
        assert people.resolve(email="tara@example.com", source="crm").source == "tagged-crm"
    with override_settings(KARNI_PEOPLE_RESOLVER="builtins.object"):
        with pytest.raises(Exception) as caught:
            people.resolve(email="umar@example.com")
    assert "E253" in str(caught.value)


def test_an_event_takes_its_declared_fields_only() -> None:
    person = Person.objects.create(email="vera@example.com")
    with pytest.raises(KarniValueError) as caught:
        events.publish("people.person.erased", subject=person, reason="asked")
    assert caught.value.code == "E259"
    with pytest.raises(KarniValueError):
        events.signal_for("people.person.renamed")
    assert events.signal_for("people.person.merged") is events.person_merged


def test_a_receiver_written_against_a_signal_gets_ids_only() -> None:
    seen: list[dict[str, Any]] = []

    @receiver(events.organisation_created, dispatch_uid="test-org-created")
    def follow(sender: Any, payload: dict[str, Any], subject: Any, **kwargs: Any) -> None:
        seen.append(payload)

    try:
        from karni.people.models import Organisation

        org = Organisation.objects.create(name="Saltmarsh Cycles", source="crm")
    finally:
        events.organisation_created.disconnect(dispatch_uid="test-org-created")
    assert seen[0]["subject"]["id"] == str(org.pk) and seen[0]["source"] == "crm"
    assert seen[0]["person"] is None


def test_the_events_hand_over_to_a_family_bus_unchanged() -> None:
    declared: list[tuple[str, dict[str, Any]]] = []
    events.declare_all(lambda name, **options: declared.append((name, options)))
    by_name = dict(declared)
    assert list(by_name) == list(events.EVENTS)
    assert by_name["people.person.merged"]["person"] == "kept"
    assert by_name["people.person.created"] == {
        "version": 1,
        "fields": {"source": "the app label of the part that created it"},
        "person": "person",
        "describe": "A part created a person.",
    }
    assert by_name["people.organisation.merged"]["person"] is None
    person = Person.objects.create(email="wren@example.com")
    payload = events.publish("people.person.erased", subject=person, person=person)
    assert payload["request_id"] is None and payload["actor"] is None
