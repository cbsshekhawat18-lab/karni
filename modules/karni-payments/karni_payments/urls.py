"""URLs the payments module needs outside the auto-routed API: the webhook.

Wire it once in the project (the viewsets ride the auto-router and need no
URL wiring)::

    # config/urls.py
    path("payments/", include("karni_payments.urls")),

giving ``POST /payments/webhook/<provider>/`` (e.g.
``/payments/webhook/stripe/``) — the URL you register at the provider.
"""

from __future__ import annotations

from django.urls import path

from karni_payments.webhooks import webhook

app_name = "karni_payments"

urlpatterns = [
    path("webhook/<str:provider>/", webhook, name="webhook"),
]
