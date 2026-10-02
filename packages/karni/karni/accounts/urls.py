"""URLconf for the :mod:`karni.accounts` auth API.

Projects mount the whole surface in one line::

    urlpatterns = [
        path("api/auth/", include("karni.accounts.urls")),
    ]

The pattern list is **mode-independent** (amendment A3): every endpoint exists
in both ``jwt`` and ``session`` mode and the views branch on
``settings.KARNI_AUTH_MODE`` per request (``refresh/`` answers 405 in session
mode). Only the optional feature blocks are conditional at import time:

* ``2fa/...`` is included from :mod:`karni.accounts.twofa` when ``KARNI_2FA``
  is enabled — the module is referenced by dotted path so core installs
  (without the ``karni[2fa]`` extra) never import it;
* ``social/...`` mounts allauth's socialaccount + provider URLs when
  ``KARNI_SOCIAL_AUTH`` is enabled (session mode only — the jwt+social combo
  is rejected by ``karni.conf`` validation, amendment A2). Deliberately *not*
  ``allauth.urls``: no parallel HTML account surface, just the provider flow.

Route names carry a ``karni-accounts-`` prefix instead of an ``app_name``
namespace: allauth reverses its own route names unnamespaced, so wrapping the
include in a namespace would break the social flow.

Override / escape hatch: declare your own
``path("api/auth/<endpoint>/", YourView.as_view())`` *before* the include —
first match wins (amendment A11) — or cherry-pick single views from
:mod:`karni.accounts.api.views` into a hand-rolled URLconf.
"""

from __future__ import annotations

from importlib import import_module

from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

from karni.accounts.api import views

__all__ = ["urlpatterns"]

urlpatterns: list[URLPattern | URLResolver] = [
    path("register/", views.RegisterView.as_view(), name="karni-accounts-register"),
    path("login/", views.LoginView.as_view(), name="karni-accounts-login"),
    path("logout/", views.LogoutView.as_view(), name="karni-accounts-logout"),
    path("refresh/", views.RefreshView.as_view(), name="karni-accounts-refresh"),
    path("csrf/", views.CsrfView.as_view(), name="karni-accounts-csrf"),
    path("me/", views.MeView.as_view(), name="karni-accounts-me"),
    path(
        "password/change/",
        views.PasswordChangeView.as_view(),
        name="karni-accounts-password-change",
    ),
    path(
        "password/reset/",
        views.PasswordResetView.as_view(),
        name="karni-accounts-password-reset",
    ),
    path(
        "password/reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="karni-accounts-password-reset-confirm",
    ),
    path("email/verify/", views.EmailVerifyView.as_view(), name="karni-accounts-email-verify"),
    path(
        "email/verify/resend/",
        views.EmailVerifyResendView.as_view(),
        name="karni-accounts-email-verify-resend",
    ),
    path("email/change/", views.EmailChangeView.as_view(), name="karni-accounts-email-change"),
    path(
        "email/change/confirm/",
        views.EmailChangeConfirmView.as_view(),
        name="karni-accounts-email-change-confirm",
    ),
]


def _social_urlpatterns() -> list[URLPattern | URLResolver]:
    """Build the allauth provider-flow patterns (amendment A2).

    ``allauth.socialaccount.urls`` plus the ``urls`` module of every installed
    provider app — assembled from ``INSTALLED_APPS`` (which ``karni.conf``
    populates from ``KARNI_SOCIAL_PROVIDERS``) rather than allauth's registry,
    so it tracks exactly what the project enabled. Providers without a
    ``urls`` module are skipped.
    """
    patterns: list[URLPattern | URLResolver] = [path("", include("allauth.socialaccount.urls"))]
    for app in settings.INSTALLED_APPS:
        if not app.startswith("allauth.socialaccount.providers."):
            continue
        try:
            provider_urls = import_module(f"{app}.urls")
        except ImportError:
            continue
        patterns.append(path("", include(provider_urls)))
    return patterns


if getattr(settings, "KARNI_2FA", False):
    # karni.accounts.twofa exposes its own ``urlpatterns`` (setup/, confirm/,
    # disable/, login/); the dotted-path include keeps the import conditional.
    urlpatterns.append(path("2fa/", include("karni.accounts.twofa")))

if getattr(settings, "KARNI_SOCIAL_AUTH", False):
    urlpatterns.append(path("social/", include(_social_urlpatterns())))
