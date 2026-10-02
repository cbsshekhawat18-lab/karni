"""``AdminMeta.inline_on`` → generated inlines on the parent admin."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from django.urls import reverse
from unfold.admin import TabularInline

from karni.admin.inlines import build_inline, collect_inlines
from tests.adminapp.models import KitchenSink, Note


class TestCollectInlines:
    def test_maps_parents_to_declared_children(self) -> None:
        mapping = collect_inlines([KitchenSink, Note])
        assert mapping == {KitchenSink: [(Note, "kitchen")]}

    def test_models_without_a_declaration_are_ignored(self) -> None:
        assert collect_inlines([KitchenSink]) == {}

    def test_a_list_of_fk_names_is_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = type("AdminMeta", (), {"inline_on": ["kitchen"]})
        monkeypatch.setattr(Note, "AdminMeta", meta)
        assert collect_inlines([Note]) == {KitchenSink: [(Note, "kitchen")]}

    def test_an_unknown_field_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = type("AdminMeta", (), {"inline_on": "missing"})
        monkeypatch.setattr(Note, "AdminMeta", meta)
        with pytest.raises(ImproperlyConfigured, match="missing"):
            collect_inlines([Note])

    def test_a_non_fk_field_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = type("AdminMeta", (), {"inline_on": "title"})
        monkeypatch.setattr(Note, "AdminMeta", meta)
        with pytest.raises(ImproperlyConfigured, match="ForeignKey"):
            collect_inlines([Note])


class TestBuildInline:
    def test_builds_an_unfold_tabular_inline(self) -> None:
        inline = build_inline(Note, "kitchen")
        assert issubclass(inline, TabularInline)
        assert inline.model is Note
        assert inline.fk_name == "kitchen"
        assert inline.extra == 0
        assert inline.show_change_link is True

    def test_password_named_fields_are_excluded_from_the_inline_form(self) -> None:
        from tests.adminapp.models import ApiCredential

        inline = build_inline(ApiCredential, "label")  # fk_name unused here
        assert inline.exclude == ["api_password"]


class TestRegistration:
    def test_parent_admin_carries_the_generated_inline(self, site: admin.AdminSite) -> None:
        (inline,) = site._registry[KitchenSink].inlines
        assert issubclass(inline, TabularInline)
        assert inline.model is Note
        assert inline.fk_name == "kitchen"

    def test_the_child_stays_registered_on_its_own(self, site: admin.AdminSite) -> None:
        assert site.is_registered(Note)
        assert type(site._registry[Note])._karni_generated

    @pytest.mark.django_db
    def test_the_change_form_renders_the_inline(self, admin_client: Client) -> None:
        sink = KitchenSink.objects.create(name="Parent")
        Note.objects.create(kitchen=sink, title="Inlined note")
        response = admin_client.get(reverse("admin:adminapp_kitchensink_change", args=[sink.pk]))
        assert response.status_code == 200
        assert b"Inlined note" in response.content

    @pytest.mark.django_db
    def test_a_soft_delete_child_inline_shows_alive_rows_only(self, admin_client: Client) -> None:
        # Documented scope note: the inline formset uses the child's default
        # manager, so soft-deleted rows stay out of the parent's change form.
        sink = KitchenSink.objects.create(name="Parent")
        Note.objects.create(kitchen=sink, title="Alive note")
        dead = Note.objects.create(kitchen=sink, title="Dead note")
        dead.delete()
        response = admin_client.get(reverse("admin:adminapp_kitchensink_change", args=[sink.pk]))
        assert response.status_code == 200
        assert b"Alive note" in response.content
        assert b"Dead note" not in response.content
