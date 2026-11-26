"""The people contract in the admin: people, organisations, merge and erase.

``PersonAdmin`` and ``OrganisationAdmin`` list and edit the rows with their
memberships and addresses inline. Two bulk actions:

* *Merge the selected two*: pick exactly two rows, see the plan
  (:func:`karni.people.merge_plan`: what moves, which blank fields fill,
  what refuses), choose which row stays, and confirm. Needs the explicit
  ``merge`` permission (``people.person:merge``).
* *Erase the selected people's data* (people only): a confirmation page,
  then :func:`karni.people.erase` for each. Needs ``people.person:erase``.

Override / escape hatch: register your own admin for these models first
(``admin.site.unregister(Person)`` then ``admin.site.register(...)``), or
subclass :class:`PersonAdmin` / :class:`OrganisationAdmin`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _

from karni.admin import KarniModelAdmin
from karni.imports import import_setting
from karni.people import services
from karni.people.models import Address, Membership, Organisation, Person

__all__ = ["OrganisationAdmin", "PersonAdmin", "merge_view"]


def _inlines(owner: str) -> list[Any]:
    from karni.admin.inlines import build_inline

    return [build_inline(Membership, owner), build_inline(Address, owner)]


def merge_view(model_admin: Any, request: HttpRequest, queryset: QuerySet[Any]) -> Any:
    """The merge action: a preview of two rows, then the merge on confirmation."""
    if not model_admin.granted(request, "merge") and not request.user.is_superuser:
        raise PermissionDenied
    rows = list(queryset[:3])
    if len(rows) != 2:
        model_admin.message_user(
            request, _("Select exactly two rows to merge."), level=messages.WARNING
        )
        return None
    keep_pk = request.POST.get("keep")
    keep, drop = rows
    if keep_pk and str(drop.pk) == keep_pk:
        keep, drop = drop, keep
    plan = services.merge_plan(keep, drop)
    if request.POST.get("confirm") == "yes" and plan.allowed:
        try:
            services.merge(keep, drop)
        except services.MergeRefused as exc:
            model_admin.message_user(request, str(exc), level=messages.ERROR)
            return None
        model_admin.message_user(
            request,
            _("%(drop)s was merged into %(keep)s.") % {"drop": drop, "keep": keep},
            level=messages.SUCCESS,
        )
        return None
    context = {
        **model_admin.admin_site.each_context(request),
        "opts": model_admin.model._meta,
        "title": _("Merge two %(name)s") % {"name": model_admin.model._meta.verbose_name_plural},
        "plan": plan,
        "keep": keep,
        "drop": drop,
        "rows": rows,
        "action": "merge_selected",
        "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
    }
    return TemplateResponse(request, "karni_people/merge.html", context)


class _MergeAdmin(KarniModelAdmin):
    actions: ClassVar[list[str]] = ["merge_selected"]

    def has_merge_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_superuser) or self.granted(request, "merge")

    @admin.action(description="Merge the selected two", permissions=["merge"])
    def merge_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> Any:
        return merge_view(self, request, queryset)


class PersonAdmin(_MergeAdmin):
    """People with memberships and addresses inline, merge and erase."""

    list_display: ClassVar[list[str]] = ["display_name", "email", "phone", "organisation", "user"]
    search_fields: ClassVar[list[str]] = ["display_name", "email", "phone"]
    list_select_related: ClassVar[list[str]] = ["organisation", "user"]
    readonly_fields: ClassVar[list[str]] = ["user", "source", "merged_into", "erased_at"]
    actions: ClassVar[list[str]] = ["merge_selected", "erase_selected"]
    inlines: ClassVar[list[Any]] = _inlines("person")

    def has_erase_permission(self, request: HttpRequest) -> bool:
        return bool(request.user.is_superuser) or self.granted(request, "erase")

    @admin.action(description="Erase the selected people's data", permissions=["erase"])
    def erase_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> HttpResponse | None:
        if request.POST.get("confirm") != "yes":
            context = {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": _("Erase people's data"),
                "rows": list(queryset[:100]),
                "action": "erase_selected",
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            }
            return TemplateResponse(request, "karni_people/erase.html", context)
        count = 0
        for person in queryset:
            services.erase(person)
            count += 1
        self.message_user(
            request, _("Erased %(count)d people's data.") % {"count": count}, messages.SUCCESS
        )
        return None


class OrganisationAdmin(_MergeAdmin):
    """Organisations with memberships and addresses inline, and merge."""

    list_display: ClassVar[list[str]] = ["name", "domain", "phone"]
    search_fields: ClassVar[list[str]] = ["name", "domain"]
    readonly_fields: ClassVar[list[str]] = ["source", "merged_into"]
    inlines: ClassVar[list[Any]] = _inlines("organisation")


_site: admin.AdminSite = import_setting(
    "KARNI_ADMIN_SITE", getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site")
)
for _model, _admin in ((Person, PersonAdmin), (Organisation, OrganisationAdmin)):
    if not _site.is_registered(_model):
        _site.register(_model, _admin)
