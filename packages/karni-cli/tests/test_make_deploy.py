"""``karni make deploy compose`` and the production stack every new project gets.

Docker is not needed: the files are parsed and checked for what the stack
relies on (services, health checks, volumes, dependencies, the variables
.env.prod must define, the Dockerfile targets, the Caddyfile's paths). The CI
job "Production stack (compose, smoke)" boots the same files for real; its
definition and helpers are checked at the end.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from karni_cli.generators import deploy
from karni_cli.main import app

from .conftest import REPO_ROOT, TEMPLATE

ALL = {"release", "django", "worker", "beat", "caddy", "db", "redis", "backup"}
APP_SERVICES = {"release", "django", "worker", "beat"}
GATE = ["python", "-m", "karni.deploy.entrypoint"]


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(app, ["new", "Clinic Hours", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    root = tmp_path / "clinic_hours"
    monkeypatch.chdir(root)
    return root


def make(*args: str) -> Result:
    return CliRunner().invoke(app, ["make", "deploy", *args])


def load(project: Path) -> dict[str, Any]:
    data = yaml.safe_load((project / deploy.COMPOSE_FILE).read_text())
    assert isinstance(data, dict)
    return data


def check_stack(project: Path) -> dict[str, Any]:
    """Everything docker-compose.prod.yml relies on, checked without Docker."""
    data = load(project)
    services: dict[str, dict[str, Any]] = data["services"]
    named = set(data.get("volumes") or {})
    env_example = (project / deploy.ENV_EXAMPLE).read_text()
    targets = deploy.dockerfile_targets((project / "Dockerfile").read_text())
    for name, service in services.items():
        if name == "release":
            assert service["restart"] == "no"
        else:
            assert service["restart"] == "unless-stopped", name
            assert service["healthcheck"]["test"], f"{name} has no health check"
        assert service.get("logging", {}).get("driver") == "json-file", name
        assert service["deploy"]["resources"]["limits"]["memory"], name
        for mount in service.get("volumes", []):
            assert isinstance(mount, str), f"{name}: {mount!r} (long syntax could bind)"
            source = mount.split(":", 1)[0]
            assert source in named, f"{name} mounts {source}, not a named volume"
        for dependency in service.get("depends_on", {}):
            assert dependency in services, f"{name} depends on a missing {dependency}"
        if "build" in service:
            assert service["build"]["target"] in targets, name
        if name in APP_SERVICES:
            assert service["entrypoint"] == GATE, name
            assert service["env_file"] == deploy.ENV_FILE
            assert service["build"]["target"] == "prod"
            assert "app_data:/data" in service["volumes"]
            if name != "release":
                assert service["depends_on"]["release"] == {
                    "condition": "service_completed_successfully"
                }
    for name in ("db", "redis"):
        if name in services:
            assert "ports" not in services[name], f"{name} must not be published"
    text = (project / deploy.COMPOSE_FILE).read_text()
    for variable in set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", text)):
        assert re.search(rf"^#? ?{variable}=", env_example, re.MULTILINE), (
            f"{variable} is used by {deploy.COMPOSE_FILE} but not in {deploy.ENV_EXAMPLE}"
        )
    caddy = services["caddy"]
    assert f"app_data:{deploy.VOLUME}:ro" in caddy["volumes"]
    caddyfile = (project / deploy.CADDYFILE).read_text()
    assert caddyfile.count("{") == caddyfile.count("}")
    for placeholder in set(re.findall(r"\{\$([A-Z_]+)", caddyfile)):
        assert placeholder in caddy["environment"], f"caddy needs {placeholder}"
    # The release step publishes into /data/web, which caddy sees at /srv/data/web.
    release = " ".join(services["release"]["command"])
    assert "karni_publish_web --root /data/web" in release
    assert f"--config {deploy.WEB_ROOT}/Caddyfile" in " ".join(caddy["command"])
    from karni.deploy.web import HEADERS_FILE

    assert f"import {deploy.WEB_ROOT}/{HEADERS_FILE}" in caddyfile
    return services


# karni new


def test_a_new_project_gets_the_production_stack(project: Path) -> None:
    services = check_stack(project)
    assert set(services) == ALL
    data = load(project)
    assert set(data["volumes"]) == {
        "postgres_data",
        "redis_data",
        "app_data",
        "caddy_data",
        "caddy_config",
        "backups",
    }
    django = services["django"]
    assert "uvicorn_worker.UvicornWorker" in django["command"]
    assert django["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-m",
        "karni.deploy.healthcheck",
        "http://127.0.0.1:8000/readyz",
        "--quiet",
    ]
    assert services["backup"]["build"]["target"] == "backup"
    assert services["backup"]["volumes"] == ["app_data:/data", "backups:/backups"]
    assert data["x-app"]["build"]["args"]["KARNI_APP_PATH"] == "/app/"
    caddyfile = (project / "Caddyfile").read_text()
    assert "handle /app/* {" in caddyfile and "try_files {path} /app/index.html" in caddyfile
    env = (project / ".env.prod.example").read_text()
    for line in (
        "DJANGO_ENV=prod",
        "SECRET_KEY=",
        "KARNI_ADMIN_PATH=",
        "ALLOWED_HOSTS=example.com",
        "CSRF_TRUSTED_ORIGINS=https://example.com",
        "KARNI_FRONTEND_URL=https://example.com/app",
        "KARNI_AUTH_MODE=jwt",
    ):
        assert f"\n{line}\n" in env, line
    assert "DEBUG" not in re.sub(r"^#.*$", "", env, flags=re.MULTILINE)
    # Email and phone numbers: commented, with the format of each value.
    for line in (
        "# KARNI_PHONE_COUNTRY_CODE=44",
        "# EMAIL_URL=smtp+tls://user:password@smtp.example.com:587",
        "# DEFAULT_FROM_EMAIL=noreply@example.com",
        "# SERVER_EMAIL=server@example.com",
    ):
        assert f"\n{line}\n" in env, line
    assert '"44" for the UK (not "GB")' in env and "(karni.W520)" in env
    assert ".env.prod" in (project / ".gitignore").read_text().split()
    assert ".env.prod" in (project / ".dockerignore").read_text().split()


def test_the_scaffold_builds_every_image_the_stack_runs() -> None:
    dockerfile = (TEMPLATE / "{{cookiecutter.project_slug}}" / "Dockerfile").read_text()
    assert deploy.dockerfile_targets(dockerfile) >= {"deps", "dev", "staff-app", "prod", "backup"}
    prod = dockerfile.split("AS prod", 1)[1].split("\nFROM ", 1)[0]
    assert 'ENTRYPOINT ["python", "-m", "karni.deploy.entrypoint"]' in prod
    assert "USER app" in prod and "/app/frontend/dist" in prod
    assert "FROM postgres:${POSTGRES_VERSION}-alpine AS backup" in dockerfile
    assert 'npm run build -- --base="${KARNI_APP_PATH}"' in dockerfile
    routes = TEMPLATE / "{{cookiecutter.project_slug}}" / "frontend" / "src" / "routes.tsx"
    assert "basepath: import.meta.env.BASE_URL" in routes.read_text()
    assert not (TEMPLATE / "{{cookiecutter.project_slug}}" / "Caddyfile").exists()


def test_the_domain_comes_from_karni_new(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
    result = CliRunner().invoke(
        app, ["new", "Shop", "--domain", "shop.example.net", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    env = (tmp_path / "shop" / ".env.prod.example").read_text()
    assert "\nDOMAIN=shop.example.net\n" in env
    assert "\nKARNI_FRONTEND_URL=https://shop.example.net/app\n" in env


# the flags


def test_without_celery(project: Path) -> None:
    result = make("compose", "--force", "--no-celery")
    assert result.exit_code == 0, result.output
    services = check_stack(project)
    assert set(services) == ALL - {"worker", "beat"}
    env = (project / deploy.ENV_EXAMPLE).read_text()
    assert (
        "\nKARNI_HEALTH_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache\n"
        in env
    )


def test_managed_database_and_redis_without_backups(project: Path) -> None:
    result = make("compose", "--force", "--no-db", "--no-redis", "--no-backups")
    assert result.exit_code == 0, result.output
    services = check_stack(project)
    assert set(services) == ALL - {"db", "redis", "backup"}
    assert set(load(project)["volumes"]) == {"app_data", "caddy_data", "caddy_config"}
    assert "release" not in (services["release"].get("depends_on") or {})
    env = (project / deploy.ENV_EXAMPLE).read_text()
    assert "\nDATABASE_URL=\n" in env and "\nREDIS_URL=\n" in env
    assert "POSTGRES_PASSWORD" not in env


def test_the_staff_app_at_the_root(project: Path) -> None:
    result = make("compose", "--force", "--app-path", "/")
    assert result.exit_code == 0, result.output
    services = check_stack(project)
    assert "KARNI_ADMIN_PATH" in services["caddy"]["environment"]
    caddyfile = (project / "Caddyfile").read_text()
    assert "@django path /api/* /health/* /healthz /readyz /{$KARNI_ADMIN_PATH}*" in caddyfile
    assert f"root * {deploy.WEB_ROOT}/app" in caddyfile
    assert load(project)["x-app"]["build"]["args"]["KARNI_APP_PATH"] == "/"


def test_the_staff_app_on_its_own_host(project: Path) -> None:
    result = make("compose", "--force", "--app-domain", "app.example.com")
    assert result.exit_code == 0, result.output
    services = check_stack(project)
    assert "APP_DOMAIN" in services["caddy"]["environment"]
    assert "{$APP_DOMAIN} {" in (project / "Caddyfile").read_text()
    env = (project / deploy.ENV_EXAMPLE).read_text()
    assert "\nALLOWED_HOSTS=example.com,app.example.com\n" in env
    assert "\nCSRF_TRUSTED_ORIGINS=https://example.com,https://app.example.com\n" in env
    assert "\nKARNI_FRONTEND_URL=https://app.example.com\n" in env


def test_no_staff_app(project: Path) -> None:
    result = make("compose", "--force", "--no-app", "--app-path", "/staff/")
    assert result.exit_code == 0, result.output
    services = check_stack(project)
    assert '--app ""' in " ".join(services["release"]["command"])
    assert "try_files" not in (project / "Caddyfile").read_text()
    assert "KARNI_FRONTEND_URL" not in (project / deploy.ENV_EXAMPLE).read_text()


def test_another_path_for_the_staff_app(project: Path) -> None:
    result = make("compose", "--force", "--app-path", "staff")
    assert result.exit_code == 0, result.output
    check_stack(project)
    caddyfile = (project / "Caddyfile").read_text()
    assert "redir /staff /staff/ 308" in caddyfile and "handle /staff/* {" in caddyfile
    assert load(project)["x-app"]["build"]["args"]["KARNI_APP_PATH"] == "/staff/"


# refusals and edits


def test_existing_files_need_force(project: Path) -> None:
    before = (project / deploy.COMPOSE_FILE).read_text()
    result = make("compose", "--no-celery")
    assert result.exit_code != 0
    assert "C101" in str(result.exception) or "C101" in result.output
    assert (project / deploy.COMPOSE_FILE).read_text() == before


def test_dry_run_writes_nothing(project: Path) -> None:
    before = (project / deploy.COMPOSE_FILE).read_text()
    result = make("compose", "--force", "--no-celery", "--dry-run")
    assert result.exit_code == 0, result.output
    assert "would modify docker-compose.prod.yml" in result.output
    assert (project / deploy.COMPOSE_FILE).read_text() == before


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["kubernetes"], "Unknown deploy target"),
        (["compose", "--app-path", "/app/x y/"], "is not a URL path"),
        (["compose", "--app-path", "/static/"], "already serves"),
        (["compose", "--app-path", "/x/", "--app-domain", "app.example.com"], "exclude each other"),
        (["compose", "--app-domain", "https://app.example.com"], "is not a host name"),
        (["compose", "--domain", "example.com:8443"], "is not a host name"),
    ],
)
def test_invalid_options(project: Path, args: list[str], message: str) -> None:
    result = make(*args, "--force")
    assert result.exit_code != 0
    text = str(result.exception) + result.output
    assert message in text and "C106" in text


def test_an_older_dockerfile_is_named_with_the_fix(project: Path) -> None:
    dockerfile = project / "Dockerfile"
    text = dockerfile.read_text()
    dockerfile.write_text(text.split("# Backups:", 1)[0])
    result = make("compose", "--force")
    assert result.exit_code != 0
    message = str(result.exception) + result.output
    assert "no backup target" in message and "C105" in message
    assert make("compose", "--force", "--no-backups").exit_code == 0


def test_an_existing_project_gets_env_prod_ignored(project: Path) -> None:
    for name in (".gitignore", ".dockerignore"):
        path = project / name
        path.write_text("\n".join(l for l in path.read_text().splitlines() if l != ".env.prod"))
    result = make("compose", "--force")
    assert result.exit_code == 0, result.output
    for name in (".gitignore", ".dockerignore"):
        assert (project / name).read_text().splitlines().count(".env.prod") == 1


# the CI job that boots it


def _smoke() -> ModuleType:
    path = REPO_ROOT / ".github" / "ci" / "prod_smoke.py"
    spec = importlib.util.spec_from_file_location("prod_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


def test_the_ci_job_boots_this_stack_without_secrets() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = yaml.safe_load(text)["jobs"]["production-stack"]
    assert job["name"] == "Production stack (compose, smoke)"
    assert job["timeout-minutes"] <= 20
    body = yaml.safe_dump(job)
    assert "secrets." not in body.replace("import secrets; print(secrets.", "")
    assert "${{ secrets" not in text.split("production-stack:", 1)[1].split("\n  ui:", 1)[0]
    builds = [step["with"] for step in job["steps"] if "build-push-action" in step.get("uses", "")]
    stack = deploy.compose(deploy.Options(slug="prod_smoke"))
    for build in builds:
        assert build["target"] in deploy.dockerfile_targets(
            (TEMPLATE / "{{cookiecutter.project_slug}}" / "Dockerfile").read_text()
        )
        assert "type=gha" in build["cache-from"]
        name = "prod_smoke" if build["target"] == "prod" else "prod_smoke-backup"
        assert build["tags"] == f"{name}:latest"
        assert (
            f"${{KARNI_IMAGE:-prod_smoke}}{name[len('prod_smoke') :]}:${{KARNI_TAG:-latest}}"
            in stack
        )
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    # The deploy gate refuses a stack whose email goes nowhere (karni.W520).
    assert "--set EMAIL_URL=" in runs and "--set DEFAULT_FROM_EMAIL=" in runs
    for needed in (
        '"$SMOKE" env',
        '"$SMOKE" wait',
        '"$SMOKE" check',
        "karni new",
        "--app-path /app/",
    ):
        assert needed in runs, needed
    assert '"Prod Smoke"' in runs


def test_the_smoke_helpers() -> None:
    smoke = _smoke()
    example = "SECRET_KEY=\nPOSTGRES_PASSWORD=\nDATABASE_URL=postgres://karni:<POSTGRES_PASSWORD>@db/karni\nDOMAIN=localhost\n# KARNI_SRC=\n"
    filled = smoke.fill_env(example, {"KARNI_SRC": ".karni-src"})
    values = dict(
        line.split("=", 1)
        for line in filled.splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert len(values["SECRET_KEY"]) >= 50
    assert values["DATABASE_URL"] == f"postgres://karni:{values['POSTGRES_PASSWORD']}@db/karni"
    assert values["KARNI_SRC"] == ".karni-src"
    with pytest.raises(SystemExit):
        smoke.fill_env("EMAIL_HOST=\n", {})

    def state(service: str, running: str, health: str = "", code: int = 0) -> dict[str, object]:
        return {"Service": service, "State": running, "Health": health, "ExitCode": code}

    one_shot = {"release"}
    ready = [state("release", "exited"), state("django", "running", "healthy")]
    assert smoke.stack_state(ready, one_shot)[0] == "ready"
    assert smoke.stack_state([state("django", "running", "starting")], one_shot)[0] == "waiting"
    assert smoke.stack_state([state("release", "exited", code=1)], one_shot)[0] == "failed"
    assert smoke.stack_state([state("django", "running", "unhealthy")], one_shot)[0] == "failed"
    assert smoke.stack_state([state("redis", "running")], one_shot)[0] == "failed"
    lines = '{"Service": "db", "State": "running", "Health": "healthy"}\n{"Service": "release", "State": "exited", "ExitCode": 0}\n'
    assert [s["Service"] for s in smoke.compose_states(lines)] == ["db", "release"]
    assert smoke.compose_states('[{"Service": "db"}]') == [{"Service": "db"}]


def test_a_project_without_the_probe_urls_keeps_asking_health(project: Path) -> None:
    """``karni make deploy compose`` in an older project: ``/readyz`` would be a 404 there."""
    urls = project / "config" / "urls.py"
    urls.write_text(urls.read_text().replace("karni.health.probe_urls", "karni.health.urls"))
    result = make("compose", "--force")
    assert result.exit_code == 0, result.output
    django = load(project)["services"]["django"]
    assert django["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-m",
        "karni.deploy.healthcheck",
        "--quiet",
    ]


def test_the_ci_job_migrates_seeds_and_runs_the_smoke_and_the_browser_test() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    steps = yaml.safe_load(text)["jobs"]["production-stack"]["steps"]
    runs = [step.get("run", "") for step in steps]
    order = [
        next(i for i, run in enumerate(runs) if needle in run)
        for needle in ("manage.py migrate --noinput", "karni_seed --force", '"$SMOKE" check')
    ]
    assert order == sorted(order), "migrate, then seed, then the smoke script"
    smoke = next(run for run in runs if '"$SMOKE" check' in run)
    for needed in ("--worker-check", "--user", "--api-version v1", "--deprecated-version v0"):
        assert needed in smoke, needed
    playwright = next(step for step in steps if step.get("run") == "npx playwright test")
    assert playwright["working-directory"] == ".github/ci/prod_e2e"
    assert playwright["env"]["E2E_BASE_URL"] == "https://localhost/app/"
    for name in ("signin.spec.ts", "playwright.config.ts", "package.json"):
        assert (REPO_ROOT / ".github" / "ci" / "prod_e2e" / name).is_file()
    assert "karni make model Product" in "\n".join(runs)


class _Stack(BaseHTTPRequestHandler):
    """A stand-in for the stack's HTTP surface: what the smoke script reads."""

    deprecated = True

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        raw = body if isinstance(body, str) else json.dumps(body)
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw.encode())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        sent = json.loads(self.rfile.read(length) or b"{}")
        ok = self.path == "/api/auth/login/" and sent.get("password") == "pw"
        self._send(200 if ok else 401, {"access": "token"} if ok else {})

    def do_GET(self) -> None:
        signed_in = self.headers.get("Authorization") == "Bearer token"
        path = self.path
        if path in ("/readyz", "/health/ready/"):
            checks = {"database": {"ok": True}, "cache": {"ok": True}, "broker": {"ok": True}}
            checks["celery"] = {"ok": True}
            self._send(200, {"status": "ok", "failing": [], "checks": checks})
        elif path == "/healthz":
            self._send(200, {"status": "ok"})
        elif path.startswith("/api/") and path.endswith("/things/"):
            if not signed_in:
                self._send(401, {})
                return
            marked = {"Deprecation": "@1780272000"} if path.startswith("/api/v0/") else {}
            self._send(200, {"results": [{"id": 1}]}, marked)
        elif path == "/":
            self._send(200, "<title>Home</title>")
        elif path == "/admin/login/":
            self._send(200, '<input name="csrfmiddlewaretoken">')
        elif path == "/app/":
            self._send(200, '<div id="root"></div><script src="/app/a.js"></script>')
        elif path == "/app/a.js":
            self._send(200, "x", {"Content-Type": "text/javascript"})
        elif path == "/app/some/deep/link":
            self._send(200, '<div id="root"></div>')
        else:
            self._send(404, "")


def _run_smoke(*extra: str) -> tuple[int, str]:
    import contextlib
    import io

    server = HTTPServer(("127.0.0.1", 0), _Stack)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = _smoke().main(
                [
                    "check",
                    "--base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--admin-path",
                    "admin/",
                    "--no-headers",
                    "--no-static",
                    "--app-path",
                    "/app/",
                    "--wait",
                    "5",
                    *extra,
                ]
            )
    finally:
        server.shutdown()
    return code, out.getvalue()


def test_the_smoke_script_signs_in_reads_a_list_and_checks_the_versions() -> None:
    code, output = _run_smoke(
        "--user", "a@example.com", "--password", "pw", "--list-path", "/api/things/",
        "--api-version", "v1", "--deprecated-version", "v0", "--worker-check",
        "--expect-check", "broker",
    )  # fmt: skip
    assert code == 0, output
    for line in (
        "ok   /readyz reports every check ok",
        "ok   /readyz runs the broker check",
        "ok   /healthz answers",
        "ok   a Celery worker answers /health/ready/",
        "ok   sign in as a@example.com",
        "ok   /api/things/ refuses anonymous",
        "ok   /api/v1/things/ lists at least 1 row(s)",
        "ok   /api/v0/things/ answers with a Deprecation header",
        "ok   /api/v1/things/ is not deprecated",
        "ok   staff app /app/",
    ):
        assert line in output, line


def test_the_smoke_script_fails_on_a_wrong_password_and_a_missing_deprecation() -> None:
    code, output = _run_smoke("--user", "a@example.com", "--password", "nope")
    assert code == 1 and "FAIL sign in as a@example.com" in output
    code, output = _run_smoke(
        "--user", "a@example.com", "--password", "pw", "--list-path", "/api/things/",
        "--deprecated-version", "v1",
    )  # fmt: skip
    assert code == 1
    assert "FAIL /api/v1/things/ answers with a Deprecation header" in output
