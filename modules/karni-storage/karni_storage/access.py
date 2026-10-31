"""Who may read or upload a protected file: whoever the row's own viewset lets through.

Every endpoint of the module starts here. :func:`resolve` finds the viewset
the API serves at ``<resource>`` and the protected field it names.
:func:`retrieve` then runs that viewset's ``retrieve`` checks for one row
without serializing it: its gate (``check_permissions``, so 401 or 403 as its
own ``retrieve`` answers) and its ``get_object()``, which looks the row up
through the read scope (404 for a row out of the caller's scope, a
soft-deleted row and a row that does not exist). :func:`may_upload` asks the
same viewset whether the caller may create or change rows. A field that
``Karni.field_roles`` hides from the caller is a 404, and one it may not
write refuses uploads.

Override / escape hatch: the viewset decides, so its ``access`` declaration,
``get_queryset`` and permission classes are the knobs. ``auto_register =
False`` on a viewset keeps its files off the API too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rest_framework.exceptions import NotFound, PermissionDenied

from karni_storage.errorcodes import coded
from karni_storage.fields import ProtectedFieldMixin

__all__ = ["Target", "may_upload", "resolve", "retrieve", "route_for_model"]


@dataclass(frozen=True)
class Target:
    """Experimental. A resource of the API and one of its protected fields."""

    resource: str
    viewset: type[Any]
    model: type[Any]
    #: A ProtectedFileField or ProtectedImageField.
    field: Any


def _registry() -> list[tuple[str, type[Any], str]]:
    from karni.api.routers import resolve_router

    router = resolve_router()
    return list(getattr(router, "registry", None) or [])


def route_for_model(model: type[Any]) -> str | None:
    """Experimental. The API prefix the first viewset serving ``model`` is routed at."""
    from karni.api.routers import serves_model

    for prefix, viewset, _basename in _registry():
        if serves_model(viewset, model):
            return str(prefix)
    return None


def _served_model(viewset: type[Any]) -> type[Any] | None:
    served = getattr(viewset, "model", None)
    if served is None:
        served = getattr(getattr(viewset, "queryset", None), "model", None)
    return served


def _not_found(message: str) -> NotFound:
    return NotFound(coded("STORE010", message), code="STORE010")


def resolve(resource: str, field: str) -> Target:
    """Experimental. The viewset at ``resource`` and its protected field ``field``.

    :raises rest_framework.exceptions.NotFound: ``STORE010`` when no viewset is
        routed at ``resource`` or ``field`` is not one of its model's protected fields.
    """
    for prefix, viewset, _basename in _registry():
        if prefix != resource:
            continue
        model = _served_model(viewset)
        try:
            found = model._meta.get_field(field) if model is not None else None
        except Exception:  # noqa: BLE001 - FieldDoesNotExist and friends: not a field
            found = None
        if model is not None and isinstance(found, ProtectedFieldMixin):
            return Target(resource, viewset, model, found)
        break
    raise _not_found(f"{resource}/ has no protected file field {field!r}.")


def _view(target: Target, request: Any, action: str, pk: str | None = None) -> Any:
    view = target.viewset()
    view.request = request
    view.args = ()
    view.kwargs = {} if pk is None else {view.lookup_url_kwarg or view.lookup_field: str(pk)}
    view.format_kwarg = None
    view.action = action
    view.action_map = {"get": action} if pk is not None else {"post": action}
    view.detail = pk is not None
    return view


def _hidden(target: Target, request: Any) -> bool:
    from karni.accounts.visibility import hidden_fields

    return target.field.name in hidden_fields(target.model, request.user)


def retrieve(target: Target, request: Any, pk: str) -> Any:
    """Experimental. The row ``pk`` exactly as the viewset's ``retrieve`` finds it for ``request``.

    :raises rest_framework.exceptions.NotAuthenticated: or ``PermissionDenied``
        when the viewset's gate refuses the caller.
    :raises django.http.Http404: when the row does not exist or is out of the
        caller's read scope, or the field is hidden from the caller.
    """
    view = _view(target, request, "retrieve", pk)
    view.check_permissions(request)
    row = view.get_object()
    if _hidden(target, request):
        raise _not_found(f"{target.resource}/ has no protected file field {target.field.name!r}.")
    return row


def may_upload(target: Target, request: Any) -> None:
    """Experimental. Refuse unless the caller may create or change rows of ``target``.

    The viewset's gate for ``create`` is asked first, then for
    ``partial_update``: a caller allowed either may upload. The row-level
    check of a change still runs when the row is saved.

    :raises rest_framework.exceptions.NotAuthenticated: or ``PermissionDenied``.
    """
    from karni.accounts.visibility import protected_fields

    refusal: Exception | None = None
    for action in ("create", "partial_update"):
        view = _view(target, request, action)
        try:
            view.check_permissions(request)
        except Exception as exc:  # noqa: BLE001 - NotAuthenticated/PermissionDenied: try the next
            refusal = refusal or exc
            continue
        if _hidden(target, request) or target.field.name in protected_fields(
            target.model, request.user
        ):
            raise PermissionDenied(f"You may not change {target.field.name}.")
        return
    assert refusal is not None
    raise refusal
