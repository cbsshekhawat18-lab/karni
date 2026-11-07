"""The errors an extraction answers with: a code from :mod:`karni_ai.errorcodes` and an HTTP status.

:class:`ExtractionRefused` is anything refused before or after the provider
call (the resource, the user's right to create, the source, the URL, the
budget). :class:`ProviderError` is the provider call itself failing or
answering something that cannot be used. It carries the tokens the call used
when the provider reported them, so the usage log stays exact.

The endpoint answers ``{"code": ..., "detail": ...}`` with :attr:`status`.
"""

from __future__ import annotations

from karni.exceptions import KarniValueError

from karni_ai.providers.base import Usage

__all__ = ["ExtractionRefused", "ProviderError"]


class ExtractionRefused(KarniValueError):
    """Experimental. An extraction refused with a code and the HTTP status it is answered with."""

    status: int = 400

    def __init__(self, message: str, *, code: str, status: int = 400) -> None:
        super().__init__(message, code=code)
        self.status = status


class ProviderError(KarniValueError):
    """Experimental. The provider call failed (AI006) or its answer cannot be used (AI007).

    ``usage`` is what the provider billed for the call, when it said (a cut
    off or declined answer still costs its tokens), else zero.
    """

    status: int = 502

    def __init__(self, message: str, *, code: str = "AI006", usage: Usage | None = None) -> None:
        super().__init__(message, code=code)
        self.usage = usage if usage is not None else Usage(0, 0)
