"""``KARNI_ADMIN_MENU``: the admin's side menu in groups (site report 2, item 10).

Groups and their items in the order written, only what each user may open
(role grants included), no empty group, superusers' full list with the rest in
a last group, a warning for a label that names nothing, and the project's own
``UNFOLD["SIDEBAR"]`` winning.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import checks
from django.test import Client, RequestFactory, override_settings

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.admin.menu import NAVIGATION, PROJECT, menu_problems, sidebar_navigation
from karni.checks import check_admin_menu
from karni.conf import karni_settings
from karni.conf.validation import validate_settings
from karni.testing._source import project_app_configs

pytestmark = pytest.mark.django_db

ROLES = {
    # What a client's content editor holds: two models of the project and Karni's menu table.
    "content": {
        "grants": {
            "adminapp.widget:*": "all",
            "adminapp.gizmo:view": "all",
            "karni_navigation.navitem:*": "all",
        }
    },
}

MENU = [
    {"title": "Things", "icon": "inventory_2", "items": ["adminapp.Gizmo", "adminapp.widget"]},
    {"title": "Menus", "icon": "menu", "items": ["karni_navigation"]},
    {"title": "People", "icon": "group", "items": ["karni_accounts.User", "karni_accounts.Role"]},
    {"title": "Schedules", "items": ["django_celery_beat"]},
]


@pytest.fixture(autouse=True)
def _roles() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _user(email: str, *, superuser: bool = False, roles: tuple[str, ...] = ()) -> Any:
    users = get_user_model()
    if superuser:
        return users.objects.create_superuser(email=email, password="pw-123456-menu")
    user = users.objects.create_user(email=email, password="pw-123456-menu", is_staff=True)
    for role in roles:
        assign_role(user, role)
    return user


def navigation(user: Any, menu: Any = MENU) -> list[dict[str, Any]]:
    request = RequestFactory().get("/admin/")
    request.user = user
    with override_settings(KARNI_ADMIN_MENU=menu):
        return sidebar_navigation(request)


def titles(found: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    return [
        (str(group["title"]), [str(item["title"]) for item in group["items"]]) for group in found
    ]


def index_titles(site: admin.AdminSite, user: Any) -> list[str]:
    request = RequestFactory().get("/admin/")
    request.user = user
    return [str(entry["name"]) for app in site.get_app_list(request) for entry in app["models"]]


def test_no_setting_keeps_unfolds_list_of_every_app() -> None:
    assert navigation(_user("root@example.com", superuser=True), menu=None) == []


def test_a_content_editor_sees_the_groups_as_written_and_only_what_they_may_open() -> None:
    found = navigation(_user("content@example.com", roles=("content",)))
    assert titles(found) == [
        ("Things", ["Gizmos", "Widgets"]),  # the order written, not the home page's
        ("Menus", ["Navigation items"]),
    ]  # no People (no grant on users or roles), no Schedules, and no last group
    assert [item["icon"] for item in found[0]["items"]] == ["inventory_2", "inventory_2"]
    assert found[0]["items"][1]["link"] == "/admin/adminapp/widget/"


def test_a_user_on_djangos_permissions_sees_what_they_open() -> None:
    user = _user("perms@example.com")
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="django_celery_beat", codename="view_crontabschedule"
        )
    )
    user = get_user_model().objects.get(pk=user.pk)
    assert titles(navigation(user)) == [("Schedules", ["Crontabs"])]


def test_a_superuser_keeps_the_full_list_with_the_rest_last(site: admin.AdminSite) -> None:
    root = _user("root@example.com", superuser=True)
    found = navigation(root)
    assert [group["title"] for group in found] == [
        "Things",
        "Menus",
        "People",
        "Schedules",
        "Other",
    ]
    assert titles(found)[2] == ("People", ["Users", "Roles"])
    other = found[-1]
    assert other["collapsible"] is True
    apps = {
        str(item["title"]): [str(sub["title"]) for sub in item["items"]] for item in other["items"]
    }
    assert apps["Authentication and Authorization"] == ["Groups"]
    assert "Widgets" not in apps["Karni admin test app"]  # named above, so not repeated
    shown = [str(i["title"]) for group in found[:-1] for i in group["items"]]
    shown += [sub for subs in apps.values() for sub in subs]
    assert sorted(shown) == sorted(index_titles(site, root))  # every model once


def test_a_model_named_by_label_wins_over_an_app_label() -> None:
    menu = [
        {"title": "All of it", "items": ["adminapp"]},
        {"title": "Featured", "items": ["adminapp.Widget"]},
    ]
    found = titles(navigation(_user("content@example.com", roles=("content",)), menu))
    assert found == [("All of it", ["Gizmos"]), ("Featured", ["Widgets"])]


def test_an_app_named_by_label_wins_over_project() -> None:
    menu = [
        {"title": "Ours", "items": [PROJECT, PROJECT]},
        {"title": "Admin tests", "items": ["adminapp", "adminapp"]},
    ]
    found = titles(navigation(_user("content@example.com", roles=("content",)), menu))
    assert found == [("Admin tests", ["Gizmos", "Widgets"])]  # each once, Ours left empty


def test_project_stands_for_the_apps_in_the_project_folder() -> None:
    menu = [{"title": "Ours", "items": [PROJECT]}]
    found = navigation(_user("root@example.com", superuser=True), menu)
    ours = {str(item["link"]).split("/")[2] for item in found[0]["items"]}
    own = {config.label for config in project_app_configs(skip_apps=False)}
    assert ours <= own and "adminapp" in ours
    assert "karni_accounts" not in ours and "auth" not in ours and "django_celery_beat" not in ours
    other = {str(item["link"]).split("/")[2] for item in found[-1]["items"]}
    assert {"karni_accounts", "auth", "django_celery_beat"} <= other


def test_titles_are_escaped() -> None:
    from tests.adminapp.models import Widget

    with override_settings(KARNI_ADMIN_MENU=MENU):
        original = Widget._meta.verbose_name_plural
        Widget._meta.verbose_name_plural = "<b>Widgets</b>"
        try:
            found = navigation(_user("root@example.com", superuser=True))
        finally:
            Widget._meta.verbose_name_plural = original
    assert "&lt;b&gt;Widgets&lt;/b&gt;" in [str(item["title"]) for item in found[0]["items"]]


def test_the_page_shows_the_menu() -> None:
    editor = Client()
    editor.force_login(_user("content@example.com", roles=("content",)))
    root = Client()
    root.force_login(_user("root@example.com", superuser=True))
    with override_settings(KARNI_ADMIN_MENU=MENU):
        page = editor.get("/admin/").content.decode()
        everything = root.get("/admin/").content.decode()
    sidebar = page.split('id="nav-sidebar-apps"', 1)[1].split("</nav>", 1)[0]
    assert "Things" in sidebar and "Navigation items" in sidebar
    assert "Schedules" not in sidebar and "Other" not in sidebar
    assert ">Other" in everything.split('id="nav-sidebar-apps"', 1)[1].replace("\n", "").replace(
        " ", ""
    )


# -- the setting's shape, the checks and the escape hatch ----------------------------------


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ({"title": "x"}, "must be None or a list"),
        (["blog"], "must be a mapping"),
        ([{"items": ["blog"]}], "needs a title"),
        ([{"title": "Blog", "items": []}], "must be a list of app labels"),
        ([{"title": "Blog", "items": "blog"}], "must be a list of app labels"),
        ([{"title": "Blog", "items": ["blog"], "icon": 3}], "Material Symbols"),
        ([{"title": "Blog", "items": ["blog"], "order": 1}], "has keys ['order']"),
    ],
)
def test_a_malformed_menu_fails_startup_validation(value: Any, says: str) -> None:
    assert any(says in problem for problem in menu_problems(value))
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev")
    namespace["KARNI_ADMIN_MENU"] = value
    with pytest.raises(Exception, match="KARNI_ADMIN_MENU"):
        validate_settings(namespace)


def test_a_label_that_names_nothing_is_w301() -> None:
    menu = [{"title": "Typos", "items": ["adminap.Widget", "adminapp", "nosuchapp", PROJECT]}]
    with override_settings(KARNI_ADMIN_MENU=menu):
        found = check_admin_menu()
    assert [(m.id, m.level) for m in found] == [("karni.W301", checks.WARNING)] * 2
    assert "'adminap.Widget'" in found[0].msg and "'nosuchapp'" in found[1].msg
    with override_settings(KARNI_ADMIN_MENU=MENU):
        assert check_admin_menu() == []


def test_the_projects_own_sidebar_wins_and_w302_says_so(settings: Any) -> None:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev")
    assert namespace["UNFOLD"]["SIDEBAR"]["navigation"] == NAVIGATION
    own = {"navigation": [{"title": "Mine", "items": [{"title": "Home", "link": "/admin/"}]}]}
    namespace = {"SECRET_KEY": "x" * 50, "UNFOLD": {"SIDEBAR": own}}
    karni_settings(namespace, env_name="dev")
    assert namespace["UNFOLD"]["SIDEBAR"] is own
    settings.KARNI_ADMIN_MENU = MENU
    settings.UNFOLD = {**settings.UNFOLD, "SIDEBAR": own}
    assert [m.id for m in check_admin_menu()] == ["karni.W302"]
