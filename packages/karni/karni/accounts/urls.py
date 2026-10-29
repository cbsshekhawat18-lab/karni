"""URLconf for the :mod:`karni.accounts` auth API.

Projects mount the whole surface in one line::

    urlpatterns = [
        path("api/auth/", include("karni.accounts.urls")),
    ]

The pattern list is **mode-independent** (amendment A3): every endpoint exists
in both ``jwt`` and ``session`` mode and the views branch on
``settings.KARNI_AUTH_MODE`` per request (``refresh/`` answers 405 in session
mode). Only the optional feature blocks are conditional at import time:

* ``register/`` exists while ``KARNI_ACCOUNTS_REGISTRATION`` is ``True`` (the
  default). ``False`` leaves it out, so it answers 404 and is absent from the
  OpenAPI schema. Use it when staff create every account.
* ``otp/send/`` and ``otp/verify/`` (experimental) exist while
  ``KARNI_EMAIL_OTP`` is ``True`` (default ``False``): sign-in with a code
  sent by email, in both modes (:class:`~karni.accounts.api.views.OtpSendView`,
  :class:`~karni.accounts.api.views.OtpVerifyView`). Off, they answer 404 and
  are absent from the OpenAPI schema, like ``register/``;
* ``2fa/...`` is included from :mod:`karni.accounts.twofa` when ``KARNI_2FA``
  is enabled — the module is referenced by dotted path so core installs
  (without the ``karni[2fa]`` extra) never import it;
* ``social/<provider>/`` (experimental) exists for each provider named in
  ``KARNI_SOCIAL_TOKEN_PROVIDERS``: sign-in with that provider's ID token, in
  both modes (:class:`~karni.accounts.api.views.SocialTokenLoginView`). An
  unconfigured provider has no route and answers 404. These routes come
  before allauth's, whose pages sit one level deeper
  (``social/<provider>/login/``, ``social/signup/``), so the two coexist;
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
:func:`build_urlpatterns` assembles the list for the current settings, so a
URLconf (or a test) can build it under other settings than the import saw.
"""

from __future__ import annotations

from importlib import import_module

from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path

from karni.accounts.api import matrix as matrix_views
from karni.accounts.api import views

__all__ = ["build_urlpatterns", "urlpatterns"]

_PERMISSION_PATTERNS: list[URLPattern | URLResolver] = [
    path(
        "permissions/matrix/",
        matrix_views.PermissionMatrixView.as_view(),
        name="karni-accounts-permission-matrix",
    ),
    path(
        "permissions/effective/",
        matrix_views.EffectivePermissionsView.as_view(),
        name="karni-accounts-effective-permissions",
    ),
    path(
        "permissions/effective/<str:user_id>/",
        matrix_views.EffectivePermissionsView.as_view(),
        name="karni-accounts-effective-permissions-user",
    ),
]

_AUTH_PATTERNS: list[URLPattern | URLResolver] = [
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


_OTP_PATTERNS: list[URLPattern | URLResolver] = [
    path("otp/send/", views.OtpSendView.as_view(), name="karni-accounts-otp-send"),
    path("otp/verify/", views.OtpVerifyView.as_view(), name="karni-accounts-otp-verify"),
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


def _social_token_urlpatterns() -> list[URLPattern | URLResolver]:
    """One ``social/<provider>/`` route per ``KARNI_SOCIAL_TOKEN_PROVIDERS`` entry (experimental).

    The route passes the provider's name to the view as ``provider``. A name
    startup validation would refuse (not a slug, or one of allauth's own
    ``login`` and ``signup``) gets no route.
    """
    from karni.accounts.social_token import PROVIDER_NAME_RE, RESERVED_NAMES

    providers = getattr(settings, "KARNI_SOCIAL_TOKEN_PROVIDERS", None) or {}
    return [
        path(
            f"social/{name}/",
            views.SocialTokenLoginView.as_view(),
            {"provider": name},
            name=f"karni-accounts-social-token-{name}",
        )
        for name in providers
        if isinstance(name, str) and PROVIDER_NAME_RE.match(name) and name not in RESERVED_NAMES
    ]


def build_urlpatterns() -> list[URLPattern | URLResolver]:
    """The auth URL patterns for the current settings (what ``urlpatterns`` holds).

    ``register/`` is present while ``KARNI_ACCOUNTS_REGISTRATION`` is true,
    ``otp/send/`` and ``otp/verify/`` while ``KARNI_EMAIL_OTP`` is, ``2fa/``
    while ``KARNI_2FA`` is, ``social/<provider>/`` for each provider
    in ``KARNI_SOCIAL_TOKEN_PROVIDERS``, and allauth's ``social/`` while
    ``KARNI_SOCIAL_AUTH`` is.
    """
    patterns: list[URLPattern | URLResolver] = list(_PERMISSION_PATTERNS)
    if getattr(settings, "KARNI_ACCOUNTS_REGISTRATION", True):
        patterns.append(
            path("register/", views.RegisterView.as_view(), name="karni-accounts-register")
        )
    patterns += _AUTH_PATTERNS
    if getattr(settings, "KARNI_EMAIL_OTP", False):
        patterns += _OTP_PATTERNS
    if getattr(settings, "KARNI_2FA", False):
        # karni.accounts.twofa exposes its own ``urlpatterns`` (setup/, confirm/,
        # disable/, login/). The dotted-path include keeps the import conditional.
        patterns.append(path("2fa/", include("karni.accounts.twofa")))
    # Before allauth's include: first match wins, and allauth's provider pages
    # are one level deeper (social/<provider>/login/), so both resolve.
    patterns += _social_token_urlpatterns()
    if getattr(settings, "KARNI_SOCIAL_AUTH", False):
        patterns.append(path("social/", include(_social_urlpatterns())))
    return patterns


urlpatterns: list[URLPattern | URLResolver] = build_urlpatterns()
