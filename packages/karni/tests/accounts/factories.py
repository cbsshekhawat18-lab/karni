"""factory-boy factories shared by the accounts (and wider) test suite."""

from __future__ import annotations

import factory
from django.contrib.auth.hashers import make_password

DEFAULT_PASSWORD = "karni-tests-password-123"
"""The raw password every :class:`UserFactory` user authenticates with."""


class UserFactory(factory.django.DjangoModelFactory):
    """Build ``karni_accounts.User`` rows with unique emails.

    The stored password hash corresponds to :data:`DEFAULT_PASSWORD`, so
    ``user.check_password(DEFAULT_PASSWORD)`` (and login endpoints) work
    without post-generation saves. Use the ``verified`` trait for users whose
    email address is already verified::

        UserFactory(verified=True)
    """

    class Meta:
        model = "karni_accounts.User"

    class Params:
        verified = factory.Trait(email_verified=True)

    email = factory.Sequence(lambda n: f"user-{n}@example.com")
    first_name = factory.Sequence(lambda n: f"First{n}")
    last_name = factory.Sequence(lambda n: f"Last{n}")
    password = factory.LazyFunction(lambda: make_password(DEFAULT_PASSWORD))
