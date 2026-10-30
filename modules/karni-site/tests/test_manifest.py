"""The catalog entry, karni_site/karni.module.toml, matches the module."""

from __future__ import annotations

from karni.testing import assert_module_manifest


def test_the_manifest_matches_the_module() -> None:
    manifest = assert_module_manifest("karni_site")
    assert manifest.name == "site"
