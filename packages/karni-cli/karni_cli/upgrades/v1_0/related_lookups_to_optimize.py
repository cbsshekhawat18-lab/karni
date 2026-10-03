"""Detector: ``karni.api.expansion.related_lookups()`` -> ``karni.api.optimizer.optimize()``.

Not mechanical: the replacement takes a queryset and a serializer instead
of expand paths. Changelog entry ``related-lookups``; migration note
docs/migrations/0.2.md#related_lookups-and-scoped_related_lookups.
"""

from __future__ import annotations

from karni_cli.upgrades.python import FindReferences

CODEMOD = FindReferences(
    qualified_names=("karni.api.expansion.related_lookups",),
    note="replace with karni.api.optimizer.optimize(queryset, serializer)",
)
