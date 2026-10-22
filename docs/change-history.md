---
description: Field-level change history with karni.audit — opt a model in, every save and delete records who changed what from what to what, surfaced in the admin, the API and @karni/ui.
---

# Change history

`AuditedModel` records *who* last touched a row. `karni.audit` records *what
changed*: for a model that opts in, every create, update, delete and restore
leaves a `ChangeLog` row with the actor, the timestamp, the action and a diff
of the changed fields only. No project writes its own history table, signal
handlers or history screen (ADR 0002, P4).

## Opt in on the model

```python
class Price(BaseModel):
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    note = models.TextField(blank=True)
    api_token = models.CharField(max_length=64, blank=True)

    class Karni:
        audit = True                      # every field (or a list: ["amount", "currency"])
        sensitive = ["note"]              # recorded as changed, never its value
```

Logging every row of every table is a storage problem, so nothing is audited
until a model says so. `audit = True` covers every concrete field except the
primary key and the two timestamps that move on every save; a list names the
fields exactly. A name the model does not have is refused at boot (`E007`).

## What is captured, and where from

Capture happens at the model layer — a `pre_save` snapshot of the audited
columns, then `post_save` / `post_delete` — so a change made through the API,
the admin, a management command or the shell leaves the same entry. The
actor is the current user (`CurrentUserMiddleware` in a request,
`karni.middleware.current_user(user)` in tasks and commands, nobody in a bare
shell). The diff is `{field: [old, new]}` for changed fields only; a save
that changes nothing records nothing. Relations are recorded by primary key,
decimals and dates as strings, files by name. A soft delete is `delete`, an
undelete is `restore`, a hard delete is `delete` with every value → `null`.

**Redaction.** Fields named in `Karni.sensitive`, and any field whose name
contains `password`, `token`, `secret` or `key` (`KARNI_AUDIT_REDACT`), are
recorded as `["[redacted]", "[redacted]"]`: the entry says the field
changed, never what it was.

**Not captured, by design: `QuerySet.update()` and `bulk_update()`.** They
bypass Django's signals and leave no entry. `karni check` flags both on an
audited model (`audited-bulk-write`, rule `K113`); save the instances
instead, or opt out on the line with
`# karni: allow(audited-bulk-write): <reason>` when a backfill really needs
it. `raw()` and SQL-level writes are likewise invisible.

**Cost.** For an audited model a save costs one extra `SELECT` of the audited
columns before the write and one `INSERT` after it; the suite asserts the
overhead stays under 5 ms per save against an unaudited model on SQLite
(`tests/test_audit.py::test_capture_cost_per_save_is_small`; measured well
under 1 ms on the development machine). For a very wide model, or one saved
in tight loops, set `KARNI_AUDIT_ASYNC = True`: the entry is written by a
Celery task after the transaction commits, and history becomes eventually
consistent — an entry may lag the row by the queue's latency.

## Where it shows

- **Admin.** The History tab of an audited model's change page lists the
  field changes (date, user, action, each field's old → new) above Django's
  own admin-action log. The `Change log` admin lists every entry, read-only.
- **API.** `GET /api/<resource>/<id>/history/` on every `BaseViewSet`,
  paginated, newest first:

    ```json
    {"id": 12, "timestamp": "2026-10-19T10:00:00Z",
     "actor": {"id": "…", "email": "ada@example.com"}, "action": "update",
     "diff": {"amount": ["10.00", "12.50"]}, "fields_changed": ["amount"]}
    ```

    The row is looked up through the viewset's read scope, so an
    unreadable row is a 404; a model that does not opt in answers 404 saying
    so, and the OpenAPI document carries the operation only for audited
    resources.
- **`@karni/ui`.** `<ChangeHistory resource="prices" id={id} />` renders the
  list (`useChangeHistory(resource, id)` is the hook behind it).

**Visibility.** History respects [field-level visibility](api.md#field-visibility):
a field `Karni.field_roles` hides from a role is absent from every diff that
role sees, in the admin and the API alike.

## Retention

Nothing is pruned unless you ask: `KARNI_AUDIT_RETENTION_DAYS = 90` schedules
`karni.audit.tasks.prune_change_logs` daily (declared in
`karni/audit/schedules.py`; it is a no-op while the setting is `None`).
Projects with a legal retention requirement archive before pruning: the task
is a plain function — call `prune_change_logs(days=365)` from your own task
after exporting `ChangeLog.objects.filter(timestamp__lt=cutoff)` to cold
storage, or point `CELERY_BEAT_SCHEDULE["karni-prune-change-logs"]` at a
wrapper that does both.

Settings: `KARNI_AUDIT_ASYNC`, `KARNI_AUDIT_RETENTION_DAYS`,
`KARNI_AUDIT_REDACT` ([settings](settings.md)).

## Batches

An operation that changes many rows at once — an [import](import-export.md)
today — is recorded as one `ChangeBatch` (who, when, what kind, a label such
as the file name, and what it knew about itself in `meta`), and every entry
written while it ran points at it through `ChangeLog.batch`, so "which rows
did this import touch" and "which import changed this row" are one query
each. In code, `with karni.audit.capture.change_batch("import", label) as
batch:` groups whatever the block records; the history endpoint and
`<ChangeHistory/>` carry the batch id on each entry.

## Request ids

Every entry and batch records the id of the request (or Celery task) that
made it, `request_id` — the `X-Request-ID` of the response
([request ids](debugging/capture.md#request-ids)). `karni trace <id>` lists
a request's changes among its tasks, email and webhooks;
`ChangeLog.objects.filter(request_id=...)` is the same in code, and the
admin's *Change log* searches by it. A change made in a shell has none
(`""`) unless the block runs under `karni.tracing.bound_request_id()`.
