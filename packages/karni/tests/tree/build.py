"""Tree builders for the tree model suite: a small region tree and a 10,000-node one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import models

from tests.testapp.models import Region


@dataclass
class Regions:
    """World > Europe > (France > Paris, Germany > Berlin), and Asia, a second root."""

    world: Region
    europe: Region
    france: Region
    paris: Region
    germany: Region
    berlin: Region
    asia: Region


def regions() -> Regions:
    world = Region.objects.create(name="World", code="world")
    europe = Region.objects.create(name="Europe", code="eu", parent=world)
    france = Region.objects.create(name="France", code="fr", parent=europe)
    paris = Region.objects.create(name="Paris", code="fr-par", parent=france)
    germany = Region.objects.create(name="Germany", code="de", parent=europe)
    berlin = Region.objects.create(name="Berlin", code="de-ber", parent=germany)
    asia = Region.objects.create(name="Asia", code="asia")
    return Regions(world, europe, france, paris, germany, berlin, asia)


#: Nodes per level of the large tree: 10 roots, then 9, 10 and 10 children each.
LEVELS = (10, 9, 10, 10)


def bulk_tree(model: type[models.Model] = Region, levels: tuple[int, ...] = LEVELS) -> list[Any]:
    """A tree of ``10 + 90 + 900 + 9000 = 10,000`` nodes, one ``bulk_create`` per level.

    Returns the rows level by level (the last level is the leaves).
    """
    made: list[list[Any]] = []
    parents: list[Any] = [None]
    for depth, fan_out in enumerate(levels):
        rows = [
            model(name=f"n{depth}-{index}-{number}", parent=parent)
            for index, parent in enumerate(parents)
            for number in range(fan_out)
        ]
        created = model._default_manager.bulk_create(rows, batch_size=2000)
        made.append(created)
        parents = created
    return made
