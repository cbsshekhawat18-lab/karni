"""Field-level visibility (ADR 0002, P3): which fields a user may see or change on a model.

``class Karni: field_roles`` on the model names, per field, the roles that
may read it and the roles that may write it; the role slugs are the
project's own (``KARNI_ROLES``). Everything that renders or accepts a field
asks here — the generated serializer, the filter, ordering and search
backends, the OpenAPI schema and the admin — so a hidden field is absent on
every surface, not just one. Superusers see and change everything.
"""

from __future__ import annotations

from typing import Any, Final

from django.db import models

from karni.meta import field_roles

__all__ = [
    "allowed_roles",
    "hidden_fields",
    "protected_fields",
    "role_names",
    "visible",
]

_ROLES_ATTR: Final = "_karni_role_names"


def role_names(user: Any) -> frozenset[str]:
    """The user's role slugs, resolved once per user instance (so once per request)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    cached = getattr(user, _ROLES_ATTR, None)
    if cached is not None:
        return cached
    from karni.accounts.permissions import user_roles

    names = frozenset(user_roles(user))
    setattr(user, _ROLES_ATTR, names)
    return names


def _fields_denied(model: type[models.Model], user: Any, action: str) -> frozenset[str]:
    rules = field_roles(model)
    if not rules or getattr(user, "is_superuser", False):
        return frozenset()
    roles = role_names(user)
    return frozenset(
        name for name, rule in rules.items() if roles.isdisjoint(getattr(rule, action))
    )


def hidden_fields(model: type[models.Model], user: Any) -> frozenset[str]:
    """Fields of ``model`` that ``user`` may not read: absent from every surface."""
    return _fields_denied(model, user, "read")


def protected_fields(model: type[models.Model], user: Any) -> frozenset[str]:
    """Fields of ``model`` that ``user`` may not write (read-only, or rejected on input)."""
    return _fields_denied(model, user, "write")


def visible(model: type[models.Model], user: Any, names: Any) -> list[str]:
    """``names`` without the fields hidden from ``user`` (a lookup's head decides)."""
    hidden = hidden_fields(model, user)
    if not hidden:
        return list(names)
    return [name for name in names if str(name).lstrip("^=@$").split("__", 1)[0] not in hidden]


def allowed_roles(model: type[models.Model], name: str, action: str = "write") -> tuple[str, ...]:
    """The roles ``field_roles`` lets ``action`` the field (for messages)."""
    rule = field_roles(model).get(name)
    return getattr(rule, action) if rule is not None else ()
