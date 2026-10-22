"""karni.E214: a role's scope must resolve on every model its grant covers."""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import Q

from karni.accounts.roles import _custom_scopes, register_scope
from karni.checks import check_role_scope_paths

pytestmark = pytest.mark.django_db

STAFF = {"name": "Staff", "system": True, "grants": {"*": "all"}}


@pytest.fixture
def by_city() -> Any:
    register_scope("by_city", lambda user, model: Q(venue__city="Berlin"))
    yield
    _custom_scopes.pop("by_city", None)


def test_a_custom_scope_written_for_one_model_fails_on_another(
    settings: Any, by_city: None
) -> None:
    # The trap the social-leads rebuild hit: a scope that follows `venue` is
    # granted by pattern on a model that has no `venue` (Venue itself).
    settings.KARNI_ROLES = {
        "staff": STAFF,
        "local": {
            "grants": {
                "testapp.event:view": "custom:by_city",
                "testapp.venue:view": "custom:by_city",
            }
        },
    }
    messages = check_role_scope_paths()
    assert [message.id for message in messages] == ["karni.E214"]
    assert "testapp.venue:view" in messages[0].msg and "by_city" in messages[0].msg


def test_scopes_that_resolve_pass(settings: Any, by_city: None) -> None:
    settings.KARNI_ROLES = {
        "staff": STAFF,
        "organizer": {"grants": {"testapp.event:*": "own", "testapp.venue:view": "all"}},
        "local": {"grants": {"testapp.event:view": "custom:by_city"}},
        "venue_manager": {"grants": {"testapp.event:view": "related:venue"}},
    }
    assert check_role_scope_paths() == []


def test_an_owner_path_through_a_many_to_many_resolves(settings: Any) -> None:
    # `own` with an owner path is the membership pattern (owner_field =
    # "workspace__members"); Book reaches its readers through labels here.
    register_scope("labelled", lambda user, model: Q(labels__isnull=False))
    try:
        settings.KARNI_ROLES = {
            "staff": STAFF,
            "reader": {"grants": {"testapp.book:view": "custom:labelled"}},
        }
        assert check_role_scope_paths() == []
    finally:
        _custom_scopes.pop("labelled", None)
