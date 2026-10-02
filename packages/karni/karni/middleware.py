"""Current-user tracking for :class:`karni.models.AuditedModel`.

The request (not the user) is stored in a :class:`~contextvars.ContextVar`
and the user is resolved lazily at save time. Two reasons:

* DRF authenticates (JWT, session) inside the view, after middleware ran.
  DRF's ``Request.user`` setter writes through to the underlying Django
  request, so resolving lazily sees the JWT user too.
* ``ContextVar`` (unlike ``threading.local``) is isolated per asyncio task
  and copied into ``sync_to_async`` threads, so it is correct under ASGI.

Outside a request (Celery tasks, management commands, shells) there is no
current user; set one explicitly with :func:`current_user`.

Override / escape hatch: remove ``karni.middleware.CurrentUserMiddleware``
from ``MIDDLEWARE`` to stop automatic population (audit fields are then only
set where you assign them or use :func:`current_user`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponseBase

__all__ = ["CurrentUserMiddleware", "current_user", "get_current_user"]

_UNSET: Any = object()
_current_request: ContextVar[HttpRequest | None] = ContextVar("karni_current_request", default=None)
_user_override: ContextVar[Any] = ContextVar("karni_current_user_override", default=_UNSET)


def get_current_user() -> Any | None:
    """The authenticated user for the current context, or ``None``.

    An explicit :func:`current_user` override wins; otherwise the user of the
    request seen by :class:`CurrentUserMiddleware`. Anonymous users are
    ``None`` — audit fields never point at an anonymous placeholder.
    """
    override = _user_override.get()
    if override is not _UNSET:
        return override
    request = _current_request.get()
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


@contextmanager
def current_user(user: Any | None) -> Iterator[None]:
    """Set the audit user for a block of code (tasks, commands, tests).

    ``with current_user(admin): Event.objects.create(...)`` stamps
    ``created_by=admin``. ``current_user(None)`` explicitly suppresses
    stamping even inside a request.
    """
    token = _user_override.set(user)
    try:
        yield
    finally:
        _user_override.reset(token)


class CurrentUserMiddleware:
    """Makes the request available to :func:`get_current_user` (sync and async)."""

    sync_capable = True
    async_capable = True

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponseBase]
        | Callable[[HttpRequest], Awaitable[HttpResponseBase]],
    ) -> None:
        self.get_response = get_response
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        if iscoroutinefunction(self):
            return self.__acall__(request)
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)

    async def __acall__(self, request: HttpRequest) -> HttpResponseBase:
        token = _current_request.set(request)
        try:
            return await self.get_response(request)  # type: ignore[misc]
        finally:
            _current_request.reset(token)
