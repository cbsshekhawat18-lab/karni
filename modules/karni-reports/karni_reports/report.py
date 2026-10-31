"""The report declaration: a model, a template and a ``get_context(obj)`` hook.

A project declares its reports in ``<app>/reports.py``, which the module
imports at startup::

    from karni_reports import Report, register

    from catalog.models import Product


    @register
    class ProductSheet(Report):
        model = Product
        template = "catalog/product_sheet.html"

        def get_context(self, obj: Product) -> dict[str, object]:
            return {"product": obj, "prices": obj.prices.order_by("region")}

The file is shared by everyone who may see the row, so ``get_context`` gets
the row and nothing about who asks.

Override / escape hatch: every ``get_*`` method below is the place to
change one thing for one report: the file name, the context, the template,
the renderer, the versions, the rows pre-generation covers, the viewset that
decides access.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.db.models import Model, QuerySet
from django.template.loader import render_to_string
from django.utils.module_loading import import_string
from karni.exceptions import KarniImproperlyConfigured

from karni_reports import conf, versions
from karni_reports.rendering import Renderer, get_renderer

__all__ = ["Report"]


class Report:
    """Experimental. A PDF the rows of one model print as, rendered from one template.

    Class attributes:

    * ``model``: the model whose rows the report prints (required).
    * ``template``: the template name (required). It usually extends
      ``karni_reports/base.html``, the base print template with the page size,
      the margins and the ``header``, ``content`` and ``footer`` blocks.
    * ``name``: the report's address in the API (``/api/reports/<name>/<id>/``),
      lowercase letters, digits, ``-`` and ``_``. Default: the class name in
      kebab case (``ProductSheet`` is ``product-sheet``).
    * ``title``: the human name the admin and the UI show. Default: the class
      name with spaces.
    * ``viewset``: the viewset whose ``retrieve`` decides who may see a row's
      report, a class or a dotted path. Default: the viewset routed for
      ``model``.
    """

    name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    model: ClassVar[type[Model] | None] = None
    template: ClassVar[str] = ""
    viewset: ClassVar[type[Any] | str | None] = None

    # what is printed

    def get_context(self, obj: Any) -> dict[str, Any]:
        """The template's context for ``obj``, and what the data version hashes.

        Put everything the template prints from other rows in it (a related
        row, a list of children), so a change to them changes the data version.
        The default is ``{"object": obj}``.
        """
        return {"object": obj}

    def get_template_name(self) -> str:
        """The template to render: ``template`` by default."""
        return self.template

    def get_render_options(self) -> dict[str, Any]:
        """What the template gets besides the context, and the template version counts too.

        The default is the page size (``KARNI_REPORTS_PAGE_SIZE``) and the
        renderer's identity.
        """
        return {
            "page_size": str(conf.get("KARNI_REPORTS_PAGE_SIZE")),
            "renderer": self.get_renderer().identity(),
        }

    def render_html(self, obj: Any, context: dict[str, Any]) -> str:
        """The HTML of the report: the template rendered with ``report``, ``object``,
        ``page_size`` and the context (whose keys win)."""
        options = self.get_render_options()
        return render_to_string(
            self.get_template_name(),
            {"report": self, "object": obj, "page_size": options["page_size"], **context},
        )

    def get_renderer(self) -> Renderer:
        """The renderer: the one ``KARNI_REPORTS_RENDERER`` names by default."""
        return get_renderer()

    def get_filename(self, obj: Any) -> str:
        """The download's file name: ``<name>-<pk>.pdf`` by default."""
        return f"{self.name}-{obj.pk}.pdf"

    # the cache key

    def get_template_version(self) -> str:
        """A hash of the template's sources and the render options."""
        return versions.template_version(self.get_template_name(), self.get_render_options())

    def get_data_version(self, obj: Any, context: dict[str, Any]) -> str:
        """A hash of ``context`` (:func:`karni_reports.versions.data_version`)."""
        return versions.data_version(context)

    # rows and access

    def get_queryset(self) -> QuerySet[Any]:
        """The rows the report prints: what renders look rows up in and pre-generation covers."""
        model = self.get_model()
        queryset: QuerySet[Any] = model._default_manager.all()
        return queryset

    def get_model(self) -> type[Model]:
        if self.model is None:
            raise KarniImproperlyConfigured(
                f"{type(self).__name__} names no model. Set `model` on the report.",
                code="REPORT002",
            )
        return self.model

    def get_viewset(self) -> type[Any]:
        """The viewset whose ``retrieve`` decides who may see a row (``REPORT004`` when none)."""
        declared = self.viewset
        if isinstance(declared, str):
            found: Any = import_string(declared)
            return found
        if declared is not None:
            return declared
        from karni.api.routers import viewset_for_model

        model = self.get_model()
        routed = viewset_for_model(model)
        if routed is None:
            raise KarniImproperlyConfigured(
                f"Report {self.name!r}: no viewset serves {model._meta.label}, so who may see "
                "a row's report cannot be checked. Add a BaseViewSet for the model, or set "
                "`viewset` on the report.",
                code="REPORT004",
            )
        return routed

    def get_object(self, request: Any, object_id: str) -> Any:
        """The row ``object_id`` as ``request`` may retrieve it through :meth:`get_viewset`.

        The viewset's own gate and read scope decide: 401 or 403 when its
        ``retrieve`` refuses the caller, 404 for a row out of their scope.
        """
        from karni_reports.access import retrieve

        return retrieve(self.get_viewset(), request, object_id)

    def __repr__(self) -> str:
        return f"<Report {self.name!r} of {getattr(self.model, '__name__', None)}>"
