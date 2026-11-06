---
description: Import and export for master data. CSV and XLSX from any list, and an upload with a mandatory dry run, permission-aware throughout.
---

# Import and export

Master data starts life in somebody's spreadsheet, so every project asks for
the same two things: a download of what a screen shows, and an upload that
creates or updates rows from a file. Karni ships both, generic, on every
resource. A new model gets them without a line of project code, and both are
permission-aware throughout. An export that ignored permissions would be a
data leak with a friendly button on it.

## Export

`GET /<resource>/export/?format=csv|xlsx` on every `BaseViewSet` answers with
a file of **the list as this request would see it**. It uses the same filters,
`?search=` and `?ordering=` the list takes, the same row scope
([row-level scoping](api.md#access-control)), and the columns the requester
may read ([field visibility](api.md#field-visibility)). Write-only fields
never export. Relations are written as the target's
[natural key](#natural-keys) when it has one (`venue` → `Arena`), else the
primary key, and to-many relations join their values with `|`. That way the
file imports back. Only a related row the requester may read is named. One
outside the target's read scope keeps its primary key (what the API shows for
it), and an unreadable member of a to-many relation is left out.

In the admin, every changelist has **Export selected as CSV / XLSX** actions
(the selection, or every filtered row with "select all"), through the same
scope and visibility. There, related rows are named as far as the admin's
row scope (the user's `view` grants) shows them. In `@karni/ui`, `<ResourceTable>` shows **Export CSV /
XLSX** buttons whenever the resource serves the route (`exportFormats={false}`
hides them). Each one downloads the table's current query.

`KARNI_EXPORT_MAX_ROWS` (100 000) caps an export. Beyond it the answer is a
400 with code `E803`, so narrow the filters. CSV streams, and XLSX is built in
memory.

## Import

Importing is four steps, and the third is not optional:

1. **Upload** a CSV or XLSX file (`POST /<resource>/import/`, multipart
   `file`). Karni reads the headers and the row count and answers with a job.
2. **Map** columns to fields. The mapping is suggested from the headers (by
   field name or label, case and punctuation aside) and **remembered per
   model per user**, so the second import of the same spreadsheet is one
   click. A column the remembered mapping does not name is still suggested
   by its header, a to-many column such as `tags` too, and a column the
   user left out last time stays out. Only fields the role may write are
   offered. A mapping to anything else is refused (`E801`).
3. **Preview** (`POST …/import/<job>/preview/` with `{"mapping": …}`). This is
   the mandatory dry run. Every row goes through the resource's generated
   serializer, exactly as a `POST` would: types, choices, relation lookup by
   natural key, uniqueness, `Model.clean()`. The run happens inside a
   transaction that is rolled back. So the preview's numbers (N created, N
   updated, N skipped, with each row's errors and its line number) are what
   the commit will do, database constraints included.
4. **Commit** (`POST …/import/<job>/commit/`), only after a preview and only
   with the previewed mapping (changing it sends the job back to step 2). It
   runs in one transaction. Rows with errors are skipped and listed, and the
   rest go in. [`karni.audit`](change-history.md) records the whole import as
   **one batch** linked to every row it created or changed.

`GET /<resource>/import/` describes the importable fields (kind, required,
choices, the relation's target and lookup field, which column is the key) and
the remembered mapping. `GET …/import/<job>/` is the job's state and progress.
`GET /<resource>/import/template/?format=xlsx|csv` is a downloadable
**template**. It has the right headers, one example row and, on a second
sheet, every allowed value of every choice field. That removes most support
questions before they are asked.

A row is an **update** when its key column matches an existing row the user
may change, else a **create**. The key is `Karni.import_key`, else the
model's [natural key](#natural-keys). The `id` column matches existing rows
only when the import asks for it (see [ids](#ids)), so an export of a model
with a natural key re-imports as updates and one without creates new rows
unless you turn `match_ids` on. Blank cells leave a field unchanged (or at
its default on create). Rows whose update changes nothing count as
*unchanged* and are skipped.

### Ids

!!! warning "Experimental"
    The `match_ids` and `keep_ids` options are
    [experimental](stability.md#experimental-names).

An import has two id options, both off by default. Send them with the
preview (`POST …/import/<job>/preview/` with `{"mapping": …, "match_ids":
true}`) or tick them on the admin's map step. The job remembers them for the
commit, and changing one sends the job back to the preview.

- **`match_ids`**: a row whose key is blank or matches nothing is matched to
  an existing row by its `id` column. Off, the `id` column never matches, so
  a file exported from one environment (staging) cannot update unrelated
  rows that happen to have the same ids in another (production). A model
  without a natural key needs it to re-import an export as updates.
- **`keep_ids`**: a created row keeps the id its row gives, for legacy data
  whose ids other systems already use. Afterwards the database sequence
  moves past the largest id (PostgreSQL's `setval`; SQLite needs nothing),
  so the next row created without an id gets a fresh one. Only a role that
  may create rows anywhere may keep ids: inserting a chosen id fails when any
  row has it, which would tell a scoped user which ids exist outside their
  scope (`E801` otherwise).

With `match_ids`, an id that matches nothing in your write scope is refused,
whether the row does not exist or belongs to someone else. The message is
the same "not found or not in your scope" for both, and for a natural key
held by a row outside your scope, so a preview never confirms that a row
exists. Leave the id empty to create the row with a new id, or turn
`keep_ids` on as well to create it with that id.

`karni load` always matches rows by their key and, for a model keyed by its
id, creates them with the ids the file gives, then moves the sequence on
([loading content](content-loading.md)).

### Small and large files

A file with at most `KARNI_IMPORT_INLINE_ROWS` (500) rows previews and
commits inside the request. A larger one runs in Celery. The job answers
`previewing` / `committing` with `rows_done` climbing, and the UI polls it.
`KARNI_IMPORT_MAX_ROWS` (100 000) refuses an upload outright (`E803`).
Uploads live in the default storage, so a worker on another machine reads the
same file.

### Permissions

- **The gate** is the resource's `access` declaration. Whoever may `create`
  **or** `write` may start an import (`BaseViewSet.write_or_create_actions`).
  A model without a routed viewset is gated by the roles' grants (`add` /
  `change`). That is the admin's path.
- **Per row**, creating needs the `create` gate, and the new row must lie
  inside that predicate's scope. A branch manager cannot import rows into
  another branch. Updating needs the `write` gate, and the existing row is
  looked up through the write scope. So a row that exists elsewhere is "not
  found or not in your scope", never silently overwritten.
- **Fields** the role may not write are not importable. The serializer
  refuses them and names the roles that may ([field visibility](api.md#field-visibility)).
- **Relations** are resolved among the rows the user may read: by the
  target's natural key when it has one, else by its id. An unreadable target
  reads as "no venue with name 'X' (or it is not visible to you)".
- **Owner fields** (`Owned("organizer")`, `Karni.owner_field` under
  `Granted()`) are stamped from the importer, never read from the file.

### Natural keys

`class Karni: natural_key = "sku"` says how people (and files) name a row
of a model. It is what exports write for a relation and what imports look
up. If it is not declared, it is the model's first unique slug/char/email field
(`slug`, `email`). A model with neither uses its primary key.

A relation cell is matched against the natural key alone, never also
against the primary key. A numeric natural key (a year, a part number such
as `2024`) is therefore never read as an id: on [integer keys](models.md#choosing-the-key-type)
part number `"7"` and the part with id 7 are different rows. To let a
column carry ids instead, say so: `import_lookup = {"part": "id"}`.

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
dropped) and returns the values to validate. `after_import` receives the
`ImportResult` (counts and the pks it touched) once a commit succeeds, and
never after a preview.

### In code

`karni.transfer.imports.Importer(model, request)` is the whole thing:
`importable()`, `suggest_mapping(headers)`, `validate_mapping(...)` and
`run(headers, rows, mapping, dry_run=True)`. The API, the admin page and the
Celery task share `karni.transfer.services`
(`create_job`, `set_mapping`, `start_stage`, `run_stage`, `job_state`).
`karni.transfer.exports.export_response` and
`karni.transfer.template.template_response` are the downloads.

### Content files

An upload is for a person bringing a spreadsheet. A project's own content
(the copy, images and children a site is made of) lives in a JSON or YAML
file in the repository instead, and `karni load` loads it with the same row
logic: the same keys, natural-key relations, serializer and hooks. See
[Loading content](content-loading.md).

## In the admin

Every Karni admin changelist has **Import**: a button under django-unfold, or
`…/<model>/import/` for plain admins. It does upload, map, preview and commit
on one page, with progress for large files and the same template download. The
`ImportJob` admin lists every import with its counts and problems. An admin
class opts out with `karni_transfer = False`.

## In `@karni/ui`

```tsx
<ResourceTable resource="orders" />                 {/* Export CSV / XLSX buttons */}
<ResourceImport resource="orders" onDone={() => navigate("/orders")} />
```

`<ResourceImport>` is the four steps as a component. `useImportDescribe`,
`useImportJob` (polling while the backend works) and `useImportActions`
(`upload`, `preview`, `commit`) are the hooks behind it.
`downloadResourceExport(client, resource, params, format)` and
`downloadImportTemplate(client, resource, format)` are the downloads. See
[@karni/ui](ui.md).

## Settings

| setting | default | does |
|---|---|---|
| `KARNI_IMPORT_INLINE_ROWS` | 500 | files with at most this many rows import inside the request, and larger ones run in Celery with progress |
| `KARNI_IMPORT_MAX_ROWS` | 100 000 | an upload beyond this is refused (`E803`) |
| `KARNI_EXPORT_MAX_ROWS` | 100 000 | an export beyond this is refused (`E803`) |

XLSX needs `openpyxl`, a core dependency. Errors: `E801` (an import cannot
proceed as asked), `E802` (not a CSV or XLSX), `E803` (too many rows).
