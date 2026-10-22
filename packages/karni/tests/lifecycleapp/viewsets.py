"""Viewsets for the lifecycle suite, mounted by ``tests.lifecycleapp.urls`` only.

``auto_register = False`` keeps them out of the main router (and of the
OpenAPI snapshot the UI parser tests share).
"""

from __future__ import annotations

from django.db import transaction
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from karni.api import Access, Authenticated, BaseViewSet
from karni.capacity import reserve
from tests.lifecycleapp.models import HAS_RANGES, Order, Slot, Stock

OPEN = Access(read=Authenticated(), write=Authenticated())


class OrderViewSet(BaseViewSet):
    model = Order
    access = OPEN
    auto_register = False

    @action(detail=True, methods=["post"])
    def confirm(self, request: Request, pk: str | None = None) -> Response:
        """A custom action: the transition's errors reach the client the same way."""
        order = self.get_object()
        order.transition("status", request.data.get("to", "confirmed"))
        return Response(self.get_serializer(order).data)


class StockViewSet(BaseViewSet):
    model = Stock
    access = OPEN
    auto_register = False

    @action(detail=True, methods=["post"])
    def buy(self, request: Request, pk: str | None = None) -> Response:
        """Take ``quantity`` units: the one supported way to consume capacity."""
        stock = self.get_object()
        with transaction.atomic():
            left = reserve(stock, int(request.data.get("quantity", 1)))
        return Response({"remaining": left})


class SlotViewSet(BaseViewSet):
    model = Slot
    access = OPEN
    auto_register = False


if HAS_RANGES:
    from tests.lifecycleapp.models import Reservation

    class ReservationViewSet(BaseViewSet):
        model = Reservation
        access = OPEN
        auto_register = False
