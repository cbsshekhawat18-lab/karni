"""The demo login: one public account that every visitor signs in with.

It is the account ``karni seed`` makes (``demo@example.com``, password
``karni-password``, staff and superuser, every role the API names).
:func:`ensure` puts it back the way the seed made it, and accepts the shop's
current terms for it, so the terms gate never stops a visitor.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model


def demo_mode() -> bool:
    """Whether the demo rules apply (``DEMO_MODE``, read per call so tests can switch it)."""
    return bool(getattr(settings, "DEMO_MODE", False))


def email() -> str:
    """The demo login's email: the one ``karni seed`` gives the first user."""
    from karni.seeding import DEMO_LOGIN

    return str(DEMO_LOGIN)


def password() -> str:
    """The demo login's password: ``karni seed``'s, printed with every seed run."""
    from karni.testing.factories import DEFAULT_PASSWORD

    return str(DEFAULT_PASSWORD)


def reset_hours() -> int:
    """Hours between two resets of the demo data (``DEMO_RESET_HOURS``)."""
    return int(getattr(settings, "DEMO_RESET_HOURS", 24))


def is_demo(user: Any) -> bool:
    """Whether ``user`` is the demo account (matched by its login field)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    login = getattr(user, get_user_model().USERNAME_FIELD, None)
    return str(login or "").lower() == email()


def find() -> Any | None:
    """The demo account, or ``None`` before the first seed."""
    model = get_user_model()
    return model._base_manager.filter(**{model.USERNAME_FIELD: email()}).first()


def ensure() -> Any:
    """Put the demo account back as the seed made it: password, flags and the terms.

    The write rule (:mod:`demo.guard`) already stops the account from changing
    itself. This is the second line: every reset and every boot restores it.
    """
    user = find()
    if user is None:
        raise LookupError(f"No demo account ({email()}): run the seed first (manage.py demo_boot).")
    changed: list[str] = []
    if not user.check_password(password()):
        user.set_password(password())
        changed.append("password")
    names = {field.name for field in user._meta.concrete_fields}
    for flag in ("is_active", "is_staff", "is_superuser", "email_verified"):
        if flag in names and getattr(user, flag) is not True:
            setattr(user, flag, True)
            changed.append(flag)
    if changed:
        user.save(update_fields=changed)
    _accept_terms(user)
    return user


def _accept_terms(user: Any) -> None:
    """Accept the shop's current terms (``KARNI_TERMS``) for the demo account."""
    from karni.accounts import terms

    current = terms.config()
    if current is not None and not terms.has_accepted(user.pk, current.version):
        terms.accept(user, current.version, client={"source": "demo"})
