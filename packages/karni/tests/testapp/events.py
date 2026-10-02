"""Custom events of the testapp, autodiscovered with its listeners.

Custom events are plain Django signals; ``<app>/events.py`` is where they
live, ``<app>/listeners.py`` is where they are received.
"""

from __future__ import annotations

from django.dispatch import Signal

#: Sent with ``shelf=<Shelf>`` when a shelf is archived.
shelf_archived = Signal()
