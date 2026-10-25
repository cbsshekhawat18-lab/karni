"""``karni doctor``'s local PostgreSQL and Redis: probes and the .env lines it prints.

Fake servers on loopback ports stand in for PostgreSQL and Redis, so the
tests never touch a service running on this machine.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from karni_cli import project as project_mod
from karni_cli import services
from karni_cli.main import app


def _server(reply: bytes, *, read: int) -> tuple[socketserver.ThreadingTCPServer, int]:
    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            self.request.recv(read)
            self.request.sendall(reply)

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


@pytest.fixture
def fakes() -> Iterator[dict[str, int]]:
    """Ports of a fake PostgreSQL (answers SSLRequest with N), Redis and an HTTP server."""
    started = {
        "postgres": _server(b"N", read=8),
        "redis": _server(b"+PONG\r\n", read=6),
        "http": _server(b"HTTP/1.1 400 Bad Request\r\n\r\n", read=6),
    }
    yield {name: port for name, (_, port) in started.items()}
    for server, _ in started.values():
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# the probes


def test_each_service_is_told_apart(fakes: dict[str, int]) -> None:
    assert services.speaks("postgres", "127.0.0.1", fakes["postgres"]) is True
    assert services.speaks("redis", "127.0.0.1", fakes["redis"]) is True
    assert services.speaks("postgres", "127.0.0.1", fakes["http"]) is False
    assert services.speaks("redis", "127.0.0.1", fakes["http"]) is False
    assert services.speaks("redis", "127.0.0.1", _closed_port()) is None


def test_find_local_tries_the_default_port_then_the_configured_one(
    fakes: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", _closed_port())
    assert services.find_local("postgres") is None
    assert services.find_local("postgres", fakes["postgres"]) == fakes["postgres"]
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", fakes["postgres"])
    assert services.find_local("postgres") == fakes["postgres"]


def test_parse_and_names() -> None:
    endpoint = services.parse("postgres", "postgres://karni:karni@db/karni")
    assert endpoint == services.Endpoint("postgres", "db", 5432, "karni", "/karni")
    assert services.parse("redis", "postgres://x@y/z") is None
    assert services.parse("postgres", "sqlite:///db.sqlite3") is None
    assert services.resolves("localhost") is True
    assert services.resolves("no-such-host.invalid") is False
    assert services.database_name(Path("/x/ticket_shop"), None) == "ticket_shop"
    assert services.database_name(Path("/x/y"), "Ticket-Shop") == "ticket_shop"
    assert services.database_name(Path("/x/y"), "2024 app") == "db_2024_app"


def test_env_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services.getpass, "getuser", lambda: "ada")
    assert services.env_lines("postgres", 5432, database="shop", configured=None) == [
        "DATABASE_URL=postgres://ada@127.0.0.1:5432/shop",
        "createdb shop",
    ]
    assert services.env_lines("postgres", 55432, database="shop", configured=None)[1] == (
        "createdb -h 127.0.0.1 -p 55432 shop"
    )
    redis = services.parse("redis", "redis://redis:6379/3")
    assert services.env_lines("redis", 6379, database="shop", configured=redis) == [
        "REDIS_URL=redis://127.0.0.1:6379/3"
    ]


# karni doctor


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A host project (commands run on this machine) whose compose names never resolve."""
    root = tmp_path / "ticket_shop"
    root.mkdir()
    (root / "manage.py").write_text("")
    monkeypatch.chdir(root)
    for name in ("DATABASE_URL", "REDIS_URL", "PROJECT_NAME", "KARNI_DOTENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(project_mod, "venv_python", lambda p: Path("/venv/bin/python"))
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: False)
    monkeypatch.setattr(
        services, "resolves", lambda host, timeout=0: host != "db" and host != "redis"
    )
    monkeypatch.setattr(services.getpass, "getuser", lambda: "ada")
    real = services.speaks

    def speaks(
        kind: services.Kind, host: str, port: int, timeout: float | None = None
    ) -> bool | None:
        # Never reach a PostgreSQL or Redis this machine runs on the standard ports.
        return None if port in (5432, 6379) else real(kind, host, port, timeout)

    monkeypatch.setattr(services, "speaks", speaks)
    return root


def _doctor(runner: CliRunner) -> dict[str, list[str]]:
    """Doctor's database and redis lines, by label."""
    result = runner.invoke(app, ["doctor", "-q"])
    assert result.exit_code == 0, result.output
    lines: dict[str, list[str]] = {}
    label = ""
    for line in result.stdout.splitlines():
        if line[:1].strip():
            label = line.split()[0]
        lines.setdefault(label, []).append(line[12:])
    return lines


COMPOSE_ENV = (
    "PROJECT_NAME=ticket_shop\n"
    "DATABASE_URL=postgres://karni:karni@db:5432/karni\n"
    "REDIS_URL=redis://redis:6379/0\n"
)


def test_compose_hosts_with_local_services_print_the_env_lines(
    runner: CliRunner, project: Path, fakes: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", fakes["postgres"])
    monkeypatch.setitem(services.DEFAULT_PORTS, "redis", fakes["redis"])
    (project / ".env").write_text(COMPOSE_ENV)
    lines = _doctor(runner)
    pg, redis = fakes["postgres"], fakes["redis"]
    assert lines["database"] == [
        (
            "DATABASE_URL (.env) postgres://karni:***@db:5432/karni: db does not resolve here: "
            "it is the docker compose service, reachable only inside the stack"
        ),
        f"PostgreSQL answers on 127.0.0.1:{pg}. To use it, put this line in .env:",
        f"  DATABASE_URL=postgres://ada@127.0.0.1:{pg}/ticket_shop",
        "and create the database once: createdb ticket_shop",
    ]
    assert lines["redis"] == [
        (
            "REDIS_URL (.env) redis://redis:6379/0: redis does not resolve here: it is the "
            "docker compose service, reachable only inside the stack"
        ),
        f"Redis answers on 127.0.0.1:{redis}. To use it, put this line in .env:",
        f"  REDIS_URL=redis://127.0.0.1:{redis}/0",
    ]


def test_without_local_services_doctor_says_how_to_start_them(
    runner: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pg, redis = _closed_port(), _closed_port()
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", pg)
    monkeypatch.setitem(services.DEFAULT_PORTS, "redis", redis)
    lines = _doctor(runner)  # no .env: Karni's defaults name the compose hosts
    assert lines["database"][0].startswith("DATABASE_URL (default) postgres://karni:***@db")
    assert lines["database"][1].startswith(
        f"No PostgreSQL answers on 127.0.0.1:{pg}. Start one with `brew services start "
        "postgresql@16` on macOS"
    )
    assert "docker compose up -d --wait db" in lines["database"][1]
    assert lines["redis"][1].startswith(f"No Redis answers on 127.0.0.1:{redis}.")
    assert "KARNI_CACHE=locmem" in lines["redis"][1]


def test_services_that_answer_are_reported_as_such(
    runner: CliRunner, project: Path, fakes: dict[str, int]
) -> None:
    (project / ".env").write_text(
        f"DATABASE_URL=postgres://ada@127.0.0.1:{fakes['postgres']}/shop\n"
        f"REDIS_URL=redis://127.0.0.1:{fakes['redis']}/0\n"
    )
    lines = _doctor(runner)
    assert lines["database"] == [
        f"DATABASE_URL (.env) postgres://ada@127.0.0.1:{fakes['postgres']}/shop: PostgreSQL answers"
    ]
    assert lines["redis"] == [
        f"REDIS_URL (.env) redis://127.0.0.1:{fakes['redis']}/0: Redis answers"
    ]


def test_a_local_service_on_the_configured_port_is_found(
    runner: CliRunner, project: Path, fakes: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", _closed_port())
    pg = fakes["postgres"]
    (project / ".env").write_text(f"DATABASE_URL=postgres://karni:karni@db:{pg}/karni\n")
    database = _doctor(runner)["database"]
    assert f"  DATABASE_URL=postgres://ada@127.0.0.1:{pg}/ticket_shop" in database
    assert f"and create the database once: createdb -h 127.0.0.1 -p {pg} ticket_shop" in database


def test_a_stopped_server_at_a_resolving_host(
    runner: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(services.DEFAULT_PORTS, "postgres", _closed_port())
    port = _closed_port()
    (project / ".env").write_text(f"DATABASE_URL=postgres://ada@127.0.0.1:{port}/shop\n")
    database = _doctor(runner)["database"]
    assert database[0].endswith(f": nothing answers at 127.0.0.1:{port}")
    assert database[1].startswith("No PostgreSQL answers")


def test_sqlite_and_the_compose_stack_are_not_probed(
    runner: CliRunner, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_probe(*args: object, **kwargs: object) -> bool:
        raise AssertionError("probed")

    monkeypatch.setattr(services, "speaks", no_probe)
    (project / ".env").write_text(
        "DATABASE_URL=sqlite:///db.sqlite3\nREDIS_URL=redis://redis:6379/0\n"
    )
    monkeypatch.setattr(project_mod, "venv_python", lambda p: None)
    monkeypatch.setattr(project_mod, "compose_service_running", lambda *a: True)
    lines = _doctor(runner)
    assert lines["database"] == ["DATABASE_URL (.env) sqlite:///db.sqlite3: SQLite, no server"]
    assert lines["redis"] == [
        (
            "REDIS_URL (.env) redis://redis:6379/0: the docker compose service (project "
            "commands run in the stack)"
        )
    ]
