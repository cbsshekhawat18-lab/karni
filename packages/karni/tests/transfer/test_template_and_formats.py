"""The downloadable template, and the two file formats round-tripping."""

from __future__ import annotations

import datetime as dt
import decimal
import io
from typing import Any

import pytest

from karni.transfer.formats import cell_text, csv_lines, detect_format, read_table, xlsx_bytes
from karni.transfer.imports import Importer
from karni.transfer.template import template_rows
from tests.testapp.models import Event
from tests.transfer.conftest import EventViewSet, api_request, call

pytestmark = pytest.mark.django_db


def test_formats_round_trip() -> None:
    rows: list[list[Any]] = [
        ["name", "when", "n", "ok"],
        ["Arena", dt.datetime(2026, 1, 2, 3, 4), decimal.Decimal("1.50"), True],
        ["", None, 2, False],
    ]
    headers, back = read_table(io.StringIO("".join(csv_lines(rows))), "csv")
    assert headers == ["name", "when", "n", "ok"]
    assert back == [["Arena", "2026-01-02T03:04:00", "1.50", "true"], ["", "", "2", "false"]]
    headers, back = read_table(io.BytesIO(xlsx_bytes([("Data", rows)])), "xlsx")
    assert headers == ["name", "when", "n", "ok"]
    assert back[0] == ["Arena", "2026-01-02T03:04:00", 1.5, True] and back[1][2] == 2
    assert detect_format("x.XLSX") == "xlsx" and detect_format("x.csv") == "csv"
    assert detect_format(None, "text/csv") == "csv"
    assert cell_text(["a", "b"]) == "a|b" and cell_text({"k": 1}) == '{"k": 1}'


def test_the_template_has_headers_an_example_and_allowed_values(make_user: Any) -> None:
    staff = make_user("staff@example.com", "staff")
    importer = Importer(Event, api_request("get", "/events/import/template/", staff))
    data, allowed = template_rows(importer.importable())
    headers, example = data
    assert "title" in headers and "venue" in headers and "status" not in headers  # read-only
    assert "organizer" not in headers  # the owner is stamped, never imported
    assert (
        example[headers.index("title")] == "Title"
        and example[headers.index("venue")] == "<name of a testapp.venue>"
    )
    assert ["is_public", "true", "yes"] in allowed
    assert ["venue", "<name>", "the name of a testapp.venue"] in allowed

    response = call(
        EventViewSet,
        {"get": "import_template"},
        api_request("get", "/events/import/template/", staff),
    )
    assert response.status_code == 200 and "events-template.xlsx" in response["Content-Disposition"]
    sheets_headers, _rows = read_table(io.BytesIO(response.content), "xlsx")
    assert sheets_headers == headers
    csv_response = call(
        EventViewSet,
        {"get": "import_template"},
        api_request("get", "/events/import/template/", staff, {"format": "csv"}),
    )
    assert csv_response.content.decode().splitlines()[0] == ",".join(headers)
