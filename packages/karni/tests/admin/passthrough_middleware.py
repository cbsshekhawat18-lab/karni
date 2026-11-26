"""A project middleware that only calls ``get_response`` (the query attribution tests)."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class PassThrough:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)
