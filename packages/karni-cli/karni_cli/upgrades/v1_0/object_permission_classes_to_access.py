"""Detector: ``BaseViewSet.object_permission_classes`` -> the ``access`` declaration.

Not mechanical: an arbitrary permission class has no faithful translation
into access predicates, so this reports every viewset that sets it and edits
nothing. Changelog entry ``object-permission-classes``; migration note
docs/migrations/0.2.md#object_permission_classes.
"""

from __future__ import annotations

from karni_cli.upgrades.python import FindClassAttribute

CODEMOD = FindClassAttribute(
    name="object_permission_classes",
    note="express this rule in the access declaration (Owned, HasRole, Where)",
)
