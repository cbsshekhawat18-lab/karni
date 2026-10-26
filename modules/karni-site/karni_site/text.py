"""Words a design highlights inside a line, kept as ``*marked words*`` in content.

``karni design extract`` writes ``Custom homes, *crafted for place*`` for a
heading whose last words the design wraps in ``<span class="accent">``. The
``highlight`` filter (``{% load karni_site %}``) writes that markup back,
everything else escaped:

``{{ project.heading|highlight:"span.accent" }}``
    ``Custom homes, <span class="accent">crafted for place</span>``.
``{{ slide.badge|highlight:"span.dot" }}``, ``{{ x|highlight:"em" }}``
    any tag, with or without classes.
``{{ project.heading|highlight:"" }}``
    the words without the marks, for a ``<title>`` or an ``alt``.

A literal asterisk is written ``\\*`` in the content. Staff edit the field in
the admin as plain text with asterisks: no HTML reaches the page.

Override / escape hatch: :func:`highlight` is a plain function, so a
project's own filter can call it with another markup.
"""

from __future__ import annotations

import re
from typing import Any, Final

from django.utils.html import conditional_escape
from django.utils.safestring import SafeString, mark_safe
from karni.exceptions import KarniValueError

__all__ = ["highlight", "markup"]

_MARKED: Final = re.compile(r"(?<!\\)\*(.+?)(?<!\\)\*", re.DOTALL)
_TAG: Final = re.compile(r"^[a-z][a-z0-9-]*$")
_CLASS: Final = re.compile(r"^-?[_a-zA-Z][-_a-zA-Z0-9]*$")


def markup(spec: str) -> tuple[str, str]:
    """``"span.accent"`` as its opening and closing tags, and ``("", "")`` for ``""``.

    :raises KarniValueError: (``SITE003``) the spec is not a tag name with optional classes.
    """
    if not spec:
        return "", ""
    tag, *classes = spec.strip().split(".")
    if not _TAG.match(tag) or not all(_CLASS.match(name) for name in classes):
        raise KarniValueError(
            "highlight takes a tag with optional classes, such as span.accent or em, "
            f"not {spec!r}.",
            code="SITE003",
        )
    attribute = f' class="{" ".join(classes)}"' if classes else ""
    return f"<{tag}{attribute}>", f"</{tag}>"


def highlight(value: Any, spec: str = "em") -> SafeString:
    """``value`` escaped, each ``*marked*`` part wrapped in the markup ``spec`` names."""
    opening, closing = markup(str(spec))
    escaped = str(conditional_escape("" if value is None else value))
    wrapped = _MARKED.sub(lambda match: f"{opening}{match.group(1)}{closing}", escaped)
    return mark_safe(wrapped.replace("\\*", "*"))  # noqa: S308 - every part was escaped above
