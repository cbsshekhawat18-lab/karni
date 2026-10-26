"""SITE020 for ``karni check``: every ``{% karni_form "<name>" %}`` names a form that exists.

A name is checked the way the tag resolves it (:func:`karni_site.forms.resolve_form`),
so a renamed model or a typo fails the build instead of the contact page.
A variable (``{% karni_form form_name %}``) is only known when the page renders.
"""

from __future__ import annotations

import re

from django.utils.text import smart_split

__all__ = ["unknown_forms"]

_TAG = re.compile(r"\{%-?\s*karni_form\s+(.*?)\s*-?%\}", re.S)


def unknown_forms() -> list[str]:
    """``SITE020: <template>:<line>: ...`` for each tag whose form does not resolve."""
    from karni_site.checks import template_dirs
    from karni_site.forms import UnknownForm, resolve_form

    failures: list[str] = []
    for directory in template_dirs():
        for path in sorted(directory.rglob("*.html")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in _TAG.finditer(text):
                first = next(iter(smart_split(match.group(1))), "")
                if first[:1] not in "\"'" or first[-1:] != first[:1]:
                    continue  # a variable: only known when the page renders
                try:
                    resolve_form(first[1:-1])
                except UnknownForm as exc:
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(f"SITE020: {path}:{line}: {exc.message}")
    return failures
