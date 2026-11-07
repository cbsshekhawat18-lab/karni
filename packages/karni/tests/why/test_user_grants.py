"""``karni why`` and ``karni why-empty`` with per-user grants (experimental).

They say whether a role grant or a user grant decided, and name the user
grant: its id, its reason and its expiry. ``world`` is tests/why's: alice and
bob organise events at the Arena and the Hall, nobody holds no role.
"""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.utils import timezone

from karni.accounts import grants

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"


@pytest.fixture(autouse=True)
def _user_grants(settings: Any) -> None:
    settings.KARNI_USER_GRANTS = True


def _run(*args: str) -> str:
    out = StringIO()
    call_command("karni_why", *args, stdout=out)
    return out.getvalue()


def test_a_user_grant_that_decides_is_named(world: Any) -> None:
    arena, _hall = world.venues
    later = timezone.now() + timedelta(days=30)
    row = grants.grant(
        None,
        world.users["nobody"],
        VIEW,
        "related:venue",
        targets=[arena.pk],
        expires_at=later,
        reason="pilot",
    )
    target = world.rows["bob-draft"]  # at the Arena
    text = _run(f"granted-events/{target.pk}", "--as", "nobody@example.com")
    assert "roles    none + 1 user grant" in text
    assert f"holds testapp.event:view through user grant {row.pk}" in text
    assert (
        f"{VIEW}  scope related:venue on {arena.pk}  (user grant {row.pk}, reason 'pilot', "
        f"expires {later:%Y-%m-%d %H:%M})  → venue in"
    ) in text
    assert "← reaches this row" in text
    assert "result   200 OK" in text

    data = json.loads(_run(f"granted-events/{target.pk}", "--as", "nobody@example.com", "--json"))
    entry = data["grants"][0]["grants"][0]
    assert entry["origin"] == "user_grant" and entry["grant"] == str(row.pk)
    assert entry["reason"] == "pilot" and entry["expires_at"] == later.isoformat()
    assert entry["targets"] == [str(arena.pk)] and entry["reaches_row"] is True
    assert data["user_grants"] == 1


def test_the_role_or_the_user_grant_that_reaches_the_row(world: Any) -> None:
    _arena, hall = world.venues
    row = grants.grant(None, world.users["alice"], VIEW, "related:venue", targets=[hall.pk])
    theirs = world.rows["bob-published"]  # bob's, at the Hall
    data = json.loads(_run(f"granted-events/{theirs.pk}", "--as", "alice@example.com", "--json"))
    entries = data["grants"][0]["grants"]
    by_origin = {entry["origin"]: entry for entry in entries}
    assert by_origin["declared"]["reaches_row"] is False
    assert by_origin["user_grant"]["reaches_row"] is True
    assert by_origin["user_grant"]["grant"] == str(row.pk)
    mine = world.rows["alice-draft"]  # alice's, at the Arena: her role decides
    data = json.loads(_run(f"granted-events/{mine.pk}", "--as", "alice@example.com", "--json"))
    by_origin = {entry["origin"]: entry for entry in data["grants"][0]["grants"]}
    assert by_origin["declared"]["reaches_row"] is True
    assert by_origin["user_grant"]["reaches_row"] is False


def test_a_row_outside_the_targets_names_the_grant_to_widen(world: Any) -> None:
    _arena, hall = world.venues
    row = grants.grant(None, world.users["nobody"], VIEW, "related:venue", targets=[hall.pk])
    target = world.rows["bob-draft"]  # at the Arena
    text = _run(f"granted-events/{target.pk}", "--as", "nobody@example.com")
    assert "404 Not Found" in text
    assert f"to the targets of user grant {row.pk}" in text


def test_no_grant_at_all_offers_a_user_grant(world: Any) -> None:
    target = world.rows["bob-draft"]
    text = _run(f"granted-events/{target.pk}", "--as", "nobody@example.com")
    assert "no role or user grant you hold grants testapp.event:view" in text
    assert "or: give nobody@example.com a user grant of 'testapp.event:view'" in text


def test_expired_and_switched_off_grants_do_not_count(world: Any, settings: Any) -> None:
    arena, _hall = world.venues
    grants.grant(
        None,
        world.users["nobody"],
        VIEW,
        "related:venue",
        targets=[arena.pk],
        expires_at=timezone.now() - timedelta(minutes=5),
    )
    target = world.rows["bob-draft"]
    text = _run(f"granted-events/{target.pk}", "--as", "nobody@example.com")
    assert "user grant" not in text.splitlines()[1] and "403" in text
    grants.grant(None, world.users["nobody"], VIEW, "related:venue", targets=[arena.pk])
    settings.KARNI_USER_GRANTS = False
    text = _run(f"granted-events/{target.pk}", "--as", "nobody@example.com")
    assert "no role you hold grants testapp.event:view" in text and "403" in text


def test_why_empty_names_the_user_grant(world: Any) -> None:
    _arena, hall = world.venues
    row = grants.grant(
        None, world.users["nobody"], VIEW, "related:venue", targets=[hall.pk], reason="hall only"
    )
    data = json.loads(_run("granted-events", "--empty", "--as", "nobody@example.com", "--json"))
    assert data["outcome"] == "not-empty" and data["count"] == 2  # the two Hall events
    entry = data["grants"][0]["grants"][0]
    assert (entry["origin"], entry["grant"], entry["reason"]) == (
        "user_grant",
        str(row.pk),
        "hall only",
    )
    assert entry["expires_at"] is None and "reaches_row" not in entry
    text = _run("granted-events", "--empty", "--as", "nobody@example.com")
    assert f"(user grant {row.pk}, reason 'hall only', no expiry)" in text
