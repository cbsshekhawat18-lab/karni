"""Usage, cost and budgets: every provider call logged, and spending capped per month.

* :func:`log_call` writes one :class:`~karni_ai.models.AICall` per provider
  call, failed ones included, with the cost from :func:`cost_of`.
* :func:`cost_of` prices tokens from ``KARNI_AI_PRICES``: per million input
  and output tokens, by model name, in whatever currency the table is in. A
  model the table does not name has no cost (``None``), never a guessed one.
* :func:`check_budget` refuses a call before it is made when the user's
  tokens this calendar month reached ``KARNI_AI_MONTHLY_TOKENS_PER_USER``
  (AI013) or the project's reached ``KARNI_AI_MONTHLY_TOKENS`` (AI014). A
  call that starts under the budget finishes, so the last one may go past it.

The month is the calendar month in the project's ``TIME_ZONE``.

Override / escape hatch: :func:`spent` and :func:`month_start` are plain
functions; subclass :class:`karni_ai.extraction.Extractor` and override
``check_budget`` for another rule (per role, per resource).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db.models import F, Sum
from django.utils import timezone

from karni_ai import conf
from karni_ai.exceptions import ExtractionRefused
from karni_ai.models import AICall
from karni_ai.providers.base import Usage

__all__ = ["check_budget", "cost_of", "log_call", "month_start", "spent"]

_MILLION = Decimal(1_000_000)
_PLACES = Decimal("0.000001")


def _price(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def cost_of(model: str, usage: Usage) -> Decimal | None:
    """Experimental. What ``usage`` cost on ``model``, by ``KARNI_AI_PRICES`` (or ``None``)."""
    prices = conf.get("KARNI_AI_PRICES") or {}
    entry = prices.get(model) if isinstance(prices, dict) else None
    if not isinstance(entry, dict):
        return None
    input_price, output_price = _price(entry.get("input", 0)), _price(entry.get("output", 0))
    if input_price is None or output_price is None:
        return None
    total = (usage.input_tokens * input_price + usage.output_tokens * output_price) / _MILLION
    return total.quantize(_PLACES)


def month_start(now: datetime | None = None) -> datetime:
    """The start of the current calendar month in the project's time zone."""
    local = timezone.localtime(now or timezone.now())
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent(user: Any = None, *, since: datetime | None = None) -> int:
    """Tokens spent since ``since`` (this month): by ``user``, or by everyone when ``None``."""
    calls = AICall.objects.filter(created_at__gte=since or month_start())
    if user is not None:
        calls = calls.filter(user=user)
    total = calls.aggregate(total=Sum(F("input_tokens") + F("output_tokens")))["total"]
    return int(total or 0)


def _budget(name: str) -> int | None:
    value = conf.get(name)
    if value in (None, ""):
        return None
    return int(value)


def check_budget(user: Any) -> None:
    """Experimental. Refuse the next call when a monthly budget is spent (AI013, AI014)."""
    per_user = _budget("KARNI_AI_MONTHLY_TOKENS_PER_USER")
    if per_user is not None and getattr(user, "is_authenticated", False):
        used = spent(user)
        if used >= per_user:
            raise ExtractionRefused(
                f"You have used {used} of your {per_user} tokens this month "
                "(KARNI_AI_MONTHLY_TOKENS_PER_USER). It starts again next month.",
                code="AI013",
                status=429,
            )
    project = _budget("KARNI_AI_MONTHLY_TOKENS")
    if project is not None:
        used = spent()
        if used >= project:
            raise ExtractionRefused(
                f"The project has used {used} of its {project} tokens this month "
                "(KARNI_AI_MONTHLY_TOKENS). It starts again next month.",
                code="AI014",
                status=429,
            )


def log_call(
    *,
    user: Any,
    provider: str,
    model: str,
    resource: str,
    source: str,
    usage: Usage,
    error_code: str = "",
) -> AICall:
    """Experimental. Write one provider call to the usage log, with its cost."""
    owner = user if getattr(user, "is_authenticated", False) else None
    return AICall.objects.create(
        user=owner,
        provider=provider,
        model=model,
        resource=resource,
        source=source,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=cost_of(model, usage),
        status=AICall.Status.FAILED if error_code else AICall.Status.OK,
        error_code=error_code,
    )
