"""KarniRouter autodiscovery: conventions, conflicts, idempotence, the factory."""

from __future__ import annotations

import importlib
import logging
from typing import Any

import pytest

from karni.api.routers import KarniRouter, get_default_router, kebab
from karni.api.viewsets import BaseViewSet
from tests.testapp.models import Event, Tag, Venue
from tests.testapp.viewsets import EventViewSet, TagViewSet, VenueViewSet

ROUTER_LOGGER = "karni.api.routers"


def _discovered() -> KarniRouter:
    router = KarniRouter()
    router.autodiscover()
    return router


def _by_prefix(router: KarniRouter) -> dict[str, type[Any]]:
    return {prefix: viewset for prefix, viewset, _ in router.registry}


def _inject_viewset(monkeypatch: pytest.MonkeyPatch, name: str, viewset: type[Any]) -> None:
    """Add a viewset to the testapp's viewsets module for one test."""
    module = importlib.import_module("tests.testapp.viewsets")
    viewset.__module__ = module.__name__
    monkeypatch.setattr(module, name, viewset, raising=False)


def test_autodiscovers_declared_viewsets_at_kebab_plural_prefixes() -> None:
    registry = _by_prefix(_discovered())
    assert "events" in registry
    assert "venues" in registry
    assert registry["events"].model is Event
    assert registry["venues"].model is Venue


def test_auto_register_false_is_skipped() -> None:
    router = _discovered()
    assert TagViewSet not in {viewset for _, viewset, _ in router.registry}
    assert "tags" not in _by_prefix(router)


def test_basename_is_app_label_dash_kebab_model() -> None:
    router = _discovered()
    basenames = {
        viewset: basename for _, viewset, basename in router.registry if viewset.model is Event
    }
    expected = f"{Event._meta.app_label}-{kebab(Event.__name__)}"
    assert expected in basenames.values()


def test_autodiscover_is_idempotent() -> None:
    router = _discovered()
    snapshot = list(router.registry)
    router.autodiscover()
    assert list(router.registry) == snapshot


def test_explicit_registration_wins_over_autodiscovery(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=ROUTER_LOGGER)
    router = KarniRouter()
    router.register("events", VenueViewSet, basename="explicit-events")
    router.autodiscover()

    registry = _by_prefix(router)
    assert registry["events"] is VenueViewSet
    assert [prefix for prefix, _, _ in router.registry].count("events") == 1
    # The explicitly registered class is never re-registered elsewhere either.
    assert len([viewset for _, viewset, _ in router.registry if viewset is VenueViewSet]) == 1
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ROUTER_LOGGER and record.levelno == logging.DEBUG
    ]
    assert any("events" in message for message in debug_messages)


def test_auto_vs_auto_prefix_conflict_warns_naming_both(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    conflicting = type("ZzConflictViewSet", (EventViewSet,), {"route": "events"})
    _inject_viewset(monkeypatch, "ZzConflictViewSet", conflicting)

    caplog.set_level(logging.DEBUG, logger=ROUTER_LOGGER)
    router = KarniRouter()
    router.autodiscover()

    assert conflicting not in {viewset for _, viewset, _ in router.registry}
    holder = _by_prefix(router)["events"]
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == ROUTER_LOGGER and record.levelno == logging.WARNING
    ]
    assert any(
        "ZzConflictViewSet" in message and holder.__name__ in message
        for message in warning_messages
    ), f"expected a WARNING naming both viewsets, got {warning_messages!r}"


def test_route_attribute_replaces_the_derived_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routed = type("ZzRoutedTagViewSet", (BaseViewSet,), {"model": Tag, "route": "labels"})
    _inject_viewset(monkeypatch, "ZzRoutedTagViewSet", routed)

    registry = _by_prefix(_discovered())
    assert registry.get("labels") is routed


def test_get_default_router_returns_a_cached_discovered_router() -> None:
    first = get_default_router()
    second = get_default_router()
    assert first is second
    assert isinstance(first, KarniRouter)
    assert "events" in _by_prefix(first)


def test_urls_module_exposes_the_factory_router() -> None:
    api_urls = importlib.import_module("karni.api.urls")
    assert isinstance(api_urls.router, KarniRouter)
    assert api_urls.urlpatterns
    route_names = {getattr(pattern, "name", "") or "" for pattern in api_urls.urlpatterns}
    assert any(name.endswith("-list") for name in route_names)
