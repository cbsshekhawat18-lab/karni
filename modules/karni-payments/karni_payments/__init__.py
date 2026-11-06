"""karni-payments — the Karni payments module (Stripe, Razorpay, test provider).

Checkout sessions, refunds and webhook-driven payment state, built on Karni's
bases: models on :class:`karni.models.BaseModel`, viewsets on
:class:`karni.api.BaseViewSet`, settings via the ``karni.settings`` fragment,
admin derived via ``AdminMeta``.

Project code talks to :mod:`karni_payments.services` — never to a provider
SDK directly.
"""

from __future__ import annotations

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("karni-payments")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"
