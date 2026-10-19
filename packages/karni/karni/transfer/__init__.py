"""Import and export for master data (ADR 0002, P6).

Master data starts life in somebody's spreadsheet, so every project asks for
the same two things: a download of what a screen shows, and an upload that
creates or updates rows from a file. Both are generic here and permission-
aware throughout — an export that ignored permissions would be a data leak
with a friendly button on it.

* **Export** (:mod:`karni.transfer.exports`): CSV or XLSX from any
  ``BaseViewSet`` (``GET /<resource>/export/?format=xlsx``, honouring the
  request's filters, search and ordering) or admin changelist (the *Export
  selected* actions). Rows come from the read scope (P2), columns from the
  fields the role may see (P3); relations are written as the target's
  ``Karni.natural_key`` so the file imports back.
* **Import** (:mod:`karni.transfer.imports`, :mod:`karni.transfer.services`)
  with a mandatory dry run: upload, map columns to fields (the mapping is
  remembered per model per user), preview — every row validated through the
  generated serializer (types, choices, relation lookup by natural key,
  uniqueness, ``clean()``), N created / updated / skipped with per-row
  errors — then commit in one transaction, recorded by ``karni.audit`` as
  one batch linked to every row it touched. Small files run inline, large
  ones in Celery with progress (``KARNI_IMPORT_INLINE_ROWS`` decides).
  Importing needs the add / change grants, respects the row scope (no
  importing into another branch) and refuses fields the role may not write.
* **Hooks** in ``class Karni`` (:func:`karni.meta.import_options`):
  ``natural_key``, ``import_key``, ``import_lookup``, ``import_transform``,
  ``after_import`` — declared, never subclassed.
* **Templates** (:mod:`karni.transfer.template`): a downloadable file per
  model with the right headers, one example row and every choice field's
  allowed values.

Settings: ``KARNI_IMPORT_INLINE_ROWS``, ``KARNI_IMPORT_MAX_ROWS``,
``KARNI_EXPORT_MAX_ROWS``. XLSX needs ``openpyxl`` (a core dependency).
"""

from __future__ import annotations
