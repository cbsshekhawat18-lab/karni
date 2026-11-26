"""A mixin that ``Stamped.AdminMeta.mixins`` puts in front of the derived admin.

It adds a block under the change form (unfold's ``change_form_after_template``),
a value in the form's context and a write of its own on save: the three things
a project adds to the derived admin without registering one by hand.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest


class StampMixin(admin.ModelAdmin):
    """Shows a note under the form and stamps each row it saves."""

    change_form_after_template = "adminapp/stamp_after.html"

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict[str, Any],
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: Any = None,
    ) -> Any:
        context["stamp_note"] = "Rows saved here are stamped."
        return super().render_change_form(request, context, add, change, form_url, obj)

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        obj.stamp = f"stamped by {request.user}"
        super().save_model(request, obj, form, change)
