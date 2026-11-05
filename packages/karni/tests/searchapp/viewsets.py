"""The catalog's viewsets. ``auto_register = False``: :mod:`tests.searchapp.urls` routes them."""

from __future__ import annotations

from karni.api import Access, Authenticated, BaseViewSet, HasRole, Owned, Public
from tests.searchapp.models import Note, Product, Report, Supplier


class SupplierViewSet(BaseViewSet):
    model = Supplier
    auto_register = False
    access = Access(read=Authenticated(), write=HasRole("staff"))


class ProductViewSet(BaseViewSet):
    model = Product
    auto_register = False
    access = Access(read=Public(), write=HasRole("staff"))
    search_fields = ["name", "sku"]


class NoteViewSet(BaseViewSet):
    model = Note
    auto_register = False
    access = Access(read=Owned("created_by"), write=Owned("created_by"), create=Authenticated())


class ReportViewSet(BaseViewSet):
    model = Report
    auto_register = False
    access = Access(read=HasRole("staff"), write=HasRole("staff"))
