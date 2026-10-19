"""Load the object a ``KARNI_*`` setting names, with a Karni error when it cannot be.

A dotted path that does not import is a configuration mistake, so it is
reported as one — ``E506`` naming the setting — instead of a bare
``ModuleNotFoundError`` from somewhere inside Django.
"""

from __future__ import annotations

from typing import Any

from django.utils.module_loading import import_string

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["import_setting"]


def import_setting(name: str, path: Any, *, code: str = "E506") -> Any:
    """``import_string(path)``, where ``path`` is the value of the setting ``name``.

    A non-string value is returned as is (a project may assign the object
    itself). ``code`` lets a setting with an error code of its own keep it.
    """
    if not isinstance(path, str):
        return path
    try:
        return import_string(path)
    except ImportError as exc:
        raise KarniImproperlyConfigured(
            f"{name} ({path!r}) cannot be imported: {exc}. Name an importable "
            "'package.module.Object' (is the package installed in this environment?).",
            code=code,
        ) from exc
