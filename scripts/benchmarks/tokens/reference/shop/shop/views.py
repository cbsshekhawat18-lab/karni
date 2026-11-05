"""The customer's cart and checkout, and the test provider's payment confirmation."""

from django.db import transaction
from django.shortcuts import get_object_or_404
from karni.accounts.permissions import has_role
from karni_payments.models import Payment
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from shop.models import Cart, CartItem, Product
from shop.serializers import OrderSerializer
from shop.viewsets import open_payment


def cart_body(cart: Cart) -> dict:
    items = [
        {
            "id": item.pk,
            "product": item.product_id,
            "quantity": item.quantity,
            "line_total": item.line_total(),
        }
        for item in cart.cartitem_set.select_related("product").order_by("created_at")
    ]
    return {"items": items, "total": cart.total()}


class CartView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(cart_body(Cart.of(request.user)))


class CartItemsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            quantity = int(request.data.get("quantity", 0))
        except (TypeError, ValueError):
            quantity = 0
        if quantity < 1:
            raise ValidationError({"quantity": ["Must be at least 1."]})
        product = Product.objects.filter(pk=request.data.get("product")).first()
        if product is None:
            raise ValidationError({"product": ["Unknown product."]})
        cart = Cart.of(request.user)
        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, defaults={"quantity": quantity}
        )
        if not created:
            item.quantity += quantity
            item.save(update_fields=["quantity", "updated_at"])
        body = {"id": item.pk, "product": product.pk, "quantity": item.quantity}
        return Response(body, status=201)


class CartItemView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        item = CartItem.objects.filter(pk=pk, cart__customer=request.user).first()
        if item is None:
            raise NotFound()
        item.delete()
        return Response(status=204)


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        order = Cart.of(request.user).checkout()
        open_payment(request, order)
        return Response(OrderSerializer(order).data, status=201)


class ConfirmPaymentView(APIView):
    """What the test provider calls when the customer has paid (a webhook, in production)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        if payment.user_id != request.user.pk and not has_role(request.user, "staff"):
            raise PermissionDenied() if payment.user_id else NotFound()
        if payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.SUCCEEDED
            payment.save(update_fields=["status", "updated_at"])
        return Response({"id": payment.pk, "status": payment.status})
