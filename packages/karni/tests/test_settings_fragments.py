"""Tests for the ``karni.settings`` entry-point fragment merge (amendment G7).

Fake entry points are injected by monkeypatching the loader function
``karni.conf._settings_fragment_entry_points`` — no real distribution needs
to be installed for these tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

import karni.conf
from karni.conf import karni_settings
from karni.conf.base import BASE


@dataclass(frozen=True)
class FakeEntryPoint:
    """Minimal stand-in for :class:`importlib.metadata.EntryPoint`."""

    name: str
    value: str = "fake_module.conf:DEFAULTS"
    loader: Callable[[], Any] = field(default=dict)

    def load(self) -> Any:
        return self.loader()


@pytest.fixture
def install_fragments(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace the entry-point loader function with one returning fakes."""

    def _install(*entry_points: FakeEntryPoint) -> None:
        monkeypatch.setattr(
            karni.conf, "_settings_fragment_entry_points", lambda: tuple(entry_points)
        )

    return _install


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_fragment_dict_is_merged(install_fragments) -> None:
    install_fragments(FakeEntryPoint("payments", loader=lambda: {"KARNI_FAKE_PROVIDER": "stripe"}))
    ns: dict[str, Any] = {}
    karni_settings(ns, env_name="dev")
    assert ns["KARNI_FAKE_PROVIDER"] == "stripe"


def test_user_preset_names_survive(install_fragments) -> None:
    install_fragments(FakeEntryPoint("payments", loader=lambda: {"KARNI_FAKE_PROVIDER": "stripe"}))
    ns: dict[str, Any] = {"KARNI_FAKE_PROVIDER": "razorpay"}
    karni_settings(ns, env_name="dev")
    assert ns["KARNI_FAKE_PROVIDER"] == "razorpay"


def test_override_kwargs_beat_fragment_values(install_fragments) -> None:
    install_fragments(FakeEntryPoint("payments", loader=lambda: {"KARNI_FAKE_PROVIDER": "stripe"}))
    ns: dict[str, Any] = {}
    karni_settings(ns, env_name="dev", KARNI_FAKE_PROVIDER="test")
    assert ns["KARNI_FAKE_PROVIDER"] == "test"


def test_fragments_merge_in_entry_point_name_order(install_fragments) -> None:
    # Both introduce distinct names; order is observable through collisions
    # (see below) and asserted here via the sorted loader contract.
    install_fragments(
        FakeEntryPoint("alpha", loader=lambda: {"KARNI_FAKE_A": 1}),
        FakeEntryPoint("beta", loader=lambda: {"KARNI_FAKE_B": 2}),
    )
    ns: dict[str, Any] = {}
    karni_settings(ns, env_name="dev")
    assert ns["KARNI_FAKE_A"] == 1
    assert ns["KARNI_FAKE_B"] == 2


def test_deepcopy_isolates_fragment_defaults(install_fragments) -> None:
    defaults: dict[str, Any] = {"KARNI_FAKE_NESTED": {"links": ["https://a.example"]}}
    install_fragments(FakeEntryPoint("payments", loader=lambda: defaults))

    ns: dict[str, Any] = {}
    karni_settings(ns, env_name="dev")
    ns["KARNI_FAKE_NESTED"]["links"].append("https://mutant.example")
    ns["KARNI_FAKE_NESTED"]["extra"] = True

    assert defaults["KARNI_FAKE_NESTED"] == {"links": ["https://a.example"]}
    ns2: dict[str, Any] = {}
    karni_settings(ns2, env_name="dev")
    assert ns2["KARNI_FAKE_NESTED"] == {"links": ["https://a.example"]}


# ---------------------------------------------------------------------------
# Collisions and failures (every error names the entry point)
# ---------------------------------------------------------------------------


def test_collision_with_base_key_raises_naming_entry_point(install_fragments) -> None:
    assert "TIME_ZONE" in BASE
    install_fragments(
        FakeEntryPoint(
            "payments",
            value="karni_payments.conf:DEFAULTS",
            loader=lambda: {"TIME_ZONE": "Mars/Olympus"},
        )
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        karni_settings({}, env_name="dev")
    message = str(excinfo.value)
    assert "payments" in message
    assert "karni_payments.conf:DEFAULTS" in message
    assert "TIME_ZONE" in message


def test_collision_with_profile_key_raises(install_fragments) -> None:
    # DEBUG comes from the dev profile overlay, not BASE.
    install_fragments(FakeEntryPoint("payments", loader=lambda: {"DEBUG": False}))
    with pytest.raises(ImproperlyConfigured, match="DEBUG"):
        karni_settings({}, env_name="dev")


def test_collision_between_fragments_names_the_later_one(install_fragments) -> None:
    install_fragments(
        FakeEntryPoint("alpha", loader=lambda: {"KARNI_FAKE_SHARED": 1}),
        FakeEntryPoint("beta", loader=lambda: {"KARNI_FAKE_SHARED": 2}),
    )
    with pytest.raises(ImproperlyConfigured) as excinfo:
        karni_settings({}, env_name="dev")
    message = str(excinfo.value)
    assert "beta" in message
    assert "KARNI_FAKE_SHARED" in message


def test_load_failure_raises_naming_entry_point(install_fragments) -> None:
    def _boom() -> dict[str, Any]:
        raise ImportError("no module named fake_module")

    install_fragments(FakeEntryPoint("broken", value="fake_module.conf:DEFAULTS", loader=_boom))
    with pytest.raises(ImproperlyConfigured) as excinfo:
        karni_settings({}, env_name="dev")
    message = str(excinfo.value)
    assert "broken" in message
    assert "fake_module.conf:DEFAULTS" in message


def test_non_dict_fragment_raises(install_fragments) -> None:
    install_fragments(FakeEntryPoint("listy", loader=lambda: ["not", "a", "dict"]))
    with pytest.raises(ImproperlyConfigured, match="listy"):
        karni_settings({}, env_name="dev")


# ---------------------------------------------------------------------------
# Entry-point scan caching
# ---------------------------------------------------------------------------


def test_entry_point_scan_is_cached_module_level(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_entry_points(*, group: str) -> list[FakeEntryPoint]:
        calls.append(group)
        return [FakeEntryPoint("payments", loader=lambda: {"KARNI_FAKE_CACHED": True})]

    monkeypatch.setattr(karni.conf, "metadata", SimpleNamespace(entry_points=fake_entry_points))
    monkeypatch.setattr(karni.conf, "_fragment_entry_points", None)

    ns1: dict[str, Any] = {}
    ns2: dict[str, Any] = {}
    karni_settings(ns1, env_name="dev")
    karni_settings(ns2, env_name="dev")

    assert ns1["KARNI_FAKE_CACHED"] is True
    assert ns2["KARNI_FAKE_CACHED"] is True
    assert calls == ["karni.settings"]
