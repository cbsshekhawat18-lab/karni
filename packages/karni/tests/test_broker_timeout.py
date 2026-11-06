"""A development worker stops even when Redis never answers its last BRPOP.

At a warm shutdown Celery closes the consuming channel, and kombu's Redis
channel reads the answer to its outstanding BRPOP first. A Redis whose timers
stalled never sends it, so without a socket timeout the worker waits for good.
The fake server below answers every command except BRPOP.

The test drives kombu the way a Celery worker does, through public API only:
a consumer on a channel, the connection registered with an event loop, one
tick of that loop to send the BRPOP, then ``close()``. It holds for the oldest
supported versions (redis-py 5 and kombu 5.3, RESP2) and the newest (redis-py 8,
which opens every connection with ``HELLO 3``, and kombu 5.7).
"""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import kombu
import pytest
from kombu import Connection, Consumer, Queue
from kombu.asynchronous import Hub
from kombu.common import ignore_errors

from karni.conf.dev import BROKER_SOCKET_TIMEOUT, DEV

#: kombu 5.3.2 and later read the answer to an outstanding BRPOP when a channel
#: closes, which is the wait the socket timeout bounds. kombu 5.3.0 and 5.3.1
#: (Celery 5.3's oldest) drop the connection without reading, so never wait.
READS_BRPOP_AT_CLOSE = tuple(kombu.VERSION[:3]) >= (5, 3, 2)


class _SilentOnBrpop(socketserver.BaseRequestHandler):
    """Speaks just enough RESP: nothing to BRPOP, +OK to most commands.

    ``HELLO`` gets the map redis-py 8 checks, ``PING`` gets +PONG, and ``SET``
    gets a null reply, so kombu's scan for unacknowledged messages finds its
    lock held by another worker and skips the scan.
    """

    server: _Server

    def handle(self) -> None:
        reader = self.request.makefile("rb")
        protocol = 2  # until the client says HELLO 3
        while True:
            header = reader.readline()
            if not header:
                return
            words = []
            for _ in range(int(header[1:])):
                size = int(reader.readline()[1:])
                words.append(reader.read(size + 2)[:-2])
            command = words[0].upper()
            if command == b"BRPOP":
                self.server.seen.brpop.set()
                continue
            if command == b"HELLO":
                protocol = int(words[1]) if len(words) > 1 else 2
                # A map in RESP3, a flat array in RESP2: {"proto": protocol}.
                kind = b"%1" if protocol == 3 else b"*2"
                self.request.sendall(kind + b"\r\n$5\r\nproto\r\n:%d\r\n" % protocol)
                continue
            null = b"_\r\n" if protocol == 3 else b"$-1\r\n"
            replies = {b"PING": b"+PONG\r\n", b"SET": null}
            self.request.sendall(replies.get(command, b"+OK\r\n"))


@dataclass
class _Seen:
    brpop: threading.Event = field(default_factory=threading.Event)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    seen: _Seen


@dataclass
class _Silent:
    port: int
    seen: _Seen


@pytest.fixture
def silent_redis() -> Iterator[_Silent]:
    server = _Server(("127.0.0.1", 0), _SilentOnBrpop)
    server.seen = _Seen()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield _Silent(port=server.server_address[1], seen=server.seen)
    server.shutdown()
    server.server_close()


def test_the_dev_profile_bounds_broker_reads() -> None:
    assert DEV["CELERY_BROKER_TRANSPORT_OPTIONS"] == {"socket_timeout": BROKER_SOCKET_TIMEOUT}


def test_a_dev_worker_channel_closes_when_brpop_gets_no_answer(silent_redis: _Silent) -> None:
    conn = Connection(
        f"redis://127.0.0.1:{silent_redis.port}/0",
        transport_options=DEV["CELERY_BROKER_TRANSPORT_OPTIONS"],
    )
    hub = Hub()
    try:
        # The worker's queue is declared already: the fake server stores nothing.
        queue = Queue("celery", no_declare=True)
        Consumer(conn.default_channel, queues=[queue], no_ack=True).consume()
        conn.register_with_event_loop(hub)
        # One tick of the worker's event loop sends a BRPOP and polls for its answer.
        hub.run_once()
        assert silent_redis.seen.brpop.wait(5), "the event loop sent no BRPOP"

        started = time.monotonic()
        # Celery's consumer closes its connection the same way at a warm shutdown.
        closer = threading.Thread(target=ignore_errors, args=(conn, conn.close), daemon=True)
        closer.start()
        closer.join(BROKER_SOCKET_TIMEOUT + 5)
        assert not closer.is_alive(), "closing the channel waited for an answer that never comes"
        if READS_BRPOP_AT_CLOSE:
            # The socket timeout ended the wait, not an error in the exchange.
            assert time.monotonic() - started >= BROKER_SOCKET_TIMEOUT - 1
    finally:
        hub.close()


def test_the_fake_server_answers_other_commands(silent_redis: _Silent) -> None:
    with socket.create_connection(("127.0.0.1", silent_redis.port), timeout=2) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        assert sock.recv(16) == b"+PONG\r\n"
        sock.sendall(b"*2\r\n$5\r\nHELLO\r\n$1\r\n3\r\n")
        assert sock.recv(64) == b"%1\r\n$5\r\nproto\r\n:3\r\n"


def test_the_fake_server_never_answers_brpop(silent_redis: _Silent) -> None:
    with socket.create_connection(("127.0.0.1", silent_redis.port), timeout=0.5) as sock:
        sock.sendall(b"*3\r\n$5\r\nBRPOP\r\n$6\r\ncelery\r\n$1\r\n1\r\n")
        assert silent_redis.seen.brpop.wait(2)
        with pytest.raises(TimeoutError):
            sock.recv(16)
