"""Build-failing checks for ``karni check``: every report can render and be checked.

``REPORT004``: a report whose model no viewset serves (who may see a row
cannot be decided). ``REPORT010``: a report whose template does not exist.
"""

from __future__ import annotations

__all__ = ["run_checks"]

MISSING_TEMPLATE = "REPORT010"


def run_checks() -> list[str]:
    from django.apps import apps
    from django.template import TemplateDoesNotExist
    from django.template.loader import get_template
    from karni.exceptions import KarniImproperlyConfigured

    from karni_reports.registry import reports

    if not apps.is_installed("karni_reports"):
        return []  # installed in the environment, not in this project
    failures: list[str] = []
    for name, report in reports().items():
        try:
            report.get_viewset()
        except KarniImproperlyConfigured as exc:
            failures.append(f"{exc.code}: {exc.message}")
        except ImportError as exc:
            failures.append(f"REPORT004: report {name!r}: its viewset cannot be imported ({exc}).")
        template = report.get_template_name()
        try:
            get_template(template)
        except TemplateDoesNotExist:
            failures.append(
                f"{MISSING_TEMPLATE}: report {name!r} names the template {template!r}, which "
                "does not exist. Create it (it usually extends karni_reports/base.html)."
            )
    return failures
