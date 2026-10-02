"""Soft-delete awareness of derived admins (contract amendment C3).

Integration tests drive the real admin views through the test client (the
site mounted at ``admin/`` by ``tests/urls.py``); unit tests poke the
registered admin instances directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from karni.admin.soft_delete import SoftDeleteListFilter
from tests.admin.conftest import RequestForUser
from tests.adminapp.models import Citation, Memo, Note

pytestmark = pytest.mark.django_db

CHANGELIST_URL = reverse("admin:adminapp_note_changelist")


def _note(title: str, *, deleted: bool = False) -> Note:
    note = Note.objects.create(title=title)
    if deleted:
        note.delete()
    return note


def _changelist_pks(response: Any) -> set[str]:
    return {str(pk) for pk in response.context["cl"].queryset.values_list("pk", flat=True)}


class TestChangelistScoping:
    def test_defaults_to_alive_rows_only(self, admin_client: Client) -> None:
        alive = _note("Alive")
        dead = _note("Dead", deleted=True)
        response = admin_client.get(CHANGELIST_URL)
        assert response.status_code == 200
        assert _changelist_pks(response) == {str(alive.pk)}
        assert str(dead.pk) not in _changelist_pks(response)

    def test_deleted_value_shows_only_deleted_rows(self, admin_client: Client) -> None:
        _note("Alive")
        dead = _note("Dead", deleted=True)
        response = admin_client.get(CHANGELIST_URL, {"deleted": "deleted"})
        assert _changelist_pks(response) == {str(dead.pk)}

    def test_all_value_shows_everything(self, admin_client: Client) -> None:
        alive = _note("Alive")
        dead = _note("Dead", deleted=True)
        response = admin_client.get(CHANGELIST_URL, {"deleted": "all"})
        assert _changelist_pks(response) == {str(alive.pk), str(dead.pk)}

    def test_facets_report_counts_for_the_filter_choices(self, admin_client: Client) -> None:
        # Django 5.1 ShowFacets.ALLOW: ?_facets=True must not blow up and the
        # two non-default choices must carry their counts.
        _note("Alive")
        _note("Dead", deleted=True)
        response = admin_client.get(CHANGELIST_URL, {"_facets": "True"})
        assert response.status_code == 200
        changelist = response.context["cl"]
        spec = next(
            spec for spec in changelist.filter_specs if isinstance(spec, SoftDeleteListFilter)
        )
        displays = [str(choice["display"]) for choice in spec.choices(changelist)]
        assert displays == ["Not deleted", "Deleted (1)", "All (2)"]

    def test_change_form_opens_deleted_rows(self, admin_client: Client) -> None:
        dead = _note("Dead", deleted=True)
        url = reverse("admin:adminapp_note_change", args=[dead.pk])
        assert admin_client.get(url).status_code == 200

    def test_admin_queryset_sees_deleted_rows(
        self, site: admin.AdminSite, make_request: RequestForUser, admin_user: Any
    ) -> None:
        dead = _note("Dead", deleted=True)
        queryset = site._registry[Note].get_queryset(make_request(admin_user))
        assert dead in queryset

    def test_explicit_admin_meta_list_filter_still_gets_the_deleted_filter(
        self, site: admin.AdminSite, make_request: RequestForUser, admin_user: Any
    ) -> None:
        filters = site._registry[Memo].get_list_filter(make_request(admin_user))
        assert filters[0] is SoftDeleteListFilter
        assert "topic" in filters


class TestActions:
    def test_delete_selected_stays_and_is_soft(self, admin_client: Client) -> None:
        note = _note("Target")
        data = {"action": "delete_selected", helpers.ACTION_CHECKBOX_NAME: [str(note.pk)]}
        confirmation = admin_client.post(CHANGELIST_URL, data)
        assert confirmation.status_code == 200  # Django's stock confirmation page
        response = admin_client.post(CHANGELIST_URL, {**data, "post": "yes"})
        assert response.status_code == 302
        refreshed = Note.objects.without("soft_delete", reason="test").get(
            pk=note.pk
        )  # row still exists
        assert refreshed.deleted_at is not None

    def test_restore_selected_undeletes(self, admin_client: Client) -> None:
        note = _note("Target", deleted=True)
        untouched = _note("Alive")
        # Selected pks are intersected with the changelist queryset, so the
        # action must be posted from the view that shows deleted rows.
        response = admin_client.post(
            f"{CHANGELIST_URL}?deleted=all",
            {
                "action": "restore_selected",
                helpers.ACTION_CHECKBOX_NAME: [str(note.pk), str(untouched.pk)],
            },
        )
        assert response.status_code == 302
        assert Note.objects.filter(pk=note.pk).exists()

    def test_hard_delete_confirms_then_really_deletes_with_cascade(
        self, admin_client: Client
    ) -> None:
        note = _note("Target", deleted=True)
        citation = Citation.objects.create(note=note, label="Cascades too")
        url = f"{CHANGELIST_URL}?deleted=all"
        data = {
            "action": "hard_delete_selected",
            helpers.ACTION_CHECKBOX_NAME: [str(note.pk)],
        }
        confirmation = admin_client.post(url, data)
        assert confirmation.status_code == 200
        assert "karni_admin/hard_delete_selected_confirmation.html" in [
            template.name for template in confirmation.templates if template.name
        ]
        # The collector lists the cascade child on the confirmation page.
        assert b"Cascades too" in confirmation.content
        assert (
            Note.objects.without("soft_delete", reason="test").filter(pk=note.pk).exists()
        )  # nothing deleted yet

        response = admin_client.post(url, {**data, "post": "yes"})
        assert response.status_code == 302
        assert not Note.objects.without("soft_delete", reason="test").filter(pk=note.pk).exists()
        assert not Citation.objects.filter(pk=citation.pk).exists()

    def test_hard_delete_is_superuser_only(
        self,
        client: Client,
        django_user_model: Any,
        site: admin.AdminSite,
        make_request: RequestForUser,
        admin_user: Any,
    ) -> None:
        staff = django_user_model.objects.create_user(
            email="staff@example.com", password="a-strong-password-123", is_staff=True
        )
        staff.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="adminapp",
                codename__in=["view_note", "change_note", "delete_note"],
            )
        )
        model_admin = site._registry[Note]
        staff_actions = model_admin.get_actions(make_request(staff))
        assert "hard_delete_selected" not in staff_actions
        assert "restore_selected" in staff_actions
        assert "delete_selected" in staff_actions
        assert "hard_delete_selected" in model_admin.get_actions(make_request(admin_user))

        note = _note("Survivor")
        client.force_login(staff)
        response = client.post(
            CHANGELIST_URL,
            {
                "action": "hard_delete_selected",
                helpers.ACTION_CHECKBOX_NAME: [str(note.pk)],
            },
        )
        # An unavailable action bounces back to the changelist ("No action
        # selected.") and touches nothing.
        assert response.status_code == 302
        assert response.url == CHANGELIST_URL
        assert Note.objects.without("soft_delete", reason="test").filter(pk=note.pk).exists()


class TestAutocomplete:
    def test_responses_offer_alive_rows_only(self, admin_client: Client) -> None:
        alive = _note("Amber")
        dead = _note("Alder", deleted=True)
        response = admin_client.get(
            reverse("admin:autocomplete"),
            {
                "term": "a",
                "app_label": "adminapp",
                "model_name": "citation",
                "field_name": "note",
            },
        )
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()["results"]}
        assert str(alive.pk) in ids
        assert str(dead.pk) not in ids


class TestForeignKeyFormFields:
    def test_change_form_keeps_the_current_deleted_value(
        self, site: admin.AdminSite, make_request: RequestForUser, admin_user: Any
    ) -> None:
        dead = _note("Dead", deleted=True)
        other_dead = _note("Other", deleted=True)
        alive = _note("Alive")
        citation = Citation.objects.create(note=dead, label="Keeps its target")
        form_cls = site._registry[Citation].get_form(
            make_request(admin_user), citation, change=True
        )
        queryset = form_cls.base_fields["note"].queryset
        assert set(queryset) == {dead, alive}
        assert other_dead not in queryset
        # Re-saving the unchanged value validates (amendment C3).
        assert form_cls.base_fields["note"].clean(str(dead.pk)) == dead

    def test_add_forms_offer_alive_rows_only(
        self, site: admin.AdminSite, make_request: RequestForUser, admin_user: Any
    ) -> None:
        dead = _note("Dead", deleted=True)
        alive = _note("Alive")
        form_cls = site._registry[Citation].get_form(make_request(admin_user))
        queryset = form_cls.base_fields["note"].queryset
        assert alive in queryset
        assert dead not in queryset
