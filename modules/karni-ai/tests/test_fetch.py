"""URL safety: what the fetcher refuses, and a real fetch from a local server it is told to allow.

Refusals use a mocked DNS (``resolve``) and a mocked connection (``open``),
so no test leaves the machine. The last tests run a real HTTP server on
127.0.0.1, which only a subclass that allows loopback may reach: the default
fetcher refuses it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from django.test import override_settings

from karni_ai.exceptions import ExtractionRefused
from karni_ai.services.fetch import Fetcher, Target, public_address


class FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes = b"") -> None:
        self.status = status
        self._headers = {key.lower(): value for key, value in headers.items()}
        self._body = body
        self.closed = False

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self._headers.get(name.lower(), default)

    def read(self, size: int = -1) -> bytes:
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


class ScriptedFetcher(Fetcher):
    """DNS and HTTP answered from tables: ``dns[host]`` and ``pages[url]``."""

    dns: ClassVar[dict[str, list[str]]] = {}
    pages: ClassVar[dict[str, FakeResponse]] = {}
    opened: ClassVar[list[tuple[str, str]]] = []

    def resolve(self, host: str, port: int) -> list[str]:
        return self.dns.get(host) or super().resolve(host, port)

    def open(self, target: Target, address: str, timeout: float) -> Any:
        self.opened.append((target.url, address))
        return self.pages[target.url]


@pytest.fixture(autouse=True)
def _tables() -> Iterator[None]:
    ScriptedFetcher.dns = {"shop.example.com": ["93.184.215.14"]}
    ScriptedFetcher.pages = {}
    ScriptedFetcher.opened = []
    yield


def refused(url: str, fetcher: Fetcher | None = None) -> ExtractionRefused:
    with pytest.raises(ExtractionRefused) as exc:
        (fetcher or ScriptedFetcher()).fetch(url)
    return exc.value


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
    ],
)
def test_non_public_addresses(address: str) -> None:
    assert not public_address(address)


def test_public_addresses() -> None:
    assert public_address("93.184.215.14") and public_address("2606:4700:4700::1111")


@pytest.mark.parametrize(
    ("url", "fragment"),
    [
        ("file:///etc/passwd", "Only http and https"),
        ("ftp://shop.example.com/a", "Only http and https"),
        ("gopher://shop.example.com/", "Only http and https"),
        ("shop.example.com/page", "Only http and https"),
        ("https://user:secret@shop.example.com/", "user name or password"),
        ("https://shop.example.com:8443/", "Port 8443"),
        ("http://shop.example.com:99999/", "not a valid URL"),
        ("https:///path-only", "names no host"),
    ],
)
def test_refused_urls(url: str, fragment: str) -> None:
    error = refused(url)
    assert error.code == "AI011" and fragment in error.message
    assert ScriptedFetcher.opened == []


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://[::ffff:192.168.0.1]/",
    ],
)
def test_private_address_literals_are_refused(url: str) -> None:
    error = refused(url)
    assert error.code == "AI011" and "not a public address" in error.message
    assert ScriptedFetcher.opened == []


def test_a_name_that_resolves_to_a_private_address_is_refused() -> None:
    ScriptedFetcher.dns["intranet.example.com"] = ["10.0.0.7"]
    error = refused("https://intranet.example.com/")
    assert error.code == "AI011" and "10.0.0.7" in error.message
    assert ScriptedFetcher.opened == []


def test_one_private_answer_among_public_ones_is_refused() -> None:
    ScriptedFetcher.dns["mixed.example.com"] = ["93.184.215.14", "127.0.0.1"]
    assert refused("https://mixed.example.com/").code == "AI011"


def test_the_connection_goes_to_the_checked_address() -> None:
    ScriptedFetcher.pages["https://shop.example.com/a"] = FakeResponse(
        200, {"Content-Type": "text/html; charset=latin-1"}, b"<p>ok</p>"
    )
    fetched = ScriptedFetcher().fetch("https://shop.example.com/a")
    assert ScriptedFetcher.opened == [("https://shop.example.com/a", "93.184.215.14")]
    assert (fetched.content_type, fetched.charset, fetched.body) == (
        "text/html",
        "latin-1",
        b"<p>ok</p>",
    )


def test_a_redirect_to_a_private_address_is_refused() -> None:
    ScriptedFetcher.pages["https://shop.example.com/go"] = FakeResponse(
        302, {"Location": "http://169.254.169.254/latest/meta-data/"}
    )
    error = refused("https://shop.example.com/go")
    assert error.code == "AI011" and "not a public address" in error.message
    assert ScriptedFetcher.opened == [("https://shop.example.com/go", "93.184.215.14")]


def test_a_redirect_to_another_scheme_is_refused() -> None:
    ScriptedFetcher.pages["https://shop.example.com/go"] = FakeResponse(
        301, {"Location": "file:///etc/passwd"}
    )
    assert refused("https://shop.example.com/go").code == "AI011"


def test_a_relative_redirect_is_followed_and_checked() -> None:
    ScriptedFetcher.pages["https://shop.example.com/old"] = FakeResponse(308, {"Location": "/new"})
    ScriptedFetcher.pages["https://shop.example.com/new"] = FakeResponse(
        200, {"Content-Type": "text/plain"}, b"Name: Hose"
    )
    fetched = ScriptedFetcher().fetch("https://shop.example.com/old")
    assert fetched.url == "https://shop.example.com/new" and fetched.body == b"Name: Hose"


def test_too_many_redirects_are_refused() -> None:
    for n in range(5):
        ScriptedFetcher.pages[f"https://shop.example.com/{n}"] = FakeResponse(
            302, {"Location": f"/{n + 1}"}
        )
    with override_settings(KARNI_AI_FETCH_MAX_REDIRECTS=2):
        error = refused("https://shop.example.com/0")
    assert error.code == "AI011" and "more than 2 times" in error.message
    assert len(ScriptedFetcher.opened) == 3


def test_a_declared_size_over_the_limit_is_refused_before_reading() -> None:
    response = FakeResponse(200, {"Content-Length": "999999"}, b"x" * 10)
    ScriptedFetcher.pages["https://shop.example.com/big"] = response
    with override_settings(KARNI_AI_FETCH_MAX_BYTES=1000):
        error = refused("https://shop.example.com/big")
    assert error.code == "AI012" and "larger than 1000 bytes" in error.message
    assert response._body == b"x" * 10 and response.closed


def test_a_body_over_the_limit_is_refused_while_reading() -> None:
    ScriptedFetcher.pages["https://shop.example.com/big"] = FakeResponse(200, {}, b"x" * 5000)
    with override_settings(KARNI_AI_FETCH_MAX_BYTES=1000):
        assert refused("https://shop.example.com/big").code == "AI012"


def test_http_errors_and_compressed_bodies_are_refused() -> None:
    ScriptedFetcher.pages["https://shop.example.com/gone"] = FakeResponse(404, {})
    ScriptedFetcher.pages["https://shop.example.com/zip"] = FakeResponse(
        200, {"Content-Encoding": "gzip"}, b"\x1f\x8b"
    )
    assert "HTTP 404" in refused("https://shop.example.com/gone").message
    assert "gzip" in refused("https://shop.example.com/zip").message


def test_a_failed_connection_is_ai012() -> None:
    class Unreachable(ScriptedFetcher):
        def open(self, target: Target, address: str, timeout: float) -> Any:
            raise TimeoutError("timed out")

    error = refused("https://shop.example.com/slow", Unreachable())
    assert error.code == "AI012" and "did not answer within" in error.message


def test_an_unknown_host_is_ai011() -> None:
    class NoDns(Fetcher):
        def resolve(self, host: str, port: int) -> list[str]:
            raise ExtractionRefused(f"{host} cannot be resolved.", code="AI011")

    assert refused("https://nowhere.invalid/", NoDns()).code == "AI011"


# a real server on loopback


class _Pages(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the http.server API
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        if self.path == "/slow-drip":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            for _ in range(3):
                self.wfile.write(b"x" * 600)
                self.wfile.flush()
            return
        body = b"<html><body><p>Name: Hose</p><p>Price: 9.50</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _loopback(port: int) -> Fetcher:
    class Loopback(Fetcher):
        def allowed_address(self, address: str) -> bool:
            return address == "127.0.0.1"

    with override_settings(KARNI_AI_FETCH_PORTS=[port]):
        return Loopback()


def test_the_default_fetcher_refuses_the_local_server(server: str) -> None:
    port = int(server.rsplit(":", 1)[1])
    with override_settings(KARNI_AI_FETCH_PORTS=[port]):
        error = refused(f"{server}/page", Fetcher())
    assert error.code == "AI011" and "127.0.0.1" in error.message


def test_a_real_fetch_follows_a_redirect(server: str) -> None:
    fetched = _loopback(int(server.rsplit(":", 1)[1])).fetch(f"{server}/redirect")
    assert fetched.url == f"{server}/page" and fetched.content_type == "text/html"
    assert b"Name: Hose" in fetched.body


def test_a_real_fetch_stops_at_the_size_limit(server: str) -> None:
    fetcher = _loopback(int(server.rsplit(":", 1)[1]))
    fetcher.max_bytes = 1000
    with pytest.raises(ExtractionRefused) as exc:
        fetcher.fetch(f"{server}/slow-drip")
    assert exc.value.code == "AI012" and "larger than 1000 bytes" in exc.value.message
