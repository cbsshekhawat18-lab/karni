"""karni-reports' error codes (prefix ``REPORT``), registered with Karni's registry.

Exposed through the ``karni.errorcodes`` entry point, so ``karni explain
REPORT004`` and ``docs/errors.md`` include them. Codes are permanent: never
renumber or reuse one; append new codes at the end.
"""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_reports"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="REPORT001",
        title="No report has that name",
        kind="api",
        source=f"{_SOURCE}.registry.get_report (the endpoints answer 404)",
        why="A report is requested by the name its class declares, and none is registered "
        "under this one.",
        fix="Use a name `manage.py karni_pregenerate --list` prints, or declare the report in "
        "<app>/reports.py with @register.",
    ),
    ErrorCode(
        code="REPORT002",
        title="A report declaration is incomplete",
        kind="exception",
        source=f"{_SOURCE}.registry.register",
        why="A report prints rows of one model through one template, so both must be named.",
        fix="Set `model` to a model class and `template` to a template name on the Report "
        "subclass, and give it a name of lowercase letters, digits, - and _.",
    ),
    ErrorCode(
        code="REPORT003",
        title="Two reports have the same name",
        kind="exception",
        source=f"{_SOURCE}.registry.register",
        why="The name is the report's address in the API, so it must be unique.",
        fix="Give one of them another `name`.",
    ),
    ErrorCode(
        code="REPORT004",
        title="No viewset serves the report's model",
        kind="check",
        source=f"{_SOURCE}.report.Report.get_viewset and karni check",
        why="Who may see a row's report is decided by who may retrieve the row through its "
        "model's viewset. Without one, nobody can be checked, so the report is refused.",
        fix="Add a BaseViewSet for the model (karni make viewset <Model>), or set `viewset` on "
        "the Report to the viewset class or its dotted path.",
    ),
    ErrorCode(
        code="REPORT005",
        title="KARNI_REPORTS_RENDERER cannot be loaded",
        kind="exception",
        source=f"{_SOURCE}.rendering.get_renderer",
        why="Every report goes through the configured renderer to become a PDF.",
        fix="Set KARNI_REPORTS_RENDERER to 'weasyprint', 'fake' (tests) or the dotted path of "
        "a karni_reports.rendering.Renderer subclass.",
    ),
    ErrorCode(
        code="REPORT006",
        title="WeasyPrint or the system libraries it needs are missing",
        kind="exception",
        source=f"{_SOURCE}.rendering.WeasyPrintRenderer",
        why="WeasyPrint draws the PDF with Pango, which is a system library, not a Python package.",
        fix="Install Pango: apt-get install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b "
        "fonts-dejavu-core (Debian, Ubuntu), apk add pango font-dejavu (Alpine) or brew "
        "install pango (macOS). Set KARNI_REPORTS_RENDERER = 'fake' in tests.",
    ),
    ErrorCode(
        code="REPORT007",
        title="A report failed to render",
        kind="exception",
        source=f"{_SOURCE}.services.render (stored on the GeneratedReport row)",
        why="The template, the report's get_context or the renderer raised. The row keeps the "
        "error and the API answers status 'failed'.",
        fix="Read the error on the row in the admin (Generated reports, filter by status "
        "failed), fix the template or get_context, then use the Regenerate action or request "
        "the report again.",
    ),
    ErrorCode(
        code="REPORT008",
        title="No file is ready for this report and row yet",
        kind="api",
        source=f"{_SOURCE}.viewsets.GeneratedReportViewSet.download_report",
        why="The download serves a rendered file. This row's report was never requested, or "
        "is still rendering, or failed.",
        fix="POST /api/reports/<report>/<id>/ to request it, poll its status/ until it says "
        "ready, then download.",
    ),
    ErrorCode(
        code="REPORT009",
        title="A template referenced a URL the renderer does not fetch",
        kind="warning",
        source=f"{_SOURCE}.rendering.WeasyPrintRenderer.fetch",
        why="Fetching any URL while rendering would let a value in a row make the server "
        "call another host. The renderer reads only data: URLs and files under STATIC_URL "
        "and MEDIA_URL, and leaves the rest out of the PDF.",
        fix="Serve the image or stylesheet from your static or media files, or subclass "
        "WeasyPrintRenderer with allow_network = True and name it in KARNI_REPORTS_RENDERER.",
    ),
    ErrorCode(
        code="REPORT010",
        title="A report's template does not exist",
        kind="check",
        source=f"{_SOURCE}.checks.run_checks",
        why="Every render loads the template, so a missing one fails every request.",
        fix="Create the template the report names, or correct its `template`.",
    ),
    ErrorCode(
        code="REPORT011",
        title="A report's context holds a value with no stable text",
        kind="exception",
        source=f"{_SOURCE}.versions.encode",
        why="The data version is a hash of the context. A value whose text changes on every "
        "run (an object without __str__) would make every request render again.",
        fix="Put plain data in the context (dicts, lists, model instances, querysets), give "
        "the class a __str__, or override Report.get_data_version.",
    ),
)
