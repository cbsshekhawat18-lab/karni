"""Words a field highlights, rendered in the design's markup: the ``highlight`` filter.

A site has one convention for highlighted words, ``KARNI_SITE_HIGHLIGHT``:
the marker a client types around them (``==words==`` by default) and the
element they render in (``<mark>``). Editable blocks use it, and so do model
fields: ``karni design extract`` writes ``Custom homes, ==crafted for place==``
for a heading whose last words the design wraps in ``<span class="accent">``,
and staff edit the field in the admin the same way they edit a block.

``{{ project.heading|highlight }}``
    the words in ``KARNI_SITE_HIGHLIGHT``'s tag and class:
    ``Custom homes, <span class="accent">crafted for place</span>`` once the
    setting says ``"tag": "span", "class": "accent"``.
``{{ slide.badge|highlight:"span.dot" }}``, ``{{ x|highlight:"em" }}``
    another markup for this value, any tag with or without classes. The
    marker is still the setting's.
``{{ project.heading|highlight:"" }}``
    the words without the marks, for a ``<title>`` or an ``alt``.

Everything else is escaped: no HTML from a field reaches the page. A
backslash before the marker (``\\==``) keeps it as typed, as it does in an
editable block (:func:`karni_site.sanitize.apply_marks`).

Override / escape hatch: :func:`highlight` is a plain function, so a
project's own filter can call it with another markup.
"""

from __future__ import annotations

import re
from typing import Any, Final

from django.utils.html import conditional_escape
from django.utils.safestring import SafeString, mark_safe
from karni.exceptions import KarniValueError

from karni_site import sanitize

__all__ = ["highlight", "markup"]

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


def highlight(value: Any, spec: str | None = None) -> SafeString:
    """``value`` escaped, each part between two markers wrapped in the highlight markup.

    The marker is ``KARNI_SITE_HIGHLIGHT``'s. The markup is the setting's tag
    and class without ``spec``, else the one ``spec`` names (``""``: none).
    """
    mark = sanitize.highlight()
    if spec is None:
        opening, closing = (mark.start_tag(), mark.end_tag()) if mark.tag else ("", "")
    else:
        opening, closing = markup(str(spec))
    escaped = str(conditional_escape("" if value is None else value))
    marker = str(conditional_escape(mark.marker))
    # Every part was escaped above, the markup is a validated tag and class.
    return mark_safe(sanitize.apply_marks(escaped, marker, opening, closing))  # noqa: S308
