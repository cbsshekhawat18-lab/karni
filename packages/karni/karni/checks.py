"""Django system checks for Karni's model layer.

Registered from :class:`karni.apps.KarniAppConfig`, so problems surface on
boot (``runserver``, ``migrate``, ``check``) instead of at request time.
Silence one deliberately with Django's ``SILENCED_SYSTEM_CHECKS``.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks


@checks.register(checks.Tags.models)
def check_soft_delete_managers(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E001: a soft-delete model whose default manager shows deleted rows.

    Composing mixins with another one before ``SoftDeleteModel`` (e.g.
    ``class X(TimestampedModel, SoftDeleteModel)``) makes the earlier mixin's
    plain ``objects`` and ``Meta`` win, so deleted rows silently reappear in
    every query, relation and API response.
    """
    from karni.managers import SoftDeleteManagerMixin
    from karni.models import SoftDeleteModel

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    errors: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if not issubclass(model, SoftDeleteModel):
                continue
            manager = model._default_manager
            if isinstance(manager, SoftDeleteManagerMixin):
                continue
            errors.append(
                checks.Error(
                    f"{model.__name__} inherits SoftDeleteModel, but its default manager "
                    f"'{manager.name}' ({type(manager).__name__}) does not hide soft-deleted "
                    "rows, so deleted rows appear in every query, relation and API response.",
                    hint=(
                        "Inherit karni.models.BaseModel, or list SoftDeleteModel first among "
                        "the Karni mixins, or declare objects = SoftDeleteManager() (any "
                        "manager built on karni.managers.SoftDeleteManagerMixin) with "
                        "'class Meta(SoftDeleteModel.Meta)'."
                    ),
                    obj=model,
                    id="karni.E001",
                )
            )
    return errors
