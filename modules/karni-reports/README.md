# karni-reports

Reports for Karni: a row printed to PDF from an HTML template in the background, cached by template and data, served only to users who may see the row.

[![PyPI](https://img.shields.io/pypi/v/karni-reports)](https://pypi.org/project/karni-reports/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/cbsshekhawat18-lab/karni/blob/main/LICENSE) [![Docs](https://img.shields.io/badge/docs-online-FB5D08)](https://cbsshekhawat18-lab.github.io/karni/reports/)

Experimental. A Celery task renders the template with WeasyPrint and stores the file through Django's storage. The file is cached by the template and the data, so a changed row or template gives a new file and an unchanged one is served again without rendering. The API serves it only to users who may retrieve the row through its own viewset.

## Install

```sh
pip install karni-reports
karni add reports
karni migrate
```

No URL include: the endpoints ride the API router. WeasyPrint draws with
Pango, a system library. Install it in the image or on the host:

```sh
apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core   # Debian, Ubuntu
apk add pango font-dejavu                                                              # Alpine
brew install pango                                                                     # macOS
```

## Declare a report

```python
# catalog/reports.py
from karni_reports import Report, register

from catalog.models import Product


@register
class ProductSheet(Report):
    model = Product
    template = "catalog/product_sheet.html"

    def get_context(self, obj: Product) -> dict[str, object]:
        return {"product": obj, "category": obj.category}
```

```html
{% extends "karni_reports/base.html" %}
{% block content %}<h1>{{ product.name }}</h1>{% endblock %}
```

`get_context` gets only the row: one file serves everyone who may see the
row, so it must not depend on who asks.

## Main features

- A report declared in `<app>/reports.py`: the model, the template and `get_context(obj)`
- Rendered in the background by a Celery task, with WeasyPrint
- Cached by the template and a hash of the data
- `POST /api/reports/<report>/<id>/`, its status and its download, under the row's own access
- A base print template, `manage.py karni_pregenerate` and a Generated reports admin
- A React button in [`@karni/reports-ui`](https://www.npmjs.com/package/@karni/reports-ui)

## Endpoints

| Method and path | Answer |
|---|---|
| `POST /api/reports/<report>/<id>/` | 200 with `url` when a file is ready at the current key, else 202 with status `pending` |
| `GET /api/reports/<report>/<id>/status/` | the last request's status: `none`, `pending`, `rendering`, `ready` or `failed` |
| `GET /api/reports/<report>/<id>/download/` | the PDF, once ready (404 `REPORT008` before) |

Each checks the row through its model's viewset `retrieve`: 401 or 403 from
its gate, 404 for a row out of the caller's scope.

## Settings

| Setting | Env var | Default | Meaning |
|---|---|---|---|
| `KARNI_REPORTS_RENDERER` | same | `"weasyprint"` | `weasyprint`, `fake` (tests) or a `Renderer` subclass's dotted path |
| `KARNI_REPORTS_STORAGE` | same | `"default"` | the `STORAGES` alias the files go to |
| `KARNI_REPORTS_DIRECTORY` | same | `"karni/reports"` | the folder inside that storage |
| `KARNI_REPORTS_PAGE_SIZE` | same | `"A4"` | the CSS page size of the base template |
| `KARNI_REPORTS_KEEP` | same | `1` | ready files kept per report and row (`0`: all) |
| `KARNI_REPORTS_RENDER_TIMEOUT` | same | `600` | seconds before a stuck render is queued again |

## Admin

**Generated reports** lists every file with its status, size, data version
and times. Filter by status `failed` to read why a render failed, and use
**Regenerate selected reports** to queue renders again. The admin is an
explicit registration (`karni_reports.admin.GeneratedReportAdmin`).

## Escape hatches

- `Report.get_context`, `get_template_name`, `get_filename`, `get_renderer`,
  `get_queryset`, `get_template_version`, `get_data_version` and
  `get_render_options`: one change for one report.
- `Report.viewset`, or `Report.get_object`, decides access for one report.
- `KARNI_REPORTS_RENDERER`: your own `karni_reports.rendering.Renderer`.
  Subclass `WeasyPrintRenderer` with `allow_network = True` to let templates
  load images from other hosts (only static, media and `data:` URLs by default).
- Throttles: `reports.request_report`, `reports.report_status` and
  `reports.download_report` in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`.
- The task: `karni_reports.tasks.render_report`. Route it with Celery's
  `task_routes`.

## Links

- Reports (PDF): <https://cbsshekhawat18-lab.github.io/karni/reports/>
- React components: <https://www.npmjs.com/package/@karni/reports-ui>
- Karni, the framework this package is part of: <https://github.com/cbsshekhawat18-lab/karni>
- Changelog: <https://github.com/cbsshekhawat18-lab/karni/blob/main/CHANGELOG.md>
- Issues: <https://github.com/cbsshekhawat18-lab/karni/issues>
- License: Apache-2.0. karni-reports is released with every other Karni package, at one version.
