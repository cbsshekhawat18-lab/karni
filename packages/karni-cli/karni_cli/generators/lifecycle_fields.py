"""``karni make model`` types for lifecycle columns and limited resources.

* ``status:state:draft,confirmed,cancelled`` — a ``StateField``. Plain
  states get a linear lifecycle to edit (each state moves to the next one);
  ``>`` declares the transitions instead:
  ``"status:state:draft>confirmed>refunded|draft>cancelled|confirmed>cancelled"``
  (states in order of first appearance, the first one is the default).
* ``during:datetimerange`` / ``nights:daterange`` — PostgreSQL range columns.
* ``remaining:capacity:quantity`` — a ``CapacityField(total="quantity")``,
  consumed with ``karni.capacity.reserve()``; without a total it starts at 0.

Kept apart from :mod:`karni_cli.generators.fields` so other field types can
be added there without touching these; that module dispatches here.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any

from karni_cli.generators.pysource import Import, call, pystr
from karni_cli.project import CliError

__all__ = ["FIELD_DOCS", "TYPES", "render"]

TYPES: tuple[str, ...] = ("state", "daterange", "datetimerange", "capacity")

#: (syntax, what it generates) — rendered into docs/cli.md with the other types.
FIELD_DOCS: tuple[tuple[str, str], ...] = (
    (
        "status:state:draft,confirmed,cancelled",
        (
            "StateField(states=[...], transitions={...}): each state moves to the next (edit "
            "the dict), or declare the moves with >: 'status:state:draft>confirmed|draft>cancelled'"
        ),
    ),
    (
        "during:datetimerange / nights:daterange",
        "DateTimeRangeField() / DateRangeField() (PostgreSQL range columns, karni.fields)",
    ),
    (
        "remaining:capacity:quantity",
        (
            'CapacityField(total="quantity"): consumed with karni.capacity.reserve(); '
            "without :total, CapacityField(default=0)"
        ),
    ),
)

_STATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _states(name: str, raw: str) -> tuple[list[str], dict[str, list[str]], bool]:
    """``(states, transitions, declared)`` from ``draft,confirmed`` or ``draft>confirmed|...``."""
    tokens = [token.strip() for token in re.split(r"[|,]", raw) if token.strip()]
    if not tokens:
        raise CliError(
            f"Field {name}: state needs its states, e.g. '{name}:state:draft,confirmed,cancelled' "
            f"or '{name}:state:draft>confirmed|draft>cancelled'.",
            code="C370",
        )
    states: list[str] = []
    transitions: dict[str, list[str]] = {}
    declared = any(">" in token for token in tokens)
    for token in tokens:
        chain = [part.strip() for part in token.split(">")]
        for state in chain:
            if not _STATE.match(state):
                raise CliError(
                    f"Field {name}: state {state!r} may only use letters, digits, - and _ "
                    "(and > between states to declare a transition).",
                    code="C370",
                )
            if state not in states:
                states.append(state)
        for source, target in pairwise(chain):
            if source == target:
                raise CliError(
                    f"Field {name}: {source}>{target} moves a state to itself; drop it.",
                    code="C370",
                )
            targets = transitions.setdefault(source, [])
            if target not in targets:
                targets.append(target)
    if not declared:
        if len(tokens) != len(set(tokens)):
            raise CliError(f"Field {name}: a state is listed twice.", code="C370")
        transitions = {source: [target] for source, target in pairwise(states)}
    reachable = {states[0]}
    frontier = [states[0]]
    while frontier:
        for target in transitions.get(frontier.pop(), []):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    stranded = [state for state in states if state not in reachable]
    if stranded:
        raise CliError(
            f"Field {name}: nothing leads to {', '.join(stranded)} from {states[0]!r} (the first "
            f"state is where rows start). Add a move into it, e.g. {states[0]}>{stranded[0]}.",
            code="C370",
        )
    return states, transitions, declared


def _state_call(
    name: str, states: list[str], moves: list[str], indent: str, line_length: int
) -> str:
    """``StateField(states=[...], transitions={...})`` split the way ruff format splits it."""
    listed = "[" + ", ".join(states) + "]"
    mapping = "{" + ", ".join(moves) + "}"
    args = [f"states={listed}", f"transitions={mapping}"]
    flat = call(f"{name} = StateField", args, indent, line_length)
    if all(len(line) <= line_length for line in flat.splitlines()):
        return flat
    inner = f"{indent}    "

    def argument(key: str, opening: str, items: list[str], closing: str) -> list[str]:
        line = f"{inner}{key}={opening}{', '.join(items)}{closing},"
        if len(line) <= line_length:
            return [line]
        return [
            f"{inner}{key}={opening}",
            *(f"{inner}    {item}," for item in items),
            f"{inner}{closing},",
        ]

    return "\n".join(
        [
            f"{indent}{name} = StateField(",
            *argument("states", "[", states, "]"),
            *argument("transitions", "{", moves, "}"),
            f"{indent})",
        ]
    )


def render(
    spec: Any, out: Any, indent: str, line_length: int, model: str, field_names: set[str]
) -> None:
    """Append the field line (and its import) for one of :data:`TYPES` to ``out``."""
    if spec.kind == "state":
        if spec.optional:
            raise CliError(
                f"Field {spec.name}: a state column always holds a state; drop the '?' (the "
                "first state is the default).",
                code="C370",
            )
        states, transitions, declared = _states(spec.name, ":".join(spec.args))
        moves = [
            f"{pystr(source)}: [" + ", ".join(pystr(t) for t in targets) + "]"
            for source, targets in transitions.items()
        ]
        out.lines.append(
            _state_call(spec.name, [pystr(state) for state in states], moves, indent, line_length)
        )
        out.imports.append(Import("karni.fields", "StateField"))
        if not declared:
            out.notes.append(
                f"note: {model}.{spec.name} moves {' -> '.join(states)} in order; edit its "
                "transitions={...} (or declare them: "
                f"'{spec.name}:state:{states[0]}>{states[-1]}|...'). Terminal: "
                f"{states[-1]}."
            )
        return
    if spec.kind in {"daterange", "datetimerange"}:
        if spec.args:
            raise CliError(
                f"Field {spec.name}: {spec.kind} takes no arguments (write "
                f"'{spec.name}:{spec.kind}' or '{spec.name}:{spec.kind}?').",
                code="C371",
            )
        django = "DateRangeField" if spec.kind == "daterange" else "DateTimeRangeField"
        extra = ["null=True", "blank=True"] if spec.optional else []
        out.lines.append(call(f"{spec.name} = {django}", extra, indent, line_length))
        out.imports.append(Import("karni.fields", django))
        out.notes.append(
            f"note: {model}.{spec.name} is a PostgreSQL range column (psycopg required). "
            f"To forbid overlaps per resource: class Karni: no_overlap = ('<resource>', "
            f"{pystr(spec.name)})."
        )
        return
    total = spec.args[0] if spec.args and spec.args[0] else None
    if len(spec.args) > 1:
        raise CliError(
            f"Field {spec.name}: capacity takes one argument, the field holding the total "
            f"(e.g. '{spec.name}:capacity:quantity').",
            code="C372",
        )
    if spec.optional:
        raise CliError(
            f"Field {spec.name}: a capacity counter is never empty; drop the '?'.", code="C372"
        )
    if total is not None and total not in field_names:
        raise CliError(
            f"Field {spec.name}: capacity:{total} names {total!r}, which is not a field of "
            f"{model}. Declare it first, e.g. '{total}:int {spec.name}:capacity:{total}'.",
            code="C372",
        )
    args = [f"total={pystr(total)}"] if total is not None else ["default=0"]
    out.lines.append(call(f"{spec.name} = CapacityField", args, indent, line_length))
    out.imports.append(Import("karni.fields", "CapacityField"))
    out.notes.append(
        f"note: {model}.{spec.name} is consumed only through karni.capacity.reserve(row, n) "
        "inside transaction.atomic() (release() gives units back)."
    )
