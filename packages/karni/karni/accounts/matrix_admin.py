"""The permission matrix and effective-permissions admin pages (ADR 0002, P5).

Plain view functions a ``ModelAdmin`` method hands the request to (see
:mod:`karni.accounts.admin`), so they work on django-unfold's ``ModelAdmin``
and on any other ``KARNI_ADMIN_BASE`` alike. ``admin_view`` has already
required a staff login; the grants decide the rest —
``karni_accounts.rolepermission:view`` to look, ``:change`` to edit, and the
guard rails in :mod:`karni.accounts.matrix` for every change.

The matrix page posts every cell (``cell:<role>:<app.model:action>``); the
confirmation page shows the diff and re-posts only the changed cells
(``change:<role>:<permission>``) with ``confirm=1``. Nothing is written
before the second post.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from karni.accounts.matrix import (
    MATRIX_PERMISSION,
    EffectiveReport,
    Matrix,
    MatrixRefused,
    apply_changes,
    build_matrix,
    effective_permissions,
    plan_changes,
    recent_changes,
)
from karni.accounts.roles import user_can

__all__ = ["effective_view", "matrix_view"]

CELL_PREFIX = "cell:"
CHANGE_PREFIX = "change:"


def _requested(data: Any, prefix: str) -> list[tuple[str, str, str | None]]:
    found: list[tuple[str, str, str | None]] = []
    for name in data:
        if not name.startswith(prefix):
            continue
        _, role, permission = name.split(":", 2)
        raw = data.get(name, "")
        found.append((role, permission, raw or None))
    return found


def _table(matrix: Matrix) -> list[dict[str, Any]]:
    """The matrix as nested rows the template can walk: model → action → one cell per role."""
    groups: list[dict[str, Any]] = []
    for model in matrix.models:
        actions = []
        for action in model.actions:
            permission = model.permission(action)
            cells = []
            for role in matrix.roles:
                cell = matrix.cell(role.slug, permission)
                cells.append(
                    {
                        "name": f"{CELL_PREFIX}{role.slug}:{permission}",
                        "role": role.slug,
                        "value": cell.scope or "",
                        "origin": cell.origin,
                        "declared": cell.declared,
                        "locked": cell.locked,
                        "options": [
                            (value, label, value == cell.scope) for value, label in model.scopes
                        ],
                    }
                )
            actions.append({"action": action, "permission": permission, "cells": cells})
        groups.append({"model": model, "actions": actions})
    return groups


def matrix_view(model_admin: Any, request: HttpRequest) -> HttpResponse:
    """``GET``: the matrix. ``POST``: the confirmation diff; with ``confirm=1``, apply it."""
    user = request.user
    if not user_can(user, f"{MATRIX_PERMISSION}:view"):
        raise PermissionDenied
    can_edit = user_can(user, f"{MATRIX_PERMISSION}:change")
    site = model_admin.admin_site
    base = {**site.each_context(request), "model_admin": model_admin, "matrix_url": request.path}

    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        confirming = request.POST.get("confirm") == "1"
        requested = _requested(request.POST, CHANGE_PREFIX if confirming else CELL_PREFIX)
        if confirming:
            try:
                plan = apply_changes(user, requested)
            except MatrixRefused as exc:
                plan = exc.plan
            else:
                count = len(plan.changes)
                messages.success(
                    request,
                    ngettext("%(count)d grant changed.", "%(count)d grants changed.", count)
                    % {"count": count},
                )
                return HttpResponseRedirect(request.path)
        else:
            plan = plan_changes(user, requested)
            if not plan.changes and not plan.refusals:
                messages.info(request, _("Nothing changed."))
                return HttpResponseRedirect(request.path)
        context = {
            **base,
            "title": _("Confirm permission changes"),
            "plan": plan,
            "replay": [
                (f"{CHANGE_PREFIX}{c.role}:{c.permission}", c.after or "") for c in plan.changes
            ],
        }
        return TemplateResponse(request, "karni_accounts/permission_matrix_confirm.html", context)

    matrix = build_matrix()
    context = {
        **base,
        "title": _("Permission matrix"),
        "matrix": matrix,
        "table": _table(matrix),
        "can_edit": can_edit,
        "recent": recent_changes(),
    }
    return TemplateResponse(request, "karni_accounts/permission_matrix.html", context)


def _find_user(query: str) -> Any | None:
    model = get_user_model()
    manager = model._default_manager
    found = manager.filter(**{f"{model.USERNAME_FIELD}__iexact": query}).first()
    if found is not None:
        return found
    try:
        return manager.filter(pk=query).first()
    except (ValueError, ValidationError):
        return None


def _grouped(report: EffectiveReport | None) -> list[dict[str, Any]]:
    groups: dict[str, list[Any]] = {}
    for entry in report.entries if report is not None else []:
        groups.setdefault(entry.model, []).append(entry)
    return [{"model": model, "entries": entries} for model, entries in groups.items()]


def effective_view(model_admin: Any, request: HttpRequest, user: Any = None) -> HttpResponse:
    """What one user may do and why. Without ``user``, ``?user=<email or id>`` picks one."""
    viewer = request.user
    query = ""
    if user is None:
        query = request.GET.get("user", "").strip()
        if query:
            user = _find_user(query)
            if user is None:
                messages.error(request, _("No user matches %(query)s.") % {"query": query})
    if (
        user is not None
        and user.pk != viewer.pk
        and not user_can(viewer, f"{MATRIX_PERMISSION}:view")
    ):
        raise PermissionDenied
    report = effective_permissions(user) if user is not None else None
    context = {
        **model_admin.admin_site.each_context(request),
        "model_admin": model_admin,
        "title": _("Effective permissions"),
        "query": query,
        "subject": user,
        "report": report,
        "grouped": _grouped(report),
    }
    return TemplateResponse(request, "karni_accounts/effective_permissions.html", context)
