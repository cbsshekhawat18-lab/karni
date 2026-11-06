"""karni-reports: a row of any model printed to PDF, in the background, cached.

A report is declared in code (:class:`Report`, :func:`register`) in
``<app>/reports.py``: the model, the template and ``get_context(obj)``. A
Celery task renders the template to HTML, then to PDF with WeasyPrint, and
stores the file through Django's storage. The file is cached by the template
(its sources) and the data (a hash of the context), so a changed row or
template gives a new file and an unchanged one is served again. The API
serves it only to users who may retrieve the row through its own viewset.

The names load on first use (PEP 562), so Django importing the app at
startup loads nothing else.
"""

from __future__ import annotations

from importlib import metadata as _metadata
from typing import TYPE_CHECKING, Any

try:
    __version__ = _metadata.version("karni-reports")  # [project] version in pyproject.toml
except _metadata.PackageNotFoundError:  # a source tree on sys.path, never installed
    __version__ = "0+unknown"

if TYPE_CHECKING:
    from karni_reports.registry import get_report, register, reports, unregister
    from karni_reports.report import Report

__all__ = ["Report", "get_report", "register", "reports", "unregister"]

_LAZY = {
    "Report": "karni_reports.report",
    "get_report": "karni_reports.registry",
    "register": "karni_reports.registry",
    "reports": "karni_reports.registry",
    "unregister": "karni_reports.registry",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'karni_reports' has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module), name)
