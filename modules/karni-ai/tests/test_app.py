"""The module contract: app, fragment, manifest, error codes, architecture, core's independence."""

from __future__ import annotations

import ast
from pathlib import Path

import karni
from django.apps import apps
from karni.errorcodes import registry
from karni.testing import assert_module_manifest

from karni_ai import conf


def test_app_is_installed() -> None:
    assert apps.get_app_config("karni_ai").name == "karni_ai"


def test_settings_fragment_has_no_default_provider_or_model() -> None:
    assert conf.DEFAULTS["KARNI_AI_PROVIDER"] == ""
    assert conf.DEFAULTS["ANTHROPIC_MODEL"] == "" and conf.DEFAULTS["OPENAI_MODEL"] == ""
    assert conf.DEFAULTS["ANTHROPIC_API_KEY"] == "" and conf.DEFAULTS["OPENAI_API_KEY"] == ""


def test_the_manifest_matches_the_module() -> None:
    manifest = assert_module_manifest("karni_ai")
    assert manifest.name == "ai" and manifest.status == "experimental"
    assert [ask.setting for ask in manifest.asks] == ["KARNI_AI_PROVIDER"]


def test_error_codes_are_registered() -> None:
    codes = registry()
    assert all(f"AI{n:03d}" in codes for n in range(1, 17))
    assert codes["AI011"].source.startswith("karni_ai")


def test_karni_core_never_imports_karni_ai() -> None:
    """No module of the karni package names karni_ai: not in an import, not in a string."""
    root = Path(karni.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = [node.value]
            if any(name == "karni_ai" or name.startswith("karni_ai.") for name in names):
                offenders.append(f"{path.relative_to(root)}:{getattr(node, 'lineno', 0)}")
    assert offenders == []


def test_architecture_rules_pass() -> None:
    from karni.testing.architecture import run_checks

    assert run_checks() == []
