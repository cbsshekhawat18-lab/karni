"""karni-site's error codes (prefix ``SITE``), registered with Karni's registry."""

from __future__ import annotations

from typing import Final

from karni.errorcodes import ErrorCode

__all__ = ["CODES"]

_SOURCE = "karni_site"

CODES: Final[tuple[ErrorCode, ...]] = (
    ErrorCode(
        code="SITE001",
        title="Templates do not get the request",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "{% ifactive %} reads the current page from the request, and {% csp_hash %} and "
            "{% csp_allow %} add to the request's Content-Security-Policy. Without "
            "django.template.context_processors.request in the template engine's "
            "context_processors, no menu item is ever current and the design's inline "
            "scripts are blocked in production."
        ),
        fix=(
            "Add 'django.template.context_processors.request' to "
            "TEMPLATES[0]['OPTIONS']['context_processors'] in config/settings.py "
            "(karni_settings() includes it unless the project replaced TEMPLATES)."
        ),
    ),
    ErrorCode(
        code="SITE002",
        title="{% ifactive %} names a URL the project does not have",
        kind="check",
        source=f"{_SOURCE}.checks",
        why=(
            "A menu item marks itself current when the request resolved to one of the URL "
            "names in its {% ifactive %}. A name that no URL pattern has, after a view was "
            "renamed or removed, never matches, so the item is never marked and nothing fails."
        ),
        fix=(
            "Use the name `karni routes` lists for that page (`<app>:<name>`), or remove the "
            "name from the tag."
        ),
    ),
    ErrorCode(
        code="SITE003",
        title="A karni_site template tag is written wrongly",
        kind="exception",
        source=f"{_SOURCE}.templatetags.karni_site",
        why=(
            "{% ifactive %} needs at least one URL name or path. {% csp_hash %} takes nothing, "
            "or `attribute`. {% csp_allow %} takes arguments like "
            '"font-src https://fonts.gstatic.com". The template does not compile otherwise.'
        ),
        fix="Write the tag as the message shows. The karni-site README has an example of each.",
    ),
)
