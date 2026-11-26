"""An order's invoice and packing slip, as printable pages and, with
karni-reports installed, as PDF.

``GET /api/orders/{id}/document/?kind=invoice`` (or ``packing_slip``) answers
the page as HTML, for staff and the order's own buyer: the app shows it and
prints it. One template each, ``karni_commerce/documents/invoice.html`` and
``packing_slip.html``, serves the page and the PDF, so the two never differ.

An invoice exists once the order is paid (``Invoice``, numbered then) and
prints the business's details as they were that day. A packing slip lists
what goes in the parcel and where it goes, with no prices.

When ``karni_reports`` is installed, the reports ``commerce-invoice`` and
``commerce-packing-slip`` print them to PDF in the background
(``POST /api/reports/commerce-invoice/<order id>/``), under the order's own
access.

Override / escape hatch: put a template of the same name in your project's
templates, or change :func:`context` by subclassing the reports.
"""

from __future__ import annotations

from typing import Any

from django.template.loader import render_to_string
from karni import preferences

from karni_commerce.models import Invoice, Order

__all__ = ["KINDS", "context", "render"]

#: The documents an order prints, by kind: the template and the title.
KINDS: dict[str, tuple[str, str]] = {
    "invoice": ("karni_commerce/documents/invoice.html", "Invoice"),
    "packing_slip": ("karni_commerce/documents/packing_slip.html", "Packing slip"),
}


def context(order: Order, kind: str = "invoice") -> dict[str, Any]:
    """What the document of ``kind`` shows for ``order``."""
    from karni_commerce.services import seller

    invoice = Invoice.objects.filter(order=order).first()
    lines = list(order.lines.order_by("position", "pk"))
    found = preferences.details()
    return {
        "kind": kind,
        "title": KINDS[kind][1],
        "order": order,
        "lines": lines,
        "shipped": [line for line in lines if line.needs_shipping] or lines,
        "invoice": invoice,
        "seller": invoice.seller if invoice is not None and invoice.seller else seller(),
        "business": found.name,
        "footer": preferences.value("commerce.invoice_footer", ""),
        "billing": order.billing or {},
        "shipping": order.shipping or order.billing or {},
    }


def render(order: Order, kind: str = "invoice") -> str:
    """The document of ``kind`` for ``order``, as an HTML page."""
    template, _title = KINDS[kind]
    return render_to_string(template, context(order, kind))


def register_pdf_reports() -> None:
    """With karni-reports installed, the invoice and the packing slip as PDF reports."""
    from karni_reports import Report, register

    @register
    class CommerceInvoice(Report):
        name = "commerce-invoice"
        title = "Invoice"
        model = Order
        template = KINDS["invoice"][0]

        def get_context(self, obj: Any) -> dict[str, Any]:
            return context(obj, "invoice")

        def get_filename(self, obj: Any) -> str:
            invoice = Invoice.objects.filter(order=obj).first()
            return f"{invoice.reference if invoice else obj.number}.pdf"

    @register
    class CommercePackingSlip(Report):
        name = "commerce-packing-slip"
        title = "Packing slip"
        model = Order
        template = KINDS["packing_slip"][0]

        def get_context(self, obj: Any) -> dict[str, Any]:
            return context(obj, "packing_slip")

        def get_filename(self, obj: Any) -> str:
            return f"packing-slip-{obj.number}.pdf"
