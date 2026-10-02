"""Django system checks for Karni's model layer.

Registered from :class:`karni.apps.KarniAppConfig`, so problems surface on
boot (``runserver``, ``migrate``, ``check``) instead of at request time.
Silence one deliberately with Django's ``SILENCED_SYSTEM_CHECKS``.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.core import checks
from django.core.exceptions import ImproperlyConfigured


@checks.register(checks.Tags.models)
def check_soft_delete_managers(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E001: a soft-delete model whose default manager shows deleted rows.

    The default manager must run the scope pipeline
    (:class:`karni.managers.ScopedManagerMixin`) without ``soft_delete``
    lifted. One way to break this is to compose another mixin before
    ``SoftDeleteModel`` (e.g. ``class X(TimestampedModel, SoftDeleteModel)``).
    The earlier mixin's plain ``objects`` and ``Meta`` then win, and deleted
    rows silently reappear in every query, relation and API response. They
    would also miss every future scope, such as ``tenant``.
    """
    from karni.managers import ScopedManagerMixin
    from karni.models import SoftDeleteModel
    from karni.scopes import SOFT_DELETE

    configs = app_configs if app_configs is not None else apps.get_app_configs()
    errors: list[checks.CheckMessage] = []
    for config in configs:
        for model in config.get_models():
            if not issubclass(model, SoftDeleteModel):
                continue
            manager = model._default_manager
            if isinstance(manager, ScopedManagerMixin) and SOFT_DELETE not in manager._karni_lifted:
                continue
            errors.append(
                checks.Error(
                    f"{model.__name__} inherits SoftDeleteModel, but its default manager "
                    f"'{manager.name}' ({type(manager).__name__}) does not apply Karni's "
                    "'soft_delete' scope, so deleted rows appear in every query, relation "
                    "and API response.",
                    hint=(
                        "Inherit karni.models.BaseModel, or list SoftDeleteModel first among "
                        "the Karni mixins, or declare objects = SoftDeleteManager() (any "
                        "manager built on karni.managers.ScopedManagerMixin) with "
                        "'class Meta(SoftDeleteModel.Meta)'."
                    ),
                    obj=model,
                    id="karni.E001",
                )
            )
    return errors


@checks.register(checks.Tags.models)
def check_scopes(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """karni.E002 / karni.W001: the scope registry and ``KARNI_SCOPES``.

    E002 reports a scope that fails to load or register, or a malformed
    ``KARNI_SCOPES``. W001 reports a registered scope that ``KARNI_SCOPES``
    leaves out, and that is therefore off. Silence W001 when that is
    deliberate.
    """
    from django.conf import settings

    from karni.scopes import SETTING, registry

    try:
        active = {scope.name for scope in registry.active()}
        registered = registry.names()
    except ImproperlyConfigured as exc:
        return [
            checks.Error(
                str(exc),
                hint="Fix the scope or the KARNI_SCOPES setting the message names.",
                id="karni.E002",
            )
        ]
    if getattr(settings, SETTING, None) is None:
        return []
    return [
        checks.Warning(
            f"Scope {name!r} is registered but not listed in {SETTING}, so it is off "
            "and filters nothing.",
            hint=(
                f"Add {name!r} to {SETTING} (or unset {SETTING} to run every scope), or "
                "add 'karni.W001' to SILENCED_SYSTEM_CHECKS if disabling it is deliberate."
            ),
            id="karni.W001",
        )
        for name in registered
        if name not in active
    ]
