"""``KARNI_ADMIN_LOGO``: no logo by default, Karni's mark on request, a project's own paths.

Every admin page declares a favicon: the logo's icon, else a neutral icon Karni
ships, so no browser asks for ``/favicon.ico`` and gets a 404 (site report 2, item 8).

The admin reads the setting on every request, so a value assigned after
``karni_settings()`` (``override_settings`` here) shows in the header and on
the login screen.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.contrib import admin
from django.contrib.staticfiles import finders
from django.test import Client, override_settings

from karni.admin.apps import LOGIN_TEMPLATE, use_login_template
from karni.conf import karni_settings
from karni.conf.admin_logo import (
    DEFAULT_ICON,
    KARNI_MARK,
    logo_paths,
    site_favicon,
    site_icon,
    site_logo,
    unfold_logo_entries,
)
from karni.conf.validation import validate_settings
from karni.exceptions import KarniImproperlyConfigured


def _settings(**overrides: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"SECRET_KEY": "x" * 50}
    karni_settings(namespace, env_name="dev", **overrides)
    return namespace


def test_no_logo_by_default() -> None:
    unfold = _settings()["UNFOLD"]
    assert unfold["SITE_LOGO"] is site_logo and unfold["SITE_ICON"] is site_icon
    assert site_logo(None) is None and site_icon(None) is None
    assert unfold_logo_entries(None) == {} and unfold_logo_entries("") == {}


@pytest.mark.django_db
def test_karni_mark_is_shipped_as_static_files() -> None:
    for path in KARNI_MARK.values():
        assert finders.find(path), path
    with override_settings(KARNI_ADMIN_LOGO="karni"):
        logo, icon = site_logo(None), site_icon(None)
    assert logo is not None and icon is not None
    assert logo["light"].endswith("/karni/brand/karni-mark.svg")
    assert logo["dark"].endswith("/karni/brand/karni-mark-light.svg")
    assert icon["light"].endswith("/karni/brand/karni-mark-simple.svg")


def test_project_paths_with_fallbacks() -> None:
    assert logo_paths({"light": "img/mark.svg"}) == {
        "light": "img/mark.svg",
        "dark": "img/mark.svg",
        "icon": "img/mark.svg",
    }
    entries = unfold_logo_entries({"light": "img/mark.svg"})
    assert entries["SITE_LOGO"]["dark"](None).endswith("/img/mark.svg")
    with override_settings(KARNI_ADMIN_LOGO={"light": "img/a.svg", "dark": "img/b.svg"}):
        logo = site_logo(None)
    assert logo is not None and logo["dark"].endswith("/img/b.svg")


def test_explicit_unfold_keys_win() -> None:
    unfold = _settings(
        KARNI_ADMIN_LOGO="karni", UNFOLD={"SITE_LOGO": "mine.svg", "SITE_TITLE": "Ops"}
    )["UNFOLD"]
    assert unfold["SITE_LOGO"] == "mine.svg" and unfold["SITE_ICON"] is site_icon


def test_bad_declaration_is_e303() -> None:
    with pytest.raises(KarniImproperlyConfigured, match="E303"):
        unfold_logo_entries({"dark": "x.svg"})
    with pytest.raises(KarniImproperlyConfigured, match="E303"):
        _settings(KARNI_ADMIN_LOGO=["karni"])


def test_a_bad_value_assigned_after_the_call_fails_startup_validation() -> None:
    namespace = _settings()
    namespace["KARNI_ADMIN_LOGO"] = {"dark": "x.svg"}
    with pytest.raises(KarniImproperlyConfigured, match="E303"):
        validate_settings(namespace)


# The real admin: the setting is read per request, after the call.


def test_the_admin_site_gets_the_logo_login_page() -> None:
    assert admin.site.login_template == LOGIN_TEMPLATE

    class Site:
        login_template = "mine/login.html"

    own = Site()
    use_login_template(own)
    assert own.login_template == "mine/login.html"


@pytest.mark.django_db
def test_the_login_screen_shows_the_logo_assigned_after_the_call(client: Client) -> None:
    plain = client.get("/admin/login/")
    assert plain.status_code == 200
    assert "karni-mark" not in plain.content.decode()

    with override_settings(KARNI_ADMIN_LOGO="karni"):
        page = client.get("/admin/login/").content.decode()
    assert "/karni/brand/karni-mark.svg" in page
    assert "/karni/brand/karni-mark-light.svg" in page
    assert page.index("karni-mark.svg") < page.index('id="login-form"')


@pytest.mark.django_db
def test_the_header_shows_the_logo_assigned_after_the_call(admin_client: Client) -> None:
    with override_settings(KARNI_ADMIN_LOGO={"light": "img/ours.svg"}):
        page = admin_client.get("/admin/").content.decode()
    assert "/img/ours.svg" in page


# -- the favicon (every admin page, the login page included) ---------------------------

ICON_LINK = re.compile(r'<link\s+rel="icon"\s+href="([^"]+)"')


def test_the_favicon_is_karnis_neutral_icon_without_a_logo() -> None:
    (entry,) = _settings()["UNFOLD"]["SITE_FAVICONS"]
    assert entry == {"rel": "icon", "href": site_favicon}
    assert finders.find(DEFAULT_ICON)
    assert site_favicon(None).endswith("/karni/admin-icon.svg")


def test_the_favicon_is_the_logos_icon() -> None:
    with override_settings(KARNI_ADMIN_LOGO="karni"):
        assert site_favicon(None).endswith("/karni/brand/karni-mark-simple.svg")
    with override_settings(KARNI_ADMIN_LOGO={"light": "img/mark.svg", "icon": "img/icon.png"}):
        assert site_favicon(None).endswith("/img/icon.png")
    with override_settings(KARNI_ADMIN_LOGO={"light": "img/mark.svg"}):
        assert site_favicon(None).endswith("/img/mark.svg")  # the icon falls back to light


def test_a_projects_own_favicons_win() -> None:
    assert _settings(UNFOLD={"SITE_FAVICONS": []})["UNFOLD"]["SITE_FAVICONS"] == []
    mine = [{"rel": "icon", "href": "/static/mine.ico"}]
    assert _settings(UNFOLD={"SITE_FAVICONS": mine})["UNFOLD"]["SITE_FAVICONS"] == mine


@pytest.mark.django_db
def test_every_admin_page_declares_the_favicon(client: Client, admin_client: Client) -> None:
    from django.urls import reverse

    from tests.adminapp.models import Widget

    widget = Widget.objects.create(name="Bolt")
    pages = [
        "admin:index",
        ("admin:app_list", "adminapp"),
        "admin:adminapp_widget_changelist",
        "admin:adminapp_widget_add",
        ("admin:adminapp_widget_change", widget.pk),
        ("admin:adminapp_widget_delete", widget.pk),
        ("admin:adminapp_widget_history", widget.pk),
        "admin:adminapp_widget_import",
        "admin:password_change",
        "admin:karni_api_cache",
        "admin:karni_accounts_rolepermission_permission_matrix",
    ]
    login = client.get(reverse("admin:login")).content.decode()
    assert ICON_LINK.findall(login) == ["/static/karni/admin-icon.svg"], "login"
    for page in pages:
        name, *args = page if isinstance(page, tuple) else (page,)
        response = admin_client.get(reverse(name, args=args))
        assert response.status_code == 200, (name, response.status_code)
        icons = ICON_LINK.findall(response.content.decode())
        assert icons == ["/static/karni/admin-icon.svg"], (name, icons)
    with override_settings(KARNI_ADMIN_LOGO="karni"):
        index = admin_client.get(reverse("admin:index")).content.decode()
        signed_out = client.get(reverse("admin:login")).content.decode()
    for html in (index, signed_out):
        assert ICON_LINK.findall(html) == ["/static/karni/brand/karni-mark-simple.svg"]
