"""Experimental. ``NavItem``: the menu as a tree of rows, for ``KARNI_NAVIGATION = "db"``."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from karni import navigation
from karni.models import BaseModel, OrderedTreeModel

__all__ = ["NavItem", "validate_icon", "validate_requirement", "validate_route"]


def _refuse(problem: str | None, code: str) -> None:
    if problem:
        raise ValidationError(f"{problem[0].upper()}{problem[1:]}. ({code})", code=code)


def validate_route(value: Any) -> None:
    """Experimental. An app path from ``/`` (``E530``). Empty is a group."""
    _refuse(navigation.route_problem(value) if value else None, "E530")


def validate_icon(value: Any) -> None:
    """Experimental. An icon name such as ``home`` (``E530``)."""
    _refuse(navigation.icon_problem(value), "E530")


def validate_requirement(value: Any) -> None:
    """Experimental. ``public``, ``authenticated`` or a permission pattern (``E532``)."""
    _refuse(navigation.requirement_problem(value), "E532")


class NavItem(OrderedTreeModel, BaseModel):
    """Experimental. One entry of the database menu: an item with a route, or a group without one.

    ``parent`` and ``position`` (:class:`~karni.models.OrderedTreeModel`) place
    it in the tree and among its siblings. ``requires`` is ``public``,
    ``authenticated`` (the default) or a permission pattern as in
    ``KARNI_ROLES`` grants, so role grants and per-user grants both open it.
    A group shows when an entry inside it shows. Every change is history
    (``karni.audit``).

    ``clean()`` (the admin form) refuses a route on a node with children and a
    child under a node with a route (``E536``).

    Override / escape hatch: the menu is read through
    :func:`karni.navigation.nodes_from_db`, and ``menu_for(user, nodes=...)``
    takes nodes from any source.
    """

    label = models.CharField(max_length=navigation.LABEL_MAX)
    route = models.CharField(
        max_length=navigation.ROUTE_MAX,
        blank=True,
        default="",
        validators=[validate_route],
        help_text="An app path such as /products. Empty: a group, which holds other entries.",
    )
    icon = models.CharField(
        max_length=navigation.ICON_MAX,
        blank=True,
        default="",
        validators=[validate_icon],
        help_text="An icon name the frontend knows, e.g. home or bar-chart.",
    )
    requires = models.CharField(
        max_length=navigation.REQUIRES_MAX,
        default=navigation.AUTHENTICATED,
        validators=[validate_requirement],
        help_text=(
            "public, authenticated, or a permission pattern as in KARNI_ROLES "
            "(app_label.model:action, with * for a part)."
        ),
    )

    class Meta(BaseModel.Meta):
        verbose_name = "navigation item"
        verbose_name_plural = "navigation items"

    class Karni:
        audit = True

    def __str__(self) -> str:
        return self.label

    def clean(self) -> None:
        """The tree's parent rule, then: a route and children never go together (``E536``)."""
        super().clean()
        if self.parent_id is not None:
            parent = type(self)._default_manager.filter(pk=self.parent_id).first()
            if parent is not None and parent.route:
                raise ValidationError(
                    {
                        "parent": [
                            f"{parent.label} links to {parent.route}, so it holds no entries. "
                            "Choose a group (an entry without a route) as the parent. (E536)"
                        ]
                    },
                    code="E536",
                )
        if self.route and self.pk is not None and self.live_children_count():
            raise ValidationError(
                {
                    "route": [
                        f"{self.label} holds entries, so it is a group and has no route. Add an "
                        "entry inside it for the route. (E536)"
                    ]
                },
                code="E536",
            )
