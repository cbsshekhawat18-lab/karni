"""Tests for :mod:`karni.events`: lifecycle listeners, queued dispatch, autodiscovery.

The listeners under test live in ``tests/testapp/listeners.py`` and are
connected by Karni's startup autodiscovery — nothing here connects them. Each
records ``(event, model label, value)`` into ``listeners.received``.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest
from celery import Celery
from celery import _state as celery_state
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.test import override_settings
from django.utils import timezone

from karni import events as karni_events
from karni.celery import create_celery_app, resolve_task
from karni.events import QueuedListener, is_soft_delete, on_created, queued
from tests.testapp import events as testapp_events
from tests.testapp import listeners, tasks
from tests.testapp.models import Entry, Shelf, Stamp

CaptureCallbacks = Callable[..., AbstractContextManager[list[Callable[[], Any]]]]


@pytest.fixture
def received() -> Iterator[list[tuple[str, str, Any]]]:
    """The testapp listeners' record, emptied around each test."""
    listeners.received.clear()
    tasks.deleted_shelves.clear()
    yield listeners.received
    listeners.received.clear()
    tasks.deleted_shelves.clear()


@pytest.fixture
def eager_celery() -> Iterator[Celery]:
    """A factory-built Celery app (eager per tests/settings.py) as the current app."""
    previous = celery_state.get_current_app()
    app = create_celery_app("karni-events-tests")
    app.set_current()
    assert app.conf.task_always_eager is True
    yield app
    previous.set_current()


def _events(received: list[tuple[str, str, Any]], model: str = "testapp.Shelf") -> list[str]:
    return [event for event, label, _ in received if label == model]


# autodiscovery


def test_events_and_listeners_modules_are_autodiscovered_at_startup() -> None:
    assert "tests.testapp.events" in sys.modules
    assert "tests.testapp.listeners" in sys.modules
    assert post_save.has_listeners(Shelf)
    assert post_delete.has_listeners(Entry)


def test_ready_autodiscovers_unless_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(karni_events, "autodiscover", lambda: calls.append("discovered"))
    config = apps.get_app_config("karni")

    config.ready()
    assert calls == ["discovered"]

    with override_settings(KARNI_EVENTS_AUTODISCOVER=False):
        config.ready()
    assert calls == ["discovered"]


def test_autodiscover_imports_events_before_listeners(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(karni_events, "autodiscover_modules", lambda *names: seen.append(names))
    karni_events.autodiscover()
    assert seen == [("events", "listeners")]


# lifecycle semantics


@pytest.mark.django_db
def test_create_fires_created_only(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    assert received == [("created", "testapp.Shelf", shelf.pk)]


@pytest.mark.django_db
def test_save_of_existing_row_fires_updated(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    received.clear()
    shelf.name = "Poetry"
    shelf.save()
    assert received == [("updated", "testapp.Shelf", shelf.pk)]


@pytest.mark.django_db
def test_soft_delete_fires_deleted_not_updated(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    received.clear()
    shelf.delete()
    assert _events(received) == ["deleted"]
    assert Shelf._base_manager.filter(pk=shelf.pk).exists()  # hidden, not removed


@pytest.mark.django_db
def test_restore_is_an_update_and_a_restore(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    shelf.delete()
    received.clear()
    shelf.restore()
    assert sorted(_events(received)) == ["restored", "updated"]
    received.clear()
    shelf.save()  # a plain update is not a restore
    assert _events(received) == ["updated"]


@pytest.mark.django_db
def test_a_refusing_restore_listener_undoes_the_restore(
    received: list[tuple[str, str, Any]],
) -> None:
    from karni.exceptions import KarniValueError

    shelf = Shelf.objects.create(name="Fiction")
    shelf.delete()
    listeners.refuse_restore.append(True)
    try:
        with pytest.raises(KarniValueError):
            shelf.restore()
    finally:
        listeners.refuse_restore.clear()
    assert shelf.is_deleted  # the instance keeps its deleted_at
    assert Shelf._base_manager.get(pk=shelf.pk).is_deleted  # and so does the row


@pytest.mark.django_db
def test_hard_delete_of_live_row_fires_deleted(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    pk = shelf.pk
    received.clear()
    shelf.hard_delete()
    assert received == [("deleted", "testapp.Shelf", pk)]


@pytest.mark.django_db
def test_purging_a_soft_deleted_row_does_not_fire_again(
    received: list[tuple[str, str, Any]],
) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    shelf.delete()
    received.clear()
    shelf.hard_delete()
    assert received == []


@pytest.mark.django_db
def test_hard_delete_of_plain_model(received: list[tuple[str, str, Any]]) -> None:
    entry = Entry.objects.create(text="draft")
    pk = entry.pk
    entry.delete()
    assert ("deleted", "testapp.Entry", pk) in received


@pytest.mark.django_db
def test_raw_saves_fire_nothing(received: list[tuple[str, str, Any]]) -> None:
    now = timezone.now()  # raw saves skip auto_now, as loaddata does
    shelf = Shelf(name="Loaded from a fixture", created_at=now, updated_at=now)
    shelf.save_base(raw=True)
    assert received == []


@pytest.mark.django_db
def test_bulk_operations_fire_nothing(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    received.clear()
    Shelf.objects.filter(pk=shelf.pk).update(name="Bulk")
    Shelf.objects.filter(pk=shelf.pk).delete()  # soft queryset delete: one UPDATE
    assert received == []


@pytest.mark.django_db
def test_lazy_string_model_reference(received: list[tuple[str, str, Any]]) -> None:
    stamp = Stamp.objects.create(value="x")
    assert ("created", "testapp.Stamp", stamp.pk) in received


@pytest.mark.django_db
def test_custom_event_reaches_its_listener(received: list[tuple[str, str, Any]]) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    received.clear()
    testapp_events.shelf_archived.send(sender=Shelf, shelf=shelf)
    assert received == [("shelf_archived", "testapp.Shelf", shelf.pk)]


def test_decorator_returns_the_listener_unchanged() -> None:
    assert callable(listeners.shelf_created_queued)
    assert not isinstance(listeners.shelf_created_queued, QueuedListener)


def test_decorator_rejects_a_non_model() -> None:
    with pytest.raises(TypeError, match="model class or an 'app_label.ModelName'"):
        on_created(42)  # type: ignore[arg-type]


class TestIsSoftDelete:
    def test_requires_deleted_at_in_update_fields(self) -> None:
        shelf = Shelf(name="x", deleted_at=timezone.now())
        assert is_soft_delete(shelf, frozenset({"deleted_at", "updated_at"})) is True
        assert is_soft_delete(shelf, None) is False  # a full save is an update
        assert is_soft_delete(shelf, frozenset({"name"})) is False

    def test_cleared_deleted_at_is_a_restore(self) -> None:
        shelf = Shelf(name="x")
        assert is_soft_delete(shelf, frozenset({"deleted_at"})) is False

    def test_models_without_deleted_at(self) -> None:
        assert is_soft_delete(Entry(text="x"), frozenset({"deleted_at"})) is False


# queued dispatch


@pytest.mark.django_db
def test_queued_listener_runs_in_the_worker_after_commit(
    received: list[tuple[str, str, Any]],
    eager_celery: Celery,
    django_capture_on_commit_callbacks: CaptureCallbacks,
) -> None:
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        Shelf.objects.create(name="Queued")
        assert ("queued:created", "testapp.Shelf", "Queued") not in received  # not before commit
    assert len(callbacks) == 1
    assert ("queued:created", "testapp.Shelf", "Queued") in received


@pytest.mark.django_db
def test_queued_task_receives_the_primary_key_on_soft_delete(
    received: list[tuple[str, str, Any]],
    eager_celery: Celery,
    django_capture_on_commit_callbacks: CaptureCallbacks,
) -> None:
    shelf = Shelf.objects.create(name="Fiction")
    with django_capture_on_commit_callbacks(execute=True):
        shelf.delete()
    assert tasks.deleted_shelves == [str(shelf.pk)]


@pytest.mark.django_db
def test_queued_hard_delete_rebuilds_the_row_from_a_snapshot(
    received: list[tuple[str, str, Any]],
    eager_celery: Celery,
    django_capture_on_commit_callbacks: CaptureCallbacks,
) -> None:
    entry = Entry.objects.create(text="gone soon")
    with django_capture_on_commit_callbacks(execute=True):
        entry.delete()
    assert not Entry.objects.filter(text="gone soon").exists()
    assert ("queued:deleted", "testapp.Entry", "gone soon") in received


@pytest.mark.django_db
def test_rolled_back_save_queues_nothing(
    received: list[tuple[str, str, Any]],
    django_capture_on_commit_callbacks: CaptureCallbacks,
) -> None:
    with django_capture_on_commit_callbacks() as callbacks:
        with pytest.raises(RuntimeError), transaction.atomic():
            Shelf.objects.create(name="Rolled back")
            raise RuntimeError("abort")
    assert callbacks == []


@pytest.mark.django_db
def test_queued_listener_skips_a_vanished_row(
    received: list[tuple[str, str, Any]],
    eager_celery: Celery,
    caplog: pytest.LogCaptureFixture,
) -> None:
    task = resolve_task("tests.testapp.listeners.shelf_created_queued")
    with caplog.at_level(logging.WARNING, logger="karni.events"):
        task.apply(args=("testapp.Shelf", str(uuid.uuid4()), None))
    assert received == []
    assert "no longer exists" in caplog.text


@pytest.mark.django_db
def test_calling_a_queued_listener_directly_queues(
    received: list[tuple[str, str, Any]],
    eager_celery: Celery,
    django_capture_on_commit_callbacks: CaptureCallbacks,
) -> None:
    listener = queued(tasks.record_shelf_deleted, countdown=0)
    shelf = Shelf.objects.create(name="Direct")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        listener(shelf)
    assert len(callbacks) == 1
    assert tasks.deleted_shelves == [str(shelf.pk)]


def test_queued_decorator_form_with_options() -> None:
    built = queued(queue="emails")(listeners.shelf_created)
    assert isinstance(built, QueuedListener)
    assert built.options == {"queue": "emails"}
    assert built.name == "tests.testapp.listeners.shelf_created"


def test_queued_needs_a_module_level_function() -> None:
    with pytest.raises(ImproperlyConfigured, match="module-level function"):
        queued(lambda instance: None)

    def nested(instance: Any) -> None:
        return None

    with pytest.raises(ImproperlyConfigured, match="module-level function"):
        queued(nested)


def test_queued_accepts_a_dotted_task_name() -> None:
    listener = queued("tests.testapp.tasks.record_shelf_deleted")
    assert listener.func is None
    assert listener.name == "tests.testapp.tasks.record_shelf_deleted"
    assert repr(listener) == "<QueuedListener tests.testapp.tasks.record_shelf_deleted>"
