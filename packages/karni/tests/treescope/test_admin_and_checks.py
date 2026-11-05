"""The tree scope in the admin's row scope, the permission matrix and the startup checks."""

from __future__ import annotations

from typing import Any

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, override_settings
from django.utils.module_loading import import_string

from karni.accounts import grants
from karni.accounts.matrix import scope_options
from karni.accounts.roles import declared_roles, expand_grants, permission_keys
from karni.checks import check_tree_scopes
from karni.exceptions import KarniImproperlyConfigured
from tests.testapp.models import Event, Listing, Product, Region
from tests.treescope import PRODUCT_VIEW
from tests.treescope.conftest import Catalog, fresh, make_user

pytestmark = pytest.mark.django_db


def registered(model: Any) -> Any:
    return import_string(settings.KARNI_ADMIN_SITE)._registry[model]


def staff_request(user: Any) -> Any:
    content_type = ContentType.objects.get_for_model(Product)
    user.user_permissions.add(*Permission.objects.filter(content_type=content_type))
    request = RequestFactory().get("/")
    request.user = fresh(user)
    return request


class TestAdmin:
    def test_the_changelist_and_the_change_form_follow_the_subtree(self, catalog: Catalog) -> None:
        user = make_user("staff@example.com", is_staff=True)
        grants.grant(None, user, PRODUCT_VIEW, "tree:category", targets=[catalog.food.pk])
        request = staff_request(user)
        admin = registered(Product)
        shown = sorted(admin.get_queryset(request).values_list("name", flat=True))
        assert shown == ["Apple pie", "Milk"]
        assert admin.has_view_permission(request, catalog.milk)
        assert not admin.has_view_permission(request, catalog.saw)


class TestMatrix:
    def test_the_matrix_offers_the_relations_to_a_tree(self) -> None:
        values = [value for value, _label in scope_options(Product)]
        assert "tree:category" in values and "tree:regions" in values
        assert not any(value.startswith("tree:") for value, _ in scope_options(Event))
        assert not any(value == "tree:parent" for value, _ in scope_options(Region))


class TestStartup:
    def test_the_declared_tree_scopes_pass(self) -> None:
        messages = check_tree_scopes()
        assert {m.id for m in messages} <= {"karni.W620"}

    def test_a_path_that_does_not_end_at_a_tree_is_e490(self) -> None:
        roles = {"bad": {"grants": {PRODUCT_VIEW: "tree:name", "testapp.*:view": "tree:venue"}}}
        with override_settings(KARNI_ROLES=roles):
            messages = check_tree_scopes()
            codes = [m.id for m in messages]
            assert codes == ["karni.E490", "karni.E490"]
            assert "Product.name is not a relation" in messages[0].msg
            assert "none of the" in messages[1].msg
            with pytest.raises(KarniImproperlyConfigured) as caught:
                expand_grants(declared_roles()[0], permission_keys())
            assert caught.value.code == "E490"

    def test_a_wildcard_skips_the_models_without_the_path(self) -> None:
        roles = {"wide": {"grants": {"testapp.*:view": "tree:product__category"}}}
        with override_settings(KARNI_ROLES=roles):
            (spec,) = declared_roles()
            keys = {grant.permission for grant in expand_grants(spec, permission_keys())}
        assert keys == {"testapp.listing:view"}

    def test_a_role_grant_whose_members_hold_no_node_is_w620(self) -> None:
        messages = [m for m in check_tree_scopes() if m.id == "karni.W620"]
        # The default user model has no category and no regions attribute.
        assert messages and all("gives its members no node" in m.msg for m in messages)
        assert any("'category'" in m.msg for m in messages)
        assert any("'regions'" in m.msg for m in messages)

    def test_tree_scope_in_a_where_checks_its_path_at_once(self) -> None:
        from karni.accounts.tree_scope import tree_scope

        with pytest.raises(KarniImproperlyConfigured) as caught:
            tree_scope(Listing, "product")
        assert caught.value.code == "E490"
        assert tree_scope(Listing, "product__category").__name__ == "tree_scope_product__category"
