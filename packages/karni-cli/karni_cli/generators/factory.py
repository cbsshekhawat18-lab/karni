"""``karni make factory <Model>`` — an explicit test factory in ``<app>/factories.py``.

Every model already has a generated factory (:mod:`karni.testing.factories`):
fields get realistic values from their names and types. Write an explicit one
only to change some of them — it derives from ``ModelFactory``, so it
declares just what differs, and it then replaces the generated factory
everywhere (tests, related rows, ``karni seed``, the N+1 scaling check).
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

NAME = "factory"
SUMMARY = "Add an explicit test factory to <app>/factories.py (overrides the generated one)."


def plan(ws: Workspace, app: App, model_name: str) -> str:
    """Plan ``<Model>Factory``; returns the class name."""
    model = require_model(ws, app, require_pascal(model_name, "Model"))
    path = model.app.file("factories.py")
    rel = ws.rel(path)
    line = ws.line_length
    text = ws.read(path)
    if text is None:
        text = (
            docstring(f"{model.app.label} test factories: declare only what differs.", "", line)
            + "\n"
        )
    class_name = f"{model.name}Factory"
    block = "\n".join(
        [
            f"class {class_name}(ModelFactory):",
            docstring(
                f"Test rows for {model.name}; undeclared fields keep their generated values.",
                "    ",
                line,
            ),
            "",
            "    class Meta:",
            f"        model = {model.name}",
            "",
            "    # Declare only the fields to change, e.g.:",
            '    # title = factory.Faker("catch_phrase")',
        ]
    )
    text = ensure_imports(
        ws,
        rel,
        text,
        [
            Import("karni.testing.factories", "ModelFactory"),
            Import(model.import_module, model.name),
        ],
    )
    ws.write(path, replace_or_append(ws, rel, text, class_name, block))
    ws.note(f"factory: {model.app.module}.factories.{class_name} (picked up automatically)")
    return class_name


def command(
    model: str = typer.Argument(..., help="Model class name (e.g. Event)."),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `<Model>Factory(ModelFactory)` to APP/factories.py.

    Only needed to change generated values: an explicit factory replaces the
    generated one everywhere (tests, related rows, karni seed), and fields it
    does not declare keep their generated, realistic values.
    """
    ws = project_workspace(force)
    plan(ws, resolve_app(ws, app), model)
    ws.commit(dry_run=dry_run)
