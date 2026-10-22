"""Shared fixtures for karni's test suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from karni.conf import karni_settings

SettingsFactory = Callable[..., dict[str, Any]]


@pytest.fixture(autouse=True)
def _isolate_karni_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ambient environment variables from leaking into in-test settings.

    ``karni_settings()`` reads ``DJANGO_ENV`` (profile selection) and
    ``SENTRY_DSN`` (Sentry initialisation) at call time; clearing them makes
    namespaces assembled inside tests deterministic on any machine.
    """
    for var in ("DJANGO_ENV", "SENTRY_DSN"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def make_settings() -> SettingsFactory:
    """Build a fresh settings namespace through ``karni_settings()``.

    Usage::

        ns = make_settings("prod", preset={"TIME_ZONE": "UTC"}, DEBUG=False)

    ``preset`` seeds the namespace before the call (simulating names defined
    above ``karni_settings(globals())`` in a settings module) and keyword
    arguments are passed through as overrides.
    """

    def _make(
        env_name: str = "dev",
        preset: dict[str, Any] | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        namespace: dict[str, Any] = dict(preset or {})
        karni_settings(namespace, env_name=env_name, **overrides)
        return namespace

    return _make


@pytest.fixture(autouse=True, scope="session")
def _capture_outside_the_package(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Tests that turn DEBUG on capture into a temporary ``.karni/``, never packages/karni/."""
    from karni.debug import store

    root = tmp_path_factory.mktemp("capture") / ".karni"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store, "capture_root", lambda: root)
        yield
