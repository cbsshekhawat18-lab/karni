"""The catalog's reports, found by the module at startup like a project's."""

from __future__ import annotations

from typing import Any

from karni_reports import Report, register
from tests.testapp.models import Category, Product


@register
class ProductSheet(Report):
    model = Product
    template = "products/product_sheet.html"

    def get_context(self, obj: Product) -> dict[str, Any]:
        return {"product": obj, "category": obj.category}


@register
class CategorySheet(Report):
    name = "category"
    model = Category
    template = "products/category_sheet.html"
