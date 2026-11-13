"""The buyer is a person (karni.people): resolved at checkout, backfilled, with commerce's facts."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.apps import apps
from django.db import connection
from karni import people
from karni.people.models import Person
from karni.testing import user_with_roles

from karni_commerce.checks import people_installed
from karni_commerce.models import Order
from tests.conftest import cart_with, pay, place
from tests.testapp.models import Gadget

MakeGadget = Callable[..., Gadget]


def test_checkout_names_the_person_of_the_email(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(stock=9)
    first = place(cart_with(("gadget", lamp, 1)), email="Mira@Example.com")
    second = place(cart_with(("gadget", lamp, 1)), email="mira@example.com")
    assert first.person is not None
    assert first.person_id == second.person_id
    person = Person.objects.get(pk=first.person_id)
    assert (person.email, person.source) == ("mira@example.com", "karni_commerce")


def test_the_person_gets_the_name_and_phone_checkout_knew(make_gadget: MakeGadget) -> None:
    from karni_commerce import services

    lamp = make_gadget(stock=9)
    billing = {
        "name": "Ines Moreau",
        "line1": "4 Rue des Lilas",
        "city": "Lyon",
        "postcode": "69001",
        "country": "FR",
        "phone": "+33 4 00 00 00 00",
    }
    order = services.checkout(
        cart_with(("gadget", lamp, 1)),
        email="ines@example.com",
        name="Ines Moreau",
        billing=billing,
        shipping=billing,
    )
    person = Person.objects.get(pk=order.person_id)
    assert (person.given_name, person.family_name) == ("Ines", "Moreau")
    assert person.phone == "+33 4 00 00 00 00"


def test_a_signed_in_buyer_is_the_person_of_their_account(make_gadget: MakeGadget) -> None:
    account = user_with_roles("customer", email="noor@example.com", email_verified=True)
    lamp = make_gadget(stock=9)
    order = place(cart_with(("gadget", lamp, 1)), email=account.email, user=account)
    person = Person.objects.get(pk=order.person_id)
    assert person.user_id == account.pk
    assert people.resolve(user=account).pk == person.pk


def test_commerce_gives_the_person_facts(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(price=Decimal("10.00"), stock=20)
    paid = pay(place(cart_with(("gadget", lamp, 2)), email="ana@example.com"))
    later = place(cart_with(("gadget", lamp, 1)), email="ana@example.com")
    place(cart_with(("gadget", lamp, 1)), email="sol@example.com")
    assert set(people.facts()) >= {"orders", "total_spent", "last_order", "first_order"}
    ana = Person.objects.with_facts().get(email="ana@example.com")
    assert (ana.orders, ana.total_spent) == (2, Decimal("20.00"))
    assert ana.last_order == later.created_at
    assert ana.first_order == paid.created_at
    rich = Person.objects.with_facts("total_spent").filter(total_spent__gte=15)
    assert [row.email for row in rich] == ["ana@example.com"]


def test_a_merge_moves_the_orders_to_the_person_kept(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(stock=9)
    keep = place(cart_with(("gadget", lamp, 1)), email="lea@example.com").person
    drop_order = place(cart_with(("gadget", lamp, 1)), email="lea+shop@example.com")
    people.merge(keep, drop_order.person)
    drop_order.refresh_from_db()
    assert drop_order.person_id == keep.pk
    assert Person.objects.with_facts("orders").get(pk=keep.pk).orders == 2


def test_erasing_a_person_blanks_their_orders_but_keeps_the_money(
    make_gadget: MakeGadget,
) -> None:
    lamp = make_gadget(price=Decimal("10.00"), stock=9)
    order = pay(place(cart_with(("gadget", lamp, 1)), email="zoe@example.com"))
    people.erase(order.person)
    order.refresh_from_db()
    assert (order.buyer_name, order.email, order.billing, order.shipping) == ("", "", {}, {})
    assert (order.total, order.amount_paid) == (Decimal("10.00"), Decimal("10.00"))


def test_the_backfill_gives_old_orders_their_person(make_gadget: MakeGadget) -> None:
    lamp = make_gadget(stock=20)
    account = user_with_roles("customer", email="kai@example.com", email_verified=True)
    known = Person.objects.create(email="eve@example.com", given_name="Eve")
    one = place(cart_with(("gadget", lamp, 1)), email="KAI@example.com", user=account)
    two = place(cart_with(("gadget", lamp, 1)), email="kai@example.com")
    three = place(cart_with(("gadget", lamp, 1)), email="eve@example.com")
    Order.objects.filter(pk__in=[one.pk, two.pk, three.pk]).update(person=None)
    Person.objects.get(email="kai@example.com").delete()  # the account is free again
    Order.objects.filter(pk=one.pk).update(buyer_name="Kai Lund")
    migration = importlib.import_module("karni_commerce.migrations.0006_order_person")
    migration.backfill(apps, SimpleNamespace(connection=connection))
    rows = {row.pk: row for row in Order.objects.filter(pk__in=[one.pk, two.pk, three.pk])}
    assert rows[one.pk].person_id == rows[two.pk].person_id
    kai = Person.objects.get(pk=rows[one.pk].person_id)
    assert (kai.email, kai.display_name, kai.user_id) == ("kai@example.com", "Kai Lund", account.pk)
    assert rows[three.pk].person_id == known.pk
    migration.backfill(apps, SimpleNamespace(connection=connection))  # twice: nothing new
    assert Person.objects.filter(email="kai@example.com").count() == 1


def test_commerce_says_when_the_people_contract_is_missing() -> None:
    assert people_installed() == []
    with mock.patch("karni_commerce.checks.apps.is_installed", return_value=False):
        found = people_installed()
    assert [message.id for message in found] == ["karni.COM001"]
