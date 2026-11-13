"""Experimental. ``dashboard:`` of ``karni.yaml``: the home tiles ``karni build`` writes.

Each entry becomes one dict of ``KARNI_DASHBOARD_TILES`` (:mod:`karni.tiles`
reads it): ``entity`` turns into the entity's API ``resource``
(``Shipment`` → ``shipments``), and a tile with an entity and no
``requires`` gets the entity's view permission (``shop.shipment:view``), so
a role sees a count only of rows it may read. A tile without an entity
places a tile an app declares in code (``commerce.revenue``).

:func:`tiles` gives the setting's list (``None`` without ``dashboard``),
:func:`summary` the line ``karni plan`` prints, and :func:`entries_from_setting`
the ``dashboard:`` entries of a project's setting (``karni spec export``).

Override / escape hatch: leave ``dashboard`` out and write
``KARNI_DASHBOARD_TILES`` below the spec block in the settings.
"""

from __future__ import annotations

from typing import Any, Final

from karni_cli.generators.naming import default_route
from karni_cli.spec import schema

__all__ = ["SETTING", "entries_from_setting", "summary", "tiles"]

#: The setting ``karni build`` writes the tiles to.
SETTING: Final = "KARNI_DASHBOARD_TILES"
_ORDER: Final = (
    "key",
    "title",
    "kind",
    "resource",
    "filters",
    "columns",
    "limit",
    "link",
    "requires",
    "roles",
    "order",
    "size",
    "description",
    "hidden",
)


def _entity(spec: schema.Spec, ref: str) -> tuple[str, str] | None:
    """``(app label, entity name)`` of ``ref`` (``Shipment`` or ``shop.Shipment``)."""
    if "." in ref:
        app, _, name = ref.partition(".")
        return app, name
    found = [app for app, block in spec.apps.items() if ref in block.entities]
    return (found[0], ref) if len(found) == 1 else None


def _tile(spec: schema.Spec, tile: schema.DashboardTile) -> dict[str, Any]:
    raw = tile.model_dump(exclude_none=True)
    entity = raw.pop("entity", None)
    if entity is not None:
        name = entity.rpartition(".")[2]
        raw["resource"] = default_route(name)
        found = _entity(spec, entity)
        if "requires" not in raw and found is not None:
            raw["requires"] = f"{found[0]}.{found[1].lower()}:view"
    return {key: raw[key] for key in _ORDER if key in raw}


def tiles(spec: schema.Spec) -> list[dict[str, Any]] | None:
    """Experimental. The ``KARNI_DASHBOARD_TILES`` value of ``spec``, or ``None`` without tiles."""
    if not spec.dashboard:
        return None
    return [_tile(spec, tile) for tile in spec.dashboard]


def summary(items: list[dict[str, Any]] | None) -> str:
    """Experimental. ``shop.to_send (shipments), commerce.revenue``."""
    return ", ".join(
        f"{item['key']} ({item['resource']})" if item.get("resource") else str(item["key"])
        for item in items or []
    )


def entries_from_setting(
    value: Any, spec: schema.Spec, left_out: list[str]
) -> list[dict[str, Any]] | None:
    """Experimental. The ``dashboard:`` entries a ``KARNI_DASHBOARD_TILES`` list writes.

    A ``resource`` becomes the entity whose route it is. A tile on a resource
    no entity of the spec has is added to ``left_out`` and skipped, and so is
    an entity's view permission the build would write anyway.
    """
    if not isinstance(value, list) or not value:
        return None
    by_route: dict[str, tuple[str, str]] = {}
    for app, block in spec.apps.items():
        for name in block.entities:
            by_route.setdefault(default_route(name), (app, name))
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or "key" not in item:
            continue
        entry = dict(item)
        resource = entry.pop("resource", None)
        if resource:
            found = by_route.get(str(resource))
            if found is None:
                left_out.append(
                    f"dashboard: {entry['key']}, on {resource}, a resource no entity has"
                )
                continue
            entry = {"key": entry.pop("key"), "entity": found[1], **entry}
            if entry.get("requires") == f"{found[0]}.{found[1].lower()}:view":
                entry.pop("requires")
        out.append(entry)
    return out or None
