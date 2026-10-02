"""The pure derivation rules in :mod:`karni.admin.derive`.

Every assertion here runs against the real models in ``tests.adminapp`` —
no database needed; the rules only read ``_meta``.
"""

from __future__ import annotations

from django.contrib import admin
from django.test import override_settings

from karni.admin.derive import (
    admin_meta,
    derive_autocomplete_fields,
    derive_date_hierarchy,
    derive_list_display,
    derive_list_filter,
    derive_list_select_related,
    derive_readonly_fields,
    derive_search_fields,
    is_password_field,
    password_field_names,
)
from karni.admin.soft_delete import SoftDeleteListFilter
from tests.adminapp.models import (
    ApiCredential,
    Bot,
    Category,
    Citation,
    Hidden,
    KitchenSink,
    Memo,
    Metric,
    Note,
    Reading,
    Tuned,
)


class TestListDisplay:
    def test_scalarish_fields_in_declaration_order_capped_at_six(self) -> None:
        # char, slug, email and url are all CharField family; blurb (Text)
        # never qualifies; the cap (6) truncates everything after price.
        assert derive_list_display(KitchenSink) == [
            "name",
            "slug",
            "email",
            "url",
            "count",
            "price",
        ]

    def test_text_json_file_image_duration_uuid_and_m2m_never_qualify(self) -> None:
        with override_settings(KARNI_ADMIN_LIST_DISPLAY_MAX=100):
            display = derive_list_display(KitchenSink)
        # Everything scalar-ish made it in under the raised cap...
        assert display == [
            "name",
            "slug",
            "email",
            "url",
            "count",
            "price",
            "rating",
            "featured",
            "published_on",
            "released_at",
            "status",
            "category",
        ]
        # ...and the excluded shapes are demonstrably absent.
        for name in ("blurb", "payload", "attachment", "cover", "runtime", "token", "tags"):
            assert name not in display

    @override_settings(KARNI_ADMIN_LIST_DISPLAY_MAX=3)
    def test_cap_is_read_from_settings_per_call(self) -> None:
        assert derive_list_display(KitchenSink) == ["name", "slug", "email"]

    def test_falls_back_to_str_when_nothing_qualifies(self) -> None:
        # Hidden has only audit fields and a TextField.
        assert derive_list_display(Hidden) == ["__str__"]

    def test_audit_fields_are_skipped(self) -> None:
        display = derive_list_display(Note)
        assert display == ["title", "kitchen"]
        for name in ("id", "created_at", "updated_at", "deleted_at"):
            assert name not in display

    def test_password_named_fields_are_skipped(self) -> None:
        assert "api_password" not in derive_list_display(ApiCredential)
        assert "password" not in derive_list_display(Bot)


class TestListFilter:
    def test_booleans_choices_fks_then_dates(self) -> None:
        assert derive_list_filter(KitchenSink) == [
            "featured",
            "status",
            ("category", admin.RelatedOnlyFieldListFilter),
            "published_on",
            "released_at",
        ]

    @override_settings(KARNI_ADMIN_LIST_FILTER_MAX=0)
    def test_soft_delete_filter_is_not_counted_against_the_cap(self) -> None:
        # A zero cap drops every derived entry (Memo's choices field), but
        # the soft-delete filter is prepended regardless.
        assert derive_list_filter(Memo) == [SoftDeleteListFilter]

    def test_soft_delete_models_get_the_deleted_filter_first(self) -> None:
        assert derive_list_filter(Note) == [
            SoftDeleteListFilter,
            ("kitchen", admin.RelatedOnlyFieldListFilter),
        ]
        assert derive_list_filter(KitchenSink)[0] is not SoftDeleteListFilter


class TestSearchFields:
    def test_charish_and_text_fields_without_choices(self) -> None:
        # Slug/Email/URL are CharFields; status has choices; audit and
        # password-named fields are skipped.
        assert derive_search_fields(KitchenSink) == ["name", "slug", "email", "url", "blurb"]
        assert derive_search_fields(Note) == ["title", "body"]

    def test_password_named_fields_are_skipped(self) -> None:
        assert derive_search_fields(ApiCredential) == ["label"]
        assert derive_search_fields(Bot) == ["name"]

    def test_unsearchable_models_derive_an_empty_list(self) -> None:
        assert derive_search_fields(Metric) == []

    @override_settings(KARNI_ADMIN_SEARCH_MAX=2)
    def test_cap_is_read_from_settings_per_call(self) -> None:
        assert derive_search_fields(KitchenSink) == ["name", "slug"]


class TestDateHierarchy:
    def test_first_declared_non_audit_date_field(self) -> None:
        assert derive_date_hierarchy(KitchenSink) == "published_on"

    def test_falls_back_to_created_at(self) -> None:
        assert derive_date_hierarchy(Category) == "created_at"
        assert derive_date_hierarchy(Note) == "created_at"

    def test_none_without_any_date_field(self) -> None:
        assert derive_date_hierarchy(Metric) is None


class TestReadonlyFields:
    def test_audit_fields_present_on_the_model(self) -> None:
        assert derive_readonly_fields(KitchenSink) == ("id", "created_at", "updated_at")
        assert derive_readonly_fields(Note) == (
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
        )

    def test_only_audit_names_present_on_the_model_are_listed(self) -> None:
        # Metric has no timestamps; only its auto pk matches an audit name,
        # so that is all the rule may return.
        assert derive_readonly_fields(Metric) == ("id",)


class TestListSelectRelated:
    def test_fks_present_in_the_derived_display(self) -> None:
        assert derive_list_select_related(Note) == ("kitchen",)
        assert derive_list_select_related(Citation) == ("note",)
        # category is capped out of KitchenSink's derived list_display.
        assert derive_list_select_related(KitchenSink) == ()

    def test_respects_an_explicit_display(self) -> None:
        assert derive_list_select_related(KitchenSink, ["name", "category"]) == ("category",)
        assert derive_list_select_related(KitchenSink, ["name"]) == ()


class TestAutocompleteFields:
    def test_fk_and_m2m_relations_with_searchable_registered_targets(
        self, site: admin.AdminSite
    ) -> None:
        assert derive_autocomplete_fields(KitchenSink, site) == ["category", "tags"]
        assert derive_autocomplete_fields(Citation, site) == ["note"]

    def test_unsearchable_target_keeps_the_default_widget(self, site: admin.AdminSite) -> None:
        assert derive_autocomplete_fields(Reading, site) == []

    def test_unregistered_target_keeps_the_default_widget(self) -> None:
        empty_site = admin.AdminSite(name="karni-empty")
        assert derive_autocomplete_fields(KitchenSink, empty_site) == []


class TestPasswordFields:
    def test_substring_match_on_the_field_name(self) -> None:
        (field,) = [f for f in ApiCredential._meta.fields if f.name == "api_password"]
        assert is_password_field(field)
        assert password_field_names(ApiCredential) == ("api_password",)
        assert password_field_names(Bot) == ("password",)
        assert password_field_names(KitchenSink) == ()


class TestAdminMeta:
    def test_returns_the_inner_class(self) -> None:
        meta = admin_meta(Tuned)
        assert meta is not None
        assert meta.list_display == ["number", "total"]

    def test_none_without_a_declaration(self) -> None:
        assert admin_meta(KitchenSink) is None
