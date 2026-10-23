"""Per-action rate limits for :class:`karni.api.viewsets.BaseViewSet`.

A form open to anonymous visitors needs a tighter limit than the project-wide
``anon`` throttle gives it. One declaration per viewset names the actions it
limits and the rate of each, in DRF's ``"<number>/<period>"`` format::

    class ContactViewSet(BaseViewSet):
        model = Contact
        access = Access(read=HasRole("staff"), write=HasRole("staff"), create=Public())
        throttle = Throttle(create="10/hour")

Public creates are limited without a declaration. When a viewset's
``create`` predicate lets anonymous callers in (``create=Public()``, or a
``write=Public()`` that ``create`` defaults to), its ``create`` action is
limited at ``KARNI_PUBLIC_CREATE_RATE`` (default ``"10/hour"``). A
declaration that names ``create`` replaces that default, and
``Throttle(create=None)`` turns it off for one viewset.

``BaseViewSet.__init_subclass__`` adds :class:`ActionRateThrottle` to the
viewset's ``throttle_classes``, so the limit is an ordinary DRF throttle: it
counts per caller (the user id, or the client IP honouring ``NUM_PROXIES``),
keeps its history in the throttle cache, answers 429 with ``Retry-After``,
and goes away with the rest of ``throttle_classes`` (``assert_crud`` and the
``karni why`` probe switch throttling off that way). Actions without a rate
keep only the project-wide ``anon`` and ``user`` throttles.

The scope of a limited action is ``"<route>.<action>"`` (``contacts.create``):
the viewset's router prefix, or its class name when it is not routed.
Settings win over the declaration and the public-create default: a rate
under that scope in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` replaces
the rate, and ``None`` there switches the limit off. The rate in force is
published as ``x-karni-throttle`` on the operation in the OpenAPI schema.

Override / escape hatch: tune or disable a limit per scope in
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``, or every public-create default
at once with ``KARNI_PUBLIC_CREATE_RATE`` (``None`` turns it off). Set
``throttle_classes`` or override ``get_throttles()`` as in plain DRF. For
another caller identity, subclass :class:`ActionRateThrottle`
(``get_cache_key``) and name it in ``BaseViewSet.action_throttle_class``.
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

__all__ = [
    "DEFAULT_PUBLIC_CREATE_RATE",
    "ActionRateThrottle",
    "Throttle",
    "is_public_create",
    "public_create_rate",
    "throttle_rate",
    "throttle_scope",
]

#: ``KARNI_PUBLIC_CREATE_RATE`` when the setting is absent.
DEFAULT_PUBLIC_CREATE_RATE = "10/hour"


@dataclass(frozen=True, init=False, repr=False)
class Throttle:
    """``throttle = Throttle(create="10/hour")``: a rate per action.

    Each keyword names an action of the viewset (``create``, ``list``, or a
    custom ``@action`` by its method name) and gives its rate in DRF's
    ``"<number>/<period>"`` format. ``None`` declares no limit for that
    action, which turns off the default a public ``create`` gets
    (``KARNI_PUBLIC_CREATE_RATE``). The viewset checks the action names at
    class definition (``E132``).
    """

    rates: Mapping[str, str | None]

    def __init__(self, **rates: str | None) -> None:
        if not rates:
            raise KarniImproperlyConfigured(
                "Throttle() names no action. Write Throttle(create='10/hour').", code="E132"
            )
        for action, rate in rates.items():
            if rate is None:
                continue
            if not isinstance(rate, str) or not THROTTLE_RATE_RE.match(rate):
                raise KarniImproperlyConfigured(
                    f"Throttle({action}={rate!r}) is not a rate. Write '<number>/<period>' with "
                    "the period s, sec, second, m, min, minute, h, hour, d or day, e.g. "
                    f"Throttle({action}='10/hour'), or None for no limit.",
                    code="E132",
                )
        object.__setattr__(self, "rates", MappingProxyType(dict(rates)))

    def declares(self, action: str) -> bool:
        """Whether the declaration names ``action`` (with a rate or with ``None``)."""
        return action in self.rates

    def rate_for(self, action: str) -> str | None:
        """The declared rate of ``action``: ``None`` when it is not named or declared ``None``."""
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


def public_create_rate() -> str | None:
    """``KARNI_PUBLIC_CREATE_RATE``: the default limit of a public ``create`` (``None``: none)."""
    from django.conf import settings

    rate = getattr(settings, "KARNI_PUBLIC_CREATE_RATE", DEFAULT_PUBLIC_CREATE_RATE)
    return rate if isinstance(rate, str) and rate else None


def _access_of(view: Any) -> Any:
    """The view's ``access``: ``get_access()`` on an instance, the attribute on a class."""
    if isinstance(view, type):
        from karni.api.access import Access, Granted

        declared = getattr(view, "access", None)
        return Access(read=declared, write=declared) if isinstance(declared, Granted) else declared
    get_access = getattr(view, "get_access", None)
    return get_access() if callable(get_access) else getattr(view, "access", None)


def is_public_create(view: Any) -> bool:
    """Whether ``view``'s ``create`` lets anonymous callers in (``create=Public()`` and the like).

    Only an :class:`~karni.api.access.Access` declaration is read, through
    ``get_access()``, so a per-request declaration counts. A gate built from
    ``Where`` is not public here (:func:`karni.api.access.admits_anyone`).
    """
    from karni.api.access import Access, admits_anyone

    declaration = _access_of(view)
    return isinstance(declaration, Access) and admits_anyone(declaration.create)


def _default_rate(view: Any, action: str) -> tuple[bool, str | None]:
    """``(limited, rate)`` before settings: the declaration, else the public-create default."""
    declaration = getattr(view, "throttle", None)
    if isinstance(declaration, Throttle) and declaration.declares(action):
        return True, declaration.rate_for(action)
    if action == "create" and is_public_create(view):
        return True, public_create_rate()
    return False, None


def throttle_rate(view: Any, action: str | None = None) -> str | None:
    """The rate limiting ``action`` on ``view``, or ``None`` when nothing limits it.

    Settings first: the scope's entry in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``
    (``None`` there disables the limit). Then the viewset's declaration, and
    for a public ``create`` without one, ``KARNI_PUBLIC_CREATE_RATE``. An
    action with neither is not limited, whatever the settings name.
    """
    name = action if action is not None else getattr(view, "action", None)
    if not name:
        return None
    limited, rate = _default_rate(view, name)
    if not limited:
        return None
    configured = ActionRateThrottle.THROTTLE_RATES
    scope = throttle_scope(view, name)
    if scope in configured:
        setting = configured[scope]
        return setting if isinstance(setting, str) else None
    return rate


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
