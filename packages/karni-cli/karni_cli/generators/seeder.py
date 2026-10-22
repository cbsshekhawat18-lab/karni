"""``karni make seeder <Model>`` — a ``Seeder`` in ``<app>/seeds.py`` for ``karni seed``.

``karni seed`` already fills every model with values inferred from field
names and types. A seeder steers one model: ``Meta.count`` pins its rows per
run (``0`` skips it) and any class attribute overrides one field with a
value or a factory-boy declaration; override ``seed()`` for full control.
"""

from __future__ import annotations

import typer

from karni_cli.generators.core import (
    APP_OPTION,
    DRY_RUN_OPTION,
    FORCE_OPTION,
    App,
    Workspace,
    project_workspace,
    resolve_app,
)
from karni_cli.generators.introspect import require_model
from karni_cli.generators.naming import require_pascal
from karni_cli.generators.pysource import Import, docstring, ensure_imports, replace_or_append
from karni_cli.project import CliError

NAME = "seeder"
SUMMARY = "Add a Seeder to <app>/seeds.py: per-model rows and values for karni seed."


def plan(ws: Workspace, app: App, model_name: str, *, count: int | None = None) -> str:
    """Plan ``<Model>Seeder``; returns the class name."""
    if count is not None and count < 0:
        raise CliError("--count must be 0 or more (0 skips the model).", code="C106")
    model = require_model(ws, app, require_pascal(model_name, "Model"))
    path = model.app.file("seeds.py")
    rel = ws.rel(path)
    line = ws.line_length
    text = ws.read(path)
    if text is None:
        text = docstring(f"{model.app.label} demo data for `karni seed`.", "", line) + "\n"
    class_name = f"{model.name}Seeder"
    meta = ["    class Meta:", f"        model = {model.name}"]
    if count is not None:
        meta.append(f"        count = {count}")
    block = "\n".join(
        [
            f"class {class_name}(Seeder):",
            docstring(
                f"Demo rows for {model.name}; undeclared fields are inferred from their names.",
                "    ",
                line,
            ),
            "",
            *meta,
            "",
            "    # Steer a field with a value or a factory-boy declaration, e.g.:",
            '    # status = factory.Iterator(["published", "draft"])',
        ]
    )
    text = ensure_imports(
        ws, rel, text, [Import("karni.seeding", "Seeder"), Import(model.import_module, model.name)]
    )
    ws.write(path, replace_or_append(ws, rel, text, class_name, block))
    ws.note(f"seeder: {model.app.module}.seeds.{class_name} — run: karni seed")
    return class_name


def command(
    model: str = typer.Argument(..., help="Model class name (e.g. Event)."),
    count: int | None = typer.Option(
        None, "--count", help="Rows per `karni seed` run for this model (0 skips it)."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `<Model>Seeder(Seeder)` to APP/seeds.py, read by `karni seed`.

    Only needed to steer a model's demo data: Meta.count pins its rows per
    run, and a class attribute overrides a field (a value or a factory-boy
    declaration). Every other field stays inferred from its name and type.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), model, count=count)
    ws.commit(dry_run=dry_run)
