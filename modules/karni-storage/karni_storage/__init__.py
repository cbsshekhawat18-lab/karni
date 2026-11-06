"""karni-storage: protected files in S3 or an S3-compatible service.

Files a row owns, kept in a private bucket (or a private directory in
development) and handed only to whoever may read the row, through the row's
own viewset: :mod:`karni_storage.fields` (``ProtectedFileField``,
``ProtectedImageField``), provider presets for core's S3 backend
(:mod:`karni_storage.presets`), direct uploads with a confirm step
(:mod:`karni_storage.views`) and thumbnails (:mod:`karni_storage.thumbnails`).

Experimental: every public name here may change in a minor release, with a
CHANGELOG entry (docs/stability.md).
"""

from __future__ import annotations

from importlib import metadata as _metadata

__version__ = _metadata.version("karni-storage")  # [project] version in pyproject.toml
