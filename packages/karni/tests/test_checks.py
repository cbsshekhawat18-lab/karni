"""karni.E001: soft-delete models must hide deleted rows by default.

The scope-registry checks (karni.E002, karni.W001) are in ``tests/test_scopes.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.db import models
from django.test.utils import isolate_apps

from karni.checks import check_soft_delete_managers
from karni.managers import ScopedManagerMixin, SoftDeleteQuerySet
from karni.models import BaseModel, SoftDeleteModel, TimestampedModel


def _run(*model_classes: type[models.Model]) -> list:
    config = SimpleNamespace(get_models=lambda: list(model_classes))
    return check_soft_delete_managers(app_configs=[config])


@isolate_apps("tests.testapp")
def test_mixin_order_that_loses_the_soft_delete_manager_errors() -> None:
    class Wrong(TimestampedModel, SoftDeleteModel):
        class Meta:
            app_label = "testapp"

    errors = _run(Wrong)
    assert [e.id for e in errors] == ["karni.E001"]
    assert "Wrong" in errors[0].msg
    assert "SoftDeleteModel first" in errors[0].hint


@isolate_apps("tests.testapp")
def test_correct_compositions_pass() -> None:
    class Base(BaseModel):
        class Meta:
            app_label = "testapp"

    class SoftFirst(SoftDeleteModel, TimestampedModel):
        class Meta(SoftDeleteModel.Meta):
            app_label = "testapp"

    class Plain(TimestampedModel):
        class Meta:
            app_label = "testapp"

    assert _run(Base, SoftFirst, Plain) == []


@isolate_apps("tests.testapp")
def test_a_default_manager_with_soft_delete_lifted_errors() -> None:
    class Lifted(BaseModel):
        class Meta(BaseModel.Meta):
            app_label = "testapp"
            default_manager_name = "all_objects"  # the deprecated alias

    errors = _run(Lifted)
    assert [e.id for e in errors] == ["karni.E001"]
    assert "does not apply Karni's 'soft_delete' scope" in errors[0].msg
    assert "karni.managers.ScopedManagerMixin" in errors[0].hint


@isolate_apps("tests.testapp")
def test_a_custom_manager_on_the_pipeline_passes() -> None:
    class ArchiveManager(ScopedManagerMixin, models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
        pass

    class Archived(SoftDeleteModel):
        objects = ArchiveManager()

        class Meta(SoftDeleteModel.Meta):
            app_label = "testapp"

    assert _run(Archived) == []


def test_project_models_are_clean() -> None:
    """The real test apps pass the check (it runs on every boot)."""
    assert check_soft_delete_managers() == []
