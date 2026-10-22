"""Redaction for everything written under ``.karni/`` — the audit log's rules, applied everywhere.

A value is replaced by ``"[redacted]"`` when:

* **its name says so** — a key, header, query parameter, form field, setting
  or local variable whose name contains one of ``KARNI_AUDIT_REDACT``
  (``password``, ``token``, ``secret``, ``key`` by default), or that some
  model declares in ``Karni.sensitive`` (the same rule
  :func:`karni.audit.capture.sensitive_fields` applies to the change log);
* **it is a header that carries credentials** — ``Authorization`` and
  ``Proxy-Authorization`` (the scheme is kept: ``Bearer [redacted]``),
  ``Cookie`` (cookie names are kept), ``Set-Cookie``, ``X-CSRFToken``;
* **its value is a known secret** — ``SECRET_KEY`` (and its fallbacks), every
  string setting whose name is sensitive, database and broker passwords, and
  for the request being captured every value that was redacted by name above
  (the password in the body, the bearer token, the cookie values). A string
  equal to a known secret is replaced; a longer string containing one has
  that part replaced, wherever it appears — a traceback local, an exception
  message, a SQL statement;
* **it looks like a JSON Web Token** (``eyJ…​.…​.…``), under any name — the
  ``access`` and ``refresh`` of a login response, a token in a body field.

Override / escape hatches: ``KARNI_AUDIT_REDACT`` (the name substrings) and
``Karni.sensitive`` on a model; :meth:`Redactor.add_secret` for a value only
your code knows.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from functools import cache
from typing import Any, Final
from urllib.parse import urlsplit

from django.conf import settings

from karni.audit import REDACTED

__all__ = ["CREDENTIAL_HEADERS", "REDACTED", "Redactor", "active_redactor", "declared_sensitive"]

#: Headers whose value is always a credential (lower case).
CREDENTIAL_HEADERS: Final = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-csrftoken", "x-csrf-token"}
)

#: A secret this long or longer is also cut out of longer strings.
_SCRUB_MIN: Final = 6
#: Shorter secrets (still at least this long) are matched only as whole values.
_EXACT_MIN: Final = 3
#: A JSON Web Token (header.payload.signature, base64url): a bearer credential
#: wherever it appears — a login response's ``access``, a body field.
_JWT: Final = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}")

_active: ContextVar[Redactor | None] = ContextVar("karni_debug_redactor", default=None)


@cache
def declared_sensitive() -> frozenset[str]:
    """Every field name some installed model lists in ``Karni.sensitive`` (lower case)."""
    from django.apps import apps

    from karni.meta import karni_option

    found: set[str] = set()
    for model in apps.get_models():
        declared = karni_option(model, "sensitive", ()) or ()
        if isinstance(declared, str):
            continue
        found.update(str(name).lower() for name in declared)
    return frozenset(found)


def _pattern() -> re.Pattern[str]:
    from karni.audit.capture import redact_patterns

    parts = [re.escape(str(part)) for part in redact_patterns() if str(part)]
    return re.compile("|".join(parts) if parts else r"(?!x)x", re.I)


def _url_password(value: Any) -> str | None:
    if not isinstance(value, str) or "@" not in value:
        return None
    try:
        return urlsplit(value).password
    except ValueError:
        return None


class Redactor:
    """Applies the rules in the module docstring; one per captured request.

    ``Redactor()`` knows the settings' secrets; :meth:`collect` adds the
    request's own (call it before rendering anything of that request).
    """

    def __init__(self, *, names: Iterable[str] = (), secrets: Iterable[Any] = ()) -> None:
        self._pattern = _pattern()
        self._names = {str(name).lower() for name in names} | set(declared_sensitive())
        self._secrets: set[str] = set()
        self._settings_secrets()
        for secret in secrets:
            self.add_secret(secret)

    # --- what is secret -------------------------------------------------------

    def sensitive(self, name: Any) -> bool:
        """True when a value stored under ``name`` must never be recorded."""
        text = str(name)
        return text.lower() in self._names or self._pattern.search(text) is not None

    def add_secret(self, value: Any) -> None:
        """Treat ``value`` as a secret wherever it appears from now on."""
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, str) and len(value.strip()) >= _EXACT_MIN and value != REDACTED:
            self._secrets.add(value)

    def _settings_secrets(self) -> None:
        self.add_secret(getattr(settings, "SECRET_KEY", None))
        for fallback in getattr(settings, "SECRET_KEY_FALLBACKS", None) or ():
            self.add_secret(fallback)
        for name in dir(settings):
            if not name.isupper():
                continue
            try:
                value = getattr(settings, name)
            except Exception:  # noqa: BLE001 - a lazy setting that fails is not our concern
                continue
            if self.sensitive(name):
                self.add_secret(value)
            self.add_secret(_url_password(value))
            if isinstance(value, Mapping):
                self._mapping_secrets(value, depth=0)

    def _mapping_secrets(self, value: Mapping[Any, Any], depth: int) -> None:
        if depth > 3:
            return
        for key, item in value.items():
            if isinstance(item, Mapping):
                self._mapping_secrets(item, depth + 1)
            elif self.sensitive(key):
                self.add_secret(item)
            else:
                self.add_secret(_url_password(item))

    def collect(self, data: Any, *, key: Any = None, depth: int = 0) -> None:
        """Learn the secrets in ``data`` (a body, a query): values under sensitive keys."""
        if depth > 20:
            return
        if key is not None and self.sensitive(key):
            for leaf in _leaves(data):
                self.add_secret(leaf if isinstance(leaf, str) else str(leaf))
            return
        if isinstance(data, Mapping):
            for name, item in data.items():
                self.collect(item, key=name, depth=depth + 1)
        elif isinstance(data, list | tuple):
            for item in data:
                self.collect(item, depth=depth + 1)

    def collect_headers(self, headers: Mapping[str, str]) -> None:
        """Learn the credentials in request headers (bearer token, cookie values, CSRF token)."""
        for name, value in headers.items():
            lower = name.lower()
            if lower == "cookie":
                for part in str(value).split(";"):
                    self.add_secret(part.partition("=")[2].strip())
            elif lower in ("authorization", "proxy-authorization"):
                self.add_secret(value)
                self.add_secret(str(value).partition(" ")[2].strip())
            elif lower in CREDENTIAL_HEADERS or self.sensitive(lower):
                self.add_secret(value)

    # --- rendering ------------------------------------------------------------

    def scrub(self, text: str) -> str:
        """``text`` with every known secret, and anything shaped like a JWT, cut out."""
        if not text:
            return text
        if text in self._secrets:
            return REDACTED
        for secret in sorted(self._secrets, key=len, reverse=True):
            if len(secret) >= _SCRUB_MIN and secret in text:
                text = text.replace(secret, REDACTED)
        return _JWT.sub(REDACTED, text) if "eyJ" in text else text

    def value(self, value: Any, *, key: Any = None, depth: int = 0) -> Any:
        """A JSON value with sensitive keys redacted and known secrets scrubbed."""
        if key is not None and self.sensitive(key):
            return REDACTED
        if depth > 20:
            return "…"
        if isinstance(value, Mapping):
            return {
                str(name): self.value(item, key=name, depth=depth + 1)
                for name, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [self.value(item, depth=depth + 1) for item in value]
        if isinstance(value, str):
            return self.scrub(value)
        if value is None or isinstance(value, bool | int | float):
            return value
        return self.scrub(str(value))

    def headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        """Request headers with credentials redacted (scheme and cookie names kept)."""
        out: dict[str, str] = {}
        for name, value in headers.items():
            lower = name.lower()
            text = str(value)
            if lower == "cookie":
                names = [part.partition("=")[0].strip() for part in text.split(";") if part.strip()]
                out[name] = "; ".join(f"{cookie}={REDACTED}" for cookie in names)
            elif lower in ("authorization", "proxy-authorization"):
                scheme, _, credentials = text.partition(" ")
                out[name] = f"{scheme} {REDACTED}" if credentials else REDACTED
            elif lower in CREDENTIAL_HEADERS or self.sensitive(lower):
                out[name] = REDACTED
            else:
                out[name] = self.scrub(text)
        return out

    def query(self, pairs: Iterable[tuple[str, list[str]]]) -> dict[str, list[str]]:
        """``{name: [values]}`` from ``QueryDict.lists()``, sensitive names redacted."""
        return {
            str(name): [REDACTED] * len(values)
            if self.sensitive(name)
            else [self.scrub(str(value)) for value in values]
            for name, values in pairs
        }


def _leaves(data: Any) -> Iterable[Any]:
    if isinstance(data, Mapping):
        for item in data.values():
            yield from _leaves(item)
    elif isinstance(data, list | tuple):
        for item in data:
            yield from _leaves(item)
    elif data is not None and not isinstance(data, bool):
        yield data


def active_redactor() -> Redactor:
    """The redactor of the request being captured, else a fresh one (settings secrets only)."""
    current = _active.get()
    return current if current is not None else Redactor()


def activate(redactor: Redactor | None) -> Any:
    """Make ``redactor`` the active one; returns the token for :func:`deactivate`."""
    return _active.set(redactor)


def deactivate(token: Any) -> None:
    _active.reset(token)
