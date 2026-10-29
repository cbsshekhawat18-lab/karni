"""``karni make form <name> <field:type> ... [--notify SETTING]``: a public form, end to end.

One command gives a site a form that works with and without JavaScript and
cannot be abused, for a contact form, a booking request, a newsletter
sign-up or a job application alike. It writes project code only. The
runtime is the ``karni-site`` module:

* ``<app>/models.py``: the model, with the visitor's fields from the field
  DSL, a ``status`` StateField for the inbox (``--states``, default
  ``new>replied|new>archived|replied>archived``), staff-only ``notes``, and
  ``class Karni`` (``field_roles`` hides both from visitors, ``audit`` and
  ``dashboard``) and ``class AdminMeta`` (the admin inbox: newest first,
  filtered by status, searchable).
* ``<app>/viewsets.py``: a BaseViewSet with ``create=Public()``, read and
  written by ``--role`` (default ``staff``). Karni limits each visitor's
  creates (``KARNI_PUBLIC_CREATE_RATE``) and gives the form a honeypot
  field by itself, so no throttle code is written.
* With ``--notify SETTING``: a queued listener in ``<app>/listeners.py``
  that calls ``karni_site.notify.notify_recipients``, the email's subject
  and body templates under ``<app>/templates/<app>/email/``, the setting
  in config/settings.py and a line in .env.example. Without it nothing is
  sent.
* ``<app>/tests/test_<name>_form.py``: anonymous submit, the form without
  JavaScript, the email, the protected fields, the rate limit and
  staff-only reading.
* With a ``frontend/``: the staff app's list, detail and form pages.
* ``config/urls.py`` includes ``karni_site.urls`` (the view the form posts
  to), and the project gets ``karni-site`` as ``karni add site`` would.

It prints the tag to put in a page, ``{% karni_form "<name>" %}``. When the
project's site came from ``karni import design`` and one of its templates
holds a ``<form>``, it names the template and the line, and prints the tag
with the arguments that keep that form's own class names, labels, rows and
button.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import typer

from karni_cli.commands.add import record_guidance
from karni_cli.design.forms import DesignForm, best_match, forms_in, match_fields, suggest_tag
from karni_cli.generators import migration as migration_gen
from karni_cli.generators import model as model_gen
from karni_cli.generators import site as site_gen
from karni_cli.generators import viewset as viewset_gen
from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    SETTINGS,
    App,
    Workspace,
    local_apps,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.fields import (
    FieldSpec,
    is_user_target,
    parse_fields,
    relation_name,
    render_model_body,
)
from karni_cli.generators.introspect import models_file
from karni_cli.generators.lifecycle_fields import _states
from karni_cli.generators.naming import default_route, humanize, pascal, pluralize, snake
from karni_cli.generators.pysource import (
    Import,
    append,
    call,
    comment,
    docstring,
    ensure_imports,
    parse,
    pystr,
    replace_or_append,
    top_level,
    tuple_literal,
)
from karni_cli.project import CliError

NAME = "form"
SUMMARY = "Add a public form: model, viewset, notification, tests, staff pages ({% karni_form %})."

#: The inbox lifecycle every form gets unless --states says otherwise.
DEFAULT_STATES = "new>replied|new>archived|replied>archived"
#: Field types a visitor types or picks. The rest (money, json, ranges...) are not form input.
FORM_TYPES = (
    "str",
    "text",
    "email",
    "url",
    "phone",
    "int",
    "float",
    "decimal",
    "bool",
    "date",
    "datetime",
    "choice",
    "country",
    "file",
    "image",
    "fk",
    "m2m",
)
#: The fields the command adds to every form's model.
STATUS, NOTES, SEARCH = "status", "notes", "search"
ENV_EXAMPLE = Path(".env.example")
ENV_SECTION = "# --- Forms (karni make form) ----------------------------------------------"
_SETTING = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_LISTABLE = frozenset({"str", "email", "url", "phone", "int", "float", "decimal", "bool", "date"})
_LISTABLE |= frozenset({"datetime", "choice", "country", "fk"})


# validation


def form_name(raw: str) -> str:
    """The form's name, snake_case (``booking-request`` becomes ``booking_request``)."""
    name = snake(raw.replace("-", "_"))
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", raw) or not _NAME.match(name):
        raise CliError(
            f"Form name {raw!r} must be a word in snake_case, e.g. contact or booking_request.",
            code="C103",
        )
    return name


def form_fields(tokens: list[str]) -> list[FieldSpec]:
    """The visitor's fields: the model DSL, limited to what a person types or picks."""
    if not tokens:
        raise CliError(
            "karni make form needs the fields a visitor fills, e.g. name:str email:email "
            "message:text.",
            code="C104",
        )
    specs = parse_fields(tokens)
    for spec in specs:
        if spec.name in {STATUS, NOTES}:
            raise CliError(
                f"Field {spec.name!r}: karni make form adds {STATUS} (the inbox lifecycle, "
                f"--states) and {NOTES} (staff-only) itself. Name the visitor's field another "
                "way, e.g. topic or message.",
                code="C104",
            )
        if spec.kind not in FORM_TYPES:
            raise CliError(
                f"Field {spec.name}:{spec.kind}: a public form takes what a visitor types or "
                f"picks ({', '.join(FORM_TYPES)}). Add other columns to the model afterwards.",
                code="C104",
            )
        if spec.is_relation and is_user_target(relation_name(spec)):
            raise CliError(
                f"Field {spec.name}: a visitor cannot pick a user. A form a signed-in user "
                "sends is a model with an owner: karni make model ... --access owned:<field>.",
                code="C104",
            )
    return specs


def setting_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    if not _SETTING.match(raw):
        raise CliError(
            f"--notify {raw!r}: name a Django setting in capitals, e.g. ENQUIRY_RECIPIENTS. "
            "It holds the addresses each new submission is emailed to.",
            code="C106",
        )
    return raw


def states_spec(raw: str | None) -> str:
    spec = (raw or DEFAULT_STATES).strip()
    _states(STATUS, spec)  # raises C370 naming the problem
    return spec


# the model


def _first(specs: list[FieldSpec], kinds: set[str]) -> FieldSpec | None:
    return next((spec for spec in specs if spec.kind in kinds), None)


def searched(specs: list[FieldSpec]) -> list[str]:
    """The fields staff search the inbox by: the short text a visitor typed."""
    return [spec.name for spec in specs if spec.kind in {"str", "email", "phone"}][:4]


def _admin_meta(specs: list[FieldSpec], line: int) -> list[str]:
    shown = [spec.name for spec in specs if spec.kind in _LISTABLE][:4]
    filters = [STATUS, *(spec.name for spec in specs if spec.kind in {"choice", "bool"})][:4]
    search = searched(specs)
    indent = "        "

    def names(head: str, items: list[str]) -> str:
        return tuple_literal(head, [pystr(item) for item in items], indent, line)

    lines = [
        "    class AdminMeta:",
        f"{indent}# The inbox in the admin: newest first, filtered by status.",
        names("list_display = ", [*shown, STATUS, "created_at"]),
        names("list_filter = ", filters),
    ]
    if search:
        lines.append(names("search_fields = ", search))
    lines.append(names("ordering = ", ["-created_at"]))
    return lines


def plan_model(
    ws: Workspace, app: App, model: str, name: str, specs: list[FieldSpec], states: str, role: str
) -> None:
    """``class <Model>(BaseModel)`` with the visitor's fields, the inbox status and notes."""
    from karni_cli.generators.fields import parse_field

    status = parse_field(f"{STATUS}:state:{states}")
    path = models_file(ws, app)
    rel = ws.rel(path)
    line = ws.line_length
    body = render_model_body(
        [*specs, status],
        model=model,
        app_label=app.label,
        resolve=model_gen._targets(ws, app, model, specs),
        line_length=line,
    )
    verbose = humanize(name).lower()
    lines = [
        f"class {model}(BaseModel):",
        docstring(
            f"What a visitor sends with {{% karni_form {pystr(name)} %}} on the public site. "
            f"Visitors fill the fields above {STATUS}. Only role {role!r} reads them.",
            "    ",
            line,
        ),
        "",
    ]
    if body.inner:
        lines += [*body.inner, ""]
    lines += body.lines
    lines.append(
        call(
            f"{NOTES} = models.TextField",
            ["blank=True", 'help_text="Staff only: visitors never see or send it."'],
            "    ",
            line,
        )
    )
    imports = [
        Import("typing", "ClassVar"),
        Import("karni.models", "BaseModel"),
        Import("django.db", "models"),
        *body.imports,
    ]
    search = searched(specs)
    if search and all(spec.name != SEARCH for spec in specs):
        lines += [
            "    # What ?search= and the staff app's search box match, through an index.",
            call(
                f"{SEARCH} = SearchField",
                [f"sources=[{', '.join(map(pystr, search))}]"],
                "    ",
                line,
            ),
        ]
        imports.append(Import("karni.fields", "SearchField"))
    roles = "(" + pystr(role) + ",)"
    head = "        field_roles: ClassVar[dict[str, tuple[str, ...]]] = "
    entries = [f"{pystr(STATUS)}: {roles}", f"{pystr(NOTES)}: {roles}"]
    rule = head + "{" + ", ".join(entries) + "}"
    if len(rule) > line:  # ruff format: one entry per line, trailing comma
        rule = "\n".join([head + "{", *(f"            {entry}," for entry in entries), "        }"])
    plural = pluralize(verbose)
    if plural != f"{verbose}s":  # Django's own plural only adds an s ("enquirys")
        lines += ["", "    class Meta:", f"        verbose_name_plural = {pystr(plural)}"]
    lines += [
        "",
        "    class Karni:",
        "        audit = True  # every change staff make shows on the History tab",
        "        dashboard = True  # counts per status on the staff app's home page",
        comment(
            "Only the role sees or sets these: the API, the form and the admin hide them "
            "from everyone else.",
            "        ",
            line,
        ),
        rule,
        "",
        *_admin_meta(specs, line),
    ]
    text_field = _first(specs, {"str", "email"})
    if text_field is not None:
        lines += ["", "    def __str__(self) -> str:", f"        return self.{text_field.name}"]
    text = ws.read(path) or ""
    text = ensure_imports(ws, rel, text, imports)
    ws.write(path, replace_or_append(ws, rel, text, model, "\n".join(lines)))
    for note in body.notes:
        if "moves" not in note:
            ws.note(note)
    if body.images:
        model_gen.plan_images_extra(ws, body.images)


# the notification


def _email_line(spec: FieldSpec) -> str:
    label = humanize(spec.name)
    value = f"submission.{spec.name}"
    if spec.kind == "text":
        return f"{label}:\n{{{{ {value} }}}}"
    if spec.kind in {"choice", "country"}:
        return f"{label}: {{{{ submission.get_{spec.name}_display }}}}"
    if spec.kind == "date":
        return f'{label}: {{{{ {value}|date:"j M Y" }}}}'
    if spec.kind == "datetime":
        return f'{label}: {{{{ {value}|date:"j M Y, H:i" }}}}'
    if spec.kind == "bool":
        return f'{label}: {{{{ {value}|yesno:"yes,no" }}}}'
    if spec.kind in {"file", "image"}:
        return f"{label}: {{{{ {value}.name }}}}"
    if spec.kind == "m2m":
        return f'{label}: {{{{ {value}.all|join:", " }}}}'
    return f"{label}: {{{{ {value} }}}}"


def email_templates(
    ws: Workspace, app: App, name: str, specs: list[FieldSpec], setting: str
) -> str:
    """The subject and body templates. Returns the template stem for the listener."""
    verbose = humanize(name).lower()
    stem = f"{app.label}/email/{name}"
    folder = app.file("templates", app.label, "email")
    titled = next((s for s in specs if s.name in {"subject", "title", "topic"}), None)
    named = _first(specs, {"str"})
    if titled is not None and titled.kind in {"str", "choice"}:
        shown = (
            f"submission.get_{titled.name}_display"
            if titled.kind == "choice"
            else f"submission.{titled.name}"
        )
        subject = f"New {verbose}: {{{{ {shown} }}}}"
    elif named is not None:
        subject = f"New {verbose} from {{{{ submission.{named.name} }}}}"
    else:
        subject = f"New {verbose} from the website"
    ws.create(
        folder / f"{name}_subject.txt",
        f"{{# The subject of the email each new {verbose} sends to settings.{setting}. One line. #}}\n"
        f"{subject}\n",
    )
    email = _first(specs, {"email"})
    body = [
        (
            f"{{# The email each new {verbose} sends to settings.{setting} (karni_site.notify). "
            "Plain text, so autoescape is off. Edit it freely. #}"
        ),
        f"{{% autoescape off %}}A new {verbose} arrived from the website.",
        "",
        *(_email_line(spec) for spec in specs if spec.kind != "text"),
        "",
    ]
    for spec in specs:
        if spec.kind == "text":
            body += [_email_line(spec), ""]
    if email is not None:
        body.append(f"Reply to this email to answer {{{{ submission.{email.name} }}}}.")
    if ws.is_dir("frontend"):
        body.append(
            f"Staff app: {{{{ frontend_url }}}}/{default_route(pascal(name))}/{{{{ submission.pk }}}}"
        )
    body += ["In the admin: {{ admin_path }}{% endautoescape %}", ""]
    ws.create(folder / f"{name}_body.txt", "\n".join(body))
    return stem


def plan_listener(
    ws: Workspace, app: App, model: str, name: str, specs: list[FieldSpec], setting: str, stem: str
) -> str:
    """``@on_created(<Model>, queued=True)`` calling ``notify_recipients``. Returns its name."""
    function = f"notify_{name}"
    param = name if name != function else "row"
    line = ws.line_length
    email = _first(specs, {"email"})
    args = [param, f"setting={pystr(setting)}", f"template={pystr(stem)}"]
    if email is not None:
        args.append(f"reply_to={param}.{email.name}")
    lines = [
        f"@on_created({model}, queued=True)",
        f"def {function}({param}: {model}) -> None:",
        docstring(
            f"Emails each new {humanize(name).lower()} to settings.{setting} (after commit).",
            "    ",
            line,
        ),
        call("notify_recipients", args, "    ", line),
    ]
    path = app.file("listeners.py")
    rel = ws.rel(path)
    imports = [
        Import("karni.events", "on_created"),
        Import("karni_site.notify", "notify_recipients"),
        Import(f"{app.module}.models", model),
    ]
    text = ensure_imports(ws, rel, ws.read(path) or "", imports)
    ws.write(path, replace_or_append(ws, rel, text, function, "\n".join(lines)))
    return function


def plan_setting(ws: Workspace, name: str, setting: str) -> None:
    """``SETTING = env.list("SETTING", default=[])`` in config/settings.py, and .env.example."""
    rel = SETTINGS.as_posix()
    text = ws.read(SETTINGS)
    if text is None:
        raise CliError(f"{rel} not found. Run inside a Karni project.", code="C001")
    if top_level(parse(ws, rel, text), setting) is None:
        block = (
            comment(
                f"Who is emailed each new {humanize(name).lower()} (karni make form {name} "
                f"--notify). Comma-separated in .env: {setting}=team@example.com",
                "",
                ws.line_length,
            )
            + f"\n{setting} = env.list({pystr(setting)}, default=[])  # noqa: F821\n"
        )
        ws.write(SETTINGS, append(text, block))
    example = ws.read(ENV_EXAMPLE)
    if example is not None and not re.search(rf"^#?\s*{setting}=", example, re.MULTILINE):
        lines = example.rstrip("\n").split("\n")
        if ENV_SECTION not in lines:
            lines += ["", ENV_SECTION]
        lines += [
            f"# Who is emailed each new {humanize(name).lower()} form submission, comma-separated.",
            f"# {setting}=team@example.com",
        ]
        ws.write(ENV_EXAMPLE, "\n".join(lines) + "\n")


# the site


def _design_record(ws: Workspace) -> dict[str, Any] | None:
    text = ws.read(Path(".karni") / "design.json")
    if not text:
        return None
    try:
        record = json.loads(text)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _page_keys(record: dict[str, Any]) -> dict[str, str]:
    """Template name → the first part of its blocks' keys, as the import gave them."""
    found: dict[str, str] = {}
    base = record.get("base")
    if isinstance(base, dict) and base.get("template"):
        found[str(base["template"])] = "shared"
    for entry in record.get("partials") or []:
        if isinstance(entry, dict) and entry.get("template"):
            found[str(entry["template"])] = "shared"
    for key in ("pages", "error_pages"):
        for entry in record.get(key) or []:
            if isinstance(entry, dict) and entry.get("template"):
                name = str(entry.get("name") or "")
                found[str(entry["template"])] = re.sub(r"[^a-z0-9_]+", "_", name.lower()) or "page"
    return found


def design_forms(ws: Workspace) -> list[tuple[str, DesignForm]]:
    """``(template path, form)`` for every ``<form>`` in the imported design's templates."""
    return [(path, form) for path, form, _page in _design_forms(ws)]


def _design_forms(ws: Workspace) -> list[tuple[str, DesignForm, str]]:
    """``(template path, form, page key)`` for every ``<form>`` of the imported templates."""
    record = _design_record(ws)
    if record is None:
        return []
    label = str(record.get("app") or "")
    app = next((a for a in local_apps(ws) if label in (a.label, a.module)), None)
    if app is None:
        return []
    pages = _page_keys(record)
    found: list[tuple[str, DesignForm, str]] = []
    for template, page in pages.items():
        path = app.file("templates", template)
        source = ws.read(path)
        if source is None:
            continue
        found += [(ws.rel(path), form, page) for form in forms_in(source)]
    return found


def _editable(ws: Workspace) -> bool:
    """Whether the import made the site editable (``--editable``)."""
    record = _design_record(ws) or {}
    return bool((record.get("editable") or {}).get("enabled"))


def design_notes(ws: Workspace, name: str, specs: list[FieldSpec]) -> None:
    """Which imported template holds the ``<form>`` this one replaces, and the tag that keeps it.

    The design's controls are matched to the model's fields by name, then by
    their label and type (:func:`karni_cli.design.forms.match_fields`), and
    the notes say which control fills which field and which fill none.
    """
    found = _design_forms(ws)
    if not found:
        return
    fields = {spec.name: spec.kind for spec in specs}
    best = best_match([form for _, form, _page in found], fields)
    for template, form, _page in found:
        mark = form is best
        ws.note(
            f"design: {template}:{form.line}: <form"
            + (f' id="{form.id}"' if form.id else "")
            + (f' action="{form.action}"' if form.action else "")
            + f"> with {', '.join(form.names) or 'no named fields'}"
            + (f" (the fields of {name})" if mark else "")
        )
    if best is None:
        ws.note(
            f'design: no <form> there has the fields of {name}. Put {{% karni_form "{name}" %}} '
            "where the form belongs."
        )
        return
    template, page = next((t, p) for t, form, p in found if form is best)
    matches, unmatched = match_fields(best, fields)
    ws.note(
        "fields: the design's form fills "
        + ", ".join(match.describe(best) for match in matches)
        + "."
    )
    editable = f"{page}.{name}" if _editable(ws) else ""
    filled = {match.model for match in matches}
    extra = [spec.name for spec in specs if spec.name not in filled]
    lines = [
        f"replace: in {template}, replace that <form> ... </form> (line {best.line}) with:",
        f"    {suggest_tag(name, best, fields, editable=editable)}",
    ]
    if unmatched:
        lines.append(
            f"  The design's form also asks for {', '.join(unmatched)}, which no field of {name} "
            "fills: add them to the command, rename a field to match, or leave them out."
        )
    if extra:
        lines.append(
            f"  {name} also has {', '.join(extra)}, which the design's form does not show: the "
            'tag renders them too (fields="..." chooses which).'
        )
    if editable:
        lines.append(
            f'  editable="{editable}": the labels, placeholders, button and sent message are '
            f"blocks the client edits in the admin (Page content, {editable}.*)."
        )
    ws.note("\n".join(lines))


# the tests


def _sample(spec: FieldSpec) -> str:
    """A Python expression for a valid value of ``spec`` in a multipart post."""
    if spec.kind == "email":
        return pystr("ada@example.com")
    if spec.kind == "text":
        return pystr("Hello. This is a sample message.")
    if spec.kind == "url":
        return pystr("https://example.com/")
    if spec.kind == "phone":
        return pystr("+14155550123")
    if spec.kind in {"int", "decimal"}:
        return pystr("3")
    if spec.kind == "float":
        return pystr("1.5")
    if spec.kind == "bool":
        return pystr("true")
    if spec.kind == "date":
        return pystr("2030-01-15")
    if spec.kind == "datetime":
        return pystr("2030-01-15T10:30")
    if spec.kind == "choice":
        first = re.split(r"[|,]", ":".join(spec.args))[0].strip()
        return pystr(first)
    if spec.kind == "country":
        return pystr("US")
    if spec.kind == "file":
        return f"file_upload({pystr(spec.name)})"
    if spec.kind == "image":
        return f"image_upload({pystr(spec.name)})"
    if spec.kind in {"fk", "m2m"}:
        created = f"str(create({pystr(_relation_label(spec))}).pk)"
        return f"[{created}]" if spec.kind == "m2m" else created
    size = int(spec.args[0]) if spec.args and spec.args[0].isdigit() else 255
    named = spec.name in {"name", "full_name", "your_name"}
    text = "Ada Lovelace" if named else f"A sample {humanize(spec.name).lower()}"
    return pystr(text[:size])


def _relation_label(spec: FieldSpec) -> str:
    """``app_label.Model`` for ``create()``: the DSL's target, qualified by the form's app."""
    return relation_name(spec)


def render_tests(
    ws: Workspace,
    app: App,
    model: str,
    viewset: str,
    name: str,
    specs: list[FieldSpec],
    *,
    setting: str | None,
    role: str,
    first_state: str,
) -> str:
    """The form's test module, ruff-clean in the project's layout."""
    route = default_route(model)
    verbose = humanize(name).lower()
    required = [spec for spec in specs if not spec.optional]
    sample = required or specs
    email = _first(specs, {"email"})
    lines = [
        docstring(
            f"The {verbose} form (karni make form {name}): anyone may send it, role {role!r} "
            "reads it.",
            "",
            ws.line_length,
        ),
        "",
        f"API = {pystr('/api/' + route + '/')}",
        "",
        "",
        "def valid() -> dict[str, Any]:",
        '    """A submission that passes every check (a new dict, and new files, each call)."""',
        "    return {",
        *(f"        {pystr(spec.name)}: {_sample(spec)}," for spec in sample),
        "    }",
        "",
        "",
        "@pytest.fixture(autouse=True)",
        "def _in_process(settings: Settings, tmp_path: Path) -> None:",
        "    settings.CELERY_TASK_ALWAYS_EAGER = True  # queued listeners run inside the test",
        "    settings.CELERY_TASK_EAGER_PROPAGATES = True",
        "    settings.MEDIA_ROOT = str(tmp_path)  # uploads go to a folder the test owns",
    ]
    if setting:
        lines.append(f'    settings.{setting} = ["team@example.com"]')
    lines += [
        "",
        "",
        "def test_anyone_may_send_it(client: Client) -> None:",
        "    response = client.post(API, valid())",
        "    assert response.status_code == 201, response.content",
        f"    assert {model}.objects.get().{STATUS} == {pystr(first_state)}",
        "",
        "",
        "def test_it_works_without_javascript(client: Client) -> None:",
        f'    form = reverse("karni_site:form", args=[{pystr(name)}])',
        '    sent = client.post(form, {**valid(), "karni-next": "/"})',
        f'    assert (sent.status_code, sent["Location"]) == (303, "/?sent={name}")',
        "    # Nothing filled in: the page comes back with the errors (here the plain page,",
        "    # since /no-such-page/ is not a page of the site).",
        '    refused = client.post(form, {"karni-next": "/no-such-page/"})',
        "    assert refused.status_code == 400",
        f"    assert {model}.objects.count() == 1",
        "",
        "",
    ]
    if setting:
        lines += [
            "def test_the_recipients_are_emailed(",
            "    client: Client, django_capture_on_commit_callbacks: Callable[..., Any]",
            ") -> None:",
            "    with django_capture_on_commit_callbacks(execute=True):",
            "        client.post(API, valid())",
            '    assert [message.to for message in mail.outbox] == [["team@example.com"]]',
        ]
        if email is not None and not email.optional:
            lines.append('    assert mail.outbox[0].reply_to == ["ada@example.com"]')
        lines += ["", ""]
    else:
        lines += [
            "def test_nobody_is_emailed(",
            "    client: Client, django_capture_on_commit_callbacks: Callable[..., Any]",
            ") -> None:",
            "    with django_capture_on_commit_callbacks(execute=True):",
            "        client.post(API, valid())",
            "    assert mail.outbox == []",
            "",
            "",
        ]
    lines += [
        "def test_visitors_cannot_set_the_staff_fields(client: Client) -> None:",
        f'    client.post(API, {{**valid(), "{STATUS}": "x", "{NOTES}": "set by a visitor"}})',
        f"    row = {model}.objects.get()",
        f'    assert (row.{STATUS}, row.{NOTES}) == ({pystr(first_state)}, "")',
        "",
        "",
        "def test_sending_is_rate_limited(client: Client, settings: Settings) -> None:",
        '    settings.KARNI_PUBLIC_CREATE_RATE = "2/hour"',
        "    codes = [client.post(API, valid()).status_code for _ in range(3)]",
        "    assert codes == [201, 201, 429]",
        "",
        "",
        "def test_only_the_role_reads_it(client: Client, client_as: Callable[..., Any]) -> None:",
        "    client.post(API, valid())",
        "    assert client.get(API).status_code in (401, 403)",
        "    assert client_as().get(API).status_code == 403",
        f"    staff = client_as({pystr(role)}).get(API)",
        '    assert staff.status_code == 200 and staff.json()["count"] == 1',
        f'    assert staff.json()["results"][0]["{NOTES}"] == ""',
        "",
        "",
        "def test_the_role_works_the_inbox_through_the_api() -> None:",
        f"    assert_crud({viewset}, {pystr(role)})",
    ]
    text = "\n".join(lines) + "\n"
    imports = [
        Import("collections.abc", "Callable"),
        Import("pathlib", "Path"),
        Import("typing", "Any"),
        Import("pytest"),
        Import("django.core", "mail"),
        Import("django.test", "Client"),
        Import("django.urls", "reverse"),
        Import("karni.testing", "assert_crud"),
        Import("pytest_django", "Settings"),
        Import(f"{app.module}.models", model),
        Import(f"{app.module}.viewsets", viewset),
    ]
    if any(spec.kind == "file" for spec in sample):
        imports.append(Import("karni.testing.api", "file_upload"))
    if any(spec.kind == "image" for spec in sample):
        imports.append(Import("karni.testing.api", "image_upload"))
    if any(spec.is_relation for spec in sample):
        imports.append(Import("karni.testing.factories", "create"))
    head = "pytestmark = pytest.mark.django_db\n"
    text = text.replace("\nAPI = ", f"\n{head}\nAPI = ", 1)
    return ensure_imports(ws, "tests/test.py", text, imports)


# planning


def plan(
    ws: Workspace,
    app: App,
    raw_name: str,
    tokens: list[str],
    *,
    notify: str | None,
    states: str | None,
    role: str,
) -> str:
    """Plan every file of the form ``raw_name``. Returns its name."""
    name = form_name(raw_name)
    model = pascal(name)
    specs = form_fields(tokens)
    setting = setting_name(notify)
    spec = states_spec(states)
    first_state = _states(STATUS, spec)[0][0]
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", role):
        raise CliError(f"--role {role!r}: name a role (a group), e.g. staff.", code="C106")
    plan_model(ws, app, model, name, specs, spec, role)
    search = searched(specs) if all(s.name != SEARCH for s in specs) else []
    access = "public-create" if role == viewset_gen.PUBLIC_READ_WRITER else f"public-create:{role}"
    viewset_gen.plan(ws, app, model, access=access, search=search)
    if setting:
        stem = email_templates(ws, app, name, specs, setting)
        function = plan_listener(ws, app, model, name, specs, setting, stem)
        plan_setting(ws, name, setting)
        ws.note(
            f"notify: {app.module}.listeners.{function} emails each new {model} to settings."
            f"{setting} (queued, after commit), from {app.label}/templates/{stem}_*.txt"
        )
    else:
        ws.note(f"notify: none (add --notify SETTING to email each new {model})")
    tests = app.file("tests")
    if not ws.exists(tests / "__init__.py"):
        ws.create(tests / "__init__.py", "")
    ws.create(
        tests / f"test_{name}_form.py",
        render_tests(
            ws,
            app,
            model,
            f"{model}ViewSet",
            name,
            specs,
            setting=setting,
            role=role,
            first_state=first_state,
        ),
    )
    if ws.is_dir("frontend"):
        model_gen.plan_chain(ws, app, model, ["page"], access=None, search=[])
    site_gen.wire_site_module(ws)
    site_gen.wire_site_urls(ws)
    if role != viewset_gen.PUBLIC_READ_WRITER:
        ws.note(
            f"role: declare {role!r} in KARNI_ROLES (config/settings.py): field_roles and the "
            "viewset name it, and karni check refuses a role nobody declared (E212)."
        )
    ws.note(f'tag: {{% load karni_site %}} then {{% karni_form "{name}" %}} in a site template')
    design_notes(ws, name, specs)
    return name


def command(
    name: str = typer.Argument(
        ..., help="The form's name, snake_case: contact, booking_request, newsletter."
    ),
    fields: list[str] | None = typer.Argument(
        None,
        help=(
            "The fields a visitor fills, as name:type[:arg][?] (karni make model's DSL): str "
            "text email url phone int float decimal bool date datetime choice:a|b country file "
            "image fk:Model m2m:Model. A trailing ? makes a field optional."
        ),
        show_default=False,
    ),
    notify: str | None = typer.Option(
        None,
        "--notify",
        help=(
            "A Django setting (e.g. ENQUIRY_RECIPIENTS) holding the addresses each new "
            "submission is emailed to, by a queued listener. Without it nothing is sent."
        ),
    ),
    states: str | None = typer.Option(
        None,
        "--states",
        help=(
            f"The inbox lifecycle of the status field (default {DEFAULT_STATES}): "
            "a,b,c moves in order, and a>b|a>c declares each move. The first state is where a "
            "submission starts."
        ),
    ),
    role: str = typer.Option(
        viewset_gen.PUBLIC_READ_WRITER,
        "--role",
        help="The role that reads, answers and deletes submissions (default staff).",
    ),
    migrate: bool = typer.Option(
        False, "--migrate", help="Run `karni make migration` for the app afterwards."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add a public form NAME with FIELDS: it works with and without JavaScript, safely.

    Writes the model (the visitor's fields, a status lifecycle and staff-only
    notes, hidden from visitors through field_roles, an admin inbox), a
    BaseViewSet with create=Public() (Karni's rate limit and honeypot apply
    by themselves), the tests, the staff app's pages when there is a
    frontend, and with --notify a queued email to the addresses in that
    setting. It wires karni-site and its form view. Put
    {% karni_form "NAME" %} in a site template: the output names the
    imported design's <form> it replaces, with the arguments that keep its
    markup.

    Example: karni make form contact name:str email:email subject:str
    message:text --notify ENQUIRY_RECIPIENTS
    """
    ws = project_workspace(force)
    target = resolve_app(ws, app)
    form = plan(ws, target, name, fields or [], notify=notify, states=states, role=role)
    if not migrate:
        ws.note(f"next: karni make migration --app {target.label}, then karni test")
    ws.commit(dry_run=dry_run)
    if dry_run:
        return
    record_guidance(ws.root, site_gen.SITE_MODULE)
    if migrate:
        code = migration_gen.run(ws.root, target.label)
        if code != 0:
            raise typer.Exit(code)
    typer.echo(f'done: {{% karni_form "{form}" %}} is ready for a page.')
