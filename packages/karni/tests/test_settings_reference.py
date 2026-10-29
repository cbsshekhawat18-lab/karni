"""docs/settings.md is generated from karni/conf/base.py: it must never go stale."""

from __future__ import annotations

import re
from pathlib import Path

from karni.conf import reference
from karni.conf.validation import KarniSettingsModel

DOCS = Path(__file__).resolve().parents[3] / "docs" / "settings.md"


def test_docs_settings_md_is_fresh() -> None:
    assert DOCS.read_text(encoding="utf-8") == reference.render(), (
        "docs/settings.md is stale — regenerate: python -m karni.conf.reference > docs/settings.md"
    )


def test_every_setting_has_a_description_and_the_model_is_covered() -> None:
    found = {setting.name: setting for setting in reference.settings()}
    undocumented = [name for name, setting in found.items() if not setting.description]
    assert not undocumented, f"add these to karni.conf.reference.DESCRIPTIONS: {undocumented}"
    source = reference.BASE_SOURCE.read_text(encoding="utf-8")
    declared = set(re.findall(r'^\s+"(KARNI_[A-Z0-9_]+)":', source, re.M))
    assert declared <= set(found), f"settings the parser missed: {sorted(declared - set(found))}"
    validated = {name for name in KarniSettingsModel.model_fields if name.startswith("KARNI_")}
    page = reference.render()
    missing = [name for name in validated if f"`{name}`" not in page]
    assert not missing, f"validated settings absent from the page: {missing}"


def test_env_and_defaults_are_read_from_the_source() -> None:
    found = {setting.name: setting for setting in reference.settings()}
    assert found["KARNI_AUTH_MODE"].env == "KARNI_AUTH_MODE"
    assert found["KARNI_AUTH_MODE"].default == '"jwt"'
    assert found["KARNI_MAX_PAGE_SIZE"].default == "100"
    assert found["KARNI_ADMIN_LIST_DISPLAY_MAX"].env is None
    assert found["KARNI_SEED_LOGINS"].env == "KARNI_SEED_LOGINS"


def test_every_modules_settings_are_on_the_page_with_an_anchor() -> None:
    files = reference.module_conf_files()
    assert {name for name, _path in files} >= {"karni-site", "karni-payments"}
    page = DOCS.read_text(encoding="utf-8")
    assert "## Module settings" in page and "### karni-site" in page
    for module, path in files:
        found = reference.module_settings(path, module)
        assert found, module
        for setting in found:
            assert setting.description, f"{module}: {setting.name} has no comment in conf.py"
            assert f'<a id="{reference.anchor(setting.name)}"></a>`{setting.name}`' in page
    # Karni's own rows have anchors too: karni explain links each one.
    assert '<a id="karni_auth_mode"></a>`KARNI_AUTH_MODE`' in page


def test_lookup_finds_karnis_and_a_modules_setting() -> None:
    core = reference.lookup("karni_auth_mode")
    assert core is not None and core.module == "" and core.env == "KARNI_AUTH_MODE"
    site = reference.lookup("KARNI_SITE_HIGHLIGHT")
    assert site is not None and site.module == "karni-site" and site.env is None
    assert site.default == '{"marker": "==", "tag": "mark", "class": ""}'
    assert "highlight" in site.description
    multi = reference.lookup("KARNI_SITE_PUBLISHED_FIELDS")
    assert multi is not None and multi.default.startswith('["published", "is_published"')
    assert reference.lookup("KARNI_NO_SUCH_SETTING") is None


def test_the_module_parser_reads_comments_variables_and_blocks(tmp_path: Path) -> None:
    conf = tmp_path / "conf.py"
    conf.write_text(
        "DEFAULTS = {\n"
        "    # The first one.\n"
        '    "SHOP_COLOUR": env("SHOP_COLOUR", default="blue"),\n'
        '    "SHOP_SIZE": 3,\n'
        "}\n"
        "DEFAULTS |= {\n"
        "    # Kept over\n"
        "    # two lines.\n"
        '    "SHOP_TAGS": [\n        "a",\n        "b",\n    ],\n'
        "}\n",
        encoding="utf-8",
    )
    found = reference.module_settings(conf, "karni-shop")
    assert [(s.name, s.env, s.default, s.description) for s in found] == [
        ("SHOP_COLOUR", "SHOP_COLOUR", '"blue"', "The first one."),
        ("SHOP_SIZE", None, "3", "The first one."),  # no comment: the one above
        ("SHOP_TAGS", None, '["a", "b"]', "Kept over two lines."),
    ]
