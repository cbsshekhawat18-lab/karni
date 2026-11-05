"""The project under test: a product catalog with protected files.

``KARNI_TEST_PK=bigint`` puts ``Product`` and ``Brochure`` on integer keys
(``BigIntBaseModel``), so the download path is checked with both key types.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, TypeAlias

from django.conf import settings
from django.db import models
from karni.models import BaseModel, BigIntBaseModel

from karni_storage.fields import ProtectedFileField, ProtectedImageField

TEST_PK = os.environ.get("KARNI_TEST_PK", "uuid")
if TEST_PK not in ("uuid", "bigint"):
    raise RuntimeError(f"KARNI_TEST_PK must be uuid or bigint, not {TEST_PK!r}.")

if TYPE_CHECKING:
    ApiBase: TypeAlias = BaseModel  # noqa: UP040 - a base class, under TYPE_CHECKING only
else:
    ApiBase = BigIntBaseModel if TEST_PK == "bigint" else BaseModel


class Product(ApiBase):
    """A product with a protected manual and a protected photo, owned by one user."""

    name = models.CharField(max_length=100)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    manual = ProtectedFileField(
        upload_to="products/manuals/",
        blank=True,
        max_size=1024 * 1024,
        content_types=["application/pdf", "text/plain"],
    )
    photo = ProtectedImageField(upload_to="products/photos/", blank=True)
    #: Only staff may see or change it (Karni.field_roles): hidden from the owner.
    invoice = ProtectedFileField(upload_to="products/invoices/", blank=True)

    class Karni:
        owner_field = "owner"
        field_roles = {"invoice": ["staff"]}

    def __str__(self) -> str:
        return self.name


class Brochure(ApiBase):
    """A protected file on a model no viewset serves (STORE006)."""

    title = models.CharField(max_length=100)
    scan = ProtectedFileField(upload_to="brochures/", blank=True)

    def __str__(self) -> str:
        return self.title
