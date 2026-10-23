"""The ``# karni:urls`` marker in config/urls.py, where ``karni make site`` inserts routes.

Changelog entry ``urls-marker`` (0.4.1). Migration note:
docs/migrations/0.4.1.md#a-marker-for-project-routes-in-configurlspy.

The marker goes inside ``urlpatterns`` right before ``*welcome_urls()`` (and
before the comment lines attached to it), so the welcome route stays last. A
URLconf without ``*welcome_urls()`` is reported for a person to place the
marker. A URLconf that already has it is left alone.
"""

from __future__ import annotations

from pathlib import Path

from karni_cli.upgrades.codemod import Codemod, Outcome, Site
from karni_cli.urls_edit import URLS_MARKER, has_marker

CONFIG_URLS = "config/urls.py"
ANCHOR = "*welcome_urls()"
COMMENT = "# Project routes that `karni make` wires (a public site's include goes here)."


def insert_marker(text: str) -> str | None:
    """``text`` with the marker before ``*welcome_urls()``, or ``None`` without that anchor."""
    lines = text.splitlines()
    index = next((i for i, line in enumerate(lines) if line.strip().startswith(ANCHOR)), None)
    if index is None:
        return None
    indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
    while index > 0 and lines[index - 1].strip().startswith("#"):
        index -= 1
    lines[index:index] = [indent + COMMENT, indent + URLS_MARKER]
    return "\n".join(lines) + "\n"


class UrlsMarker(Codemod):
    def apply(self, root: Path) -> Outcome:
        path = root / CONFIG_URLS
        if not path.is_file():
            return Outcome()
        text = path.read_text(encoding="utf-8")
        if has_marker(text):
            return Outcome()
        updated = insert_marker(text)
        if updated is None:
            return Outcome(
                sites=[
                    Site(
                        CONFIG_URLS,
                        0,
                        f"add a `{URLS_MARKER}` line inside urlpatterns, after your routes "
                        "(`karni make site` inserts the site's include there)",
                    )
                ]
            )
        path.write_text(updated, encoding="utf-8")
        return Outcome(files={CONFIG_URLS: 1})


CODEMOD = UrlsMarker()
