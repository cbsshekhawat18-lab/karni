"""Soft-delete awareness for derived admins.

Applies only to :class:`karni.models.SoftDeleteModel` subclasses:
``autodiscover()`` puts :class:`SoftDeleteAdminMixin` in front of
``KarniModelAdmin`` when building their admin classes. The changelist and
change form see every row (``all_objects``); the default changelist view is
scoped back to alive rows by :class:`SoftDeleteListFilter`.

Django's builtin ``delete_selected`` stays available and is *soft* on these
models (``queryset.delete()`` is soft on both managers). Note that its
confirmation page lists cascade children that a soft delete will not touch —
a documented v0.1 trade-off. ``hard_delete_selected`` is the explicit,
superuser-only, confirmed path to real deletion.

Override / escape hatch: subclass the mixin (or override any method in
``AdminMeta.extra``) — every hook is a plain ``ModelAdmin`` method.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.utils import model_ngettext
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

if TYPE_CHECKING:
    from collections.abc import Generator

    from django.contrib.admin.views.main import ChangeList

    from karni.models import SoftDeleteModel


def _is_autocomplete_request(request: HttpRequest) -> bool:
    """True when ``request`` targets the admin site's autocomplete endpoint."""
    match = getattr(request, "resolver_match", None)
    if match is not None:
        return match.url_name == "autocomplete"
    return request.path.rstrip("/").endswith("autocomplete")


class SoftDeleteListFilter(admin.SimpleListFilter):
    """Changelist filter over ``deleted_at``: alive (default) / deleted / all.

    No filter value selects alive rows only, ``?deleted=deleted`` selects only
    soft-deleted rows, and ``?deleted=all`` shows everything. The default
    choice is relabelled (there is no automatic "All" entry). Facets
    (Django 5.1 ``?_facets``) are supported through the stock
    ``SimpleListFilter`` machinery.

    Override / escape hatch: subclass and list yours first via
    ``AdminMeta.list_filter`` (or ``AdminMeta.extra``) on the model.
    """

    title = gettext_lazy("deleted")
    parameter_name = "deleted"

    def lookups(self, request: HttpRequest, model_admin: admin.ModelAdmin) -> list[tuple[str, str]]:
        """Return the two non-default choices; the default is emitted by ``choices()``."""
        return [("deleted", _("Deleted")), ("all", _("All"))]

    def queryset(self, request: HttpRequest | None, queryset: QuerySet) -> QuerySet:
        """Scope ``queryset`` by the selected value; alive-only by default.

        ``request`` may be ``None`` when Django computes facet counts.
        """
        value = self.value()
        if value == "deleted":
            return queryset.filter(deleted_at__isnull=False)
        if value == "all":
            return queryset
        return queryset.filter(deleted_at__isnull=True)

    def choices(self, changelist: ChangeList) -> Generator[dict[str, Any]]:
        """Mirror ``SimpleListFilter.choices`` but relabel the default entry."""
        add_facets = changelist.add_facets
        facet_counts = self.get_facet_queryset(changelist) if add_facets else {}
        yield {
            "selected": self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": _("Not deleted"),
        }
        for i, (lookup, title) in enumerate(self.lookup_choices):
            if add_facets:
                count = facet_counts.get(f"{i}__c", -1)
                title = f"{title} ({count})" if count != -1 else f"{title} (-)"
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }


class SoftDeleteAdminMixin(admin.ModelAdmin):
    """Admin behaviour for soft-delete models.

    * ``get_queryset()`` uses ``all_objects`` so the filter can show deleted
      rows (and deleted rows stay editable through the change form).
    * Autocomplete responses stay alive-only.
    * ``restore_selected`` and the superuser-only, confirmation-guarded
      ``hard_delete_selected`` actions join the builtin (soft)
      ``delete_selected``.

    Override / escape hatch: every method is a stock ``ModelAdmin`` hook;
    ``has_hard_delete_permission()`` gates the hard-delete action, and
    ``hard_delete_selected_confirmation_template`` swaps the confirmation
    page. Inline forms (not built from this mixin) keep alive-only FK choices.
    """

    actions = ("restore_selected", "hard_delete_selected")

    #: Template used by :meth:`hard_delete_selected`'s confirmation page.
    #: Set a template path to replace ``karni_admin/hard_delete_selected_confirmation.html``.
    hard_delete_selected_confirmation_template: str | None = None

    model: type[SoftDeleteModel]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Return ``all_objects`` (deleted included), with admin ordering applied.

        Mirrors ``ModelAdmin.get_queryset`` exactly, swapping the default
        manager for ``all_objects``; :class:`SoftDeleteListFilter` scopes the
        changelist back to alive rows by default.
        """
        queryset = self.model.all_objects.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            queryset = queryset.order_by(*ordering)
        return queryset

    def get_list_filter(self, request: HttpRequest) -> list[Any]:
        """Guarantee the "deleted" filter, whatever ``list_filter`` says.

        ``get_queryset()`` exposes every row, so the changelist is only
        alive-by-default *because* :class:`SoftDeleteListFilter` scopes it.
        Derivation prepends the filter itself, but an explicit
        ``AdminMeta.list_filter`` (or subclass attribute) must not silently
        mix deleted rows into the changelist, so it is prepended here when
        missing.

        Override / escape hatch: override this method (via a subclass or
        ``AdminMeta.extra``) to drop the filter deliberately.
        """
        filters = list(super().get_list_filter(request))
        if SoftDeleteListFilter not in filters:
            filters.insert(0, SoftDeleteListFilter)
        return filters

    def get_search_results(
        self, request: HttpRequest, queryset: QuerySet, search_term: str
    ) -> tuple[QuerySet, bool]:
        """Keep autocomplete responses alive-only; other searches see all rows."""
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        if _is_autocomplete_request(request):
            queryset = queryset.filter(deleted_at__isnull=True)
        return queryset, may_have_duplicates

    def has_hard_delete_permission(self, request: HttpRequest) -> bool:
        """Gate ``hard_delete_selected``: superusers only.

        Override / escape hatch: relax or tighten per project by overriding
        this method (via a ``KarniModelAdmin`` subclass or ``AdminMeta.extra``).
        """
        return request.user.is_superuser

    @admin.action(
        description=gettext_lazy("Restore selected %(verbose_name_plural)s"),
        permissions=["change"],
    )
    def restore_selected(self, request: HttpRequest, queryset: QuerySet) -> None:
        """Un-delete the selected rows (``deleted_at=None``).

        Uses ``.update(...)``, so ``auto_now`` does not fire: ``updated_at``
        is set explicitly when the model has it (a standalone
        ``SoftDeleteModel`` may not).
        """
        changes: dict[str, object] = {"deleted_at": None}
        if any(f.name == "updated_at" for f in queryset.model._meta.concrete_fields):
            changes["updated_at"] = timezone.now()
        restored = queryset.filter(deleted_at__isnull=False).update(**changes)
        self.message_user(
            request,
            _("Restored %(count)d %(items)s.")
            % {"count": restored, "items": model_ngettext(self.opts, restored)},
            messages.SUCCESS,
        )

    @admin.action(
        description=gettext_lazy("Hard delete selected %(verbose_name_plural)s"),
        permissions=["hard_delete"],
    )
    def hard_delete_selected(
        self, request: HttpRequest, queryset: QuerySet
    ) -> TemplateResponse | None:
        """Really delete the selected rows, after an intermediate confirmation.

        Follows the builtin ``delete_selected`` pattern: first render a
        confirmation page listing everything the database cascade will remove,
        then, on the confirmed POST, call ``queryset.hard_delete()``.
        """
        opts = self.model._meta
        deletable_objects, model_count, perms_needed, protected = self.get_deleted_objects(
            queryset, request
        )

        if request.POST.get("post") and not protected:
            if perms_needed:
                raise PermissionDenied
            count = queryset.count()
            if count:
                self.log_deletions(request, queryset)
                queryset.hard_delete()
                self.message_user(
                    request,
                    _("Successfully hard deleted %(count)d %(items)s.")
                    % {"count": count, "items": model_ngettext(self.opts, count)},
                    messages.SUCCESS,
                )
            return None

        objects_name = model_ngettext(queryset)
        if perms_needed or protected:
            title = _("Cannot delete %(name)s") % {"name": objects_name}
        else:
            title = _("Are you sure?")
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "subtitle": None,
            "objects_name": str(objects_name),
            "deletable_objects": [deletable_objects],
            "model_count": dict(model_count).items(),
            "queryset": queryset,
            "perms_lacking": perms_needed,
            "protected": protected,
            "opts": opts,
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "media": self.media,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            self.hard_delete_selected_confirmation_template
            or [
                f"admin/{opts.app_label}/{opts.model_name}/hard_delete_selected_confirmation.html",
                f"admin/{opts.app_label}/hard_delete_selected_confirmation.html",
                "karni_admin/hard_delete_selected_confirmation.html",
            ],
            context,
        )
