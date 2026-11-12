"""The people admin (merge with a preview, erase with a confirmation) and the shared seed pool."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.test import Client

from karni import people
from karni.people.models import Address, Membership, Organisation, Person
from karni.seeding import DEMO_LOGIN, seed
from tests.helpdeskapp.models import Ticket

pytestmark = pytest.mark.django_db

CHANGELIST = "/admin/people/person/"


@pytest.fixture
def superuser_client() -> Client:
    user = get_user_model().objects.create_superuser(
        email="root@example.net", password="karni-password"
    )
    client = Client()
    client.force_login(user)
    return client


def test_the_changelist_and_the_change_form_open(
    superuser_client: Client, family: dict[str, Any]
) -> None:
    listed = superuser_client.get(CHANGELIST)
    assert listed.status_code == 200 and b"ana+club@example.com" in listed.content
    form = superuser_client.get(f"{CHANGELIST}{family['keep'].pk}/change/")
    assert form.status_code == 200 and b"1 Mill Lane" in form.content  # the address inline
    assert superuser_client.get("/admin/people/organisation/").status_code == 200


def test_the_merge_action_previews_then_merges(
    superuser_client: Client, family: dict[str, Any]
) -> None:
    keep, drop = family["keep"], family["drop"]
    selected = [str(keep.pk), str(drop.pk)]
    preview = superuser_client.post(
        CHANGELIST, {"action": "merge_selected", ACTION_CHECKBOX_NAME: selected}
    )
    assert preview.status_code == 200 and b"karni-people-merge" in preview.content
    assert b"helpdeskapp.Ticket" in preview.content
    assert Ticket.objects.filter(person=drop).count() == 2  # a preview changes nothing
    done = superuser_client.post(
        CHANGELIST,
        {
            "action": "merge_selected",
            ACTION_CHECKBOX_NAME: selected,
            "keep": str(keep.pk),
            "confirm": "yes",
        },
    )
    assert done.status_code == 302
    assert Ticket.objects.filter(person=keep).count() == 3
    assert Person._base_manager.get(pk=drop.pk).merged_into_id == keep.pk


def test_the_merge_action_takes_exactly_two(
    superuser_client: Client, family: dict[str, Any]
) -> None:
    response = superuser_client.post(
        CHANGELIST, {"action": "merge_selected", ACTION_CHECKBOX_NAME: [str(family["keep"].pk)]}
    )
    assert response.status_code == 302
    assert not Person._base_manager.filter(merged_into__isnull=False).exists()


def test_the_erase_action_asks_first(superuser_client: Client, family: dict[str, Any]) -> None:
    selected = [str(family["drop"].pk)]
    ask = superuser_client.post(
        CHANGELIST, {"action": "erase_selected", ACTION_CHECKBOX_NAME: selected}
    )
    assert ask.status_code == 200 and b"karni-people-erase" in ask.content
    assert Person.objects.filter(pk=family["drop"].pk).exists()
    superuser_client.post(
        CHANGELIST,
        {"action": "erase_selected", ACTION_CHECKBOX_NAME: selected, "confirm": "yes"},
    )
    assert Person._base_manager.get(pk=family["drop"].pk).erased_at is not None


NOW = dt.datetime(2026, 11, 2, tzinfo=dt.UTC)


def _snapshot() -> list[tuple[str, str, str, bool]]:
    return [
        (p.display_name, p.email, p.phone, p.user_id is not None)
        for p in Person.objects.order_by("email")
    ]


def test_the_seed_pool_is_realistic_connected_and_deterministic() -> None:
    plan = [get_user_model(), Organisation, Person]
    report = seed(models=plan, count=12, seed=7, now=NOW)
    assert report.rows["people.Person"] == 12
    assert report.rows["people.Organisation"] == 3  # one for every four people
    pool = people.pool()
    assert len(pool) == 12 and pool == sorted(pool, key=lambda p: (p.email, str(p.pk)))
    with_account = people.pool(with_account=True)
    assert len(with_account) == 4  # a third of them
    assert Person.objects.get(user__email=DEMO_LOGIN).email == DEMO_LOGIN
    assert all(p.email.split("@")[1].endswith((".com", ".org", ".net", ".example")) for p in pool)
    members = Membership.objects.select_related("person", "organisation")
    assert members.exists()
    assert all(m.person.email.endswith("@" + m.organisation.domain) for m in members)
    assert all(m.person.organisation_id == m.organisation_id for m in members)
    assert Address.objects.filter(is_default_shipping=True).count() == 6
    assert all(p.time_zone and p.language and p.display_name for p in pool)
    first = _snapshot()
    Person._base_manager.all().delete()
    Organisation._base_manager.all().delete()
    seed(models=plan, count=12, seed=7, now=NOW)
    assert [row[:3] for row in _snapshot()] == [row[:3] for row in first]


def test_the_seed_plan_includes_the_pool_and_orders_it_first() -> None:
    from karni.seeding import seed_plan

    labels = [model._meta.label for model in seed_plan()]
    assert labels.index("people.Organisation") < labels.index("people.Person")
    assert labels.index("karni_accounts.User") < labels.index("people.Person")
