"""The approvals queue in the admin (an explicit registration, documented in the README).

``PendingChangeAdmin`` lists what the signed-in checker may decide (their
scope), shows each change's diff and decisions, and offers **Approve
selected** / **Reject selected** actions that ask for a reason on an
intermediate page and then call ``services.decide`` — so the maker-is-not-
the-checker rule and every other rule hold here exactly as in the API.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from karni.admin import KarniModelAdmin

from karni_approvals import services
from karni_approvals.models import Decision, PendingChange

__all__ = ["PendingChangeAdmin"]


class DecisionInline(admin.TabularInline):
    model = Decision
    extra = 0
    can_delete = False
    fields = ("checker", "verdict", "reason", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(PendingChange)
class PendingChangeAdmin(KarniModelAdmin):
    """The queue: pending first, in the checker's scope, decided through the two actions."""

    list_display = (
        "summary",
        "model_label",
        "action",
        "maker",
        "status",
        "progress",
        "created_at",
        "expires_at",
    )
    list_filter = ("status", "action", "content_type")
    search_fields = ("summary", "object_id")
    readonly_fields = (
        "content_type",
        "object_id",
        "action",
        "summary",
        "changes_display",
        "maker",
        "status",
        "required",
        "approvals",
        "expires_at",
        "escalated_at",
        "resolved_at",
        "resolved_by",
        "reason",
    )
    fields = readonly_fields
    inlines: ClassVar[list[type[admin.options.InlineModelAdmin]]] = [DecisionInline]
    actions = ("approve_selected", "reject_selected")
    karni_transfer = False
    decide_template: ClassVar[str] = "karni_approvals/decide.html"

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        queryset = super().get_queryset(request).select_related("content_type", "maker")
        return services.visible_to(request.user, queryset)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self.has_view_permission(request, obj)  # the form is read-only; actions decide

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    @admin.display(description=_("model"))
    def model_label(self, obj: PendingChange) -> str:
        return f"{obj.content_type.app_label}.{obj.content_type.model}"

    @admin.display(description=_("approvals"))
    def progress(self, obj: PendingChange) -> str:
        return f"{obj.approvals}/{obj.required}"

    @admin.display(description=_("changes"))
    def changes_display(self, obj: PendingChange) -> str:
        rows = format_html_join(
            "",
            "<tr><td><code>{}</code></td><td>{}</td><td>{}</td></tr>",
            (
                (
                    name,
                    change[0] if change[0] is not None else "—",
                    change[1] if change[1] is not None else "—",
                )
                for name, change in (obj.changes or {}).items()
            ),
        )
        if not rows:
            return "—"
        return format_html(
            "<table><tr><th>field</th><th>before</th><th>after</th></tr>{}</table>", rows
        )

    # the two actions

    def _decide_selected(
        self, request: HttpRequest, queryset: QuerySet[Any], verdict: str
    ) -> HttpResponse | None:
        if request.POST.get("post") == "yes":
            reason = request.POST.get("reason", "").strip()
            done, refused = 0, []
            for pending in queryset:
                try:
                    services.decide(pending, request.user, verdict, reason)
                    done += 1
                except services.ApprovalError as exc:
                    refused.append(f"{pending.summary}: {exc}")
            if done:
                self.message_user(
                    request,
                    _("%(verdict)s recorded for %(count)d change(s).")
                    % {"verdict": verdict.capitalize(), "count": done},
                    messages.SUCCESS,
                )
            for line in refused:
                self.message_user(request, line, messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Approve selected changes")
            if verdict == "approve"
            else _("Reject selected changes"),
            "verdict": verdict,
            "queryset": queryset,
            "action_name": f"{verdict}_selected",
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "media": self.media,
        }
        return TemplateResponse(request, self.decide_template, context)

    @admin.action(description=_("Approve selected pending changes"), permissions=["view"])
    def approve_selected(
        self, request: HttpRequest, queryset: QuerySet[Any]
    ) -> HttpResponse | None:
        return self._decide_selected(request, queryset, "approve")

    @admin.action(description=_("Reject selected pending changes"), permissions=["view"])
    def reject_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> HttpResponse | None:
        return self._decide_selected(request, queryset, "reject")
