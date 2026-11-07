## Reports (karni-reports, experimental)
- A PDF of one row is a report. Never call WeasyPrint or write a PDF view by hand.
  Declare it in `<app>/reports.py`: `@register class ProductSheet(Report)` with
  `model`, `template` (extends `karni_reports/base.html`) and `get_context(obj)`.
- `get_context` gets only the row: the file is shared by everyone who may see it.
  Put related rows the template prints in the context, so their changes count.
- API (auto-routed, no URL include): `POST /api/reports/<report>/<id>/`, then
  `GET .../status/` and `.../download/`. Access is the model's own viewset retrieve.
- UI: `<ReportButton report="product-sheet" objectId={id} />` from `@karni/reports-ui`.
- `manage.py karni_pregenerate <report> [--ids ...|--stale] [--force]` renders ahead.
- Settings: KARNI_REPORTS_PAGE_SIZE, KARNI_REPORTS_RENDERER (`fake` in tests),
  KARNI_REPORTS_STORAGE, KARNI_REPORTS_KEEP. Keep the Celery worker running.
