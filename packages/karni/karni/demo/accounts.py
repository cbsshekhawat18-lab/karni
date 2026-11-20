"""Experimental. Put every demo account back the way it was made.

The write rule (:mod:`karni.demo.guard`) already stops a demo account from
changing itself. :func:`ensure` is the second line: every boot and every reset
restores each account's password, flags, roles and accepted terms, and makes
an account that does not exist yet. So a reset leaves what the first boot left,
and a project that adds an account to ``KARNI_DEMO_ACCOUNTS`` gets it on the
next boot without a data migration.

``karni seed`` always makes its own demo user (``demo@example.com``, with the
known seed password). When that login is not one of the demo accounts, it is
made inactive here, so no public login exists that is not on the sign-in page.

Override / escape hatch: :func:`ensure_account` takes one account, and
``KARNI_DEMO_ACCOUNTS`` decides which exist.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from karni.demo import conf

__all__ = ["ensure", "ensure_account", "find", "find_seed_user", "seeded"]


def find(login: str) -> Any | None:
    """The user with this login, or ``None``."""
    model = get_user_model()
    found = model._base_manager.filter(**{f"{model.USERNAME_FIELD}__iexact": login}).first()
    return found


def find_seed_user() -> Any | None:
    """The user ``karni seed`` makes (``demo@example.com``), or ``None`` before the first seed."""
    return find(conf.seed_login())


def seeded() -> bool:
    """Whether the first seed has run: ``karni seed``'s demo user exists."""
    return find_seed_user() is not None


def wanted_roles(account: conf.DemoAccount) -> list[str]:
    """The roles the account holds: its list, or every role the routed API names."""
    from karni.accounts.permissions import routed_roles

    return routed_roles() if account.roles is None else list(account.roles)


def ensure_account(account: conf.DemoAccount) -> Any:
    """Make or repair one demo account: password, flags, roles, accepted terms."""
    from karni.accounts.permissions import assign_role, remove_role, user_roles

    model = get_user_model()
    names = {field.name for field in model._meta.concrete_fields}
    flags = {"is_active": True, "is_staff": account.staff, "is_superuser": account.superuser}
    if "email_verified" in names:
        flags["email_verified"] = True
    user = find(account.login)
    if user is None:
        extra = {key: value for key, value in flags.items() if key in names}
        user = model._default_manager.create_user(  # type: ignore[attr-defined]
            **{model.USERNAME_FIELD: account.login, "password": account.secret}, **extra
        )
    changed: list[str] = []
    if not user.check_password(account.secret):
        user.set_password(account.secret)
        changed.append("password")
    for flag, value in flags.items():
        if flag in names and getattr(user, flag) is not value:
            setattr(user, flag, value)
            changed.append(flag)
    if changed:
        user.save(update_fields=changed)
    wanted = wanted_roles(account)
    for role in wanted:
        assign_role(user, role)
    for role in user_roles(user):
        if role not in wanted:
            remove_role(user, role)
    _accept_terms(user)
    return user


def ensure() -> list[Any]:
    """Make or repair every demo account, and close ``karni seed``'s own if it is not listed."""
    users = [ensure_account(account) for account in conf.accounts()]
    seed_user = find_seed_user()
    if (
        seed_user is not None
        and conf.find_account(conf.seed_login()) is None
        and getattr(seed_user, "is_active", False)
    ):
        seed_user.is_active = False
        seed_user.save(update_fields=["is_active"])
    return users


def _accept_terms(user: Any) -> None:
    """Accept the current terms (``KARNI_TERMS``), so the terms gate never stops a visitor."""
    from karni.accounts import terms

    current = terms.config()
    if current is not None and not terms.has_accepted(user.pk, current.version):
        terms.accept(user, current.version, client={"source": "demo"})
