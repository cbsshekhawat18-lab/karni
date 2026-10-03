"""``objects.all_with_deleted()`` -> ``objects.without("soft_delete", reason=...)``.

Changelog entry ``all-with-deleted``; migration note docs/migrations/0.2.md#all_with_deleted.
"""

from __future__ import annotations

from karni_cli.upgrades.python import ReplaceMethodCall

CODEMOD = ReplaceMethodCall(
    method="all_with_deleted",
    replacement='without("soft_delete", reason="<auto: migrated from all_with_deleted()>")',
)
