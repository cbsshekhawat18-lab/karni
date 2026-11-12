"""The demo's two middlewares (``config/settings.py`` lists them after Karni's stack).

Both do nothing while ``DEMO_MODE`` is off, and read it on every request.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase

from demo import account, guard, reset

logger = logging.getLogger("demo")


class DemoResetMiddleware:
    """Reset the demo data when it is due, asked at most every ``DEMO_RESET_CHECK_SECONDS``.

    Each worker process asks on its own. :func:`demo.reset.reset_if_due` makes
    sure only one of them resets. A reset that fails is logged, the request is
    served anyway, and the next check tries again.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response
        self.next_check = 0.0

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if account.demo_mode():
            now = time.monotonic()
            if now >= self.next_check:
                self.next_check = now + float(getattr(settings, "DEMO_RESET_CHECK_SECONDS", 60))
                try:
                    reset.reset_if_due()
                except Exception:
                    logger.exception("demo data reset failed: the next check tries again")
        return self.get_response(request)


class DemoWriteGuardMiddleware:
    """Refuse the writes :func:`demo.guard.refusal` refuses, with a 403 that says why."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if account.demo_mode():
            refused = guard.refusal(request)
            if refused is not None:
                return guard.respond(request, refused)
        return self.get_response(request)
