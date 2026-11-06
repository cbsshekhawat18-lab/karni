"""karni-ai: structured extraction with a language model, into any resource's import preview.

Experimental. A source (text, a URL or a PDF) is read by a language model
into rows that follow the target resource's own JSON Schema, and the rows go
through Karni's import preview. Nothing is written until a user confirms the
preview through the import's commit. Every call is logged with its tokens
and cost, and monthly budgets cap the spending.

Karni core never imports this package.
"""

from __future__ import annotations

from importlib import metadata as _metadata

try:
    __version__ = _metadata.version("karni-ai")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"
