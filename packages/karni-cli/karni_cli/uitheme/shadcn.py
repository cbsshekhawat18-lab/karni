"""shadcn/ui: Karni's tokens reference the project's own CSS variables.

shadcn keeps its theme in CSS variables on ``:root`` and ``.dark`` in the
stylesheet ``components.json`` names. Karni's tokens point at them with
``var()`` (never copies), declared on ``:root, .dark`` so the project's
theme, dark mode and later edits flow through live:

- Tailwind 3 format, HSL channels (``--primary: 222.2 47.4% 11.2%``):
  ``--karni-color-primary: hsl(var(--primary))``;
- Tailwind 4 format, full colours (``--primary: oklch(...)``):
  ``--karni-color-primary: var(--primary)``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karni_cli.project import CliError
from karni_cli.uitheme import css
from karni_cli.uitheme.frontend import Frontend
from karni_cli.uitheme.model import (
    COLOR_ROLES,
    RADIUS_NAMES,
    Detection,
    color_token,
    radius_token,
    references_karni,
    shadow_token,
)

#: shadcn's variable for each Karni token beyond the colours (read from :root).
EXTRA_VARIABLES: dict[str, str] = {
    "--radius": "--karni-radius",
    "--font-sans": "--karni-font-sans",
    "--font-mono": "--karni-font-mono",
    "--shadow-sm": shadow_token("sm"),
    "--shadow": shadow_token("DEFAULT"),
    "--shadow-md": shadow_token("md"),
    "--shadow-lg": shadow_token("lg"),
    "--spacing": "--karni-space-unit",
    "--tracking-tight": "--karni-font-tracking-tight",
    "--tracking-wide": "--karni-font-tracking-wide",
}


@dataclass
class ShadcnConfig:
    path: Path
    data: dict[str, Any]

    @property
    def css_path(self) -> str:
        tailwind = self.data.get("tailwind")
        return str(tailwind.get("css", "")) if isinstance(tailwind, dict) else ""

    @property
    def tailwind_config(self) -> str:
        tailwind = self.data.get("tailwind")
        return str(tailwind.get("config", "") or "") if isinstance(tailwind, dict) else ""

    @property
    def css_variables(self) -> bool:
        tailwind = self.data.get("tailwind")
        return not (isinstance(tailwind, dict) and tailwind.get("cssVariables") is False)

    @property
    def tsx(self) -> bool:
        return self.data.get("tsx", True) is not False

    def alias(self, name: str) -> str | None:
        aliases = self.data.get("aliases")
        if not isinstance(aliases, dict):
            return None
        value = aliases.get(name)
        return str(value) if value else None

    @property
    def ui_alias(self) -> str | None:
        ui = self.alias("ui")
        if ui:
            return ui
        components = self.alias("components")
        return f"{components}/ui" if components else None


def load_config(frontend: Frontend) -> ShadcnConfig | None:
    path = frontend.root / "components.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CliError(
            f"{path} is not valid JSON ({exc}). karni ui detect reads shadcn/ui's stylesheet "
            "path and aliases from it. Fix the file (npx shadcn@latest init rewrites it), or "
            "pass --source to read another theme source.",
            code="C303",
        ) from None
    if not isinstance(data, dict):
        raise CliError(
            f"{path} is not a JSON object, so it is not shadcn/ui's components.json. Fix or "
            "remove it, or pass --source to read another theme source.",
            code="C303",
        )
    return ShadcnConfig(path, data)


def detect(frontend: Frontend, config: ShadcnConfig) -> Detection | None:
    """Map the project's shadcn variables, or None when there are none to reference."""
    if not config.css_variables:
        return None
    stylesheet_path = _stylesheet(frontend, config)
    sheet = css.parse(frontend.read(stylesheet_path))
    light = sheet.variables(":root")
    dark = sheet.variables(".dark")
    theme = sheet.theme()
    if not light and not dark:
        raise CliError(
            f"{frontend.rel(stylesheet_path)} (components.json tailwind.css) declares no CSS "
            "variables on :root or .dark, so there is no shadcn/ui theme to map. Run "
            "`npx shadcn@latest init` to write them, or pass --source to read another theme "
            "source.",
            code="C303",
        )
    primary = light.get("--primary") or dark.get("--primary") or ""
    channels = css.is_hsl_channels(primary)
    if channels:
        label = "shadcn/ui (Tailwind 3 format: HSL channels, hsl(var(--x)))"
    else:
        label = f"shadcn/ui (Tailwind 4 format: full colours, {css.colour_function(primary)})"
    detection = Detection(
        "shadcn", label, files=[frontend.rel(config.path), frontend.rel(stylesheet_path)]
    )
    names = {**light, **dark}
    used: set[str] = set()

    for role in COLOR_ROLES:
        variable = f"--{role}"
        value = light.get(variable, dark.get(variable))
        if value is None:
            continue
        used.add(variable)
        if references_karni(value):
            detection.skip(variable, "already reads a Karni token (circular): left out")
            continue
        wrapped = f"hsl(var({variable}))" if css.is_hsl_channels(value) else f"var({variable})"
        detection.add(variable, color_token(role), wrapped, "both")

    if "--destructive-foreground" not in names and "--destructive" in names:
        detection.add(
            "(none)",
            color_token("destructive-foreground"),
            "white",
            "both",
            note=(
                "this shadcn/ui version has no --destructive-foreground (its destructive "
                "button sets its own text colour: white, or text-destructive on a tint). "
                "Karni's destructive button is solid, so its text is white"
            ),
        )

    for variable, token in EXTRA_VARIABLES.items():
        if variable in names:
            used.add(variable)
            detection.add(variable, token, f"var({variable})", "both")

    _radii_from_theme(detection, theme)
    _fonts_from_theme(detection, theme, names)

    _report_unused(detection, names, used)
    if dark:
        detection.notes.append(
            f".dark redefines {len(dark)} variables, and Karni's tokens follow them through var()."
        )
    else:
        detection.notes.append("No .dark block: dark mode keeps the same variables.")
    return detection


def _stylesheet(frontend: Frontend, config: ShadcnConfig) -> Path:
    relative = config.css_path
    if not relative:
        raise CliError(
            f"{config.path} has no tailwind.css entry, so karni ui detect cannot tell which "
            'stylesheet holds the shadcn/ui variables. Add it ("tailwind": {"css": '
            '"src/index.css"}), or pass --source to read another theme source.',
            code="C303",
        )
    path = (config.path.parent / relative).resolve()
    if not path.is_file():
        raise CliError(
            f"{config.path.name} names the stylesheet {relative} (tailwind.css), which does not "
            f"exist under {config.path.parent}. Fix the path in components.json, or pass "
            "--source to read another theme source.",
            code="C303",
        )
    return path


_THEME_RADIUS = re.compile(r"^--radius-(sm|md|lg|xl)$")


def _radii_from_theme(detection: Detection, theme: dict[str, str]) -> None:
    """Tailwind 4 shadcn derives its radii in ``@theme inline``: Karni copies the same formulas."""
    for variable, value in theme.items():
        match = _THEME_RADIUS.match(variable)
        if not match or references_karni(value) or "var(--radius" not in value:
            continue
        detection.add(f"@theme {variable}", radius_token(match.group(1)), value, "both")
    if any(m.source.startswith("@theme --radius-") for m in detection.mappings):
        return
    if detection.has("--karni-radius"):
        detection.notes.append(
            "Radii: --karni-radius reads --radius, and sm, md and xl derive from it as shadcn/ui "
            "derives them (-4px, -2px, +4px)."
        )


def _fonts_from_theme(
    detection: Detection, theme: dict[str, str], variables: dict[str, str]
) -> None:
    """Fonts declared in ``@theme`` (shadcn 4 writes ``--font-sans`` there)."""
    for name in ("sans", "mono"):
        variable = f"--font-{name}"
        token = f"--karni-font-{name}"
        value = theme.get(variable)
        if variable in variables or value is None or references_karni(value):
            continue
        detection.add(f"@theme {variable}", token, value, "both")
    for variable in theme:
        if variable.startswith("--font-") and variable not in ("--font-sans", "--font-mono"):
            detection.skip(
                f"@theme {variable}",
                "Karni has sans and mono font tokens only (headings use the sans font)",
            )


def _report_unused(detection: Detection, variables: dict[str, str], used: set[str]) -> None:
    families: dict[str, list[str]] = {}
    for variable in variables:
        if variable in used:
            continue
        stem = variable[2:].split("-", 1)[0]
        families.setdefault(stem, []).append(variable)
    for stem, members in families.items():
        if stem == "sidebar":
            detection.skip(
                ", ".join(members),
                "Karni has no sidebar tokens (its Layout reads background, border and accent)",
            )
            continue
        for variable in members:
            if stem == "radius" and variable in {f"--radius-{n}" for n in RADIUS_NAMES}:
                continue
            detection.skip(variable, "Karni has no token for this variable")
