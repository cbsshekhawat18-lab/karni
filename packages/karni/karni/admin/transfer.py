"""Import and export in the admin (ADR 0002, P6): two actions and one page per model.

:class:`TransferAdminMixin` is part of every Karni admin: *Export selected
as CSV / XLSX* on the changelist (the selection, or every filtered row with
"select all", already narrowed by the row scope; columns the user may see)
and an **Import** button leading to the four-step page — upload, map,
preview, commit — that drives :mod:`karni.transfer.services` exactly as the
API does. A model with a routed viewset is gated and scoped by its
``access`` declaration; any other by the roles' grants.

Override / escape hatch: ``karni_transfer = False`` on an admin class
removes both; the page's template is ``karni_admin/import.html``.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from karni.exceptions import KarniValueError

__all__ = ["TransferAdminMixin"]


def _unfold_action() -> Any:
    """django-unfold's ``@action`` (a changelist button), or a stand-in that only names the path."""
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


class TransferAdminMixin(admin.ModelAdmin):
    """Export actions and the import page, for the model this admin serves."""

    karni_transfer: ClassVar[bool] = True
    """``False`` removes the export actions and the import page from this admin."""

    import_template: ClassVar[str] = "karni_admin/import.html"

    #: django-unfold's changelist buttons (ignored by a plain ``ModelAdmin``, which
    #: reaches the page at ``…/import/`` all the same).
    actions_list: Any = ["import_rows"]

    def __init__(self, model: Any, admin_site: Any) -> None:
        super().__init__(model, admin_site)
        if self.karni_transfer:
            current = list(getattr(self, "actions", None) or ())
            self.actions = [*current, "export_csv", "export_xlsx"]
        else:
            self.actions_list = [
                entry for entry in list(self.actions_list or ()) if entry != "import_rows"
            ]

    def get_actions(self, request: HttpRequest) -> Any:
        found = super().get_actions(request)
        if not self.karni_transfer:
            for name in ("export_csv", "export_xlsx"):
                found.pop(name, None)
        return found

    def get_actions_list(self, request: HttpRequest) -> Any:
        """Unfold's button list without *Import* for whoever may not import here."""
        parent = getattr(super(), "get_actions_list", None)
        found = list(parent(request)) if parent is not None else []
        if not self.karni_transfer or not self._may_import(request):
            opts = self.model._meta
            name = f"{opts.app_label}_{opts.model_name}_import_rows"
            found = [entry for entry in found if getattr(entry, "action_name", "") != name]
        return found

    @_action(description=gettext_lazy("Import"), url_path="import", icon="upload_file")
    def import_rows(self, request: HttpRequest) -> HttpResponse:
        """The import page, as an unfold changelist button."""
        return self.import_view(request)

    # export

    def _export(self, request: HttpRequest, queryset: QuerySet[Any], fmt: str) -> HttpResponse:
        """The selection as a file; related rows named only as far as the admin shows them."""
        from karni.admin.scope import related_rows_scope
        from karni.api.access import routed_view
        from karni.api.related import SCOPE_KEY
        from karni.api.serializers import build_serializer
        from karni.transfer.exports import export_response

        view = routed_view(self.model, request)
        serializer_class = (
            view.get_serializer_class() if view is not None else build_serializer(self.model)
        )
        context: dict[str, Any] = {
            "request": request,
            SCOPE_KEY: related_rows_scope(self, request),
        }
        if view is not None:
            context["view"] = view
        if not queryset.ordered:
            queryset = queryset.order_by("pk")
        try:
            return export_response(queryset, serializer_class, context, fmt=fmt)
        except KarniValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())

    @admin.action(description=gettext_lazy("Export selected as CSV"), permissions=["view"])
    def export_csv(self, request: HttpRequest, queryset: QuerySet[Any]) -> HttpResponse:
        return self._export(request, queryset, "csv")

    @admin.action(description=gettext_lazy("Export selected as XLSX"), permissions=["view"])
    def export_xlsx(self, request: HttpRequest, queryset: QuerySet[Any]) -> HttpResponse:
        return self._export(request, queryset, "xlsx")

    # import

    def get_urls(self) -> Any:
        urls = list(super().get_urls())
        if not self.karni_transfer:
            return urls
        opts = self.model._meta
        stem = f"{opts.app_label}_{opts.model_name}"
        wrap = self.admin_site.admin_view
        own = [
            path("import/", wrap(self.import_view), name=f"{stem}_import"),
            path(
                "import/template/", wrap(self.import_template_view), name=f"{stem}_import_template"
            ),
            path("import/<uuid:job>/", wrap(self.import_view), name=f"{stem}_import_job"),
            path(
                "import/<uuid:job>/state/",
                wrap(self.import_state_view),
                name=f"{stem}_import_state",
            ),
        ]
        return own + urls

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> Any:
        extra = dict(extra_context or {})
        if self.karni_transfer and self._may_import(request):
            opts = self.model._meta
            extra["karni_import_url"] = reverse(
                f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_import"
            )
        return super().changelist_view(request, extra)

    def _importer(self, request: HttpRequest) -> Any:
        from karni.transfer.imports import Importer

        return Importer(self.model, request)

    def _may_import(self, request: HttpRequest) -> bool:
        if not (self.has_add_permission(request) or self.has_change_permission(request)):
            return False
        vetoed = getattr(self, "vetoed", None)
        if vetoed is not None and vetoed(request, "import") is not None:
            return False
        importer = self._importer(request)
        return bool(importer.may_create() or importer.may_update())

    def _job(self, request: HttpRequest, job: Any) -> Any:
        from django.contrib.contenttypes.models import ContentType

        from karni.transfer.models import ImportJob

        found = (
            ImportJob.objects.filter(
                pk=job, content_type=ContentType.objects.get_for_model(self.model)
            )
            .select_related("content_type")
            .first()
        )
        if found is None:
            raise Http404
        if not request.user.is_superuser and found.created_by_id != request.user.pk:
            raise PermissionDenied
        return found

    def import_template_view(self, request: HttpRequest) -> HttpResponse:
        from karni.transfer.template import template_response

        if not self._may_import(request):
            raise PermissionDenied
        importer = self._importer(request)
        return template_response(self.model, importer.importable(), request.GET.get("format"))

    def import_state_view(self, request: HttpRequest, job: Any) -> HttpResponse:
        from karni.transfer.services import job_state

        return JsonResponse(job_state(self._job(request, job)))

    def import_view(self, request: HttpRequest, job: Any = None) -> HttpResponse:
        """Upload (no job), then map / preview / commit (with a job) — one template, by status."""
        from karni.transfer.services import (
            COMMIT,
            PREVIEW,
            create_job,
            job_state,
            set_mapping,
            start_stage,
        )

        if not self._may_import(request):
            raise PermissionDenied
        opts = self.model._meta
        stem = f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}"
        found = self._job(request, job) if job is not None else None
        importer = self._importer(request)

        if request.method == "POST":
            step = request.POST.get("step", "")
            try:
                if found is None:
                    upload = request.FILES.get("file")
                    if upload is None:
                        raise KarniValueError(_("Choose a file to upload."), code="E801")
                    found = create_job(self.model, request, upload)
                    return HttpResponseRedirect(reverse(f"{stem}_import_job", args=[found.pk]))
                if step == "map":
                    mapping = {
                        header: request.POST.get(f"map:{index}", "")
                        for index, header in enumerate(found.columns)
                    }
                    set_mapping(found, request, mapping)
                    start_stage(found, request, PREVIEW)
                elif step == "commit":
                    start_stage(found, request, COMMIT)
                elif step == "remap":
                    found.status = found.Status.UPLOADED
                    found.save(update_fields=["status", "updated_at"])
                else:
                    raise KarniValueError(_("Unknown step."), code="E801")
            except KarniValueError as exc:
                self.message_user(request, str(exc), messages.ERROR)
                if found is None:
                    return HttpResponseRedirect(reverse(f"{stem}_import"))
            else:
                if step == "commit" and found.status == found.Status.DONE and found.result:
                    self.message_user(
                        request,
                        _(
                            "Imported %(name)s: %(created)d created, %(updated)d updated, "
                            "%(skipped)d skipped."
                        )
                        % {"name": found.original_name, **found.result},
                        messages.SUCCESS,
                    )
            return HttpResponseRedirect(reverse(f"{stem}_import_job", args=[found.pk]))

        state = job_state(found) if found is not None else None
        columns = []
        if found is not None:
            specs = importer.importable()
            for index, header in enumerate(found.columns):
                columns.append(
                    {
                        "index": index,
                        "header": header,
                        "value": found.mapping.get(header, ""),
                        "options": [(spec.name, spec.label, spec.required) for spec in specs],
                    }
                )
        context = {
            **self.admin_site.each_context(request),
            "opts": opts,
            "title": _("Import %(name)s") % {"name": opts.verbose_name_plural},
            "model_admin": self,
            "job": found,
            "state": state,
            "columns": columns,
            "fields": importer.importable(),
            "key": importer.options.key,
            "template_url": reverse(f"{stem}_import_template"),
            "upload_url": reverse(f"{stem}_import"),
            "changelist_url": reverse(f"{stem}_changelist"),
            "state_url": reverse(f"{stem}_import_state", args=[found.pk])
            if found is not None
            else "",
        }
        return TemplateResponse(request, self.import_template, context)
