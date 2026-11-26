"""The game API from other origins: a game built for a portal runs on its domain.

A portal build of a game calls ``/api/game/`` from the portal's own domain.
:func:`allow_game_origin` is a receiver of django-cors-headers'
``check_request_enabled`` signal (Karni's stack runs its middleware): it lets
the origins of ``KARNI_GAME_CORS_ORIGINS`` (or ``"*"``) reach the game API,
and only the game API. Such a call signs in with a token: the guest's
``X-Player-Token`` or the account's ``Authorization: Bearer`` JWT. Cookies are
never used across origins: the game views drop session authentication for a
request from another origin (:func:`cross_origin`), whatever
``CORS_ALLOW_CREDENTIALS`` says (session mode turns it on for the project's own
app).

The project lets the browser send the token's header:

    from corsheaders.defaults import default_headers

    CORS_ALLOW_HEADERS = (*default_headers, "x-player-token")

``karni check`` reports ``GAME038`` while ``KARNI_GAME_CORS_ORIGINS`` is set and
the header is missing. ``karni new --kind game`` (and ``app+game``) writes the line.

Override / escape hatch: connect a receiver of your own to
``check_request_enabled`` for other rules, or list the origins in
``CORS_ALLOWED_ORIGINS`` to open the whole API to them.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.http import HttpRequest

from karni_game import conf

__all__ = ["allow_game_origin", "allowed_origins", "cross_origin", "game_prefix"]


def allowed_origins() -> list[str]:
    """``KARNI_GAME_CORS_ORIGINS``, each as ``scheme://host[:port]``."""
    return [str(origin).rstrip("/") for origin in conf.get("KARNI_GAME_CORS_ORIGINS") or []]


def game_prefix() -> str | None:
    """The path the game API is mounted at (``/api/game/``), or ``None`` without the include."""
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse("karni_game:guest").removesuffix("guest/")
    except NoReverseMatch:
        return None


def allow_game_origin(sender: Any, request: HttpRequest, **kwargs: Any) -> bool:
    """True for a request to the game API from an origin ``KARNI_GAME_CORS_ORIGINS`` lists."""
    origin = str(request.headers.get("Origin", "")).rstrip("/")
    allowed = allowed_origins()
    if not origin or not allowed:
        return False
    prefix = game_prefix()
    if prefix is None or not request.path.startswith(prefix):
        return False
    return "*" in allowed or origin in allowed


def cross_origin(request: HttpRequest) -> bool:
    """Whether the request comes from a page of another origin (its ``Origin`` header)."""
    origin = str(request.headers.get("Origin", ""))
    if not origin or origin == "null":
        return bool(origin)
    found = urlsplit(origin)
    return found.netloc != request.get_host() or found.scheme != request.scheme
