"""`KarniModelAdmin`, `build_model_admin` and the `AdminMeta` contract
(amendments C5/C6)."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory, override_settings

from karni.admin import autodiscover
from karni.admin.base import (
    KarniAdminMixin,
    KarniModelAdmin,
    build_model_admin,
    resolve_admin_base,
)
from karni.admin.soft_delete import SoftDeleteAdminMixin
from tests.adminapp.models import ApiCredential, Bot, KitchenSink, Ledger, Metric, Note, Tuned


@pytest.fixture
def scratch_site() -> admin.AdminSite:
    """A throwaway site so instantiating admins never touches the real registry."""
    return admin.AdminSite(name="karni-scratch")


class TestAdminMetaApplication:
    """The registered Tuned admin mirrors its ``AdminMeta`` exactly."""

    def test_explicit_attributes_beat_derivation(self, site: admin.AdminSite) -> None:
        model_admin = site._registry[Tuned]
        assert list(model_admin.list_display) == ["number", "total"]
        assert list(model_admin.list_filter) == ["status"]
        assert list(model_admin.search_fields) == ["number"]
        assert model_admin.date_hierarchy == "issued_at"
        assert list(model_admin.ordering or []) == ["-issued_at"]

    def test_extra_is_applied_last(self, site: admin.AdminSite) -> None:
        assert site._registry[Tuned].list_per_page == 10

    def test_read_only_extends_the_derived_readonly_fields(self, site: admin.AdminSite) -> None:
        assert list(site._registry[Tuned].readonly_fields) == [
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "created_by",
            "updated_by",
            "total",
        ]

    def test_underived_attributes_are_still_filled_in(self, site: admin.AdminSite) -> None:
        # AdminMeta pins five attributes; list_select_related is derived from
        # the *explicit* list_display (no FKs there → stays off).
        assert site._registry[Tuned].list_select_related is False


class TestBuildModelAdmin:
    def test_marks_generated_classes(self) -> None:
        cls = build_model_admin(KitchenSink)
        assert cls._karni_generated
        assert cls._karni_autocomplete_managed
        assert issubclass(cls, KarniModelAdmin)

    def test_soft_delete_models_get_the_mixin_in_front(self) -> None:
        # A standalone SoftDeleteModel (Note) and a BaseModel (KitchenSink —
        # every BaseModel is soft-deletable) alike.
        for model in (Note, KitchenSink):
            cls = build_model_admin(model)
            assert issubclass(cls, SoftDeleteAdminMixin), model
            assert cls.__mro__.index(SoftDeleteAdminMixin) < cls.__mro__.index(KarniModelAdmin)

    def test_models_without_soft_delete_get_no_mixin(self) -> None:
        # Ledger composes every Karni mixin except SoftDeleteModel.
        for model in (Ledger, Metric):
            cls = build_model_admin(model)
            assert issubclass(cls, KarniModelAdmin), model
            assert not issubclass(cls, SoftDeleteAdminMixin), model

    def test_inlines_are_attached(self) -> None:
        from karni.admin.inlines import build_inline

        inline = build_inline(Note, "kitchen")
        cls = build_model_admin(KitchenSink, inlines=[inline])
        assert cls.inlines == [inline]

    def test_extra_autocomplete_fields_disable_the_second_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        meta = type("AdminMeta", (), {"extra": {"autocomplete_fields": ["category"]}})
        monkeypatch.setattr(KitchenSink, "AdminMeta", meta, raising=False)
        cls = build_model_admin(KitchenSink)
        assert not cls._karni_autocomplete_managed
        assert cls.autocomplete_fields == ["category"]

    def test_explicit_none_date_hierarchy_disables_the_drilldown(
        self, monkeypatch: pytest.MonkeyPatch, scratch_site: admin.AdminSite
    ) -> None:
        meta = type("AdminMeta", (), {"date_hierarchy": None})
        monkeypatch.setattr(KitchenSink, "AdminMeta", meta, raising=False)
        model_admin = build_model_admin(KitchenSink)(KitchenSink, scratch_site)
        assert model_admin.date_hierarchy is None


class TestHandRegisteredDerivation:
    """``KarniModelAdmin`` derives at ``__init__`` even without the factory."""

    def test_stock_attributes_are_derived(self, scratch_site: admin.AdminSite) -> None:
        class PlainAdmin(KarniModelAdmin):
            pass

        model_admin = PlainAdmin(KitchenSink, scratch_site)
        assert list(model_admin.list_display) == [
            "name",
            "slug",
            "email",
            "url",
            "count",
            "price",
        ]
        assert list(model_admin.search_fields) == ["name", "slug", "email", "url", "blurb"]
        assert model_admin.date_hierarchy == "published_on"
        assert list(model_admin.readonly_fields) == [
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "created_by",
            "updated_by",
        ]
        # No FK in the derived display → nothing to select_related.
        assert model_admin.list_select_related is False

    def test_select_related_follows_fks_in_the_derived_display(
        self, scratch_site: admin.AdminSite
    ) -> None:
        class NoteAdmin(KarniModelAdmin):
            pass

        model_admin = NoteAdmin(Note, scratch_site)
        assert list(model_admin.list_display) == ["title", "kitchen"]
        assert list(model_admin.list_select_related) == ["kitchen"]

    def test_class_attributes_are_never_overwritten(self, scratch_site: admin.AdminSite) -> None:
        class PinnedAdmin(KarniModelAdmin):
            list_display = ("name",)
            search_fields = ("name",)

        model_admin = PinnedAdmin(KitchenSink, scratch_site)
        assert model_admin.list_display == ("name",)
        assert model_admin.search_fields == ("name",)
        assert model_admin.list_select_related is False

    def test_karni_explicit_pins_stock_looking_values(self, scratch_site: admin.AdminSite) -> None:
        class NoDrilldownAdmin(KarniModelAdmin):
            _karni_explicit = frozenset({"date_hierarchy"})

        model_admin = NoDrilldownAdmin(KitchenSink, scratch_site)
        assert model_admin.date_hierarchy is None

    def test_derive_hooks_are_overridable_per_subclass(self, scratch_site: admin.AdminSite) -> None:
        class HookAdmin(KarniModelAdmin):
            @classmethod
            def derive_search_fields(cls, model: Any) -> list[str]:
                return ["name"]

        model_admin = HookAdmin(KitchenSink, scratch_site)
        assert model_admin.search_fields == ["name"]


class TestPasswordFormExclusion:
    """Amendment C5: password-named fields stay out of derived forms."""

    def test_derived_forms_drop_password_named_fields(
        self, site: admin.AdminSite, rf: RequestFactory
    ) -> None:
        form = site._registry[ApiCredential].get_form(rf.get("/"))
        assert "label" in form.base_fields
        assert "api_password" not in form.base_fields

    def test_derived_user_model_form_drops_the_password_field(self, rf: RequestFactory) -> None:
        # The contract's user-model case: an AbstractBaseUser subclass opted
        # in via AdminMeta.register on a fresh AdminSite.
        fresh = admin.AdminSite(name="karni-user-form")
        autodiscover(site=fresh)
        form = fresh._registry[Bot].get_form(rf.get("/"))
        assert "name" in form.base_fields
        assert "password" not in form.base_fields

    def test_fields_declared_in_fieldsets_stay(
        self, scratch_site: admin.AdminSite, rf: RequestFactory
    ) -> None:
        # The KarniUserAdmin pattern: an admin that deliberately exposes a
        # password field keeps it.
        class DeclaredAdmin(KarniModelAdmin):
            fieldsets = ((None, {"fields": ("label", "api_password")}),)

        form = DeclaredAdmin(ApiCredential, scratch_site).get_form(rf.get("/"))
        assert "api_password" in form.base_fields

    def test_an_explicit_exclude_is_extended_not_replaced(
        self, scratch_site: admin.AdminSite, rf: RequestFactory
    ) -> None:
        class ExcludingAdmin(KarniModelAdmin):
            exclude = ("label",)

        form = ExcludingAdmin(ApiCredential, scratch_site).get_form(rf.get("/"))
        assert "label" not in form.base_fields
        assert "api_password" not in form.base_fields

    def test_models_without_password_fields_keep_the_default_exclude(
        self, site: admin.AdminSite, rf: RequestFactory
    ) -> None:
        assert site._registry[KitchenSink].get_exclude(rf.get("/")) is None


class TestAdminBaseResolution:
    """Amendment C6: ``KARNI_ADMIN_BASE`` is a dotted path resolved lazily."""

    def test_default_is_unfold(self) -> None:
        from unfold.admin import ModelAdmin as UnfoldModelAdmin

        assert resolve_admin_base() is UnfoldModelAdmin
        assert issubclass(KarniModelAdmin, UnfoldModelAdmin)
        assert issubclass(KarniModelAdmin, KarniAdminMixin)

    @override_settings(KARNI_ADMIN_BASE="django.contrib.admin.ModelAdmin")
    def test_any_model_admin_subclass_is_accepted(self) -> None:
        assert resolve_admin_base() is admin.ModelAdmin

    @override_settings(KARNI_ADMIN_BASE="no.such.module.Admin")
    def test_an_unimportable_path_fails_loudly(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="cannot be imported"):
            resolve_admin_base()

    @override_settings(KARNI_ADMIN_BASE="karni.models.BaseModel")
    def test_a_non_model_admin_class_is_rejected(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="ModelAdmin"):
            resolve_admin_base()
