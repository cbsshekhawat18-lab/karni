"""``karni.facts`` and ``manage.py karni_facts`` (experimental): the project as JSON facts."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.test import override_settings

from karni.facts import count_rows, project_apps, project_facts


@override_settings(KARNI_FACTS_APPS=["testapp"])
def test_facts_describe_models_viewsets_and_settings() -> None:
    facts = project_facts()
    assert json.loads(json.dumps(facts)) == facts  # JSON-safe throughout
    assert [config.label for config in project_apps()] == ["testapp"]
    (testapp,) = facts["apps"]
    models = {model["name"]: model for model in testapp["models"]}
    event = models["Event"]
    assert event["base_model"] is True
    names = [field["name"] for field in event["fields"]]
    assert "id" not in names and "created_by" not in names  # BaseModel's own fields
    venue = next(field for field in event["fields"] if field.get("related") == "testapp.Venue")
    assert venue["class"] == "django.db.models.fields.related.ForeignKey"
    assert venue["kwargs"]["on_delete"].startswith("django.db.models.deletion.")
    assert models["Stamp"]["base_model"] is False
    routes = {viewset["route"]: viewset for viewset in facts["viewsets"]}
    assert any(viewset["model"] == "testapp.Event" for viewset in routes.values())
    assert all("access" in viewset for viewset in routes.values())
    assert set(facts["settings"]) >= {"KARNI_ROLES", "KARNI_2FA", "KARNI_TERMS"}
    assert facts["user_model"] == "karni_accounts.User"


@override_settings(KARNI_FACTS_APPS=["testapp"])
def test_karni_facts_prints_the_facts() -> None:
    out = StringIO()
    call_command("karni_facts", stdout=out)
    printed = json.loads(out.getvalue())
    assert printed["apps"][0]["label"] == "testapp"


@override_settings(KARNI_FACTS_APPS=["testapp", "externalapp"])
def test_facts_name_the_key_type_the_table_and_the_databases() -> None:
    facts = project_facts()
    models = {model["label"]: model for app in facts["apps"] for model in app["models"]}
    assert models["testapp.Event"]["pk"] in ("uuid", "bigint")  # ApiBase follows the suite
    part = models["testapp.Part"]
    assert part["pk"] == "bigint" and part["base_model"] is True  # BigIntBaseModel
    assert "id" not in [field["name"] for field in part["fields"]]
    stamp = models["testapp.Stamp"]  # UUIDModel alone: its key is left out, like BaseModel's
    assert stamp["pk"] == "uuid" and stamp["base_model"] is False
    assert [field["name"] for field in stamp["fields"]] == ["value"]
    stock = models["externalapp.Stock"]
    assert stock["managed"] is False and stock["db_table"] == "wh_stock"
    assert stock["karni"]["external"] is True and stock["karni"]["database"] == "second"
    assert stock["pk"] is None and "sku" in [field["name"] for field in stock["fields"]]
    assert {"default", "second"} <= set(facts["databases"])
    assert "KARNI_PK" in facts["settings"]


@override_settings(KARNI_FACTS_APPS=["testapp"])
def test_facts_name_the_tree_kind_and_leave_the_tree_fields_out() -> None:
    facts = project_facts()
    models = {model["label"]: model for app in facts["apps"] for model in app["models"]}
    region, category = models["testapp.Region"], models["testapp.Category"]
    assert region["tree"] == "tree" and category["tree"] == "ordered"
    assert models["testapp.Event"]["tree"] is None and models["testapp.Stamp"]["tree"] is None
    assert [field["name"] for field in region["fields"]] == ["name", "code"]
    assert [field["name"] for field in category["fields"]] == ["name"]
    product = [field["name"] for field in models["testapp.Product"]["fields"]]
    assert product == ["name", "category", "regions"]  # a relation to a tree is a plain field
    assert models["testapp.Product"]["taxonomies"] == {}


@override_settings(KARNI_FACTS_APPS=["taxoapp"])
def test_facts_name_the_taxonomies_and_leave_the_generated_fields_out() -> None:
    facts = project_facts()
    models = {model["label"]: model for app in facts["apps"] for model in app["models"]}
    product, supplier = models["taxoapp.Product"], models["taxoapp.Supplier"]
    assert product["taxonomies"] == {
        "region": {"to": "taxoapp.Region", "generated": True},
        "category": {"to": "taxoapp.Category", "generated": True},
    }
    assert [field["name"] for field in product["fields"]] == ["name", "price"]
    assert supplier["taxonomies"] == {"region": {"to": "taxoapp.Region", "generated": False}}
    assert [field["name"] for field in supplier["fields"]] == ["name", "region"]  # adopted


@pytest.mark.django_db
def test_count_rows_counts_each_kind_through_the_base_manager() -> None:
    from tests.testapp.models import Book, Label, Part, Shelf

    shelf = Shelf.objects.create(name="Main")
    long_one = Book.objects.create(shelf=shelf, title="A very long title indeed")
    Book.objects.create(shelf=shelf, title="Short")
    long_one.labels.add(Label.objects.create(name="x"), Label.objects.create(name="y"))
    Book.objects.get(title="Short").delete()  # soft-deleted rows are data too
    Part.objects.create(number="1")
    Part.objects.create(number="2", label="has one")
    found = count_rows(
        [
            {"model": "testapp.Book"},
            {"model": "testapp.Book", "field": "title", "kind": "longer", "arg": 10},
            {"model": "testapp.Book", "field": "title", "kind": "in", "arg": ["Short"]},
            {"model": "testapp.Book", "field": "labels", "kind": "set"},
            {"model": "testapp.Part", "field": "label", "kind": "set"},
            {"model": "testapp.Part", "field": "label", "kind": "empty"},
            {"model": "testapp.Missing"},
            {"model": "testapp.Book", "field": "nope", "kind": "set"},
            {"model": "testapp.Book", "field": "title", "kind": "sideways"},
        ]
    )
    assert found == {"rows": [2, 1, 1, 2, 1, 1, None, None, None], "unreachable": {}}


@pytest.mark.django_db
def test_karni_rows_prints_the_counts_and_refuses_bad_input() -> None:
    out = StringIO()
    call_command("karni_rows", '[{"model": "testapp.Shelf"}]', stdout=out)
    assert json.loads(out.getvalue()) == {"rows": [0], "unreachable": {}}
    for bad in ('{"model": "testapp.Shelf"}', "[nope"):
        out = StringIO()
        call_command("karni_rows", bad, stdout=out)
        answer = json.loads(out.getvalue())
        assert answer["rows"] == [] and answer["error"].startswith("The requests are not")


def test_count_rows_reports_a_database_that_does_not_answer(
    tmp_path: Any, django_db_blocker: Any
) -> None:
    from django.db import connections

    connection = connections["second"]
    saved = dict(connection.settings_dict)
    if connection.vendor == "sqlite":
        connection.settings_dict["NAME"] = str(tmp_path / "missing.sqlite3")
        expected = "does not exist yet"
    else:
        connection.close()
        connection.settings_dict["PORT"] = "1"  # nothing listens there
        expected = "OperationalError"
    try:
        with django_db_blocker.unblock():  # PostgreSQL: the refused connection is the test
            found = count_rows([{"model": "externalapp.Stock"}])
    finally:
        connection.close()
        connection.settings_dict.clear()
        connection.settings_dict.update(saved)
    assert found["rows"] == [None]
    assert expected in found["unreachable"]["second"]
    assert not (tmp_path / "missing.sqlite3").exists()  # counting never creates the file
