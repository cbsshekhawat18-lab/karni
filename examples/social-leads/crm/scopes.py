"""The `custom:workspace` scope: the rows of the workspaces a user is a member of."""

from typing import Any

from django.db.models import Q


def workspace_rows(user: Any, model: type) -> Q:
    """A ``Q`` for ``model`` selecting rows that belong to one of ``user``'s workspaces."""
    label = model._meta.model_name
    if label == "workspace":
        return Q(members=user)
    if label == "leadactivity":
        return Q(lead__workspace__members=user)
    return Q(workspace__members=user)
