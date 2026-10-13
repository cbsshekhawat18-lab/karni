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
