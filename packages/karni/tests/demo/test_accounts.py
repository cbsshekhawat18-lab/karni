"""Every demo account is made, and put back the way it was made."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model

from karni.accounts import terms
from karni.accounts.permissions import assign_role, routed_roles, user_roles
from karni.demo import accounts, conf

from .conftest import CUSTOMER, STAFF, user


@pytest.mark.django_db
def test_ensure_makes_each_account_with_its_flags_and_roles(demo: Any) -> None:
    accounts.ensure()

    staff, customer = user(STAFF), user(CUSTOMER)
    assert staff.is_staff and staff.is_superuser and staff.check_password("karni-password")
    assert user_roles(staff) == sorted(routed_roles())
    assert not customer.is_staff and not customer.is_superuser
    assert user_roles(customer) == ["customer"]


@pytest.mark.django_db
def test_ensure_puts_a_changed_account_back(demo: Any) -> None:
    accounts.ensure()
    customer = user(CUSTOMER)
    customer.set_password("changed-somehow")
    customer.is_staff = True
    customer.is_active = False
    customer.save()
    assign_role(customer, "staff-ish")

    accounts.ensure()

    customer = user(CUSTOMER)
    assert customer.check_password("karni-password")
    assert (customer.is_staff, customer.is_active) == (False, True)
    assert user_roles(customer) == ["customer"]


@pytest.mark.django_db
def test_ensure_accepts_the_current_terms(demo: Any) -> None:
    demo.KARNI_TERMS = {"version": "2026-01", "url": "/terms/"}
    accounts.ensure()
    for login in (STAFF, CUSTOMER):
        assert terms.has_accepted(user(login).pk, "2026-01")


@pytest.mark.django_db
def test_an_unlisted_seed_account_is_closed(demo: Any) -> None:
    demo.KARNI_DEMO_ACCOUNTS = [{"login": CUSTOMER, "roles": ["customer"]}]
    seed_user = get_user_model().objects.create_user(email=conf.seed_login(), password="x-1234567")
    assert seed_user.is_active

    accounts.ensure()

    assert accounts.find(conf.seed_login()).is_active is False
    assert user(CUSTOMER).is_active


@pytest.mark.django_db
def test_an_account_with_its_own_password(demo: Any) -> None:
    demo.KARNI_DEMO_ACCOUNTS = [{"login": CUSTOMER, "password": "own-password-1"}]
    accounts.ensure()
    assert user(CUSTOMER).check_password("own-password-1")
