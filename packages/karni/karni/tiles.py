"""Home tiles: what each role sees first, declared once, from any part.

A tile is one box on a home page: a number (``stat``), a short list
(``list``), a chart (``chart``) or a component of the app's own
(``custom``). ``GET /api/dashboard/`` answers the tiles the signed-in
person may see, in order, and @karni/ui's ``<DashboardTiles>`` draws them.
So a project with a shop and a booking app has one home that grows with
what is installed, and each role sees its own.

Tiles come from two places:

* **karni.yaml**, ``dashboard:``, which ``karni build`` writes to
  ``KARNI_DASHBOARD_TILES``. A tile there counts or lists the rows of a
  resource with filters, through that resource's own list endpoint (the
  browser asks it, so the row scope and the access rules apply unchanged)::

      dashboard:
        - {key: shop.to_send, title: Parcels to send, kind: stat, entity: Shipment,
           filters: {status: processing}, requires: "shop.shipment:change"}

* **code**, in ``<app>/dashboard.py`` (imported at startup), for a tile
  whose figures the server works out (revenue by day, the best sellers)::

      from karni.tiles import Tile, register

      @register
      def revenue(request):
          return Tile.stat_values([("Today", "120.00", "money")], currency="EUR")

  with the tile's facts on the decorator: ``register(key=..., title=...,
  kind=..., requires=...)``.

A setting entry with the key of a code tile places it: its ``title``,
``order``, ``size``, ``requires`` and ``roles`` win, and ``hidden: true``
takes it off the home.

Who sees a tile: ``requires`` (``authenticated``, ``*`` or a permission
pattern as in the roles' grants, read like the menu's,
:func:`karni.navigation.opens`) and, when set, ``roles`` (any of them).

Override / escape hatch: :func:`unregister` a tile, ``hidden: true`` in the
setting, or a home page of the app's own that composes ``Stat`` and
``ResourceTable``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Final

from django.conf import settings
from django.utils.module_loading import autodiscover_modules

from karni.exceptions import KarniImproperlyConfigured

__all__ = [
    "KINDS",
    "SIZES",
    "SETTING",
    "Tile",
    "autodiscover",
    "register",
    "tiles_for",
    "unregister",
]

#: The setting karni build writes karni.yaml's ``dashboard:`` to.
SETTING: Final = "KARNI_DASHBOARD_TILES"
KINDS: Final = ("stat", "list", "chart", "custom")
SIZES: Final = ("third", "half", "full")

Source = Callable[[Any], Mapping[str, Any] | None]


@dataclass(frozen=True)
class Tile:
    """One tile: who sees it, what kind, and where its figures come from.

    ``source`` (a code tile) returns the tile's data for a request, or
    ``None`` to leave the tile out for it. ``resource`` and ``filters`` (a
    setting tile) name a list endpoint the browser counts or lists.
    """

    key: str
    title: str
    kind: str = "stat"
    requires: str = "authenticated"
    roles: tuple[str, ...] = ()
    order: int = 0
    size: str = "third"
    description: str = ""
    link: str = ""
    resource: str = ""
    filters: Mapping[str, Any] = field(default_factory=dict)
    columns: tuple[str, ...] = ()
    limit: int = 5
    source: Source | None = None
    hidden: bool = False

    def __post_init__(self) -> None:
        if not self.key or not isinstance(self.key, str):
            raise _fail(f"a tile needs a key, got {self.key!r}")
        if self.kind not in KINDS:
            raise _fail(f"{self.key}: kind is {self.kind!r}, one of {', '.join(KINDS)}")
        if self.size not in SIZES:
            raise _fail(f"{self.key}: size is {self.size!r}, one of {', '.join(SIZES)}")

    def visible_to(self, user: Any) -> bool:
        """Whether ``user`` sees the tile: its requirement opens, and one of its roles."""
        from karni.navigation import opens

        if self.hidden or not opens(self.requires, user):
            return False
        if not self.roles:
            return True
        from karni.accounts.permissions import user_roles

        return bool(set(self.roles) & set(user_roles(user)))

    def payload(self, request: Any) -> dict[str, Any] | None:
        """The tile as ``GET /api/dashboard/`` answers it (``None``: left out for ``request``)."""
        data: Mapping[str, Any] | None = None
        if self.source is not None:
            data = self.source(request)
            if data is None:
                return None
        return {
            "key": self.key,
            "title": self.title,
            "kind": self.kind,
            "size": self.size,
            "order": self.order,
            "description": self.description,
            "link": self.link or None,
            "resource": self.resource or None,
            "filters": dict(self.filters),
            "columns": list(self.columns),
            "limit": self.limit,
            "data": _plain(data) if data is not None else None,
        }

    # -- helpers for a code tile's data -----------------------------------------------------

    @staticmethod
    def stat_values(
        values: Iterable[tuple[str, Any, str] | tuple[str, Any, str, str]],
        *,
        currency: str = "",
    ) -> dict[str, Any]:
        """A ``stat`` tile's data: ``(label, value, format[, link])`` rows.

        ``format`` is ``number`` or ``money`` (shown in ``currency``).
        """
        rows = []
        for value in values:
            label, amount, kind, *link = value
            rows.append(
                {
                    "label": label,
                    "value": _plain(amount),
                    "format": kind,
                    "link": link[0] if link else None,
                }
            )
        return {"values": rows, "currency": currency}


def _fail(problem: str) -> KarniImproperlyConfigured:
    return KarniImproperlyConfigured(f"Dashboard tile: {problem}.", code="E133")


def _plain(value: Any) -> Any:
    """``value`` with every Decimal as text with two places (money stays exact in JSON)."""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


_REGISTRY: dict[str, Tile] = {}


def register(
    source: Source | None = None,
    *,
    key: str = "",
    title: str = "",
    kind: str = "stat",
    requires: str = "authenticated",
    roles: Sequence[str] = (),
    order: int = 0,
    size: str = "third",
    description: str = "",
    link: str = "",
) -> Any:
    """Register a code tile, as ``@register`` or ``@register(key=..., ...)``.

    The key defaults to ``<module's app>.<function name>``, the title to the
    function's name in words. Registering a key again replaces the tile.
    """

    def wrap(function: Source) -> Source:
        app = function.__module__.split(".")[0]
        name = key or f"{app}.{function.__name__}"
        words = title or function.__name__.replace("_", " ").capitalize()
        _REGISTRY[name] = Tile(
            key=name,
            title=words,
            kind=kind,
            requires=requires,
            roles=tuple(roles),
            order=order,
            size=size,
            description=description,
            link=link,
            source=function,
        )
        return function

    return wrap(source) if source is not None else wrap


def unregister(key: str) -> None:
    """Take the code tile ``key`` out."""
    _REGISTRY.pop(key, None)


def autodiscover() -> None:
    """Import ``<app>/dashboard.py`` of every installed app (startup)."""
    autodiscover_modules("dashboard")


_FIELDS: Final = {
    "key",
    "title",
    "kind",
    "requires",
    "roles",
    "order",
    "size",
    "description",
    "link",
    "resource",
    "filters",
    "columns",
    "limit",
    "hidden",
}


def _from_setting(entry: Mapping[str, Any], known: Mapping[str, Tile]) -> Tile:
    unknown = sorted(set(entry) - _FIELDS)
    if unknown:
        raise _fail(f"{entry.get('key')!r} has unknown keys {', '.join(unknown)}")
    values = dict(entry)
    for name in ("roles", "columns"):
        if name in values:
            values[name] = tuple(values[name] or ())
    base = known.get(str(values.get("key", "")))
    if base is not None:
        return replace(base, **values)
    if not values.get("resource"):
        raise _fail(
            f"{values.get('key')!r} names no code tile, so it needs a resource (entity:) to count"
        )
    values.setdefault("title", str(values["key"]))
    return Tile(**values)


def all_tiles() -> list[Tile]:
    """Every tile: the code tiles, with the setting's entries over them."""
    found = dict(_REGISTRY)
    for entry in getattr(settings, SETTING, None) or []:
        tile = _from_setting(entry, found)
        found[tile.key] = tile
    return sorted(found.values(), key=lambda tile: (tile.order, tile.key))


def tiles_for(request: Any) -> list[dict[str, Any]]:
    """The tiles the person of ``request`` sees, in order, with their data."""
    user = getattr(request, "user", None)
    shown = []
    for tile in all_tiles():
        if not tile.visible_to(user):
            continue
        payload = tile.payload(request)
        if payload is not None:
            shown.append(payload)
    return shown
