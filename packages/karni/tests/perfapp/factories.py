"""Explicit factories: they override the generated ones (karni.testing.factories)."""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from tests.perfapp.models import Genre


class GenreFactory(DjangoModelFactory):
    """Named ``<Model>Factory``, so it wins over any other Genre factory here."""

    class Meta:
        model = Genre

    name = factory.Sequence(lambda n: f"explicit-genre-{n}")


class OtherGenreFactory(DjangoModelFactory):
    """A second Genre factory in the same module: never chosen over GenreFactory."""

    class Meta:
        model = Genre

    name = factory.Sequence(lambda n: f"other-genre-{n}")
