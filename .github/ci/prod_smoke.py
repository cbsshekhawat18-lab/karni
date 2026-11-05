"""The production stack, smoke-tested (CI's "Production stack (compose, smoke)" job).

Three steps, each a subcommand:

``env EXAMPLE``
    Prints ``.env.prod`` filled from ``.env.prod.example`` the way a person would:
    a random SECRET_KEY, admin path and database password, and ``--set`` values.
    It fails when the example has an empty value it does not know how to fill.
``wait``
    Waits until ``docker compose ps`` shows the release step exited 0 and every
    other service running and healthy, and prints the logs when one fails.
``check``
    The HTTP checks below.

``check``: smoke-test a running production stack over HTTP.

Waits for ``/readyz``, then checks ``/healthz``, a public page, the admin login
at its private path, the admin's old path answering 404, a static file, the
staff app and one of its scripts, a deep link into the staff app, the
plain-http redirect, and the security headers on each page. With ``--user`` it
also signs in through the API and reads a list endpoint (``--list-path``), at
``/api/<version>/`` too when ``--api-version`` names a version. Every check
prints one line, and the exit status is 1 when any failed.

In CI it talks to Caddy, verifying TLS with Caddy's local root certificate::

    python .github/ci/prod_smoke.py check --base-url https://localhost --cafile root.crt \
        --admin-path staff-1a2b3c4d/ --app-path /app/ --http-url http://localhost/

Signed in, against a stack seeded with ``manage.py karni_seed`` (its demo login), with the
built staff app served from another origin (a local ``vite preview``)::

    python .github/ci/prod_smoke.py check --base-url http://127.0.0.1:8611 \
        --admin-path admin/ --user demo@example.com --password karni-password \
        --list-path /api/products/ --app-url http://127.0.0.1:4173 --app-path / --no-static

Against gunicorn directly (no proxy), send what the proxy would::

    python .github/ci/prod_smoke.py check --base-url http://127.0.0.1:18080 \
        --header Host=example.com --header X-Forwarded-Proto=https --admin-path staff-1a2b/ \
        --no-static
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.message import Message

#: What every HTML page must carry, Django's or Caddy's.
PAGE_HEADERS = (
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "Permissions-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Cross-Origin-Opener-Policy",
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@dataclass
class Response:
    status: int
    headers: Message
    body: str


@dataclass
class Smoke:
    base: str
    headers: dict[str, str]
    context: ssl.SSLContext | None
    failures: list[str] = field(default_factory=list)
    headers_on: bool = True  # False: skip the security headers (--no-headers)

    def get(
        self, url: str, timeout: float = 15.0, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self.send("GET", url, timeout=timeout, headers=headers)

    def send(
        self,
        method: str,
        url: str,
        *,
        body: object = None,
        timeout: float = 15.0,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        full = url if "://" in url else self.base.rstrip("/") + url
        sent = {**self.headers, **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            sent["Content-Type"] = "application/json"
        request = urllib.request.Request(full, data=data, headers=sent, method=method)
        handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
        if self.context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self.context))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return Response(response.status, response.headers, body)
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.headers, exc.read().decode("utf-8", "replace"))

    def check(self, ok: bool, what: str, detail: str = "") -> bool:
        print(f"{'ok  ' if ok else 'FAIL'} {what}" + (f": {detail}" if detail else ""), flush=True)
        if not ok:
            self.failures.append(what)
        return ok

    def page_headers(self, what: str, response: Response) -> None:
        if not self.headers_on:
            return
        missing = [name for name in PAGE_HEADERS if not response.headers.get(name)]
        self.check(not missing, f"{what} security headers", f"missing {missing}" if missing else "")
        if response.headers.get("Content-Security-Policy-Report-Only"):
            self.check(False, f"{what} enforces its CSP", "it is report-only")
        nosniff = response.headers.get("X-Content-Type-Options", "")
        self.check(nosniff == "nosniff", f"{what} X-Content-Type-Options", nosniff)


def wait_ready(smoke: Smoke, seconds: float, path: str = "/readyz") -> Response | None:
    deadline = time.monotonic() + seconds
    last = "no answer"
    while time.monotonic() < deadline:
        try:
            response = smoke.get(path, timeout=5)
            if response.status == 200:
                return response
            last = f"{response.status} {response.body[:300]}"
        except (OSError, urllib.error.URLError) as exc:
            last = str(exc)
        time.sleep(2)
    smoke.check(False, f"{path} within {seconds:g}s", last)
    return None


def run(smoke: Smoke, args: argparse.Namespace) -> None:
    ready = wait_ready(smoke, args.wait, args.ready_path)
    if ready is None:
        return
    report_ready(smoke, args.ready_path, ready, args.expect_check)
    live = smoke.get("/healthz")
    smoke.check(live.status == 200, "/healthz answers", str(live.status))
    if args.worker_check:
        worker = smoke.get("/health/ready/")
        celery = json.loads(worker.body).get("checks", {}).get("celery", {})
        smoke.check(
            worker.status == 200 and celery.get("ok") is True,
            "a Celery worker answers /health/ready/",
            str(celery.get("detail", worker.status)),
        )
    if args.user:
        api_checks(smoke, args)

    home = smoke.get(args.public_path)
    title = re.search(r"<title>\s*([^<]+?)\s*</title>", home.body)
    smoke.check(
        home.status == 200 and bool(title), f"public page {args.public_path}", str(home.status)
    )
    smoke.page_headers(f"public page {args.public_path}", home)

    admin = f"/{args.admin_path.strip('/')}/"
    login = smoke.get(f"{admin}login/")
    smoke.check(
        login.status == 200 and "csrfmiddlewaretoken" in login.body,
        f"admin login at {admin}login/",
        str(login.status),
    )
    smoke.page_headers("admin login", login)
    if admin != "/admin/":
        old = smoke.get("/admin/login/")
        smoke.check(old.status == 404, "the admin is not at /admin/", str(old.status))
    static = re.search(r'(?:href|src)="(/static/[^"]+\.(?:css|js))"', login.body)
    if args.static and smoke.check(bool(static), "the admin login links a static file"):
        assert static is not None
        asset = smoke.get(static.group(1))
        smoke.check(asset.status == 200 and len(asset.body) > 0, f"static {static.group(1)}")

    if args.app_path:
        base = "/" + args.app_path.strip("/") + "/" if args.app_path.strip("/") else "/"
        app = smoke.get(args.app_url.rstrip("/") + base if args.app_url else base)
        smoke.check(
            app.status == 200 and 'id="root"' in app.body, f"staff app {base}", str(app.status)
        )
        smoke.page_headers(f"staff app {base}", app)
        script = re.search(r'<script[^>]+src="([^"]+\.js)"', app.body)
        if smoke.check(bool(script), "the staff app loads a script"):
            assert script is not None
            asset = smoke.get((args.app_url.rstrip("/") if args.app_url else "") + script.group(1))
            kind = asset.headers.get("Content-Type", "")
            smoke.check(
                asset.status == 200 and "javascript" in kind,
                f"staff app script {script.group(1)}",
                f"{asset.status} {kind}",
            )
        deep = smoke.get(
            (args.app_url.rstrip("/") if args.app_url else "") + f"{base}some/deep/link"
        )
        smoke.check(
            deep.status == 200 and 'id="root"' in deep.body,
            "a deep link into the staff app answers its index.html",
            str(deep.status),
        )
    if args.http_url:
        plain = Smoke(args.http_url, {}, None)
        redirect = plain.get(args.http_url)
        location = redirect.headers.get("Location", "")
        smoke.check(
            redirect.status in (301, 302, 307, 308) and location.startswith("https://"),
            f"{args.http_url} redirects to https",
            f"{redirect.status} {location}",
        )


def report_ready(smoke: Smoke, path: str, ready: Response, expected: list[str]) -> None:
    payload = json.loads(ready.body)
    checks = payload.get("checks", {})
    failed = [name for name, entry in checks.items() if not entry.get("ok")]
    smoke.check(
        payload.get("status") == "ok" and not failed and payload.get("failing") in ([], None),
        f"{path} reports every check ok",
        ", ".join(sorted(checks)),
    )
    for name in expected:
        smoke.check(name in checks, f"{path} runs the {name} check")


def api_checks(smoke: Smoke, args: argparse.Namespace) -> None:
    """Sign in through the API, then read the list endpoint, unversioned and per version."""
    login = smoke.send(
        "POST", args.login_path, body={"email": args.user, "password": args.password}
    )
    token = json.loads(login.body).get("access", "") if login.status == 200 else ""
    smoke.check(bool(token), f"sign in as {args.user}", str(login.status))
    if not token:
        return
    bearer = {"Authorization": f"Bearer {token}"}
    refused = smoke.get(args.list_path)
    smoke.check(
        refused.status in (401, 403), f"{args.list_path} refuses anonymous", str(refused.status)
    )
    paths = [args.list_path]
    if args.api_version:
        paths.append(args.list_path.replace("/api/", f"/api/{args.api_version}/", 1))
    for path in paths:
        listed = smoke.get(path, headers=bearer)
        rows = json.loads(listed.body).get("results") if listed.status == 200 else None
        smoke.check(
            isinstance(rows, list) and len(rows) >= args.min_rows,
            f"{path} lists at least {args.min_rows} row(s)",
            f"{listed.status} {len(rows) if isinstance(rows, list) else listed.body[:200]}",
        )


# env: .env.prod from the example


def _generated(name: str, values: Mapping[str, str]) -> str | None:
    if name == "SECRET_KEY":
        return secrets.token_urlsafe(50)
    if name == "KARNI_ADMIN_PATH":
        return f"staff-{secrets.token_hex(4)}/"
    if name == "POSTGRES_PASSWORD":
        return values.get("POSTGRES_PASSWORD") or secrets.token_hex(24)
    return None


def fill_env(example: str, overrides: Mapping[str, str]) -> str:
    """``example`` with every empty value generated, placeholders filled, ``overrides`` set."""
    values: dict[str, str] = {}
    lines = []
    for line in example.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if not match:
            lines.append(line)
            continue
        name, value = match.groups()
        if name in overrides:
            value = overrides[name]
        elif not value:
            generated = _generated(name, values)
            if generated is None:
                raise SystemExit(f"{name} is empty in the example and has no generated value")
            value = generated
        values[name] = value
        lines.append(f"{name}={value}")
    text = "\n".join(lines) + "\n"
    if "<POSTGRES_PASSWORD>" in text:
        text = text.replace("<POSTGRES_PASSWORD>", values["POSTGRES_PASSWORD"])
    for name, value in overrides.items():
        if name not in values:
            text += f"{name}={value}\n"
    return text


# wait: every service healthy


def compose_states(output: str) -> list[dict[str, object]]:
    """``docker compose ps --format json``: a JSON array (older) or one object per line."""
    output = output.strip()
    if not output:
        return []
    if output.startswith("["):
        loaded = json.loads(output)
        return [dict(item) for item in loaded]
    return [dict(json.loads(line)) for line in output.splitlines() if line.strip()]


def stack_state(states: list[dict[str, object]], one_shot: set[str]) -> tuple[str, str]:
    """``("ready" | "waiting" | "failed", detail)`` for the services in ``states``."""
    waiting = []
    for state in states:
        service = str(state.get("Service"))
        running = state.get("State")
        health = state.get("Health") or ""
        code = int(str(state.get("ExitCode") or 0))
        if service in one_shot:
            if running == "exited" and code != 0:
                return "failed", f"{service} exited {code}"
            if running != "exited":
                waiting.append(f"{service} {running}")
            continue
        if running in ("exited", "dead") or health == "unhealthy":
            return "failed", f"{service} is {running} {health}".strip()
        if running != "running" or health not in ("healthy", ""):
            waiting.append(f"{service} {running} {health}".strip())
        elif not health:
            return "failed", f"{service} has no health check"
    return ("waiting", ", ".join(waiting)) if waiting else ("ready", f"{len(states)} services")


def wait_stack(compose: list[str], one_shot: set[str], timeout: float) -> int:
    deadline = time.monotonic() + timeout
    detail = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [*compose, "ps", "-a", "--format", "json"], capture_output=True, text=True, check=False
        )
        status, detail = stack_state(compose_states(result.stdout), one_shot)
        print(f"{status}: {detail}", flush=True)
        if status == "ready":
            return 0
        if status == "failed":
            break
        time.sleep(5)
    subprocess.run([*compose, "ps", "-a"], check=False)
    subprocess.run([*compose, "logs", "--no-color", "--tail", "200"], check=False)
    print(f"the stack is not ready: {detail}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    env = commands.add_parser("env", help="print .env.prod filled from the example")
    env.add_argument("example")
    env.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    wait = commands.add_parser("wait", help="wait for every service to be healthy")
    wait.add_argument("--compose-file", default="docker-compose.prod.yml")
    wait.add_argument("--env-file", default=".env.prod")
    wait.add_argument("--one-shot", action="append", default=["release"])
    wait.add_argument("--timeout", type=float, default=300.0)
    check = commands.add_parser("check", help="the HTTP checks")
    check.add_argument("--base-url", required=True)
    check.add_argument("--admin-path", required=True, help="KARNI_ADMIN_PATH, e.g. staff-1a2b/")
    check.add_argument("--public-path", default="/", help="a public page (default /)")
    check.add_argument("--app-path", default="", help="where the staff app is, e.g. /app/")
    check.add_argument("--http-url", default="", help="a plain-http URL that must redirect")
    check.add_argument(
        "--ready-path", default="/readyz", help="the readiness URL (default /readyz)"
    )
    check.add_argument(
        "--worker-check",
        action="store_true",
        help="also require a Celery worker to answer /health/ready/",
    )
    check.add_argument("--app-url", default="", help="origin of the staff app, when not --base-url")
    check.add_argument("--user", default="", help="sign in as this email (needs --password)")
    check.add_argument("--password", default="")
    check.add_argument("--login-path", default="/api/auth/login/")
    check.add_argument(
        "--list-path", default="/api/users/", help="a list endpoint to read signed in"
    )
    check.add_argument("--api-version", default="", help="also read the list at /api/<version>/")
    check.add_argument(
        "--no-headers",
        dest="headers",
        action="store_false",
        help="skip the security headers (a development server sends the development ones)",
    )
    check.add_argument("--min-rows", type=int, default=1)
    check.add_argument("--cafile", help="the CA that signed the server's certificate")
    check.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    check.add_argument("--expect-check", action="append", default=[], metavar="NAME")
    check.add_argument("--wait", type=float, default=180.0, help="seconds to wait for ready")
    check.add_argument(
        "--no-static",
        dest="static",
        action="store_false",
        help="skip the static file (Django alone serves none in production; Caddy does)",
    )
    args = parser.parse_args(argv)
    if args.command == "env":
        overrides = dict(item.split("=", 1) for item in args.set)
        with open(args.example, encoding="utf-8") as handle:
            sys.stdout.write(fill_env(handle.read(), overrides))
        return 0
    if args.command == "wait":
        compose = ["docker", "compose", "-f", args.compose_file, "--env-file", args.env_file]
        return wait_stack(compose, set(args.one_shot), args.timeout)
    headers: Mapping[str, str] = dict(item.split("=", 1) for item in args.header)
    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    smoke = Smoke(args.base_url, {"User-Agent": "karni-prod-smoke", **headers}, context)
    smoke.headers_on = args.headers
    run(smoke, args)
    if smoke.failures:
        print(f"{len(smoke.failures)} check(s) failed: {', '.join(smoke.failures)}")
        return 1
    print("production smoke: every check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
