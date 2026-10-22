"""What a detection finds: token mappings, values left unmapped, and Karni's token names."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

#: Where a mapping is declared in karni-theme.css. ``both`` is ``:root, .dark``:
#: a value that references another variable must be recomputed in a dark
#: subtree (a custom property declared on :root alone is inherited computed).
Scheme = Literal["both", "light", "dark"]

#: The colour roles Karni's components read (``--karni-color-<role>``). The
#: derived shades (-hover, -subtle, -border, overlay) follow these.
COLOR_ROLES: tuple[str, ...] = (
    "background",
    "foreground",
    "card",
    "card-foreground",
    "popover",
    "popover-foreground",
    "primary",
    "primary-foreground",
    "secondary",
    "secondary-foreground",
    "muted",
    "muted-foreground",
    "accent",
    "accent-foreground",
    "destructive",
    "destructive-foreground",
    "border",
    "input",
    "ring",
    "chart-1",
    "chart-2",
    "chart-3",
    "chart-4",
    "chart-5",
)

#: Names in other design systems that mean exactly one of Karni's colour roles.
COLOR_ALIASES: dict[str, str] = {
    "danger": "destructive",
    "error": "destructive",
    "danger-foreground": "destructive-foreground",
    "error-foreground": "destructive-foreground",
}

#: The corner radii Karni reads (``--karni-radius-<name>``).
RADIUS_NAMES: tuple[str, ...] = ("sm", "md", "lg", "xl", "full")
#: The shadows Karni reads; ``DEFAULT`` is the bare ``--karni-shadow``.
SHADOW_NAMES: tuple[str, ...] = ("sm", "DEFAULT", "md", "lg")
#: The font sizes Karni reads (``--karni-font-size-<n>``, ``--karni-font-leading-<n>``).
FONT_SIZE_NAMES: tuple[str, ...] = ("xs", "sm", "base", "lg", "xl", "2xl")
FONT_WEIGHT_NAMES: tuple[str, ...] = ("normal", "medium", "semibold", "bold")
TRACKING_NAMES: tuple[str, ...] = ("tight", "wide")
#: The spacing steps the @karni/ui preset defines (tailwind-preset.ts SPACE_STEPS;
#: a test keeps the two equal). Each reads --karni-space-<n>, else n x unit.
SPACE_STEPS: tuple[float, ...] = (
    0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40,
    44, 48, 52, 56, 60, 64, 72, 80, 96, 128,
)  # fmt: skip


def color_token(role: str) -> str:
    return f"--karni-color-{role}"


def radius_token(name: str) -> str:
    return f"--karni-radius-{name}"


def shadow_token(name: str) -> str:
    return "--karni-shadow" if name == "DEFAULT" else f"--karni-shadow-{name}"


def space_token(step: float) -> str:
    return f"--karni-space-{format_step(step)}"


def format_step(step: float) -> str:
    """``0.5`` -> ``0-5``, ``4.0`` -> ``4`` (the preset's step names)."""
    text = f"{step:g}"
    return text.replace(".", "-")


def color_role(name: str) -> str | None:
    """Karni's role for a colour name that clearly means it (``danger`` -> destructive)."""
    name = name.strip().lower()
    if name in COLOR_ROLES:
        return name
    return COLOR_ALIASES.get(name)


_KARNI_REF = re.compile(r"--karni-")


def references_karni(value: str) -> bool:
    """True for a value that already reads a Karni token (the @karni/ui preset's own)."""
    return bool(_KARNI_REF.search(value))


def references_variable(value: str) -> bool:
    return "var(" in value


@dataclass(frozen=True)
class Mapping:
    """One Karni token set from one value of the project's theme."""

    source: str  # where the value comes from: "--primary", "palette.primary.main"
    token: str  # the Karni custom property: "--karni-color-primary"
    value: str  # what karni-theme.css declares: "var(--primary)"
    scheme: Scheme = "light"
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"from": self.source, "to": self.token, "value": self.value, "scheme": self.scheme}
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class Unmapped:
    """A value of the project's theme that karni-theme.css does not carry, and why."""

    name: str
    reason: str
    #: The exact line the project could add to karni-theme.css, when there is one.
    suggestion: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"name": self.name, "reason": self.reason}
        if self.suggestion:
            out["suggestion"] = self.suggestion
        return out


@dataclass
class Detection:
    """The design system a detector found and what it maps."""

    source: str  # "shadcn", "tailwind", "mui", "chakra", "mantine", "defaults"
    label: str  # "shadcn/ui (Tailwind 4 format: full colours, oklch)"
    files: list[str] = field(default_factory=list)  # read, relative to the frontend
    mappings: list[Mapping] = field(default_factory=list)
    unmapped: list[Unmapped] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Lines written commented out (Karni's defaults, when nothing was found).
    commented: list[Mapping] = field(default_factory=list)

    def add(
        self, source: str, token: str, value: str, scheme: Scheme = "light", note: str = ""
    ) -> None:
        """Map ``token``; a later value for the same token and scheme replaces the earlier."""
        self.mappings = [m for m in self.mappings if (m.token, m.scheme) != (token, scheme)]
        self.mappings.append(Mapping(source, token, value, scheme, note))

    def skip(self, name: str, reason: str, suggestion: str = "") -> None:
        if any(u.name == name for u in self.unmapped):
            return
        self.unmapped.append(Unmapped(name, reason, suggestion))

    def has(self, token: str, scheme: Scheme | None = None) -> bool:
        return any(m.token == token and scheme in (None, m.scheme) for m in self.mappings)

    @property
    def found(self) -> bool:
        """Anything to report: a mapping, or a value the project has that Karni cannot take."""
        return bool(self.mappings or self.unmapped)
