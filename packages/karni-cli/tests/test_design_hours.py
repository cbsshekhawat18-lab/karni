"""Opening hours in a design's markup: the clear cases, in several languages, and what is not."""

from __future__ import annotations

import pytest

from karni_cli.design import hours
from karni_cli.design.parse import parse


@pytest.mark.parametrize(
    ("line", "days", "times"),
    [
        ("Mon–Fri 8:00–18:00", "Mon–Fri", "8:00–18:00"),
        ("Monday to Friday: 9am - 5.30pm", "Monday to Friday", "9am - 5.30pm"),
        ("Sat, Sun closed", "Sat, Sun", "closed"),
        ("Mon - Fri 9:00–12:00, 14:00–18:00", "Mon - Fri", "9:00–12:00, 14:00–18:00"),
        ("Mo–Fr 8–18 Uhr", "Mo–Fr", "8–18 Uhr"),
        ("Sa, So geschlossen", "Sa, So", "geschlossen"),
        ("Lundi au vendredi 9h00 - 18h00", "Lundi au vendredi", "9h00 - 18h00"),
        ("Lunes a viernes 9:00 - 14:00", "Lunes a viernes", "9:00 - 14:00"),
        ("Domenica chiuso", "Domenica", "chiuso"),
        ("Daily 7:00 to 15:00", "Daily", "7:00 to 15:00"),
    ],
)
def test_a_line_of_days_and_times(line: str, days: str, times: str) -> None:
    assert hours.read_line(line) == (days, times)


@pytest.mark.parametrize(
    "line",
    ["Call us on 0123 456 789", "Open since 2001", "Saturday market", "Sunday", "9:00 to 17:00"],
)
def test_a_line_that_is_not_opening_hours(line: str) -> None:
    assert hours.read_line(line) is None


def _find(markup: str) -> hours.HoursList | None:
    document = parse(markup)
    node = next(iter(document.root.elements()))
    return hours.find(node, markup)


def test_the_clear_cases_and_the_same_hours_in_two_formats() -> None:
    table = _find(
        "<table><tr><th>Monday to Friday</th><td>8:00 to 18:00</td></tr>"
        "<tr><th>Sunday</th><td>Closed</td></tr></table>"
    )
    lines = _find("<p>Mon&ndash;Fri 8&ndash;18<br>Sun closed</p>")
    items = _find("<ul><li>Mon–Fri 8am–6pm</li><li>Sun closed</li></ul>")
    terms = _find("<dl><dt>Weekdays</dt><dd>8:00–18:00</dd><dt>Sun</dt><dd>closed</dd></dl>")
    assert table and lines and items and terms
    assert [found.kind for found in (table, lines, items, terms)] == [
        "table",
        "lines",
        "list",
        "dl",
    ]
    assert table.rows == [("Monday to Friday", "8:00 to 18:00"), ("Sunday", "Closed")]
    assert all(hours.same_hours(table, other) for other in (lines, items, terms))
    later = _find("<p>Mon&ndash;Fri 9&ndash;17<br>Sun closed</p>")
    assert later is not None and not hours.same_hours(table, later)


def test_a_list_with_one_row_that_does_not_read_is_left_alone() -> None:
    assert _find("<p>Mon–Fri 8–18<br>Ring the bell</p>") is None
    assert _find("<ul><li>Mon–Fri 8–18</li><li><a href='/x'>Sun</a> closed</li></ul>") is None
    assert _find("<table><tr><td>Monday</td><td>8–18</td><td>Bar</td></tr></table>") is None
    assert _find("<p>Mon–Fri 8–18</p>") is None  # one line: not a list of hours
