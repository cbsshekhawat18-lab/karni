"""The catalog entry, karni_reports/karni.module.toml, matches the module."""

from __future__ import annotations

from karni.testing import assert_module_manifest


def test_the_manifest_matches_the_module() -> None:
    manifest = assert_module_manifest("karni_reports")
    assert manifest.name == "reports" and manifest.status == "experimental"
    assert [ask.setting for ask in manifest.asks] == ["KARNI_REPORTS_PAGE_SIZE"]
