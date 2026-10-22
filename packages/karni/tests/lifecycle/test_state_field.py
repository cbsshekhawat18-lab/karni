"""StateField as a declaration: validation (E983), what it derives, what migrations get."""

from __future__ import annotations

import pytest
from django.db import connection

from karni.errorcodes import KarniError
from karni.fields import StateField
from tests.lifecycleapp.models import Order, Ticket

STATES = ["draft", "confirmed", "cancelled", "refunded"]
TRANSITIONS = {"draft": ["confirmed", "cancelled"], "confirmed": ["cancelled", "refunded"]}


def test_the_machine_derives_default_initial_and_terminal_states() -> None:
    field = StateField(states=STATES, transitions=TRANSITIONS)
    assert field.default == "draft"
    assert field.initial == ("draft",)
    assert field.terminal == ("cancelled", "refunded")
    assert field.machine.allowed("confirmed") == ("cancelled", "refunded")
    assert field.machine.allowed("cancelled") == ()
    assert field.choices == [
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
    ]
    assert field.max_length == 20  # at least 20, or the longest state


def test_a_textchoices_class_keeps_its_labels() -> None:
    field = Ticket._meta.get_field("status")
    assert field.choices[1] == ("triaged", "Triaged by support")
    assert field.initial == ("open", "triaged")


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({}, "needs states=[...]"),
        ({"states": []}, "states is empty"),
        ({"states": "draft"}, "must be a list of state names"),
        ({"states": ["draft", "draft"]}, "declared twice"),
        ({"states": ["in progress"]}, "may only use letters"),
        ({"states": ["a'b"]}, "may only use letters"),
        ({"states": ["a", "b"], "transitions": {"a": ["c"]}}, "'c', which is not one of"),
        ({"states": ["a", "b"], "transitions": {"x": ["b"]}}, "names 'x', which is not"),
        ({"states": ["a", "b"], "transitions": {"a": ["a", "b"]}}, "lists 'a' itself"),
        ({"states": ["a", "b"], "transitions": {"a": "b"}}, "must be a list of states"),
        ({"states": ["a", "b"], "transitions": []}, "transitions must be a dict"),
        ({"states": ["a", "b"], "transitions": {}}, "no transition leads to 'b'"),
        ({"states": ["a", "b"], "transitions": {"a": ["b"]}, "default": "z"}, "default must be"),
        ({"states": ["a", "b"], "transitions": {"a": ["b"]}, "initial": ["b"]}, "must be one of"),
        ({"states": ["a", "b"], "transitions": {"a": ["b"]}, "initial": ["q"]}, "not declared"),
        ({"states": ["a"], "choices": [("a", "A")]}, "remove choices="),
        ({"states": ["abcdef"], "max_length": 3}, "shorter than the state"),
    ],
)
def test_an_invalid_declaration_names_the_problem(kwargs: dict, fragment: str) -> None:
    with pytest.raises(KarniError) as raised:
        StateField(**kwargs)
    assert raised.value.code == "E983"
    assert fragment in raised.value.message


def test_deconstruct_round_trips_and_omits_what_it_derives() -> None:
    field = Order._meta.get_field("status")
    name, path, args, kwargs = field.deconstruct()
    assert (name, path) == ("status", "karni.fields.StateField")
    assert kwargs == {"states": STATES, "transitions": TRANSITIONS}
    rebuilt = StateField(*args, **kwargs)
    assert rebuilt.machine == field.machine
    assert rebuilt.max_length == field.max_length


def test_labels_and_initial_states_survive_deconstruct() -> None:
    _name, _path, args, kwargs = Ticket._meta.get_field("status").deconstruct()
    assert kwargs["states"][1] == ["triaged", "Triaged by support"]
    assert kwargs["initial"] == ["open", "triaged"]
    assert kwargs["audit"] is False
    assert StateField(*args, **kwargs).machine == Ticket._meta.get_field("status").machine


def test_changing_only_the_transitions_needs_no_ddl() -> None:
    assert "transitions" in StateField.non_db_attrs
    assert "initial" in StateField.non_db_attrs


def test_the_column_carries_a_check_of_the_declared_states() -> None:
    field = Order._meta.get_field("status")
    assert field.db_check(connection) == (
        f"{connection.ops.quote_name('status')} IN ('draft', 'confirmed', 'cancelled', 'refunded')"
    )
    assert field.db_parameters(connection)["check"] == field.db_check(connection)


def test_the_schema_extensions_list_every_transition() -> None:
    assert Order._meta.get_field("status").machine.as_schema() == {
        "x-karni-transitions": {
            "draft": ["confirmed", "cancelled"],
            "confirmed": ["cancelled", "refunded"],
            "cancelled": [],
            "refunded": [],
        },
        "x-karni-initial": ["draft"],
    }
