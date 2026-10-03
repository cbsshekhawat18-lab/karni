"""Seeders for the seeding suite: a pinned count with fixed names, and a custom seed()."""

from __future__ import annotations

from typing import Any

import factory

from karni.seeding import SeedContext, Seeder
from tests.perfapp.models import Publisher, Writer


class PublisherSeeder(Seeder):
    class Meta:
        model = Publisher
        count = 3

    name = factory.Iterator(["Penguin", "Faber", "Verso"])


class WriterSeeder(Seeder):
    class Meta:
        model = Writer

    def seed(self, context: SeedContext) -> list[Any]:
        rows = context.create(context.count - 1)
        return [*rows, *context.create(1, name="Pinned Writer")]
