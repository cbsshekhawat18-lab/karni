"""``karni ui detect`` — adopt the project's design system as Karni's tokens and primitives.

    karni ui detect                  detect, write karni-theme.css (+ karni-primitives.tsx)
    karni ui detect --dry-run        print the report and the files; write nothing
    karni ui detect --json           the report as JSON (for agents)
    karni ui detect --source mui     read this source instead of detecting

See :mod:`karni_cli.uitheme` for the detection order and what each source maps.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import typer

from karni_cli.project import CliError
from karni_cli.uitheme import defaults, designsystems, render, shadcn, tailwind, wiring
from karni_cli.uitheme import frontend as frontend_mod
from karni_cli.uitheme import primitives as primitives_mod
from karni_cli.uitheme.frontend import Frontend
from karni_cli.uitheme.model import Detection, Unmapped

ui_app = typer.Typer(
    help="Fit Karni's components to the project's design system.",
    no_args_is_help=True,
    add_completion=False,
)

THEME_FILE = "karni-theme.css"


class Source(str, Enum):
    shadcn = "shadcn"
    tailwind = "tailwind"
    mui = "mui"
    chakra = "chakra"
    mantine = "mantine"
    defaults = "defaults"


@dataclass
class Outcome:
    frontend: Frontend
    detection: Detection
    theme: render.Planned
    primitives: render.Planned | None = None
    primitive_plan: primitives_mod.PrimitivePlan | None = None
    primitive_problem: Unmapped | None = None
    edits: list[wiring.Edit] = field(default_factory=list)
    skipped_sources: list[str] = field(default_factory=list)


def _detect(
    frontend: Frontend, source: Source | None, config: shadcn.ShadcnConfig | None, output: Path
) -> tuple[Detection, list[str]]:
    """The first source that has a theme (or the one ``--source`` names)."""
    passed: list[str] = []
    order = [source] if source is not None else list(Source)
    for candidate in order:
        found: Detection | None = None
        if candidate is Source.shadcn:
            if config is None:
                if source is not None:
                    raise _not_found("shadcn/ui", "components.json is not in the frontend")
                continue
            found = shadcn.detect(frontend, config)
            if found is None:
                passed.append(
                    "shadcn/ui: components.json sets tailwind.cssVariables to false, so its "
                    "components use Tailwind classes, not variables Karni could reference"
                )
        elif candidate is Source.tailwind:
            configured = config.tailwind_config if config is not None else ""
            found = tailwind.detect(frontend, configured, exclude=output)
        elif candidate is Source.defaults:
            found = defaults.detect(frontend)
        else:
            library = next(lib for lib in designsystems.LIBRARIES if lib.source == candidate.value)
            found = designsystems.detect(frontend, library)
            if found is None and frontend.has_dependency(library.package):
                passed.append(
                    f"{library.label}: {library.package} is a dependency, but no "
                    f"{' / '.join(name for name, _ in library.calls)}(...) call with a literal "
                    "theme was found in the source"
                )
            elif found is None and source is not None:
                raise _not_found(library.label, f"{library.package} is not a dependency")
        if found is not None:
            return found, passed
        if source is not None:
            raise _not_found(candidate.value, ". ".join(passed) or "no theme values found")
    raise AssertionError("defaults always detects")  # pragma: no cover


def _not_found(name: str, why: str) -> CliError:
    return CliError(
        f"--source {name}: this frontend has no {name} theme to read ({why}). Run "
        "`karni ui detect` without --source to detect what the frontend has.",
        code="C304",
    )


def _output_path(
    frontend: Frontend, output: Path | None, config: shadcn.ShadcnConfig | None
) -> Path:
    if output is not None:
        path = output if output.is_absolute() else Path.cwd() / output
        if path.suffix != ".css":
            raise CliError(
                f"--output must name a .css file, got {output}. Example: --output "
                f"src/styles/{THEME_FILE}",
                code="C106",
            )
        return path.resolve()
    stylesheet: Path | None = None
    if config is not None and config.css_path:
        candidate = (config.path.parent / config.css_path).resolve()
        stylesheet = candidate if candidate.is_file() else None
    stylesheet = stylesheet or frontend.main_stylesheet()
    if stylesheet is not None:
        return stylesheet.parent / THEME_FILE
    base = frontend.root / "src" if (frontend.root / "src").is_dir() else frontend.root
    return base / THEME_FILE


def plan(
    frontend: Frontend,
    *,
    output: Path | None,
    source: Source | None,
    with_primitives: bool,
    today: str,
) -> Outcome:
    config = shadcn.load_config(frontend)
    theme_path = _output_path(frontend, output, config)
    detection, passed = _detect(frontend, source, config, theme_path)
    theme_text = render.theme_file(detection, date=today, import_after="@karni/ui/styles.css")
    outcome = Outcome(
        frontend,
        detection,
        render.Planned(theme_path, theme_text, render.state(theme_path)),
        skipped_sources=passed,
    )
    outcome.edits.append(wiring.theme_import(frontend, theme_path))

    if with_primitives and config is not None:
        result = primitives_mod.plan(frontend, config)
        if isinstance(result, Unmapped):
            outcome.primitive_problem = result
        elif result.roles:
            outcome.primitive_plan = result
            path = wiring.primitives_location(frontend, result.suffix)
            text = render.primitives_file(
                primitives_mod.render_body(result),
                alias=result.ui_alias,
                date=today,
                missing=[u.name for u in result.missing],
                name=path.name,
            )
            outcome.primitives = render.Planned(path, text, render.state(path))
            outcome.edits.append(wiring.primitives_prop(frontend, path))
        else:
            outcome.primitive_plan = result
    return outcome


def _guard(outcome: Outcome, force: bool) -> None:
    for planned in (outcome.theme, outcome.primitives):
        if planned is None or force or planned.state != "modified" or planned.unchanged:
            continue
        rel = outcome.frontend.rel(planned.path)
        raise CliError(
            f"{rel} was edited since karni ui detect wrote it (or was not written by it), so "
            "it is not overwritten. To keep your edits, compare with --dry-run and copy what "
            "you need. Otherwise, overwrite it with --force or write elsewhere with --output.",
            code="C302",
        )


def _save(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise CliError(
            f"Cannot write {path}: {exc.strerror or exc}. Check the directory's permissions, "
            "or choose another place with --output.",
            code="C008",
        ) from None


def _write(outcome: Outcome) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for planned in (outcome.theme, outcome.primitives):
        if planned is None:
            continue
        rel = outcome.frontend.rel(planned.path)
        if planned.unchanged:
            actions.append({"path": rel, "action": "unchanged"})
            continue
        _save(planned.path, planned.content)
        actions.append({"path": rel, "action": "written"})
    for edit in outcome.edits:
        if edit.done and edit.content and edit.file is not None:
            _save(edit.file, edit.content)
    return actions


def report(outcome: Outcome, actions: list[dict[str, str]], dry_run: bool) -> dict[str, Any]:
    """The machine-readable report (``--json``)."""
    fe = outcome.frontend
    detection = outcome.detection
    data: dict[str, Any] = {
        "source": detection.source,
        "detected": detection.label,
        "frontend": str(fe.root),
        "files_read": detection.files,
        "mapped": [m.as_dict() for m in detection.mappings],
        "not_mapped": [u.as_dict() for u in detection.unmapped],
        "notes": [*detection.notes, *outcome.skipped_sources],
        "primitives": None,
        "files": [],
        "wiring": [edit.as_dict(fe) for edit in outcome.edits],
        "dry_run": dry_run,
    }
    if detection.commented:
        data["defaults"] = [m.as_dict() for m in detection.commented]
    plan_ = outcome.primitive_plan
    if plan_ is not None or outcome.primitive_problem is not None:
        data["primitives"] = {
            "file": fe.rel(outcome.primitives.path) if outcome.primitives else None,
            "registered": plan_.registered if plan_ else [],
            "not_registered": [u.as_dict() for u in plan_.missing] if plan_ else [],
            "problem": outcome.primitive_problem.as_dict() if outcome.primitive_problem else None,
        }
    for planned in (outcome.theme, outcome.primitives):
        if planned is None:
            continue
        rel = fe.rel(planned.path)
        action = next((a["action"] for a in actions if a["path"] == rel), "would write")
        if dry_run and planned.unchanged:
            action = "unchanged"
        entry = {"path": rel, "action": action, "state": planned.state}
        if dry_run:
            entry["content"] = planned.content
        data["files"].append(entry)
    return data


def _text(data: dict[str, Any], outcome: Outcome) -> str:
    lines = [f"karni ui detect: {data['detected']}"]
    if data["files_read"]:
        lines.append(f"Read: {', '.join(data['files_read'])}")
    lines.append("")
    mapped = data["mapped"]
    if mapped:
        lines.append(f"Mapped ({len(mapped)}):")
        width = min(32, max(len(m["from"]) for m in mapped))
        for m in mapped:
            colour = m["to"].startswith("--karni-color-")
            scheme = f" [{m['scheme']}]" if colour and m["scheme"] != "both" else ""
            lines.append(f"  {m['from']:<{width}} -> {m['to']}: {m['value']}{scheme}")
            if m.get("note"):
                lines.append(f"  {'':<{width}}    ({m['note']})")
    elif data.get("defaults"):
        lines.append(
            f"Mapped: nothing. {outcome.frontend.rel(outcome.theme.path)} lists "
            f"{len(data['defaults'])} of Karni's defaults, commented, for you to edit."
        )
    else:
        lines.append("Mapped: nothing.")
    unmapped = data["not_mapped"]
    if unmapped:
        lines += ["", f"Not mapped ({len(unmapped)}):"]
        for u in unmapped:
            lines.append(f"  {u['name']}: {u['reason']}")
            if u.get("suggestion"):
                lines.append(f"      {u['suggestion']}")
    if data["notes"]:
        lines += ["", "Notes:", *(f"  {note}" for note in data["notes"])]
    prims = data["primitives"]
    if prims is not None:
        lines.append("")
        if prims["problem"]:
            problem = prims["problem"]
            lines.append(f"Primitives: not generated: {problem['name']}: {problem['reason']}")
        elif prims["registered"]:
            lines.append(f"Primitives ({prims['file']}): {', '.join(prims['registered'])}")
        else:
            lines.append("Primitives: none of the shadcn/ui components Karni can use exist yet")
        for u in prims["not_registered"]:
            lines.append(f"  not registered: {u['name']}: {u['reason']}")
    lines += ["", "Files:"]
    for entry in data["files"]:
        lines.append(f"  {entry['action']}: {entry['path']}")
    manual = [w for w in data["wiring"] if not w["done"]]
    done = [w for w in data["wiring"] if w["done"]]
    prefix = "would wire" if data["dry_run"] else "wired"
    for wire in done:
        lines.append(f"  {prefix if wire['changed'] else 'ok'}: {wire['message']}")
    if manual:
        lines += ["", "Next:", *(f"  {w['message']}" for w in manual)]
    if data["dry_run"]:
        for entry in data["files"]:
            lines += ["", f"--- {entry['path']} (dry run: not written) ---", entry["content"]]
    return "\n".join(lines).rstrip() + "\n"


@ui_app.command("detect")
def detect(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=f"Where to write {THEME_FILE} (default: next to the main stylesheet).",
        show_default=False,
    ),
    frontend: Path | None = typer.Option(
        None,
        "--frontend",
        help="The frontend directory (default: the current directory if it has package.json, "
        "else ./frontend, else the Karni project's frontend/).",
        show_default=False,
    ),
    source: Source | None = typer.Option(
        None,
        "--source",
        help="Read this source instead of detecting the first one present: shadcn, "
        "tailwind, mui, chakra, mantine or defaults.",
        case_sensitive=False,
        show_default=False,
    ),
    with_primitives: bool = typer.Option(
        True,
        "--primitives/--no-primitives",
        help="For shadcn/ui, also write karni-primitives.tsx (the project's components as "
        "Karni's primitives).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite generated files even if they were edited."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the report and the files, but write nothing."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON (for agents)."),
) -> None:
    """Adopt the frontend's design system: map its theme onto Karni's `--karni-*` tokens.

    It looks for a theme in this order. First shadcn/ui (`components.json`): Karni's
    tokens reference the project's CSS variables with `var()`, and `karni-primitives.tsx`
    registers its components as Karni's primitives. Next a Tailwind theme (`@theme`
    blocks, or the `tailwind.config` that Node evaluates in the project). Then a Material
    UI, Chakra UI or Mantine theme (literal values read from the source). Without any of
    these it uses Karni's defaults, listed for editing.

    Writes one file the project owns, `karni-theme.css`, imported after
    `@karni/ui/styles.css` (wired into `src/main.tsx` when it has the scaffold's import).
    The report lists every token mapped (from, to, value) and every value not mapped, with
    the reason. A generated file edited since is never overwritten without `--force`.

    Example: karni ui detect --dry-run
    """
    fe = frontend_mod.locate(frontend)
    outcome = plan(
        fe,
        output=output,
        source=source,
        with_primitives=with_primitives,
        today=dt.datetime.now().astimezone().date().isoformat(),
    )
    if not dry_run:
        _guard(outcome, force)
    actions = [] if dry_run else _write(outcome)
    data = report(outcome, actions, dry_run)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
    else:
        typer.echo(_text(data, outcome), nl=False)
