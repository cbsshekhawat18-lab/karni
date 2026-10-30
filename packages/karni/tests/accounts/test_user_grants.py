"""Per-user grants (experimental): ``UserGrant`` rows join the role grants while the switch is on.

The project is ``tests.testapp``: ``Event`` is owned by its ``organizer`` and
has the scope path ``venue``, so ``related:venue`` with targets reaches the
events of the venues listed. Venues take integer keys under
``KARNI_TEST_PK=bigint``, so every target here is ``str(venue.pk)``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Q
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from karni.accounts import grants
from karni.accounts import roles as roles_mod
from karni.accounts.models import UserGrant
from karni.accounts.permissions import assign_role
from karni.accounts.roles import grant_sources, grants_for, rows_for, sync_roles, user_can
from karni.conf.validation import validate_settings
from karni.exceptions import KarniValueError
from tests.testapp.models import Event, Venue

pytestmark = pytest.mark.django_db

VIEW = "testapp.event:view"
APPROVE = "testapp.event:approve"

ROLES = {
    "organizer": {"grants": {VIEW: "own", "testapp.event:add": "all"}},
    "venue_manager": {"grants": {VIEW: "related:venue", APPROVE: "related:venue"}},
    "ops": {"system": True, "grants": {"*": "all"}},
}


@pytest.fixture(autouse=True)
def _world(settings: Any) -> Any:
    settings.KARNI_USER_GRANTS = True
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _user(email: str, *roles: str, **flags: Any) -> Any:
    user = get_user_model().objects.create_user(email=email, password="s3cret-pass-123", **flags)
    for slug in roles:
        assign_role(user, slug)
    return user


def _fresh(user: Any) -> Any:
    """The same user as a new instance: what the next request sees (no cached grants)."""
    return get_user_model().objects.get(pk=user.pk)


def _event(title: str, **fields: Any) -> Event:
    return Event.objects.create(title=title, starts_at=timezone.now(), **fields)


def _visible(user: Any) -> set[str]:
    rows = rows_for(user, Event, "view")
    if rows is False:
        return set()
    queryset = Event.objects.all() if rows is True else Event.objects.filter(rows)
    return set(queryset.values_list("title", flat=True))


@pytest.fixture
def place() -> Any:
    arena = Venue.objects.create(name="Arena", city="Pune")
    hall = Venue.objects.create(name="Hall", city="Jaipur")
    dome = Venue.objects.create(name="Dome", city="Kochi")
    return arena, hall, dome


# the model and its checks


class TestCheck:
    def test_a_role_pattern_and_scope_are_accepted(self) -> None:
        checked = grants.check("testapp.event:*", "own")
        assert checked.scope == "own" and checked.targets == ()
        assert VIEW in checked.keys and APPROVE in checked.keys

    @pytest.mark.parametrize("pattern", ["", "events", "testapp.event:aprove", "nope.thing:view"])
    def test_a_pattern_that_matches_nothing_is_e360(self, pattern: str) -> None:
        with pytest.raises(KarniValueError) as caught:
            grants.check(pattern, "all")
        assert caught.value.code == "E360"

    @pytest.mark.parametrize(
        ("pattern", "scope"),
        [
            (VIEW, "everything"),
            (VIEW, "related"),
            (VIEW, "related:city"),
            ("testapp.venue:view", "related:venue"),
            (VIEW, "custom:unregistered"),
            ("auth.group:view", "own"),
        ],
    )
    def test_a_scope_that_does_not_fit_is_e361(self, pattern: str, scope: str) -> None:
        with pytest.raises(KarniValueError) as caught:
            grants.check(pattern, scope)
        assert caught.value.code == "E361"

    def test_a_wildcard_skips_models_without_the_scope(self) -> None:
        checked = grants.check("testapp.*:view", "related:venue")
        assert checked.keys == (VIEW,)

    def test_targets_are_text_ids_without_repeats(self, place: Any) -> None:
        arena, hall, _ = place
        checked = grants.check(VIEW, "related:venue", [arena.pk, str(hall.pk), arena.pk])
        assert checked.targets == (str(arena.pk), str(hall.pk))

    @pytest.mark.parametrize(
        ("scope", "targets"),
        [("all", ["1"]), ("own", ["1"]), ("related:venue", "1"), ("related:venue", [None])],
    )
    def test_bad_targets_are_e362(self, scope: str, targets: Any) -> None:
        with pytest.raises(KarniValueError) as caught:
            grants.check(VIEW, scope, targets)
        assert caught.value.code == "E362"

    def test_a_target_the_field_refuses_is_e362(self) -> None:
        with pytest.raises(KarniValueError, match="not a value Event.venue takes") as caught:
            grants.check(VIEW, "related:venue", ["not-an-id"])
        assert caught.value.code == "E362"

    def test_full_clean_reports_on_the_field(self) -> None:
        row = UserGrant(user=_user("a@example.com"), permission=VIEW, scope="related:nowhere")
        with pytest.raises(ValidationError) as caught:
            row.full_clean()
        assert "scope" in caught.value.message_dict
        assert "E361" in caught.value.message_dict["scope"][0]

    def test_save_stores_targets_as_text(self, place: Any) -> None:
        arena, *_ = place
        row = UserGrant.objects.create(
            user=_user("a@example.com"), permission=VIEW, scope="related:venue", targets=[arena.pk]
        )
        row.refresh_from_db()
        assert row.targets == [str(arena.pk)]

    def test_the_switch_must_be_a_boolean(self, settings: Any) -> None:
        from django.conf import settings as live

        values = {name: getattr(live, name) for name in dir(live) if name.isupper()}
        with pytest.raises(Exception, match="KARNI_USER_GRANTS = 'yes' must be True or False"):
            validate_settings({**values, "KARNI_USER_GRANTS": "yes"})


# the union


class TestUnion:
    def test_role_grants_alone(self, place: Any) -> None:
        alice = _user("alice@example.com", "organizer")
        _event("Mine", organizer=alice)
        _event("Theirs")
        assert _visible(alice) == {"Mine"}
        assert all(not grant.grant_id for grant in grants_for(alice)[VIEW])

    def test_user_grants_alone(self, place: Any) -> None:
        arena, hall, _ = place
        guest = _user("guest@example.com")
        _event("At arena", venue=arena)
        _event("At hall", venue=hall)
        assert not user_can(guest, VIEW)
        grants.grant(None, guest, VIEW, "related:venue", targets=[arena.pk])
        guest = _fresh(guest)
        assert user_can(guest, VIEW)
        assert _visible(guest) == {"At arena"}
        assert not user_can(guest, APPROVE)

    def test_role_and_user_grants_are_a_union(self, place: Any) -> None:
        arena, hall, _ = place
        alice = _user("alice@example.com", "organizer")
        _event("Mine", organizer=alice, venue=hall)
        _event("At arena", venue=arena)
        _event("At hall", venue=hall)
        grants.grant(None, alice, VIEW, "related:venue", targets=[arena.pk])
        alice = _fresh(alice)
        assert _visible(alice) == {"Mine", "At arena"}
        held = grants_for(alice)[VIEW]
        assert {grant.scope for grant in held} == {"own", "related"}
        assert user_can(alice, VIEW, Event.objects.get(title="At arena"))
        assert not user_can(alice, VIEW, Event.objects.get(title="At hall"))

    def test_an_all_grant_reaches_every_row(self) -> None:
        guest = _user("guest@example.com")
        _event("One")
        _event("Two")
        grants.grant(None, guest, "testapp.event:*", "all")
        guest = _fresh(guest)
        assert rows_for(guest, Event, "view") is True
        assert user_can(guest, APPROVE)

    def test_without_targets_related_reads_the_users_attribute(self, place: Any) -> None:
        arena, hall, _ = place
        guest = _user("guest@example.com")
        _event("At arena", venue=arena)
        _event("At hall", venue=hall)
        grants.grant(None, guest, VIEW, "related:venue")
        guest = _fresh(guest)
        guest.venue = hall
        assert _visible(guest) == {"At hall"}

    def test_a_custom_scope_works_for_a_user_grant(self) -> None:
        roles_mod.register_scope("published", lambda user, model: Q(status="published"))
        try:
            guest = _user("guest@example.com")
            _event("Draft")
            _event("Out", status="published")
            grants.grant(None, guest, VIEW, "custom:published")
            assert _visible(_fresh(guest)) == {"Out"}
        finally:
            roles_mod._custom_scopes.pop("published", None)

    def test_a_readable_row_follows_the_first_target(self, place: Any) -> None:
        from karni.testing.api import granted_values

        arena, *_ = place
        guest = _user("guest@example.com")
        grants.grant(None, guest, VIEW, "related:venue", targets=[arena.pk])
        values = granted_values(Event, _fresh(guest))
        assert values == {"venue_id": str(arena.pk)}
        row = _event("Readable", **values)
        assert user_can(_fresh(guest), VIEW, row)

    def test_a_superuser_pays_nothing_more(self) -> None:
        root = _user("root@example.com", is_superuser=True)
        with CaptureQueriesContext(connection) as queries:
            grants_for(root)
        assert len(queries) == 0


# expiry and revocation


class TestExpiry:
    def test_an_expired_grant_is_ignored(self, place: Any) -> None:
        arena, *_ = place
        guest = _user("guest@example.com")
        _event("At arena", venue=arena)
        grants.grant(
            None,
            guest,
            VIEW,
            "related:venue",
            targets=[arena.pk],
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert not user_can(_fresh(guest), VIEW)
        assert UserGrant.objects.expired().count() == 1 and not UserGrant.objects.live().exists()

    def test_a_grant_until_later_applies_until_then(self, place: Any) -> None:
        arena, *_ = place
        guest = _user("guest@example.com")
        row = grants.grant(None, guest, VIEW, "all", expires_at=timezone.now() + timedelta(days=1))
        assert user_can(_fresh(guest), VIEW) and row.is_live
        later = timezone.now() + timedelta(days=2)
        assert not UserGrant.objects.live(at=later).exists()

    def test_expire_ends_it_and_keeps_the_row(self) -> None:
        guest = _user("guest@example.com")
        row = grants.grant(None, guest, VIEW, "all")
        grants.expire(None, row)
        assert not user_can(_fresh(guest), VIEW)
        assert UserGrant.objects.filter(pk=row.pk).exists() and not row.is_live

    def test_revoke_is_a_recorded_soft_delete(self) -> None:
        from karni.audit.services import history_for

        operator = _user("ops@example.com", "ops")
        guest = _user("guest@example.com")
        row = grants.grant(operator, guest, VIEW, "all", reason="pilot")
        grants.revoke(operator, row)
        assert not user_can(_fresh(guest), VIEW)
        assert not UserGrant.objects.filter(pk=row.pk).exists()
        assert UserGrant.objects.without("soft_delete", reason="test").filter(pk=row.pk).exists()
        actions = [entry.action for entry in history_for(row)]
        assert actions[0] == "delete" and "create" in actions
        assert all(entry.actor_id == operator.pk for entry in history_for(row))

    def test_the_grantee_instance_forgets_its_grants(self) -> None:
        guest = _user("guest@example.com")
        assert not user_can(guest, VIEW)
        row = grants.grant(None, guest, VIEW, "all")
        assert user_can(guest, VIEW)  # grant() forgot the cached answer
        grants.revoke(None, UserGrant.objects.select_related("user").get(pk=row.pk))
        assert user_can(guest, VIEW)  # a different instance: this one keeps its request's view
        assert not user_can(_fresh(guest), VIEW)


# the interface for scopes that point at rows


class TestScopeTargets:
    def test_roles_and_user_grants_name_their_targets(self, place: Any) -> None:
        arena, hall, dome = place
        manager = _user("manager@example.com", "venue_manager")
        manager.venue = hall
        first = grants.grant(
            None, manager, VIEW, "related:venue", targets=[arena.pk], reason="cover"
        )
        grants.grant(None, manager, APPROVE, "related:venue", targets=[dome.pk])
        manager = _fresh(manager)
        manager.venue = hall
        found = grants.scope_targets(manager, "related:venue", permission=VIEW)
        by_target = {(item.target, item.source.origin) for item in found}
        assert by_target == {(str(hall.pk), "declared"), (str(arena.pk), "user_grant")}
        granted = next(item for item in found if item.source.origin == "user_grant")
        assert granted.source.grant_id == str(first.pk) and granted.source.reason == "cover"
        assert granted.to_dict()["grant"] == str(first.pk)
        role = next(item for item in found if item.source.origin == "declared")
        assert role.source.role == "venue_manager"
        everything = grants.scope_targets(manager, "related:venue")
        assert {item.target for item in everything} == {
            str(arena.pk),
            str(hall.pk),
            str(dome.pk),
        }
        assert {item.permission for item in everything} == {VIEW, APPROVE}
        assert grants.scope_targets(manager, "related:venue", permission="testapp.event:a*")

    def test_expired_revoked_and_switched_off_grants_give_no_target(
        self, place: Any, settings: Any
    ) -> None:
        arena, hall, _ = place
        guest = _user("guest@example.com")
        grants.grant(
            None,
            guest,
            VIEW,
            "related:venue",
            targets=[arena.pk],
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        gone = grants.grant(None, guest, VIEW, "related:venue", targets=[hall.pk])
        grants.revoke(None, gone)
        assert grants.scope_targets(_fresh(guest), "related:venue") == []
        grants.grant(None, guest, VIEW, "related:venue", targets=[hall.pk])
        settings.KARNI_USER_GRANTS = False
        assert grants.scope_targets(_fresh(guest), "related:venue") == []

    def test_scopes_without_rows_and_superusers_give_nothing(self) -> None:
        root = _user("root@example.com", is_superuser=True)
        assert grants.scope_targets(root, "related:venue") == []
        assert grants.scope_targets(_user("a@example.com", "organizer"), "own") == []
        with pytest.raises(KarniValueError, match="E361"):
            grants.scope_targets(root, "related")


# the switch and the query cost


class TestCost:
    def test_switched_off_reads_no_grant_and_costs_no_query(
        self, place: Any, settings: Any
    ) -> None:
        arena, *_ = place
        alice = _user("alice@example.com", "organizer")
        grants.grant(None, alice, VIEW, "related:venue", targets=[arena.pk])
        settings.KARNI_USER_GRANTS = False
        fresh = _fresh(alice)
        with CaptureQueriesContext(connection) as queries:
            grants_for(fresh)
        assert len(queries) == 1  # the role grants only
        assert all("usergrant" not in query["sql"] for query in queries.captured_queries)
        assert all(not grant.grant_id for grant in grants_for(fresh)[VIEW])
        assert [source.origin for source in grant_sources(fresh, VIEW)] == ["declared"]

    def test_switched_on_is_one_more_query_however_many_checks(self, place: Any) -> None:
        arena, *_ = place
        alice = _user("alice@example.com", "organizer")
        for venue in place:
            grants.grant(None, alice, VIEW, "related:venue", targets=[venue.pk])
        grants.grant(None, alice, "testapp.*:*", "all")
        event = _event("At arena", venue=arena)
        fresh = _fresh(alice)
        with CaptureQueriesContext(connection) as queries:
            for _ in range(50):
                assert user_can(fresh, VIEW)
                assert user_can(fresh, APPROVE)
                rows_for(fresh, Event, "view")
                rows_for(fresh, Venue, "change")
        assert len(queries) == 2  # role grants + user grants, once for the request
        with CaptureQueriesContext(connection) as again:
            assert user_can(fresh, VIEW, event)
        assert len(again) == 0  # an all grant needs no row query

    def test_sources_name_the_user_grant(self, place: Any) -> None:
        arena, *_ = place
        alice = _user("alice@example.com", "organizer")
        later = timezone.now() + timedelta(days=3)
        row = grants.grant(
            None,
            alice,
            VIEW,
            "related:venue",
            targets=[arena.pk],
            expires_at=later,
            reason="cover",
        )
        found = grant_sources(_fresh(alice), VIEW)
        assert [source.origin for source in found] == ["declared", "user_grant"]
        source = found[1]
        assert (source.grant_id, source.reason, source.expires_at) == (str(row.pk), "cover", later)
        assert source.targets == (str(arena.pk),) and source.scope_label == "related:venue"


# writing: what the operator may give


class TestRefusals:
    def test_nobody_grants_what_they_do_not_hold(self) -> None:
        organizer = _user("o@example.com", "organizer")
        guest = _user("guest@example.com")
        with pytest.raises(grants.GrantRefused) as caught:
            grants.grant(organizer, guest, APPROVE, "all")
        assert caught.value.code == "E363"
        assert "you do not hold testapp.event:approve" in caught.value.reasons[0]
        with pytest.raises(grants.GrantRefused, match="only as own"):
            grants.grant(organizer, guest, VIEW, "all")
        assert not UserGrant.objects.exists()
        grants.grant(organizer, guest, VIEW, "own")  # what they hold, they may give

    def test_targets_must_be_the_operators_own(self, place: Any) -> None:
        arena, hall, dome = place
        manager = _user("manager@example.com", "venue_manager")
        manager.venue = hall
        guest = _user("guest@example.com")
        grants.grant(manager, guest, VIEW, "related:venue", targets=[hall.pk])
        with pytest.raises(grants.GrantRefused, match=f"without {dome.pk}"):
            grants.grant(manager, guest, VIEW, "related:venue", targets=[hall.pk, dome.pk])
        grants.grant(None, manager, VIEW, "related:venue", targets=[dome.pk])
        manager = _fresh(manager)
        manager.venue = hall
        grants.grant(manager, guest, VIEW, "related:venue", targets=[hall.pk, dome.pk])

    def test_a_bulk_grant_is_all_or_nothing(self) -> None:
        operator = _user("ops@example.com", "ops")
        people = [_user(f"p{n}@example.com") for n in range(4)]
        made = grants.bulk_grant(operator, people, VIEW, "all", reason="launch")
        assert len(made) == 4 and {row.granted_by_id for row in made} == {operator.pk}
        assert all(user_can(_fresh(person), VIEW) for person in people)
        with pytest.raises(KarniValueError, match="E360"):
            grants.bulk_grant(operator, people, "testapp.event:nope", "all")
        assert UserGrant.objects.count() == 4

    def test_change_checks_only_what_gives_more(self, place: Any) -> None:
        arena, hall, _ = place
        organizer = _user("o@example.com", "organizer")
        guest = _user("guest@example.com")
        row = grants.grant(None, guest, VIEW, "all", expires_at=timezone.now() + timedelta(days=9))
        assert row.granted_by is None
        grants.change(organizer, row, reason="kept", expires_at=timezone.now() + timedelta(days=1))
        with pytest.raises(grants.GrantRefused):
            grants.change(organizer, row, expires_at=None)
        with pytest.raises(grants.GrantRefused):
            grants.change(organizer, row, scope="related:venue", targets=[arena.pk])
        grants.change(None, row, scope="related:venue", targets=[arena.pk, hall.pk])
        row.refresh_from_db()
        assert (row.scope, row.targets, row.reason) == (
            "related:venue",
            [str(arena.pk), str(hall.pk)],
            "kept",
        )
        with pytest.raises(TypeError, match=r"E365: change\(\) cannot set user"):
            grants.change(None, row, user=organizer)

    def test_a_superuser_may_give_anything(self) -> None:
        root = _user("root@example.com", is_superuser=True)
        row = grants.grant(root, _user("g@example.com"), "*", "all")
        assert row.granted_by == root and row.permission == "*"
