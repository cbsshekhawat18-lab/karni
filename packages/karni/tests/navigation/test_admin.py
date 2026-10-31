"""The database menu in the admin (experimental): the tree changelist, the form and the preview."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.admin.sites import site
from django.core.exceptions import ValidationError
from django.test import Client
from pytest_django import Settings

from karni.accounts.roles import sync_roles
from karni.navigation.admin import NavItemAdmin
from karni.navigation.models import NavItem

from .conftest import MENU, ROLES, make_user, store

pytestmark = pytest.mark.django_db

ITEMS = "/admin/karni_navigation/navitem/"
PREVIEW = f"{ITEMS}preview/"

ADMIN_ROLES = {
    **ROLES,
    "menu_editor": {"grants": {"karni_navigation.navitem:*": "all"}},
}


@pytest.fixture(autouse=True)
def _world(settings: Settings) -> None:
    settings.KARNI_NAVIGATION = "db"
    settings.KARNI_ROLES = ADMIN_ROLES
    sync_roles()
    store(MENU)


def _preview(html: str) -> str:
    """The menu the preview lists (the admin's own navigation is outside it)."""
    start = html.index('data-testid="karni-menu-preview"')
    return html[start : html.index("</ul>\n", start)]


def _signed_in(user: Any) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def root() -> Any:
    return make_user("root@example.com", is_superuser=True, is_staff=True)


def test_navitem_is_registered_with_the_tree_changelist() -> None:
    model_admin = site._registry[NavItem]
    assert isinstance(model_admin, NavItemAdmin)
    assert model_admin.list_display[0] == "tree_label"


def test_the_changelist_lists_the_menu_in_tree_order(root: Any) -> None:
    html = _signed_in(root).get(ITEMS).content.decode()
    order = [html.index(f">{label}<") for label in ("Home", "Catalog", "Categories", "Products")]
    assert order == sorted(order)
    assert 'class="karni-tree-label" style="padding-left: 1.5rem">Categories<' in html
    assert "/admin/karni_navigation/navitem/preview/" in html  # the Menu preview button


def test_the_preview_shows_a_users_menu_with_each_requirement(root: Any) -> None:
    make_user("editor@example.com", "catalog_editor")
    response = _signed_in(root).get(PREVIEW, {"user": "editor@example.com"})
    assert response.status_code == 200
    html = response.content.decode()
    assert "editor@example.com sees:" in html
    menu = _preview(html)
    for text in ("Catalog", "Categories", "<code>/products</code>", "testapp.product:view"):
        assert text in menu
    assert "Regions" not in menu and "Events" not in menu


def test_the_preview_for_a_visitor_and_by_id(root: Any) -> None:
    html = _signed_in(root).get(PREVIEW, {"visitor": "1"}).content.decode()
    assert "A visitor who is not signed in sees:" in html
    assert "<strong>Home</strong>" in _preview(html) and "Account" not in _preview(html)
    organizer = make_user("organizer@example.com", "organizer")
    html = _signed_in(root).get(PREVIEW, {"user": str(organizer.pk)}).content.decode()
    assert "<strong>Events</strong>" in _preview(html)


def test_the_preview_says_when_nobody_matches(root: Any) -> None:
    response = _signed_in(root).get(PREVIEW, {"user": "nobody@example.com"}, follow=True)
    assert "No user matches nobody@example.com." in response.content.decode()


def test_previewing_another_users_menu_needs_the_matrix_permission() -> None:
    from django.contrib.auth.models import Permission

    editor = make_user("menus@example.com", "menu_editor", is_staff=True)
    editor.user_permissions.add(Permission.objects.get(codename="view_navitem"))
    other = make_user("editor@example.com", "catalog_editor")
    client = _signed_in(editor)
    assert client.get(PREVIEW).status_code == 200
    assert client.get(PREVIEW, {"user": "menus@example.com"}).status_code == 200
    assert client.get(PREVIEW, {"visitor": "1"}).status_code == 200
    assert client.get(PREVIEW, {"user": str(other.pk)}).status_code == 403


def test_the_preview_needs_the_admins_view_permission() -> None:
    staff = make_user("staff@example.com", "catalog_editor", is_staff=True)
    assert _signed_in(staff).get(PREVIEW).status_code in (302, 403)


def test_the_form_refuses_a_route_on_a_group_and_a_child_under_an_item() -> None:
    catalog = NavItem.objects.get(label="Catalog")
    catalog.route = "/catalog"
    with pytest.raises(ValidationError) as caught:
        catalog.full_clean()
    assert "E536" in str(caught.value.message_dict["route"])
    home = NavItem.objects.get(label="Home")
    child = NavItem(label="Inside", route="/inside", parent=home)
    with pytest.raises(ValidationError) as caught:
        child.full_clean()
    assert "E536" in str(caught.value.message_dict["parent"])


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [("route", "products", "E530"), ("icon", "Big Box", "E530"), ("requires", "staff", "E532")],
)
def test_the_form_checks_each_field(field: str, value: str, code: str) -> None:
    row = NavItem(label="Products", route="/products")
    setattr(row, field, value)
    with pytest.raises(ValidationError) as caught:
        row.full_clean()
    assert code in str(caught.value.message_dict[field])


def test_adding_an_entry_in_the_admin_is_history(root: Any) -> None:
    from karni.audit.models import ChangeLog

    catalog = NavItem.objects.get(label="Catalog")
    response = _signed_in(root).post(
        f"{ITEMS}add/",
        {
            "label": "Regions of the catalog",
            "route": "/regions",
            "icon": "map",
            "requires": "testapp.region:view",
            "parent": str(catalog.pk),
            "position": "0",
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    row = NavItem.objects.get(label="Regions of the catalog")
    assert row.parent_id == catalog.pk
    assert ChangeLog.objects.filter(object_id=str(row.pk), action="create").exists()
