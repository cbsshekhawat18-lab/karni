"""Fingerprinted static files: ``KARNI_STATIC_STORAGE = "manifest"``.

:class:`ManifestStaticStorage` is Django's ``ManifestStaticFilesStorage``:
``collectstatic`` writes a copy of each file whose name carries a hash of its
content (``site.css`` becomes ``site.3f2a91c0b4d7.css``) and a manifest, and
``{% static %}`` names the copy. A file whose content changes gets a new name,
so a web server may tell browsers to keep the copies for a year. The original
names stay in ``STATIC_ROOT`` too, so an address written by hand (a script
that fetches ``/static/website/data.json``) keeps working, without the
fingerprint.

Django's storage fails where Karni prefers a broken link to a broken page.
Two differences:

* ``{% static %}`` for a file that is not in the manifest (a typo, a file
  added without ``collectstatic``) gives its plain name and logs a warning
  (logger ``karni.storage``), where Django's raises and the page answers 500.
* ``collectstatic`` keeps a stylesheet's ``url(...)`` to a file that does
  not exist as written and logs a warning, where Django's stops the whole
  run. A designer's CSS often names a font or image it does not ship.

Override / escape hatch: ``KARNI_STATIC_STORAGE`` takes a dotted path to any
storage class, and ``STORAGES`` in settings.py replaces the whole mapping.
Subclass this one to change ``manifest_name`` or the hashing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from re import Match
from typing import Any

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

__all__ = ["ManifestStaticStorage"]

logger = logging.getLogger("karni.storage")


class ManifestStaticStorage(ManifestStaticFilesStorage):
    """``ManifestStaticFilesStorage`` that names a missing file plainly instead of failing.

    Override / escape hatch: subclass it, or name another class in
    ``KARNI_STATIC_STORAGE``.
    """

    manifest_strict = False

    def stored_name(self, name: str) -> str:
        try:
            return str(super().stored_name(name))
        except ValueError as exc:
            logger.warning(
                "karni.storage: the static file %r is not in the manifest. Its plain name is "
                "used: run collectstatic, or fix the path (%s).",
                name,
                str(exc).split(" with <", 1)[0],
            )
            return name

    def url_converter(
        self, name: str, hashed_files: dict[str, Any], template: str | None = None
    ) -> Callable[[Match[str]], str]:
        convert = super().url_converter(name, hashed_files, template)

        def lenient(matchobj: Match[str]) -> str:
            try:
                return str(convert(matchobj))
            except ValueError as exc:
                logger.warning(
                    "karni.storage: %s names %r, which is not a static file (%s). The "
                    "reference is kept as written.",
                    name,
                    matchobj.groupdict().get("url"),
                    str(exc).split(" with <", 1)[0],
                )
                return str(matchobj.groupdict()["matched"])

        return lenient
