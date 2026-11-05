"""Rate limits of the three endpoints, per caller, under scopes of their own.

=====================  ==========================================  ================
Scope                  Endpoint                                    Default
=====================  ==========================================  ================
``storage.download``   ``GET <resource>/<id>/files/<field>/``      ``1000/hour``
``storage.upload``     ``POST <resource>/files/<field>/upload/``   ``120/hour``
``storage.confirm``    ``POST <resource>/files/<field>/confirm/``  ``120/hour``
=====================  ==========================================  ================

:class:`StorageRateThrottle` is Karni's :class:`karni.api.throttling.ActionRateThrottle`
with these scopes: it counts per caller (the user id, else the client IP
honouring ``NUM_PROXIES``), keeps its history in the throttle cache and
answers 429 with ``Retry-After``. A signed download link (``?sig=``) counts
against the IP that opens it. The project-wide ``anon`` and ``user``
throttles still apply.

Override / escape hatch: ``KARNI_STORAGE_THROTTLE_RATES`` gives the module's
rates (``{"download": "1000/hour", "upload": ..., "confirm": ...}``). A rate
under the scope in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` wins over it,
the way Karni's viewset throttles work, and ``None`` in either turns that
limit off. Subclass the throttle and override a view's ``get_throttles()``
for another caller identity.
"""

from __future__ import annotations

from typing import Any, Final

from karni.api.throttling import ActionRateThrottle
from rest_framework.request import Request
from rest_framework.throttling import ScopedRateThrottle

from karni_storage import conf

__all__ = ["ACTIONS", "DEFAULT_RATES", "StorageRateThrottle", "rate_problems", "storage_rate"]

#: The endpoints that are limited, by the action name their scope carries.
ACTIONS: Final = ("download", "upload", "confirm")

#: The rates when ``KARNI_STORAGE_THROTTLE_RATES`` does not name one.
DEFAULT_RATES: Final[dict[str, str]] = {
    "download": "1000/hour",
    "upload": "120/hour",
    "confirm": "120/hour",
}

_UNSET: Final = object()


def scope(action: str) -> str:
    """``storage.<action>``: the throttle scope of one endpoint."""
    return f"storage.{action}"


def storage_rate(action: str) -> str | None:
    """Experimental. The rate limiting ``action``, or ``None`` when it is turned off.

    ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["storage.<action>"]`` first,
    then ``KARNI_STORAGE_THROTTLE_RATES[action]``, then :data:`DEFAULT_RATES`.
    """
    from rest_framework.settings import api_settings

    configured = api_settings.DEFAULT_THROTTLE_RATES or {}
    rate: Any = configured.get(scope(action), _UNSET)
    if rate is _UNSET:
        module = dict(conf.get("KARNI_STORAGE_THROTTLE_RATES") or {})
        rate = module.get(action, DEFAULT_RATES.get(action))
    return rate if isinstance(rate, str) and rate else None


def rate_problems() -> list[str]:
    """What is wrong with ``KARNI_STORAGE_THROTTLE_RATES``, as ``STORE005`` messages."""
    from karni.conf.validation import THROTTLE_RATE_RE

    from karni_storage.presets import SETTING_CODE

    raw = conf.get("KARNI_STORAGE_THROTTLE_RATES")
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return [
            f"{SETTING_CODE}: KARNI_STORAGE_THROTTLE_RATES must map download, upload or "
            'confirm to a rate such as "120/hour" (or None).'
        ]
    found = []
    for action, rate in raw.items():
        if action not in ACTIONS:
            found.append(
                f"{SETTING_CODE}: KARNI_STORAGE_THROTTLE_RATES names {action!r}. It takes "
                f"{', '.join(ACTIONS)}."
            )
        elif rate is not None and (not isinstance(rate, str) or not THROTTLE_RATE_RE.match(rate)):
            found.append(
                f"{SETTING_CODE}: KARNI_STORAGE_THROTTLE_RATES[{action!r}] is {rate!r}. Give a "
                'rate such as "120/hour", or None to turn the limit off.'
            )
    return found


class StorageRateThrottle(ActionRateThrottle):
    """Experimental. Karni's action throttle under the module's scopes (``storage.<action>``).

    The view names its endpoint in ``throttle_action``. Override / escape
    hatch: subclass it (``get_cache_key`` for another caller identity) and
    return it from the view's ``get_throttles()``.
    """

    def allow_request(self, request: Request, view: Any) -> bool:
        action = str(getattr(view, "throttle_action", "") or "")
        rate = storage_rate(action) if action else None
        if rate is None:
            return True
        self.scope = scope(action)
        self.rate = rate
        self.num_requests, self.duration = self.parse_rate(rate)
        return bool(super(ScopedRateThrottle, self).allow_request(request, view))
