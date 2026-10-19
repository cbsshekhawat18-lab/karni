"""Row scope in the admin (ADR 0002, P2): the admin shows what the user's grants reach."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.admin.base import KarniModelAdmin, build_model_admin
from karni.checks import check_admin_scope
from karni.scoping import scope_exemptions
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

ROLES = {
    "staff": {"system": True, "grants": {"*": "all"}},
    "organizer": {"grants": {"testapp.event:*": "own", "testapp.venue:view": "all"}},
    "reader": {"grants": {"testapp.event:view": "all"}},
}


class ExemptEventAdmin(KarniModelAdmin):
    scope_exempt = True
    scope_exempt_reason = "support console: every event, Django permissions only"


class ReasonlessEventAdmin(KarniModelAdmin):
    scope_exempt = True


exempt_site = AdminSite(name="exempt")
exempt_site.register(Event, ExemptEventAdmin)
reasonless_site = AdminSite(name="reasonless")
reasonless_site.register(Event, ReasonlessEventAdmin)


@pytest.fixture(autouse=True)
def _roles() -> Any:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _staff(email: str, *roles: str, perms: tuple[str, ...] = ("view", "change", "delete")) -> Any:
    user = get_user_model().objects.create_user(
        email=email, password="a-strong-password-123", is_staff=True
    )
    for role in roles:
        assign_role(user, role)
    content_type = ContentType.objects.get_for_model(Event)
    user.user_permissions.add(
        *Permission.objects.filter(
            content_type=content_type, codename__in=[f"{p}_event" for p in perms]
        )
    )
    return user


def _request(user: Any) -> Any:
    request = RequestFactory().get("/")
    request.user = user
    return request


def _event(title: str, **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(title=title, **kwargs)


def _event_admin(site: AdminSite | None = None) -> Any:
    return build_model_admin(Event)(Event, site or AdminSite())


def _titles(queryset: Any) -> set[str]:
    return set(queryset.values_list("title", flat=True))


def test_the_queryset_follows_the_view_grant() -> None:
    alice = _staff("alice@example.com", "organizer")
    bob = _staff("bob@example.com", "organizer")
    reader = _staff("reader@example.com", "reader")
    lost = _staff("lost@example.com")  # Django permissions, no grant: nothing
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    _event("Alice's", organizer=alice)
    _event("Bob's", organizer=bob)
    model_admin = _event_admin()
    assert _titles(model_admin.get_queryset(_request(alice))) == {"Alice's"}
    assert _titles(model_admin.get_queryset(_request(reader))) == {"Alice's", "Bob's"}
    assert _titles(model_admin.get_queryset(_request(lost))) == set()
    assert _titles(model_admin.get_queryset(_request(root))) == {"Alice's", "Bob's"}


def test_object_permissions_follow_the_action_grants() -> None:
    alice = _staff("alice@example.com", "organizer")
    reader = _staff("reader@example.com", "reader")
    mine = _event("Mine", organizer=alice)
    theirs = _event("Theirs", organizer=reader)
    model_admin = _event_admin()
    request = _request(alice)
    assert model_admin.has_change_permission(request, mine)
    assert model_admin.has_delete_permission(request, mine)
    assert not model_admin.has_view_permission(request, theirs)
    assert not model_admin.has_change_permission(request, theirs)
    assert not model_admin.has_delete_permission(request, theirs)
    assert model_admin.has_change_permission(request)  # the screen exists
    reading = _request(reader)
    assert model_admin.has_view_permission(reading, mine)
    assert not model_admin.has_change_permission(reading, mine)  # no change grant


def test_relation_choices_are_the_rows_the_user_may_view() -> None:
    alice = _staff("alice@example.com", "organizer")  # venue:view all, no tag grant
    Venue.objects.create(name="Here", city="Berlin")
    Venue.objects.create(name="There", city="Rome")
    Tag.objects.create(name="music")
    model_admin = _event_admin()
    request = _request(alice)
    venues = model_admin.formfield_for_foreignkey(Event._meta.get_field("venue"), request)
    assert venues.queryset.count() == 2
    tags = model_admin.formfield_for_manytomany(Event._meta.get_field("tags"), request)
    assert tags.queryset.count() == 0
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    assert (
        model_admin.formfield_for_manytomany(
            Event._meta.get_field("tags"), _request(root)
        ).queryset.count()
        == 1
    )


def test_a_soft_deleted_row_inside_the_scope_stays_reachable() -> None:
    alice = _staff("alice@example.com", "organizer")
    gone = _event("Gone", organizer=alice)
    gone.delete()  # soft
    model_admin = _event_admin()
    request = _request(alice)
    assert _titles(model_admin.get_queryset(request)) == {"Gone"}  # the admin lifts soft_delete
    assert model_admin.has_change_permission(request, gone)  # restorable by its owner


def test_an_exempt_admin_sees_everything_and_is_listed() -> None:
    alice = _staff("alice@example.com", "organizer")
    _event("Mine", organizer=alice)
    _event("Theirs", organizer=_staff("bob@example.com", "organizer"))
    exempt = exempt_site._registry[Event]
    assert _titles(exempt.get_queryset(_request(alice))) == {"Mine", "Theirs"}
    with override_settings(KARNI_ADMIN_SITE="tests.admin.test_scope.exempt_site"):
        found = {(item.kind, item.name): item.reason for item in scope_exemptions()}
        assert found[("admin", "ExemptEventAdmin (testapp.event)")].startswith("support console")
        assert check_admin_scope() == []
    with override_settings(KARNI_ADMIN_SITE="tests.admin.test_scope.reasonless_site"):
        messages = check_admin_scope()
        assert [m.id for m in messages] == ["karni.E210"]
        assert "ReasonlessEventAdmin" in messages[0].msg


def test_through_the_admin_site() -> None:
    if Event not in admin.site._registry:
        pytest.skip("Event is not registered on the default admin site")
    alice = _staff("alice@example.com", "organizer")
    bob = _staff("bob@example.com", "organizer")
    mine = _event("Alice keynote", organizer=alice)
    theirs = _event("Bob keynote", organizer=bob)
    client = Client()
    client.force_login(alice)
    changelist = reverse("admin:testapp_event_changelist")
    response = client.get(changelist)
    assert response.status_code == 200
    shown = set(response.context_data["cl"].queryset.values_list("pk", flat=True))
    assert shown == {mine.pk}
    searched = client.get(changelist, {"q": "keynote"})
    assert set(searched.context_data["cl"].queryset.values_list("pk", flat=True)) == {mine.pk}
    change = reverse("admin:testapp_event_change", args=[theirs.pk])
    assert client.get(change).status_code != 200
    before = Event.objects.filter(pk=theirs.pk).values().first()
    client.post(change, {"title": "Hijacked", "_save": "1"})
    assert Event.objects.filter(pk=theirs.pk).values().first() == before
    assert client.get(reverse("admin:testapp_event_change", args=[mine.pk])).status_code == 200
