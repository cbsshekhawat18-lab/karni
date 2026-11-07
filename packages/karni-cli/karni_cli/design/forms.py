"""The ``<form>`` elements of a design, and the ``{% karni_form %}`` that replaces each one.

A designer's page posts its form somewhere that does not exist in the
project (``action="contact.php"``, a form service, ``#``). ``karni import
design`` records every form of every page in ``.karni/design.json``, and
``karni make form`` reads the site's templates the same way to say which
``<form>`` the tag replaces, with the arguments that keep the design's own
markup: its class names (a field's element, a row, the label, the control,
the button, the required mark), its labels, placeholders and rows.

:func:`forms_in` reads a page or a template, :func:`best_match` picks the
form whose fields a generated form has, :func:`match_fields` says which
model field each control fills (by name, then by its label and its type,
so the design's ``date`` fills ``preferred_date``), :func:`suggest_tag`
writes the tag. Texts read from a template (an imported, editable page)
lose their template tags: a tag's argument holds plain text only.
Nothing here writes a file.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from karni_cli.design.parse import Node, collapse, parse

__all__ = [
    "ATTRIBUTES",
    "DesignField",
    "DesignForm",
    "FieldMatch",
    "best_match",
    "forms_in",
    "match_fields",
    "plain_text",
    "suggest_tag",
]

#: Inputs a visitor does not fill.
_NOT_FILLED: Final = frozenset({"hidden", "submit", "button", "reset", "image"})
#: Django template syntax in a template's text: ``{% editable "..." %}``, ``{{ site.name }}``.
_TEMPLATE_SYNTAX: Final = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.DOTALL)
_WORD: Final = re.compile(r"[a-z0-9]+")
#: The model field kinds (karni make model's field DSL) each kind of control can fill.
_FILLS: Final[dict[str, frozenset[str]]] = {
    "email": frozenset({"email", "str"}),
    "tel": frozenset({"phone", "str"}),
    "url": frozenset({"url", "str"}),
    "date": frozenset({"date"}),
    "datetime-local": frozenset({"datetime"}),
    "time": frozenset({"time", "str"}),
    "number": frozenset({"int", "decimal", "float"}),
    "range": frozenset({"int", "decimal", "float"}),
    "checkbox": frozenset({"bool", "m2m", "choice"}),
    "radio": frozenset({"choice", "fk", "country", "str"}),
    "select": frozenset({"choice", "fk", "m2m", "country", "str"}),
    "textarea": frozenset({"text", "str"}),
    "file": frozenset({"file", "image"}),
}
#: Controls whose type alone says which field they fill, when the model has one such field.
_DISTINCT: Final = frozenset(
    {"email", "tel", "url", "date", "datetime-local", "time", "number", "file", "checkbox"}
)
#: The attributes of a control the tag keeps (karni_site.forms.FIELD_ATTRIBUTES): the
#: design's ``rows="4"``, ``min``, ``max``, ``step``, ``pattern`` and the like.
ATTRIBUTES: Final = (
    "rows",
    "cols",
    "min",
    "max",
    "step",
    "pattern",
    "size",
    "inputmode",
    "autocomplete",
)
#: The class sets ``{% karni_form classes="..." %}`` ships (karni_site.forms.PRESETS).
BOOTSTRAP: Final[dict[str, str]] = {
    "row": "row",
    "column": "col-md",
    "field": "mb-3",
    "label": "form-label",
    "input": "form-control",
    "select": "form-select",
    "check": "form-check mb-3",
    "check_input": "form-check-input",
    "check_label": "form-check-label",
    "button": "btn btn-primary",
    "required": "text-danger",
}


@dataclass
class DesignField:
    """One control of a design's form."""

    name: str
    tag: str  # input, select, textarea
    type: str  # the input's type, "select" or "textarea"
    required: bool
    label: str
    placeholder: str
    line: int
    #: The control's own :data:`ATTRIBUTES` (``{"rows": "4"}``), kept by the tag's ``attrs``.
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class DesignForm:
    """A ``<form>`` of a page: where it is, where it posts, its fields and its class names."""

    line: int
    action: str
    method: str
    id: str
    classes: str
    fields: list[DesignField]
    #: The class names of each part, keyed like ``KARNI_SITE_FORM_CLASSES``.
    markup: dict[str, str] = field(default_factory=dict)
    #: Field names that share a row element, in order.
    rows: list[list[str]] = field(default_factory=list)
    button: str = ""
    required_mark: str = ""

    @property
    def names(self) -> list[str]:
        return [item.name for item in self.fields]

    def as_record(self) -> dict[str, Any]:
        """The ``forms`` entry of a page in ``.karni/design.json``."""
        return {
            "line": self.line,
            "action": self.action,
            "method": self.method,
            "id": self.id,
            "class": self.classes,
            "fields": [
                {
                    "name": item.name,
                    "type": item.type,
                    "required": item.required,
                    **({"attrs": dict(item.attrs)} if item.attrs else {}),
                }
                for item in self.fields
            ],
            "markup": dict(sorted(self.markup.items())),
            "rows": self.rows,
            "button": self.button,
        }


def _line(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _ancestors(node: Node, stop: Node) -> list[Node]:
    found: list[Node] = []
    current = node.parent
    while current is not None and current is not stop:
        found.append(current)
        current = current.parent
    return found


def _controls(form: Node, source: str) -> list[Node]:
    found = []
    for node in form.iter_elements():
        if node.tag in {"select", "textarea"}:
            found.append(node)
        elif node.tag == "input":
            kind = (node.attr(source, "type") or "text").lower()
            if kind not in _NOT_FILLED:
                found.append(node)
    return [node for node in found if node.attr(source, "name")]


def _label_for(control: Node, form: Node, source: str) -> Node | None:
    ident = control.attr(source, "id")
    if ident:
        for node in form.iter_elements():
            if node.tag == "label" and node.attr(source, "for") == ident:
                return node
    return next((node for node in _ancestors(control, form) if node.tag == "label"), None)


def _common(values: Iterable[str]) -> str:
    counted = Counter(value for value in values if value)
    return counted.most_common(1)[0][0] if counted else ""


def _required_mark(label: Node | None, source: str) -> tuple[str, str]:
    """``(text, classes)`` of a required mark inside the label (``<span class="req">*</span>``)."""
    if label is None:
        return "", ""
    for node in label.iter_elements():
        if node is label:
            continue
        text = node.plain_text(source)
        if text in {"*", "(required)", "required"}:
            return text, " ".join(node.classes(source))
    return "", ""


def plain_text(text: str) -> str:
    """``text`` without Django template syntax, whitespace collapsed: what a tag argument holds.

    A page ``karni import design --editable`` wrote wraps a label in
    ``{% editable "..." %}...{% endeditable %}``. Inside another tag's
    argument that would not parse, so only the words are kept.
    """
    return collapse(_TEMPLATE_SYNTAX.sub("", text))


def _label_text(label: Node | None, control: Node, source: str) -> str:
    if label is None:
        return ""
    parts = []
    for child in label.iter():
        if child.kind != "text":
            continue
        if any(
            a is control or a.tag in {"select", "textarea", "span", "abbr"}
            for a in _ancestors(child, label)
        ):
            continue
        parts.append(child.text(source))
    return plain_text("".join(parts)).rstrip(" *:").strip()


def _wrapper(control: Node, label: Node | None, form: Node, controls: list[Node]) -> Node | None:
    """The closest element around the control and its label that holds no other control."""
    name_of = {id(node): node for node in controls}
    for node in _ancestors(control, form):
        if node.tag == "label":
            continue
        inside = [c for c in node.iter_elements() if id(c) in name_of]
        if any(c is not control for c in inside):
            return None
        if label is None or label in list(node.iter_elements()):
            return node
    return None


def _attributes(control: Node, source: str) -> dict[str, str]:
    """The control's :data:`ATTRIBUTES` that a tag argument can hold as they are."""
    found: dict[str, str] = {}
    for name in ATTRIBUTES:
        value = control.attr(source, name)
        if value is None:
            continue
        value = plain_text(value)
        # The tag argument is in double quotes, splits on "|" and quotes a value with
        # spaces in single quotes: a value with one of them stays out.
        if (
            value
            and not any(char in value for char in "\"|'")
            and not _TEMPLATE_SYNTAX.search(value)
        ):
            found[name] = value
    return found


def _describe(form: Node, source: str) -> DesignForm:
    controls = _controls(form, source)
    fields: list[DesignField] = []
    parts: dict[str, list[str]] = {key: [] for key in BOOTSTRAP}
    marks: list[str] = []
    wrappers: dict[int, tuple[Node, str]] = {}
    for control in controls:
        name = control.attr(source, "name") or ""
        kind = (
            control.tag
            if control.tag in {"select", "textarea"}
            else (control.attr(source, "type") or "text").lower()
        )
        label = _label_for(control, form, source)
        mark, mark_class = _required_mark(label, source)
        if mark:
            marks.append(mark)
            parts["required"].append(mark_class)
        check = kind in {"checkbox", "radio"}
        fields.append(
            DesignField(
                name=name,
                tag=control.tag,
                type=kind,
                required=control.attr(source, "required") is not None or bool(mark),
                label=_label_text(label, control, source),
                placeholder=plain_text(control.attr(source, "placeholder") or ""),
                line=_line(source, control.start),
                attrs=_attributes(control, source),
            )
        )
        own = " ".join(control.classes(source))
        if check:
            parts["check_input"].append(own)
        elif control.tag == "select":
            parts["select"].append(own)
        else:
            parts["input"].append(own)
        if label is not None:
            parts["check_label" if check else "label"].append(" ".join(label.classes(source)))
        wrapper = _wrapper(control, label, form, controls)
        if wrapper is not None:
            wrappers[id(control)] = (wrapper, name)
            parts["check" if check else "field"].append(" ".join(wrapper.classes(source)))
    rows: list[list[str]] = []
    row_classes: list[str] = []
    grouped: dict[int, list[tuple[Node, str]]] = {}
    for wrapper, name in wrappers.values():
        parent = wrapper.parent
        if parent is not None and parent is not form:
            grouped.setdefault(id(parent), []).append((wrapper, name))
    in_rows: set[str] = set()
    row_members: list[tuple[Node, list[tuple[Node, str]]]] = []
    for members in grouped.values():
        if len(members) < 2 or members[0][0].parent is None:
            continue
        parent = members[0][0].parent
        rows.append([name for _wrapper, name in members])
        row_classes.append(" ".join(parent.classes(source)))
        in_rows.update(name for _wrapper, name in members)
        row_members.append((parent, members))
    checks = {
        id(c) for c in controls if (c.attr(source, "type") or "").lower() in {"checkbox", "radio"}
    }
    plain_fields = [
        " ".join(wrapper.classes(source))
        for key, (wrapper, name) in wrappers.items()
        if name not in in_rows and key not in checks
    ]
    if rows and plain_fields:
        parts["field"] = plain_fields
    plain = _common(parts["field"]).split()
    columns = [
        " ".join(c for c in wrapper.classes(source) if c not in plain)
        for _parent, members in row_members
        for wrapper, _name in members
    ]
    buttons = [
        node
        for node in form.iter_elements()
        if (node.tag == "button" and (node.attr(source, "type") or "submit").lower() == "submit")
        or (node.tag == "input" and (node.attr(source, "type") or "").lower() == "submit")
    ]
    button = buttons[0] if buttons else None
    markup = {key: _common(values) for key, values in parts.items()}
    markup["row"] = _common(row_classes)
    markup["column"] = _common(columns)
    if button is not None:
        markup["button"] = " ".join(button.classes(source))
    markup["form"] = " ".join(form.classes(source))
    status = next(
        (
            node
            for node in form.iter_elements()
            if node is not form
            and (node.attr(source, "role") == "status" or node.attr(source, "aria-live"))
        ),
        None,
    )
    if status is not None:  # where the design says "sent" or "try again"
        markup["message"] = " ".join(status.classes(source))
    button_text = ""
    if button is not None:
        button_text = (
            button.attr(source, "value") or ""
            if button.tag == "input"
            else button.plain_text(source)
        )
    return DesignForm(
        line=_line(source, form.start),
        action=form.attr(source, "action") or "",
        method=(form.attr(source, "method") or "get").lower(),
        id=form.attr(source, "id") or "",
        classes=" ".join(form.classes(source)),
        fields=fields,
        markup={key: value for key, value in markup.items() if value},
        rows=rows,
        button=plain_text(button_text),
        required_mark=_common(marks),
    )


def forms_in(source: str) -> list[DesignForm]:
    """Every ``<form>`` of a page or a template, in document order."""
    document = parse(source)
    return [_describe(node, source) for node in document.root.find_all("form")]


@dataclass(frozen=True)
class FieldMatch:
    """A control of the design's form and the model field it fills."""

    design: str  # the control's name in the design
    model: str  # the model field
    how: str  # "name", "label" (its label and type) or "type" (its type alone)

    def describe(self, form: DesignForm) -> str:
        if self.how == "name":
            return f"{self.design} -> {self.model}"
        control = next((item for item in form.fields if item.name == self.design), None)
        kind = control.type if control is not None else "?"
        if self.how == "label" and control is not None and control.label:
            return f"{self.design} -> {self.model} (by its label {control.label!r} and type {kind})"
        return f"{self.design} -> {self.model} (by its type {kind}, the only such field left)"


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("_", " ").replace("-", " "))


def _fills(control: DesignField, kind: str) -> bool:
    """Whether ``control`` can hold a value of the model field kind ``kind``."""
    allowed = _FILLS.get(control.type)
    if allowed is None:  # a text input holds most things
        return kind not in {"bool", "file", "image", "m2m", "json"}
    return kind in allowed


def match_fields(
    form: DesignForm, fields: Mapping[str, str] | Sequence[str]
) -> tuple[list[FieldMatch], list[str]]:
    """Which model field each control of ``form`` fills, and the controls nothing fills.

    ``fields`` maps the model's field names to their kinds (``"date"``,
    ``"choice"``), or lists the names. A control fills, in this order: the
    field of its own name; the field its label names (``Preferred date``,
    ``preferred_date``) or whose name holds its own (``date`` in
    ``preferred_date``), when its type can hold that field; the model's only
    field of its type (the only date) when the control's type says what it
    is. Each field is filled once.
    """
    kinds: dict[str, str] = (
        dict(fields) if isinstance(fields, Mapping) else dict.fromkeys(fields, "")
    )
    free = dict(kinds)
    found: dict[str, FieldMatch] = {}
    for control in form.fields:
        if control.name in free:
            found[control.name] = FieldMatch(control.name, control.name, "name")
            free.pop(control.name)
    for control in form.fields:
        if control.name in found:
            continue
        snake = "_".join(_words(control.name))
        if snake in free:
            found[control.name] = FieldMatch(control.name, snake, "name")
            free.pop(snake)
    for control in form.fields:
        if control.name in found:
            continue
        own = set(_words(control.name))
        label = set(_words(control.label))
        scored: list[tuple[int, str]] = []
        for name, kind in free.items():
            if kind and not _fills(control, kind):
                continue
            words = set(_words(name))
            if control.label and "_".join(_words(control.label)) == name:
                scored.append((3, name))
            elif label and words <= label:
                scored.append((2, name))
            elif own and own <= words:
                scored.append((1, name))
        if not scored:
            continue
        best = max(score for score, _ in scored)
        names = [name for score, name in scored if score == best]
        if len(names) == 1:
            found[control.name] = FieldMatch(control.name, names[0], "label")
            free.pop(names[0])
    for control in form.fields:
        if control.name in found or control.type not in _DISTINCT:
            continue
        same = [c for c in form.fields if c.name not in found and c.type == control.type]
        fitting = [name for name, kind in free.items() if kind and _fills(control, kind)]
        if len(same) == 1 and len(fitting) == 1:
            found[control.name] = FieldMatch(control.name, fitting[0], "type")
            free.pop(fitting[0])
    matched = [found[c.name] for c in form.fields if c.name in found]
    return matched, [c.name for c in form.fields if c.name not in found]


def best_match(
    forms: Sequence[DesignForm], names: Mapping[str, str] | Sequence[str]
) -> DesignForm | None:
    """The form most of whose fields ``names`` fills, or ``None`` when none is half covered.

    ``names`` maps the model's field names to their kinds, or lists them
    (see :func:`match_fields`). Ranked by the fields in common, then by the
    share of the form's fields they are, then by document order.
    """
    scored = []
    for index, form in enumerate(forms):
        common = len(match_fields(form, names)[0])
        share = common / len(form.names) if form.names else 0.0
        if common and share >= 0.5:
            scored.append((common, share, -index, form))
    return max(scored, key=lambda entry: entry[:3])[3] if scored else None


def _humanize(name: str) -> str:
    text = name.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:]


def _argument(text: str) -> str:
    """A label inside ``labels="field: text | ..."``: no ``|`` that would split it."""
    return plain_text(text).replace("|", "/")


def _attribute(name: str, value: str) -> str:
    """``rows=4``, or ``pattern='[0-9 ]+'`` for a value with spaces (karni_site reads both)."""
    return f"{name}='{value}'" if re.search(r"\s", value) else f"{name}={value}"


def _quote(value: str) -> str:
    return '"' + plain_text(value).replace('"', "'") + '"'


def suggest_tag(
    name: str,
    form: DesignForm,
    fields: Mapping[str, str] | Sequence[str],
    *,
    editable: str = "",
) -> str:
    """``{% karni_form "<name>" ... %}`` with the arguments that keep the design's markup.

    Only fields the generated form has are named, by the model's names
    (:func:`match_fields`). Class names equal to the Bootstrap preset become
    ``classes="bootstrap"``. ``editable`` (a block key prefix such as
    ``contact.enquiry``) makes the form's labels, placeholders, button and
    message blocks the client edits in the admin. Every value is plain
    text, so the tag always compiles.
    """
    matches, _unmatched = match_fields(form, fields)
    rename = {match.design: match.model for match in matches}
    options: list[tuple[str, str]] = []
    markup = dict(form.markup)
    same = [key for key, value in BOOTSTRAP.items() if markup.get(key) == value]
    differ = [key for key in BOOTSTRAP if key in markup and markup[key] != BOOTSTRAP[key]]
    if len(same) >= 2 and not differ:
        options.append(("classes", "bootstrap"))
        markup = {key: value for key, value in markup.items() if key not in BOOTSTRAP}
    for key in (
        "form",
        "message",
        "row",
        "column",
        "field",
        "label",
        "input",
        "select",
        "check",
        "check_input",
        "check_label",
        "required",
        "button",
    ):
        if markup.get(key):
            options.append((f"{key}_class", markup[key]))
    rows = [[rename[n] for n in row if n in rename] for row in form.rows]
    rows = [row for row in rows if len(row) > 1]
    if rows:
        options.append(("rows", "|".join(",".join(row) for row in rows)))
    labels = [
        f"{rename[item.name]}: {_argument(item.label)}"
        for item in form.fields
        if item.name in rename
        and item.label
        and item.label.lower() != _humanize(rename[item.name]).lower()
    ]
    if labels:
        options.append(("labels", " | ".join(labels)))
    hints = [
        f"{rename[item.name]}: {_argument(item.placeholder)}"
        for item in form.fields
        if item.name in rename and item.placeholder
    ]
    if hints:
        options.append(("placeholders", " | ".join(hints)))
    kept = [
        f"{rename[item.name]}: "
        + " ".join(_attribute(key, value) for key, value in item.attrs.items())
        for item in form.fields
        if item.name in rename and item.attrs
    ]
    if kept:
        options.append(("attrs", " | ".join(kept)))
    if form.button:
        options.append(("button", plain_text(form.button)))
    if form.id:
        options.append(("id", form.id))
    if editable:
        options.append(("editable", editable))
    args = "".join(f" {key}={_quote(value)}" for key, value in options)
    return f'{{% karni_form "{name}"{args} %}}'
