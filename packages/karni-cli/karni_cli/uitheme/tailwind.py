"""Tailwind themes: ``@theme`` blocks (Tailwind 4) and ``tailwind.config`` (Tailwind 3, or 4 via ``@config``).

Only names that clearly mean one of Karni's tokens are mapped: the semantic
colours (primary, destructive/danger/error, muted, border, ...), sans and mono
fonts, the sm-xl radii, the sm-lg shadows, the spacing unit and the xs-2xl
type scale. A palette (``brand: {50 ... 950}``) is not a role: it is reported
with the line the project could add, never turned into primary silently.

A JavaScript or TypeScript config is evaluated by Node in the project, with
the project's own packages: Tailwind 3's ``loadConfig`` + ``resolveConfig``
(diffed against Tailwind's defaults so only the project's own values count),
or, for Tailwind 4's ``@config``, the module itself through jiti.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from karni_cli.project import CliError
from karni_cli.uitheme import css
from karni_cli.uitheme.frontend import Frontend
from karni_cli.uitheme.model import (
    COLOR_ROLES,
    FONT_SIZE_NAMES,
    FONT_WEIGHT_NAMES,
    RADIUS_NAMES,
    SHADOW_NAMES,
    SPACE_STEPS,
    TRACKING_NAMES,
    Detection,
    Scheme,
    color_role,
    color_token,
    radius_token,
    references_karni,
    references_variable,
    shadow_token,
    space_token,
)

CONFIG_NAMES = tuple(
    f"tailwind.config.{suffix}" for suffix in ("ts", "js", "mjs", "cjs", "mts", "cts")
)
#: Tailwind's own palette names: a project overriding one is not naming a brand colour.
TAILWIND_PALETTES = frozenset(
    {
        "slate", "gray", "zinc", "neutral", "stone", "red", "orange", "amber", "yellow", "lime",
        "green", "emerald", "teal", "cyan", "sky", "blue", "indigo", "violet", "purple",
        "fuchsia", "pink", "rose", "mauve", "olive", "mist", "taupe",
    }
)  # fmt: skip
SHADE_KEYS = frozenset({"50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"})
NODE_TIMEOUT = 60

#: Evaluates a Tailwind config in the project (argv[1]: the config path). Prints JSON.
NODE_SCRIPT = r"""
const path = require("node:path");
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");
const configPath = path.resolve(process.argv[1]);
const base = path.join(process.cwd(), "karni-ui-detect.cjs");
const projectRequire = createRequire(base);
const isFn = (v) => typeof v === "function";
const replacer = (_k, v) => (isFn(v) ? { __karni_function__: String(v).slice(0, 80) } : v);
const tryRequire = (id) => { try { return projectRequire(id); } catch { return null; } };
const unwrap = (m) => (m && typeof m === "object" && "default" in m ? m.default : m);
const isKarni = (o) => { try { return JSON.stringify(o, replacer).includes("--karni-"); } catch { return false; } };
function userKeys(config) {
  const keys = new Set();
  const walk = (cfg) => {
    if (!cfg || typeof cfg !== "object") return;
    for (const preset of cfg.presets || []) if (!isKarni(preset)) walk(preset);
    const theme = cfg.theme || {};
    for (const k of Object.keys(theme)) if (k !== "extend") keys.add(k);
    for (const k of Object.keys(theme.extend || {})) keys.add(k);
  };
  walk(config);
  return [...keys];
}
function rawTheme(config) {
  const out = {};
  const plain = (v) => v && typeof v === "object" && !Array.isArray(v);
  const merge = (target, source) => {
    for (const [k, v] of Object.entries(source || {})) {
      if (plain(v) && plain(target[k])) merge(target[k], v);
      else target[k] = v;
    }
  };
  const walk = (cfg) => {
    if (!cfg || typeof cfg !== "object") return;
    for (const preset of cfg.presets || []) walk(preset);
    const { extend, ...theme } = cfg.theme || {};
    merge(out, theme);
    merge(out, extend);
  };
  walk(config);
  return out;
}
async function load() {
  const jiti = tryRequire("jiti");
  if (jiti && isFn(jiti.createJiti)) return unwrap(await jiti.createJiti(base).import(configPath));
  if (isFn(jiti)) return unwrap(jiti(base, { interopDefault: true })(configPath));
  return unwrap(await import(pathToFileURL(configPath).href));
}
(async () => {
  const pkg = tryRequire("tailwindcss/package.json");
  const version = pkg ? pkg.version : null;
  if (version && version.startsWith("3.")) {
    const loadConfig = tryRequire("tailwindcss/loadConfig");
    const resolveConfig = projectRequire("tailwindcss/resolveConfig");
    const config = loadConfig ? unwrap(loadConfig(configPath)) : await load();
    const resolved = resolveConfig(config);
    const defaults = resolveConfig({ content: ["./karni-ui-detect-none"] });
    const out = { mode: "resolved", version, theme: resolved.theme, defaults: defaults.theme, userKeys: userKeys(config) };
    process.stdout.write(JSON.stringify(out, replacer));
    return;
  }
  const config = await load();
  const out = { mode: "raw", version, theme: rawTheme(config), userKeys: userKeys(config) };
  process.stdout.write(JSON.stringify(out, replacer));
})().catch((error) => {
  process.stderr.write(String((error && error.stack) || error));
  process.exit(1);
});
"""


def is_function(value: Any) -> bool:
    return isinstance(value, dict) and "__karni_function__" in value


def clean_colour(value: str) -> str:
    """Drop Tailwind 3's ``<alpha-value>`` placeholder: ``hsl(var(--x) / <alpha-value>)`` -> ``hsl(var(--x))``."""
    value = re.sub(r"\s*/\s*<alpha-value>", "", value)
    return value.replace("<alpha-value>", "1").strip()


def scheme_for(value: str) -> Scheme:
    return "both" if references_variable(value) else "light"


def css_value(value: Any) -> str | None:
    """A theme value as CSS text, or None when it is not a literal."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return f"{value:g}"
    if isinstance(value, str):
        return value.strip()
    return None


def font_stack(value: Any) -> str | None:
    """A Tailwind font family: ``["Inter", "sans-serif"]`` or ``[[...], {fontFeatureSettings}]``."""
    if isinstance(value, list) and value and isinstance(value[0], list):
        value = value[0]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return ", ".join(value)
    return css_value(value)


def is_palette(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and set(value) <= SHADE_KEYS | {"DEFAULT"}


def palette_shade(palette: dict[str, Any], preferred: tuple[str, ...] = ("600", "500")) -> str:
    for shade in preferred:
        found = palette.get(shade)
        if isinstance(found, str):
            return found
    for found in palette.values():
        if isinstance(found, str):
            return found
    return "<colour>"


@dataclass
class KarniRefs:
    """How many values already read a Karni token (the @karni/ui preset's): skipped, counted."""

    karni: int = 0


def map_colour(
    detection: Detection,
    source: str,
    name: str,
    value: Any,
    counter: KarniRefs,
    scheme: Scheme | None = None,
    palette_shades: tuple[str, ...] = ("600", "500"),
) -> None:
    """One entry of a colour scale (Tailwind colors, Chakra colors, ...)."""
    role = color_role(name)
    if is_function(value):
        detection.skip(
            source, "a function, evaluated by Tailwind at build time, while Karni maps values"
        )
        return
    if isinstance(value, str):
        if references_karni(value):
            counter.karni += 1
            return
        text = clean_colour(value)
        if role is None:
            detection.skip(source, f"Karni has no '{name}' colour role")
            return
        detection.add(source, color_token(role), text, scheme or scheme_for(text))
        return
    if not isinstance(value, dict):
        detection.skip(source, "not a colour value")
        return
    if name == "chart":
        for key, shade in value.items():
            map_colour(detection, f"{source}.{key}", f"chart-{key}", shade, counter, scheme)
        return
    if role is not None and "DEFAULT" in value:
        map_colour(detection, f"{source}.DEFAULT", name, value["DEFAULT"], counter, scheme)
        for key, shade in value.items():
            if key == "DEFAULT":
                continue
            if key == "foreground" and f"{role}-foreground" in COLOR_ROLES:
                map_colour(
                    detection, f"{source}.foreground", f"{role}-foreground", shade, counter, scheme
                )
            elif isinstance(shade, str) and references_karni(shade):
                counter.karni += 1
            else:
                detection.skip(
                    f"{source}.{key}",
                    f"Karni has no '{role}-{key}' token (it derives -hover and -subtle shades "
                    "from the base colour)",
                )
        return
    if is_palette(value):
        if all(isinstance(v, str) and references_karni(v) for v in value.values()):
            counter.karni += 1
            return
        target = role or "primary"
        shade = palette_shade(value, palette_shades)
        line = f"{color_token(target)}: {clean_colour(shade)};"
        if role is not None:
            detection.skip(
                source,
                f"a palette ({', '.join(sorted(value, key=_shade_key))}) with no DEFAULT. Karni "
                f"needs one colour for {role}. Pick a shade",
                line,
            )
        elif name.lower() in TAILWIND_PALETTES:
            detection.skip(source, "one of Tailwind's palettes, not a role Karni has")
        else:
            detection.skip(
                source,
                "a palette, not a role: Karni does not guess that it is your primary colour. "
                "If it is, add",
                line,
            )
        return
    detection.skip(source, f"Karni has no '{name}' colour role")


def _shade_key(shade: str) -> int:
    return int(shade) if shade.isdigit() else -1


def _differs(defaults: dict[str, Any] | None, section: str, key: str, value: Any) -> bool:
    if defaults is None:
        return True
    scale = defaults.get(section)
    return not isinstance(scale, dict) or scale.get(key) != value


def _rem(value: str) -> float | None:
    match = re.fullmatch(r"(-?\d*\.?\d+)(rem|px)", value.strip())
    if not match:
        return None
    number = float(match.group(1))
    return number if match.group(2) == "rem" else number / 16


def map_spacing(
    detection: Detection,
    origin: str,
    scale: dict[str, Any],
    defaults: dict[str, Any] | None,
    counter: KarniRefs,
) -> None:
    """A spacing scale: one unit when every numeric step is n x unit, else per step."""
    custom: dict[float, str] = {}
    for key, value in scale.items():
        if not _differs(defaults, "spacing", key, value):
            continue
        text = css_value(value)
        if text is None:
            detection.skip(f"{origin}.{key}", "not a literal value")
            continue
        if references_karni(text):
            counter.karni += 1
            continue
        try:
            step = float(key)
        except ValueError:
            detection.skip(
                f"{origin}.{key}", "a named step: Karni's spacing scale has numeric steps only"
            )
            continue
        custom[step] = text
    if not custom:
        return
    units = {
        round(rem / step, 6)
        for step, text in custom.items()
        if step and (rem := _rem(text)) is not None
    }
    if len(units) == 1 and len(custom) > 1:
        unit = units.pop()
        if unit != 0.25:
            detection.add(f"{origin} (n x {unit:g}rem)", "--karni-space-unit", f"{unit:g}rem")
            return
    for step, text in sorted(custom.items()):
        if step in SPACE_STEPS:
            detection.add(f"{origin}.{step:g}", space_token(step), text, scheme_for(text))
        else:
            detection.skip(f"{origin}.{step:g}", "a step the @karni/ui preset does not define")


def map_config_theme(
    detection: Detection,
    theme: dict[str, Any],
    defaults: dict[str, Any] | None,
    user_keys: list[str] | None,
    origin: str = "theme",
) -> None:
    """A Tailwind config theme (resolved, with Tailwind's defaults to diff against, or raw)."""
    counter = KarniRefs()
    handled = {
        "colors",
        "fontFamily",
        "borderRadius",
        "boxShadow",
        "spacing",
        "fontSize",
        "fontWeight",
        "letterSpacing",
    }
    computed = [key for key, value in theme.items() if is_function(value)]
    for key in computed:
        detection.skip(
            f"{origin}.{key}",
            "a theme function, which only Tailwind 3's resolveConfig evaluates: write the "
            "values it returns as literals to have them mapped",
        )
    theme = {key: value for key, value in theme.items() if key not in computed}
    colors = theme.get("colors")
    if isinstance(colors, dict):
        for name, value in colors.items():
            if _differs(defaults, "colors", name, value):
                map_colour(detection, f"{origin}.colors.{name}", name, value, counter)

    def entries(section: str) -> list[tuple[str, Any]]:
        scale = theme.get(section)
        if not isinstance(scale, dict):
            return []
        return [(k, v) for k, v in scale.items() if _differs(defaults, section, k, v)]

    for name, value in entries("fontFamily"):
        source = f"{origin}.fontFamily.{name}"
        text = font_stack(value)
        if text is None or is_function(value):
            detection.skip(source, "not a literal value")
        elif references_karni(text):
            counter.karni += 1
        elif name in ("sans", "mono"):
            detection.add(source, f"--karni-font-{name}", text, scheme_for(text))
        else:
            detection.skip(source, "Karni has sans and mono font tokens only")

    for section, names, token_of, what in (
        ("borderRadius", RADIUS_NAMES, radius_token, "radius"),
        ("boxShadow", SHADOW_NAMES, shadow_token, "shadow"),
    ):
        for name, value in entries(section):
            source = f"{origin}.{section}.{name}"
            text = css_value(value)
            if text is None:
                detection.skip(source, "not a literal value")
            elif references_karni(text):
                counter.karni += 1
            elif name in names:
                detection.add(source, token_of(name), text, scheme_for(text))
            elif section == "borderRadius" and name == "DEFAULT":
                detection.skip(
                    source,
                    "Karni's bare `rounded` reads --karni-radius-sm. Set it if you want both",
                    f"--karni-radius-sm: {text};",
                )
            else:
                detection.skip(source, f"Karni has no '{name}' {what}")

    spacing = theme.get("spacing")
    if isinstance(spacing, dict):
        map_spacing(detection, f"{origin}.spacing", spacing, defaults, counter)

    for name, value in entries("fontSize"):
        source = f"{origin}.fontSize.{name}"
        size: Any = value
        leading: Any = None
        if isinstance(value, list) and value:
            size = value[0]
            extra = value[1] if len(value) > 1 else None
            leading = extra.get("lineHeight") if isinstance(extra, dict) else extra
        size_text, leading_text = css_value(size), css_value(leading)
        if size_text is None:
            detection.skip(source, "not a literal value")
        elif references_karni(size_text):
            counter.karni += 1
        elif name in FONT_SIZE_NAMES:
            detection.add(source, f"--karni-font-size-{name}", size_text)
            if leading_text and not references_karni(leading_text):
                detection.add(f"{source} lineHeight", f"--karni-font-leading-{name}", leading_text)
        else:
            detection.skip(source, "Karni's components use the xs-2xl sizes only")

    for section, names, prefix in (
        ("fontWeight", FONT_WEIGHT_NAMES, "--karni-font-weight-"),
        ("letterSpacing", TRACKING_NAMES, "--karni-font-tracking-"),
    ):
        for name, value in entries(section):
            source = f"{origin}.{section}.{name}"
            text = css_value(value)
            if text is None:
                detection.skip(source, "not a literal value")
            elif references_karni(text):
                counter.karni += 1
            elif name in names:
                detection.add(source, f"{prefix}{name}", text)
            else:
                detection.skip(source, f"Karni has no '{name}' token for {section}")

    for key in user_keys or []:
        if key in handled or key == "extend" or key in computed:
            continue
        written = theme.get(key)
        if defaults is not None and defaults.get(key) == written:
            continue
        if written is not None and references_karni(json.dumps(written, default=str)):
            continue
        detection.skip(f"{origin}.{key}", "Karni has no tokens for this part of the theme")

    if counter.karni:
        detection.notes.append(
            f"{counter.karni} value(s) already read Karni's tokens (the @karni/ui preset): skipped."
        )


_THEME_COLOR_SHADE = re.compile(r"^(.*)-(50|[1-9]00|950)$")


def map_theme_variables(detection: Detection, variables: dict[str, str], where: str) -> None:
    """Tailwind 4 ``@theme`` variables. Each token reads the variable, with its value as fallback."""
    palettes: dict[str, dict[str, str]] = {}
    others: dict[str, list[str]] = {}
    karni = 0
    for variable, value in variables.items():
        if value == "initial" or variable.endswith("-*"):
            continue
        if references_karni(value):
            karni += 1
            continue
        name = variable[2:]
        source = f"@theme {variable}"
        live = f"var({variable}, {value})"
        if name.startswith("color-"):
            colour = name[len("color-") :]
            role = color_role(colour)
            shade = _THEME_COLOR_SHADE.match(colour)
            if role is not None:
                detection.add(source, color_token(role), live, "both")
            elif shade:
                palettes.setdefault(shade.group(1), {})[shade.group(2)] = value
            else:
                detection.skip(source, f"Karni has no '{colour}' colour role")
        elif name in ("font-sans", "font-mono"):
            detection.add(source, f"--karni-{name}", live, "both")
        elif name.startswith("font-weight-"):
            weight = name[len("font-weight-") :]
            if weight in FONT_WEIGHT_NAMES:
                detection.add(source, f"--karni-font-weight-{weight}", live, "both")
            else:
                detection.skip(source, f"Karni has no '{weight}' font weight")
        elif name.startswith("font-"):
            detection.skip(source, "Karni has sans and mono font tokens only")
        elif name == "radius" or name.startswith("radius-"):
            size = name[len("radius-") :] if name != "radius" else ""
            if not size:
                detection.add(source, "--karni-radius", live, "both")
            elif size in RADIUS_NAMES:
                detection.add(source, radius_token(size), live, "both")
            else:
                detection.skip(source, f"Karni has no '{size}' radius")
        elif name == "shadow" or name.startswith("shadow-"):
            size = name[len("shadow-") :] if name != "shadow" else "DEFAULT"
            if size in SHADOW_NAMES:
                detection.add(source, shadow_token(size), live, "both")
            else:
                detection.skip(source, f"Karni has no '{size}' shadow")
        elif name == "spacing":
            detection.add(source, "--karni-space-unit", live, "both")
        elif name.startswith("text-"):
            rest = name[len("text-") :]
            size, _, suffix = rest.partition("--")
            if size in FONT_SIZE_NAMES and suffix in ("", "line-height"):
                token = "size" if not suffix else "leading"
                detection.add(source, f"--karni-font-{token}-{size}", live, "both")
            else:
                detection.skip(source, "Karni's components use the xs-2xl sizes only")
        elif name.startswith("tracking-"):
            tracking = name[len("tracking-") :]
            if tracking in TRACKING_NAMES:
                detection.add(source, f"--karni-font-tracking-{tracking}", live, "both")
            else:
                detection.skip(source, f"Karni has no '{tracking}' letter spacing")
        elif name == "leading-none":
            detection.add(source, "--karni-font-leading-none", live, "both")
        else:
            others.setdefault(name.split("-", 1)[0], []).append(variable)
    for palette, shades in palettes.items():
        line = f"{color_token('primary')}: {palette_shade(shades)};"
        if palette.lower() in TAILWIND_PALETTES:
            detection.skip(f"@theme --color-{palette}-*", "one of Tailwind's palettes, not a role")
        else:
            detection.skip(
                f"@theme --color-{palette}-* ({len(shades)} shades)",
                "a palette, not a role: Karni does not guess that it is your primary colour. "
                "If it is, add",
                line,
            )
    for namespace, members in others.items():
        shown = ", ".join(members) if len(members) <= 3 else f"--{namespace}-* ({len(members)})"
        detection.skip(f"@theme {shown}", f"Karni has no {namespace} tokens")
    if karni:
        detection.notes.append(
            f"{karni} @theme value(s) in {where} already read Karni's tokens: skipped."
        )


_CONFIG_DIRECTIVE = re.compile(r"""@config\s+["']([^"']+)["']""")
_V4_IMPORT = re.compile(r"""@import\s+["']tailwindcss["']""")
_PRESETS = re.compile(r"presets\s*:\s*\[([^\]]*)\]")
_IMPORT = re.compile(r"""import\s+(\w+)\s+from\s+["']([^"']+)["']""")
_REQUIRE = re.compile(r"""(?:const|let|var)\s+(\w+)\s*=\s*require\(\s*["']([^"']+)["']\s*\)""")


def needs_evaluation(source: str) -> bool:
    """A config worth running: it sets a theme, or uses a preset other than Karni's."""
    if re.search(r"\btheme\s*:", source):
        return True
    presets = _PRESETS.search(source)
    if presets is None:
        return False
    imported = dict(_IMPORT.findall(source)) | dict(_REQUIRE.findall(source))
    names = [name.strip() for name in presets.group(1).split(",") if name.strip()]
    return any(imported.get(name) != "@karni/ui/tailwind-preset" for name in names)


def find_config(frontend: Frontend, configured: str = "") -> tuple[Path | None, int | None]:
    """The Tailwind config that applies, and Tailwind's major version (None: unknown)."""
    major = frontend.major_version("tailwindcss")
    for sheet in frontend.stylesheets:
        text = css.strip_comments(frontend.read(sheet))
        directive = _CONFIG_DIRECTIVE.search(text)
        if directive:
            return (sheet.parent / directive.group(1)).resolve(), major or 4
        if major is None and _V4_IMPORT.search(text):
            major = 4
    if major is not None and major >= 4:
        return None, major  # Tailwind 4 reads a JS config only through @config
    if configured:
        path = (frontend.root / configured).resolve()
        if path.is_file():
            return path, major
    for name in CONFIG_NAMES:
        path = frontend.root / name
        if path.is_file():
            return path, major
    return None, major


def evaluate(frontend: Frontend, config: Path) -> dict[str, Any]:
    """Run Node in the project to load (and for Tailwind 3, resolve) ``config``."""
    rel = frontend.rel(config)
    node = shutil.which("node")
    if node is None:
        raise CliError(
            f"Node.js is not on PATH, and {rel} is JavaScript: karni ui detect evaluates it "
            "with Node in the project. Install Node 20+, or pass --source to read another "
            "theme source.",
            code="C006",
        )
    try:
        proc = subprocess.run(
            [node, "-e", NODE_SCRIPT, str(config)],
            cwd=frontend.root,
            capture_output=True,
            text=True,
            timeout=NODE_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CliError(
            f"Evaluating {rel} with Node took over {NODE_TIMEOUT}s and was stopped. Check the "
            "config for work at import time, or pass --source to read another theme source.",
            code="C303",
        ) from None
    if proc.returncode != 0:
        lines = [line for line in proc.stderr.strip().splitlines() if line.strip()]
        reason = lines[0] if lines else f"node exited with {proc.returncode}"
        hint = (
            "Install the frontend's packages (npm install in "
            f"{frontend.root}) so the config and what it imports can load"
        )
        if not (frontend.root / "node_modules").is_dir():
            hint = f"node_modules is missing: run npm install in {frontend.root}"
        raise CliError(
            f"{rel} could not be evaluated with Node: {reason}\n{hint}, or pass --source to "
            "read another theme source.",
            code="C303",
        )
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise CliError(
            f"Evaluating {rel} printed something other than the theme (the config writes to "
            "stdout at import time?). Remove that output, or pass --source to read another "
            "theme source.",
            code="C303",
        ) from None
    if not isinstance(data, dict):
        raise CliError(f"Evaluating {rel} returned no theme.", code="C303")
    return data


def detect(
    frontend: Frontend, configured: str = "", exclude: Path | None = None
) -> Detection | None:
    """The project's Tailwind theme, or None when it has no values of its own."""
    detection = Detection("tailwind", "")
    sources: list[str] = []
    theme_variables: dict[str, str] = {}
    theme_files: list[str] = []
    for sheet in frontend.stylesheets:
        if exclude is not None and sheet.resolve() == exclude.resolve():
            continue
        blocks = css.parse(frontend.read(sheet)).theme_blocks()
        if blocks:
            theme_files.append(frontend.rel(sheet))
            for block in blocks:
                theme_variables.update(block.declarations)

    config, major = find_config(frontend, configured)
    if config is not None and not config.is_file():
        raise CliError(
            f"@config names {config}, which does not exist. Fix the path in the stylesheet, or "
            "pass --source to read another theme source.",
            code="C303",
        )
    if config is not None and needs_evaluation(frontend.read(config)):
        data = evaluate(frontend, config)
        theme = data.get("theme")
        if isinstance(theme, dict):
            defaults = data.get("defaults") if data.get("mode") == "resolved" else None
            keys = data.get("userKeys")
            map_config_theme(
                detection,
                theme,
                defaults if isinstance(defaults, dict) else None,
                [str(k) for k in keys] if isinstance(keys, list) else None,
            )
            detection.files.append(frontend.rel(config))
            version = data.get("version") or "?"
            sources.append(f"{frontend.rel(config)}, tailwindcss {version}")
            if data.get("mode") != "resolved":
                detection.notes.append(
                    f"{frontend.rel(config)} was read as written (Tailwind 4 has no "
                    "resolveConfig): theme functions are reported, not evaluated."
                )
    if theme_variables:
        where = ", ".join(theme_files)
        map_theme_variables(detection, theme_variables, where)
        detection.files.extend(theme_files)
        sources.append(f"@theme in {where}")
    if not detection.found:
        return None
    version = f"Tailwind {major}" if major else "Tailwind"
    detection.label = f"{version} theme ({', plus '.join(sources)})"
    if any(m.scheme == "light" and "-color-" in m.token for m in detection.mappings):
        detection.notes.append(
            "Tailwind colours are not per scheme: dark mode keeps Karni's default dark colours "
            "for literal values. Add a .dark block to karni-theme.css to set them."
        )
    return detection
