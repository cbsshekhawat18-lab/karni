"""Print, as JSON, what a finished project's Django serves. Run with its python, cwd = the project.

The same probe runs in a plain Django project and in a Karni one, so the counts mean the same
thing on both sides: URL routes under ``api/`` (a DRF router's format-suffix duplicates left
out) and the HTTP methods each one answers, the sign-in and account routes outside the admin,
the models registered in the admin, and whether an OpenAPI schema is served.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from typing import Any

import django

django.setup()

from django.contrib import admin  # noqa: E402
from django.urls import URLPattern, URLResolver, get_resolver  # noqa: E402

FORMAT_SUFFIX = re.compile(r"\\\.\(\?P<format>")
ACCOUNT_WORDS = ("login", "logout", "token", "auth", "password", "signup", "register")


def walk(patterns: list[Any], prefix: str = "") -> Iterator[tuple[str, URLPattern]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern


def methods(callback: Callable[..., Any]) -> list[str]:
    """The HTTP methods a route answers: a viewset route's actions, else the view's handlers."""
    actions = getattr(callback, "actions", None)
    if actions:
        return sorted(method for method in actions if method != "options")
    view = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
    if view is None:
        return ["get"]
    names = getattr(view, "http_method_names", ["get"])
    return sorted(m for m in names if m not in ("options", "head") and hasattr(view, m))


def main() -> None:
    routes = [
        (route, pattern)
        for route, pattern in walk(get_resolver().url_patterns)
        if not FORMAT_SUFFIX.search(route)
    ]
    api = [(route, p) for route, p in routes if route.lstrip("^").startswith("api/")]
    accounts = {
        route
        for route, _ in routes
        if any(word in route.lower() for word in ACCOUNT_WORDS)
        and not route.lstrip("^").startswith("admin/")
    }
    print(
        json.dumps(
            {
                "api_routes": len({route for route, _ in api}),
                "api_operations": sum(len(methods(p.callback)) for _, p in api),
                "account_routes": len(accounts),
                "admin_models": len(admin.site._registry),
                "openapi_schema": any(
                    "schema" in route.lower() or "openapi" in route.lower() for route, _ in routes
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
