"""Experimental. Demo mode's two middlewares (list them after Karni's stack in ``MIDDLEWARE``).

Both do nothing while ``KARNI_DEMO_MODE`` is off, and read it on every request.
``DemoWriteGuardMiddleware`` should come after the authentication middleware
(Karni's stack has it) so the admin's session user is known.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponseBase

from karni.demo import conf, guard, reset

logger = logging.getLogger("karni.demo")


class DemoResetMiddleware:
    """Reset the demo data when it is due, asked at most every ``KARNI_DEMO_RESET_CHECK_SECONDS``.

    Each worker process asks on its own. :func:`karni.demo.reset.reset_if_due` makes
    sure only one of them resets. A reset that fails is logged, the request is
    served anyway, and the next check tries again.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response
        self.next_check = 0.0

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if conf.demo_mode():
            now = time.monotonic()
            if now >= self.next_check:
                self.next_check = now + conf.reset_check_seconds()
                try:
                    reset.reset_if_due()
                except Exception:
                    logger.exception("demo data reset failed: the next check tries again")
        return self.get_response(request)


class DemoWriteGuardMiddleware:
    """Refuse the writes :func:`karni.demo.guard.check_request` refuses, with a 403 and why."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        if conf.demo_mode():
            refused = guard.check_request(request)
            if refused is not None:
                return guard.respond(request, refused)
        return self.get_response(request)
