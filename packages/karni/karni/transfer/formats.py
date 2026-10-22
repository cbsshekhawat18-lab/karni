"""Reading and writing CSV and XLSX — the only two formats, in one place.

CSV is the stdlib; XLSX is ``openpyxl`` (a core dependency, imported lazily
so a CSV-only path never loads it). Cell values are normalised on the way in
(a spreadsheet's datetime becomes an ISO string, ``None`` becomes ``""``)
and on the way out (dates ISO, booleans ``true``/``false``, ``None`` empty),
so the importer and the exporter speak one vocabulary whatever the format.
"""

from __future__ import annotations

import csv
import datetime as dt
import decimal
import io
import uuid
from collections.abc import Iterable, Iterator, Sequence
from typing import IO, Any, Final

from karni.exceptions import KarniValueError

__all__ = [
    "CONTENT_TYPES",
    "FORMATS",
    "cell_text",
    "xlsx_cell",
    "csv_lines",
    "detect_format",
    "read_table",
    "xlsx_bytes",
]

FORMATS: Final[tuple[str, ...]] = ("csv", "xlsx")
CONTENT_TYPES: Final[dict[str, str]] = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_XLSX_TYPES: Final = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }
)


def detect_format(name: str | None, content_type: str | None = None, fmt: str | None = None) -> str:
    """``"csv"`` or ``"xlsx"`` from an explicit choice, the file name, or the content type."""
    if fmt:
        if fmt not in FORMATS:
            raise KarniValueError(
                f"Unsupported format {fmt!r}. Use one of {', '.join(FORMATS)}.", code="E802"
            )
        return fmt
    lowered = (name or "").lower()
    if lowered.endswith(".xlsx") or (content_type or "") in _XLSX_TYPES:
        return "xlsx"
    if lowered.endswith(".csv") or (content_type or "").startswith("text/"):
        return "csv"
    raise KarniValueError(
        f"Cannot tell the format of {name!r}: upload a .csv or .xlsx file.", code="E802"
    )


def cell_text(value: Any) -> Any:
    """A CSV/JSON-safe rendering of a value (``None`` → ``""``, dates ISO, bools lowercase)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple | set | frozenset):
        return "|".join(str(cell_text(item)) for item in value)
    if isinstance(value, dict):
        import json

        return json.dumps(value, sort_keys=True)
    name = getattr(value, "name", None)  # files
    if isinstance(name, str):
        return name
    return str(value)


def xlsx_cell(value: Any) -> Any:
    """A native spreadsheet cell: numbers, booleans and dates stay typed; the rest is text."""
    if value is None or isinstance(
        value, bool | int | float | str | dt.datetime | dt.date | dt.time
    ):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    return cell_text(value)


def _incoming(value: Any) -> Any:
    """Normalise a cell read from a file: ``None`` → ``""``, datetimes → ISO, keep the rest."""
    if value is None:
        return ""
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        return value.strip()
    return value


def _headers(row: Sequence[Any]) -> list[str]:
    return [str(_incoming(cell)) for cell in row]


def read_table(file: IO[Any], fmt: str) -> tuple[list[str], list[list[Any]]]:
    """``(headers, rows)`` of the first sheet; trailing empty rows and columns dropped."""
    if fmt == "xlsx":
        headers, rows = _read_xlsx(file)
    else:
        headers, rows = _read_csv(file)
    while headers and headers[-1] == "":
        headers.pop()
    width = len(headers)
    cleaned: list[list[Any]] = []
    for row in rows:
        cells = [_incoming(cell) for cell in row[:width]]
        cells.extend([""] * (width - len(cells)))
        if any(cell != "" for cell in cells):
            cleaned.append(cells)
    return headers, cleaned


def _read_csv(file: IO[Any]) -> tuple[list[str], list[list[Any]]]:
    raw = file.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
    reader = csv.reader(io.StringIO(text))
    try:
        headers = _headers(next(reader))
    except StopIteration:
        return [], []
    return headers, [list(row) for row in reader]


def _read_xlsx(file: IO[Any]) -> tuple[list[str], list[list[Any]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl is a core dependency
        raise KarniValueError(
            "Reading .xlsx needs openpyxl: pip install openpyxl", code="E802"
        ) from exc
    workbook = load_workbook(file, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        iterator = sheet.iter_rows(values_only=True)
        try:
            headers = _headers(next(iterator))
        except StopIteration:
            return [], []
        return headers, [list(row) for row in iterator]
    finally:
        workbook.close()


def csv_lines(rows: Iterable[Sequence[Any]]) -> Iterator[str]:
    """Each row as one CSV line (with its newline) — streamable."""
    for row in rows:
        buffer = io.StringIO()
        csv.writer(buffer).writerow([cell_text(cell) for cell in row])
        yield buffer.getvalue()


def xlsx_bytes(sheets: Sequence[tuple[str, Iterable[Sequence[Any]]]]) -> bytes:
    """A workbook with one sheet per ``(title, rows)``; the first row of each is bold."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:  # pragma: no cover - openpyxl is a core dependency
        raise KarniValueError(
            "Writing .xlsx needs openpyxl: pip install openpyxl", code="E802"
        ) from exc
    workbook = Workbook(write_only=True)
    for title, rows in sheets:
        sheet = workbook.create_sheet(title=title[:31] or "Sheet")
        for index, row in enumerate(rows):
            cells = [xlsx_cell(cell) for cell in row]
            if index == 0:
                from openpyxl.cell import WriteOnlyCell

                styled = []
                for cell in cells:
                    header = WriteOnlyCell(sheet, value=cell)
                    header.font = Font(bold=True)
                    styled.append(header)
                sheet.append(styled)
            else:
                sheet.append(cells)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
