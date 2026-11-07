"""``class Karni: taxonomies`` on the model: the generated field, migrations, queries and checks."""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps
from django.db import connection, models
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.questioner import MigrationQuestioner
from django.db.migrations.state import ModelState, ProjectState
from django.db.migrations.writer import MigrationWriter
from django.test.utils import CaptureQueriesContext, isolate_apps

from karni.checks import check_taxonomies
from karni.exceptions import KarniImproperlyConfigured
from karni.models import BaseModel, TreeModel
from karni.taxonomy import (
    facet_counts,
    facets,
    get_taxonomy,
    tagged_rows,
    tagging,
    taxonomies,
)
from tests.taxoapp.models import Category, Product, Region, Supplier
from tests.taxonomy.conftest import Catalog

# the field


def test_each_key_is_a_generated_many_to_many_to_its_tree() -> None:
    found = taxonomies(Product)
    assert list(found) == ["region", "category"]
    region = found["region"]
    assert region.generated is True and region.tree is Region
    assert found["category"].tree is Category
    field = Product._meta.get_field("region")
    assert isinstance(field, models.ManyToManyField)
    assert field.blank is True and field.remote_field.hidden
    assert str(field.verbose_name) == "region"
    assert (region.row_field, region.node_field) == ("product", "region")
    assert region.descendants_param == "region_descendants"
    assert not hasattr(Region, "product_set")  # no reverse accessor to clash


def test_a_declared_many_to_many_is_adopted() -> None:
    region = get_taxonomy(Supplier, "region")
    assert region is not None and region.generated is False
    assert region.target == "taxoapp.Region"  # a class is written as its label
    assert region.through is Supplier._meta.get_field("region").remote_field.through
    assert hasattr(Region, "suppliers")


def test_makemigrations_writes_the_generated_field() -> None:
    state = ModelState.from_model(Product)
    _name, path, _args, kwargs = state.fields["region"].deconstruct()
    assert path == "django.db.models.ManyToManyField"
    assert kwargs == {
        "blank": True,
        "related_name": "+",
        "to": "taxoapp.region",
        "verbose_name": "region",
    }
    detector = MigrationAutodetector(
        ProjectState(),
        ProjectState.from_apps(apps),
        MigrationQuestioner(specified_apps={"taxoapp"}),
    )
    changes = detector.changes(graph=MigrationGraph(), trim_to_apps={"taxoapp"})
    written = "".join(MigrationWriter(migration).as_string() for migration in changes["taxoapp"])
    assert "name='Product'" in written
    assert (
        "('region', models.ManyToManyField(blank=True, related_name='+', "
        "to='taxoapp.region', verbose_name='region'))"
    ) in written


@pytest.mark.django_db
def test_the_through_table_holds_the_indexes_the_queries_use() -> None:
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, "taxoapp_product_region")
    unique = [c["columns"] for c in constraints.values() if c["unique"] and not c["primary_key"]]
    indexed = [c["columns"] for c in constraints.values() if c["index"] and not c["unique"]]
    assert ["product_id", "region_id"] in unique
    assert ["region_id"] in indexed


@isolate_apps("tests.taxoapp")
def test_an_abstract_base_gives_each_concrete_model_its_own_field() -> None:
    class Zone(TreeModel, BaseModel):
        class Meta:
            app_label = "taxoapp"

    class Tagged(BaseModel):
        class Karni:
            taxonomies = {"zone": "taxoapp.Zone"}

        class Meta:
            abstract = True
            app_label = "taxoapp"

    class Note(Tagged):
        class Meta:
            app_label = "taxoapp"

    class Memo(Tagged):
        class Meta:
            app_label = "taxoapp"

    assert not any(field.name == "zone" for field in Tagged._meta.get_fields())
    for model in (Note, Memo):
        field = model._meta.get_field("zone")
        assert field.remote_field.through._meta.db_table == f"taxoapp_{model._meta.model_name}_zone"
        assert get_taxonomy(model, "zone").generated is True  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("declared", "why"),
    [
        (["region"], "is a list, not a dict"),
        ({"_region": "taxoapp.Region"}, "'_region', which is not a field name"),
        ({"place__region": "taxoapp.Region"}, "'place__region'"),
        ({"region_descendants": "taxoapp.Region"}, "ending in _descendants"),
        ({"region": 3}, "maps 'region' to 3, which names no model"),
        ({"region": ""}, "which names no model"),
    ],
)
def test_a_malformed_declaration_fails_when_the_class_is_built(declared: Any, why: str) -> None:
    with isolate_apps("tests.taxoapp"), pytest.raises(KarniImproperlyConfigured) as raised:

        class Broken(BaseModel):
            class Karni:
                taxonomies = declared

            class Meta:
                app_label = "taxoapp"

    assert raised.value.code == "E570"
    assert why in str(raised.value)


# the checks


@isolate_apps("tests.taxoapp")
def test_the_check_reports_a_target_that_is_not_a_tree_and_a_field_that_does_not_fit() -> None:
    class Zone(TreeModel, BaseModel):
        class Meta:
            app_label = "taxoapp"

    class Flat(BaseModel):
        class Meta:
            app_label = "taxoapp"

    class OnFlat(BaseModel):
        class Karni:
            taxonomies = {"flat": "taxoapp.Flat"}

        class Meta:
            app_label = "taxoapp"

    class Elsewhere(BaseModel):
        zone = models.ManyToManyField(Flat, blank=True, related_name="+")

        class Karni:
            taxonomies = {"zone": "taxoapp.Zone"}

        class Meta:
            app_label = "taxoapp"

    class Single(BaseModel):
        zone = models.ForeignKey(Zone, null=True, on_delete=models.SET_NULL, related_name="+")

        class Karni:
            taxonomies = {"zone": Zone}

        class Meta:
            app_label = "taxoapp"

    class Fine(BaseModel):
        class Karni:
            taxonomies = {"zone": "Zone"}

        class Meta:
            app_label = "taxoapp"

    found = check_taxonomies([Zone._meta.apps.get_app_config("taxoapp")])
    codes = {(message.id, message.obj) for message in found}
    assert ("karni.E571", OnFlat) in codes
    assert ("karni.E572", Elsewhere) in codes
    assert ("karni.E572", Single) in codes
    assert not any(message.obj is Fine for message in found)
    messages = {message.obj: message.msg for message in found}
    assert "points at taxoapp.Flat, which is not a tree model" in messages[OnFlat]
    assert "points at taxoapp.Flat" in messages[Elsewhere]
    assert "which is ForeignKey, not a many-to-many" in messages[Single]
    with pytest.raises(KarniImproperlyConfigured) as raised:
        _ = get_taxonomy(Single, "zone").field  # type: ignore[union-attr]
    assert raised.value.code == "E572"


def test_the_project_passes_the_check() -> None:
    assert check_taxonomies() == []


def test_tagging_lists_every_taxonomy_on_a_tree() -> None:
    found = {(item.model, item.key) for item in tagging(Region)}
    assert found == {(Product, "region"), (Supplier, "region")}
    assert [(item.model, item.key) for item in tagging(Category)] == [(Product, "category")]
    assert tagging(Product) == []


# the queries


def keys(queryset: Any) -> list[str]:
    return sorted(row.name for row in queryset)


@pytest.mark.django_db
def test_tagged_rows_with_and_without_descendants(catalog: Catalog) -> None:
    region = get_taxonomy(Product, "region")
    assert region is not None
    assert keys(Product.objects.filter(tagged_rows(region, [catalog.france]))) == [
        "Secret plan",
        "Wine",
    ]
    europe = Product.objects.filter(tagged_rows(region, [catalog.europe.pk], descendants=True))
    assert keys(europe) == ["Ham", "Pie", "Secret plan", "Sunk", "Wine"]
    with CaptureQueriesContext(connection) as queries:
        list(europe.all())
    assert len(queries) == 1
    readable = Region.objects.exclude(code="hidden")
    within = tagged_rows(region, [catalog.europe], descendants=True, within=readable)
    assert keys(Product.objects.filter(within)) == ["Ham", "Pie", "Secret plan", "Wine"]
    assert keys(Product.objects.filter(tagged_rows(region, []))) == []


@pytest.mark.django_db
def test_facet_counts_is_one_query_and_facets_two(
    catalog: Catalog, django_assert_num_queries: Any
) -> None:
    region = get_taxonomy(Product, "region")
    assert region is not None
    rows = Product.objects.all()
    with django_assert_num_queries(1):
        counted = facet_counts(region, rows, rollup=True)
    assert counted[catalog.world.pk] == 6 and counted[catalog.hidden.pk] == 1
    with django_assert_num_queries(1):
        flat = facet_counts(region, rows)
    assert flat == {
        catalog.france.pk: 2,
        catalog.lyon.pk: 2,
        catalog.spain.pk: 1,
        catalog.japan.pk: 1,
        catalog.deep.pk: 1,
    }
    with django_assert_num_queries(2):
        nodes = facets(region, rows, rollup=True)
    assert [(node.label, node.count) for node in nodes][:3] == [
        ("World", 6),
        ("Europe", 5),
        ("France", 3),
    ]
    assert nodes[0].parent is None and nodes[1].parent == catalog.world.pk
    assert facets(region, Product.objects.none()) == []
    catalog.lyon.delete()  # soft delete: Lyon and its rows drop out of the walk
    assert catalog.lyon.pk not in facet_counts(region, rows, rollup=True)


@pytest.mark.django_db
def test_a_cycle_in_the_tree_never_loops_the_rollup(catalog: Catalog) -> None:
    region = get_taxonomy(Product, "region")
    assert region is not None
    Region.objects.filter(pk=catalog.world.pk).update(parent=catalog.lyon)  # World under Lyon
    counted = facet_counts(region, Product.objects.all(), rollup=True)
    assert counted[catalog.world.pk] == 6
    assert counted[catalog.lyon.pk] == 6  # Lyon is now above everything, through World
