"""The catalog entry, karni_storage/karni.module.toml, matches the module."""

from __future__ import annotations

from karni.testing import assert_module_manifest


def test_the_manifest_matches_the_module() -> None:
    manifest = assert_module_manifest("karni_storage")
    assert manifest.name == "storage"
    assert manifest.status == "experimental"
    assert manifest.wiring.urls == 'path("api/", include("karni_storage.urls"))'
    assert [ask.setting for ask in manifest.asks] == ["KARNI_STORAGE_PROVIDER"]
