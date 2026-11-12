"""The rules the people tables keep: email identity, names, owners, defaults, settings wiring."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from karni.conf import PEOPLE_APP, karni_settings
from karni.people.models import ERASED, UNNAMED, Address, Membership, Organisation, Person
from tests.people.conftest import make_user

pytestmark = pytest.mark.django_db


def _codes(error: ValidationError) -> str:
    return str(error.message_dict)


def test_an_email_is_kept_lower_case_and_one_live_person_has_it() -> None:
    person = Person.objects.create(given_name="Ben", email="  Ben.Brooks@Example.COM ")
    assert person.email == "ben.brooks@example.com"
    with pytest.raises(ValidationError) as caught:
        Person(email="BEN.BROOKS@example.com").clean()
    assert "E254" in _codes(caught.value)
    with pytest.raises(IntegrityError), transaction.atomic():
        Person.objects.create(email="ben.brooks@example.com")
    person.delete()
    Person.objects.create(email="ben.brooks@example.com")  # a deleted row holds no email


def test_many_people_may_have_no_email() -> None:
    Person.objects.create(given_name="Guest one")
    Person.objects.create(given_name="Guest two")
    assert Person.objects.filter(email="").count() == 2


def test_the_display_name_follows_the_names_until_it_is_written_by_hand() -> None:
    person = Person.objects.create(given_name="Chloe", family_name="Chen")
    assert person.display_name == "Chloe Chen" and str(person) == "Chloe Chen"
    person.family_name = "Chen-Novak"
    person.save()
    assert Person.objects.get(pk=person.pk).display_name == "Chloe Chen-Novak"
    person.display_name = "Dr Chen"
    person.save()
    loaded = Person.objects.get(pk=person.pk)
    loaded.given_name = "Chloe A."
    loaded.save()
    assert Person.objects.get(pk=person.pk).display_name == "Dr Chen"
    assert Person.objects.create(email="dev@example.org").display_name == "dev"
    assert Person.objects.create().display_name == UNNAMED


def test_a_linked_person_keeps_the_accounts_email() -> None:
    user = make_user("elena@example.com")
    person = Person.objects.get(user=user) if Person.objects.filter(user=user).exists() else None
    assert person is None  # nothing to link to: no person had the email
    person = Person.objects.create(email="elena@example.com", user=user)
    person.email = "someone.else@example.com"
    with pytest.raises(ValidationError) as caught:
        person.clean()
    assert "E255" in _codes(caught.value)
    person.email = "elena@example.com"
    person.phone = "+44 20 7946 0002"
    person.clean()


@pytest.mark.parametrize(
    ("field", "value"),
    [("time_zone", "Mars/Olympus"), ("language", "english please")],
)
def test_time_zone_and_language_are_checked(field: str, value: str) -> None:
    person = Person(email="farid@example.com", **{field: value})
    with pytest.raises(ValidationError) as caught:
        person.clean()
    assert "E256" in _codes(caught.value) and field in caught.value.message_dict
    Person(email="farid@example.com", time_zone="Asia/Tokyo", language="pt-BR").clean()


def test_deleting_a_person_frees_the_account() -> None:
    user = make_user("grace@example.com")
    person = Person.objects.create(email="grace@example.com", user=user)
    person.delete()
    assert Person._base_manager.get(pk=person.pk).user_id is None
    Person.objects.create(email="grace@example.com", user=user)


def test_an_address_has_exactly_one_owner() -> None:
    person = Person.objects.create(email="hiro@example.com")
    org = Organisation.objects.create(name="Quarry Hill Labs")
    for owners in ({}, {"person": person, "organisation": org}):
        with pytest.raises(ValidationError) as caught:
            Address(line1="1 Station Road", **owners).clean()
        assert "E256" in _codes(caught.value)
        with pytest.raises(IntegrityError), transaction.atomic():
            Address.objects.create(line1="1 Station Road", **owners)


def test_an_owner_has_one_default_address_of_each_kind() -> None:
    person = Person.objects.create(email="ines@example.com")
    home = Address.objects.create(
        person=person, line1="2 Mill Lane", is_default_billing=True, is_default_shipping=True
    )
    work = Address.objects.create(person=person, line1="3 River Walk", is_default_shipping=True)
    home.refresh_from_db()
    assert home.is_default_billing and not home.is_default_shipping
    assert work.is_default_shipping
    with pytest.raises(IntegrityError), transaction.atomic():
        Address.objects.filter(pk=home.pk).update(is_default_shipping=True)


def test_a_person_is_a_member_of_an_organisation_once() -> None:
    person = Person.objects.create(email="jonas@example.com")
    org = Organisation.objects.create(name="Cobalt Harbor Supply")
    Membership.objects.create(person=person, organisation=org, title="Buyer")
    with pytest.raises(ValidationError) as caught:
        Membership(person=person, organisation=org).clean()
    assert "E256" in _codes(caught.value)


def test_an_organisations_domain_is_kept_bare() -> None:
    org = Organisation.objects.create(name="Lumen Grove School", domain="HTTPS://www.Lumen.Example/x")
    assert org.domain == "lumen.example"


def test_people_switch_installs_the_app_before_the_admin() -> None:
    namespace: dict[str, object] = {"SECRET_KEY": "x" * 50, "KARNI_PEOPLE": True}
    karni_settings(namespace, env_name="dev")
    apps = list(namespace["INSTALLED_APPS"])  # type: ignore[call-overload]
    assert apps.index(PEOPLE_APP) == apps.index("karni.admin") - 1
    plain: dict[str, object] = {"SECRET_KEY": "x" * 50}
    karni_settings(plain, env_name="dev")
    assert PEOPLE_APP not in plain["INSTALLED_APPS"]  # type: ignore[operator]


def test_the_migrations_match_the_models() -> None:
    from django.apps import apps
    from django.db.migrations.autodetector import MigrationAutodetector
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.state import ProjectState

    loader = MigrationLoader(None, ignore_no_migrations=True)
    detector = MigrationAutodetector(loader.project_state(), ProjectState.from_apps(apps))
    assert "people" not in detector.changes(graph=loader.graph, trim_to_apps={"people"})


def test_the_erased_name_constant_is_what_screens_show() -> None:
    assert ERASED == "Erased person"
