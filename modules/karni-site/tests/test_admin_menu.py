"""``KARNI_SITE_ADMIN_MENU``: the admin's side menu a site project starts with.

A site project's settings say ``KARNI_ADMIN_MENU = KARNI_SITE_ADMIN_MENU``:
the project's apps, then this module's pages, then the people. The technical
apps (task results, schedules, tokens, sign-in codes) show to superusers only.
"""

from __future__ import annotations

from typing import Any

from django.test import Client, RequestFactory
from karni.admin.menu import sidebar_navigation
from karni.checks import check_admin_menu
from pytest_django import Settings

from tests.conftest import make_user

TECHNICAL = ("Periodic task tracks", "Login codes", "One time tokens", "Task results")


def menu(user: Any, settings: Settings) -> list[tuple[str, list[str]]]:
    settings.KARNI_ADMIN_MENU = settings.KARNI_SITE_ADMIN_MENU
    request = RequestFactory().get("/admin/")
    request.user = user
    return [
        (str(group["title"]), [str(item["title"]) for item in group["items"]])
        for group in sidebar_navigation(request)
    ]


def test_the_menu_names_only_installed_labels(settings: Settings) -> None:
    assert [group["title"] for group in settings.KARNI_SITE_ADMIN_MENU] == [
        "Content",
        "Site",
        "People",
    ]
    settings.KARNI_ADMIN_MENU = settings.KARNI_SITE_ADMIN_MENU
    assert check_admin_menu() == []


def test_the_editor_sees_the_sites_pages_only(editor: Any, settings: Settings) -> None:
    assert menu(editor, settings) == [
        ("Site", ["Menus", "Page content", "Page titles and descriptions", "Site settings"])
    ]


def test_a_staff_client_sees_content_site_and_people_and_nothing_technical(
    roles: None, settings: Settings
) -> None:
    found = menu(make_user("client@example.com", "staff", staff=True), settings)
    assert [title for title, _items in found] == ["Content", "Site", "People"]
    assert found[2] == ("People", ["Users", "Roles"])
    assert "Redirects" in found[1][1]
    shown = [item for _title, items in found for item in items]
    assert not set(TECHNICAL) & set(shown)


def test_the_owner_keeps_everything_with_the_rest_last(owner: Any, settings: Settings) -> None:
    found = menu(owner, settings)
    assert [title for title, _items in found] == ["Content", "Site", "People", "Other"]
    assert "Authentication and Authorization" in found[-1][1]


def test_the_page_shows_it_to_the_editor(editor: Any, settings: Settings) -> None:
    settings.KARNI_ADMIN_MENU = settings.KARNI_SITE_ADMIN_MENU
    client = Client()
    client.force_login(editor)
    sidebar = client.get("/admin/").content.decode().split('id="nav-sidebar-apps"', 1)[1]
    assert "Page content" in sidebar.split("</nav>", 1)[0]
    assert "People" not in sidebar.split("</nav>", 1)[0]
