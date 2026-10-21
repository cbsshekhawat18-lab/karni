"""Material UI, Chakra UI and Mantine themes, read statically from the project's source.

The theme definition (``createTheme`` / ``extendTheme`` / ``createSystem`` /
``defineConfig``) is found by its call and its import, and its literal values
are mapped where the meaning is the same as a Karni token. A value the source
computes (a variable, a function call, a spread) is reported, never guessed;
so is every key Karni has no token for.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karni_cli.uitheme import jsobject
from karni_cli.uitheme.frontend import SOURCE_SUFFIXES, Frontend
from karni_cli.uitheme.jsobject import NonLiteral
from karni_cli.uitheme.model import (
    FONT_SIZE_NAMES,
    RADIUS_NAMES,
    Detection,
    Scheme,
    color_role,
    color_token,
    radius_token,
    references_karni,
    shadow_token,
)
from karni_cli.uitheme.tailwind import KarniRefs, css_value, map_colour, map_spacing


@dataclass(frozen=True)
class Library:
    source: str  # "mui", "chakra", "mantine"
    label: str
    package: str
    #: (function name, import sources it must come from)
    calls: tuple[tuple[str, tuple[str, ...]], ...]


LIBRARIES: tuple[Library, ...] = (
    Library(
        "mui",
        "Material UI",
        "@mui/material",
        (("createTheme", ("@mui/material/styles", "@mui/material")),),
    ),
    Library(
        "chakra",
        "Chakra UI",
        "@chakra-ui/react",
        (
            ("extendTheme", ("@chakra-ui/react", "@chakra-ui/theme-utils")),
            ("defineConfig", ("@chakra-ui/react",)),
            ("createSystem", ("@chakra-ui/react",)),
        ),
    ),
    Library("mantine", "Mantine", "@mantine/core", (("createTheme", ("@mantine/core",)),)),
)

_SKIP_ARGUMENTS = frozenset({"defaultConfig", "defaultBaseConfig"})


@dataclass
class Found:
    path: Path
    call: str
    tree: dict[str, Any]
    line: int
    extra_arguments: int


def _imports(source: str, name: str, modules: tuple[str, ...]) -> bool:
    for module in modules:
        pattern = rf"""import\s*\{{[^}}]*\b{name}\b[^}}]*\}}\s*from\s*["']{re.escape(module)}["']"""
        if re.search(pattern, source) or re.search(
            rf"""\b{name}\b[^;]*require\(\s*["']{re.escape(module)}["']""", source
        ):
            return True
    return False


def _argument_tree(source: str, start: int, depth: int = 0) -> dict[str, Any] | None:
    """The object literal at ``start``: inline, behind a ``const``, or inside ``defineConfig(...)``."""
    value = jsobject.parse_value(source, start)
    if isinstance(value, dict):
        return value
    if not isinstance(value, NonLiteral) or depth > 3:
        return None
    raw = value.raw
    call = re.match(r"^([A-Za-z_$][\w$.]*)\s*(?:<[^>()]*>)?\s*\(", raw)
    if call:
        open_paren = source.find("(", start + call.start(1) + len(call.group(1)))
        for arg_start, text in jsobject.call_arguments(source, open_paren):
            if text not in _SKIP_ARGUMENTS:
                return _argument_tree(source, arg_start, depth + 1)
        return None
    if re.fullmatch(r"[A-Za-z_$][\w$]*", raw):
        resolved = jsobject.resolve_identifier(source, raw)
        if resolved is not None:
            return _argument_tree(source, resolved, depth + 1)
    return None


def find_theme(frontend: Frontend, library: Library) -> Found | None:
    for path in frontend.files(SOURCE_SUFFIXES):
        source = frontend.read(path)
        for name, modules in library.calls:
            if name not in source or not _imports(source, name, modules):
                continue
            for open_paren in jsobject.find_calls(source, name):
                arguments = [
                    (start, text)
                    for start, text in jsobject.call_arguments(source, open_paren)
                    if text not in _SKIP_ARGUMENTS
                ]
                if not arguments:
                    continue
                tree = _argument_tree(source, arguments[0][0])
                if tree is None:
                    continue
                line = source.count("\n", 0, open_paren) + 1
                return Found(path, name, tree, line, len(arguments) - 1)
    return None


def _not_literal(detection: Detection, name: str, value: Any, token: str = "") -> bool:
    """Report a computed value; True when ``value`` is not usable."""
    if isinstance(value, NonLiteral):
        line = f"{token}: <the value it computes>;" if token else ""
        detection.skip(name, value.describe(), line)
        return True
    return False


def _colour(
    detection: Detection, name: str, value: Any, role: str, scheme: Scheme, note: str = ""
) -> None:
    token = color_token(role)
    if value is None or _not_literal(detection, name, value, token):
        return
    text = css_value(value)
    if text is None:
        detection.skip(name, "not a colour value")
    elif references_karni(text):
        return
    else:
        detection.add(name, token, text, scheme, note)


def _report_rest(detection: Detection, prefix: str, tree: dict[str, Any], used: set[str]) -> None:
    for key, value in tree.items():
        if key in used:
            continue
        if key.startswith("...") and isinstance(value, NonLiteral):
            detection.skip(f"{prefix}{value.raw}", value.describe())
        else:
            detection.skip(f"{prefix}{key}", "Karni has no token for this")


# --- Material UI ---------------------------------------------------------------

MUI_UNMAPPED_PALETTE = {
    "secondary": (
        "MUI's secondary is a second brand colour; Karni's secondary is a quiet surface for "
        "secondary buttons, so they are not the same role. To use it anyway, add"
    ),
    "warning": "Karni has no warning colour",
    "info": "Karni has no info colour",
    "success": "Karni has no success colour",
    "grey": "a palette, not a role",
    "common": "MUI's black and white constants",
    "action": "MUI's interaction shades: Karni derives hover shades from the base colour",
    "contrastThreshold": "MUI computes contrast text at runtime",
    "tonalOffset": "MUI computes light and dark shades at runtime",
}


MUI_READ_FIELDS = frozenset({"main", "contrastText", "default", "paper", "primary", "secondary"})


def _mui_palette(detection: Detection, palette: Any, scheme: Scheme, prefix: str) -> None:
    if not isinstance(palette, dict):
        if isinstance(palette, NonLiteral):
            detection.skip(prefix.rstrip("."), palette.describe())
        return
    used = {"mode"}

    def part(key: str, field: str) -> Any:
        node = palette.get(key)
        if isinstance(node, NonLiteral):
            detection.skip(f"{prefix}{key}", node.describe())
            used.add(key)
            return None
        return node.get(field) if isinstance(node, dict) else None

    for key, field, roles in (
        ("primary", "main", ("primary",)),
        ("primary", "contrastText", ("primary-foreground",)),
        ("error", "main", ("destructive",)),
        ("error", "contrastText", ("destructive-foreground",)),
        ("background", "default", ("background",)),
        ("background", "paper", ("card", "popover")),
        ("text", "primary", ("foreground", "card-foreground", "popover-foreground")),
        ("text", "secondary", ("muted-foreground",)),
    ):
        if key in palette:
            used.add(key)
        value = part(key, field)
        for role in roles:
            _colour(detection, f"{prefix}{key}.{field}", value, role, scheme)
        node = palette.get(key)
        if isinstance(node, dict):
            for other in node:
                if other not in MUI_READ_FIELDS:
                    detection.skip(
                        f"{prefix}{key}.{other}",
                        "Karni derives hover and subtle shades from the base colour",
                    )
    if "divider" in palette:
        used.add("divider")
        _colour(detection, f"{prefix}divider", palette["divider"], "border", scheme)
    secondary = palette.get("secondary")
    if secondary is not None:
        used.add("secondary")
        main = secondary.get("main") if isinstance(secondary, dict) else None
        line = f"--karni-color-secondary: {main};" if isinstance(main, str) else ""
        detection.skip(f"{prefix}secondary", MUI_UNMAPPED_PALETTE["secondary"], line)
    for key, reason in MUI_UNMAPPED_PALETTE.items():
        if key in palette and key not in used:
            used.add(key)
            detection.skip(f"{prefix}{key}", reason)
    _report_rest(detection, prefix, palette, used)


def _px(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return f"{value:g}px"
    if isinstance(value, str):
        return value
    return None


def map_mui(detection: Detection, tree: dict[str, Any]) -> None:
    used: set[str] = set()
    palette = tree.get("palette")
    schemes = tree.get("colorSchemes")
    if isinstance(schemes, dict):
        used.add("colorSchemes")
        pairs: tuple[tuple[str, Scheme], ...] = (("light", "light"), ("dark", "dark"))
        for name, which in pairs:
            entry = schemes.get(name)
            if isinstance(entry, dict):
                _mui_palette(
                    detection, entry.get("palette"), which, f"colorSchemes.{name}.palette."
                )
            elif entry is True:
                detection.notes.append(
                    f"colorSchemes.{name} is MUI's default palette: Karni keeps its own."
                )
    if palette is not None:
        used.add("palette")
        mode = palette.get("mode") if isinstance(palette, dict) else None
        scheme: Scheme = "dark" if mode == "dark" else "light"
        _mui_palette(detection, palette, scheme, "palette.")
        if not isinstance(schemes, dict):
            detection.notes.append(
                f"The theme has one palette ({'dark' if scheme == 'dark' else 'light'}): "
                f"{'light' if scheme == 'dark' else 'dark'} mode keeps Karni's default colours."
            )

    shape = tree.get("shape")
    if shape is not None:
        used.add("shape")
        radius = shape.get("borderRadius") if isinstance(shape, dict) else shape
        if not _not_literal(detection, "shape.borderRadius", radius, "--karni-radius"):
            text = _px(radius)
            if text is not None:
                note = "MUI uses one radius for buttons, inputs and surfaces"
                detection.add("shape.borderRadius", "--karni-radius", text, "light", note)
                detection.add("shape.borderRadius", radius_token("md"), text, "light", note)

    typography = tree.get("typography")
    if typography is not None:
        used.add("typography")
        if isinstance(typography, NonLiteral):
            detection.skip("typography", typography.describe())
        elif isinstance(typography, dict):
            family = typography.get("fontFamily")
            if family is not None and not _not_literal(
                detection, "typography.fontFamily", family, "--karni-font-sans"
            ):
                text = css_value(family)
                if text:
                    detection.add("typography.fontFamily", "--karni-font-sans", text)
            for key in typography:
                if key != "fontFamily":
                    detection.skip(
                        f"typography.{key}",
                        "MUI's type scale does not line up with Karni's (xs-2xl); not mapped",
                    )

    spacing = tree.get("spacing")
    if spacing is not None:
        used.add("spacing")
        if isinstance(spacing, int | float) and not isinstance(spacing, bool):
            if spacing == 8:
                detection.notes.append(
                    "spacing 8 is Karni's scale already (MUI's spacing(1) = Karni's step 2 = 8px)."
                )
            else:
                unit = spacing / 2
                detection.add(
                    "spacing",
                    "--karni-space-unit",
                    f"{unit:g}px",
                    note=f"MUI's spacing(1) = {spacing:g}px is Karni's step 2",
                )
        else:
            reason = (
                spacing.describe()
                if isinstance(spacing, NonLiteral)
                else "not a single number of pixels, so it does not convert to Karni's unit"
            )
            detection.skip("spacing", reason)
    if "components" in tree:
        used.add("components")
        detection.skip(
            "components",
            "MUI's per-component style overrides: Karni has no equivalent (register your "
            "components as Karni primitives to reuse them)",
        )
    if "shadows" in tree:
        used.add("shadows")
        detection.skip("shadows", "MUI's 25 elevations do not line up with Karni's sm, md and lg")
    _report_rest(detection, "", tree, used)


# --- Chakra UI ------------------------------------------------------------------

CHAKRA_SEMANTIC = {
    "chakra-body-bg": "background",
    "chakra-body-text": "foreground",
    "chakra-border-color": "border",
    "bg": "background",
    "bg.DEFAULT": "background",
    "fg": "foreground",
    "fg.DEFAULT": "foreground",
    "bg.muted": "muted",
    "fg.muted": "muted-foreground",
    "border": "border",
    "border.DEFAULT": "border",
    "bg.panel": "card",
    "fg.error": "destructive",
}


def _unwrap_tokens(node: Any) -> Any:
    """Chakra 3 wraps every token as ``{ value: ... }``; return the plain tree."""
    if isinstance(node, dict):
        if set(node) == {"value"} or ("value" in node and set(node) <= {"value", "description"}):
            return _unwrap_tokens(node["value"])
        return {key: _unwrap_tokens(value) for key, value in node.items()}
    return node


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in tree.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and not _is_conditional(value):
            flat.update(_flatten(value, name))
        else:
            flat[name] = value
    return flat


def _is_conditional(value: dict[str, Any]) -> bool:
    return bool(value) and set(value) <= {"base", "default", "_light", "_dark"}


def _chakra_reference(value: Any, colors: dict[str, Any]) -> str | None:
    """``brand.500`` / ``{colors.brand.500}``: the project's colour, else Chakra's CSS variable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    braced = re.fullmatch(r"\{colors\.([\w.-]+)\}", text)
    path = braced.group(1) if braced else text
    if braced or re.fullmatch(r"[a-zA-Z][\w-]*\.\d{2,3}", text):
        node: Any = colors
        for step in path.split("."):
            node = node.get(step) if isinstance(node, dict) else None
        if isinstance(node, str):
            return node
        return f"var(--chakra-colors-{path.replace('.', '-')})"
    return text


def map_chakra(detection: Detection, tree: dict[str, Any]) -> None:
    """Chakra 2 (``extendTheme({colors, fonts, radii, ...})``) or 3 (``{theme: {tokens, ...}}``)."""
    counter = KarniRefs()
    used: set[str] = set()
    theme: dict[str, Any] = tree
    version3 = isinstance(tree.get("theme"), dict)
    if version3:
        for key in tree:
            if key != "theme":
                detection.skip(key, "Chakra's system setting: Karni has no equivalent")
        theme = tree["theme"]
        for key in theme:
            if key not in ("tokens", "semanticTokens"):
                detection.skip(
                    f"theme.{key}", "Karni has no equivalent (recipes and styles stay Chakra's)"
                )
    unwrapped = _unwrap_tokens(theme.get("tokens")) if version3 else theme
    tokens: dict[str, Any] = unwrapped if isinstance(unwrapped, dict) else {}
    semantic = _unwrap_tokens(theme.get("semanticTokens"))
    prefix = "theme.tokens." if version3 else ""
    shades = ("600", "500") if version3 else ("500", "600")

    found_colors = tokens.get("colors")
    colors: dict[str, Any] = found_colors if isinstance(found_colors, dict) else {}
    if "colors" in tokens:
        used.add("colors")
    for name, value in colors.items():
        source = f"{prefix}colors.{name}"
        if isinstance(value, NonLiteral):
            detection.skip(source, value.describe())
        else:
            map_colour(detection, source, name, value, counter, palette_shades=shades)

    if isinstance(semantic, dict):
        used.add("semanticTokens")
        semantic_colors = semantic.get("colors")
        flat = _flatten(semantic_colors) if isinstance(semantic_colors, dict) else {}
        for name, value in flat.items():
            source = f"{'theme.' if version3 else ''}semanticTokens.colors.{name}"
            role = CHAKRA_SEMANTIC.get(name) or color_role(name.replace(".DEFAULT", ""))
            if role is None:
                detection.skip(source, f"Karni has no '{name}' colour role")
                continue
            if isinstance(value, NonLiteral):
                detection.skip(source, value.describe())
                continue
            variants = value if isinstance(value, dict) else {"": value}
            conditions: tuple[tuple[str, Scheme], ...] = (
                ("", "light"),
                ("base", "light"),
                ("default", "light"),
                ("_light", "light"),
                ("_dark", "dark"),
            )
            for condition, scheme in conditions:
                if condition not in variants:
                    continue
                resolved = _chakra_reference(variants[condition], colors)
                name_ = f"{source}.{condition}" if condition else source
                if resolved is None:
                    detection.skip(name_, "not a literal value")
                elif not references_karni(resolved):
                    detection.add(name_, color_token(role), resolved, scheme)
        for key in semantic:
            if key != "colors":
                detection.skip(f"semanticTokens.{key}", "Karni maps semantic colours only")

    fonts = tokens.get("fonts")
    if isinstance(fonts, dict):
        used.add("fonts")
        for key, value in fonts.items():
            source = f"{prefix}fonts.{key}"
            target = {"body": "sans", "mono": "mono"}.get(key)
            if target is None:
                detection.skip(source, "Karni has sans and mono fonts only (headings use sans)")
            elif not _not_literal(detection, source, value, f"--karni-font-{target}"):
                text = css_value(value)
                if text:
                    detection.add(source, f"--karni-font-{target}", text)

    for section, names, token_of, what in (
        ("radii", RADIUS_NAMES, radius_token, "radius"),
        ("shadows", ("sm", "md", "lg"), shadow_token, "shadow"),
    ):
        scale = tokens.get(section)
        if not isinstance(scale, dict):
            continue
        used.add(section)
        for key, value in scale.items():
            source = f"{prefix}{section}.{key}"
            name = "DEFAULT" if (section == "shadows" and key == "base") else key
            if name not in names and name != "DEFAULT":
                detection.skip(source, f"Karni has no '{key}' {what}")
            elif not _not_literal(detection, source, value):
                text = css_value(value)
                if text:
                    detection.add(source, token_of(name), text)

    space = tokens.get("space") or tokens.get("spacing")
    if isinstance(space, dict):
        used.add("space" if "space" in tokens else "spacing")
        map_spacing(detection, f"{prefix}space", space, None, counter)

    sizes = tokens.get("fontSizes")
    if isinstance(sizes, dict):
        used.add("fontSizes")
        for key, value in sizes.items():
            source = f"{prefix}fontSizes.{key}"
            if key not in FONT_SIZE_NAMES:
                detection.skip(source, "Karni's components use the xs-2xl sizes only")
            elif not _not_literal(detection, source, value):
                text = css_value(value)
                if text:
                    detection.add(source, f"--karni-font-size-{key}", text)
    if not version3:
        for key, reason in (
            ("components", "Chakra's component styles: Karni has no equivalent"),
            ("styles", "Chakra's global styles: Karni has no equivalent"),
            ("config", "Chakra's colour-mode config: Karni's dark mode is the .dark class"),
        ):
            if key in theme:
                used.add(key)
                detection.skip(key, reason)
        _report_rest(detection, "", theme, used)
    else:
        for key in tokens:
            if key not in used:
                detection.skip(f"{prefix}{key}", "Karni has no token for this")


# --- Mantine ----------------------------------------------------------------------

MANTINE_RADIUS = {"xs": "0.125rem", "sm": "0.25rem", "md": "0.5rem", "lg": "1rem", "xl": "2rem"}


def _mantine_shade(colors: dict[str, Any], name: str, shade: Any) -> str | None:
    scale = colors.get(name)
    if isinstance(scale, list) and isinstance(shade, int) and 0 <= shade < len(scale):
        value = scale[shade]
        return value if isinstance(value, str) else None
    return None


def map_mantine(detection: Detection, tree: dict[str, Any]) -> None:
    counter = KarniRefs()
    used: set[str] = set()
    colors = tree.get("colors")
    if isinstance(colors, dict):
        used.add("colors")
    else:
        colors = {}
    shade = tree.get("primaryShade", {"light": 6, "dark": 8})
    if "primaryShade" in tree:
        used.add("primaryShade")
    light_shade = shade.get("light", 6) if isinstance(shade, dict) else shade
    dark_shade = shade.get("dark", 8) if isinstance(shade, dict) else shade
    primary = tree.get("primaryColor")
    mapped_palettes: set[str] = set()
    if primary is not None:
        used.add("primaryColor")
        if isinstance(primary, NonLiteral):
            detection.skip("primaryColor", primary.describe())
        elif isinstance(primary, str):
            light = _mantine_shade(colors, primary, light_shade)
            dark = _mantine_shade(colors, primary, dark_shade)
            if light is None:
                detection.skip(
                    "primaryColor",
                    f"'{primary}' is not a 10-shade palette in this theme (one of Mantine's own "
                    "palettes?); its values are not in your source. Mantine exposes it as a CSS "
                    "variable",
                    "--karni-color-primary: var(--mantine-primary-color-filled);",
                )
            else:
                mapped_palettes.add(primary)
                source = f"colors.{primary}[{light_shade}]"
                detection.add(source, color_token("primary"), light, "light")
                if dark is not None:
                    detection.add(
                        f"colors.{primary}[{dark_shade}]", color_token("primary"), dark, "dark"
                    )
                white = tree.get("white")
                foreground = white if isinstance(white, str) else "#fff"
                origin = "white" if isinstance(white, str) else "(Mantine's default white)"
                note = "Mantine's filled buttons use theme.white for text"
                for which in ("light", "dark"):
                    token = color_token("primary-foreground")
                    detection.add(origin, token, foreground, which, note)
                used.add("white")
    red = _mantine_shade(colors, "red", 6)
    if red is not None:
        mapped_palettes.add("red")
        note = "Mantine's error colour is red[6] (light) and red[8] (dark)"
        detection.add("colors.red[6]", color_token("destructive"), red, "light", note)
        red_dark = _mantine_shade(colors, "red", 8)
        if red_dark is not None:
            detection.add("colors.red[8]", color_token("destructive"), red_dark, "dark", note)
    for name, value in colors.items():
        if name in mapped_palettes:
            continue
        if isinstance(value, NonLiteral):
            detection.skip(f"colors.{name}", value.describe())
        else:
            detection.skip(f"colors.{name}", "a palette Karni has no role for")

    for key, target in (("fontFamily", "sans"), ("fontFamilyMonospace", "mono")):
        if key in tree:
            used.add(key)
            value = tree[key]
            if not _not_literal(detection, key, value, f"--karni-font-{target}"):
                text = css_value(value)
                if text:
                    detection.add(key, f"--karni-font-{target}", text)

    radius = tree.get("radius")
    scale = dict(MANTINE_RADIUS)
    custom_scale = isinstance(radius, dict)
    if radius is not None:
        used.add("radius")
        if isinstance(radius, dict):
            scale.update({k: v for k, v in radius.items() if isinstance(v, str)})
            for k, v in radius.items():
                if isinstance(v, int | float) and not isinstance(v, bool):
                    scale[k] = f"{v:g}px"
    default = tree.get("defaultRadius")
    if default is not None or custom_scale:
        used.add("defaultRadius")
        key = default if default is not None else "sm"
        if isinstance(key, NonLiteral):
            detection.skip("defaultRadius", key.describe())
        else:
            text = scale.get(key) if isinstance(key, str) else _px(key)
            if text is not None:
                source = f"defaultRadius ({key})" if isinstance(key, str) else "defaultRadius"
                note = "Mantine's components use defaultRadius for buttons, inputs and cards"
                detection.add(source, "--karni-radius", text, "light", note)
                detection.add(source, radius_token("md"), text, "light", note)
        if custom_scale:
            detection.skip(
                "radius (xs-xl)",
                "Mantine's radius scale does not line up with Karni's sizes; defaultRadius is "
                "what its components use",
            )

    shadows = tree.get("shadows")
    if isinstance(shadows, dict):
        used.add("shadows")
        for key, value in shadows.items():
            if key in ("sm", "md", "lg") and not _not_literal(detection, f"shadows.{key}", value):
                text = css_value(value)
                if text:
                    detection.add(f"shadows.{key}", shadow_token(key), text)
            elif key not in ("sm", "md", "lg"):
                detection.skip(f"shadows.{key}", f"Karni has no '{key}' shadow")

    for key, reason in (
        ("spacing", "Mantine's named spacing (xs-xl) does not convert to Karni's numeric scale"),
        ("fontSizes", "Mantine's type scale does not line up with Karni's (xs-2xl)"),
        ("headings", "Karni has no heading tokens (headings use the sans font)"),
        ("components", "Mantine's component defaults: Karni has no equivalent"),
    ):
        if key in tree:
            used.add(key)
            detection.skip(key, reason)
    _report_rest(detection, "", tree, used)
    if counter.karni:
        detection.notes.append(f"{counter.karni} value(s) already read Karni's tokens: skipped.")


MAPPERS: dict[str, Callable[[Detection, dict[str, Any]], None]] = {
    "mui": map_mui,
    "chakra": map_chakra,
    "mantine": map_mantine,
}


def detect(frontend: Frontend, library: Library) -> Detection | None:
    """The library's theme, or None when the project does not use it or defines none."""
    if not frontend.has_dependency(library.package):
        return None
    found = find_theme(frontend, library)
    if found is None:
        return None
    rel = frontend.rel(found.path)
    detection = Detection(
        library.source, f"{library.label} theme ({found.call} in {rel}:{found.line})", files=[rel]
    )
    MAPPERS[library.source](detection, found.tree)
    if found.extra_arguments:
        detection.notes.append(
            f"{found.call}() has {found.extra_arguments} more argument(s), merged at runtime: "
            "not read."
        )
    if not detection.mappings and not detection.unmapped:
        detection.notes.append(f"{found.call}() in {rel} sets nothing Karni has a token for.")
    return detection
