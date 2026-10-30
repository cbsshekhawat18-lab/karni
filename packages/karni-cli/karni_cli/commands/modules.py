"""``karni modules`` (experimental): the module catalog, every module and built-in feature.

    karni modules list [--json]           every entry, added or not, with its questions
    karni modules show NAME [--json]      one entry: what it provides, asks and wires

The entries come from :mod:`karni_cli.catalog`: Karni's own modules and
features (bundled with the CLI, so a module that is not installed shows
too) and the manifests of the modules installed in the project. Inside a
project, a module's state is ``added`` (its app is in the ``# karni:apps``
block), ``installed`` (the project's interpreter has it) or ``available``.
A feature is ``built in``: a setting turns it on.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import typer

from karni_cli import catalog as catalog_mod
from karni_cli.project import CliError, find_project

if TYPE_CHECKING:
    from karni.catalog import Ask, Manifest

    from karni_cli.catalog import Catalog

modules_app = typer.Typer(
    help=(
        "The module catalog (experimental): every module and built-in feature, added or not, "
        "with what it provides and the questions to ask (list, show)."
    ),
    no_args_is_help=True,
    add_completion=False,
)

_JSON_HELP = "Print the entries as JSON (every manifest key, plus state)."


def _load() -> Catalog:
    loaded = catalog_mod.load(find_project())
    for problem in loaded.problems:
        sys.stderr.write(f"warning: C314: {problem}\n")
    return loaded


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    return str(value)


def ask_line(ask: Ask) -> str:
    """One question in one line: the question, the setting, the options and the default."""
    parts = [f"{ask.question} -> {ask.setting}"]
    if ask.options:
        parts.append(("any of " if ask.multiple else "") + " | ".join(map(_value, ask.options)))
    if ask.has_default:
        parts.append(f"default {_value(ask.default)}")
    return ", ".join(parts)


def _entry(loaded: Catalog, manifest: Manifest) -> dict[str, Any]:
    return {**manifest.to_dict(), "state": loaded.state(manifest)}


@modules_app.command("list")
def list_(as_json: bool = typer.Option(False, "--json", help=_JSON_HELP)) -> None:
    """Experimental. Every module and built-in feature: kind, status, state, purpose, questions.

    Modules first, then features. A module is added (in the # karni:apps
    block), installed (the project's interpreter has it) or available. Each
    question names the setting its answer goes to.
    """
    loaded = _load()
    entries = [*loaded.modules, *loaded.features]
    if as_json:
        payload = {"entries": [_entry(loaded, m) for m in entries], "problems": loaded.problems}
        typer.echo(json.dumps(payload, indent=2))
        return
    typer.echo(
        "Modules (karni add NAME, karni remove NAME) and built-in features (a setting, or "
        "features: in karni.yaml). Details: karni modules show NAME."
    )
    width = max((len(m.name) for m in entries), default=0)
    for manifest in entries:
        state = loaded.state(manifest)
        typer.echo(
            f"{manifest.name:<{width}}  {manifest.kind:<7}  {manifest.status:<12}  "
            f"{state:<9}  {manifest.purpose}"
        )
        for ask in manifest.asks:
            typer.echo(f"  ? {ask_line(ask)}")


def _show_lines(loaded: Catalog, manifest: Manifest) -> list[str]:
    provides, wiring = manifest.provides, manifest.wiring
    lines = [
        (
            f"{manifest.name}: {manifest.title} ({manifest.kind}, {manifest.status}, "
            f"{loaded.state(manifest)})"
        ),
        manifest.purpose,
        "Use when: " + "; ".join(manifest.use_when),
    ]
    if manifest.kind == "module":
        extras = ", ".join(f"[{name}] {why}" for name, why in wiring.extras.items())
        lines.append(
            f"Add: karni add {manifest.name} ({manifest.distribution}"
            + (f"; extras {extras}" if extras else "")
            + f"). Remove: karni remove {manifest.name}."
        )
    else:
        spec = f", or features: {manifest.name} in karni.yaml" if manifest.in_spec else ""
        extra = f". Needs {manifest.extra}" if manifest.extra else ""
        lines.append(f"Turn on: {manifest.switch}{spec}{extra}.")
    for label, values in (
        ("Requires", manifest.requires),
        ("Conflicts", manifest.conflicts),
        ("Needs", manifest.services),
        ("Models", provides.models),
        ("Endpoints", provides.endpoints),
        ("Pages", provides.pages),
    ):
        if values:
            lines.append(f"{label}: " + "; ".join(values))
    if provides.ui:
        lines.append(f"UI: {provides.ui}")
    if provides.settings:
        lines.append(
            "Settings: "
            + ", ".join(f"{name} ({'|'.join(types)})" for name, types in provides.settings.items())
        )
    if manifest.asks:
        lines.append("Asks:")
        lines += [f"  {ask_line(ask)}" for ask in manifest.asks]
    if manifest.kind == "module":
        lines.append("Wiring (karni add writes it, karni remove takes it out):")
        lines.append("  INSTALLED_APPS: " + ", ".join(wiring.apps))
        for label, entries in (
            ("MIDDLEWARE", wiring.middleware),
            ("context processors", wiring.context_processors),
        ):
            for entry in entries:
                how = " (printed: add it yourself)" if entry.manual else ""
                lines.append(f"  {label}: {entry.path}, {entry.why}{how}")
        if wiring.urls:
            lines.append(f"  config/urls.py (printed: add it yourself): {wiring.urls}")
        if wiring.kind:
            lines.append(f"  kind: the project gains a {wiring.kind} (app becomes site+app)")
        if wiring.settings:
            lines.append(f"  settings: {wiring.settings}, merged by karni_settings()")
    if manifest.docs:
        lines.append(f"Docs: {manifest.docs}")
    return lines


@modules_app.command("show")
def show(
    name: str = typer.Argument(..., help="A module or feature, e.g. payments or two_factor."),
    as_json: bool = typer.Option(False, "--json", help=_JSON_HELP),
) -> None:
    """Experimental. One module or feature: what it provides, the questions, the wiring.

    For a module: what karni add writes (apps, middleware, context
    processors, the kind) and prints (the URL include, extras), which karni
    remove takes out again. For a feature: the setting that turns it on and
    the extra it needs.
    """
    loaded = _load()
    manifest = loaded.get(name)
    if manifest is None:
        known = ", ".join(sorted(loaded.entries))
        raise CliError(f"The catalog has no {name!r} (it has {known}).", code="C313")
    if as_json:
        typer.echo(json.dumps(_entry(loaded, manifest), indent=2))
        return
    typer.echo("\n".join(_show_lines(loaded, manifest)))
