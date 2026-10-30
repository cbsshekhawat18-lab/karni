"""The walks of a tree model: each TreeQuerySet method, cycles, soft delete and 10,000 nodes.

The suite runs on SQLite and PostgreSQL (the CYCLE clause there, a path of
keys here) and with both key types (``KARNI_TEST_PK=bigint``).
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from karni.exceptions import KarniValueError
from karni.tree import tree_order
from tests.testapp.models import Category, Region, Venue
from tests.tree.build import LEVELS, bulk_tree, regions

pytestmark = pytest.mark.django_db


def names(rows: object) -> list[str]:
    return [row.name for row in rows]  # type: ignore[attr-defined]


def test_roots_and_children_come_in_sibling_order() -> None:
    tree = regions()
    assert names(Region.objects.roots()) == ["World", "Asia"]
    assert names(Region.objects.children(tree.europe)) == ["France", "Germany"]
    assert names(Region.objects.children(tree.europe.pk)) == ["France", "Germany"]
    assert list(Region.objects.children(tree.paris)) == []


def test_descendants_walk_down_lazily_in_one_statement() -> None:
    tree = regions()
    with CaptureQueriesContext(connection) as queries:
        branch = Region.objects.descendants(tree.europe)
        assert not queries.captured_queries  # lazy until evaluated
        found = set(names(branch))
    assert found == {"France", "Paris", "Germany", "Berlin"}
    assert len(queries.captured_queries) == 1
    assert set(names(Region.objects.descendants(tree.europe, include_self=True))) == {
        "Europe",
        "France",
        "Paris",
        "Germany",
        "Berlin",
    }
    assert set(names(Region.objects.descendants(tree.world, max_depth=2))) == {
        "Europe",
        "France",
        "Germany",
    }
    # many starting nodes, as rows, keys or a queryset; the result chains
    both = Region.objects.descendants([tree.france, tree.germany.pk])
    assert set(names(both)) == {"Paris", "Berlin"}
    assert names(both.filter(name__startswith="B")) == ["Berlin"]
    from_queryset = Region.objects.descendants(Region.objects.filter(code__in=["fr", "de"]))
    assert set(names(from_queryset)) == {"Paris", "Berlin"}
    assert list(Region.objects.descendants([])) == []
    assert list(Region.objects.descendants(Region.objects.none())) == []


def test_ancestors_come_root_first() -> None:
    tree = regions()
    assert names(Region.objects.ancestors(tree.berlin)) == ["World", "Europe", "Germany"]
    assert names(Region.objects.ancestors(tree.berlin, include_self=True)) == [
        "World",
        "Europe",
        "Germany",
        "Berlin",
    ]
    assert list(Region.objects.ancestors(tree.world)) == []


def test_subtree_ids_takes_many_roots_in_one_query() -> None:
    tree = regions()
    with CaptureQueriesContext(connection) as queries:
        found = Region.objects.subtree_ids([tree.france.pk, tree.germany, tree.asia])
    assert len(queries.captured_queries) == 1
    expected = {tree.france, tree.paris, tree.germany, tree.berlin, tree.asia}
    assert found == {row.pk for row in expected}


def test_walk_reports_each_node_once_with_its_depth() -> None:
    tree = regions()
    # Europe is below World: reached twice, listed once at its smallest depth.
    rows = Region.objects.walk([tree.world, tree.europe], include_self=True)
    depths = {key: depth for key, _parent, depth in rows}
    assert depths[tree.europe.pk] == 0
    assert depths[tree.paris.pk] == 2
    assert len(rows) == 6
    up = Region.objects.walk(tree.paris, up=True)
    assert [(key, depth) for key, _parent, depth in up] == [
        (tree.france.pk, 1),
        (tree.europe.pk, 2),
        (tree.world.pk, 3),
    ]
    assert len(Region.objects.walk(tree.world, limit=2)) == 2


def test_a_cycle_written_into_the_data_never_loops() -> None:
    tree = regions()
    # Straight into the table, as an import or a hand edit would: World under Paris.
    Region.objects.filter(pk=tree.world.pk).update(parent=tree.paris)
    every = {"World", "Europe", "France", "Paris", "Germany", "Berlin"}
    assert set(names(Region.objects.descendants(tree.world, include_self=True))) == every
    assert set(names(Region.objects.descendants(tree.france))) == every - {"France"}
    assert set(names(Region.objects.ancestors(tree.berlin))) == {
        "Germany",
        "Europe",
        "World",
        "Paris",
        "France",
    }
    assert len(Region.objects.subtree_ids([tree.europe])) == 6
    assert Region.objects.roots().get() == tree.asia
    # A row that is its own parent.
    Region.objects.filter(pk=tree.asia.pk).update(parent=tree.asia)
    assert list(Region.objects.descendants(tree.asia)) == []
    assert names(Region.objects.ancestors(tree.asia, include_self=True)) == ["Asia"]


def test_a_soft_deleted_node_hides_its_branch() -> None:
    tree = regions()
    # Germany deleted with a live child left below it (written past delete()'s refusal).
    Region.objects.filter(pk=tree.germany.pk).delete()
    assert set(names(Region.objects.descendants(tree.europe))) == {"France", "Paris"}
    assert names(Region.objects.ancestors(tree.berlin)) == []
    every = Region.objects.without("soft_delete", reason="test: walk deleted rows too")
    assert set(names(every.descendants(tree.europe))) == {"France", "Paris", "Germany", "Berlin"}


def test_a_filtered_queryset_walks_only_its_rows() -> None:
    tree = regions()
    assert set(names(Region.objects.exclude(code="fr").descendants(tree.europe))) == {
        "Germany",
        "Berlin",
    }
    # Filter after the walk to keep the branch and narrow the result.
    branch = Region.objects.descendants(tree.europe).exclude(code="fr")
    assert set(names(branch)) == {"Paris", "Germany", "Berlin"}


def test_a_walk_refuses_what_names_no_node() -> None:
    venue = Venue.objects.create(name="Hall", city="Lyon")
    for bad in (venue, None, Region()):
        with pytest.raises(KarniValueError) as caught:
            Region.objects.descendants(bad)
        assert caught.value.code == "E343"
    with pytest.raises(KarniValueError) as caught:
        Region.objects.subtree_ids(["not a key"])
    assert caught.value.code == "E343"
    with pytest.raises(KarniValueError):
        Region.objects.descendants(Venue.objects.all())


def test_an_ordered_tree_sorts_siblings_by_position() -> None:
    shoes = Category.objects.create(name="Shoes")
    boots = Category.objects.create(name="Boots", parent=shoes)
    sandals = Category.objects.create(name="Sandals", parent=shoes)
    first = Category.objects.create(name="Clogs", parent=shoes, position=0)
    assert (boots.position, sandals.position, first.position) == (0, 1, 0)
    assert names(Category.objects.children(shoes)) == ["Boots", "Clogs", "Sandals"]
    assert Category.tree_ordering()[0] == "position"


def test_ten_thousand_nodes() -> None:
    levels = bulk_tree()
    roots, leaves = levels[0], levels[-1]
    total = sum(len(level) for level in levels)
    assert total == 10_000
    with CaptureQueriesContext(connection) as queries:
        everything = Region.objects.subtree_ids(roots)
        one_root = Region.objects.descendants(roots[0]).count()
        path = list(Region.objects.ancestors(leaves[-1], include_self=True))
        shallow = Region.objects.descendants(roots[0], max_depth=2).count()
    assert len(everything) == total
    assert one_root == total // len(roots) - 1
    assert [row.pk for row in path][-1] == leaves[-1].pk and len(path) == len(LEVELS)
    assert shallow == LEVELS[1] + LEVELS[1] * LEVELS[2]
    assert len(queries.captured_queries) == 5  # subtree_ids 1, count 1, ancestors 2, count 1
    # A cycle through a whole branch of the large tree: still one bounded answer.
    branch_root = roots[0]
    Region.objects.filter(pk=branch_root.pk).update(parent=leaves[0])
    assert len(Region.objects.subtree_ids([branch_root])) == total // len(roots)
    assert len(Region.objects.walk(leaves[0], up=True)) == len(LEVELS) - 1


def test_tree_order_is_depth_first_and_survives_cycles() -> None:
    rows = [("a", None), ("b", "a"), ("c", "b"), ("d", "a"), ("e", None), ("x", "y"), ("y", "x")]
    assert tree_order(rows) == [
        ("a", 0),
        ("b", 1),
        ("c", 2),
        ("d", 1),
        ("e", 0),
        ("x", 0),
        ("y", 1),
    ]
    # A row whose parent is not listed (a filtered list) starts a branch.
    assert tree_order([("c", "b"), ("d", "c")]) == [("c", 0), ("d", 1)]
    assert tree_order([("s", "s")]) == [("s", 0)]
