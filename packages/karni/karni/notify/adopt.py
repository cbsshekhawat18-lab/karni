"""Hand edited emails kept in a part's own table to the notifications contract.

A part that kept the emails a business rewrote in a table of its own (as
karni-commerce did) moves them in a data migration::

    from karni.notify.adopt import adopt_edited_emails, return_edited_emails

    migrations.RunPython(
        lambda apps, editor: adopt_edited_emails(apps, editor, "shop.EmailTemplate"),
        lambda apps, editor: return_edited_emails(apps, editor, "shop.EmailTemplate"),
    )

Each live row (``kind``, ``subject``, ``text``, its authors and dates) is copied
to :class:`karni.notify.models.EmailTemplate`, unless the contract already
holds an edit of that kind. Without ``karni.notify`` installed, a table with no
edited email moves nothing, and one with edits stops the migration (``E446``)
before the part drops its table.

Override / escape hatch: write the copy in your own migration with the
historical models, as these two functions do.
"""

from __future__ import annotations

from typing import Any, Final

from django.apps import apps as global_apps

from karni.exceptions import KarniImproperlyConfigured

__all__ = ["adopt_edited_emails", "installed", "return_edited_emails"]

#: What is copied from row to row besides the dates.
_COPIED: Final = ("kind", "subject", "text", "created_by_id", "updated_by_id")
_TARGET: Final = "notify.EmailTemplate"


def installed() -> bool:
    """Whether ``karni.notify`` is in ``INSTALLED_APPS``: its table can take the rows."""
    return global_apps.is_installed("karni.notify")


def _live(model: Any, alias: str) -> Any:
    return model._base_manager.using(alias).filter(deleted_at__isnull=True)


def _copy(source: Any, target: Any, alias: str) -> int:
    have = set(_live(target, alias).values_list("kind", flat=True))
    copied = 0
    for row in _live(source, alias).order_by("kind"):
        if row.kind in have:
            continue  # the edit already there wins
        made = target._base_manager.using(alias).create(
            id=row.id, **{name: getattr(row, name) for name in _COPIED}
        )
        # create() stamps the dates now: put the originals back.
        target._base_manager.using(alias).filter(pk=made.pk).update(
            created_at=row.created_at, updated_at=row.updated_at
        )
        copied += 1
    return copied


def adopt_edited_emails(apps: Any, schema_editor: Any, source: str) -> int:
    """Copy the live rows of ``source`` (``"app_label.Model"``) to notify.

    Returns how many were copied. ``apps`` and ``schema_editor`` are the ones
    ``RunPython`` passes.

    :raises KarniImproperlyConfigured: E446, edited emails and no ``karni.notify``.
    """
    alias = schema_editor.connection.alias
    model = apps.get_model(source)
    if not installed():
        edited = _live(model, alias).count()
        if edited:
            raise KarniImproperlyConfigured(
                f"karni.notify: {edited} edited email(s) in {source} move to the "
                "notifications contract, and karni.notify is not installed, so they would be "
                "lost. Add 'karni.notify' to INSTALLED_APPS (features: {notify: true} in "
                "karni.yaml) and run migrate again.",
                code="E446",
            )
        return 0
    return _copy(model, apps.get_model(_TARGET), alias)


def return_edited_emails(apps: Any, schema_editor: Any, target: str) -> int:
    """The way back: copy notify's edited emails to ``target`` again."""
    if not installed():
        return 0
    alias = schema_editor.connection.alias
    return _copy(apps.get_model(_TARGET), apps.get_model(target), alias)
