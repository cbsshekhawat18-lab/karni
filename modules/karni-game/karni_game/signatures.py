"""Signed server-to-server requests: a portal's callback, a realtime server's report.

The sender puts two headers on the request::

    X-Karni-Timestamp: 1763541000
    X-Karni-Signature: sha256=<hex of HMAC-SHA256(secret, "<timestamp>." + raw body)>

:class:`HmacVerifier` checks both: the timestamp is within
``KARNI_GAME_SIGNATURE_TOLERANCE`` seconds of the server's clock, and the
signature is the body's under the shared secret (compared in constant time).
Anything else is ``403 GAME019``. :func:`sign` makes the headers, for a sender
written in Python and for tests.

Override / escape hatch: a portal that signs its callback another way gets a
verifier of its own: subclass :class:`HmacVerifier`, override ``verify``, and
name it in ``KARNI_GAME_PORTALS[<portal>]["verifier"]``.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

from karni_game import conf
from karni_game.errors import game_error

__all__ = ["SIGNATURE_HEADER", "TIMESTAMP_HEADER", "HmacVerifier", "sign"]

TIMESTAMP_HEADER = "X-Karni-Timestamp"
SIGNATURE_HEADER = "X-Karni-Signature"


def _digest(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def sign(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """The two headers that sign ``body`` with ``secret``."""
    stamp = str(int(timestamp if timestamp is not None else time.time()))
    return {TIMESTAMP_HEADER: stamp, SIGNATURE_HEADER: f"sha256={_digest(secret, stamp, body)}"}


class HmacVerifier:
    """Checks the timestamp and the HMAC-SHA256 signature of a request's raw body."""

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def refuse(self, why: str) -> Exception:
        return game_error("GAME019", f"The request's signature does not verify: {why}.", status=403)

    def verify(self, request: Any) -> None:
        if not self.secret:
            raise self.refuse("no secret is set for this sender")
        stamp = str(request.headers.get(TIMESTAMP_HEADER, ""))
        given = str(request.headers.get(SIGNATURE_HEADER, ""))
        if not stamp.isdigit() or not given.startswith("sha256="):
            raise self.refuse(f"{TIMESTAMP_HEADER} and {SIGNATURE_HEADER} are both needed")
        tolerance = int(conf.get("KARNI_GAME_SIGNATURE_TOLERANCE"))
        if abs(time.time() - int(stamp)) > tolerance:
            raise self.refuse(f"the timestamp is more than {tolerance} seconds away")
        expected = _digest(self.secret, stamp, bytes(request.body))
        if not hmac.compare_digest(expected, given.removeprefix("sha256=")):
            raise self.refuse("the signature is not the body's")
