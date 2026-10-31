"""Build-failing checks for ``karni check``: what protected files need to work.

* STORE001: ``KARNI_STORAGE_PROVIDER`` names a preset.
* STORE002: with ``KARNI_STORAGE=s3``, the preset has credentials.
* STORE003: with ``KARNI_STORAGE=s3``, the preset has its region, account id,
  endpoint and bucket.
* STORE004: ``karni_storage.urls`` is included, when a model has protected fields.
* STORE005: the module's settings take the values they are given.
* STORE006: every model with protected fields has a viewset on the API.

Every check is skipped when ``karni_storage`` is not in ``INSTALLED_APPS``.
Nothing here makes a network request: credentials are checked for presence.
"""

from __future__ import annotations

from typing import Any

__all__ = ["run_checks"]


def _models_with_protected_fields() -> list[Any]:
    from django.apps import apps

    from karni_storage.fields import protected_fields

    return [
        model for model in apps.get_models() if not model._meta.abstract and protected_fields(model)
    ]


def run_checks() -> list[str]:
    """Every problem found, each message starting with its code."""
    from django.apps import apps

    if not apps.is_installed("karni_storage"):
        return []
    from karni_storage.access import route_for_model
    from karni_storage.presets import problems
    from karni_storage.thumbnails import size_problems

    found = [*problems(), *size_problems()]
    models = _models_with_protected_fields()
    if not models:
        return found
    from django.urls import NoReverseMatch, reverse

    try:
        reverse("karni_storage:upload", kwargs={"resource": "x", "field": "x"})
    except NoReverseMatch:
        found.append(
            "STORE004: karni_storage.urls is not included, so protected files have no download "
            'path. Add path("api/", include("karni_storage.urls")) to config/urls.py.'
        )
    from karni_storage.fields import protected_fields

    for model in models:
        if route_for_model(model) is None:
            names = ", ".join(field.name for field in protected_fields(model))
            found.append(
                f"STORE006: {model._meta.label}.{names} is protected, but no viewset serves "
                f"{model.__name__} on the API, so nobody can download its files. Declare a "
                "BaseViewSet for it."
            )
    return found
