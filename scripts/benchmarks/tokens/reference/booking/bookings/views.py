"""The test provider's payment confirmation."""

from django.shortcuts import get_object_or_404
from karni.accounts.permissions import has_role
from karni_payments.models import Payment
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class ConfirmPaymentView(APIView):
    """What the test provider calls when the customer has paid (a webhook, in production)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        if payment.user_id != request.user.pk and not has_role(request.user, "staff"):
            raise NotFound()
        if payment.status == Payment.Status.PENDING:
            payment.status = Payment.Status.SUCCEEDED
            payment.save(update_fields=["status", "updated_at"])
        return Response({"id": payment.pk, "status": payment.status})
