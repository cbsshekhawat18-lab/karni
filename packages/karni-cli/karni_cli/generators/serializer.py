"""``karni make serializer <Model> --reason "..."`` — an explicit serializer, wired in.

``BaseViewSet(model=X)`` already generates the serializer (K106), and
``APIMeta`` steers its fields; an explicit one is the escape hatch for what
neither covers. So ``--reason`` is mandatory: it becomes the
``# karni: allow(redundant-serializer): <reason>`` marker above the class.
The viewset's ``serializer_class`` is set in the same run.
"""

from __future__ import annotations

import ast
from pathlib import Path

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
from karni_cli.generators.introspect import (
    ModelInfo,
    owned_paths,
    require_model,
    viewset_for,
    viewsets_file,
)
from karni_cli.generators.naming import require_pascal
from karni_cli.generators.pysource import (
    Import,
    ensure_imports,
    pystr,
    replace_or_append,
    replace_span,
    tuple_literal,
)
from karni_cli.project import CliError

NAME = "serializer"
SUMMARY = "Add an explicit serializer (--reason required) and set serializer_class."


def _field_lists(model: ModelInfo, owners: list[str]) -> tuple[list[str], list[str]]:
    bases = model.bases
    head = ["id"]
    tail: list[str] = []
    if bases & {"BaseModel", "TimestampedModel"}:
        tail += ["created_at", "updated_at"]
    if bases & {"BaseModel", "AuditedModel"}:
        tail += ["created_by", "updated_by"]
    fields = [*head, *model.fields, *tail]
    owned = dict.fromkeys(o for o in owners if o in model.fields)  # read + write may both name it
    read_only = [*head, *tail, *owned]
    return fields, read_only


def plan(ws: Workspace, app: App, model_name: str, reason: str) -> str:
    reason = " ".join(reason.split())
    if not reason:
        raise CliError(
            "--reason is required: BaseViewSet already generates this serializer (K106) — say "
            'why an explicit one is needed, e.g. --reason "computed display_name field".',
            code="C109",
        )
    model = require_model(ws, app, model_name)
    found = viewset_for(ws, app, model.name)
    if found is None:
        raise CliError(
            f"No viewset for {model.name} in {ws.rel(viewsets_file(ws, app))} to wire the "
            f"serializer into — karni make viewset {model.name} first.",
            code="C105",
        )
    vs_path, viewset = found
    class_name = f"{model.name}Serializer"
    line = ws.line_length
    fields, read_only = _field_lists(model, owned_paths(viewset))
    block = "\n".join(
        [
            f"# karni: allow(redundant-serializer): {reason}",
            f"class {class_name}(KarniModelSerializer):",
            "    class Meta:",
            f"        model = {model.name}",
            tuple_literal("fields = ", [pystr(f) for f in fields], "        ", line),
            tuple_literal("read_only_fields = ", [pystr(f) for f in read_only], "        ", line),
        ]
    )
    path = app.file("serializers.py")
    rel = ws.rel(path)
    text = ensure_imports(
        ws,
        rel,
        ws.read(path) or "",
        [
            Import("karni.api.serializers", "KarniModelSerializer"),
            Import(model.import_module, model.name),
        ],
    )
    ws.write(path, replace_or_append(ws, rel, text, class_name, block))
    _wire(ws, vs_path, viewset, class_name, f"{app.module}.serializers")
    ws.note(
        f"note: BaseViewSet(model={model.name}) generates a serializer already; "
        f"{class_name} replaces it. Prefer APIMeta for fields/read_only/write_only."
    )
    return class_name


def _wire(ws: Workspace, path: Path, viewset: ast.ClassDef, class_name: str, module: str) -> None:
    """Set ``serializer_class`` on the viewset: after its ``model = X`` line (AST-located)."""
    rel = ws.rel(path)
    text = ws.read(path) or ""
    lines = text.splitlines()
    indent = " " * viewset.body[0].col_offset
    assignment = f"{indent}serializer_class = {class_name}"
    existing = next(
        (
            stmt
            for stmt in viewset.body
            if isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "serializer_class" for t in stmt.targets)
        ),
        None,
    )
    if existing is not None:
        ws.refuse_existing(f"{viewset.name}.serializer_class in {rel}")
        text = replace_span(
            text, existing.lineno, existing.end_lineno or existing.lineno, assignment
        )
    else:
        anchor = next(
            stmt
            for stmt in viewset.body
            if isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets)
        )
        end = anchor.end_lineno or anchor.lineno
        lines.insert(end, assignment)
        text = "\n".join(lines) + "\n"
    text = ensure_imports(ws, rel, text, [Import(module, class_name)])
    ws.write(path, text)


def command(
    model: str = typer.Argument(..., help="Model class name (e.g. Event)."),
    reason: str = typer.Option(
        "", "--reason", help="Why the generated serializer is not enough (required)."
    ),
    app: str | None = APP_OPTION,
    force: bool = FORCE_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Add `<Model>Serializer` to APP/serializers.py and set the viewset's serializer_class.

    BaseViewSet generates the serializer and APIMeta steers it, so an
    explicit one needs --reason. The reason is recorded as the
    `# karni: allow(redundant-serializer): <reason>` marker.
    """
    ws = project_workspace(force)
    target = resolve_app(ws, app)
    plan(ws, target, require_pascal(model.removesuffix("Serializer"), "Model"), reason)
    ws.commit(dry_run=dry_run)
