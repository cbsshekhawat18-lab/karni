"""``Karni.explicit_actions``: actions a wildcard grant never reaches.

``Event`` (tests.testapp) declares the extra action ``approve``. Marked
explicit, ``"*"`` and ``"testapp.event:*"`` stop reaching it in a role and
in a user grant, while a grant that writes the action out still does.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from karni.accounts import grants
from karni.accounts.permissions import assign_role
from karni.accounts.roles import (
    RoleSpec,
    expand_grants,
    pattern_matches,
    permission_keys,
    sync_roles,
    user_can,
)
from karni.checks import check_explicit_actions
from karni.exceptions import KarniImproperlyConfigured
from karni.meta import explicit_actions
from tests.testapp.models import Event

APPROVE = "testapp.event:approve"


@pytest.fixture
def explicit_approve(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Event.Karni, "explicit_actions", ["approve"], raising=False)
    yield


def _spec(grants_: dict[str, str]) -> RoleSpec:
    return RoleSpec(slug="r", name="R", description="", system=False, grants=grants_)


def _expanded(grants_: dict[str, str]) -> dict[str, str]:
    expanded = expand_grants(_spec(grants_), permission_keys())
    return {g.permission: ":".join(filter(None, (g.scope, g.scope_path))) for g in expanded}


@pytest.mark.parametrize(
    ("pattern", "reaches"),
    [
        ("*", False),
        ("*:*", False),
        ("testapp.*:*", False),
        ("testapp.event:*", False),
        ("testapp.event:appr*", False),
        ("testapp.event:appr?ve", False),
        ("testapp.event:approve", True),
        ("testapp.*:approve", True),
        ("*:approve", True),
    ],
)
def test_only_a_pattern_that_writes_the_action_out_reaches_it(
    explicit_approve: None, pattern: str, reaches: bool
) -> None:
    assert pattern_matches(pattern, APPROVE, Event) is reaches
    # The standard actions are not explicit: every wildcard still reaches them.
    glob = "*:*" if pattern == "*" else pattern
    view = fnmatch.fnmatchcase("testapp.event:view", glob)
    assert pattern_matches(pattern, "testapp.event:view", Event) is view


def test_without_the_option_a_wildcard_reaches_every_action() -> None:
    assert explicit_actions(Event) == frozenset()
    assert pattern_matches("*", APPROVE, Event)
    assert _expanded({"*": "all"})[APPROVE] == "all"


def test_a_wildcard_role_skips_it_and_a_named_grant_keeps_it(explicit_approve: None) -> None:
    assert APPROVE not in _expanded({"*": "all"})
    assert APPROVE not in _expanded({"testapp.event:*": "own"})
    assert "testapp.event:view" in _expanded({"testapp.event:*": "own"})
    # A later wildcard does not overwrite the named grant.
    assert _expanded({APPROVE: "related:venue", "*": "all"})[APPROVE] == "related:venue"


def test_a_pattern_that_reaches_only_explicit_actions_is_e206(explicit_approve: None) -> None:
    with pytest.raises(KarniImproperlyConfigured, match="explicit_actions") as caught:
        _expanded({"testapp.event:appr*": "all"})
    assert caught.value.code == "E206"


@pytest.mark.django_db
def test_sync_and_user_can_follow_the_option(explicit_approve: None) -> None:
    roles = {
        "staff": {"system": True, "grants": {"*": "all"}},
        "checker": {"grants": {APPROVE: "all"}},
    }
    with override_settings(KARNI_ROLES=roles):
        sync_roles()
        model = get_user_model()
        staff = model.objects.create_user(email="staff@example.com", password="s3cret-pass-123")
        checker = model.objects.create_user(email="check@example.com", password="s3cret-pass-123")
        assign_role(staff, "staff")
        assign_role(checker, "checker")
        assert user_can(staff, "testapp.event:view") and not user_can(staff, APPROVE)
        assert user_can(checker, APPROVE)


@pytest.mark.django_db
def test_a_wildcard_user_grant_skips_it(explicit_approve: None, settings: Any) -> None:
    settings.KARNI_USER_GRANTS = True
    model = get_user_model()
    guest = model.objects.create_user(email="guest@example.com", password="s3cret-pass-123")
    grants.grant(None, guest, "testapp.event:*", "all")
    guest = model.objects.get(pk=guest.pk)
    assert user_can(guest, "testapp.event:view") and not user_can(guest, APPROVE)
    grants.grant(None, guest, APPROVE, "all")
    guest = model.objects.get(pk=guest.pk)
    assert user_can(guest, APPROVE)


def test_karni_check_refuses_a_name_that_is_not_an_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.apps import apps

    config = [apps.get_app_config("testapp")]
    assert check_explicit_actions(config) == []
    monkeypatch.setattr(Event.Karni, "explicit_actions", ["aprove"], raising=False)
    found = check_explicit_actions(config)
    assert [message.id for message in found] == ["karni.E290"]
    assert "'aprove'" in found[0].msg and "approve" in found[0].msg
    # A single string is one action, never its letters (fail closed).
    monkeypatch.setattr(Event.Karni, "explicit_actions", "approve", raising=False)
    assert explicit_actions(Event) == frozenset({"approve"})
    assert check_explicit_actions(config) == []
