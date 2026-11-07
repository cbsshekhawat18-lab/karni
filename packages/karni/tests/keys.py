"""Key-type helpers for tests that run with either key type (``KARNI_TEST_PK``)."""

from __future__ import annotations

from typing import Any

from django.db import models


def missing_pk(model: type[models.Model]) -> Any:
    """A primary key of ``model``'s type that no row has: a UUID, or an integer past the last."""
    from karni.testing.hidden import _missing_value

    return _missing_value(model, "pk")
