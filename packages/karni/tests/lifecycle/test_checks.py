"""System checks: W980 (no_overlap unenforced off PostgreSQL); E986/E987/E988 misdeclarations."""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps
from django.db import connection, models
from django.test.utils import isolate_apps

from karni.constraints import NoOverlap
from karni.fields import CapacityField, StateField
from karni.guard_checks import check_guarded_models
from karni.models import BaseModel


def _ids(messages: list[Any]) -> list[str]:
    return [message.id for message in messages]


def _lifecycleapp() -> list[Any]:
    return check_guarded_models(app_configs=[apps.get_app_config("lifecycleapp")])


@pytest.mark.skipif(connection.vendor == "postgresql", reason="the warning is for other backends")
def test_no_overlap_off_postgresql_warns_on_every_boot() -> None:
    messages = _lifecycleapp()
    warned = sorted(m.obj.__name__ for m in messages if m.id == "karni.W980")
    assert "Slot" in warned
    slot = next(m for m in messages if m.id == "karni.W980" and m.obj.__name__ == "Slot")
    assert "is NOT enforced: the sqlite database has no EXCLUDE constraint" in slot.msg
    assert "SILENCED_SYSTEM_CHECKS" in slot.hint


@pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL enforces it")
def test_no_overlap_on_postgresql_is_silent() -> None:
    assert _lifecycleapp() == []


class _App:
    """Run checks over models built inside ``isolate_apps``."""

    @staticmethod
    def check(*models_: type[models.Model]) -> list[Any]:
        class Config:
            def get_models(self) -> list[type[models.Model]]:
                return list(models_)

        return [m for m in check_guarded_models(app_configs=[Config()]) if m.id != "karni.W980"]


@isolate_apps("tests.lifecycleapp")
def test_a_guarded_field_on_a_model_without_guardedmodel_is_an_error() -> None:
    class Plain(models.Model):
        status = StateField(states=["a", "b"], transitions={"a": ["b"]})

        class Meta:
            app_label = "lifecycleapp"

    (message,) = _App.check(Plain)
    assert message.id == "karni.E988"
    assert "Inherit karni.models.BaseModel" in message.hint


@isolate_apps("tests.lifecycleapp")
def test_a_capacity_total_must_be_an_integer_field_of_the_model() -> None:
    class Bad(BaseModel):
        label = models.CharField(max_length=10)
        left = CapacityField(total="label")

        class Meta(BaseModel.Meta):
            app_label = "lifecycleapp"

    (message,) = _App.check(Bad)
    assert message.id == "karni.E986" and "is a CharField" in message.msg


@isolate_apps("tests.lifecycleapp")
def test_a_no_overlap_over_a_plain_field_or_an_unknown_state_is_an_error() -> None:
    class Shift(BaseModel):
        who = models.CharField(max_length=10)
        day = models.CharField(max_length=10)
        status = StateField(states=["on", "off"], transitions={"on": ["off"]})

        class Meta(BaseModel.Meta):
            app_label = "lifecycleapp"

        class Karni:
            no_overlap = NoOverlap("who", "day", ignore={"status": ["gone"], "nope": [1]})

    messages = _App.check(Shift)
    assert _ids(messages) == ["karni.E987"] * 3
    text = " ".join(m.msg for m in messages)
    assert "'day' is a CharField, not a range field" in text
    assert "'gone', which is not a state of Shift.status" in text
    assert "ignore names 'nope'" in text


@isolate_apps("tests.lifecycleapp")
def test_no_overlap_is_added_to_the_models_constraints_for_migrations() -> None:
    class Visit(BaseModel):
        guide = models.CharField(max_length=10)
        starts_at = models.DateTimeField()
        ends_at = models.DateTimeField()

        class Meta(BaseModel.Meta):
            app_label = "lifecycleapp"

        class Karni:
            no_overlap = [("guide", ("starts_at", "ends_at")), NoOverlap(("starts_at", "ends_at"))]

    names = [c.name for c in Visit._meta.constraints]
    assert names == [
        "lifecycleapp_visit_guide_starts_at_ends_at_no_overlap",
        "lifecycleapp_visit_starts_at_ends_at_no_overlap",
    ]
    assert "constraints" in Visit._meta.original_attrs
    from django.db.migrations.state import ModelState

    state = ModelState.from_model(Visit)
    assert [c.name for c in state.options["constraints"]] == names
    _path, args, kwargs = Visit._meta.constraints[0].deconstruct()
    assert args == ("guide", ("starts_at", "ends_at"))
    assert NoOverlap(*args, **kwargs) == Visit._meta.constraints[0]


@isolate_apps("tests.lifecycleapp")
def test_a_malformed_no_overlap_fails_at_import() -> None:
    from karni.errorcodes import KarniError

    with pytest.raises(KarniError) as raised:

        class Broken(BaseModel):
            class Meta(BaseModel.Meta):
                app_label = "lifecycleapp"

            class Karni:
                no_overlap = "room"

    assert raised.value.code == "E987"
