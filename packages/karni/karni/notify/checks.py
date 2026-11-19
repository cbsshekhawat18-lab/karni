"""Experimental. System checks of the notifications contract.

* ``karni.W440``: a declared message kind sends only on channels the project
  leaves out of ``KARNI_NOTIFY_CHANNELS``, so it goes nowhere.

Registered when ``karni.notify`` is installed (its ``ready()``).
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks

from karni.exceptions import check_warning

__all__ = ["check_notify"]


@checks.register()
def check_notify(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.W440 (see the module docstring)."""
    from karni.mail import kinds
    from karni.notify.services import project_channels

    if not apps.is_installed("karni.notify"):
        return []
    ours = set(project_channels())
    messages: list[checks.CheckMessage] = []
    for kind in kinds():
        if set(kind.channels) & ours:
            continue
        messages.append(
            check_warning(
                "W440",
                f"The message kind {kind.name!r} is sent on {list(kind.channels)!r}, and "
                f"KARNI_NOTIFY_CHANNELS is {sorted(ours)!r}, so it goes nowhere.",
                hint="Add the channel to KARNI_NOTIFY_CHANNELS, or declare the kind with "
                "channels the project sends on.",
                obj=kind.name,
            )
        )
    return messages
