---
description: "PDF reports with the karni-reports module: a row printed from an HTML template by WeasyPrint in a Celery task, cached by template and data, served only to users who may retrieve the row, with a pre-generation command and a React button."
---

# Reports (PDF)

!!! warning "Experimental"
    The `karni-reports` module, `karni_reports` (`Report`, `register`, the
    renderers, `GeneratedReport`), its settings, its endpoints, `manage.py
    karni_pregenerate` and `@karni/reports-ui` are
    [experimental](stability.md#experimental-names).

Projects keep writing the same PDF code: a view that renders a template,
calls a PDF library, holds a worker for seconds, and forgets to check who
asked. `karni-reports` does it once. A report prints one row of a model from
an HTML template. A Celery task renders it with WeasyPrint and stores the
file through Django's storage. The file is cached by the template and the
data, so a changed row or template gives a new file and an unchanged one is
served again without rendering. Every endpoint first retrieves the row
through the model's own viewset, so a report is never readable by someone
who cannot read the row.

## Install

```sh
pip install karni-reports
karni add reports
karni migrate
```

Or list it in [karni.yaml](app-spec.md#modules), and `karni build` adds it:

```yaml
modules:
  reports: {page_size: letter}
```

There is no URL include: the endpoints ride the API router. Keep a Celery
worker running, since renders are tasks.

### The system libraries

WeasyPrint draws with Pango, a system library that `pip` does not install.
Add it to the image (or the host) next to a font:

```sh
# Debian, Ubuntu (the python:3.12-slim image)
apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core
# Alpine
apk add pango font-dejavu
# macOS
brew install pango
```

Without it a render fails with [`REPORT006`](errors.md#report006), which
names these packages. Tests need none of it: set
`KARNI_REPORTS_RENDERER = "fake"` in the test settings (see
[testing](#testing)).

## Declaring a report

A report is a class in `<app>/reports.py`, which the module imports at
startup:

```python
# catalog/reports.py
from karni_reports import Report, register

from catalog.models import Product


@register
class ProductSheet(Report):
    model = Product
    template = "catalog/product_sheet.html"

    def get_context(self, obj: Product) -> dict[str, object]:
        return {"product": obj, "category": obj.category, "prices": obj.prices.order_by("region")}
```

| Attribute | Default | Meaning |
|---|---|---|
| `model` | required | the model whose rows the report prints |
| `template` | required | the template name |
| `name` | the class name in kebab case (`product-sheet`) | the report's address in the API: lowercase letters, digits, `-` and `_` |
| `title` | the class name with spaces | what the admin and the base template show |
| `viewset` | the viewset routed for `model` | the viewset whose `retrieve` decides who may see a row's report: a class or a dotted path |

`@register` refuses a report without a model or a template
([`REPORT002`](errors.md#report002)) and a name two reports share
([`REPORT003`](errors.md#report003)). `karni check` fails for a report whose
model no viewset serves ([`REPORT004`](errors.md#report004)) and for a
template that does not exist ([`REPORT010`](errors.md#report010)).

`get_context(obj)` gets the row and nothing about who asks. One file serves
everyone who may see the row, so the context must not depend on the
requesting user. The default context is `{"object": obj}`.

### Escape hatches

Each `get_*` method changes one thing for one report:

| Method | Default |
|---|---|
| `get_context(obj)` | `{"object": obj}` |
| `get_template_name()` | `template` |
| `get_filename(obj)` | `<name>-<pk>.pdf` |
| `get_renderer()` | the renderer `KARNI_REPORTS_RENDERER` names |
| `get_render_options()` | the page size and the renderer's identity |
| `get_queryset()` | `model._default_manager.all()`: the rows renders look up and pre-generation covers |
| `get_template_version()`, `get_data_version(obj, context)` | the two hashes of the cache key |
| `get_viewset()`, `get_object(request, id)` | the access check |

## Templates

A report's template usually extends `karni_reports/base.html`, the base
print template the module ships:

```html
{% extends "karni_reports/base.html" %}
{% block header %}{{ product.name }}{% endblock %}
{% block content %}
<h1>{{ product.name }}</h1>
<table>
  <thead><tr><th>Region</th><th>Price</th></tr></thead>
  <tbody>{% for price in prices %}<tr><td>{{ price.region }}</td><td>{{ price.amount }}</td></tr>{% endfor %}</tbody>
</table>
{% endblock %}
```

| Block | Default |
|---|---|
| `content` | the body (empty) |
| `header`, `footer` | repeated at the top and bottom of every page: the report's title, and nothing |
| `title` | the document title: the report's title |
| `styles` | extra CSS after the base rules |
| `page_margin` | `22mm 16mm 20mm 16mm` |
| `page_label` | `Page`, before the page number and count |

The template gets the context, plus `report` (the report), `object` (the
row) and `page_size` (`KARNI_REPORTS_PAGE_SIZE`). The context's keys win.

**Override the base template by its name.** A project's
`templates/karni_reports/base.html` replaces the shipped one for every
report: a letterhead, a font, other margins. The template version follows
the override, so every file renders again once.

**Images and stylesheets.** While rendering, WeasyPrint reads `data:` URLs
and the files under `STATIC_URL` (through the static files finders, then the
static files storage) and `MEDIA_URL` (the default storage), so
`<img src="{% static 'catalog/logo.png' %}">` works. Any other URL is left
out of the PDF with a [`REPORT009`](errors.md#report009) warning: a value in
a row can never make the server call another host. A subclass of
`karni_reports.rendering.WeasyPrintRenderer` with `allow_network = True`,
named in `KARNI_REPORTS_RENDERER`, lifts that.

## The cache key

A file is identified by:

- the report's name and the row (its model and id; ids are stored as text, so
  UUID and integer keys both work),
- the **template version**: a hash of the template's source, the source of
  every template it extends or includes by a constant name, and the render
  options (the page size and the renderer),
- the **data version**: a hash of what `get_context` returns, as canonical
  JSON. A model instance counts with every concrete field, `updated_at`
  included, so any saved change of the row counts. A queryset counts with
  its rows, and is evaluated once: the template reuses its rows.

A request whose key has a ready file gets that file without rendering. Put
the related rows the template prints in the context (`"category":
obj.category`): a related row that is only reached from the template does
not count. A value without a stable text (an object without `__str__`) is
refused with [`REPORT011`](errors.md#report011), since it would make every
request a miss.

After a render, the older files of the same report and row beyond
`KARNI_REPORTS_KEEP` (default 1) are deleted with their rows.

## The endpoints

| Method and path | Answer |
|---|---|
| `POST /api/reports/<report>/<id>/` | 200 with the status `ready` and `url` when a file is ready at the current key. Otherwise a render is queued and the answer is 202 with the status `pending` |
| `GET /api/reports/<report>/<id>/status/` | the status of the last request for this report and row: `none` (never requested), `pending`, `rendering`, `ready` or `failed` |
| `GET /api/reports/<report>/<id>/download/` | the PDF of the last request, once ready. Before that, 404 [`REPORT008`](errors.md#report008) |
| `GET /api/reports/` | the generated files, for roles granted `karni_reports.generatedreport:view` |

```json
{
  "id": "6f1c…",
  "report": "product-sheet",
  "object_id": "42",
  "status": "ready",
  "url": "/api/reports/product-sheet/42/download/",
  "size": 18234,
  "data_version": "9b2e…",
  "error": "",
  "requested_at": "2026-10-30T10:00:00Z",
  "rendered_at": "2026-10-30T10:00:02Z",
  "created_at": "2026-10-30T10:00:00Z"
}
```

**Access.** Each endpoint first retrieves the row through the viewset that
serves the report's model, with that viewset's own gate and read scope. The
caller gets what `GET /api/<resource>/<id>/` would answer them: 401 or 403
from the gate, and 404 for a row out of their scope, so another user's row
is a 404 (with `access = Access(read=Owned("owner"))`, only the owner and
the roles the declaration names get the file). The download makes the same
check itself. The file is streamed through the API, never handed out as a
public media URL, so a link alone opens nothing.

A failed render answers the status `failed` with a fixed sentence. The
exception stays in the admin. The next request queues the render again, and
so does one for a render stuck in `pending` or `rendering` for longer than
`KARNI_REPORTS_RENDER_TIMEOUT` seconds.

**Throttling.** Each endpoint is limited per caller: `60/hour` for requests
and downloads, `60/min` for status checks. Change a rate under its scope,
`reports.request_report`, `reports.report_status` or
`reports.download_report`, in `REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`.

## In React

`@karni/reports-ui` has a button and the hook behind it:

```tsx
import { ReportButton, useReport } from "@karni/reports-ui";

<ReportButton report="product-sheet" objectId={product.id} />;

const { status, isWorking, request, download } = useReport("product-sheet", product.id);
```

One click requests the report, says "Preparing PDF..." while it renders,
polls the status and downloads the file once it is ready. A failed render,
or a row the user may not see, shows "Try again". `labels`, `autoDownload`,
`pollInterval`, `onReady`, `onError` and `save` change each part. The
package README lists them.

## Pre-generation

Render ahead of requests, for example after an import or from a schedule:

```sh
manage.py karni_pregenerate product-sheet                 # every row
manage.py karni_pregenerate product-sheet --ids 12 40 41  # these rows
manage.py karni_pregenerate product-sheet --stale         # rows rendered before whose file is out of date
manage.py karni_pregenerate product-sheet --force         # render current files again too
manage.py karni_pregenerate --list                        # the registered reports
```

It works in batches of `--batch-size` rows (100 by default) in key order,
renders in its own process (no worker needed), skips a row whose file is
current (counted as cached), and prints the counts and the time of each
batch and of the run:

```text
batch 1: 100 rows, 97 rendered, 3 cached, 0 failed in 21.4s
batch 2: 52 rows, 50 rendered, 1 cached, 1 failed in 11.0s
product-sheet: 152 rows, 147 rendered, 4 cached, 1 failed in 32.4s
```

A failed row is counted, stored with its error and does not stop the run.

## The admin

**Generated reports** lists every file with its report, row, status, size,
data version and times. The status filter `failed` lists the renders that
failed with their error. **Regenerate selected reports** (for users with the
change permission) queues the selected rows to render again.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `KARNI_REPORTS_RENDERER` | `"weasyprint"` | `weasyprint`, `fake`, or the dotted path of a `karni_reports.rendering.Renderer` subclass ([`REPORT005`](errors.md#report005) when it cannot load) |
| `KARNI_REPORTS_STORAGE` | `"default"` | the `STORAGES` alias the files are saved to |
| `KARNI_REPORTS_DIRECTORY` | `"karni/reports"` | the folder inside that storage, one folder per report under it |
| `KARNI_REPORTS_PAGE_SIZE` | `"A4"` | the CSS page size of the base template: `A4`, `letter`, `A5 landscape`... |
| `KARNI_REPORTS_KEEP` | `1` | ready files kept per report and row, the newest first. `0` keeps every file |
| `KARNI_REPORTS_RENDER_TIMEOUT` | `600` | seconds after which a render still pending or rendering is queued again |

Each one is also read from the environment variable of the same name. In
karni.yaml they are the module's options without the prefix, lowercased:
`reports: {page_size: letter, keep: 3}`.

## Testing

```python
# tests/settings.py (or config/settings.py for the test run)
KARNI_REPORTS_RENDERER = "fake"
```

The fake renderer returns deterministic bytes that start with `%PDF` and
records the HTML of every render in `karni_reports.rendering.FakeRenderer.rendered`,
so a test reads what was printed. Renders are queued on commit: run them
with pytest-django's `django_capture_on_commit_callbacks(execute=True)` and
eager Celery, or call `karni_reports.services.render` directly.

```python
from karni_reports import get_report, services
from karni_reports.rendering import FakeRenderer


def test_the_sheet_prints_the_price(product, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        services.request(get_report("product-sheet"), product)
    assert "49.00" in FakeRenderer.rendered[-1]
```
