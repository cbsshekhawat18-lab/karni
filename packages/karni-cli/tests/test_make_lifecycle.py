"""The field DSL for lifecycle columns and limited resources: state, ranges, capacity."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from karni_cli.generators.fields import FIELD_DOCS, TYPES, parse_field, render_model_body
from karni_cli.generators.pysource import Import
from karni_cli.project import CliError


def _render(*tokens: str, line_length: int = 88) -> tuple[str, list[Import], list[str]]:
    specs = [parse_field(token) for token in tokens]
    out = render_model_body(
        specs, model="Booking", app_label="events", resolve={}, line_length=line_length
    )
    return "\n".join([*out.inner, *out.lines]), out.imports, out.notes


def test_the_types_are_listed_and_documented() -> None:
    assert {"state", "daterange", "datetimerange", "capacity"} <= set(TYPES)
    syntaxes = " ".join(syntax for syntax, _ in FIELD_DOCS)
    assert "status:state:" in syntaxes and "capacity:quantity" in syntaxes


def test_plain_states_get_a_linear_lifecycle_to_edit() -> None:
    body, imports, notes = _render("status:state:draft,confirmed,cancelled")
    assert body == (
        "    status = StateField(\n"
        '        states=["draft", "confirmed", "cancelled"],\n'
        '        transitions={"draft": ["confirmed"], "confirmed": ["cancelled"]},\n'
        "    )"
    )
    assert Import("karni.fields", "StateField") in imports
    assert "moves draft -> confirmed -> cancelled in order" in notes[0]


def test_arrows_declare_the_transitions() -> None:
    body, _imports, notes = _render(
        "status:state:draft>confirmed>refunded|draft>cancelled|confirmed>cancelled"
    )
    assert '"draft": ["confirmed", "cancelled"]' in body
    assert '"confirmed": ["refunded", "cancelled"]' in body
    assert 'states=["draft", "confirmed", "refunded", "cancelled"]' in body
    assert notes == []


def test_a_long_lifecycle_is_split_the_way_ruff_formats_it(tmp_path: Path) -> None:
    token = (
        "status:state:requested>approved>scheduled>in_progress>completed|"
        "requested>rejected|approved>cancelled|scheduled>cancelled|in_progress>failed"
    )
    body, _imports, _notes = _render(token, line_length=88)
    assert "        transitions={\n" in body
    if importlib.util.find_spec("ruff") is None:
        pytest.skip("ruff is not installed")
    source = tmp_path / "models.py"
    source.write_text(
        "from django.db import models\nfrom karni.fields import StateField\n\n\n"
        f"class Booking(models.Model):\n{body}\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "--line-length", "88", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_range_and_capacity_fields_render() -> None:
    body, imports, notes = _render(
        "seats:int",
        "during:datetimerange",
        "nights:daterange?",
        "left:capacity:seats",
        "units:capacity",
    )
    assert "    during = DateTimeRangeField()" in body
    assert "    nights = DateRangeField(null=True, blank=True)" in body
    assert '    left = CapacityField(total="seats")' in body
    assert "    units = CapacityField(default=0)" in body
    assert {
        Import("karni.fields", name) for name in ("DateTimeRangeField", "CapacityField")
    } <= set(imports)
    assert any("no_overlap = ('<resource>', \"during\")" in note for note in notes)
    assert any("karni.capacity.reserve" in note for note in notes)


@pytest.mark.parametrize(
    ("token", "code", "fragment"),
    [
        ("status:state", "C370", "needs its states"),
        ("status:state:draft,in review", "C370", "may only use letters"),
        ("status:state:draft>draft", "C370", "moves a state to itself"),
        ("status:state:draft>confirmed|cancelled", "C370", "nothing leads to cancelled"),
        ("status:state:draft,draft", "C370", "listed twice"),
        ("status:state:draft,done?", "C370", "drop the '?'"),
        ("during:datetimerange:utc", "C371", "takes no arguments"),
        ("left:capacity:seats", "C372", "not a field of Booking"),
        ("left:capacity:a:b", "C372", "takes one argument"),
        ("left:capacity?", "C372", "never empty"),
    ],
)
def test_invalid_specs_name_the_problem(token: str, code: str, fragment: str) -> None:
    with pytest.raises(CliError) as raised:
        _render(token)
    assert raised.value.code == code
    assert fragment in str(raised.value)
