"""Viewsets for the rules suite, mounted by ``tests.rulesapp.urls`` only."""

from __future__ import annotations

from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import (
    Access,
    Authenticated,
    BaseViewSet,
    HasRole,
    Matching,
    Owned,
    Public,
    RowAction,
    Where,
)
from tests.rulesapp.models import Item, Lesson, Purchase, Shop

STAFF = HasRole("staff")


class ShopViewSet(BaseViewSet):
    model = Shop
    access = Access(
        read=Public(), write=Owned("owner") | STAFF, create=Authenticated(), assign=STAFF
    )
    auto_register = False


class ItemViewSet(BaseViewSet):
    model = Item
    access = Access(
        read=Where(Matching(active=True)) | Owned("shop__owner") | STAFF,
        write=Owned("shop__owner") | STAFF,
    )
    auto_register = False


class PurchaseViewSet(BaseViewSet):
    model = Purchase
    access = Access(
        read=Owned("buyer") | Owned("item__shop__owner") | STAFF,
        write=Owned("buyer") | STAFF,
        delete=STAFF,
        assign=STAFF,
    )
    auto_register = False
    row_actions = {
        "pay": RowAction(from_="pending", by=Owned("buyer")),
        "cancel": RowAction(from_="pending", to="cancelled", by=Owned("buyer") | STAFF),
        "refund": RowAction(from_="paid", to="refunded", by=STAFF),
    }

    @action(detail=True, methods=["post"])
    def pay(self, request: Request, pk: str | None = None) -> Response:
        """The project's own step (here: mark it paid at once)."""
        purchase = self.get_object()
        purchase.transition("status", "paid")
        return Response(self.get_serializer(purchase).data)


class LessonViewSet(BaseViewSet):
    model = Lesson
    access = Access(
        read=Owned("course__enrolment__student") | STAFF,
        write=STAFF,
    )
    auto_register = False
