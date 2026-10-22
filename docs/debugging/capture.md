---
description: One request id across requests, Celery tasks, email, webhooks and the change log, and the development-only capture under .karni/ that karni trace, karni replay and karni explain --failure read — with the redaction rules and limits.
---

# Request ids and the development capture

Debugging with an agent is cheap when the context is already written down
and expensive when the agent has to rebuild it from logs and code. Karni
writes it down for you in development, with no configuration: one id per
request that follows the work everywhere, and a capture of every request
and every crash under `.karni/` in the project. `karni trace`,
`karni replay` and `karni explain --failure` read it
([trace and replay](trace-and-replay.md)).

This is a debugging layer, not monitoring: it runs only with `DEBUG` on,
writes plain files, needs no service, and keeps a bounded amount.

## Request ids

Every request gets an id from `karni.tracing.RequestIdMiddleware` (first in
Karni's `MIDDLEWARE`). The id travels with everything the request causes:

| Where | How it gets there |
|---|---|
| Logs | bound into structlog's context; django-structlog's `RequestMiddleware` logs the same id |
| The response | `X-Request-ID: <id>` header — what you hand to `karni trace` |
| Celery tasks enqueued during the request | a `karni_request_id` message header (`before_task_publish`), restored in the worker (`task_prerun`) |
| Their retries | a retry is published from inside the running task, so it carries the same id, minutes later too |
| A task with no id (beat, a shell) | gets a fresh one, so its own email and changes still correlate |
| Email | `X-Karni-Request-ID` on every `EmailMessage.send()` (`send_mail`, account emails, …) |
| Outgoing HTTP (a webhook you send) | `karni.tracing.outgoing_headers()` gives `{"X-Request-ID": id}` for your call |
| Incoming webhooks | a delivery is a new request with its own id; the payments module links it to the checkout it settles (see [linking](#linking-requests)) |
| Change history | `ChangeLog.request_id` and `ChangeBatch.request_id`; search by it in the admin's *Change log* |

```python
import requests
from karni.debug import trace_event
from karni.tracing import outgoing_headers

response = requests.post(url, json=payload, headers={**outgoing_headers()}, timeout=10)
trace_event("webhook.sent", url=url, status=response.status_code)
```

Outside a request, `with karni.tracing.bound_request_id() as rid:` gives a
management command or a script an id of its own.

**Which id is used.** A client's `X-Request-ID` is accepted only when it
can be trusted: always in development (`DEBUG` on), and with `DEBUG` off
only when `KARNI_REQUEST_ID_TRUST_HEADER = True` *and* `NUM_PROXIES` is not
`0` — the same trust model as `X-Forwarded-For` ([security](../security.md)):
turn it on only when the proxy in front overwrites the header on every
request (in Caddy: `header_up X-Request-ID {http.request.uuid}` inside
`reverse_proxy`). Otherwise the id is a fresh UUID and the client's value is
replaced, so nobody can write ids into your production logs. Ids are 1–128
letters, digits, `_` and `-` (they name files); anything else is replaced
even in development. `karni.W920` warns when `RequestIdMiddleware` comes
after django-structlog's middleware.

## What `.karni/` holds

With `DEBUG` on, under the project root (`BASE_DIR`, else the directory
above the settings package):

```
.karni/requests/<request_id>.json   every request (static files and CORS preflights excepted)
.karni/failures/<failure_id>.json   every unhandled exception, in a request or a Celery task
.karni/trace/<YYYY-MM-DD>.jsonl     one event per line, each with its request id
```

The rest of `.karni/` (`config.toml`, `modules/`) is project configuration
and stays committed; the three capture directories each carry their own
`.gitignore`, and the scaffold's `.gitignore` and `.dockerignore` list them.

### The request record

A contract other tools read (version 1, exactly these keys):

```json
{"version": 1, "request_id": "5f0c2e9a-…", "at": "2026-10-21T10:14:03.512+00:00",
 "method": "POST", "path": "/api/bookings/3/pay/", "query": {"expand": ["tier"]},
 "headers": {"Authorization": "Bearer [redacted]", "Content-Type": "application/json"},
 "body": {"note": "window seat"}, "content_type": "application/json",
 "user": {"id": "7", "email": "ada@example.com", "username": null,
          "is_staff": false, "is_superuser": false},
 "view": "events.viewsets.BookingViewSet", "resource": "booking", "action": "pay",
 "view_kwargs": {"pk": "3"}, "status": 403, "duration_ms": 18.4,
 "error_code": "permission_denied", "failure_id": null}
```

`view` is the dotted path of the view (the viewset for a DRF viewset; `""`
when no URL matched), `resource` the router basename, `action` the DRF
action. `body` is the parsed JSON, a form as `{field: value}` (an upload as
`"<file name.pdf, 1234 bytes>"`), a short note for a body that is not
captured (another content type, over 64 KiB), or `null`. `error_code` is the
Karni code the response carries (`E801`), else DRF's error code
(`permission_denied`, `not_authenticated`, `not_found`, `invalid`), else
`null`. `failure_id` names the failure snapshot when the request raised.

### The failure snapshot

Written on an unhandled exception (`got_request_exception`, and
`task_failure` for a Celery task that failed for good). It holds what an
agent would otherwise reconstruct:

- the request (method, path, query, headers, body) or the task (name, id,
  retries, its arguments by parameter name);
- the resolved view, viewset, router basename, action and serializer class;
- the user with their roles and their grants on the resource's model;
- the SQL the request ran, with timings, and the repeated statements grouped
  (statement text with placeholders — parameters are never recorded);
- the exception, its chain, a Karni code when it has one, and the full
  traceback, outermost first; frames of the project and of Karni (and its
  modules) carry their local variables, rendered safely (no query runs, a
  queryset is not evaluated, a model instance shows its fields) and
  truncated; library and standard-library frames do not;
- `origin`: the frame it failed in — the innermost project frame, else the
  innermost Karni frame;
- the relevant settings: `DEBUG`, each database's engine, name, host and
  port (never a password), the project's own apps, every `KARNI_*` setting;
  and the Python, Django, DRF and Karni versions.

### The trace

One JSON object per line: `v`, `at` (UTC), `request_id`, `event`, `pid`,
the event's fields, and optionally `refs`. Events Karni writes:

| Event | Fields |
|---|---|
| `request.start` / `request.end` | method, path; end: status, duration_ms, view, user, error_code, failure_id |
| `task.enqueued` | task, task_id, retries, eta, queue |
| `task.started` | task, task_id, retries, eager |
| `task.retried` | task, task_id, retries, reason |
| `task.succeeded` / `task.failed` | task, task_id, duration_ms; failed: exception, message, failure_id |
| `email.sent` | to, cc and bcc counts, subject, sent |
| `audit.batch` | batch_id, kind, label |
| `webhook.received` / `webhook.matched` (karni-payments) | provider, event_id, event_type; refs |
| `payment.checkout` (karni-payments) | provider, amount, currency; refs |

Your code adds its own with `karni.debug.trace_event("name", field=value,
refs=[...])` — a no-op with `DEBUG` off.

### Linking requests

A ref names a row: `karni_payments.Payment:<pk>`. Two requests whose events
share a ref are linked in `karni trace`: the checkout that created a payment
and the webhook delivery, minutes later, that settled it.

## Redaction

Everything under `.karni/` passes the same rules as the
[change history](../change-history.md#what-is-captured-and-where-from):

- **By name.** A key, form field, query parameter, header, setting or local
  variable whose name contains one of `KARNI_AUDIT_REDACT` (`password`,
  `token`, `secret`, `key` by default), or that a model lists in
  `Karni.sensitive`, is recorded as `"[redacted]"` — nested bodies included.
- **Credential headers.** `Authorization` (the scheme is kept:
  `Bearer [redacted]`), `Proxy-Authorization`, `Cookie` (cookie names kept),
  `Set-Cookie`, `X-CSRFToken`.
- **By value.** `SECRET_KEY` and its fallbacks, every string setting with a
  sensitive name, database and broker passwords, and — for the request being
  captured — every value redacted by name (the password in the body, the
  bearer token, the cookie values) are known secrets: a string equal to one
  is replaced, and a longer string containing one has it cut out, wherever it
  appears (a local under an innocent name, an exception message, SQL text).

`tests/test_debug.py::test_no_secret_reaches_the_capture_directory` sends
passwords (JSON, form and multipart bodies), a token in the query, a real
bearer token, a session cookie, a CSRF header, a `Karni.sensitive` value and
a pattern-named field, crashes with all of them and `SECRET_KEY` in the
locals and the exception message, and asserts none of their bytes appear in
any file under `.karni/`.

## Limits and switches

| Setting | Default | What it does |
|---|---|---|
| `KARNI_DEBUG_CAPTURE` | `True` | `False` turns the capture off; with `DEBUG` off it never runs |
| `KARNI_DEBUG_CAPTURE_KEEP` | `200` | request records kept, and failure snapshots kept (the oldest go first) |
| `KARNI_DEBUG_TRACE_DAYS` | `7` | days of trace files kept |
| `KARNI_REQUEST_ID_TRUST_HEADER` | `False` | accept a proxy's `X-Request-ID` with `DEBUG` off |
| `KARNI_REQUEST_ID_EMAILS` | `True` | stamp `X-Karni-Request-ID` on outgoing email |

**Inert in production.** With `DEBUG` off, `CaptureMiddleware` raises
`MiddlewareNotUsed` when Django builds the handler, so it is not in the
chain at all, and `trace_event` returns before touching the disk;
`tests/test_debug.py::test_capture_is_inert_when_debug_is_off` makes
requests, crashes and traces with `DEBUG` off and asserts `.karni/` was
never created.

**Escape hatches.** Subclass `karni.debug.middleware.CaptureMiddleware` and
override `should_capture(request)` or `max_body_bytes`; remove
`RequestIdMiddleware` or `CaptureMiddleware` from `MIDDLEWARE`.
