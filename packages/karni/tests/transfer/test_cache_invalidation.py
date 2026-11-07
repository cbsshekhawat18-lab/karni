"""An import or a content load invalidates the API response cache once, never once per row."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache as default_cache
from django.test.utils import override_settings

from karni.api import caching
from karni.transfer.imports import Importer
from karni.transfer.loading import load_content
from tests.testapp.models import Event
from tests.transfer.conftest import api_request

pytestmark = pytest.mark.django_db

HEADERS = ["title", "starts_at", "capacity"]
ROWS = [[f"Gig {n}", "2026-02-01T10:00:00Z", n] for n in range(1, 6)]


@pytest.fixture(autouse=True)
def _cache_on() -> Iterator[None]:
    default_cache.clear()
    with override_settings(KARNI_API_CACHE=True):
        yield
    default_cache.clear()


@pytest.fixture
def replaced(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    original = caching._replace

    def spy(keys: Any) -> None:
        keys = list(keys)
        calls.append(keys)
        original(keys)

    monkeypatch.setattr(caching, "_replace", spy)
    return calls


def _run(user: Any, *, dry_run: bool) -> Any:
    importer = Importer(Event, api_request("post", "/events/import/", user))
    mapping = {name: name for name in HEADERS}
    return importer.run(HEADERS, ROWS, mapping, dry_run=dry_run)


def _event_batches(replaced: list[list[str]]) -> list[list[str]]:
    return [keys for keys in replaced if "karni:api:m:testapp.event" in keys]


def test_an_import_invalidates_once(make_user: Any, replaced: list[list[str]]) -> None:
    staff = make_user("staff@example.com", "staff")
    result = _run(staff, dry_run=False)
    assert result.created == 5 and Event.objects.count() == 5
    batches = _event_batches(replaced)
    assert len(batches) == 1
    assert "karni:api:a:testapp.event" in batches[0]  # every row counts as changed


def test_a_dry_run_invalidates_nothing(make_user: Any, replaced: list[list[str]]) -> None:
    staff = make_user("staff@example.com", "staff")
    assert _run(staff, dry_run=True).created == 5
    assert Event.objects.count() == 0 and _event_batches(replaced) == []


def test_a_content_load_invalidates_once_per_model(
    tmp_path: Path, replaced: list[list[str]]
) -> None:
    content = {
        "contentapp.Service": [
            {"slug": slug, "title": slug.title(), "image": ""} for slug in ("plan", "build", "fix")
        ]
    }
    path = tmp_path / "content.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    load_content(path)
    services = [keys for keys in replaced if "karni:api:m:contentapp.service" in keys]
    assert len(services) == 1
    replaced.clear()
    load_content(path, dry_run=True)
    assert replaced == []
