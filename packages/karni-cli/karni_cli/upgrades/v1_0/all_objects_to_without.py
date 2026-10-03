"""``Model.all_objects`` -> ``Model.objects.without("soft_delete", reason=...)``.

Changelog entry ``all-objects``; migration note docs/migrations/0.2.md#all_objects.
"""

from __future__ import annotations

from karni_cli.upgrades.python import ReplaceAttribute

CODEMOD = ReplaceAttribute(
    attr="all_objects",
    replacement='objects.without("soft_delete", reason="<auto: migrated from all_objects>")',
    # all_objects is a manager; the replacement is a queryset. These need the
    # manager (or would chain a second, conflicting scope lift).
    manager_only=frozenset(
        {"get_queryset", "db_manager", "without", "all_with_deleted", "deleted_only"}
    ),
)
