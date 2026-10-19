"""The admin: a read-only log of sessions, and the way in (an explicit registration).

``ImpersonationSessionAdmin`` lists every session (who, as whom, when, why,
how it ended) and carries the **Impersonate a user** button: an email and a
reason, then the impersonator is redirected to the site acting as the target
with the banner on every page. :func:`install_user_admin_button` adds the
same page as an **Impersonate** button on each user's change page when the
user admin is a django-unfold one.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib import admin, messages
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from karni.admin import KarniModelAdmin

from karni_impersonation import conf, services
from karni_impersonation.models import ImpersonationSession

__all__ = ["ImpersonationSessionAdmin", "install_user_admin_button"]


def _unfold_action() -> Any:
    try:
        from unfold.decorators import action
    except ImportError:  # pragma: no cover - unfold is a core dependency

        def action(**options: Any) -> Any:
            def decorate(fn: Any) -> Any:
                fn.url_path = options.get("url_path", fn.__name__)
                return fn

            return decorate

    return action


_action = _unfold_action()


def start_page(model_admin: Any, request: HttpRequest, target: Any = None) -> HttpResponse:
    """The start form; on POST, start the session and send the impersonator to the site."""
    allowed, why = (
        services.can_impersonate(request.user, target) if target is not None else (True, "")
    )
    if request.method == "POST":
        query = str(request.POST.get("user", "")).strip()
        chosen = target if target is not None else services.find_user(query)
        if chosen is None:
            messages.error(request, _("No user matches %(query)s.") % {"query": query})
        else:
            try:
                session = services.start(
                    request.user, chosen, str(request.POST.get("reason", "")), request
                )
            except services.ImpersonationError as exc:
                messages.error(request, str(exc))
            else:
                services.attach(request, session)
                messages.info(
                    request,
                    _("You are now acting as %(target)s.") % {"target": chosen.get_username()},
                )
                return HttpResponseRedirect(str(conf.get("KARNI_IMPERSONATION_LANDING") or "/"))
    context = {
        **model_admin.admin_site.each_context(request),
        "opts": ImpersonationSession._meta,
        "title": _("Impersonate a user"),
        "model_admin": model_admin,
        "target": target,
        "refusal": why if target is not None and not allowed else "",
        "require_reason": bool(conf.get("KARNI_IMPERSONATION_REQUIRE_REASON")),
        "max_minutes": int(conf.get("KARNI_IMPERSONATION_MAX_MINUTES") or 60),
    }
    return TemplateResponse(request, "karni_impersonation/start.html", context)


@admin.register(ImpersonationSession)
class ImpersonationSessionAdmin(KarniModelAdmin):
    """Read-only: the log is evidence."""

    list_display = ("actor", "target", "reason", "started_at", "ended_at", "end_reason", "batch_id")
    list_filter = ("end_reason", "actor", "target")
    search_fields = ("reason", "actor__email", "target__email")
    readonly_fields = (
        "actor",
        "target",
        "reason",
        "started_at",
        "expires_at",
        "ended_at",
        "end_reason",
        "ip",
        "user_agent",
        "batch_id",
    )
    fields = readonly_fields
    actions_list: Any = ["impersonate_user"]
    karni_transfer = False
    scope_exempt: ClassVar[bool] = True
    scope_exempt_reason: ClassVar[str] = "the session log is evidence; whoever may open it sees all"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    @_action(
        description=gettext_lazy("Impersonate a user"),
        url_path="start",
        permissions=["view"],
        icon="person_search",
    )
    def impersonate_user(self, request: HttpRequest) -> HttpResponse:
        return start_page(self, request)


def install_user_admin_button() -> None:
    """Add an **Impersonate** detail button to the registered user admin (unfold only)."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.utils.module_loading import import_string

    site = import_string(getattr(settings, "KARNI_ADMIN_SITE", "django.contrib.admin.site"))
    user_admin = site._registry.get(get_user_model())
    if user_admin is None or not hasattr(type(user_admin), "actions_detail"):
        return
    cls = type(user_admin)
    if "impersonate" in list(cls.actions_detail or ()):
        return

    @_action(
        description=gettext_lazy("Impersonate"),
        url_path="impersonate",
        permissions=["view"],
        icon="person_search",
    )
    def impersonate(self: Any, request: HttpRequest, object_id: str) -> HttpResponse:
        target = self.get_object(request, object_id)
        if target is None:
            raise Http404
        return start_page(self, request, target=target)

    cls.impersonate = impersonate
    cls.actions_detail = [*list(cls.actions_detail or ()), "impersonate"]
