"""A development worker stops even when Redis never answers its last BRPOP.

At a warm shutdown Celery closes the consuming channel, and kombu's Redis
channel reads the answer to its outstanding BRPOP first. A Redis whose timers
stalled never sends it, so without a socket timeout the worker waits for good.
The fake server below answers every command except BRPOP.
"""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from collections.abc import Iterator

import pytest
from kombu import Connection
from kombu.common import ignore_errors

from karni.conf.dev import BROKER_SOCKET_TIMEOUT, DEV


class _SilentOnBrpop(socketserver.BaseRequestHandler):
    """Speaks just enough RESP: +PONG to PING, nothing to BRPOP, +OK to the rest."""

    def handle(self) -> None:
        reader = self.request.makefile("rb")
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
                continue
            self.request.sendall(b"+PONG\r\n" if command == b"PING" else b"+OK\r\n")


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture
def silent_redis() -> Iterator[int]:
    server = _Server(("127.0.0.1", 0), _SilentOnBrpop)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_the_dev_profile_bounds_broker_reads() -> None:
    assert DEV["CELERY_BROKER_TRANSPORT_OPTIONS"] == {"socket_timeout": BROKER_SOCKET_TIMEOUT}


def test_a_dev_worker_channel_closes_when_brpop_gets_no_answer(silent_redis: int) -> None:
    conn = Connection(
        f"redis://127.0.0.1:{silent_redis}/0",
        transport_options=DEV["CELERY_BROKER_TRANSPORT_OPTIONS"],
    )
    channel = conn.default_channel
    channel._active_queues.append("celery")
    channel._update_queue_cycle()
    # What the worker's event loop does before each poll: send a BRPOP.
    conn.transport.cycle._register_BRPOP(channel)
    assert channel._in_poll

    started = time.monotonic()
    # Celery's consumer closes its connection the same way at a warm shutdown.
    closer = threading.Thread(target=ignore_errors, args=(conn, conn.close), daemon=True)
    closer.start()
    closer.join(BROKER_SOCKET_TIMEOUT + 5)
    assert not closer.is_alive(), "closing the channel waited for an answer that never comes"
    assert time.monotonic() - started >= BROKER_SOCKET_TIMEOUT - 1


def test_the_fake_server_answers_other_commands(silent_redis: int) -> None:
    with socket.create_connection(("127.0.0.1", silent_redis), timeout=2) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        assert sock.recv(16) == b"+PONG\r\n"
