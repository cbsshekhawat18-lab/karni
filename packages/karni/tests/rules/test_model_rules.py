"""karni.rules at the model: every option refuses on save with its code, and lets the rest by."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import Error
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from karni import rules
from karni.conflicts import translate
from karni.middleware import current_user
from karni.rules import DeleteRefused, RuleViolation, UniqueRule
from tests.rulesapp.models import Course, Item, Lesson, Purchase, Review, Shop

pytestmark = pytest.mark.django_db


def _user(email: str) -> Any:
    return get_user_model().objects.create_user(email=email, password="x-Password-1")


@pytest.fixture
def seller() -> Any:
    return _user("seller@example.com")


@pytest.fixture
def buyer() -> Any:
    return _user("buyer@example.com")


@pytest.fixture
def item(seller: Any) -> Item:
    shop = Shop.objects.create(owner=seller, name="Corner")
    return Item.objects.create(shop=shop, title="Lamp", price=Decimal("20.00"))


def _refused(code: str, field: str | None = None) -> Any:
    class Check:
        def __enter__(self) -> None:
            return None

        def __exit__(self, kind: Any, exc: Any, tb: Any) -> bool:
            assert isinstance(exc, RuleViolation), f"expected {code}, got {exc!r}"
            assert exc.code == code, exc
            if field is not None:
                assert exc.field == field, exc
            return True

    return Check()


# bounds


def test_a_number_below_its_minimum_is_refused_with_e990(item: Item) -> None:
    with _refused("E990", "price"):
        Item.objects.create(shop=item.shop, title="Free", price=Decimal("0"))
    item.stock = 1001
    with _refused("E990", "stock"):
        item.save()


def test_a_value_stored_before_the_rule_is_not_checked_until_it_changes(item: Item) -> None:
    Item.objects.filter(pk=item.pk).update(stock=-5)  # bypasses save(), as documented
    item.refresh_from_db()
    item.title = "Desk lamp"
    item.save()  # stock unchanged: no refusal
    item.stock = -4
    with _refused("E990", "stock"):
        item.save()


def test_a_date_bound_reads_today(item: Item, buyer: Any) -> None:
    yesterday = timezone.localdate() - dt.timedelta(days=1)
    with _refused("E990", "wanted_by"):
        Purchase.objects.create(item=item, buyer=buyer, wanted_by=yesterday)
    Purchase.objects.create(item=item, buyer=buyer, wanted_by=timezone.localdate())


def test_clean_turns_a_refusal_into_a_form_error(item: Item) -> None:
    bad = Item(shop=item.shop, title="Free", price=Decimal("0"))
    with pytest.raises(ValidationError) as caught:
        bad.full_clean()
    assert caught.value.message_dict["price"][0].startswith("E990: ")


# unique


def test_unique_among_live_rows_matching_the_filter(item: Item, buyer: Any) -> None:
    first = Purchase.objects.create(item=item, buyer=buyer)
    with _refused("E991", "item"):
        Purchase.objects.create(item=item, buyer=buyer)
    first.transition("status", "cancelled")
    Purchase.objects.create(item=item, buyer=buyer)  # a cancelled one does not count


def test_unique_is_a_partial_index_the_database_enforces(item: Item, buyer: Any) -> None:
    constraint = next(c for c in Purchase._meta.constraints if isinstance(c, UniqueRule))
    assert constraint.fields == ("item", "buyer") or list(constraint.fields) == ["item", "buyer"]
    Purchase.objects.create(item=item, buyer=buyer)
    with rules.unchecked(reason="test: let the database refuse it"):
        with pytest.raises(IntegrityError) as caught, transaction.atomic():
            Purchase.objects.create(item=item, buyer=buyer)
    error = translate(caught.value, model=Purchase)
    assert error is not None and error.code == "E991"


def test_a_soft_deleted_row_frees_its_values(seller: Any) -> None:
    shop = Shop.objects.create(owner=seller, name="One")
    with _refused("E991", "owner"):
        Shop.objects.create(owner=seller, name="Two")
    shop.delete()
    Shop.objects.create(owner=seller, name="Two")


# targets


def test_a_relation_to_a_row_its_filter_refuses_is_e993(item: Item, buyer: Any) -> None:
    item.active = False
    item.save()
    with _refused("E993", "item"):
        Purchase.objects.create(item=item, buyer=buyer)


def test_me_is_the_signed_in_user(item: Item, seller: Any) -> None:
    with current_user(seller), _refused("E993", "item"):
        Purchase.objects.create(item=item, buyer=seller)  # their own item


def test_a_rule_about_the_caller_needs_a_caller(item: Item, seller: Any) -> None:
    Purchase.objects.create(item=item, buyer=seller)  # no signed-in user: $me is left out


def test_two_relations_must_agree(item: Item, buyer: Any) -> None:
    other = Item.objects.create(shop=item.shop, title="Desk", price=Decimal("5.00"))
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    with _refused("E993", "item"):
        Review.objects.create(purchase=purchase, item=other)
    Review.objects.create(purchase=purchase, item=item)


# frozen


def test_a_field_set_on_create_never_changes(item: Item, buyer: Any) -> None:
    other = Item.objects.create(shop=item.shop, title="Desk", price=Decimal("5.00"))
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    purchase.item = other
    with _refused("E994", "item"):
        purchase.save()
    purchase.refresh_from_db()
    purchase.reason = "a note"
    purchase.save()  # an unchanged frozen field passes


def test_a_field_frozen_while_the_row_matches(item: Item, buyer: Any) -> None:
    purchase = Purchase.objects.create(item=item, buyer=buyer, quantity=2)
    purchase.quantity = 3
    purchase.save()  # pending: it may change
    purchase.transition("status", "paid")
    purchase.quantity = 4
    with _refused("E994", "quantity"):
        purchase.save()


# moves


def test_a_move_requires_its_fields_and_stamps(item: Item, buyer: Any) -> None:
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    purchase.transition("status", "paid")
    with _refused("E996", "reason"):
        purchase.transition("status", "refunded")
    purchase.refresh_from_db()
    assert purchase.status == "paid"
    purchase.transition("status", "refunded", reason="damaged")
    purchase.refresh_from_db()
    assert purchase.refunded_at is not None


def test_a_flag_move_needs_a_related_row_and_stamps_a_date() -> None:
    course = Course.objects.create(title="Pottery")
    course.published = True
    with _refused("E996", "published"):
        course.save()
    with _refused("E996", "published"):
        Course.objects.create(title="Empty", published=True)
    Lesson.objects.create(course=course, title="Clay")
    course.published = True
    course.save()
    course.refresh_from_db()
    assert course.published_on == timezone.localdate()


# delete


def test_children_block_a_delete(item: Item) -> None:
    with pytest.raises(DeleteRefused) as caught:
        item.shop.delete()
    assert caught.value.code == "E995" and caught.value.details["count"] == 1
    item.delete()
    item.shop.delete()


def test_a_delete_only_in_the_states_when_allows(item: Item, buyer: Any) -> None:
    purchase = Purchase.objects.create(item=item, buyer=buyer)
    purchase.transition("status", "paid")
    with pytest.raises(DeleteRefused):
        purchase.delete()
    other = Purchase.objects.create(
        item=Item.objects.create(shop=item.shop, title="Desk", price=Decimal("5.00")), buyer=buyer
    )
    other.delete()


# escape hatches and declarations


def test_unchecked_skips_the_rules_and_needs_a_reason(item: Item) -> None:
    with rules.unchecked(reason="test: historical rows"):
        Item.objects.create(shop=item.shop, title="Free", price=Decimal("0"))
    with pytest.raises(Exception) as caught, rules.unchecked(reason=" "):
        pass
    assert getattr(caught.value, "code", None) == "E998"


def test_a_declaration_that_cannot_work_is_e998(monkeypatch: pytest.MonkeyPatch) -> None:
    from karni.checks import check_rules

    monkeypatch.setattr(Item.Karni, "bounds", {"title": {"min": 1}}, raising=False)
    rules.clear_caches()
    try:
        messages = check_rules()
    finally:
        monkeypatch.undo()
        rules.clear_caches()
    found = [m for m in messages if isinstance(m, Error) and m.obj is Item]
    assert found and found[0].id == "karni.E998"
    assert "bounds apply to numbers" in found[0].msg


def test_generated_values_stay_inside_the_bounds() -> None:
    from karni.testing.values import ValueInference

    inference = ValueInference()
    field = Review._meta.get_field("stars")
    values = {inference.value(Review, field, n) for n in range(30)}
    assert values and all(1 <= value <= 5 for value in values)


def test_seeding_reads_now_as_its_anchor(item: Item, buyer: Any) -> None:
    anchor = timezone.now() - dt.timedelta(days=40)
    with rules.clock(anchor):
        Purchase.objects.create(item=item, buyer=buyer, wanted_by=anchor.date())
    purchase = Purchase.objects.get(buyer=buyer)
    purchase.transition("status", "paid")
    with rules.clock(anchor):
        purchase.transition("status", "refunded", reason="late")
    purchase.refresh_from_db()
    assert purchase.refunded_at == anchor
