"""The PostgreSQL and Redis a project's host run can use, for ``karni doctor``.

Quick and with no new dependency: a TCP connect with a short timeout, then one
protocol exchange, so a port that answers is known to be PostgreSQL or Redis.
PostgreSQL gets an SSLRequest and answers one byte (``S`` or ``N``) without
logging anything when the client then leaves. Redis gets ``PING``. Nothing is
read from a database, written or listed.

Local services are looked for on 127.0.0.1 at the default ports (5432, 6379)
and at the port ``DATABASE_URL`` / ``REDIS_URL`` names. When ``.env`` still
points at the docker compose host names (``db``, ``redis``) and they do not
resolve here, :func:`env_lines` gives the lines that use the local services
instead.

Override / escape hatch: :data:`DEFAULT_PORTS` and :data:`TIMEOUT` are module
attributes, and doctor only reports: it never edits ``.env``.
"""

from __future__ import annotations

import getpass
import re
import socket
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

__all__ = [
    "COMPOSE_HOSTS",
    "DEFAULT_PORTS",
    "Endpoint",
    "database_name",
    "env_lines",
    "find_local",
    "parse",
    "resolves",
    "speaks",
]

Kind = Literal["postgres", "redis"]

#: Where each service listens unless told otherwise.
DEFAULT_PORTS: dict[Kind, int] = {"postgres": 5432, "redis": 6379}
#: The scaffold's docker compose service name for each: they resolve only inside the stack.
COMPOSE_HOSTS: dict[Kind, str] = {"postgres": "db", "redis": "redis"}
#: Seconds for each connect, and for each answer.
TIMEOUT = 0.5
#: Seconds a host name lookup may take before it counts as not resolving.
RESOLVE_TIMEOUT = 2.0

_SSL_REQUEST = struct.pack("!ii", 8, 80877103)
_SCHEMES: dict[Kind, tuple[str, ...]] = {
    "postgres": ("postgres", "postgresql", "pgsql", "postgis"),
    "redis": ("redis", "rediss"),
}


@dataclass(frozen=True)
class Endpoint:
    """One service URL, read apart."""

    kind: Kind
    host: str
    port: int
    user: str
    path: str


def parse(kind: Kind, url: str) -> Endpoint | None:
    """The host, port, user and path of ``url``, or ``None`` when it is not a ``kind`` URL."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.split("+")[0] not in _SCHEMES[kind] or not parts.hostname:
        return None
    return Endpoint(
        kind=kind,
        host=parts.hostname,
        port=port or DEFAULT_PORTS[kind],
        user=parts.username or "",
        path=parts.path,
    )


def resolves(host: str, timeout: float = RESOLVE_TIMEOUT) -> bool:
    """Whether ``host`` resolves here, giving up after ``timeout`` seconds."""
    answer: list[bool] = []

    def lookup() -> None:
        try:
            socket.getaddrinfo(host, None)
        except (OSError, UnicodeError):
            answer.append(False)
        else:
            answer.append(True)

    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    worker.join(timeout)
    return bool(answer and answer[0])


def speaks(kind: Kind, host: str, port: int, timeout: float | None = None) -> bool | None:
    """``True`` when ``kind`` answers on ``host:port``, ``False`` for another service, ``None`` for nothing."""
    wait = TIMEOUT if timeout is None else timeout
    try:
        with socket.create_connection((host, port), timeout=wait) as conn:
            conn.settimeout(wait)
            try:
                if kind == "postgres":
                    conn.sendall(_SSL_REQUEST)
                    return conn.recv(1) in (b"S", b"N")
                conn.sendall(b"PING\r\n")
                reply = conn.recv(64)
            except OSError:
                return False
    except OSError:
        return None
    return reply.startswith((b"+PONG", b"-NOAUTH", b"-DENIED", b"-ERR"))


def find_local(kind: Kind, configured_port: int | None = None) -> int | None:
    """The first port on 127.0.0.1 where ``kind`` answers: the default, then ``configured_port``."""
    ports = [DEFAULT_PORTS[kind]]
    if configured_port is not None and configured_port not in ports:
        ports.append(configured_port)
    for port in ports:
        if speaks(kind, "127.0.0.1", port):
            return port
    return None


def database_name(project: Path, project_name: str | None) -> str:
    """The database to create for ``project``: ``PROJECT_NAME``, else its folder, as a SQL name."""
    raw = (project_name or project.name).strip().lower()
    name = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_") or "karni"
    return name if not name[0].isdigit() else f"db_{name}"


def env_lines(kind: Kind, port: int, *, database: str, configured: Endpoint | None) -> list[str]:
    """The ``.env`` line (and, for PostgreSQL, the ``createdb`` command) for a local service."""
    if kind == "postgres":
        user = getpass.getuser()
        where = "" if port == DEFAULT_PORTS["postgres"] else f" -h 127.0.0.1 -p {port}"
        return [
            f"DATABASE_URL=postgres://{user}@127.0.0.1:{port}/{database}",
            f"createdb{where} {database}",
        ]
    number = (
        configured.path if configured is not None and configured.path not in ("", "/") else "/0"
    )
    return [f"REDIS_URL=redis://127.0.0.1:{port}{number}"]
