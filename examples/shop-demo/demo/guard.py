"""Who may write to the demo: the demo account only, and never to its own account.

The rule, for every request whose method is not GET, HEAD, OPTIONS or TRACE:

1. Signing in, refreshing a token, signing out and accepting the terms are
   open to every caller (:func:`open_paths`), in the API and in the admin.
   Without them nobody could sign in, and a signed-in account could not read
   past the terms gate.
2. Any other write by anyone but the demo account is refused: anonymous
   callers and every other account are read-only, in the API and the admin.
   Sign-up (``register/``) and sign-in codes (``otp/``) are writes too, so they
   are closed.
3. The demo account may write everywhere except where an account or its
   access changes (:func:`account_paths`): the rest of the auth API (password,
   email, profile, the role matrix) and, in the admin, the user and role
   tables and the password page. So it cannot change its password, email or
   roles, or delete itself, and the next visitor can still sign in.

The caller is the session's user (the admin), else the user of a JWT in the
``Authorization`` header (the React app and API clients): the same two ways
the API itself authenticates (``REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]``).

Override / escape hatch: :func:`refusal` is a plain function of the request,
and :class:`demo.middleware.DemoWriteGuardMiddleware` only calls it, so a
project changes the rule here or swaps the middleware in ``MIDDLEWARE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape

from demo import account

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Admin apps the demo account may read but not change: the user model's app is added.
LOCKED_ADMIN_APPS: tuple[str, ...] = ("auth",)


@dataclass(frozen=True)
class Refusal:
    """Why a write is refused: a code for clients and a sentence for people."""

    code: str
    detail: str


def read_only() -> Refusal:
    return Refusal(
        "demo_read_only",
        f"This demo is read-only unless you sign in as {account.email()} "
        f"(password {account.password()}).",
    )


def account_locked() -> Refusal:
    return Refusal(
        "demo_account_locked",
        "The demo account cannot change its password, email or roles, or delete itself, "
        "so the next visitor can still sign in.",
    )


def _path(name: str) -> str | None:
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


def open_paths() -> set[str]:
    """Writes every caller may make: sign in, refresh, sign out, accept the terms."""
    names = (
        "karni-accounts-login",
        "karni-accounts-refresh",
        "karni-accounts-logout",
        "karni-accounts-terms-accept",
        "admin:login",
        "admin:logout",
    )
    return {path for name in names if (path := _path(name)) is not None}


def account_paths() -> tuple[str, ...]:
    """Path prefixes where the demo account's writes are refused: accounts and access."""
    prefixes: list[str] = []
    login = _path("karni-accounts-login")
    if login is not None:
        prefixes.append(login.removesuffix("login/"))  # the auth API's mount, /api/auth/
    admin = _path("admin:index")
    if admin is not None:
        labels = {*LOCKED_ADMIN_APPS, get_user_model()._meta.app_label}
        prefixes += [f"{admin}{label}/" for label in sorted(labels)]
        if (password := _path("admin:password_change")) is not None:
            prefixes.append(password)
    return tuple(prefixes)


def caller(request: HttpRequest) -> Any | None:
    """The signed-in user: the session's (admin), else a JWT's (the API), else ``None``."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user
    from rest_framework.exceptions import APIException
    from rest_framework.settings import api_settings
    from rest_framework_simplejwt.authentication import JWTAuthentication

    for authentication in api_settings.DEFAULT_AUTHENTICATION_CLASSES:
        if isinstance(authentication, type) and issubclass(authentication, JWTAuthentication):
            try:
                found = authentication().authenticate(request)
            except APIException:
                return None  # a bad or expired token: the view answers 401 for itself
            return found[0] if found is not None else None
    return None


def refusal(request: HttpRequest) -> Refusal | None:
    """Why this request may not write, or ``None`` when it may (see the module docstring)."""
    if request.method in SAFE_METHODS:
        return None
    path = request.path
    if path in open_paths():
        return None
    if not account.is_demo(caller(request)):
        return read_only()
    if path.startswith(account_paths()):
        return account_locked()
    return None


def respond(request: HttpRequest, refused: Refusal) -> HttpResponse:
    """A 403: a short page in the admin, else JSON (``{"code", "detail"}``) for API clients."""
    admin = _path("admin:index")
    if admin is not None and request.path.startswith(admin):
        page = (
            "<!doctype html><title>Read-only demo</title>"
            f"<h1>Read-only demo</h1><p>{escape(refused.detail)}</p>"
        )
        response = HttpResponse(page, status=403)
    else:
        response = JsonResponse({"code": refused.code, "detail": refused.detail}, status=403)
    response["Cache-Control"] = "no-store"
    return response
