"""``karni make`` generators — one module per generator, registered here.

Each generator module exposes ``NAME``, ``SUMMARY``, a ``plan(...)`` that
works against a :class:`~karni_cli.generators.core.Workspace`, and a typer
``command``. :data:`GENERATORS` is the single list ``karni make``,
``karni make --list``, the hidden ``make:<type>`` aliases and docs/cli.md
are built from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from karni_cli.generators import (
    app,
    command,
    component,
    event,
    listener,
    middleware,
    migration,
    model,
    module,
    page,
    schedule,
    serializer,
    service,
    task,
    viewset,
)


@dataclass(frozen=True)
class Generator:
    name: str
    summary: str
    command: Callable[..., Any]


GENERATORS: tuple[Generator, ...] = tuple(
    Generator(mod.NAME, mod.SUMMARY, mod.command)
    for mod in (
        app,
        model,
        viewset,
        serializer,
        migration,
        task,
        schedule,
        event,
        listener,
        command,
        service,
        middleware,
        page,
        component,
        module,
    )
)
