"""Karni's exception hierarchy: every error carries a code and names its fix.

``KarniError`` (from :mod:`karni.errorcodes`) is the base. Each concrete class
also inherits the builtin or Django exception it replaces, so ``except
ImproperlyConfigured`` / ``except ValueError`` in existing code keeps working::

    from karni.exceptions import KarniImproperlyConfigured

    raise KarniImproperlyConfigured(
        f"{name}: Owned({path!r}) does not lead to the user model. ...",
        code="E104",
    )

``str(error)`` reads ``"E104: <message> See <docs url>"``. The registry entry
for the code (:func:`karni.errorcodes.get`, ``karni explain E104``,
``docs/errors.md``) explains why Karni objects and how to fix it in general;
the message names the specific class, field or setting.

Helpers build the other two shapes an error takes: :func:`api_error` (a DRF
400 whose ``ErrorDetail.code`` is the Karni code) and :func:`check_error` /
:func:`check_warning` (a Django system check message with id ``karni.<code>``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import CommandError

from karni.errorcodes import KarniError, docs_url

if TYPE_CHECKING:
    from rest_framework.exceptions import ValidationError

__all__ = [
    "KarniAssertionError",
    "KarniCommandError",
    "KarniError",
    "KarniImportError",
    "KarniImproperlyConfigured",
    "KarniLookupError",
    "KarniTypeError",
    "KarniValueError",
    "KarniWriteDeferred",
    "api_error",
    "check_error",
    "check_warning",
    "docs_url",
]


class KarniImproperlyConfigured(KarniError, ImproperlyConfigured):
    """A declaration or setting that cannot work (the most common Karni error)."""


class KarniValueError(KarniError, ValueError):
    """An argument with the right type but an unusable value."""


class KarniTypeError(KarniError, TypeError):
    """An argument of the wrong type."""


class KarniLookupError(KarniError, LookupError):
    """A name (scope, schedule, provider, ...) that is not registered."""


class KarniImportError(KarniError, ImportError):
    """An optional dependency that is not installed (code ``E501``)."""

    code = "E501"


class KarniAssertionError(KarniError, AssertionError):
    """A karni.testing assertion failed; test runners report it as a failure."""


class KarniCommandError(KarniError, CommandError):
    """A management command failed; Django prints the message and exits non-zero."""

    def __init__(self, message: str, *, code: str | None = None, returncode: int = 1) -> None:
        KarniError.__init__(self, message, code=code)
        self.returncode = returncode


class KarniWriteDeferred(KarniError):
    """A write that a ``karni.signals.pre_write`` receiver turned into something else.

    Raised before any SQL runs, so nothing is written and nothing needs
    rolling back. ``payload`` is what the API answers with (HTTP ``status``,
    202 by default) and ``str(exc)`` is what the admin shows; the ``code``
    belongs to whoever deferred the write (``karni-approvals``: ``APR001``).
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        payload: dict[str, Any] | None = None,
        status: int = 202,
    ) -> None:
        super().__init__(message, code=code)
        self.payload: dict[str, Any] = payload if payload is not None else {}
        self.status = status


def _with_link(code: str, text: str) -> str:
    return f"{text} See {docs_url(code)}"


def api_error(code: str, message: str, *, field: str | None = None) -> ValidationError:
    """A DRF 400 for a bad request parameter: ``ErrorDetail(code=<code>)``, fix + link.

    ``raise api_error("E126", "Unknown expand key 'venu'. Allowed: venue, tiers.",
    field="expand")`` responds ``{"expand": ["E126: Unknown ... See <url>"]}``.
    """
    from rest_framework.exceptions import ErrorDetail, ValidationError

    detail = ErrorDetail(f"{code}: {_with_link(code, message)}", code=code)
    return ValidationError({field: [detail]} if field else [detail], code=code)


def check_error(code: str, message: str, *, hint: str, obj: Any = None) -> checks.Error:
    """A system check error with id ``karni.<code>``; ``hint`` is the fix, then the link."""
    return checks.Error(message, hint=_with_link(code, hint), obj=obj, id=f"karni.{code}")


def check_warning(code: str, message: str, *, hint: str, obj: Any = None) -> checks.Warning:
    """A system check warning with id ``karni.<code>`` (silence it in SILENCED_SYSTEM_CHECKS)."""
    return checks.Warning(message, hint=_with_link(code, hint), obj=obj, id=f"karni.{code}")
