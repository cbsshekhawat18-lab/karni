"""One way to deprecate a Karni public API.

Karni's policy (CLAUDE.md): a public API change warns for one minor release
and is removed at the next major. Every deprecated name calls
:func:`warn_deprecated`, so every warning has the same shape: what is
deprecated, its replacement, the Karni version that removes it, and a link
to its migration note (``docs/migrations/<version>.md``) built from
:data:`DOCS_BASE_URL`::

    Model.all_objects is deprecated; use Model.objects.without("soft_delete",
    reason=...) instead. It will be removed in Karni 1.0. See
    https://github.com/karni/karni/blob/main/docs/migrations/0.2.md#all_objects

Each deprecation also has an entry in Karni's machine-readable changelog
(:mod:`karni.changelog`), which ``karni upgrade`` reads to rewrite or report
every use before the removal lands; tests keep the two in step.

All of them use one category, :class:`KarniDeprecationWarning` (a
``DeprecationWarning``), so a project can find every caller in one run:
``python -W error::karni.deprecation.KarniDeprecationWarning manage.py test``
(or pytest's ``filterwarnings``).

Override / escape hatch: filter by category or message with the standard
:mod:`warnings` machinery; :func:`deprecation_message` builds the text alone
for callers that report it some other way.
"""

from __future__ import annotations

import warnings

# One constant for every docs link Karni builds (deprecation warnings here,
# `karni upgrade`'s report through the changelog), defined where karni-cli
# can read it without importing Django.
from karni.changelog import DOCS_BASE_URL, docs_url

__all__ = [
    "DOCS_BASE_URL",
    "KarniDeprecationWarning",
    "deprecation_message",
    "docs_url",
    "warn_deprecated",
]


class KarniDeprecationWarning(DeprecationWarning):
    """Category of every warning raised through :func:`warn_deprecated`."""


def deprecation_message(old: str, new: str, *, removed_in: str, doc_anchor: str) -> str:
    """The stable message text :func:`warn_deprecated` emits."""
    return (
        f"{old} is deprecated; use {new} instead. "
        f"It will be removed in Karni {removed_in}. See {docs_url(doc_anchor)}"
    )


def warn_deprecated(
    old: str,
    new: str,
    *,
    removed_in: str,
    doc_anchor: str,
    stacklevel: int = 2,
) -> None:
    """Emit a :class:`KarniDeprecationWarning` for ``old`` (replaced by ``new``).

    ``stacklevel`` counts from the deprecated callable, exactly as if it had
    called :func:`warnings.warn` itself: the default ``2`` attributes the
    warning to whoever called the deprecated API, which is where the fix
    goes.
    """
    warnings.warn(
        deprecation_message(old, new, removed_in=removed_in, doc_anchor=doc_anchor),
        KarniDeprecationWarning,
        stacklevel=stacklevel + 1,
    )
