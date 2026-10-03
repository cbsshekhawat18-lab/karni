"""``karni.managers.SoftDeleteManagerMixin`` -> ``karni.managers.ScopedManagerMixin``.

Changelog entry ``soft-delete-manager-mixin``; migration note
docs/migrations/0.2.md#softdeletemanagermixin.
"""

from __future__ import annotations

from karni_cli.upgrades.python import RenameSymbol

CODEMOD = RenameSymbol(
    old="karni.managers.SoftDeleteManagerMixin",
    new="karni.managers.ScopedManagerMixin",
)
