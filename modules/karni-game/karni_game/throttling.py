"""Experimental. The per-player rate limits of the game API (``KARNI_GAME_RATES``).

Each limited view names a scope per method (``throttle_scopes = {"PUT": "save"}``).
:class:`PlayerRateThrottle` counts per player: the account's or the guest's
player, else the client's address (``guest``). A server-to-server view counts
per game (``results``) or per portal (``callback``). Past the limit the view
answers ``429 GAME015`` with ``retry_after``.

Override / escape hatch: change a rate in ``KARNI_GAME_RATES`` (``None`` turns
it off), or subclass :class:`PlayerRateThrottle` and set ``throttle_class``
on a view.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

from karni_game import conf

__all__ = ["PlayerRateThrottle"]


class PlayerRateThrottle(SimpleRateThrottle):
    """A limit of one scope, per player (else per client address)."""

    cache_format = "karni_game_throttle_%(scope)s_%(ident)s"

    def __init__(self, scope: str) -> None:
        self.scope = scope
        super().__init__()

    def get_rate(self) -> str | None:
        return conf.rate(self.scope)

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        ident = None
        keyed = getattr(view, "throttle_ident", None)
        if callable(keyed):
            ident = keyed(request, self.scope)
        if not ident:
            ident = f"ip:{self.get_ident(request)}"
        return self.cache_format % {"scope": self.scope, "ident": ident}
