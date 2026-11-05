"""The admin home page's *Getting started* panel, and the user menu entry that brings it back.

The panel sits above the app list on the admin index. It says what each
section is for (the one-line help of its models, see
:func:`karni.admin.derive.derive_help`), lists the first steps (add your first
record, invite a user, set roles) with links to the screens that do them, and
links to the documentation. A user closes it with *Dismiss*, which stores a
:class:`~karni.admin.models.GuideDismissal` row for that user, and brings it
back from the user menu (*Show the getting started guide*), which deletes the row.

:class:`KarniAdminConfig <karni.admin.apps.KarniAdminConfig>` calls
:func:`install` on the ``KARNI_ADMIN_SITE`` at startup. It gives the site
Karni's ``index_template`` (unless the site names one), adds the context to the
index, and serves ``<admin>/karni/guide/dismiss/`` and ``<admin>/karni/guide/show/``.

Override / escape hatch: ``KARNI_ADMIN_GUIDE = False`` removes the panel and the
menu entry. Replace ``karni_admin/includes/guide_panel.html`` to change the
panel, or the site's ``index_template`` to drop it with the rest of the page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import NoReverseMatch, path, reverse
from django.utils.translation import gettext as _

from karni.links import DOCS_BASE_URL

__all__ = ["account_links", "guide_context", "guide_enabled", "install"]

INDEX_TEMPLATE: Final = "karni_admin/index.html"
DISMISS_PATH: Final = "karni/guide/dismiss/"
SHOW_PATH: Final = "karni/guide/show/"
DISMISS_NAME: Final = "karni_guide_dismiss"
SHOW_NAME: Final = "karni_guide_show"
_INSTALLED: Final = "_karni_guide_installed"


def guide_enabled() -> bool:
    """Whether the panel exists at all (``KARNI_ADMIN_GUIDE``, default ``True``)."""
    return bool(getattr(settings, "KARNI_ADMIN_GUIDE", True))


def _dismissed(user: Any) -> bool:
    from karni.admin.models import GuideDismissal

    return bool(GuideDismissal.objects.filter(user_id=user.pk).exists())


def _admin_for(site: Any, model: type[Any]) -> Any:
    return site._registry.get(model)


def _sections(site: Any, request: HttpRequest) -> list[dict[str, Any]]:
    """Each app section of the index with its models and what they are for."""
    sections: list[dict[str, Any]] = []
    for app in site.get_app_list(request):
        entries = []
        for entry in app.get("models", ()):
            model = entry.get("model")
            model_admin = _admin_for(site, model) if model is not None else None
            help_text = ""
            if model_admin is not None and hasattr(model_admin, "model_help"):
                help_text = model_admin.model_help(request)
            entries.append(
                {"name": entry["name"], "url": entry.get("admin_url", ""), "help": help_text}
            )
        if entries:
            sections.append({"name": app["name"], "models": entries})
    return sections


def _url(site: Any, name: str, *args: Any) -> str | None:
    try:
        return reverse(f"{site.name}:{name}", args=args)
    except NoReverseMatch:
        return None


def _first_add_link(site: Any, request: HttpRequest) -> dict[str, str] | None:
    """The first model (in index order) the user may add rows to, as a link."""
    for app in site.get_app_list(request):
        for entry in app.get("models", ()):
            model = entry.get("model")
            model_admin = _admin_for(site, model) if model is not None else None
            if model_admin is None or not entry.get("add_url"):
                continue
            if model_admin.has_add_permission(request):
                return {"name": str(entry["name"]), "url": entry["add_url"]}
    return None


def _steps(site: Any, request: HttpRequest) -> list[dict[str, Any]]:
    """The first steps, each with a link when the user may take it."""
    from django.contrib.auth import get_user_model

    first = _first_add_link(site, request)
    steps: list[dict[str, Any]] = [
        {
            "title": _("Add your first record"),
            "text": (
                _("Open %(name)s and press Add.") % {"name": first["name"]}
                if first
                else _("Open a section from the list and press Add.")
            ),
            "url": first["url"] if first else "",
            "label": first["name"] if first else "",
        }
    ]
    users = get_user_model()
    user_admin = _admin_for(site, users)
    invite = (
        _url(site, f"{users._meta.app_label}_{users._meta.model_name}_add")
        if user_admin is not None and user_admin.has_add_permission(request)
        else None
    )
    steps.append(
        {
            "title": _("Invite a user"),
            "text": _("Add the person's email and tick Staff so they can sign in here."),
            "url": invite or "",
            "label": str(users._meta.verbose_name_plural).capitalize() if invite else "",
        }
    )
    roles = _url(site, "karni_accounts_role_changelist")
    steps.append(
        {
            "title": _("Set roles"),
            "text": _("Give each person a role, and set what each role may see and change."),
            "url": roles or "",
            "label": _("Roles") if roles else "",
        }
    )
    return steps


def guide_context(site: Any, request: HttpRequest) -> dict[str, Any] | None:
    """The panel's context for ``request``, or ``None`` when it is off or dismissed."""
    user = getattr(request, "user", None)
    if not guide_enabled() or user is None or not user.is_authenticated or _dismissed(user):
        return None
    return {
        "sections": _sections(site, request),
        "steps": _steps(site, request),
        "dismiss_url": reverse(f"{site.name}:{DISMISS_NAME}"),
        "docs": [
            {"title": _("The admin"), "url": f"{DOCS_BASE_URL}admin/"},
            {"title": _("Roles and permissions"), "url": f"{DOCS_BASE_URL}accounts/"},
            {"title": _("Import and export"), "url": f"{DOCS_BASE_URL}import-export/"},
        ],
    }


def account_links(request: HttpRequest) -> list[dict[str, str]]:
    """``UNFOLD["ACCOUNT"]["navigation"]``: the user menu's links.

    *Change password* (unfold's own link, which a navigation list replaces) and,
    while the panel is on, *Show the getting started guide*.
    """
    from karni.scoping import admin_site

    links: list[dict[str, str]] = []
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return links  # the login page asks too
    if user.has_usable_password():
        link = _url(admin_site(), "password_change")
        if link:
            links.append({"title": _("Change password"), "link": link})
    if guide_enabled():
        link = _url(admin_site(), SHOW_NAME)
        if link:
            links.append({"title": _("Show the getting started guide"), "link": link})
    return links


def install(site: Any) -> None:
    """Give ``site`` the panel: index template, context, and the two URLs. Idempotent.

    Call it before the URLconf reads ``site.urls`` (an ``AppConfig.ready``).
    """
    if getattr(site, _INSTALLED, False):
        return
    setattr(site, _INSTALLED, True)
    if getattr(site, "index_template", None) is None:
        site.index_template = INDEX_TEMPLATE
    index: Callable[..., HttpResponse] = site.index
    get_urls: Callable[[], list[Any]] = site.get_urls

    def index_with_guide(
        request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        extra = dict(extra_context or {})
        extra.setdefault("karni_guide", guide_context(site, request))
        return index(request, extra)

    def dismiss(request: HttpRequest) -> HttpResponse:
        from karni.admin.models import GuideDismissal

        if request.method == "POST":
            GuideDismissal.objects.get_or_create(user_id=request.user.pk)
        return HttpResponseRedirect(reverse(f"{site.name}:index"))

    def show(request: HttpRequest) -> HttpResponse:
        from karni.admin.models import GuideDismissal

        GuideDismissal.objects.filter(user_id=request.user.pk).delete()
        return HttpResponseRedirect(reverse(f"{site.name}:index"))

    def urls() -> list[Any]:
        if not guide_enabled():
            return get_urls()
        return [
            path(DISMISS_PATH, site.admin_view(dismiss), name=DISMISS_NAME),
            path(SHOW_PATH, site.admin_view(show), name=SHOW_NAME),
            *get_urls(),
        ]

    site.index = index_with_guide
    site.get_urls = urls
