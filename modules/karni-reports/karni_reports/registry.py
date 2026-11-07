"""The report registry: every declared report, by name.

``@register`` on a :class:`~karni_reports.report.Report` subclass adds it.
At startup the module imports the ``reports`` module of every installed app
(:func:`autodiscover`), so ``<app>/reports.py`` is where reports live.

Override / escape hatch: call :func:`register` from anywhere that is imported
at startup, and :func:`unregister` to take a report out (tests).
"""

from __future__ import annotations

import re

from django.db.models import Model
from karni.api.routers import kebab
from karni.exceptions import KarniImproperlyConfigured, KarniLookupError

from karni_reports.report import Report

__all__ = ["autodiscover", "get_report", "register", "reports", "unregister"]

#: A report's name: its address in the API.
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

_REPORTS: dict[str, Report] = {}


def _qualified(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def register[ReportClass: type[Report]](report_class: ReportClass) -> ReportClass:
    """Experimental. Add a report to the registry (a class decorator). Returns the class.

    Checks the declaration: a model class, a template name and a valid name
    (``REPORT002``), unique among the reports (``REPORT003``). Registering the
    same class again replaces it.
    """
    label = report_class.__name__
    if not (isinstance(report_class, type) and issubclass(report_class, Report)):
        raise KarniImproperlyConfigured(
            f"@register takes a karni_reports.Report subclass, not {report_class!r}.",
            code="REPORT002",
        )
    model = report_class.model
    if not (isinstance(model, type) and issubclass(model, Model)) or model._meta.abstract:
        raise KarniImproperlyConfigured(
            f"{label}.model must be a concrete model class, not {model!r}.", code="REPORT002"
        )
    if not isinstance(report_class.template, str) or not report_class.template:
        raise KarniImproperlyConfigured(
            f"{label}.template must name a template, e.g. "
            f"'{model._meta.app_label}/{model._meta.model_name}_report.html'.",
            code="REPORT002",
        )
    name = report_class.name or kebab(label)
    if not NAME.match(name):
        raise KarniImproperlyConfigured(
            f"{label}.name {name!r} is not a report name: use lowercase letters, digits, - and "
            "_, at most 64 characters, starting with a letter or a digit.",
            code="REPORT002",
        )
    existing = _REPORTS.get(name)
    if existing is not None and _qualified(type(existing)) != _qualified(report_class):
        raise KarniImproperlyConfigured(
            f"Two reports are named {name!r}: {_qualified(type(existing))} and "
            f"{_qualified(report_class)}. Give one of them another `name`.",
            code="REPORT003",
        )
    report_class.name = name
    report_class.title = report_class.title or re.sub(r"(?<!^)(?=[A-Z])", " ", label)
    _REPORTS[name] = report_class()
    return report_class


def unregister(name: str) -> None:
    """Take the report ``name`` out of the registry (nothing when it is not there)."""
    _REPORTS.pop(name, None)


def get_report(name: str) -> Report:
    """The report registered as ``name`` (``REPORT001`` when there is none)."""
    found = _REPORTS.get(name)
    if found is None:
        known = ", ".join(sorted(_REPORTS)) or "none"
        raise KarniLookupError(
            f"No report is named {name!r}. Registered reports: {known}.", code="REPORT001"
        )
    return found


def reports() -> dict[str, Report]:
    """Every registered report, by name."""
    return dict(sorted(_REPORTS.items()))


def autodiscover() -> None:
    """Import ``<app>.reports`` for every installed app that has one."""
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("reports")
