"""Who may see a row's report: whoever may retrieve the row through its viewset.

:func:`retrieve` runs a viewset's ``retrieve`` checks for one row without
serializing it: the viewset's gate (``check_permissions``, so 401 or 403 as
its own ``retrieve`` would answer), then its ``get_object()``, which looks the
row up through the read scope (404 for a row out of the caller's scope) and
checks the row against the gate's predicate. Every report endpoint calls it,
and the download calls it again.

Override / escape hatch: ``Report.viewset`` names another viewset, and
``Report.get_object`` replaces the whole check for one report.
"""

from __future__ import annotations

from typing import Any

__all__ = ["retrieve"]


def retrieve(viewset_class: type[Any], request: Any, object_id: str) -> Any:
    """Experimental. The row ``object_id`` as ``viewset_class``'s ``retrieve`` finds it.

    ``request`` is the caller's DRF request.

    :raises rest_framework.exceptions.NotAuthenticated: (401 or 403) or
        ``PermissionDenied`` (403) when the viewset's gate refuses the caller.
    :raises django.http.Http404: when the row does not exist or is out of the
        caller's read scope.
    """
    view = viewset_class()
    view.request = request
    view.args = ()
    view.kwargs = {view.lookup_url_kwarg or view.lookup_field: str(object_id)}
    view.format_kwarg = None
    view.action = "retrieve"
    view.action_map = {"get": "retrieve"}
    view.detail = True
    view.check_permissions(request)
    return view.get_object()
