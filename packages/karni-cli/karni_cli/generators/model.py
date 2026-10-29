"""``karni make model <Name> [field:type ...]`` — a model on BaseModel.

The field DSL is documented in :mod:`karni_cli.generators.fields`. ``--with
viewset,page,test,factory,seeder`` chains the other generators in the same
run: a viewset (``--access``/``--search`` apply), the list, detail and form
pages for the resource (linked to each other), its API test, an explicit
factory and a seeder. ``-a/--all`` chains viewset, page and test — factories
and seeders are overrides of what Karni already generates, so they are only
written when asked for.
"""

from __future__ import annotations

import typer

from karni_cli import project as project_mod
from karni_cli import pyproject_edit
from karni_cli.generators import apitest as test_gen
from karni_cli.generators import factory as factory_gen
from karni_cli.generators import migration as migration_gen
from karni_cli.generators import page as page_gen
from karni_cli.generators import seeder as seeder_gen
from karni_cli.generators import viewset as viewset_gen
from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    local_apps,
    project_workspace,
    resolve_app,
    split_csv,
)
from karni_cli.generators.fields import (
    FieldSpec,
    RelationTarget,
    images_extra_note,
    is_user_target,
    parse_fields,
    pillow_note,
    reinstall_note,
    relation_name,
    render_model_body,
)
from karni_cli.generators.introspect import models_file, models_in, viewset_for
from karni_cli.generators.naming import default_route, kebab, require_pascal
from karni_cli.generators.pysource import Import, ensure_imports, pystr, replace_or_append
from karni_cli.project import CliError

NAME = "model"
SUMMARY = "Add a model on BaseModel from a field DSL (--with viewset,page,test or -a chains them)."

#: What ``--with`` can chain, in run order.
CHAINABLE = ("viewset", "page", "test", "factory", "seeder")
#: What ``-a/--all`` chains: everything except the explicit overrides (factory, seeder).
ALL = ("viewset", "page", "test")


def _targets(
    ws: Workspace, app: App, model: str, specs: list[FieldSpec]
) -> dict[str, RelationTarget]:
    resolved: dict[str, RelationTarget] = {}
    own = models_in(ws, app)
    for spec in specs:
        if not spec.is_relation:
            continue
        raw = relation_name(spec)
        if is_user_target(raw):
            resolved[spec.name] = RelationTarget("settings.AUTH_USER_MODEL", True, "user")
        elif raw in ("self", model, f"{app.label}.{model}"):
            # The model itself (a course's related courses): Django's "self".
            resolved[spec.name] = RelationTarget(pystr("self"), False, "self")
        elif "." in raw:
            label, _, name = raw.partition(".")
            for other in local_apps(ws):
                if other.label == label and name not in models_in(ws, other):
                    raise CliError(
                        f"Field {spec.name}: app {label} has no model {name}. "
                        f"Create it: karni make model {name} --app {label}",
                        code="C104",
                    )
            resolved[spec.name] = RelationTarget(pystr(raw), False, raw.lower())
        elif raw in own:
            resolved[spec.name] = RelationTarget(pystr(raw), False, f"{app.label}.{raw}".lower())
        else:
            owners = [other for other in local_apps(ws) if raw in models_in(ws, other)]
            if len(owners) != 1:
                where = "several apps" if owners else "no local app"
                raise CliError(
                    f"Field {spec.name}: {where} defines a model {raw!r}. Create it first "
                    f"(karni make model {raw}) or write app.Model, e.g. "
                    f"{spec.name}:{spec.kind}:shop.{raw}.",
                    code="C104",
                )
            target = f"{owners[0].label}.{raw}"
            resolved[spec.name] = RelationTarget(pystr(target), False, target.lower())
    return resolved


#: The extra that installs Pillow, which every ImageField needs.
IMAGES_EXTRA = "images"


def plan_images_extra(ws: Workspace, images: list[str]) -> None:
    """Make the project's ``karni`` dependency ``karni[images]`` for ``images`` (ImageFields).

    The one requirement string in ``pyproject.toml`` is edited in place
    (:mod:`karni_cli.pyproject_edit`), so ``--dry-run`` shows it in the diff.
    A project that lists the extra already is left alone. One the edit cannot
    handle gets the manual step instead, when its Python lacks Pillow.
    """
    has_pillow = project_mod.project_has_module(ws.root, "PIL")
    text = ws.read("pyproject.toml")
    try:
        if text is None:
            raise pyproject_edit.CannotEdit("the project has no pyproject.toml")
        edit = pyproject_edit.add_extra(text, "karni", IMAGES_EXTRA)
    except pyproject_edit.CannotEdit as exc:
        if has_pillow is not True:
            ws.note(f"{pillow_note(images, missing=has_pillow is False)} ({exc}.)")
        return
    if edit is None:
        if has_pillow is False:
            ws.note(reinstall_note(images))
        return
    ws.write("pyproject.toml", edit.text)
    ws.note(images_extra_note(images, edit.before, edit.after))


#: Fields every BaseModel has, which --order may name too.
_BASE_FIELDS = ("created_at", "updated_at", "id")


def _field_option(specs: list[FieldSpec], value: str, option: str) -> str:
    """``--order``/``--key``: a field of the model (``-position`` for descending order)."""
    name = value.lstrip("-") if option == "--order" else value
    if name not in {s.name for s in specs} and name not in _BASE_FIELDS:
        names = ", ".join(s.name for s in specs) or "none"
        raise CliError(
            f"{option} {value}: {name!r} is not a field of the model (fields: {names}). "
            f"Declare it, e.g. {name}:int, or name another.",
            code="C104",
        )
    return value


def plan(
    ws: Workspace,
    app: App,
    name: str,
    field_tokens: list[str],
    *,
    order: str | None = None,
    key: str | None = None,
) -> str:
    """Plan the model class in ``<app>/models.py``; returns the class name.

    ``order`` writes ``Meta.ordering``, ``key`` writes ``Karni.import_key``: the
    field ``karni load`` and imports match rows on (for rows nested under a
    parent, the parent plus that field).
    """
    model = require_pascal(name, "Model name")
    specs = parse_fields(field_tokens)
    try:
        served = viewset_for(ws, app, model) is not None
    except CliError:  # viewsets.py does not parse: that is its own command's to report
        served = False
    if served:
        ws.api_changed()  # its fields are the API's
    path = models_file(ws, app)
    rel = ws.rel(path)
    body = render_model_body(
        specs,
        model=model,
        app_label=app.label,
        resolve=_targets(ws, app, model, specs),
        line_length=ws.line_length,
    )
    lines = [f"class {model}(BaseModel):"]
    if body.inner:
        lines += [*body.inner, ""]
    lines += body.lines
    if order is not None:
        lines += [
            "",
            "    class Meta:",
            f"        ordering = [{pystr(_field_option(specs, order, '--order'))}]",
        ]
    if key is not None:
        lines += [
            "",
            "    class Karni:",
            f"        import_key = {pystr(_field_option(specs, key, '--key'))}",
        ]
    text_field = next((s.name for s in specs if s.is_text), None)
    if text_field is not None:
        lines += ["", "    def __str__(self) -> str:", f"        return self.{text_field}"]
    if len(lines) == 1:
        lines.append("    pass")
    text = ws.read(path) or ""
    text = ensure_imports(ws, rel, text, [Import("karni.models", "BaseModel"), *body.imports])
    ws.write(path, replace_or_append(ws, rel, text, model, "\n".join(lines)))
    for note in body.notes:
        ws.note(note)
    if body.images:
        plan_images_extra(ws, body.images)
    return model


def plan_chain(
    ws: Workspace,
    app: App,
    model: str,
    chain: list[str],
    *,
    access: str | None,
    search: list[str],
    expand: list[str] | None = None,
) -> None:
    """The ``--with`` steps after the model, in :data:`CHAINABLE` order.

    ``expand``: relation fields the detail page asks the API to expand, so it
    shows the related rows' labels instead of raw ids.
    """
    if "viewset" in chain:
        viewset_gen.plan(ws, app, model, access=access, search=search)
    if "page" in chain:
        resource = default_route(model)
        singular = kebab(model)
        specs = [
            page_gen.spec_for(f"{singular}-form", resource=resource, kind="form", path=None),
            page_gen.spec_for(
                f"{singular}-detail", resource=resource, kind="detail", path=None, expand=expand
            ),
            page_gen.spec_for(resource, resource=resource, kind="list", path=None),
        ]
        planned = {path for spec in specs for path in spec.paths}
        for spec in specs:
            page_gen.plan(ws, spec, planned_routes=planned)
    if "test" in chain:
        test_gen.plan(ws, app, model)
    if "factory" in chain:
        factory_gen.plan(ws, app, model)
    if "seeder" in chain:
        seeder_gen.plan(ws, app, model)


def resolve_chain(with_: list[str], all_: bool) -> list[str]:
    chain = [*ALL, *split_csv(with_)] if all_ else split_csv(with_)
    unknown = [item for item in chain if item not in CHAINABLE]
    if unknown:
        raise CliError(
            f"--with {', '.join(unknown)}: unknown (available: {', '.join(CHAINABLE)}).",
            code="C106",
        )
    return [item for item in CHAINABLE if item in chain]


def command(
    name: str = typer.Argument(..., help="Model class name, PascalCase (e.g. Event)."),
    fields: list[str] | None = typer.Argument(
        None,
        help=(
            "Fields as name:type[:arg][?]. Types: str[:len] text int float "
            "decimal[:max:places] bool date datetime url file image uuid choice:a|b fk:Model "
            "m2m:Model o2o:Model. Typed fields (karni.fields): money[:EUR] percent[:min:max] "
            "quantity email[:unique] slug[:source] phone country currency json[:queried] "
            "array:str. A trailing ? makes the field optional."
        ),
        show_default=False,
    ),
    with_: list[str] | None = typer.Option(
        None,
        "--with",
        help="Also generate: viewset, page, test, factory, seeder (comma-separated or repeated).",
    ),
    all_: bool = typer.Option(
        False, "--all", "-a", help="Also generate the viewset, the pages and the API test."
    ),
    access: str | None = typer.Option(
        None,
        "--access",
        help=(
            f"With viewset: {viewset_gen.ACCESS_CHOICES}. public-read: anyone reads, only "
            f"role {viewset_gen.PUBLIC_READ_WRITER!r} (or :<role>) writes. public-create: "
            "anyone creates (a public form), only that role reads and writes."
        ),
    ),
    search: list[str] | None = typer.Option(
        None, "--search", help="With viewset: search_fields (comma-separated)."
    ),
    migrate: bool = typer.Option(
        False, "--migrate", help="Run `karni make migration` for the app afterwards."
    ),
    order: str | None = typer.Option(
        None,
        "--order",
        help="Order rows by this field (Meta.ordering), e.g. position or -created_at.",
    ),
    key: str | None = typer.Option(
        None,
        "--key",
        help="The field karni load and imports match rows on (Karni.import_key). Rows nested "
        "under a parent are matched on the parent plus this field, e.g. position.",
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `class NAME(BaseModel)` with FIELDS to APP/models.py.

    Example: karni make model Event title:str:200 starts_at:datetime
    "status:choice:draft|live" organizer:fk:User 'venue:fk:Venue?' -a
    --access owned:organizer
    """
    ws = project_workspace(force)
    chain = resolve_chain(with_ or [], all_)
    if (access or search) and "viewset" not in chain:
        raise CliError(
            "--access/--search configure the viewset: add --with viewset (or -a).", code="C004"
        )
    target = resolve_app(ws, app)
    if all_ and not ws.is_dir("frontend"):
        chain = [item for item in chain if item != "page"]
        ws.note("note: no frontend/ directory, so pages are skipped.")
    model = plan(ws, target, name, fields or [], order=order, key=key)
    expand = [
        spec.name
        for spec in parse_fields(fields or [])
        if spec.is_relation and not is_user_target(relation_name(spec))
    ]
    plan_chain(ws, target, model, chain, access=access, search=split_csv(search), expand=expand)
    if not migrate:
        ws.note(f"next: karni make migration --app {target.label}")
    ws.commit(dry_run=dry_run)
    if migrate and not dry_run:
        code = migration_gen.run(ws.root, target.label)
        if code != 0:
            raise typer.Exit(code)
