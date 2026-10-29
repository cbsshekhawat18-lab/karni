"""A role's grants open the admin pages (KARNI_ADMIN_GRANTS_OPEN_PAGES, docs/admin.md).

A staff user holding ``app.model:<action>`` through a role opens that page
for that action, inside the grant's scope and unless a veto refuses it.
Django's model permissions keep working for users without a grant, and the
setting restores the old rule (Django's permissions only).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.vetoes import VetoContext, register_veto, unregister_veto
from tests.adminapp.models import KitchenSink, Note
from tests.testapp.models import Event, Tag, Venue

pytestmark = pytest.mark.django_db

ROLES = {
    "staff": {"name": "Staff", "system": True, "grants": {"*": "all"}},
    # A project's own role: what a front desk does, and nothing else.
    "front_desk": {"grants": {"testapp.event:*": "all", "testapp.venue:view": "all"}},
    "organizer": {"grants": {"testapp.event:*": "own"}},
    "note_taker": {
        "grants": {
            "adminapp.kitchensink:view": "all",
            "adminapp.kitchensink:change": "all",
            "adminapp.note:*": "all",
        }
    },
    "people": {"grants": {"karni_accounts.user:*": "all"}},
}


@pytest.fixture(autouse=True)
def _roles() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _staff(email: str, *roles: str) -> Any:
    user = get_user_model().objects.create_user(
        email=email, password="a-strong-password-123", is_staff=True
    )
    for role in roles:
        assign_role(user, role)
    return user


def _signed_in(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _url(model: type[Any], view: str, *args: Any) -> str:
    opts = model._meta
    return reverse(f"admin:{opts.app_label}_{opts.model_name}_{view}", args=args)


def _listed(response: Any) -> set[str]:
    """The ``app_label.model`` of every model the index or an app page lists."""
    return {
        f"{app['app_label']}.{entry['object_name'].lower()}"
        for app in response.context["app_list"]
        for entry in app["models"]
    }


def _event(title: str, **kwargs: Any) -> Event:
    kwargs.setdefault("starts_at", timezone.now())
    return Event.objects.create(title=title, **kwargs)


def _event_form(title: str) -> dict[str, str]:
    return {
        "title": title,
        "description": "",
        "starts_at_0": "2026-11-02",
        "starts_at_1": "10:00:00",
        "status": "draft",
        "is_public": "on",
        "internal_note": "",
        "_save": "1",
    }


def test_a_project_role_opens_its_pages_without_django_permissions() -> None:
    desk = _staff("desk@example.com", "front_desk")
    assert not desk.user_permissions.exists()
    event = _event("Open day")
    client = _signed_in(desk)
    assert client.get(_url(Event, "changelist")).status_code == 200
    assert client.get(_url(Event, "change", event.pk)).status_code == 200
    assert client.get(_url(Event, "add")).status_code == 200
    saved = client.post(_url(Event, "change", event.pk), _event_form("Open evening"))
    assert saved.status_code == 302, saved.content.decode()[:2000]
    event.refresh_from_db()
    assert event.title == "Open evening"
    assert client.get(_url(Event, "delete", event.pk)).status_code == 200
    # venue:view and nothing more: the page opens read-only, add and delete do not.
    venue = Venue.objects.create(name="Hall", city="Leeds")
    assert client.get(_url(Venue, "changelist")).status_code == 200
    change = client.get(_url(Venue, "change", venue.pk))
    assert change.status_code == 200 and not change.context["has_change_permission"]
    assert client.get(_url(Venue, "add")).status_code == 403
    assert client.get(_url(Venue, "delete", venue.pk)).status_code == 403
    # No grant on tags: the page is closed.
    assert client.get(_url(Tag, "changelist")).status_code == 403


def test_the_index_and_the_app_page_list_exactly_what_the_user_may_open() -> None:
    desk = _signed_in(_staff("desk@example.com", "front_desk"))
    index = desk.get(reverse("admin:index"))
    assert index.status_code == 200
    assert _listed(index) == {"testapp.event", "testapp.venue"}
    app_page = desk.get(reverse("admin:app_list", kwargs={"app_label": "testapp"}))
    assert _listed(app_page) == {"testapp.event", "testapp.venue"}
    # An app the user holds no grant in has no page.
    assert desk.get(reverse("admin:app_list", kwargs={"app_label": "adminapp"})).status_code == 404


def test_the_staff_role_opens_every_karni_admin_page() -> None:
    staff = _staff("staff@example.com", "staff")
    client = _signed_in(staff)
    index = _listed(client.get(reverse("admin:index")))
    for model in (Event, Venue, Tag, KitchenSink, Note, get_user_model()):
        opts = model._meta
        assert f"{opts.app_label}.{opts.object_name.lower()}" in index, model
        assert client.get(_url(model, "changelist")).status_code == 200, model
        assert client.get(_url(model, "add")).status_code == 200, model
    event = _event("Gala")
    assert client.get(_url(Event, "change", event.pk)).status_code == 200


def test_django_permissions_still_open_pages_for_a_user_without_a_grant() -> None:
    clerk = _staff("clerk@example.com")
    clerk.user_permissions.add(
        *Permission.objects.filter(
            content_type=ContentType.objects.get_for_model(Venue),
            codename__in=["view_venue", "change_venue"],
        )
    )
    Venue.objects.create(name="Hall", city="Leeds")
    client = _signed_in(clerk)
    assert _listed(client.get(reverse("admin:index"))) == {"testapp.venue"}
    response = client.get(_url(Venue, "changelist"))
    assert response.status_code == 200
    # As before: a Django permission opens the page, a grant decides the rows.
    assert response.context_data["cl"].queryset.count() == 0
    assert client.get(_url(Event, "changelist")).status_code == 403


def test_a_user_with_neither_sees_nothing() -> None:
    nobody = _signed_in(_staff("nobody@example.com"))
    assert _listed(nobody.get(reverse("admin:index"))) == set()
    assert nobody.get(_url(Event, "changelist")).status_code == 403
    assert nobody.get(_url(Venue, "changelist")).status_code == 403


def test_a_role_without_staff_status_does_not_sign_in() -> None:
    desk = get_user_model().objects.create_user(
        email="desk@example.com", password="a-strong-password-123"
    )
    assign_role(desk, "front_desk")
    response = _signed_in(desk).get(_url(Event, "changelist"))
    assert response.status_code == 302 and "/login/" in response["Location"]


def test_superusers_open_every_page() -> None:
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    client = _signed_in(root)
    listed = _listed(client.get(reverse("admin:index")))
    assert {"testapp.event", "testapp.venue", "testapp.tag", "adminapp.note"} <= listed
    assert client.get(_url(Tag, "add")).status_code == 200


def test_the_grant_scope_decides_the_change_form() -> None:
    alice = _staff("alice@example.com", "organizer")
    bob = _staff("bob@example.com", "organizer")
    mine = _event("Alice's", organizer=alice)
    theirs = _event("Bob's", organizer=bob)
    client = _signed_in(alice)
    shown = client.get(_url(Event, "changelist")).context_data["cl"].queryset
    assert set(shown.values_list("pk", flat=True)) == {mine.pk}
    assert client.get(_url(Event, "change", mine.pk)).status_code == 200
    # Out of scope: answered as Django answers a row that does not exist.
    assert client.get(_url(Event, "change", theirs.pk)).status_code == 302
    client.post(_url(Event, "change", theirs.pk), _event_form("Hijacked"))
    theirs.refresh_from_db()
    assert theirs.title == "Bob's"


def test_a_veto_still_refuses_a_granted_action() -> None:
    def no_changes(context: VetoContext) -> str | None:
        if context.kind == "admin" and context.action in {"change", "delete"}:
            return "frozen for the audit"
        return None

    desk = _staff("desk@example.com", "front_desk")
    event = _event("Open day")
    register_veto(no_changes, name="tests.frozen")
    try:
        model_admin = admin.site._registry[Event]
        client = _signed_in(desk)
        page = client.get(_url(Event, "change", event.pk))
        assert page.status_code == 200 and not page.context["has_change_permission"]
        client.post(_url(Event, "change", event.pk), _event_form("Changed anyway"))
        event.refresh_from_db()
        assert event.title == "Open day"
        assert client.get(_url(Event, "delete", event.pk)).status_code == 403
        request = page.wsgi_request
        assert model_admin.granted(request, "change")  # granted, and still refused
    finally:
        unregister_veto("tests.frozen")


def test_the_setting_restores_django_permissions_only(settings: Any) -> None:
    settings.KARNI_ADMIN_GRANTS_OPEN_PAGES = False
    desk = _signed_in(_staff("desk@example.com", "front_desk"))
    assert desk.get(_url(Event, "changelist")).status_code == 403
    assert _listed(desk.get(reverse("admin:index"))) == set()
    # Django's permissions open the page, the grants still decide the rows.
    clerk = _staff("clerk@example.com", "front_desk")
    clerk.user_permissions.add(
        *Permission.objects.filter(content_type=ContentType.objects.get_for_model(Event))
    )
    _event("Open day")
    response = _signed_in(clerk).get(_url(Event, "changelist"))
    assert response.status_code == 200 and response.context_data["cl"].queryset.count() == 1


def test_an_inline_opens_for_a_grant_on_its_model(settings: Any) -> None:
    taker = _staff("taker@example.com", "note_taker")
    kitchen = KitchenSink.objects.create(name="Main")
    Note.objects.create(title="Clean the oven", kitchen=kitchen)
    page = _signed_in(taker).get(_url(KitchenSink, "change", kitchen.pk))
    assert page.status_code == 200
    formsets = {type(f.opts).__name__: f for f in page.context["inline_admin_formsets"]}
    notes = formsets["NoteInline"]
    assert notes.has_add_permission and notes.has_change_permission
    assert "Clean the oven" in page.content.decode()
    settings.KARNI_ADMIN_GRANTS_OPEN_PAGES = False
    taker.user_permissions.add(
        *Permission.objects.filter(
            content_type=ContentType.objects.get_for_model(KitchenSink), codename="view_kitchensink"
        )
    )
    taker = get_user_model().objects.get(pk=taker.pk)  # drop the cached permissions
    page = _signed_in(taker).get(_url(KitchenSink, "change", kitchen.pk))
    assert page.status_code == 200
    inlines = [type(f.opts).__name__ for f in page.context["inline_admin_formsets"]]
    assert "NoteInline" not in inlines


def test_a_grant_on_users_never_makes_a_superuser() -> None:
    manager = _staff("manager@example.com", "people")
    root = get_user_model().objects.create_superuser(
        email="root@example.com", password="a-strong-password-123"
    )
    colleague = _staff("colleague@example.com")
    client = _signed_in(manager)
    model = get_user_model()
    page = client.get(_url(model, "change", colleague.pk))
    assert page.status_code == 200 and page.context["has_change_permission"]
    readonly = page.context["adminform"].readonly_fields
    assert "is_superuser" in readonly and "user_permissions" in readonly
    # A superuser's account is read-only to them, and cannot be deleted.
    assert not client.get(_url(model, "change", root.pk)).context["has_change_permission"]
    assert client.get(_url(model, "delete", root.pk)).status_code == 403
    # A superuser still edits every field.
    as_root = _signed_in(root).get(_url(model, "change", colleague.pk))
    assert "is_superuser" not in as_root.context["adminform"].readonly_fields
