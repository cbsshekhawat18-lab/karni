"""``objects.deleted_only()`` -> ``objects.without("soft_delete", reason=...).dead()``.

Changelog entry ``deleted-only``; migration note docs/migrations/0.2.md#deleted_only.
"""

from __future__ import annotations

from karni_cli.upgrades.python import ReplaceMethodCall

CODEMOD = ReplaceMethodCall(
    method="deleted_only",
    replacement='without("soft_delete", reason="<auto: migrated from deleted_only()>").dead()',
)
