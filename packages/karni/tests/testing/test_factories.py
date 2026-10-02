"""karni.testing.factories: generated factories for any model, explicit ones override."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test.utils import isolate_apps

from karni.testing import factories
from karni.testing.factories import (
    DEFAULT_PASSWORD,
    AutoFactory,
    FactoryBuilder,
    auto_factory,
    build,
    create,
    create_batch,
    explicit_factories,
    factory_for,
)
from tests.perfapp.factories import GenreFactory
from tests.perfapp.models import Chapter, Genre, Loop, Novel, Publisher, Specimen
from tests.testapp.models import Event

pytestmark = pytest.mark.django_db


def test_every_field_shape_gets_a_valid_value() -> None:
    specimen = create(Specimen)
    specimen.full_clean()  # choices, validators, email/url/slug/IP formats all hold
    assert specimen.pk is not None
    assert 1 <= specimen.rating <= 5
    assert specimen.size in (1, 2)
    assert len(specimen.label) <= 12
    assert "n" in specimen.payload and specimen.attachment.name
    assert specimen.note is None  # nullable and blank: left empty
    assert specimen.nickname  # nullable but required in forms: filled
    assert specimen.count == 7  # model defaults are left alone
    assert specimen.deleted_at is None and specimen.created_by is None  # non-editable


def test_unique_fields_hold_across_a_batch() -> None:
    batch = create_batch(Specimen, 5)
    assert len({specimen.label for specimen in batch}) == 5
    assert len({specimen.email for specimen in batch}) == 5
    # The O2O is a new Publisher each time; the nullable self-FK stops at the cycle.
    assert len({specimen.publisher_id for specimen in batch}) == 5
    assert all(specimen.parent is None for specimen in batch)


def test_foreign_keys_create_their_targets_through_factory_for() -> None:
    chapter = create(Chapter)
    assert chapter.novel.writer.publisher.pk is not None
    assert chapter.novel.status in {"draft", "out"}


def test_unique_constraints_over_foreign_keys_hold() -> None:
    chapters = create_batch(Chapter, 3, number=1)  # unique (novel, number)
    assert len({chapter.novel_id for chapter in chapters}) == 3


def test_overrides_and_nested_overrides() -> None:
    publisher = Publisher.objects.create(name="Mine")
    novel = create(Novel, title="Given", writer__publisher=publisher)
    assert novel.title == "Given" and novel.writer.publisher == publisher


def test_m2m_takes_rows_or_a_count() -> None:
    genres = [Genre.objects.create(name="a"), Genre.objects.create(name="b")]
    assert set(create(Novel, genres=genres).genres.all()) == set(genres)
    assert create(Novel, genres=3).genres.count() == 3
    assert create(Novel).genres.count() == 0


def test_build_saves_nothing() -> None:
    novel = build(Novel)
    assert novel._state.adding
    assert Novel.objects.count() == 0


def test_generated_users_can_log_in() -> None:
    user = create(get_user_model())
    assert user.check_password(DEFAULT_PASSWORD)
    assert user.is_active


def test_explicit_factory_overrides_the_generated_one() -> None:
    assert factory_for(Genre) is GenreFactory  # named <Model>Factory beats OtherGenreFactory
    assert explicit_factories()[Genre] is GenreFactory
    assert create(Genre).name.startswith("explicit-genre-")
    # Generated factories use it for related rows too.
    assert create(Novel, genres=1).genres.get().name.startswith("explicit-genre-")
    assert issubclass(auto_factory(Genre), AutoFactory)


def test_models_can_be_named_by_label() -> None:
    assert factory_for("testapp.Event") is factory_for(Event)
    assert isinstance(create("testapp.Event"), Event)


def test_a_required_cycle_names_the_fix() -> None:
    with pytest.raises(ImproperlyConfigured, match="Loop -> Loop.*Pass an existing row"):
        create(Loop)
    first = Loop(partner_id=None)
    first.partner = first  # an existing row breaks the cycle
    assert build(Loop, partner=first).partner is first


@isolate_apps("tests.perfapp")
def test_unsupported_required_fields_fail_when_used() -> None:
    class Point(models.Field):
        def db_type(self, connection: Any) -> str:
            return "text"

    class Odd(models.Model):
        where = Point()

        class Meta:
            app_label = "perfapp"

    odd = auto_factory(Odd, builder=FactoryBuilder())
    with pytest.raises(ImproperlyConfigured, match=r"Odd.where .*pass it"):
        odd.build()
    assert odd.build(where="here").where == "here"


def test_builder_methods_are_overridable() -> None:
    class Shouty(FactoryBuilder):
        def text_value(self, field: Any, stem: str) -> Any:
            return stem.upper()

    publisher = auto_factory(Publisher, builder=Shouty()).build()
    assert publisher.name == "NAME"


def test_clear_cache_rediscovers(monkeypatch: pytest.MonkeyPatch) -> None:
    first = auto_factory(Publisher)
    factories.clear_cache()
    assert auto_factory(Publisher) is not first


def test_abstract_and_non_models_are_rejected() -> None:
    from karni.models import BaseModel

    with pytest.raises(ImproperlyConfigured, match="abstract"):
        factory_for(BaseModel)
    with pytest.raises(TypeError):
        factory_for(object)
