"""``tree:<path>``: the rows under the nodes a user holds, from role grants and user grants."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.db.models import Q
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from karni.accounts import grants
from karni.accounts.roles import Grant, rows_for, user_can
from karni.accounts.tree_scope import (
    SubtreeKeys,
    granted_targets,
    resolve_path,
    subtree_rows,
    tree_path,
    tree_rows,
)
from karni.exceptions import KarniImproperlyConfigured, KarniValueError
from karni.rows import apply_rows
from tests.testapp.models import Category, Event, Listing, Product, Region
from tests.tree.build import bulk_tree
from tests.treescope import LISTING_VIEW, PRODUCT_VIEW
from tests.treescope.conftest import Catalog, fresh, make_user

pytestmark = pytest.mark.django_db


def visible(user: Any, model: type[Any] = Product, action: str = "view") -> list[str]:
    """The names a user's grants reach, sorted, each row once."""
    rows = apply_rows(model._default_manager.all(), rows_for(user, model, action))
    field = "title" if model is Listing else "name"
    return sorted(rows.values_list(field, flat=True))


def grant(user: Any, scope: str, *nodes: Any, permission: str = PRODUCT_VIEW, **extra: Any) -> Any:
    return grants.grant(None, user, permission, scope, targets=[n.pk for n in nodes], **extra)


# the path


class TestPath:
    def test_a_foreign_key_a_many_to_many_and_a_path_through_a_relation(self) -> None:
        assert resolve_path(Product, "category").tree_model is Category
        regions = resolve_path(Product, "regions")
        assert regions.tree_model is Region and regions.to_many
        through = resolve_path(Listing, "product__category")
        assert through.tree_model is Category and not through.to_many
        assert resolve_path(Listing, "product__regions").to_many
        assert resolve_path(Category, "products__regions").to_many  # a reverse relation

    @pytest.mark.parametrize(
        ("model", "path", "why"),
        [
            (Product, "name", "is not a relation"),
            (Product, "categry", "is not a field of Product"),
            (Product, "", "empty"),
            (Product, "category__", "empty"),
            (Event, "venue", "which is not a tree model"),
            (Listing, "product", "which is not a tree model"),
        ],
    )
    def test_a_path_that_does_not_end_at_a_tree_is_e490(
        self, model: type[Any], path: str, why: str
    ) -> None:
        with pytest.raises(KarniImproperlyConfigured) as caught:
            resolve_path(model, path)
        assert caught.value.code == "E490" and why in caught.value.message
        assert tree_path(model, path) is None


# the rows


class TestRows:
    def test_a_user_grant_reaches_its_node_and_every_node_below(self, catalog: Catalog) -> None:
        user = make_user("a@example.com")
        grant(user, "tree:category", catalog.food)
        assert visible(fresh(user)) == ["Apple pie", "Milk"]

    def test_deep_trees_every_level_below_counts(self, catalog: Catalog) -> None:
        user = make_user("deep@example.com")
        grant(user, "tree:category", catalog.everything)
        assert visible(fresh(user)) == ["Apple pie", "Milk", "Saw"]
        leaf = make_user("leaf@example.com")
        grant(leaf, "tree:category", catalog.apples)
        assert visible(fresh(leaf)) == ["Apple pie"]

    def test_overlapping_grants_give_each_row_once(self, catalog: Catalog) -> None:
        user = make_user("overlap@example.com")
        grant(user, "tree:category", catalog.food, catalog.fruit)
        grant(user, "tree:category", catalog.everything, reason="a second grant")
        user = fresh(user)
        rows = apply_rows(Product.objects.all(), rows_for(user, Product, "view"))
        assert sorted(rows.values_list("name", flat=True)) == ["Apple pie", "Milk", "Saw"]

    def test_a_many_to_many_tag_reaches_each_row_once(self, catalog: Catalog) -> None:
        user = make_user("m2m@example.com", "regional")
        grant(user, "tree:regions", catalog.world, catalog.asia)
        names = visible(fresh(user))
        assert names == ["Apple pie", "Milk", "Saw"]  # the pie is in Lyon and Tokyo: once

    def test_a_path_through_a_relation(self, catalog: Catalog) -> None:
        user = make_user("through@example.com")
        grant(user, "tree:product__category", catalog.tools, permission=LISTING_VIEW)
        assert visible(fresh(user), Listing) == ["Saw listing"]

    def test_the_rows_compile_to_one_subquery_on_the_path(self, catalog: Catalog) -> None:
        rows = subtree_rows(Product, "category", [catalog.food.pk, catalog.tools.pk])
        assert isinstance(rows, Q)
        ((lookup, value),) = rows.children
        assert lookup == "category__in" and isinstance(value, SubtreeKeys)
        sql = str(Product.objects.filter(rows).query).upper()
        assert sql.count("WITH RECURSIVE") == 1
        assert subtree_rows(Product, "category", []) is False
        assert subtree_rows(Product, "category", ["not-a-key", None]) is False

    def test_a_cycle_in_the_data_never_loops(self, catalog: Catalog) -> None:
        # Food > Fruit > Apples, then Food's parent set to Apples behind the model's back.
        Category.objects.filter(pk=catalog.food.pk).update(parent=catalog.apples)
        user = make_user("cycle@example.com")
        grant(user, "tree:category", catalog.fruit)
        assert visible(fresh(user)) == ["Apple pie", "Milk"]

    def test_a_soft_deleted_node_hides_its_branch(self, catalog: Catalog) -> None:
        user = make_user("deleted@example.com")
        grant(user, "tree:category", catalog.everything)
        catalog.saws.delete()
        assert visible(fresh(user)) == ["Apple pie", "Milk"]


# where the nodes come from


class TestNodes:
    def test_a_role_grant_reaches_the_node_the_user_holds(self, catalog: Catalog) -> None:
        user = make_user("buyer@example.com", "buyer")
        assert visible(fresh(user)) == []
        assert visible(fresh(user, category=catalog.tools)) == ["Saw"]
        assert visible(fresh(user, category=catalog.tools), Listing) == ["Saw listing"]

    def test_a_grant_without_targets_gives_no_rows_never_every_row(self, catalog: Catalog) -> None:
        user = make_user("bare@example.com")
        grants.grant(None, user, PRODUCT_VIEW, "tree:category")
        user = fresh(user)
        assert rows_for(user, Product, "view") is False
        assert visible(user) == []
        # user.<path> fills in, as for related:<key>
        assert visible(fresh(user, category=catalog.books)) == ["Novel"]

    def test_role_and_user_grants_add_up(self, catalog: Catalog) -> None:
        user = make_user("both@example.com", "buyer")
        grant(user, "tree:category", catalog.books)
        assert visible(fresh(user, category=catalog.saws)) == ["Novel", "Saw"]
        found = granted_targets(fresh(user, category=catalog.saws), "category")
        assert {item.source.origin for item in found} == {"declared", "user_grant"}
        # the role's two grants of the scope (view, change) each give user.category
        assert {item.target for item in found} == {str(catalog.saws.pk), str(catalog.books.pk)}

    def test_expiry_removes_access(self, catalog: Catalog) -> None:
        user = make_user("expiring@example.com")
        row = grant(user, "tree:category", catalog.food)
        assert visible(fresh(user)) == ["Apple pie", "Milk"]
        grants.expire(None, row)
        assert visible(fresh(user)) == []
        later = grant(user, "tree:category", catalog.tools)
        later.expires_at = timezone.now() - timedelta(minutes=1)
        later.save()
        assert visible(fresh(user)) == []

    def test_switched_off_user_grants_give_nothing(self, catalog: Catalog, settings: Any) -> None:
        user = make_user("off@example.com")
        grant(user, "tree:category", catalog.food)
        settings.KARNI_USER_GRANTS = False
        assert visible(fresh(user)) == []

    def test_user_can_on_one_row(self, catalog: Catalog) -> None:
        user = make_user("one@example.com")
        grant(user, "tree:category", catalog.food)
        user = fresh(user)
        assert user_can(user, PRODUCT_VIEW, catalog.milk)
        assert not user_can(user, PRODUCT_VIEW, catalog.saw)

    def test_tree_rows_and_a_single_grant(self, catalog: Catalog) -> None:
        user = make_user("rows@example.com")
        grant(user, "tree:category", catalog.dairy)
        user = fresh(user)
        assert Product.objects.filter(tree_rows(user, Product, "category")).get() == catalog.milk
        assert tree_rows(user, Product, "category", permission="testapp.product:delete") is False
        from karni.accounts.roles import grant_rows

        role_grant = Grant(PRODUCT_VIEW, "tree", "category")
        assert grant_rows(user, Product, role_grant) is False  # no user.category

    def test_a_model_without_the_path_fails_closed(self, catalog: Catalog) -> None:
        from karni.accounts.roles import grant_rows

        user = make_user("closed@example.com")
        assert grant_rows(user, Event, Grant("testapp.event:view", "tree", "category")) is False


# the queries


class TestQueries:
    def test_the_nodes_are_read_once_per_request(self, catalog: Catalog) -> None:
        user = make_user("count@example.com", "buyer")
        grant(user, "tree:category", catalog.food)
        user = fresh(user, category=catalog.books)
        with CaptureQueriesContext(connection) as first:
            rows_for(user, Product, "view")
        with CaptureQueriesContext(connection) as again:
            rows_for(user, Product, "view")
            rows_for(user, Product, "view")
        assert len(again) == 0
        # the role grants, the user grants and the role side of scope_targets
        assert len(first) == 3

    def test_the_list_query_count_does_not_grow_with_rows_or_nodes(self, catalog: Catalog) -> None:
        user = make_user("flat@example.com")
        grant(user, "tree:category", catalog.everything)

        def count() -> int:
            fresh_user = fresh(user)
            with CaptureQueriesContext(connection) as captured:
                list(apply_rows(Product.objects.all(), rows_for(fresh_user, Product, "view")))
            return len(captured)

        before = count()
        food = Category.objects.create(name="More food", parent=catalog.food)
        for index in range(12):
            Product.objects.create(name=f"Extra {index}", category=food)
        grant(user, "tree:category", catalog.books, catalog.saws)
        assert count() == before


class TestLargeTree:
    def test_ten_thousand_nodes_one_statement(self) -> None:
        levels = bulk_tree(Category)
        roots, leaves = levels[0], levels[-1]
        products = [
            Product(name=f"p{index}", category=leaf) for index, leaf in enumerate(leaves[:500])
        ]
        Product.objects.bulk_create(products)
        user = make_user("big@example.com")
        grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[roots[0].pk])
        user = fresh(user)
        rows = rows_for(user, Product, "view")
        started = time.perf_counter()
        with CaptureQueriesContext(connection) as captured:
            found = Product.objects.filter(rows).count()
        took = time.perf_counter() - started
        # The first root holds a tenth of the leaves: 900 of 9,000, and 500 products sit on
        # the first 500 leaves, all under the first root.
        assert found == 500
        assert len(captured) == 1
        assert took < 5.0, f"the subtree of a 10,000-node tree took {took:.2f}s"
        everything = make_user("all-roots@example.com")
        grants.grant(None, everything, PRODUCT_VIEW, "tree:category", targets=[r.pk for r in roots])
        assert Product.objects.filter(rows_for(fresh(everything), Product, "view")).count() == 500


# the grant's checks


class TestCheck:
    def test_a_tree_grant_is_checked(self, catalog: Catalog) -> None:
        checked = grants.check(PRODUCT_VIEW, "tree:category", [catalog.food.pk])
        assert checked.scope == "tree" and checked.scope_path == "category"
        assert checked.targets == (str(catalog.food.pk),)

    @pytest.mark.parametrize("scope", ["tree", "tree:name", "tree:venue", "tree:categry"])
    def test_a_tree_scope_that_does_not_fit_is_e361(self, scope: str) -> None:
        with pytest.raises(KarniValueError) as caught:
            grants.check(PRODUCT_VIEW, scope)
        assert caught.value.code == "E361"

    def test_a_wildcard_keeps_the_models_with_the_path(self) -> None:
        checked = grants.check("testapp.*:view", "tree:category")
        assert checked.keys == (PRODUCT_VIEW,)

    def test_a_target_of_the_wrong_type_is_e362(self) -> None:
        if not isinstance(Category._meta.pk.get_internal_type(), str):  # pragma: no cover
            return
        with pytest.raises(KarniValueError) as caught:
            grants.check(PRODUCT_VIEW, "tree:category", ["not a key"])
        assert caught.value.code == "E362"

    def test_an_operator_may_grant_a_node_below_their_own(self, catalog: Catalog) -> None:
        operator = make_user("operator@example.com")
        grant(operator, "tree:category", catalog.food)
        operator = fresh(operator)
        user = make_user("delegated@example.com")
        grants.grant(operator, user, PRODUCT_VIEW, "tree:category", targets=[catalog.apples.pk])
        with pytest.raises(grants.GrantRefused) as caught:
            grants.grant(operator, user, PRODUCT_VIEW, "tree:category", targets=[catalog.saws.pk])
        assert caught.value.code == "E363"
        assert str(catalog.saws.pk) in caught.value.reasons[0]
