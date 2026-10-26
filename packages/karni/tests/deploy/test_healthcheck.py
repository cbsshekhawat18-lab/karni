"""The container health probe asks /health/ the way the proxy in front does."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from karni.deploy import healthcheck


class _Recorder(BaseHTTPRequestHandler):
    seen: list[dict[str, str]] = []
    status = 200

    def do_GET(self) -> None:  # noqa: N802 - the http.server hook name
        type(self).seen.append({k.lower(): v for k, v in self.headers.items()})
        self.send_response(type(self).status)
        if type(self).status == 301:
            self.send_header("Location", "https://example.com/health/")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def server() -> Iterator[str]:
    _Recorder.seen = []
    _Recorder.status = 200
    httpd = HTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/health/"
    httpd.shutdown()
    httpd.server_close()


def test_the_probe_sends_an_allowed_host_and_https(server: str) -> None:
    status = healthcheck.main([server, "-q"], environ={"ALLOWED_HOSTS": "*,.example.com,b.org"})
    assert status == 0
    assert _Recorder.seen[0]["host"] == "example.com"
    assert _Recorder.seen[0]["x-forwarded-proto"] == "https"


def test_a_redirect_is_unhealthy_and_named(server: str) -> None:
    _Recorder.status = 301
    healthy, detail = healthcheck.probe(server, host="example.com")
    assert not healthy
    assert "redirect to https://example.com/health/" in detail


def test_a_bad_host_points_at_allowed_hosts(server: str) -> None:
    _Recorder.status = 400
    healthy, detail = healthcheck.probe(server, host="wrong.example")
    assert not healthy and "ALLOWED_HOSTS" in detail


def test_nothing_listening_is_unhealthy_not_a_crash() -> None:
    healthy, detail = healthcheck.probe("http://127.0.0.1:9/health/", timeout=1)
    assert not healthy and detail


def test_the_host_comes_from_the_override_first() -> None:
    env = {"KARNI_HEALTHCHECK_HOST": "probe.example", "ALLOWED_HOSTS": "example.com"}
    assert healthcheck.probe_host(env) == "probe.example"
    assert healthcheck.probe_host({"ALLOWED_HOSTS": "*"}) is None


def test_the_process_check_waits_for_the_gate_to_hand_over(tmp_path: Path) -> None:
    cmdline = tmp_path / "cmdline"
    cmdline.write_bytes(b"python\0-m\0karni.deploy.entrypoint\0celery\0-A\0config\0beat\0")
    assert not healthcheck.process_running("beat", cmdline)[0]
    cmdline.write_bytes(b"/venv/bin/python\0/venv/bin/celery\0-A\0config\0beat\0")
    assert healthcheck.process_running("beat", cmdline)[0]
    assert not healthcheck.process_running("worker", cmdline)[0]
    assert not healthcheck.process_running("beat", tmp_path / "missing")[0]
