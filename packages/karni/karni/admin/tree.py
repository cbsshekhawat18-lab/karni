"""Experimental. A tree model's changelist: the rows in tree order, each name indented by depth.

:class:`karni.admin.KarniModelAdmin` applies it to every tree model
(:class:`karni.models.TreeModel`) with no declaration:

* the derived ``list_display`` starts with the indented name column
  (``tree_label``) in place of the model's first text field, and leaves out
  ``parent`` and ``position``, which the indentation and the order show;
* the page lists the rows depth first, siblings in the model's
  ``tree_ordering()``: a parent, then its branch, then the next sibling.
  Filters and search still apply. A row whose parent they leave out starts
  a branch of its own.

A changelist sorted by a column (``?o=``) is a flat list in that order, and
one with more than ``tree_changelist_max_rows`` rows stays in the admin's
default order: tree order reads every key of the filtered rows once (one
query) to place the page.

Override / escape hatch: set ``tree_changelist_max_rows = 0`` on an admin to
turn tree order off, declare ``list_display`` yourself (add ``"tree_label"``
to keep the indented column), or override ``get_changelist``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.admin.views.main import ORDER_VAR, ChangeList
from django.db import models
from django.http import HttpRequest
from django.utils.html import format_html

from karni.tree import is_tree_model, tree_order

__all__ = ["TreeLabel", "tree_changelist_class", "tree_list_display"]

#: The attribute each changelist row carries its depth in.
DEPTH_ATTR = "_karni_tree_depth"


class TreeLabel:
    """Experimental. The ``tree_label`` column: a row's name, indented by its depth.

    ``field`` is the model field shown (``None``: ``str(row)``). Outside tree
    order (a sorted changelist) the name is not indented.
    """

    def __init__(self, field: str | None, description: str) -> None:
        self.field = field
        self.short_description = description

    def __call__(self, obj: models.Model) -> Any:
        text = getattr(obj, self.field) if self.field else str(obj)
        depth = getattr(obj, DEPTH_ATTR, None)
        if depth is None:
            return text
        return format_html(
            '<span class="karni-tree-label" style="padding-left: {}rem">{}</span>',
            f"{depth * 1.5:g}",
            text,
        )


def tree_list_display(model: type[models.Model], derived: list[str]) -> tuple[list[str], TreeLabel]:
    """The derived ``list_display`` of a tree model, and its ``tree_label`` column."""
    rest = [name for name in derived if name not in ("parent", "position", "__str__")]
    label_field: str | None = None
    if rest:
        try:
            first = model._meta.get_field(rest[0])
        except Exception:  # noqa: BLE001 - a non-field name keeps str(row)
            first = None
        if isinstance(first, models.CharField):
            label_field = rest.pop(0)
    description = (
        str(model._meta.get_field(label_field).verbose_name)
        if label_field
        else str(model._meta.verbose_name)
    )
    return ["tree_label", *rest], TreeLabel(label_field, description.capitalize())


class _TreeChangeList:
    """Mixed in front of the admin's ``ChangeList``: the page in tree order (module docstring)."""

    model: type[models.Model]
    model_admin: Any
    queryset: Any
    params: dict[str, Any]
    result_count: int
    result_list: Any
    show_all: bool
    can_show_all: bool
    multi_page: bool
    page_num: int
    list_per_page: int

    def get_results(self, request: HttpRequest) -> None:
        super().get_results(request)  # type: ignore[misc]
        limit = int(getattr(self.model_admin, "tree_changelist_max_rows", 0) or 0)
        if ORDER_VAR in self.params or not limit or self.result_count > limit:
            return
        ordering = self.model.tree_ordering()  # type: ignore[attr-defined]
        rows = list(self.queryset.order_by(*ordering).values_list("pk", "parent_id"))
        ordered = tree_order(rows)
        if not ((self.show_all and self.can_show_all) or not self.multi_page):
            start = (self.page_num - 1) * self.list_per_page
            ordered = ordered[start : start + self.list_per_page]
        depths = dict(ordered)
        found = {row.pk: row for row in self.queryset.filter(pk__in=list(depths))}
        page = []
        for key, depth in ordered:
            row = found.get(key)
            if row is not None:
                setattr(row, DEPTH_ATTR, depth)
                page.append(row)
        self.result_list = page


_CHANGELIST_CLASSES: dict[type[ChangeList], type[ChangeList]] = {}


def tree_changelist_class(base: type[ChangeList], model: type[models.Model]) -> type[ChangeList]:
    """``base`` with tree order in front for a tree model; ``base`` itself for any other."""
    if not is_tree_model(model):
        return base
    found = _CHANGELIST_CLASSES.get(base)
    if found is None:
        found = type(f"Tree{base.__name__}", (_TreeChangeList, base), {})
        _CHANGELIST_CLASSES[base] = found
    return found
