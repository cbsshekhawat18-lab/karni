"""karni.catalog: the manifest format, Karni's feature manifests, discovery, and the
assert_module_manifest helper."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from karni import catalog
from karni.conf.base import BASE
from karni.introspect import features_section
from karni.testing import assert_module_manifest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

MODULE = """
name = "demo"
kind = "module"
title = "Demo"
purpose = "A module for the tests."
status = "experimental"
use_when = ["demo"]

[provides]
models = ["Thing"]
settings = { KARNI_DEMO_SIZE = "integer", KARNI_DEMO_MODE = ["string", "null"] }

[[asks]]
question = "Which mode?"
setting = "KARNI_DEMO_MODE"
options = ["fast", "slow"]
default = "fast"

[wiring]
apps = ["karni_demo"]
settings = "karni_demo.conf:DEFAULTS"
urls = 'path("demo/", include("karni_demo.urls"))'

[[wiring.middleware]]
path = "karni_demo.middleware.DemoMiddleware"
why = "the demo"
"""


def _problems(text: str) -> list[str]:
    with pytest.raises(catalog.ManifestError) as caught:
        catalog.parse_text(text, "demo.toml")
    return caught.value.problems


def test_a_module_manifest_parses() -> None:
    manifest = catalog.parse_text(MODULE, "demo.toml")
    assert manifest.app == "karni_demo" and manifest.distribution == "karni-demo"
    assert manifest.provides.settings["KARNI_DEMO_MODE"] == ("string", "null")
    assert manifest.wiring.middleware[0].path == "karni_demo.middleware.DemoMiddleware"
    assert manifest.asks[0].has_default and manifest.asks[0].default == "fast"
    data = manifest.to_dict()
    assert data["wiring"]["urls"] == 'path("demo/", include("karni_demo.urls"))'
    assert json.loads(json.dumps(data)) == data


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (('kind = "module"', 'kind = "plugin"'), "kind must be one of module, feature"),
        (('title = "Demo"\n', ""), "needs the key 'title'"),
        (('status = "experimental"', 'status = "beta"'), "manifest.status 'beta' is not valid"),
        (('use_when = ["demo"]', 'use_when = "demo"'), "use_when must be a list"),
        (('purpose = "A module for the tests."', f'purpose = "{"x" * 81}"'), "at most 80"),
        (('name = "demo"', 'name = "demo"\ncolour = "red"'), "unknown key 'colour'"),
        (('name = "demo"', 'name = "demo"\nswitch = "KARNI_DEMO_SIZE"'), "is for a feature"),
        (('"integer"', '"number"'), "KARNI_DEMO_SIZE must be one of"),
        (('setting = "KARNI_DEMO_MODE"', 'setting = "KARNI_OTHER"'), "not one of provides"),
        (('default = "fast"', 'default = "turbo"'), "is not one of its options"),
        (('apps = ["karni_demo"]', "apps = []"), "must name the module's app"),
        (('use_when = ["demo"]', 'use_when = ["demo"]\nrequires = ["demo"]'), "names itself"),
        (("urls = 'path(", "urls = 'route("), "wiring.urls"),
        (("[wiring]", "[wiring]\nextras = { stripe = 3 }"), "wiring.extras.stripe"),
    ],
)
def test_an_invalid_manifest_lists_its_problem(change: tuple[str, str], problem: str) -> None:
    text = MODULE.replace(*change)
    assert text != MODULE
    assert any(problem in found for found in _problems(text)), _problems(text)


def test_every_problem_is_reported_at_once() -> None:
    text = MODULE.replace('status = "experimental"', 'status = "beta"').replace(
        'title = "Demo"\n', ""
    )
    assert len(_problems(text)) == 2
    assert _problems("not = [toml")[0].startswith("not valid TOML")


def test_a_feature_cannot_take_wiring_and_needs_a_switch() -> None:
    feature = MODULE.replace('kind = "module"', 'kind = "feature"')
    problems = _problems(feature)
    assert any("'wiring' is for a module" in p for p in problems)
    assert any("needs the key 'switch'" in p for p in problems)


# Karni's own features ------------------------------------------------------------------


def test_the_feature_manifests_name_real_settings_and_extras() -> None:
    features = catalog.features()
    assert [f.name for f in features] == [
        "api_cache",
        "email_code_login",
        "social_login",
        "terms",
        "two_factor",
    ]
    extras = tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    for feature in features:
        assert feature.switch in BASE, feature.name
        missing = set(feature.provides.settings) - set(BASE)
        assert not missing, (feature.name, missing)
        if feature.extra:
            assert feature.extra.removeprefix("karni[").removesuffix("]") in extras
        for ask in feature.asks:
            assert ask.setting.split(".", 1)[0] in feature.provides.settings
    assert catalog.check_catalog(features) == []


def test_the_catalog_checks_names_between_manifests() -> None:
    module = catalog.parse_text(MODULE.replace('use_when = ["demo"]', 'use_when = ["x"]'), "m")
    needing = catalog.parse_text(
        MODULE.replace('name = "demo"', 'name = "other"').replace(
            'use_when = ["demo"]', 'use_when = ["x"]\nrequires = ["nowhere"]'
        ),
        "other.toml",
    )
    feature_text = (catalog.FEATURES_DIR / "terms.toml").read_text()
    feature = catalog.parse_text(
        feature_text.replace("[provides]", 'requires = ["demo"]\n\n[provides]'), "f"
    )
    problems = catalog.check_catalog([module, needing, feature, module])
    assert any("names 'nowhere', not in the catalog" in p for p in problems)
    assert any("a feature cannot require a module" in p for p in problems)
    assert any("the name 'demo' is taken" in p for p in problems)


def test_features_section_names_the_features_that_are_on(settings) -> None:
    settings.KARNI_2FA = False
    settings.KARNI_TERMS = None
    settings.KARNI_API_CACHE = False
    settings.KARNI_EMAIL_OTP = False
    settings.KARNI_SOCIAL_TOKEN_PROVIDERS = {}
    assert features_section() == "FEATURES: none"
    settings.KARNI_2FA = True
    settings.KARNI_TERMS = {"version": "1", "url": "/terms/"}
    assert features_section() == "FEATURES: terms two_factor"


def test_python_m_karni_catalog_prints_the_installed_manifests() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "karni.catalog"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    found = json.loads(proc.stdout)
    for name, entry in found.items():
        manifest = catalog.parse_text(entry["text"], entry["source"])
        assert manifest.name == name and manifest.kind == "module"


# assert_module_manifest ----------------------------------------------------------------


@pytest.fixture
def demo_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An installed ``karni-demo``: its package, settings fragment and karni.modules entry point."""
    package = tmp_path / "karni_demo"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "conf.py").write_text('DEFAULTS = {"KARNI_DEMO_SIZE": 3, "KARNI_DEMO_MODE": None}\n')
    (package / "karni.module.toml").write_text(MODULE)
    dist = tmp_path / "karni_demo-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: karni-demo\nVersion: 1.0\n")
    (dist / "entry_points.txt").write_text("[karni.modules]\ndemo = karni_demo\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield package
    for name in [m for m in sys.modules if m == "karni_demo" or m.startswith("karni_demo.")]:
        del sys.modules[name]


def test_assert_module_manifest_passes_for_a_matching_module(demo_module: Path) -> None:
    manifest = assert_module_manifest("karni_demo")
    assert manifest.name == "demo"
    assert "demo" in {m.name for m in catalog.installed()}


def test_assert_module_manifest_names_each_mismatch(demo_module: Path) -> None:
    (demo_module / "conf.py").write_text(
        'DEFAULTS = {"KARNI_DEMO_SIZE": 3, "KARNI_DEMO_EXTRA": 1}\n'
    )
    with pytest.raises(AssertionError) as caught:
        assert_module_manifest("karni_demo")
    message = str(caught.value)
    assert "provides.settings not in DEFAULTS: KARNI_DEMO_MODE" in message
    assert "DEFAULTS keys not in provides.settings: KARNI_DEMO_EXTRA" in message
    (demo_module / "karni.module.toml").write_text(MODULE.replace('kind = "module"', ""))
    with pytest.raises(AssertionError, match="is not valid"):
        assert_module_manifest("karni_demo")
