"""TreeModel's writes: the cycle guard, move_to, soft delete and delete_branch, and the checks."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, models
from django.test.utils import CaptureQueriesContext, isolate_apps

from karni.checks import check_tree_models
from karni.exceptions import KarniValueError
from karni.models import BaseModel, OrderedTreeModel, TreeModel
from karni.signals import pre_write
from karni.tree import TreeCycleError, TreeHasChildren, is_tree_model, tree_spec
from tests.testapp.models import Category, Region, Venue
from tests.tree.build import regions

pytestmark = pytest.mark.django_db


def test_the_mixins_declare_the_tree() -> None:
    parent = Region._meta.get_field("parent")
    assert isinstance(parent, models.ForeignKey)
    assert parent.related_model is Region
    assert parent.null and parent.db_index
    assert parent.remote_field.on_delete is models.PROTECT
    assert parent.remote_field.related_name == "children"
    assert is_tree_model(Region) and is_tree_model(Category()) and not is_tree_model(Venue)
    assert tree_spec(Region) is not None and not tree_spec(Region).ordered  # type: ignore[union-attr]
    assert tree_spec(Category).as_extension() == {"parent": "parent", "ordered": True}  # type: ignore[union-attr]
    assert tree_spec(Venue) is None


def test_save_refuses_a_parent_at_or_below_the_node() -> None:
    tree = regions()
    tree.europe.parent = tree.europe
    with pytest.raises(TreeCycleError) as caught:
        tree.europe.save()
    assert caught.value.code == "E340"
    europe = Region.objects.get(pk=tree.europe.pk)
    europe.parent = tree.berlin
    with pytest.raises(TreeCycleError):
        europe.save()
    assert Region.objects.get(pk=tree.europe.pk).parent_id == tree.world.pk
    # clean() says it on the field, for forms.
    with pytest.raises(ValidationError) as invalid:
        europe.clean()
    assert "parent" in invalid.value.message_dict
    # A parent elsewhere is fine.
    europe.parent = tree.asia
    europe.save()
    assert Region.objects.ancestors(tree.paris).first() == tree.asia


def test_an_unchanged_parent_is_not_walked() -> None:
    tree = regions()
    paris = Region.objects.get(pk=tree.paris.pk)
    paris.name = "Paris, France"
    with CaptureQueriesContext(connection) as queries:
        paris.save()
    assert not any("RECURSIVE" in query["sql"] for query in queries.captured_queries)
    paris.parent = tree.germany
    with CaptureQueriesContext(connection) as queries:
        paris.save()
    assert sum("RECURSIVE" in query["sql"] for query in queries.captured_queries) == 1


def test_move_to_reparents_and_refuses_a_cycle() -> None:
    tree = regions()
    tree.germany.move_to(tree.asia)
    assert names_above(tree.berlin) == ["Asia", "Germany"]
    with pytest.raises(TreeCycleError):
        tree.asia.move_to(tree.berlin)
    tree.asia.refresh_from_db()
    assert tree.asia.parent_id is None
    tree.germany.move_to(None)
    assert Region.objects.get(pk=tree.germany.pk).parent_id is None
    with pytest.raises(KarniValueError) as caught:
        tree.germany.move_to(tree.world, position=0)
    assert caught.value.code == "E343"


def names_above(node: Any) -> list[str]:
    return [row.name for row in type(node).objects.ancestors(node)]


def test_move_to_renumbers_the_old_and_new_siblings() -> None:
    shoes = Category.objects.create(name="Shoes")
    bags = Category.objects.create(name="Bags")
    boots, sandals, clogs = (
        Category.objects.create(name=name, parent=shoes) for name in ("Boots", "Sandals", "Clogs")
    )
    totes = Category.objects.create(name="Totes", parent=bags)
    sandals.move_to(bags, position=0)
    assert ordered(bags) == [("Sandals", 0), ("Totes", 1)]
    assert ordered(shoes) == [("Boots", 0), ("Clogs", 1)]
    clogs.move_to(shoes, position=0)
    assert ordered(shoes) == [("Clogs", 0), ("Boots", 1)]
    boots.move_to(bags)  # no position: last
    assert ordered(bags) == [("Sandals", 0), ("Totes", 1), ("Boots", 2)]
    totes.move_to(bags, position=99)
    assert ordered(bags) == [("Sandals", 0), ("Boots", 1), ("Totes", 2)]
    with pytest.raises(KarniValueError) as caught:
        totes.move_to(bags, position=-1)
    assert caught.value.code == "E343"


def ordered(parent: Category) -> list[tuple[str, int]]:
    return [(row.name, row.position) for row in Category.objects.children(parent)]


def test_a_refused_move_changes_nothing() -> None:
    shoes = Category.objects.create(name="Shoes")
    boots = Category.objects.create(name="Boots", parent=shoes)
    Category.objects.create(name="Clogs", parent=boots)
    with pytest.raises(TreeCycleError):
        shoes.move_to(boots, position=0)
    assert ordered(boots) == [("Clogs", 0)]
    assert Category.objects.get(pk=shoes.pk).parent_id is None


def test_new_ordered_nodes_go_last_and_bulk_create_stores_zero() -> None:
    shoes = Category.objects.create(name="Shoes")
    made = [Category.objects.create(name=f"c{i}", parent=shoes) for i in range(3)]
    assert [row.position for row in made] == [0, 1, 2]
    explicit = Category.objects.create(name="first", parent=shoes, position=0)
    assert explicit.position == 0
    bulk = Category.objects.bulk_create([Category(name="bulk", parent=shoes)])
    assert Category.objects.get(pk=bulk[0].pk).position == 0


def test_delete_refuses_a_node_with_live_children() -> None:
    tree = regions()
    with pytest.raises(TreeHasChildren) as caught:
        tree.europe.delete()
    assert caught.value.code == "E341"
    assert caught.value.payload()["conflict"] == {"children": 2}
    assert caught.value.status == 409
    assert not Region.objects.get(pk=tree.europe.pk).is_deleted
    tree.paris.delete()
    tree.france.delete()  # its only child is deleted now
    assert set(Region.objects.children(tree.europe)) == {tree.germany}


def test_delete_branch_deletes_the_subtree_in_one_statement() -> None:
    tree = regions()
    seen: list[str] = []

    def listener(sender: Any, instance: Any, action: str, **kwargs: Any) -> None:
        seen.append(f"{action}:{instance.name}")

    pre_write.connect(listener, sender=Region)
    try:
        with CaptureQueriesContext(connection) as queries:
            count = tree.europe.delete_branch()
    finally:
        pre_write.disconnect(listener, sender=Region)
    assert count == 5
    assert seen == ["delete:Europe"]
    sqls = [query["sql"].lstrip().upper() for query in queries.captured_queries]
    updates = [sql for sql in sqls if sql.startswith("UPDATE")]
    assert len(updates) == 1
    assert tree.europe.is_deleted
    every = Region.objects.without("soft_delete", reason="test: read the deleted branch")
    stamps = set(
        every.filter(code__in=["eu", "fr", "fr-par", "de", "de-ber"]).values_list(
            "deleted_at", flat=True
        )
    )
    assert len(stamps) == 1 and None not in stamps
    assert set(Region.objects.all()) == {tree.world, tree.asia}


@isolate_apps("tests.testapp")
def test_checks_report_a_tree_model_without_walks_or_parent() -> None:
    class Shelf(BaseModel, TreeModel):  # the base first: its objects wins
        name = models.CharField(max_length=10)

        class Meta:
            app_label = "testapp"

    class Branch(TreeModel, BaseModel):
        parent = models.CharField(max_length=10, blank=True)

        class Meta:
            app_label = "testapp"

    class Fine(OrderedTreeModel, BaseModel):
        class Meta:
            app_label = "testapp"

    found = check_tree_models([Shelf._meta.apps.get_app_config("testapp")])
    codes = {(message.id, message.obj) for message in found}
    assert ("karni.E344", Shelf) in codes
    assert ("karni.E345", Branch) in codes
    assert not any(message.obj is Fine for message in found)
