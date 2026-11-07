"""A project's own user model on an integer key: ``id`` redeclared on AbstractKarniUser.

What docs/models.md "An integer-keyed user" shows. Installed (and set as
``AUTH_USER_MODEL``) only when the suite runs with ``KARNI_TEST_USER_PK=bigint``,
which ``tests/accounts/test_integer_user.py`` does in a subprocess.
"""

from __future__ import annotations

from django.db import models

from karni.accounts.models import AbstractKarniUser


class User(AbstractKarniUser):
    """Karni's user with a 64-bit integer key instead of the UUID."""

    id = models.BigAutoField(primary_key=True)
