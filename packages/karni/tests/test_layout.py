"""Wide models (experimental): MarkdownField, field groups, column sets and their budgets.

A 120-field product (``tests.wideapp``) with twelve markdown sections, five
field groups and three column sets: the field's schema format, search over a
markdown field, the OpenAPI extensions, the admin's fieldsets, the
``karni check`` rule (E550 to E553), and the payload budgets of a list page
and a detail. The suite runs with either key type (``KARNI_TEST_PK``).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core import checks
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from karni.admin.base import build_model_admin
from karni.checks import check_layouts
from karni.errorcodes import KarniError
from karni.fields import MarkdownField
from karni.layout import REST_GROUP, column_sets, default_column_set, field_groups, fieldsets
from karni.testing import assert_schema_snapshot
from karni.testing.schema import generate_schema
from tests.testapp.models import TEST_PK
from tests.wideapp.models import SECTIONS, Product, numbered
from tests.wideapp.sample import make_products

WIDE = override_settings(
    ROOT_URLCONF="tests.wideapp.urls", KARNI_API_ROUTER="tests.wideapp.urls.get_router"
)
SNAPSHOT = Path(__file__).parent / "api" / "fixtures" / "schema.wideapp.json"

#: The payload budgets, in bytes, of the 120-field product (every field filled,
#: twelve markdown sections of about 400 characters each). Measured on
#: 2026-10-31: a list page of 25 rows 181,037 bytes and a detail 7,224 with
#: UUID keys, 179,203 and 7,150 with integer keys.
LIST_PAGE_BUDGET = 200_000
DETAIL_BUDGET = 8_000


@pytest.fixture
def declare(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Set one ``Product.Karni`` option for one test."""

    def apply(name: str, value: Any) -> None:
        monkeypatch.setattr(Product.Karni, name, value, raising=False)

    yield apply


def _list_operation(schema: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = schema["paths"]["/api/products/"]["get"]
    return operation


# MarkdownField ---------------------------------------------------------------


def test_a_markdown_field_is_a_text_column_with_a_public_migration_path() -> None:
    field = Product._meta.get_field("overview")
    assert isinstance(field, MarkdownField)
    assert field.get_internal_type() == "TextField"
    _name, path, _args, kwargs = field.deconstruct()
    assert path == "karni.fields.MarkdownField"
    assert kwargs == {"blank": True}
    assert field.karni_column().startswith("MarkdownField: text")


@pytest.mark.django_db
@WIDE
def test_its_schema_says_format_markdown_on_both_sides() -> None:
    components = generate_schema("tests.wideapp.urls")["components"]["schemas"]
    for name in ("WideappProduct", "WideappProductRequest", "PatchedWideappProductRequest"):
        prop = components[name]["properties"]["overview"]
        # blank=True: drf-spectacular adds "" as a second member of a formatted string.
        assert prop["oneOf"][0] == {"type": "string", "format": "markdown"}, name
        assert prop["oneOf"][1] == {"type": "string", "maxLength": 0}, name
    # A plain TextField keeps no format.
    assert "format" not in components["WideappProduct"]["properties"]["label_01"]


@pytest.mark.django_db
@WIDE
def test_a_required_markdown_field_is_one_formatted_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Product._meta.get_field("faq"), "blank", False)
    prop = generate_schema("tests.wideapp.urls")["components"]["schemas"]["WideappProduct"][
        "properties"
    ]["faq"]
    assert prop == {"type": "string", "format": "markdown"}


@pytest.mark.django_db
@WIDE
def test_the_list_search_finds_text_inside_a_markdown_section() -> None:
    rows = make_products(3)
    rows[1].overview = "## Overview\n\nThe only one made of **walnut**."
    rows[1].save()
    response = APIClient().get("/api/products/", {"search": "walnut"})
    assert response.status_code == 200
    assert [row["name"] for row in response.json()["results"]] == ["Product 001"]
    # The API returns the markdown source as written: rendering is the client's.
    assert response.json()["results"][0]["overview"].startswith("## Overview")


def test_seeds_and_factories_write_markdown() -> None:
    from karni.testing.values import ValueInference

    value = ValueInference().value(Product, Product._meta.get_field("care"))
    assert value.startswith("## ") and "\n\n- " in value


# field groups and column sets --------------------------------------------------


def test_the_declaration_is_read_in_order() -> None:
    groups = field_groups(Product)
    assert [group.label for group in groups] == [
        "Overview",
        "Specifications",
        "Financials",
        "Content",
        "Measurements",
    ]
    assert groups[0].fields == ("name", "sku", "brand", "status", "overview", "features")
    sets = column_sets(Product)
    assert [(found.name, found.label) for found in sets] == [
        ("default", "Default"),
        ("financial", "Financial"),
        ("logistics", "Logistics"),
    ]
    assert default_column_set(sets) == "default"
    assert default_column_set(sets[1:]) == "financial"  # no "default": the first set


@pytest.mark.django_db
@WIDE
def test_the_schema_publishes_both_on_the_list_operation() -> None:
    schema = generate_schema("tests.wideapp.urls")
    operation = _list_operation(schema)
    groups = operation["x-karni-field-groups"]
    assert groups["layout"] == "sections"
    assert [group["label"] for group in groups["groups"]] == [
        "Overview",
        "Specifications",
        "Financials",
        "Content",
        "Measurements",
    ]
    assert groups["groups"][2]["fields"] == [*numbered("price", 6), *numbered("rate", 4)]
    sets = operation["x-karni-column-sets"]
    assert sets["default"] == "default"
    assert sets["sets"][0] == {
        "name": "default",
        "label": "Default",
        "columns": ["name", "sku", "brand", "status", "price_01"],
    }
    # Only the list operation carries them, and a model without a declaration has none.
    assert "x-karni-field-groups" not in schema["paths"]["/api/products/{id}/"]["get"]
    assert "x-karni-column-sets" not in schema["paths"]["/api/brands/"]["get"]


@pytest.mark.django_db
@WIDE
def test_tabs_are_a_per_model_choice(declare: Any) -> None:
    declare("field_group_layout", "tabs")
    groups = _list_operation(generate_schema("tests.wideapp.urls"))["x-karni-field-groups"]
    assert groups["layout"] == "tabs"


@pytest.mark.django_db
@WIDE
def test_a_field_the_role_may_not_read_is_never_named(declare: Any) -> None:
    declare("field_roles", {"price_01": ["finance"], "faq": ["finance"]})
    operation = _list_operation(generate_schema("tests.wideapp.urls"))
    names = {
        name for group in operation["x-karni-field-groups"]["groups"] for name in group["fields"]
    }
    assert "price_01" not in names and "faq" not in names
    for found in operation["x-karni-column-sets"]["sets"]:
        assert "price_01" not in found["columns"]


@pytest.mark.django_db
@WIDE
def test_a_set_left_empty_is_dropped_and_the_default_moves(declare: Any) -> None:
    declare("field_roles", {"name": ["staff"], "sku": ["staff"], "brand": ["staff"]})
    declare("column_sets", {"default": ["name", "sku", "brand"], "financial": ["price_01"]})
    sets = _list_operation(generate_schema("tests.wideapp.urls"))["x-karni-column-sets"]
    assert sets == {
        "default": "financial",
        "sets": [{"name": "financial", "label": "Financial", "columns": ["price_01"]}],
    }


@pytest.mark.django_db
@WIDE
def test_a_malformed_declaration_never_breaks_the_schema(declare: Any) -> None:
    declare("field_groups", {"Overview": ["nmae"]})
    declare("column_sets", ["name"])
    operation = _list_operation(generate_schema("tests.wideapp.urls"))
    assert "x-karni-field-groups" not in operation
    assert "x-karni-column-sets" not in operation
    assert operation["x-karni-resource"] == "products"


# the admin -----------------------------------------------------------------------


def _admin_request() -> Any:
    request = RequestFactory().get("/")
    request.user = get_user_model()(email="admin@example.com", is_staff=True, is_superuser=True)
    return request


@pytest.mark.django_db
def test_the_admin_shows_each_group_as_a_fieldset_and_the_rest_last() -> None:
    model_admin = build_model_admin(Product)(Product, AdminSite())
    found = model_admin.get_fieldsets(_admin_request())
    titles = [title for title, _options in found]
    assert titles == [
        "Overview",
        "Specifications",
        "Financials",
        "Content",
        "Measurements",
        REST_GROUP,
    ]
    assert found[0][1]["fields"] == ["name", "sku", "brand", "status", "overview", "features"]
    rest = found[-1][1]["fields"]
    assert "grade" in rest and "label_01" in rest and "flag_15" in rest
    assert "overview" not in rest
    shown = [name for _title, options in found for name in options["fields"]]
    assert len(shown) == len(set(shown))  # each field once


@pytest.mark.django_db
def test_the_admins_own_fieldsets_win() -> None:
    cls = build_model_admin(Product)
    cls.fieldsets = [("Everything", {"fields": ["name", "sku"]})]
    assert cls(Product, AdminSite()).get_fieldsets(_admin_request()) == [
        ("Everything", {"fields": ["name", "sku"]})
    ]


def test_fieldsets_keep_only_the_forms_fields() -> None:
    assert fieldsets(Product, ["name", "faq", "grade"]) == [
        ("Overview", {"fields": ["name"]}),
        ("Content", {"fields": ["faq"]}),
        (REST_GROUP, {"fields": ["grade"]}),
    ]
    from tests.wideapp.models import Brand

    assert fieldsets(Brand, ["name"]) is None  # no groups: Django's single fieldset


# karni check -----------------------------------------------------------------------


def _layout_messages() -> list[checks.CheckMessage]:
    return check_layouts([apps.get_app_config("wideapp")])


def test_karni_check_is_quiet_for_valid_declarations() -> None:
    assert check_layouts() == []


def test_a_group_naming_an_unknown_field_fails_with_the_model_group_and_field(
    declare: Any,
) -> None:
    declare("field_groups", {"Overview": ["name", "nmae"]})
    messages = _layout_messages()
    assert [m.id for m in messages] == ["karni.E551"]
    assert messages[0].level == checks.ERROR and messages[0].obj is Product
    assert "Product.Karni.field_groups: group 'Overview' names 'nmae'" in messages[0].msg


def test_a_column_set_naming_an_unknown_field_fails(declare: Any) -> None:
    declare("column_sets", {"financial": ["name", "prcie_01"]})
    messages = _layout_messages()
    assert [m.id for m in messages] == ["karni.E551"]
    assert "Product.Karni.column_sets: set 'financial' names 'prcie_01'" in messages[0].msg


def test_a_field_in_two_groups_fails_naming_both(declare: Any) -> None:
    declare("field_groups", {"Overview": ["name", "sku"], "Codes": ["sku"]})
    messages = _layout_messages()
    assert [m.id for m in messages] == ["karni.E552"]
    assert "'sku' is in group 'Overview' and in group 'Codes'" in messages[0].msg
    with pytest.raises(KarniError) as caught:
        field_groups(Product)
    assert caught.value.code == "E552"


@pytest.mark.parametrize(
    ("name", "value", "code"),
    [
        ("field_groups", ["name"], "E550"),
        ("field_groups", {"": ["name"]}, "E550"),
        ("field_groups", {"Overview": []}, "E550"),
        ("field_groups", {"Overview": "name"}, "E550"),
        ("field_group_layout", "accordion", "E550"),
        ("column_sets", {}, "E553"),
        ("column_sets", {"default": []}, "E553"),
        ("column_sets", {"default": ["name", "name"]}, "E553"),
    ],
)
def test_a_malformed_declaration_fails(declare: Any, name: str, value: Any, code: str) -> None:
    declare(name, value)
    assert [m.id for m in _layout_messages()] == [f"karni.{code}"]


def test_every_problem_is_reported_not_only_the_first(declare: Any) -> None:
    declare("field_groups", {"Overview": ["nmae", "sku"], "Codes": ["sku", "sku_2"]})
    declare("column_sets", {"default": ["nmae"]})
    assert sorted(m.id for m in _layout_messages()) == [
        "karni.E551",
        "karni.E551",
        "karni.E551",
        "karni.E552",
    ]


# the budgets ----------------------------------------------------------------------


@pytest.mark.django_db
@WIDE
def test_a_list_page_and_a_detail_stay_within_their_payload_budgets() -> None:
    rows = make_products(25)
    client = APIClient()
    page = client.get("/api/products/", {"page_size": 25})
    assert page.status_code == 200
    assert len(page.json()["results"]) == 25
    detail = client.get(f"/api/products/{rows[0].pk}/")
    assert detail.status_code == 200
    assert len(detail.json()) == 125  # the 120 fields and BaseModel's five but deleted_at
    assert all(detail.json()[name] for name in SECTIONS)
    assert len(page.content) <= LIST_PAGE_BUDGET, len(page.content)
    assert len(detail.content) <= DETAIL_BUDGET, len(detail.content)


# the UI's fixture ------------------------------------------------------------------


@pytest.mark.django_db
@WIDE
@pytest.mark.skipif(TEST_PK != "uuid", reason="the UI renders the UUID-keyed document")
def test_the_wide_schema_snapshot_is_current() -> None:
    assert_schema_snapshot(
        SNAPSHOT,
        urlconf="tests.wideapp.urls",
        hint="Then copy the file to packages/karni-ui/tests/fixtures/ (the UI budget tests).",
    )
