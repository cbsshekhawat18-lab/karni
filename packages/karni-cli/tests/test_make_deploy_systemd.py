"""``karni make deploy systemd-nginx``: one Linux server without Docker.

The files are checked as text, and ``deploy/deploy.sh`` is run for real against a
folder that stands in for the server: its root, systemd's and nginx's folders are
temporary, and ``nginx``, ``systemctl``, ``curl``, ``date`` and ``python3`` are small
stand-ins on ``PATH`` that log what they were asked. So the deploy, its idempotence,
the vhost that ``nginx -t`` refuses, the health check, pruning and the rollback are
exercised without a server. ``shellcheck`` checks the script where it is installed.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from karni_cli.generators import systemd_nginx
from karni_cli.main import app

from .conftest import TEMPLATE

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash on PATH")

SCRIPT = systemd_nginx.SCRIPT


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One site project for the module (`karni new` takes a while), copied by each test."""
    where = tmp_path_factory.mktemp("made")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("KARNI_TEMPLATES", str(TEMPLATE))
        result = CliRunner().invoke(
            app,
            [
                "new",
                "Clinic Hours",
                "--kind",
                "site",
                "--no-staff-app",
                "--no-git",
                "-o",
                str(where),
            ],
        )
    assert result.exit_code == 0, result.output
    return where / "clinic_hours"


@pytest.fixture
def project(made: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "clinic_hours"
    shutil.copytree(made, root, symlinks=True)
    monkeypatch.chdir(root)
    return root


def make(*args: str) -> Result:
    return CliRunner().invoke(app, ["make", "deploy", "systemd-nginx", *args])


def said(result: Result) -> str:
    """What a run printed, with the error a refused run raised (C1xx)."""
    return f"{result.output}{result.exception or ''}"


# the files


def test_it_writes_the_deploy_folder(project: Path) -> None:
    result = make("--domain", "clinic.example.com")
    assert result.exit_code == 0, result.output
    folder = project / "deploy"
    names = {path.name for path in folder.iterdir()}
    assert names == {
        "deploy.sh",
        "web.service",
        "worker.service",
        "beat.service",
        "nginx.conf",
        "env.example",
        "README.md",
    }
    script = folder / "deploy.sh"
    assert script.stat().st_mode & stat.S_IXUSR, "deploy.sh is executable"
    text = script.read_text()
    assert 'APP="${DEPLOY_APP:-clinic_hours}"' in text
    assert 'DOMAIN="${DEPLOY_DOMAIN:-clinic.example.com}"' in text
    assert 'ROOT="${DEPLOY_ROOT:-/srv/clinic_hours}"' in text
    assert 'UNITS="${DEPLOY_UNITS:-web worker beat}"' in text
    assert '  manage "$rel" karni_site_seed\n' in text, "a site renders its pages once"
    assert "/etc/letsencrypt/live/clinic.example.com/fullchain.pem" in text
    for path in folder.iterdir():
        assert "{{" not in path.read_text(), f"{path.name} keeps a generator token"
    web = (folder / "web.service").read_text()
    assert "EnvironmentFile=@ROOT@/shared/.env" in web
    assert "--bind unix:/run/@APP@/gunicorn.sock" in web
    assert "ReadWritePaths=@ROOT@/shared/media" in web
    vhost = (folder / "nginx.conf").read_text()
    assert "server unix:/run/@APP@/gunicorn.sock" in vhost
    assert "alias @ROOT@/shared/static/;" in vhost
    assert vhost.count("{") == vhost.count("}")
    env = (folder / "env.example").read_text()
    for line in (
        "DJANGO_ENV=prod",
        "ALLOWED_HOSTS=clinic.example.com",
        "CSRF_TRUSTED_ORIGINS=https://clinic.example.com",
        "SECRET_KEY=",
        "KARNI_ADMIN_PATH=",
        "MEDIA_ROOT=/srv/clinic_hours/shared/media",
        "STATIC_ROOT=/srv/clinic_hours/shared/static",
        "REDIS_URL=redis://127.0.0.1:6379/0",
    ):
        assert f"\n{line}\n" in env, line
    assert "\nKARNI_SITE_URL=https://clinic.example.com\n" in env, "a site's address"
    assert "\n# KARNI_SITE_ALLOW_INDEXING=False\n" in env
    readme = (folder / "README.md").read_text()
    assert "sudo deploy/deploy.sh --rollback" in readme
    assert "createdb --owner clinic_hours clinic_hours" in readme


def test_no_celery_writes_the_web_unit_only(project: Path) -> None:
    result = make("--no-celery", "--root", "/opt/clinic/", "--user", "clinic", "--keep", "3")
    assert result.exit_code == 0, result.output
    folder = project / "deploy"
    assert not (folder / "worker.service").exists()
    assert not (folder / "beat.service").exists()
    text = (folder / "deploy.sh").read_text()
    assert 'UNITS="${DEPLOY_UNITS:-web}"' in text
    assert 'ROOT="${DEPLOY_ROOT:-/opt/clinic}"' in text
    assert 'RUN_AS="${DEPLOY_RUN_AS:-clinic}"' in text
    assert 'KEEP="${DEPLOY_KEEP:-3}"' in text
    env = (folder / "env.example").read_text()
    assert (
        "KARNI_HEALTH_CHECKS=karni.health.checks.check_database,karni.health.checks.check_cache"
        in env
    )


def test_single_process_runs_one_gunicorn_worker_without_redis(project: Path) -> None:
    assert make().exit_code == 0
    result = make("--single-process", "--force")
    assert result.exit_code == 0, result.output
    assert "worker.service and deploy/beat.service are not used any more" in result.output
    folder = project / "deploy"
    assert 'UNITS="${DEPLOY_UNITS:-web}"' in (folder / "deploy.sh").read_text()
    web = (folder / "web.service").read_text()
    assert "gunicorn config.wsgi:application" in web
    assert "--workers 1 --worker-class gthread --threads 4" in web
    assert "Environment=WEB_CONCURRENCY=1" in web
    env = (folder / "env.example").read_text()
    assert "\nKARNI_SINGLE_PROCESS=True\nWEB_CONCURRENCY=1\n" in env
    assert "REDIS_URL" not in env and "KARNI_HEALTH_CHECKS" not in env
    readme = (folder / "README.md").read_text()
    assert "redis-server" not in readme and "no Redis" in readme


def test_a_dry_run_writes_nothing(project: Path) -> None:
    result = make("--dry-run")
    assert result.exit_code == 0, result.output
    assert "would create deploy/deploy.sh" in result.output
    assert not (project / "deploy").exists()


def test_it_refuses_to_overwrite_without_force(project: Path) -> None:
    assert make().exit_code == 0
    (project / "deploy" / "nginx.conf").write_text("# mine\n")
    again = make()
    assert again.exit_code != 0
    assert "C101" in said(again)
    assert (project / "deploy" / "nginx.conf").read_text() == "# mine\n"
    assert make("--force").exit_code == 0
    assert "upstream" in (project / "deploy" / "nginx.conf").read_text()


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (["--user", "Bad User"], "--user"),
        (["--root", "relative/path"], "--root"),
        (["--root", "/"], "--root"),
        (["--cert", "/etc/ssl/a cert.pem"], "--cert"),
        (["--keep", "1"], "--keep"),
        (["--no-backups"], "--no-backups"),
        (["--app-path", "/staff/"], "--app-path"),
    ],
)
def test_it_refuses_values_that_do_not_fit(project: Path, args: list[str], named: str) -> None:
    result = make(*args)
    assert result.exit_code != 0
    assert "C106" in said(result)
    assert named in said(result)
    assert not (project / "deploy").exists()


def test_compose_refuses_the_server_flags(project: Path) -> None:
    result = CliRunner().invoke(app, ["make", "deploy", "compose", "--root", "/srv/x"])
    assert result.exit_code != 0
    assert "C106" in said(result)
    assert "systemd-nginx" in said(result)
    single = CliRunner().invoke(app, ["make", "deploy", "compose", "--single-process"])
    assert single.exit_code != 0 and "--single-process" in said(single)


# the script, against a stand-in server


@dataclass
class Server:
    project: Path
    root: Path
    systemd: Path
    nginx: Path
    log: Path
    env: dict[str, str]

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.project / SCRIPT), *args],
            cwd=self.project,
            env={**self.env, **extra},
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def clear(self) -> None:
        self.log.write_text("")

    def current(self) -> str:
        return os.readlink(self.root / "current").rsplit("/", 1)[-1]

    def releases(self) -> list[str]:
        return sorted(path.name for path in (self.root / "releases").iterdir())


_FAKES = {
    "nginx": """#!/bin/sh
echo "nginx $*" >> "$FAKE_LOG"
if [ "$1" = "-t" ] && [ -n "${FAKE_NGINX_FAIL_ON:-}" ]; then
  if cat "$DEPLOY_NGINX_DIR"/sites-enabled/* 2>/dev/null | grep -q "$FAKE_NGINX_FAIL_ON"; then
    echo "nginx: [emerg] unknown directive" >&2
    exit 1
  fi
fi
exit 0
""",
    "systemctl": """#!/bin/sh
echo "systemctl $*" >> "$FAKE_LOG"
""",
    "journalctl": """#!/bin/sh
echo "journalctl $*" >> "$FAKE_LOG"
""",
    "curl": """#!/bin/sh
echo "curl $*" >> "$FAKE_LOG"
printf '%s' "${FAKE_HTTP_CODE:-200}"
""",
    # Each call one second later than the last, so releases never share an id.
    "date": """#!/bin/sh
n=$(cat "$FAKE_CLOCK" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$FAKE_CLOCK"
printf '202611190900%02d\\n' "$n"
""",
    # python3: a venv is a folder holding this script, pip and manage.py are logged, and
    # anything else (the copy, the atomic switch) is the real interpreter.
    "python": """#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then mkdir -p "$3/bin"; cp "$0" "$3/bin/python"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then echo "pip $*" >> "$FAKE_LOG"; exit 0; fi
if [ "$1" = "manage.py" ]; then
  echo "manage $2 in $(basename "$(pwd)")" >> "$FAKE_LOG"
  [ "$2" = "${FAKE_MANAGE_FAIL:-}" ] && exit 1
  exit 0
fi
exec "$REAL_PYTHON" "$@"
""",
}


@pytest.fixture
def server(project: Path, tmp_path: Path) -> Server:
    assert make("--domain", "clinic.example.com").exit_code == 0
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in _FAKES.items():
        path = bin_dir / name
        path.write_text(text)
        path.chmod(0o755)
    place = tmp_path / "server"
    (place / "certs").mkdir(parents=True)
    (place / "certs" / "fullchain.pem").write_text("certificate\n")
    (place / "certs" / "privkey.pem").write_text("key\n")
    log = place / "calls.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "FAKE_LOG": str(log),
        "FAKE_CLOCK": str(place / "clock"),
        "REAL_PYTHON": sys.executable,
        "DEPLOY_ROOT": str(place / "srv"),
        "DEPLOY_SYSTEMD_DIR": str(place / "systemd"),
        "DEPLOY_NGINX_DIR": str(place / "nginx"),
        "DEPLOY_CERT": str(place / "certs" / "fullchain.pem"),
        "DEPLOY_CERT_KEY": str(place / "certs" / "privkey.pem"),
        "DEPLOY_PYTHON": str(bin_dir / "python"),
        "DEPLOY_HEALTH_TRIES": "2",
    }
    return Server(project, place / "srv", place / "systemd", place / "nginx", log, env)


def first_deploy(server: Server) -> None:
    """The first run writes the .env and stops. The second one deploys."""
    first = server.run()
    assert first.returncode == 1
    assert "wrote" in first.stderr and "shared/.env" in first.stderr
    env_file = server.root / "shared" / ".env"
    assert env_file.read_text() == (server.project / "deploy" / "env.example").read_text()
    env_file.write_text("SECRET_KEY=filled-in-on-the-server\n")
    deployed = server.run()
    assert deployed.returncode == 0, deployed.stderr + deployed.stdout


def test_a_deploy_installs_the_release_the_units_and_the_vhost(server: Server) -> None:
    first_deploy(server)
    release = server.current()
    folder = server.root / "releases" / release
    assert (folder / "manage.py").is_file()
    assert os.readlink(folder / ".env") == str(server.root / "shared" / ".env")
    assert (folder / ".built").is_file() and (folder / ".live").is_file()
    for skipped in (".env.example", ".env.prod.example", "data"):
        assert not (folder / skipped).exists(), skipped
    assert (server.root / "shared" / ".env").read_text() == "SECRET_KEY=filled-in-on-the-server\n"
    for unit in ("web", "worker", "beat"):
        text = (server.systemd / f"clinic_hours-{unit}.service").read_text()
        assert "@" not in text.replace("$MAINPID", ""), unit
        assert f"WorkingDirectory={server.root}/current" in text
    vhost = server.nginx / "sites-available" / "clinic_hours.conf"
    assert "@" not in vhost.read_text()
    assert str(server.root / "shared" / "static") in vhost.read_text()
    enabled = server.nginx / "sites-enabled" / "clinic_hours.conf"
    assert enabled.is_symlink() and os.readlink(enabled) == str(vhost)
    calls = server.calls()
    managed = [call for call in calls if call.startswith("manage ")]
    assert managed == [
        f"manage karni_check in {release}",
        f"manage migrate in {release}",
        f"manage collectstatic in {release}",
        f"manage karni_site_seed in {release}",
    ]
    assert "systemctl daemon-reload" in calls
    assert "systemctl restart clinic_hours-web.service" in calls
    assert any("--unix-socket /run/clinic_hours/gunicorn.sock" in call for call in calls)
    # nginx is tested before anything changes and again before its reload.
    tests = [i for i, call in enumerate(calls) if call == "nginx -t"]
    reload = calls.index("systemctl reload nginx")
    assert len(tests) >= 2 and tests[-1] < reload


def test_running_it_again_changes_only_the_release(server: Server) -> None:
    first_deploy(server)
    before = server.current()
    server.clear()
    again = server.run()
    assert again.returncode == 0, again.stderr
    assert server.current() != before
    calls = server.calls()
    assert "systemctl daemon-reload" not in calls, "the units did not change"
    assert "systemctl reload nginx" not in calls, "the vhost did not change"
    assert "nginx: the vhost is unchanged" in again.stdout


def test_it_keeps_the_newest_releases(server: Server) -> None:
    first_deploy(server)
    for _ in range(3):
        assert server.run(DEPLOY_KEEP="2").returncode == 0
    assert len(server.releases()) == 2
    assert server.current() == server.releases()[-1]


def test_rollback_switches_back_and_runs_no_migration(server: Server) -> None:
    first_deploy(server)
    older = server.current()
    assert server.run().returncode == 0
    newer = server.current()
    server.clear()
    back = server.run("--rollback")
    assert back.returncode == 0, back.stderr
    assert server.current() == older
    managed = [call for call in server.calls() if call.startswith("manage ")]
    assert managed == [f"manage collectstatic in {older}"]
    assert "systemctl restart clinic_hours-web.service" in server.calls()
    listed = server.run("--list").stdout
    assert f"* {older} (current)" in listed
    assert f"  {newer}" in listed
    forward = server.run("--rollback", newer)
    assert forward.returncode == 0, forward.stderr
    assert server.current() == newer
    missing = server.run("--rollback", "20990101000000")
    assert missing.returncode == 1
    assert "no release 20990101000000" in missing.stderr


def test_a_vhost_nginx_refuses_puts_the_previous_one_back(server: Server) -> None:
    first_deploy(server)
    vhost = server.nginx / "sites-available" / "clinic_hours.conf"
    working = vhost.read_text()
    source = server.project / "deploy" / "nginx.conf"
    source.write_text(source.read_text() + "broken_directive on;\n")
    server.clear()
    result = server.run(FAKE_NGINX_FAIL_ON="broken_directive")
    assert result.returncode == 1
    assert "the previous vhost is back in place" in result.stderr
    assert "nginx -t passes again" in result.stderr
    assert vhost.read_text() == working
    assert (server.nginx / "sites-enabled" / "clinic_hours.conf").is_symlink()
    assert "systemctl reload nginx" not in server.calls()


def test_a_first_vhost_nginx_refuses_is_unhooked(server: Server) -> None:
    source = server.project / "deploy" / "nginx.conf"
    source.write_text(source.read_text() + "broken_directive on;\n")
    first = server.run()
    assert first.returncode == 1
    (server.root / "shared" / ".env").write_text("SECRET_KEY=x\n")
    result = server.run(FAKE_NGINX_FAIL_ON="broken_directive")
    assert result.returncode == 1
    assert "the vhost is unhooked" in result.stderr
    assert not (server.nginx / "sites-enabled" / "clinic_hours.conf").exists()
    assert "systemctl reload nginx" not in server.calls()


def test_a_broken_nginx_stops_the_deploy_before_anything_changes(server: Server) -> None:
    first_deploy(server)
    before = server.releases()
    other = server.nginx / "sites-enabled" / "another-site.conf"
    other.write_text("broken_directive on;\n")
    result = server.run(FAKE_NGINX_FAIL_ON="broken_directive")
    assert result.returncode == 1
    assert "nginx -t fails before this deploy changed anything" in result.stderr
    assert server.releases() == before
    assert other.read_text() == "broken_directive on;\n"


def test_a_release_that_does_not_answer_stops_before_nginx(server: Server) -> None:
    first_deploy(server)
    good = server.current()
    server.clear()
    result = server.run(FAKE_HTTP_CODE="502")
    assert result.returncode == 1
    assert "did not answer /readyz with 200 (last answer: 502)" in result.stderr
    assert f"--rollback switches back to {good}" in result.stderr
    assert server.calls().count("nginx -t") == 1, "only the test before anything changed"
    assert "systemctl reload nginx" not in server.calls()
    assert "journalctl -u clinic_hours-web.service -n 40 --no-pager" in server.calls()
    assert server.run("--rollback").returncode == 0
    assert server.current() == good
    assert "never answered" in server.run("--list").stdout


def test_a_failing_check_keeps_the_running_release(server: Server) -> None:
    first_deploy(server)
    good = server.current()
    result = server.run(FAKE_MANAGE_FAIL="migrate")
    assert result.returncode == 1
    assert server.current() == good
    assert server.run().returncode == 0, "the next run removes the half-built release"
    assert all((server.root / "releases" / name / ".built").is_file() for name in server.releases())


def test_two_runs_at_once_are_refused(server: Server) -> None:
    first_deploy(server)
    (server.root / ".deploy.lock").mkdir()
    result = server.run()
    assert result.returncode == 1
    assert "another deploy.sh runs" in result.stderr


def test_list_and_help_need_no_server_tools(server: Server) -> None:
    listed = server.run("--list")
    assert listed.returncode == 0
    assert "No releases" in listed.stdout
    usage = server.run("--help")
    assert usage.returncode == 0
    assert "--rollback" in usage.stdout
    assert server.run("--bogus").returncode == 2


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="needs shellcheck on PATH")
def test_shellcheck_passes(project: Path) -> None:
    assert make().exit_code == 0
    result = subprocess.run(
        ["shellcheck", "-s", "bash", str(project / SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
