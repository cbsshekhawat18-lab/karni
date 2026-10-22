"""Build-failing checks for ``karni check``: the module must be wired to do anything."""

from __future__ import annotations

__all__ = ["run_checks"]

WIRING_CODE = "IMP007"
MALFORMED_CODE = "IMP008"
MIDDLEWARE = "karni_impersonation.middleware.ImpersonationMiddleware"
AUTH_MIDDLEWARE = "django.contrib.auth.middleware.AuthenticationMiddleware"


def run_checks() -> list[str]:
    from django.apps import apps
    from django.conf import settings
    from django.urls import NoReverseMatch, reverse

    from karni_impersonation import conf

    if not apps.is_installed("karni_impersonation"):
        return []  # installed in the environment, not in this project
    failures: list[str] = []
    middleware = list(getattr(settings, "MIDDLEWARE", []))
    if MIDDLEWARE not in middleware:
        failures.append(
            f"{WIRING_CODE}: add {MIDDLEWARE!r} to MIDDLEWARE after {AUTH_MIDDLEWARE!r}. "
            "Without it, impersonated sessions are never applied."
        )
    elif AUTH_MIDDLEWARE in middleware and middleware.index(MIDDLEWARE) < middleware.index(
        AUTH_MIDDLEWARE
    ):
        failures.append(f"{WIRING_CODE}: {MIDDLEWARE!r} must come after {AUTH_MIDDLEWARE!r}.")
    try:
        reverse("karni-impersonation-stop")
    except NoReverseMatch:
        failures.append(
            f"{WIRING_CODE}: include the module's URLs so the banner's exit works: "
            "path('impersonation/', include('karni_impersonation.urls'))."
        )
    blocked = conf.get("KARNI_IMPERSONATION_BLOCKED")
    if not isinstance(blocked, list | tuple) or not all(isinstance(p, str) for p in blocked):
        failures.append(f"{MALFORMED_CODE}: KARNI_IMPERSONATION_BLOCKED must be a list of strings.")
    return failures
