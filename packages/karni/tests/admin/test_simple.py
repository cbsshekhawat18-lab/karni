"""The simple admin: buttons by permission, bulk actions, the guide, help text, technical fields."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache as default_cache
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.admin.base import build_model_admin
from karni.admin.derive import derive_help
from karni.api import caching
from karni.audit.services import history_for
from tests.adminapp.models import Gizmo, KitchenSink, Note, Widget
from tests.externalapp.models import Stock
from tests.testapp.models import Customer, Price

pytestmark = pytest.mark.django_db

ROLES = {
    "viewer": {"grants": {"adminapp.note:view": "all"}},
    "editor": {"grants": {"adminapp.note:view": "all", "adminapp.note:change": "all"}},
    "manager": {"grants": {"adminapp.note:*": "all"}},
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


def _super() -> Any:
    users = get_user_model()
    found = users.objects.filter(email="root@example.com").first()
    return found or users.objects.create_superuser(email="root@example.com", password="pw-123456")


def _client(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


def _request(user: Any, path: str = "/") -> Any:
    request = RequestFactory().get(path)
    request.user = user
    return request


def _url(model: type[Any], view: str, *args: Any) -> str:
    opts = model._meta
    return reverse(f"admin:{opts.app_label}_{opts.model_name}_{view}", args=args)


def _notes(count: int = 3) -> list[Note]:
    return [Note.objects.create(title=f"Note {i}") for i in range(1, count + 1)]


# -- the theme: light whatever the browser prefers ----------------------------------


def test_every_admin_page_is_light_with_no_switch() -> None:
    client = _client(_super())
    for url in ("/admin/", _url(Note, "changelist")):
        html = client.get(url, headers={"Sec-CH-Prefers-Color-Scheme": "dark"}).content.decode()
        assert "theme('light')" in html and "switchTheme" not in html


# -- buttons by permission ----------------------------------------------------------


def test_a_superuser_sees_add_edit_and_delete() -> None:
    note = _notes(1)[0]
    html = _client(_super()).get(_url(Note, "changelist")).content.decode()
    assert "Add note" in html and "karni-add" in html
    assert f'aria-label="Edit {note}"' in html and f'aria-label="Delete {note}"' in html
    assert _url(Note, "delete", note.pk) in html


def test_a_view_only_role_sees_no_write_buttons() -> None:
    note = _notes(1)[0]
    client = _client(_staff("viewer@example.com", "viewer"))
    html = client.get(_url(Note, "changelist")).content.decode()
    assert "karni-add" not in html
    assert f'aria-label="View {note}"' in html
    assert 'aria-label="Edit' not in html and 'aria-label="Delete' not in html
    form = client.get(_url(Note, "change", note.pk)).content.decode()
    assert 'name="_save"' not in form and 'name="_continue"' not in form
    assert "Cancel" in form and ">Delete<" not in form


def test_a_role_that_changes_but_cannot_delete() -> None:
    note = _notes(1)[0]
    client = _client(_staff("editor@example.com", "editor"))
    html = client.get(_url(Note, "changelist")).content.decode()
    assert f'aria-label="Edit {note}"' in html
    assert 'aria-label="Delete' not in html and "karni-add" not in html
    form = client.get(_url(Note, "change", note.pk)).content.decode()
    assert 'name="_save"' in form and 'name="_continue"' in form
    assert 'name="_addanother"' not in form and ">Delete<" not in form


def test_the_form_bar_for_a_manager_has_every_button_with_save_first() -> None:
    note = _notes(1)[0]
    form = (
        _client(_staff("manager@example.com", "manager"))
        .get(_url(Note, "change", note.pk))
        .content.decode()
    )
    positions = [
        form.index(marker)
        for marker in (
            'name="_save"',
            'name="_addanother"',
            'name="_continue"',
            ">Cancel<",
            ">Delete<",
        )
    ]
    assert positions == sorted(positions)
    assert 'class="karni-button"' in form  # the primary look


def test_a_deleted_row_has_restore_not_delete_and_the_deleted_filter_exists() -> None:
    note = _notes(1)[0]
    note.delete()
    client = _client(_super())
    assert 'aria-label="Restore' not in client.get(_url(Note, "changelist")).content.decode()
    html = client.get(_url(Note, "changelist"), {"deleted": "deleted"}).content.decode()
    assert f'aria-label="Restore {note}"' in html and 'aria-label="Delete' not in html
    assert "Deleted" in html
    client.post(_url(Note, "restore", note.pk))
    assert Note.objects.filter(pk=note.pk).exists()


def test_row_restore_needs_the_change_permission() -> None:
    note = _notes(1)[0]
    note.delete()
    response = _client(_staff("viewer@example.com", "viewer")).post(_url(Note, "restore", note.pk))
    assert response.status_code in (302, 403, 404)
    assert not Note.objects.filter(pk=note.pk).exists()


def test_a_read_only_model_has_no_write_buttons() -> None:
    model_admin = admin.site._registry[Stock]
    column = model_admin.row_actions_column(_request(_super()))
    assert column is not None
    html = str(column(Stock(sku="A1", quantity=1)))
    assert "View" in html and "Edit" not in html and "Delete" not in html
    assert model_admin.has_add_permission(_request(_super())) is False


# -- bulk delete, restore, edit ----------------------------------------------------


def test_bulk_delete_confirms_with_count_and_sample_then_soft_deletes() -> None:
    notes = _notes(12)
    client = _client(_super())
    ids = [str(n.pk) for n in notes]
    page = client.post(
        _url(Note, "changelist"), {"action": "delete_selected", "_selected_action": ids}
    ).content.decode()
    assert "Delete 12 notes?" in page and "and 2 more" in page
    assert "can be restored" in page
    before = LogEntry.objects.count()
    client.post(
        _url(Note, "changelist"),
        {"action": "delete_selected", "_selected_action": ids, "post": "yes"},
    )
    assert (
        Note.objects.count() == 0
        and Note.objects.without("soft_delete", reason="test").count() == 12
    )
    assert LogEntry.objects.count() == before + 12  # audited


def test_bulk_delete_is_refused_without_the_delete_permission() -> None:
    notes = _notes(2)
    response = _client(_staff("editor@example.com", "editor")).post(
        _url(Note, "changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [str(n.pk) for n in notes],
            "post": "yes",
        },
    )
    assert response.status_code in (200, 302, 403)
    assert Note.objects.count() == 2


def test_bulk_restore() -> None:
    notes = _notes(3)
    for note in notes:
        note.delete()
    _client(_super()).post(
        _url(Note, "changelist") + "?deleted=deleted",
        {"action": "restore_selected", "_selected_action": [str(n.pk) for n in notes]},
    )
    assert Note.objects.count() == 3


def _prices(count: int = 3) -> list[Price]:
    return [Price.objects.create(amount=i, currency="EUR") for i in range(1, count + 1)]


def _edit(client: Client, rows: list[Any], data: dict[str, Any], **extra: Any) -> Any:
    return client.post(
        _url(type(rows[0]), "changelist"),
        {
            "action": "edit_selected",
            "_selected_action": [str(r.pk) for r in rows],
            **extra,
            **data,
        },
    )


def test_edit_selected_lists_the_fields_to_change() -> None:
    rows = _prices()
    page = _edit(_client(_super()), rows, {}).content.decode()
    assert "Change Currency" in page and "Change Note" in page
    assert "Change Id" not in page and "Change Created at" not in page


def test_edit_selected_sets_one_value_on_every_row_audited(monkeypatch: Any) -> None:
    rows = _prices()
    default_cache.clear()
    replaced: list[list[str]] = []
    original = caching._replace

    def spy(keys: Any) -> None:
        keys = list(keys)
        replaced.append(keys)
        original(keys)

    monkeypatch.setattr(caching, "_replace", spy)
    with override_settings(KARNI_API_CACHE=True):
        before = LogEntry.objects.count()
        response = _edit(
            _client(_super()),
            rows,
            {"apply__currency": "on", "currency": "USD"},
            post="yes",
        )
    assert response.status_code == 302
    assert set(Price.objects.values_list("currency", flat=True)) == {"USD"}
    assert LogEntry.objects.count() == before + 3  # an admin log entry per row
    for row in rows:
        latest = history_for(row).first()
        assert latest is not None and "currency" in str(latest.diff)
    assert len([keys for keys in replaced if any("testapp.price" in k for k in keys)]) == 1


def test_edit_selected_changes_nothing_when_no_field_is_ticked() -> None:
    rows = _prices()
    page = _edit(_client(_super()), rows, {"currency": "USD"}, post="yes").content.decode()
    assert "Tick Change beside at least one field" in page
    assert set(Price.objects.values_list("currency", flat=True)) == {"EUR"}


def test_edit_selected_stops_beyond_the_row_limit() -> None:
    rows = _prices(3)
    with override_settings(KARNI_ADMIN_BULK_EDIT_MAX=2):
        response = _edit(
            _client(_super()),
            rows,
            {"apply__currency": "on", "currency": "USD"},
            post="yes",
            follow=True,
        )
    assert set(Price.objects.values_list("currency", flat=True)) == {"EUR"}
    assert response.status_code in (200, 302)
    messages = [str(m) for m in response.wsgi_request._messages] if response.status_code else []
    assert any("at most 2" in m for m in messages)


def test_edit_selected_is_all_or_nothing() -> None:
    rows = _prices(3)
    response = _edit(
        _client(_super()),
        rows,
        {"apply__currency": "on", "currency": "TOOLONG"},
        post="yes",
    )
    assert response.status_code == 200
    assert set(Price.objects.values_list("currency", flat=True)) == {"EUR"}


def test_edit_selected_respects_field_permissions() -> None:
    member = _staff("member@example.com", "user")  # salary, note hidden; phone read-only
    member.user_permissions.add(
        *Permission.objects.filter(content_type=ContentType.objects.get_for_model(Customer))
    )
    model_admin = build_model_admin(Customer)(Customer, AdminSite())
    offered = {f.name for f in model_admin.bulk_editable_fields(_request(member))}
    assert "name" in offered
    assert not offered & {"salary", "internal_note", "phone", "id", "created_at"}


def test_edit_selected_needs_the_change_permission() -> None:
    notes = _notes(2)
    response = _client(_staff("viewer@example.com", "viewer")).post(
        _url(Note, "changelist"),
        {"action": "edit_selected", "_selected_action": [str(n.pk) for n in notes]},
    )
    assert response.status_code in (200, 302, 403)
    assert b"Change Title" not in response.content


# -- export of a selection ---------------------------------------------------------


def test_export_of_a_selection() -> None:
    rows = _prices(3)
    response = _client(_super()).post(
        _url(Price, "changelist"),
        {"action": "export_csv", "_selected_action": [str(rows[0].pk), str(rows[1].pk)]},
    )
    assert response.status_code == 200
    assert "csv" in response["Content-Type"]
    body = b"".join(response.streaming_content).decode()
    assert len(body.strip().splitlines()) == 3  # header and two rows


# -- the guide ----------------------------------------------------------------------


def test_the_guide_is_shown_dismissed_and_brought_back() -> None:
    client = _client(_super())
    home = client.get("/admin/").content.decode()
    assert "Getting started" in home and "Add your first record" in home
    assert "Invite a user" in home and "Set roles" in home
    assert "karni/guide/show/" in home  # the user menu entry
    assert client.get("/admin/karni/guide/dismiss/").status_code == 302  # GET does nothing
    assert "Getting started" in client.get("/admin/").content.decode()
    client.post("/admin/karni/guide/dismiss/")
    assert "karni-guide" not in client.get("/admin/").content.decode()
    client.get("/admin/karni/guide/show/")
    assert "karni-guide" in client.get("/admin/").content.decode()


def test_the_guide_is_per_user() -> None:
    first, second = _client(_super()), _client(_staff("other@example.com", "viewer"))
    first.post("/admin/karni/guide/dismiss/")
    assert "karni-guide" not in first.get("/admin/").content.decode()
    assert "karni-guide" in second.get("/admin/").content.decode()


def test_the_guide_can_be_turned_off() -> None:
    client = _client(_super())
    with override_settings(KARNI_ADMIN_GUIDE=False):
        html = client.get("/admin/").content.decode()
    assert "karni-guide" not in html


def test_the_login_page_still_renders() -> None:
    assert Client().get("/admin/login/").status_code == 200


# -- help text ----------------------------------------------------------------------


def test_help_comes_only_from_karni_help_never_the_docstring() -> None:
    assert derive_help(Widget) == "Things we sell."
    assert derive_help(Note) == ""  # its docstring is a developer note
    assert derive_help(Gizmo) == ""  # and Django's generated docstring is not help


def test_a_docstring_never_reaches_the_list_or_the_form() -> None:
    note = Note.objects.create(title="Note 1")
    client = _client(_super())
    for page in (_url(Note, "changelist"), _url(Note, "change", note.pk)):
        html = client.get(page).content.decode()
        assert "Standalone soft-delete subject" not in html
        assert 'class="karni-help"' not in html
    gizmo = client.get(_url(Gizmo, "changelist")).content.decode()
    assert "Gizmo(id" not in gizmo


def test_help_shows_on_the_list_and_form_and_field_help_is_visible() -> None:
    widget = Widget.objects.create(name="Bolt")
    client = _client(_super())
    assert "Things we sell." in client.get(_url(Widget, "changelist")).content.decode()
    form = client.get(_url(Widget, "change", widget.pk)).content.decode()
    assert "Things we sell." in form
    assert "How many are on the shelf" in form  # under the field, not a tooltip
    assert 'class="karni-help"' not in client.get(_url(Gizmo, "changelist")).content.decode()


def test_an_admin_can_set_its_own_help() -> None:
    class Own(build_model_admin(Widget)):  # type: ignore[misc]
        karni_help = "Own words."

    assert Own(Widget, AdminSite()).model_help() == "Own words."


# -- the empty state -----------------------------------------------------------------


def test_an_empty_list_says_so_and_offers_add() -> None:
    html = _client(_super()).get(_url(Widget, "changelist")).content.decode()
    assert "No widgets yet." in html and "Add widget" in html
    Widget.objects.create(name="Bolt")
    html = _client(_super()).get(_url(Widget, "changelist")).content.decode()
    assert "No widgets yet." not in html


def test_a_search_with_no_match_is_not_the_empty_state() -> None:
    Widget.objects.create(name="Bolt")
    html = _client(_super()).get(_url(Widget, "changelist"), {"q": "zzz"}).content.decode()
    assert "No widgets yet." not in html


# -- technical fields and columns ----------------------------------------------------


def test_technical_fields_leave_the_form_for_a_collapsed_details_section() -> None:
    sink = KitchenSink.objects.create(name="One")
    model_admin = admin.site._registry[KitchenSink]
    request = _request(_super())
    fieldsets = model_admin.get_fieldsets(request, sink)
    *main, (title, details) = fieldsets
    assert str(title) == "Details" and details["classes"] == ["collapse"]
    assert {"created_at", "updated_at"} <= set(details["fields"])
    assert not {"id", "created_at", "updated_at", "deleted_at", "token"} & {
        n for _t, o in main for n in o["fields"]
    }
    assert all(str(t) != "Details" for t, _o in model_admin.get_fieldsets(request, None))


def test_details_can_be_switched_off() -> None:
    class Plain(build_model_admin(KitchenSink)):  # type: ignore[misc]
        karni_details = False

    sink = KitchenSink.objects.create(name="One")
    fieldsets = Plain(KitchenSink, AdminSite()).get_fieldsets(_request(_super()), sink)
    assert all(str(t) != "Details" for t, _o in fieldsets)


def test_the_list_has_about_six_columns_ending_with_the_updated_time() -> None:
    model_admin = admin.site._registry[KitchenSink]
    columns = model_admin.get_list_display(_request(_super()))
    named = [c for c in columns if isinstance(c, str)]
    assert named[0] == "name" and named[-1] == "updated_at" and len(named) <= 6


def test_the_actions_column_can_be_turned_off() -> None:
    class Quiet(build_model_admin(Widget)):  # type: ignore[misc]
        karni_row_actions = False

    columns = Quiet(Widget, AdminSite()).get_list_display(_request(_super()))
    assert all(isinstance(c, str) for c in columns)


def test_the_guide_links_only_to_screens_the_user_may_open() -> None:
    html = _client(_staff("viewer@example.com", "viewer")).get("/admin/").content.decode()
    assert "Set roles" in html and "karni_accounts/role" not in html
    assert "karni_accounts/role" in _client(_super()).get("/admin/").content.decode()
