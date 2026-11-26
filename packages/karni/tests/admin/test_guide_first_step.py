"""The guide's first step names a model of the project's own apps (site report 2, item 3).

"Add your first record" links the first model, in the order of the admin
index, that the user may add to, among the apps whose code lives in the project
(not Django's, not Karni's or a Karni module's, not a third-party app's). Only a
project with no model of its own falls back to any model the user may add to.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import RequestFactory, override_settings

from karni.accounts.permissions import assign_role
from karni.accounts.roles import sync_roles
from karni.admin.guide import guide_context
from karni.testing._source import project_app_configs

pytestmark = pytest.mark.django_db

ROLES = {
    # What a site's content editor holds: Karni's own pages (here the navigation menu,
    # a karni.* app as karni-site's pages are) and one model of the project.
    "content": {"grants": {"karni_navigation.navitem:*": "all", "adminapp.widget:*": "all"}},
    "karni_only": {"grants": {"karni_navigation.navitem:*": "all"}},
}


@pytest.fixture(autouse=True)
def _roles() -> Iterator[None]:
    with override_settings(KARNI_ROLES=ROLES):
        sync_roles()
        yield


def _user(
    email: str, *, superuser: bool = False, roles: tuple[str, ...] = (), perms: tuple[str, ...] = ()
) -> Any:
    users = get_user_model()
    if superuser:
        return users.objects.create_superuser(email=email, password="pw-123456-guide")
    user = users.objects.create_user(email=email, password="pw-123456-guide", is_staff=True)
    for role in roles:
        assign_role(user, role)
    for perm in perms:
        app_label, codename = perm.split(".")
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app_label, codename=codename)
        )
    return get_user_model().objects.get(pk=user.pk)  # a fresh permission cache


def first_step(site: admin.AdminSite, user: Any) -> dict[str, Any]:
    request = RequestFactory().get("/admin/")
    request.user = user
    context = guide_context(site, request)
    assert context is not None
    step: dict[str, Any] = context["steps"][0]
    return step


def own_labels() -> set[str]:
    return {config.label for config in project_app_configs(skip_apps=False)}


def test_a_superuser_is_sent_to_a_model_of_the_project(site: admin.AdminSite) -> None:
    step = first_step(site, _user("root@example.com", superuser=True))
    assert step["label"] != "Groups"
    app_label = step["url"].split("/")[2]  # /admin/<app_label>/<model>/add/
    assert app_label in own_labels(), step


def test_groups_lose_to_the_project_model_the_user_may_add_to(site: admin.AdminSite) -> None:
    """The site case: a user who may add groups and the project's widgets is sent to widgets."""
    user = _user(
        "both@example.com", perms=("auth.add_group", "auth.view_group", "adminapp.add_widget")
    )
    step = first_step(site, user)
    assert step["label"] == "Widgets"
    assert step["url"] == "/admin/adminapp/widget/add/"


def test_a_content_editor_is_sent_to_the_projects_model_not_karnis(site: admin.AdminSite) -> None:
    step = first_step(site, _user("content@example.com", roles=("content",)))
    assert (step["label"], step["url"]) == ("Widgets", "/admin/adminapp/widget/add/")


def test_a_user_who_may_add_only_to_a_third_party_model_gets_no_link(site: admin.AdminSite) -> None:
    """The project has models of its own, so a celery-beat schedule is not the first record."""
    user = _user("beat@example.com", perms=("django_celery_beat.add_periodictask",))
    step = first_step(site, user)
    assert (step["url"], step["label"]) == ("", "")
    assert step["text"] == "Open a section from the list and press Add."


def test_a_user_who_may_add_only_to_karnis_pages_gets_no_link(site: admin.AdminSite) -> None:
    step = first_step(site, _user("menus@example.com", roles=("karni_only",)))
    assert step["url"] == ""


def test_a_project_with_no_model_of_its_own_falls_back_to_any_model(
    site: admin.AdminSite, tmp_path: Path
) -> None:
    """Every app lives outside the project folder: the first model the user may add to."""
    with override_settings(BASE_DIR=tmp_path):
        assert own_labels() == set()
        assert first_step(site, _user("root@example.com", superuser=True))["label"] == "Groups"
        beat = _user("beat@example.com", perms=("django_celery_beat.add_periodictask",))
        assert first_step(site, beat)["label"] == "Periodic tasks"
