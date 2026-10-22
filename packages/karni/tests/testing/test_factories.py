"""karni.testing.factories: generated factories for any model, explicit ones override."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone
from factory.random import reseed_random

from karni.testing import factories
from karni.testing.factories import (
    DEFAULT_PASSWORD,
    AutoFactory,
    FactoryBuilder,
    ModelFactory,
    auto_factory,
    build,
    create,
    create_batch,
    explicit_factories,
    factory_for,
    hashed_password,
)
from karni.testing.values import NAME_RULES, SAFE_DOMAINS, NameRule, ValueContext, ValueInference
from tests.perfapp.factories import GenreFactory
from tests.perfapp.models import Chapter, Genre, Loop, Novel, Publisher, Specimen, Writer
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
    with pytest.raises(ImproperlyConfigured, match=r"Odd.where .*Pass it"):
        odd.build()
    assert odd.build(where="here").where == "here"


def test_value_rules_are_overridable() -> None:
    class Shouty(ValueInference):
        rules = (
            NameRule("loud name", ("name",), (models.CharField,), lambda ctx: "NAME"),
            *NAME_RULES,
        )

        def text(self, ctx: ValueContext) -> str:
            return "TEXT"

    builder = FactoryBuilder(values=Shouty())
    assert auto_factory(Publisher, builder=builder).build().name == "NAME"
    assert auto_factory(Chapter, builder=builder).build().title != "TEXT"  # a name rule
    assert auto_factory(Specimen, builder=builder).build().label == "TEXT"[:12]


def test_a_phase_12a_value_hook_override_still_applies() -> None:
    class Shouty(FactoryBuilder):
        def text_value(self, field: Any, stem: str) -> Any:
            return stem.upper()

    publisher = auto_factory(Publisher, builder=Shouty()).build()
    assert publisher.name == "NAME"  # the override beats the name rule, as before


def test_values_follow_field_names() -> None:
    user = create(get_user_model())
    local, _, domain = user.email.partition("@")
    assert domain in SAFE_DOMAINS
    assert local.startswith(f"{user.first_name}.{user.last_name}".lower().replace("'", ""))
    event = create(Event)
    assert event.starts_at > timezone.now()  # starts_at: near future
    assert event.title and not event.title.startswith("title-")
    specimen = create(Specimen)
    assert Decimal("5") <= specimen.price <= Decimal("500")  # price: money
    assert specimen.price == specimen.price.quantize(Decimal("0.01"))


def test_unique_constraint_fields_embed_the_sequence() -> None:
    chapters = create_batch(Chapter, 4, novel=create(Novel))  # unique (novel, number)
    assert len({chapter.number for chapter in chapters}) == 4


def test_fill_optional_fills_nullable_blank_fields() -> None:
    class Filling(FactoryBuilder):
        fill_optional = 1.0

    assert auto_factory(Specimen, builder=Filling()).build().note
    assert auto_factory(Specimen).build().note is None


def test_generated_users_share_one_hash_per_password() -> None:
    first, second = create_batch(get_user_model(), 2)
    assert first.password == second.password == hashed_password(DEFAULT_PASSWORD)
    assert create(get_user_model(), password="other-pass").check_password("other-pass")


def test_reseeding_reproduces_the_values() -> None:
    reseed_random(7)
    first = build(Specimen)
    reseed_random(7)
    second = build(Specimen)
    assert (first.body, first.price, first.moment) == (second.body, second.price, second.moment)


def test_model_factory_declares_only_what_differs() -> None:
    from tests.perfapp.factories import PublisherFactory

    assert factory_for(Publisher) is PublisherFactory
    publisher = create(Publisher)
    assert publisher.name == "Acme Books"  # declared
    writer = create(Writer)  # the generated Writer factory uses the explicit one
    assert writer.publisher.name == "Acme Books"
    assert {"name"} <= set(PublisherFactory._meta.declarations)

    class NovelFactory(ModelFactory):
        class Meta:
            model = "perfapp.Novel"

        status = "out"

    novel = NovelFactory.create()
    assert novel.status == "out" and novel.title and novel.writer.pk  # the rest generated


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


@pytest.mark.django_db
def test_a_many_to_many_accepts_one_row() -> None:
    """``create(Event, tags=tag)``: what an owner path through a many-to-many passes down."""
    from karni.testing.factories import create
    from tests.testapp.models import Event, Tag

    tag = create(Tag)
    event = create(Event, tags=tag)
    assert list(event.tags.all()) == [tag]
