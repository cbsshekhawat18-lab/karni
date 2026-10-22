"""Karni's own token defaults, read from @karni/ui's styles.css (never retyped here).

The stylesheet comes from the project's installed @karni/ui (its version is
the one that applies), else this checkout's packages/karni-ui, else the copy
bundled into the karni-cli wheel (``karni_cli/_ui``).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from karni_cli.uitheme import css
from karni_cli.uitheme.frontend import Frontend
from karni_cli.uitheme.model import COLOR_ROLES, Detection, Mapping, Scheme, color_token

#: The non-colour tokens the defaults file lists (the ones projects change most).
MAIN_TOKENS: tuple[str, ...] = (
    "--karni-radius",
    "--karni-space-unit",
    "--karni-font-sans",
    "--karni-font-mono",
    "--karni-shadow-sm",
    "--karni-shadow-md",
    "--karni-shadow-lg",
)
_VAR = re.compile(r"var\((--[\w-]+)\)")


def styles_source(frontend: Frontend) -> tuple[str, str] | None:
    """``(text, where)`` of the @karni/ui stylesheet that defines the defaults."""
    installed = frontend.root / "node_modules" / "@karni" / "ui" / "dist" / "styles.css"
    if installed.is_file():
        return installed.read_text(encoding="utf-8"), frontend.rel(installed)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "packages" / "karni-ui" / "src" / "styles.css"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8"), "@karni/ui (this checkout)"
    bundled = resources.files("karni_cli") / "_ui" / "styles.css"
    with resources.as_file(bundled) as path:
        if path.is_file():
            return path.read_text(encoding="utf-8"), "@karni/ui (bundled with karni-cli)"
    return None


def _resolve(value: str, variables: dict[str, str]) -> str:
    """Substitute ``var(--x)`` with its value (two levels: enough for styles.css)."""
    for _ in range(2):
        value = _VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), value)
    return value


def default_values(text: str) -> dict[Scheme, list[tuple[str, str]]]:
    """``{"light": [(token, value)], "dark": [...]}`` for the colours and the main tokens."""
    sheet = css.parse(text)
    light = sheet.variables(":root")
    dark = {**light, **sheet.variables(".dark")}
    out: dict[Scheme, list[tuple[str, str]]] = {"light": [], "dark": []}
    for role in COLOR_ROLES:
        token = color_token(role)
        if token in light:
            out["light"].append((token, _resolve(light[token], light)))
            out["dark"].append((token, _resolve(light[token], dark)))
    for token in MAIN_TOKENS:
        if token in light:
            out["light"].append((token, light[token]))
    return out


def detect(frontend: Frontend) -> Detection:
    """Nothing to adopt: the file lists Karni's defaults, commented, for the project to edit."""
    detection = Detection("defaults", "nothing to adopt: Karni's defaults")
    found = styles_source(frontend)
    if found is None:
        detection.notes.append(
            "@karni/ui's styles.css was not found (npm install @karni/ui), so the file lists "
            "no default values."
        )
        return detection
    text, where = found
    detection.files.append(where)
    values = default_values(text)
    for scheme, entries in values.items():
        for token, value in entries:
            detection.commented.append(Mapping(where, token, value, scheme))
    detection.notes.append(
        "No shadcn/ui, Tailwind theme, Material UI, Chakra UI or Mantine theme found. "
        "karni-theme.css lists Karni's defaults, commented: uncomment a line to change it."
    )
    return detection
