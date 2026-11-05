"""Bulk edit in the admin: set chosen fields to one value on every selected row.

:class:`BulkEditAdminMixin` is part of every Karni admin. It adds the changelist
action *Edit selected*: the user ticks rows, picks the action, and a form lists
the fields they may change. They tick *Change* beside each field they want to
set, give it one value, and confirm.

What it guarantees:

* **Row by row, in one transaction.** Each row is changed with ``obj.save()``
  (never ``QuerySet.update()``), so signals, ``on_updated`` listeners,
  ``updated_at`` and the change history (``Karni.audit``) behave as for an edit
  of one row, and every row gets an admin log entry. One row that fails
  validation (or a listener refuses) rolls every row back, and the form shows
  which row and why.
* **Permissions.** The action needs the change permission, each row has to be
  inside the user's ``change`` scope, and a field the user may not change
  (``Karni.field_roles``, ``readonly_fields``) or may not see is not offered.
* **A limit.** ``KARNI_ADMIN_BULK_EDIT_MAX`` (default 500) rows at most. A bigger
  selection gets a clear message and nothing is changed.
* **The response cache** is invalidated once, when the action ends (the
  admin's ``response_action`` batches it).

Fields that cannot take one value for many rows are left out: the primary key,
unique fields, fields in a unique together, many-to-many, file and image
fields, lifecycle states (each row's legal moves differ), JSON, and the audit
fields.

Override / escape hatch: ``karni_bulk_edit = False`` on an admin class removes
the action, :meth:`BulkEditAdminMixin.bulk_editable_fields` decides which fields
are offered, ``bulk_edit_template`` swaps the page, and
``KARNI_ADMIN_BULK_EDIT_MAX`` sets the limit.
"""

from __future__ import annotations

import copy
from typing import Any, ClassVar

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.utils.text import capfirst
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from karni.conflicts import KarniConflict
from karni.exceptions import KarniWriteDeferred

__all__ = ["BULK_EDIT_MAX", "BulkEditAdminMixin", "bulk_edit_max"]

BULK_EDIT_MAX = 500
"""Fallback for the ``KARNI_ADMIN_BULK_EDIT_MAX`` setting."""

APPLY_PREFIX = "apply__"
"""The name of the *Change* checkbox beside a field: ``apply__<field>``."""

_SAMPLE = 5


def bulk_edit_max() -> int:
    """The most rows *Edit selected* changes at once (``KARNI_ADMIN_BULK_EDIT_MAX``)."""
    return int(getattr(settings, "KARNI_ADMIN_BULK_EDIT_MAX", BULK_EDIT_MAX))


class _Refused(Exception):
    """A row failed: the transaction rolls back and the form shows why."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class BulkEditForm(forms.Form):
    """One optional value per editable field, each with a *Change this field* checkbox.

    ``chosen`` (after ``is_valid()``) maps the field names the user ticked to
    their cleaned values. A field the model does not allow to be empty needs a
    value once it is ticked.
    """

    model_fields: dict[str, models.Field]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.chosen: dict[str, Any] = {}

    def rows(self) -> list[tuple[forms.BoundField, forms.BoundField]]:
        """``(change checkbox, value field)`` per offered field, in display order."""
        return [(self[APPLY_PREFIX + name], self[name]) for name in self.model_fields]

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        for name, field in self.model_fields.items():
            if not cleaned.get(APPLY_PREFIX + name):
                continue
            value = cleaned.get(name)
            empty = value is None or value == "" or value == []
            if (
                empty
                and not (field.blank or field.null)
                and not isinstance(field, models.BooleanField)
            ):
                self.add_error(name, _("Give a value for this field, or leave it unticked."))
                continue
            if name in self.errors:
                continue
            self.chosen[name] = None if (empty and field.null and value == "") else value
        if not self.chosen and not self.errors:
            raise ValidationError(_("Tick Change beside at least one field."))
        return cleaned


class BulkEditAdminMixin(admin.ModelAdmin):
    """The *Edit selected* action. See the module docstring."""

    karni_bulk_edit: ClassVar[bool] = True
    """``False`` removes *Edit selected* from this admin."""

    bulk_edit_template: ClassVar[str] = "karni_admin/edit_selected.html"

    def __init__(self, model: type[models.Model], admin_site: admin.AdminSite) -> None:
        super().__init__(model, admin_site)
        if self.karni_bulk_edit:
            current = list(getattr(self, "actions", None) or ())
            if "edit_selected" not in current:
                self.actions = [*current, "edit_selected"]

    def get_actions(self, request: HttpRequest) -> Any:
        found = super().get_actions(request)
        if not self.karni_bulk_edit:
            found.pop("edit_selected", None)
        return found

    # -- which fields -------------------------------------------------------

    def bulk_editable_fields(self, request: HttpRequest) -> list[models.Field]:
        """The fields *Edit selected* offers this user, in the form's order.

        The form's own fields (so a field the admin excludes, hides or shows
        read-only is not offered), without the ones that cannot share one value
        across rows (see the module docstring) and without any field the user's
        ``field_roles`` stop them from changing.

        Override / escape hatch: override this method to offer fewer or more.
        """
        from karni.accounts.visibility import hidden_fields, protected_fields
        from karni.admin.derive import AUDIT_FIELDS

        user = getattr(request, "user", None)
        blocked = hidden_fields(self.model, user) | protected_fields(self.model, user)
        blocked |= set(self.get_readonly_fields(request))
        offered = set(self.get_form(request, None, change=True).base_fields)
        unique = _unique_together_names(self.model)
        chosen: list[models.Field] = []
        for field in self.model._meta.concrete_fields:
            if field.name not in offered or field.name in blocked or field.name in AUDIT_FIELDS:
                continue
            if field.primary_key or field.unique or field.name in unique or not field.editable:
                continue
            if isinstance(field, models.FileField | models.JSONField):
                continue
            if _is_state_field(field):
                continue
            chosen.append(field)
        return chosen

    def bulk_edit_form(
        self, request: HttpRequest, fields: list[models.Field]
    ) -> type[BulkEditForm]:
        """The form class: the admin's own form field of each offered field, made optional."""
        base_fields = self.get_form(request, None, change=True).base_fields
        declared: dict[str, forms.Field] = {}
        model_fields: dict[str, models.Field] = {}
        for field in fields:
            declared[APPLY_PREFIX + field.name] = forms.BooleanField(
                required=False,
                label=_("Change %(field)s") % {"field": capfirst(str(field.verbose_name))},
            )
            value_field = copy.deepcopy(base_fields[field.name])
            value_field.required = False
            declared[field.name] = value_field
            model_fields[field.name] = field
        return type(
            "BulkEditForm",
            (BulkEditForm,),
            {**declared, "model_fields": model_fields},
        )

    # -- the action ---------------------------------------------------------

    @admin.action(
        description=gettext_lazy("Edit selected %(verbose_name_plural)s"),
        permissions=["change"],
    )
    def edit_selected(
        self, request: HttpRequest, queryset: QuerySet[Any]
    ) -> TemplateResponse | None:
        """Set the ticked fields to one value on every selected row (see the module docstring)."""
        limit = bulk_edit_max()
        count = queryset.count()
        if count > limit:
            self.message_user(
                request,
                _(
                    "You selected %(count)d rows and Edit selected changes at most %(limit)d at "
                    "a time. Narrow the list with a search or a filter, select fewer rows "
                    "and try again."
                )
                % {"count": count, "limit": limit},
                messages.ERROR,
            )
            return None
        fields = self.bulk_editable_fields(request)
        if not fields:
            self.message_user(
                request,
                _("None of the fields of these rows can be changed in bulk by you."),
                messages.ERROR,
            )
            return None
        form_class = self.bulk_edit_form(request, fields)
        confirmed = request.POST.get("post") == "yes"
        form = form_class(request.POST if confirmed else None)
        problems: list[str] = []
        if confirmed and form.is_valid():
            try:
                changed = self._apply(request, queryset, fields, form.chosen)
            except _Refused as refused:
                problems = refused.problems
            else:
                self.message_user(
                    request,
                    _("Changed %(count)d %(items)s: %(fields)s.")
                    % {
                        "count": changed,
                        "items": str(
                            self.opts.verbose_name
                            if changed == 1
                            else self.opts.verbose_name_plural
                        ),
                        "fields": ", ".join(
                            capfirst(str(f.verbose_name)) for f in fields if f.name in form.chosen
                        ),
                    },
                    messages.SUCCESS,
                )
                return None
        opts = self.model._meta
        rows = list(queryset[:_SAMPLE])
        context = {
            **self.admin_site.each_context(request),
            "title": _("Edit selected %(name)s") % {"name": opts.verbose_name_plural},
            "subtitle": None,
            "opts": opts,
            "form": form,
            "form_rows": form.rows(),
            "problems": problems,
            "count": count,
            "limit": limit,
            "sample": [str(row) for row in rows],
            "more": max(count - len(rows), 0),
            "queryset": queryset.values_list("pk", flat=True),
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "media": self.media + form.media,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, self.bulk_edit_template, context)

    def _apply(
        self,
        request: HttpRequest,
        queryset: QuerySet[Any],
        fields: list[models.Field],
        chosen: dict[str, Any],
    ) -> int:
        """Save each row with the chosen values, all or nothing. Returns the rows changed."""
        from karni.admin.scope import within_scope

        labels = [capfirst(str(f.verbose_name)) for f in fields if f.name in chosen]
        by_name = {f.name: f for f in fields}
        untouched = [f.name for f in self.model._meta.fields if f.name not in chosen]
        changed = 0
        deferred = 0
        problems: list[str] = []
        with transaction.atomic(using=queryset.db):
            for obj in queryset:
                if not self.has_change_permission(request, obj) or not within_scope(
                    self, request, obj, "change"
                ):
                    raise PermissionDenied
                for name, value in chosen.items():
                    by_name[name].save_form_data(obj, value)
                try:
                    obj.full_clean(exclude=untouched)
                    obj.save()
                except ValidationError as exc:
                    problems.append(f"{obj}: {'; '.join(exc.messages)}")
                except KarniWriteDeferred:
                    deferred += 1
                    continue
                except KarniConflict as exc:
                    problems.append(f"{obj}: {exc}")
                else:
                    self.log_change(
                        request,
                        obj,
                        [{"changed": {"name": str(self.opts.verbose_name), "fields": labels}}],
                    )
                    changed += 1
                if problems:
                    raise _Refused(problems)
        if deferred:
            self.message_user(
                request,
                _("%(count)d rows wait for approval and are not changed yet.")
                % {"count": deferred},
                messages.INFO,
            )
        return changed


def _unique_together_names(model: type[models.Model]) -> set[str]:
    names: set[str] = set()
    for group in model._meta.unique_together:
        names.update(group)
    for constraint in model._meta.constraints:
        if isinstance(constraint, models.UniqueConstraint):
            names.update(constraint.fields)
    return names


def _is_state_field(field: models.Field) -> bool:
    from karni.fields import StateField

    return isinstance(field, StateField)
