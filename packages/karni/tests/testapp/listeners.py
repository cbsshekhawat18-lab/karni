"""Listeners autodiscovered at startup by :func:`karni.events.autodiscover`.

Exercised by ``tests/test_events.py``. Every listener only *records* what it
received in :data:`received`, so the rest of the suite (which also saves
these models) is unaffected; queued listeners only register
``transaction.on_commit`` callbacks, which the suite's per-test transactions
discard unless a test captures and runs them.

Model choice keeps Django's delete plans unchanged for other suites:
``Shelf`` (``BaseModel``: soft delete) and ``Entry`` (plain hard delete) are
never the cascade target of another model.
"""

from __future__ import annotations

from typing import Any

from django.dispatch import receiver

from karni.events import on_created, on_deleted, on_restored, on_updated, queued
from tests.testapp import events, tasks
from tests.testapp.models import Entry, Shelf, Stamp

#: ``(event, model label, value)`` for every listener call, in call order.
received: list[tuple[str, str, Any]] = []


@on_created(Shelf)
def shelf_created(shelf: Shelf) -> None:
    received.append(("created", "testapp.Shelf", shelf.pk))


@on_updated(Shelf)
def shelf_updated(shelf: Shelf) -> None:
    received.append(("updated", "testapp.Shelf", shelf.pk))


#: Set by a test to make the restore listener refuse (and so undo the restore).
refuse_restore: list[bool] = []


@on_restored(Shelf)
def shelf_restored(shelf: Shelf) -> None:
    if refuse_restore:
        from karni.exceptions import KarniValueError

        raise KarniValueError("Shelf restore refused by the test listener.", code="E402")
    received.append(("restored", "testapp.Shelf", shelf.pk))


@on_deleted(Shelf)
def shelf_deleted(shelf: Shelf) -> None:
    received.append(("deleted", "testapp.Shelf", shelf.pk))


@on_deleted(Entry)
def entry_deleted(entry: Entry) -> None:
    received.append(("deleted", "testapp.Entry", entry.pk))


@on_created("testapp.Stamp")
def stamp_created(stamp: Stamp) -> None:
    """Lazy ``"app_label.ModelName"`` reference."""
    received.append(("created", "testapp.Stamp", stamp.pk))


@on_created(Shelf, queued=True)
def shelf_created_queued(shelf: Shelf) -> None:
    """Runs in the worker with the row re-fetched by primary key."""
    received.append(("queued:created", "testapp.Shelf", shelf.name))


@on_deleted(Entry, queued=True)
def entry_deleted_queued(entry: Entry) -> None:
    """Hard delete: the worker rebuilds the row from the queued snapshot."""
    received.append(("queued:deleted", "testapp.Entry", entry.text))


# An existing Celery task as a queued listener: it receives the primary key.
on_deleted(Shelf)(queued(tasks.record_shelf_deleted))


@receiver(events.shelf_archived)
def shelf_archived(sender: Any, shelf: Shelf, **kwargs: Any) -> None:
    received.append(("shelf_archived", "testapp.Shelf", shelf.pk))
