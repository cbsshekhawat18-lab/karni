"""``python -m karni.deploy.healthcheck``: the probe a production container's health check runs.

A health check runs inside the container and asks ``http://127.0.0.1:8000/health/``.
In production that plain request fails twice over: Django answers 400 to a
``Host`` that is not in ``ALLOWED_HOSTS``, and the production profile
redirects every plain-http request to https (``SECURE_SSL_REDIRECT``). The
probe therefore sends the first real host in ``ALLOWED_HOSTS`` and
``X-Forwarded-Proto: https``, exactly what the proxy in front (Caddy) sends.
It never follows a redirect: only a 2xx answer is healthy (exit status 0).

    python -m karni.deploy.healthcheck                      # /health/ on port 8000
    python -m karni.deploy.healthcheck http://127.0.0.1:8000/health/ready/
    python -m karni.deploy.healthcheck --host example.com --timeout 3
    python -m karni.deploy.healthcheck --process beat      # a process, not a URL

``--process WORD`` is for a container with no HTTP port, such as Celery beat:
it is healthy when the container's main process (PID 1) has ``WORD`` in its
command line and the deploy gate (:mod:`karni.deploy.entrypoint`) has handed
over to it.

Override / escape hatch: ``--host`` or ``KARNI_HEALTHCHECK_HOST`` names the
host, and ``--header NAME=VALUE`` adds a header. Standard library only, and
no Django import, so the check costs a few milliseconds.
"""

from __future__ import annotations

import argparse
import http.client
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlsplit

__all__ = ["DEFAULT_URL", "main", "probe", "probe_host", "process_running"]

DEFAULT_URL = "http://127.0.0.1:8000/health/"
HOST_VARIABLE = "KARNI_HEALTHCHECK_HOST"


def probe_host(environ: Mapping[str, str]) -> str | None:
    """``KARNI_HEALTHCHECK_HOST``, else the first non-wildcard host in ``ALLOWED_HOSTS``."""
    explicit = environ.get(HOST_VARIABLE, "").strip()
    if explicit:
        return explicit
    for entry in environ.get("ALLOWED_HOSTS", "").split(","):
        host = entry.strip().lstrip(".")
        if host and host != "*":
            return host
    return None


def probe(
    url: str = DEFAULT_URL,
    *,
    host: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 5.0,
) -> tuple[bool, str]:
    """GET ``url`` as the proxy would: ``(healthy, what happened)``. Never raises."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False, f"not an http(s) URL: {url}"
    connection_class = (
        http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    )
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    sent = {"X-Forwarded-Proto": "https", "User-Agent": "karni-healthcheck"}
    if host:
        sent["Host"] = host
    sent.update(headers or {})
    connection = connection_class(parts.hostname, parts.port, timeout=timeout)
    try:
        connection.request("GET", path, headers=sent)
        response = connection.getresponse()
        response.read()
    except (OSError, http.client.HTTPException) as exc:
        return False, f"{url}: {exc or type(exc).__name__}"
    finally:
        connection.close()
    status = response.status
    detail = f"{url} answered {status}"
    if status in (301, 302, 307, 308):
        detail += f" (a redirect to {response.getheader('Location')})"
    if status == 400:
        detail += f" (is {host or 'the Host header'} in ALLOWED_HOSTS?)"
    return 200 <= status < 300, detail


def process_running(word: str, proc: Path = Path("/proc/1/cmdline")) -> tuple[bool, str]:
    """Whether PID 1 runs ``word`` and is past the deploy gate."""
    try:
        argv = [part.decode() for part in proc.read_bytes().split(b"\0") if part]
    except OSError as exc:
        return False, f"cannot read {proc}: {exc}"
    shown = " ".join(argv)
    if any("karni.deploy.entrypoint" in part for part in argv):
        return False, f"still in the deploy gate: {shown}"
    if word not in argv and not any(word in Path(part).name for part in argv):
        return False, f"PID 1 is not {word}: {shown}"
    return True, f"PID 1 is {shown}"


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m karni.deploy.healthcheck",
        description="Exit 0 when the URL answers 2xx (as the proxy would ask), else 1.",
    )
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help=f"default: {DEFAULT_URL}")
    parser.add_argument("--host", help=f"Host header (default: {HOST_VARIABLE}, ALLOWED_HOSTS)")
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds (default 5)")
    parser.add_argument(
        "--header", action="append", default=[], metavar="NAME=VALUE", help="an extra header"
    )
    parser.add_argument("--process", metavar="WORD", help="check PID 1 instead of a URL")
    parser.add_argument("--quiet", "-q", action="store_true", help="print nothing when healthy")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    if args.process:
        healthy, detail = process_running(args.process)
    else:
        extra = dict(item.split("=", 1) for item in args.header if "=" in item)
        host = args.host or probe_host(env)
        healthy, detail = probe(args.url, host=host, headers=extra, timeout=args.timeout)
    if not healthy or not args.quiet:
        print(("healthy: " if healthy else "unhealthy: ") + detail, file=sys.stderr)
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
