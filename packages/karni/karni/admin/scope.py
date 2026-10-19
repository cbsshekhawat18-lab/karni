"""Row scope in the admin (ADR 0002, P2): the admin shows the rows the user's grants reach.

Django's model permissions still decide which screens a staff user may open;
the roles' grants (``KARNI_ROLES`` → ``RolePermission`` rows, the same data
the API's ``Granted()`` reads) decide which rows those screens show and
accept. The changelist, the change form, search, list filters, the
autocomplete endpoint, relation choices and every action go through
:func:`scope_queryset`, so a branch manager sees their branch and nothing
else — the same answer the API gives. Superusers hold every grant.

An admin class may opt out with ``scope_exempt = True`` and a
``scope_exempt_reason``; ``karni check`` lists every exemption (``E210``
without the reason).
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model, QuerySet
from django.http import HttpRequest

from karni.accounts.roles import rows_for
from karni.rows import RowFilter, apply_rows

__all__ = ["admin_rows", "scope_queryset", "scoped_choices", "within_scope"]


def _exempt(model_admin: Any) -> bool:
    return bool(getattr(model_admin, "scope_exempt", False))


def admin_rows(request: HttpRequest, model: type[Model], action: str = "view") -> RowFilter:
    """The rows ``request.user``'s grants reach for ``action`` on ``model``."""
    return rows_for(getattr(request, "user", None), model, action)


def scope_queryset(
    model_admin: Any, request: HttpRequest, queryset: QuerySet[Any]
) -> QuerySet[Any]:
    """``queryset`` narrowed to the rows the user may view, unless the admin is exempt."""
    if _exempt(model_admin):
        return queryset
    return apply_rows(queryset, admin_rows(request, queryset.model, "view"))


def within_scope(model_admin: Any, request: HttpRequest, obj: Any, action: str) -> bool:
    """Whether ``obj`` is inside the user's ``action`` scope (``True`` without an object).

    Anything that is not a model instance counts as "no object": django-unfold
    asks ``has_<action>_permission(request, object_id)`` with the raw id when
    it decides which detail buttons to show, and the view behind a button
    looks the row up through the scoped queryset anyway.
    """
    if obj is None or not isinstance(obj, Model) or _exempt(model_admin):
        return True
    rows = admin_rows(request, type(obj), action)
    if rows is True:
        return True
    if rows is False:
        return False
    # The base manager: a soft-deleted row shown through the admin's "deleted"
    # filter is still the user's row to restore.
    return apply_rows(type(obj)._base_manager.filter(pk=obj.pk), rows).exists()


def scoped_choices(request: HttpRequest, queryset: QuerySet[Any]) -> QuerySet[Any]:
    """Relation choices narrowed to the target rows the user may view.

    What the API's relation fields do (an out-of-scope primary key is invalid),
    applied to the admin's FK and M2M widgets.
    """
    return apply_rows(queryset, admin_rows(request, queryset.model, "view"))
