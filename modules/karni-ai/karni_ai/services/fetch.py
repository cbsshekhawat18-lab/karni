"""Fetching a URL for extraction without reaching the server's own network.

A URL a user gives is fetched by the server, so the fetch is the classic way
in to the server's private network (server-side request forgery). The
:class:`Fetcher` refuses (AI011):

* a scheme other than ``http`` and ``https``, a user name or password in the
  URL, and a port outside ``KARNI_AI_FETCH_PORTS`` (80 and 443).
* a host whose addresses are not all public: private, loopback, link-local,
  shared, reserved, multicast and unspecified addresses, IPv4 inside IPv6
  included. The connection then goes to the address that was checked, never
  to a second DNS answer, and HTTPS still verifies the certificate for the
  host name.
* a redirect to any of the above, and more than
  ``KARNI_AI_FETCH_MAX_REDIRECTS`` redirects. Each one is checked like the
  first address.

and the response (AI012) when it is an HTTP error, larger than
``KARNI_AI_FETCH_MAX_BYTES`` (by its ``Content-Length`` or while reading),
compressed (it asks for ``identity``), or slower than
``KARNI_AI_FETCH_TIMEOUT``, which bounds the whole fetch: connecting, every
redirect and reading.

Override / escape hatch: subclass :class:`Fetcher` (``allowed_address``,
``resolve``, ``open``, ``headers``) and point ``KARNI_AI_FETCHER`` at it, for
example to send requests through an egress proxy.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any, ClassVar, Final
from urllib.parse import urljoin, urlsplit

from karni_ai import conf
from karni_ai.exceptions import ExtractionRefused

__all__ = ["Fetched", "Fetcher", "Target", "public_address"]

_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_CHUNK: Final = 64 * 1024


@dataclass(frozen=True)
class Target:
    """One checked URL: what to connect to and what to ask for."""

    url: str
    scheme: str
    host: str
    port: int
    path: str


@dataclass(frozen=True)
class Fetched:
    """Experimental. A fetched response: the final URL, its media type, charset and body."""

    url: str
    content_type: str
    charset: str | None
    body: bytes


def public_address(address: str) -> bool:
    """Whether ``address`` is a public unicast address (IPv4 inside IPv6 unwrapped)."""
    try:
        ip: Any = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is not None:
            ip = inner
    return bool(ip.is_global and not ip.is_multicast)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to the checked address, sends the host name in ``Host``."""

    def __init__(self, host: str, port: int, *, address: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to the checked address, verifies the certificate for the host name."""

    def __init__(
        self, host: str, port: int, *, address: str, timeout: float, context: ssl.SSLContext
    ) -> None:
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._pinned_context = context

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._pinned_context.wrap_socket(sock, server_hostname=self.host)


class Fetcher:
    """Experimental. Fetches one public ``http`` or ``https`` URL within the limits in settings."""

    schemes: ClassVar[tuple[str, ...]] = ("http", "https")
    user_agent: ClassVar[str] = "karni-ai/0.4 (structured extraction)"

    def __init__(self) -> None:
        self.timeout = float(conf.get("KARNI_AI_FETCH_TIMEOUT"))
        self.max_bytes = int(conf.get("KARNI_AI_FETCH_MAX_BYTES"))
        self.max_redirects = int(conf.get("KARNI_AI_FETCH_MAX_REDIRECTS"))
        self.ports = {int(port) for port in conf.get("KARNI_AI_FETCH_PORTS")}

    # checks

    def check_url(self, url: str) -> Target:
        """The URL as a :class:`Target` (AI011 for a refused scheme, credentials or port)."""
        try:
            parts = urlsplit(url.strip())
            port = parts.port
        except ValueError as exc:
            raise ExtractionRefused(f"{url!r} is not a valid URL: {exc}.", code="AI011") from exc
        scheme = parts.scheme.lower()
        if scheme not in self.schemes:
            raise ExtractionRefused(
                f"Only http and https URLs are fetched, not {scheme or 'a URL without a scheme'}.",
                code="AI011",
            )
        if parts.username is not None or parts.password is not None:
            raise ExtractionRefused(
                "A URL with a user name or password is not fetched.", code="AI011"
            )
        host = parts.hostname or ""
        if not host:
            raise ExtractionRefused(f"{url!r} names no host.", code="AI011")
        if port is None:
            port = 443 if scheme == "https" else 80
        if port not in self.ports:
            allowed = ", ".join(str(p) for p in sorted(self.ports))
            raise ExtractionRefused(
                f"Port {port} is not fetched (KARNI_AI_FETCH_PORTS: {allowed}).", code="AI011"
            )
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        return Target(url=url, scheme=scheme, host=host, port=port, path=path)

    def allowed_address(self, address: str) -> bool:
        """Whether a connection may go to ``address``: a public unicast one only."""
        return public_address(address)

    def resolve(self, host: str, port: int) -> list[str]:
        """Every address ``host`` resolves to (an address literal resolves to itself)."""
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError) as exc:
            raise ExtractionRefused(f"{host} cannot be resolved: {exc}.", code="AI011") from exc
        return list(dict.fromkeys(str(info[4][0]) for info in infos))

    def address_for(self, target: Target) -> str:
        """The address to connect to, once every address of the host is allowed (else AI011)."""
        addresses = self.resolve(target.host, target.port)
        if not addresses:
            raise ExtractionRefused(f"{target.host} has no address.", code="AI011")
        refused = [address for address in addresses if not self.allowed_address(address)]
        if refused:
            raise ExtractionRefused(
                f"{target.host} resolves to {refused[0]}, which is not a public address. The "
                "server does not fetch from its own network.",
                code="AI011",
            )
        return addresses[0]

    # the request

    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html, text/plain;q=0.9, application/pdf;q=0.9, */*;q=0.1",
            "Accept-Encoding": "identity",
        }

    def open(self, target: Target, address: str, timeout: float) -> Any:
        """Send the request to ``address`` and return the ``http.client`` response."""
        connection: http.client.HTTPConnection
        if target.scheme == "https":
            connection = _PinnedHTTPSConnection(
                target.host,
                target.port,
                address=address,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        else:
            connection = _PinnedHTTPConnection(
                target.host, target.port, address=address, timeout=timeout
            )
        connection.request("GET", target.path, headers=self.headers())
        response = connection.getresponse()
        response.karni_connection = connection  # type: ignore[attr-defined]  # closed with it
        return response

    def fetch(self, url: str) -> Fetched:
        """Fetch ``url``, following checked redirects, within the size and time limits."""
        deadline = time.monotonic() + self.timeout
        current = url
        for _hop in range(self.max_redirects + 1):
            target = self.check_url(current)
            address = self.address_for(target)
            response = self._open(target, address, deadline)
            try:
                status = int(response.status)
                if status in _REDIRECTS:
                    location = response.getheader("Location")
                    if not location:
                        raise ExtractionRefused(
                            f"{target.url} redirects without a Location.", code="AI012"
                        )
                    current = urljoin(target.url, location)
                    continue
                if status >= 400:
                    raise ExtractionRefused(f"{target.url} answered HTTP {status}.", code="AI012")
                body = self._read(response, target, deadline)
                media_type, charset = _content_type(response.getheader("Content-Type") or "")
                return Fetched(url=target.url, content_type=media_type, charset=charset, body=body)
            finally:
                response.close()
                connection = getattr(response, "karni_connection", None)
                if connection is not None:
                    connection.close()
        raise ExtractionRefused(
            f"{url} redirects more than {self.max_redirects} times (KARNI_AI_FETCH_MAX_REDIRECTS).",
            code="AI011",
        )

    def _remaining(self, target: Target, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ExtractionRefused(
                f"{target.url} took longer than {self.timeout:g} seconds (KARNI_AI_FETCH_TIMEOUT).",
                code="AI012",
            )
        return remaining

    def _open(self, target: Target, address: str, deadline: float) -> Any:
        timeout = self._remaining(target, deadline)
        try:
            return self.open(target, address, timeout)
        except TimeoutError as exc:
            raise ExtractionRefused(
                f"{target.url} did not answer within {self.timeout:g} seconds "
                "(KARNI_AI_FETCH_TIMEOUT).",
                code="AI012",
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise ExtractionRefused(
                f"{target.url} could not be fetched: {exc}.", code="AI012"
            ) from exc

    def _read(self, response: Any, target: Target, deadline: float) -> bytes:
        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding not in ("", "identity"):
            raise ExtractionRefused(
                f"{target.url} sent a {encoding}-encoded body, and only identity is read.",
                code="AI012",
            )
        declared = response.getheader("Content-Length")
        if declared and declared.strip().isdigit() and int(declared) > self.max_bytes:
            raise ExtractionRefused(self._too_large(target), code="AI012")
        chunks: list[bytes] = []
        size = 0
        connection = getattr(response, "karni_connection", None)
        while True:
            remaining = self._remaining(target, deadline)
            if connection is not None and connection.sock is not None:
                connection.sock.settimeout(remaining)  # one deadline, not one per read
            try:
                chunk = response.read(_CHUNK)
            except TimeoutError as exc:
                raise ExtractionRefused(
                    f"{target.url} stopped sending within {self.timeout:g} seconds "
                    "(KARNI_AI_FETCH_TIMEOUT).",
                    code="AI012",
                ) from exc
            except (OSError, http.client.HTTPException) as exc:
                raise ExtractionRefused(
                    f"{target.url} could not be read: {exc}.", code="AI012"
                ) from exc
            if not chunk:
                return b"".join(chunks)
            size += len(chunk)
            if size > self.max_bytes:
                raise ExtractionRefused(self._too_large(target), code="AI012")
            chunks.append(chunk)

    def _too_large(self, target: Target) -> str:
        return (
            f"{target.url} is larger than {self.max_bytes} bytes (KARNI_AI_FETCH_MAX_BYTES). "
            "Download it and send the file, or paste its text."
        )


def _content_type(header: str) -> tuple[str, str | None]:
    media_type, _, rest = header.partition(";")
    charset = None
    for parameter in rest.split(";"):
        key, _, value = parameter.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip('"')
    return media_type.strip().lower(), charset
