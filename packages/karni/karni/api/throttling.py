"""Per-action rate limits for :class:`karni.api.viewsets.BaseViewSet`.

A form open to anonymous visitors needs a tighter limit than the project-wide
``anon`` throttle gives it. One declaration per viewset names the actions it
limits and the rate of each, in DRF's ``"<number>/<period>"`` format::

    class ContactViewSet(BaseViewSet):
        model = Contact
        access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())
        throttle = Throttle(create="10/hour")

``BaseViewSet.__init_subclass__`` adds :class:`ActionRateThrottle` to the
viewset's ``throttle_classes``, so the limit is an ordinary DRF throttle: it
counts per caller (the user id, or the client IP honouring ``NUM_PROXIES``),
keeps its history in the throttle cache, answers 429 with ``Retry-After``,
and goes away with the rest of ``throttle_classes`` (``assert_crud`` and the
``karni why`` probe switch throttling off that way). Actions the declaration
does not name keep only the project-wide ``anon`` and ``user`` throttles.

The scope of a limited action is ``"<route>.<action>"`` (``contacts.create``):
the viewset's router prefix, or its class name when it is not routed.
Settings win over the declaration: a rate under that scope in
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` replaces the declared one, and
``None`` there switches the limit off. The rate in force is published as
``x-karni-throttle`` on the operation in the OpenAPI schema.

Override / escape hatch: tune or disable a limit per scope in
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``. Set ``throttle_classes`` or
override ``get_throttles()`` as in plain DRF. For another caller identity,
subclass :class:`ActionRateThrottle` (``get_cache_key``) and name it in
``BaseViewSet.action_throttle_class``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from karni.conf.validation import THROTTLE_RATE_RE
from karni.exceptions import KarniImproperlyConfigured

__all__ = ["ActionRateThrottle", "Throttle", "throttle_rate", "throttle_scope"]


@dataclass(frozen=True, init=False, repr=False)
class Throttle:
    """``throttle = Throttle(create="10/hour")``: a rate per action.

    Each keyword names an action of the viewset (``create``, ``list``, or a
    custom ``@action`` by its method name) and gives its rate in DRF's
    ``"<number>/<period>"`` format. The viewset checks the action names at
    class definition (``E132``).
    """

    rates: Mapping[str, str]

    def __init__(self, **rates: str) -> None:
        if not rates:
            raise KarniImproperlyConfigured(
                "Throttle() names no action. Write Throttle(create='10/hour').", code="E132"
            )
        for action, rate in rates.items():
            if not isinstance(rate, str) or not THROTTLE_RATE_RE.match(rate):
                raise KarniImproperlyConfigured(
                    f"Throttle({action}={rate!r}) is not a rate. Write '<number>/<period>' with "
                    "the period s, sec, second, m, min, minute, h, hour, d or day, e.g. "
                    f"Throttle({action}='10/hour').",
                    code="E132",
                )
        object.__setattr__(self, "rates", MappingProxyType(dict(rates)))

    def rate_for(self, action: str) -> str | None:
        """The declared rate of ``action``, or ``None`` when the declaration does not name it."""
        return self.rates.get(action)

    def __repr__(self) -> str:
        inner = ", ".join(f"{action}={rate!r}" for action, rate in self.rates.items())
        return f"Throttle({inner})"


def _route_prefix(view_class: type[Any]) -> str | None:
    """The router prefix ``view_class`` is registered under, or ``None``."""
    from karni.api.routers import resolve_router

    try:
        router = resolve_router()
    except Exception:  # noqa: BLE001 - a broken router is karni.E128's to report
        return None
    for prefix, registered, _basename in getattr(router, "registry", ()):
        if registered is view_class:
            return str(prefix)
    return None


def throttle_scope(view: Any, action: str | None = None) -> str:
    """``"<route>.<action>"``: the router prefix (the class name when unrouted) and the action."""
    view_class = view if isinstance(view, type) else type(view)
    name = action if action is not None else getattr(view, "action", None) or ""
    return f"{_route_prefix(view_class) or view_class.__name__}.{name}"


def throttle_rate(view: Any, action: str | None = None) -> str | None:
    """The rate limiting ``action`` on ``view``, or ``None`` when nothing limits it.

    Settings first: the scope's entry in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``
    (``None`` there disables the limit), else the viewset's declaration.
    """
    declaration = getattr(view, "throttle", None)
    if not isinstance(declaration, Throttle):
        return None
    name = action if action is not None else getattr(view, "action", None)
    if not name:
        return None
    declared = declaration.rate_for(name)
    if declared is None:
        return None
    configured = ActionRateThrottle.THROTTLE_RATES
    scope = throttle_scope(view, name)
    if scope in configured:
        rate = configured[scope]
        return rate if isinstance(rate, str) else None
    return declared


class ActionRateThrottle(ScopedRateThrottle):
    """The DRF throttle behind :class:`Throttle`.

    Per caller like DRF's ``ScopedRateThrottle`` (user id, else client IP),
    under the scope :func:`throttle_scope` gives the current action, at the
    rate :func:`throttle_rate` resolves. An action without a rate passes.
    """

    def allow_request(self, request: Request, view: APIView) -> bool:
        action = getattr(view, "action", None)
        rate = throttle_rate(view, action)
        if rate is None:
            return True
        self.scope = throttle_scope(view, action)
        self.rate = rate
        self.num_requests, self.duration = self.parse_rate(rate)
        return super(ScopedRateThrottle, self).allow_request(request, view)
