---
description: Import and export for master data — CSV and XLSX from any list, and an upload with a mandatory dry run, permission-aware throughout.
---

# Import and export

Master data starts life in somebody's spreadsheet, so every project asks for
the same two things: a download of what a screen shows, and an upload that
creates or updates rows from a file. Karni ships both, generic, on every
resource — a new model gets them without a line of project code — and
permission-aware throughout. An export that ignored permissions would be a
data leak with a friendly button on it.

## Export

`GET /<resource>/export/?format=csv|xlsx` on every `BaseViewSet` answers with
a file of **the list as this request would see it**: the same filters,
`?search=` and `?ordering=` the list takes, the same row scope
([row-level scoping](api.md#access-control)), and the columns the requester
may read ([field visibility](api.md#field-visibility)); write-only fields
never export. Relations are written as the target's
[natural key](#natural-keys) when it has one (`venue` → `Arena`), else the
primary key, and to-many relations join their values with `|` — so the file
imports back. Only a related row the requester may read is named: one outside
the target's read scope keeps its primary key (what the API shows for it),
and an unreadable member of a to-many relation is left out.

In the admin, every changelist has **Export selected as CSV / XLSX** actions
(the selection, or every filtered row with "select all"), through the same
scope and visibility; there, related rows are named as far as the admin's
row scope (the user's `view` grants) shows them. In `@karni/ui`, `<ResourceTable>` shows **Export CSV /
XLSX** buttons whenever the resource serves the route (`exportFormats={false}`
hides them); each downloads the table's current query.

`KARNI_EXPORT_MAX_ROWS` (100 000) caps an export: beyond it the answer is a
400 with code `E803` — narrow the filters. CSV streams; XLSX is built in
memory.

## Import

Importing is four steps, and the third is not optional:

1. **Upload** a CSV or XLSX file (`POST /<resource>/import/`, multipart
   `file`). Karni reads the headers and the row count and answers with a job.
2. **Map** columns to fields. The mapping is suggested from the headers (by
   field name or label, case and punctuation aside) and **remembered per
   model per user**, so the second import of the same spreadsheet is one
   click. Only fields the role may write are offered; a mapping to anything
   else is refused (`E801`).
3. **Preview** (`POST …/import/<job>/preview/` with `{"mapping": …}`) — the
   mandatory dry run. Every row goes through the resource's generated
   serializer, exactly as a `POST` would: types, choices, relation lookup by
   natural key, uniqueness, `Model.clean()`. The run happens inside a
   transaction that is rolled back, so the preview's numbers — N created, N
   updated, N skipped, with each row's errors and its line number — are what
   the commit will do, database constraints included.
4. **Commit** (`POST …/import/<job>/commit/`), only after a preview and only
   with the previewed mapping (changing it sends the job back to step 2). One
   transaction; rows with errors are skipped and listed, the rest go in; the
   whole import is recorded by [`karni.audit`](change-history.md) as **one
   batch** linked to every row it created or changed.

`GET /<resource>/import/` describes the importable fields (kind, required,
choices, the relation's target and lookup field, which column is the key) and
the remembered mapping; `GET …/import/<job>/` is the job's state and progress;
`GET /<resource>/import/template/?format=xlsx|csv` is a downloadable
**template**: the right headers, one example row and — on a second sheet —
every allowed value of every choice field, which removes most support
questions before they are asked.

A row is an **update** when its key column matches an existing row the user
may change, else a **create**. The key is `Karni.import_key`, else the
model's natural key, else the `id` column when the file has one (an export
re-imports as updates). Blank cells leave a field unchanged (or at its
default on create). Rows whose update changes nothing count as *unchanged*
and are skipped.

### Small and large files

A file with at most `KARNI_IMPORT_INLINE_ROWS` (500) rows previews and
commits inside the request. A larger one runs in Celery: the job answers
`previewing` / `committing` with `rows_done` climbing, and the UI polls it.
`KARNI_IMPORT_MAX_ROWS` (100 000) refuses an upload outright (`E803`).
Uploads live in the default storage, so a worker on another machine reads the
same file.

### Permissions

- **The gate** is the resource's `access` declaration: whoever may `create`
  **or** `write` may start an import (`BaseViewSet.write_or_create_actions`).
  A model without a routed viewset is gated by the roles' grants (`add` /
  `change`) — that is the admin's path.
- **Per row**, creating needs the `create` gate and the new row must lie
  inside that predicate's scope — a branch manager cannot import rows into
  another branch; updating needs the `write` gate, and the existing row is
  looked up through the write scope, so a row that exists elsewhere is "not
  in your scope", never silently overwritten.
- **Fields** the role may not write are not importable; the serializer
  refuses them naming the roles that may ([field visibility](api.md#field-visibility)).
- **Relations** are resolved by natural key (or id) among the rows the user
  may read; an unreadable target reads as "no venue with name 'X' (or it is
  not visible to you)".
- **Owner fields** (`Owned("organizer")`, `Karni.owner_field` under
  `Granted()`) are stamped from the importer, never read from the file.

### Natural keys

`class Karni: natural_key = "sku"` says how people — and files — name a row
of a model: it is what exports write for a relation and what imports look
up. Undeclared, it is the model's first unique slug/char/email field
(`slug`, `email`); a model with neither uses its primary key.

### Hooks

What generic code cannot know is declared in `class Karni`, never by
subclassing:

```python
class Order(BaseModel):
    class Karni:
        natural_key = "number"                    # how files name an order
        import_key = "number"                     # the column that matches existing rows
        import_lookup = {"customer": "email"}     # a relation column carries this target field
        import_transform = "shop.imports.clean_order_row"   # fn(row: dict) -> dict, before validation
        after_import = "shop.imports.reindex"               # fn(result), after a commit
```

`import_transform` receives each row's mapped values (blank cells already
dropped) and returns the values to validate; `after_import` receives the
`ImportResult` (counts and the pks it touched) once a commit succeeds — never
after a preview.

### In code

`karni.transfer.imports.Importer(model, request)` is the whole thing:
`importable()`, `suggest_mapping(headers)`, `validate_mapping(...)` and
`run(headers, rows, mapping, dry_run=True)`. `karni.transfer.services`
(`create_job`, `set_mapping`, `start_stage`, `run_stage`, `job_state`) is
what the API, the admin page and the Celery task share;
`karni.transfer.exports.export_response` and
`karni.transfer.template.template_response` are the downloads.

## In the admin

Every Karni admin changelist has **Import** (django-unfold button; plain
admins reach `…/<model>/import/`): upload, map, preview, commit on one page,
with progress for large files and the same template download. The
`ImportJob` admin lists every import with its counts and problems. An admin
class opts out with `karni_transfer = False`.

## In `@karni/ui`

```tsx
<ResourceTable resource="orders" />                 {/* Export CSV / XLSX buttons */}
<ResourceImport resource="orders" onDone={() => navigate("/orders")} />
```

`<ResourceImport>` is the four steps as a component; `useImportDescribe`,
`useImportJob` (polling while the backend works) and `useImportActions`
(`upload`, `preview`, `commit`) are the hooks behind it;
`downloadResourceExport(client, resource, params, format)` and
`downloadImportTemplate(client, resource, format)` are the downloads. See
[@karni/ui](ui.md).

## Settings

| setting | default | does |
|---|---|---|
| `KARNI_IMPORT_INLINE_ROWS` | 500 | files with at most this many rows import inside the request; larger ones run in Celery with progress |
| `KARNI_IMPORT_MAX_ROWS` | 100 000 | an upload beyond this is refused (`E803`) |
| `KARNI_EXPORT_MAX_ROWS` | 100 000 | an export beyond this is refused (`E803`) |

XLSX needs `openpyxl`, a core dependency. Errors: `E801` (an import cannot
proceed as asked), `E802` (not a CSV or XLSX), `E803` (too many rows).
