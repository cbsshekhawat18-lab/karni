"""The module contract: app, settings fragment, agent guidance, error codes, checks."""

from __future__ import annotations

from importlib import resources
from importlib.metadata import entry_points

from django.apps import apps
from karni.errorcodes import registry

from karni_site import conf


def test_app_is_installed() -> None:
    assert apps.get_app_config("karni_site").name == "karni_site"


def test_settings_fragment_is_import_light_and_read_through_get() -> None:
    assert set(conf.DEFAULTS) == {
        "KARNI_SITE_IS_ACTIVE",
        "KARNI_SITE_SERVER_ERROR_TEMPLATES",
        "KARNI_SITE_NOT_FOUND_TEMPLATES",
        "KARNI_SITE_SETTINGS_MODEL",
        "KARNI_SITE_HIGHLIGHT",
        "KARNI_SITE_INLINE_TAGS",
        "KARNI_SITE_LINK_SCHEMES",
        "KARNI_SITE_SANITIZER",
        "KARNI_SITE_IMAGE_TYPES",
        "KARNI_SITE_CACHE",
        "KARNI_SITE_CACHE_TIMEOUT",
        "KARNI_SITE_SEED_ON_RENDER",
        "KARNI_SITE_MENU_ROWS",
        "KARNI_SITE_MENU_ROWS_LIMIT",
        "KARNI_SITE_REDIRECTS_BEFORE_VIEWS",
        "KARNI_SITE_EDITOR_ROLE",
        # public forms
        "KARNI_SITE_FORMS",
        "KARNI_SITE_FORM_CLASS",
        "KARNI_SITE_FORM_TEMPLATE",
        "KARNI_SITE_FORM_CLASSES",
        "KARNI_SITE_FORM_PRESETS",
        "KARNI_SITE_FORM_MESSAGES",
        "KARNI_SITE_FORM_REQUIRED_MARK",
        "KARNI_SITE_FORM_SCRIPT",
        "KARNI_SITE_FORM_SENT_PARAM",
        "KARNI_SITE_FORM_PAGE_TEMPLATE",
        "KARNI_SITE_NOTIFY_FROM",
    }
    assert conf.get("KARNI_SITE_SERVER_ERROR_TEMPLATES")[-1] == "karni_site/500.html"


def test_agents_fragment_ships_with_the_package() -> None:
    text = resources.files("karni_site").joinpath("AGENTS.fragment.md").read_text("utf-8")
    assert len(text.strip().splitlines()) <= 15
    assert "karni import design" in text and "{% ifactive" in text and "{% csp_hash %}" in text
    assert "{% editable" in text and "{% get_menu" in text and "site." in text


def test_entry_points_register_codes_and_checks() -> None:
    groups = {
        group: {ep.name for ep in entry_points(group=group)}
        for group in ("karni.settings", "karni.errorcodes", "karni.checks", "karni.roles")
    }
    assert all("site" in names for names in groups.values()), groups
    codes = {code for code in registry() if code.startswith("SITE")}
    assert codes == {f"SITE00{n}" for n in range(1, 10)} | {f"SITE02{n}" for n in range(4)}
