"""Wiring the generated files into the app, when the app has the scaffold's exact pattern.

``karni new`` writes ``import "@karni/ui/styles.css";`` in src/main.tsx and
``<KarniProvider client={client}>`` in src/App.tsx. When those lines are
there, ``karni ui detect`` adds its import (and the ``primitives`` prop) next
to them. Anything else is the project's own code: the report prints the line
to add instead of editing it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from karni_cli.uitheme.frontend import SOURCE_SUFFIXES, Frontend

STYLES_IMPORT = re.compile(r"""^import\s+["']@karni/ui/styles\.css["'];?[ \t]*$""", re.MULTILINE)
PROVIDER_OPEN = "<KarniProvider client={client}>"
_KARNI_IMPORT = re.compile(r"""^.*\bfrom\s+["']@karni/ui["'];?[ \t]*$""", re.MULTILINE)


@dataclass
class Edit:
    """One change to a project file: made (``content`` set) or to be made by hand."""

    file: Path | None
    done: bool
    message: str
    content: str = ""

    def as_dict(self, frontend: Frontend) -> dict[str, object]:
        return {
            "file": frontend.rel(self.file) if self.file else None,
            "done": self.done,
            "changed": bool(self.content),
            "message": self.message,
        }


def specifier(from_file: Path, target: Path) -> str:
    """The relative import of ``target`` from ``from_file`` (``./karni-theme.css``)."""
    rel = Path(os.path.relpath(target, from_file.parent)).as_posix()
    return rel if rel.startswith("../") else f"./{rel}"


def theme_import(frontend: Frontend, theme: Path) -> Edit:
    """Import karni-theme.css right after ``@karni/ui/styles.css`` in the entry module."""
    entries = frontend.entry_files()
    for entry in entries:
        text = frontend.read(entry)
        line = f'import "{specifier(entry, theme)}";'
        if theme.name in text and specifier(entry, theme) in text:
            return Edit(entry, True, f"{frontend.rel(entry)} already imports {theme.name}")
        match = STYLES_IMPORT.search(text)
        if match:
            content = text[: match.end()] + "\n" + line + text[match.end() :]
            return Edit(
                entry,
                True,
                f"{frontend.rel(entry)}: {line} (after @karni/ui/styles.css)",
                content,
            )
    for sheet in frontend.stylesheets:
        text = frontend.read(sheet)
        if re.search(r"""@import\s+["']@karni/ui/styles\.css["']""", text):
            line = f'@import "{specifier(sheet, theme)}";'
            if theme.name in text:
                return Edit(sheet, True, f"{frontend.rel(sheet)} already imports {theme.name}")
            return Edit(
                sheet,
                False,
                f'Add to {frontend.rel(sheet)}, after @import "@karni/ui/styles.css": {line}',
            )
    if entries:
        entry = entries[0]
        line = f'import "{specifier(entry, theme)}";'
        return Edit(
            entry,
            False,
            f'Add to {frontend.rel(entry)}, before your own CSS: import "@karni/ui/styles.css"; '
            f"then {line}",
        )
    return Edit(
        None,
        False,
        f'Import {frontend.rel(theme)} after "@karni/ui/styles.css" in your entry module.',
    )


def provider_files(frontend: Frontend) -> list[Path]:
    src = frontend.root / "src"
    base = Frontend(src, frontend.package) if src.is_dir() else frontend
    return [
        path
        for path in base.files(SOURCE_SUFFIXES)
        if path.suffix in (".tsx", ".jsx")
        and path.stem != "karni-primitives"  # its header shows the KarniProvider line
        and "<KarniProvider" in frontend.read(path)
    ]


def primitives_location(frontend: Frontend, suffix: str) -> Path:
    """Next to the file that renders KarniProvider, else in src/."""
    files = provider_files(frontend)
    if len(files) == 1:
        return files[0].parent / f"karni-primitives{suffix}"
    base = frontend.root / "src" if (frontend.root / "src").is_dir() else frontend.root
    return base / f"karni-primitives{suffix}"


def primitives_prop(frontend: Frontend, primitives: Path) -> Edit:
    """Pass ``primitives={primitives}`` to the scaffold's ``<KarniProvider client={client}>``."""
    files = provider_files(frontend)
    module = specifier(files[0] if files else primitives, primitives).rsplit(".", 1)[0]
    import_line = f'import {{ primitives }} from "{module}";'
    by_hand = (
        f"{import_line} and pass primitives={{primitives}} to <KarniProvider> "
        "(<KarniProvider client={client} primitives={primitives}>)"
    )
    if len(files) != 1:
        where = "the file that renders <KarniProvider>" if not files else "your KarniProvider"
        return Edit(None, False, f"Add to {where}: {by_hand}")
    target = files[0]
    text = frontend.read(target)
    if "primitives={primitives}" in text:
        return Edit(target, True, f"{frontend.rel(target)} already passes primitives")
    karni_import = _KARNI_IMPORT.search(text)
    if text.count(PROVIDER_OPEN) != 1 or "primitives=" in text or karni_import is None:
        return Edit(target, False, f"Add to {frontend.rel(target)}: {by_hand}")
    content = text.replace(
        PROVIDER_OPEN, "<KarniProvider client={client} primitives={primitives}>", 1
    )
    karni_import = _KARNI_IMPORT.search(content)
    assert karni_import is not None  # same text before the provider line changed
    content = content[: karni_import.end()] + "\n" + import_line + content[karni_import.end() :]
    return Edit(
        target,
        True,
        f"{frontend.rel(target)}: <KarniProvider client={{client}} primitives={{primitives}}>",
        content,
    )
