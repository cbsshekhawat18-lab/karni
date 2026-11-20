"""The preferences suite's URLconf: the core suite sets KARNI_PREFERENCES_API = False.

So the test app's OpenAPI snapshot stays as it is. These tests use
``ROOT_URLCONF="tests.preferences.urls"`` with the API switched on.
"""

from __future__ import annotations

from django.urls import include, path

from karni.preferences.api import build_urlpatterns

urlpatterns = [
    path("api/auth/", include("karni.accounts.urls")),
    path("api/", include(build_urlpatterns(force=True))),
]
