"""The deployment files: the Blueprint at the repository root, the Dockerfile, the README button.

The Blueprint's environment is checked the way the host starts the image: its
values, a generated SECRET_KEY, and the service's own address where Render
fills it in, then ``karni check --deploy`` (the image's deploy gate) must pass.
Outside the Karni repository (no render.yaml two folders up) these tests skip.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]
BLUEPRINT = REPO / "render.yaml"
HOST = "karni-shop-demo.onrender.com"
RENDER = {"RENDER_EXTERNAL_HOSTNAME": HOST, "RENDER_EXTERNAL_URL": f"https://{HOST}"}

pytestmark = pytest.mark.skipif(not BLUEPRINT.is_file(), reason="not in the Karni repository")


def service() -> dict[str, Any]:
    services = yaml.safe_load(BLUEPRINT.read_text())["services"]
    found = [s for s in services if s["name"] == "karni-shop-demo"]
    assert len(found) == 1
    return dict(found[0])


def blueprint_environment(tmp_path: Path) -> dict[str, str]:
    """The variables the service starts with, as Render would set them."""
    found: dict[str, str] = {}
    for variable in service()["envVars"]:
        if "value" in variable:
            found[variable["key"]] = str(variable["value"])
        elif variable.get("generateValue"):  # "a base64-encoded 256-bit value"
            found[variable["key"]] = base64.b64encode(secrets.token_bytes(32)).decode()
        else:
            source = variable["fromService"]
            assert source["name"] == "karni-shop-demo", "only the service's own address"
            found[variable["key"]] = RENDER[source["envVarKey"]]
    # The instance's /data, here in tmp_path.
    assert found["DATABASE_URL"] == "sqlite:////data/db.sqlite3"
    found["DATABASE_URL"] = f"sqlite:///{tmp_path / 'db.sqlite3'}"
    found["CACHE_URL"] = f"filecache://{tmp_path / 'cache'}"
    return found


def test_the_blueprint_is_one_free_docker_service_built_from_this_project() -> None:
    web = service()
    assert (web["type"], web["runtime"], web["plan"]) == ("web", "docker", "free")
    assert (REPO / web["dockerfilePath"]).resolve() == PROJECT / "Dockerfile"
    assert (REPO / web["dockerContext"]).resolve() == PROJECT
    assert web["healthCheckPath"] == "/healthz"
    assert web["autoDeployTrigger"] == "off"
    keys = {variable["key"]: variable for variable in web["envVars"]}
    assert keys["SECRET_KEY"] == {"key": "SECRET_KEY", "generateValue": True}
    assert keys["SECRET_KEY_PART_2"] == {"key": "SECRET_KEY_PART_2", "generateValue": True}
    assert keys["DEMO_MODE"]["value"] == "True"
    assert "DEBUG" not in keys  # production's default: off


def test_the_blueprint_environment_passes_the_deploy_gate(tmp_path: Path) -> None:
    env = {**os.environ, **blueprint_environment(tmp_path)}
    env.pop("DEBUG", None)
    gate = subprocess.run(
        [sys.executable, "manage.py", "karni_check", "--deploy"],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr

    shown = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            "from django.conf import settings as s; "
            "print(s.DEBUG, s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, "
            "s.KARNI_ACCOUNTS_REGISTRATION, s.CACHES['default']['BACKEND'])",
        ],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.strip().splitlines()[-1] == (
        f"False ['{HOST}'] ['https://{HOST}'] False "
        "django.core.cache.backends.filebased.FileBasedCache"
    )


def test_the_dockerfile_serves_the_start_command_from_its_last_stage() -> None:
    dockerfile = (PROJECT / "Dockerfile").read_text()
    stages = re.findall(r"^FROM \S+ AS (\S+)$", dockerfile, flags=re.MULTILINE)
    assert stages[-1] == "prod"  # the host builds without --target
    last = dockerfile[dockerfile.rindex("FROM python:3.12-slim AS prod") :]
    assert 'ENTRYPOINT ["python", "-m", "karni.deploy.entrypoint"]' in last
    assert 'CMD ["sh", "scripts/start.sh"]' in last
    assert "ARG KARNI_APP_PATH=/\n" in dockerfile
    start = (PROJECT / "scripts" / "start.sh").read_text()
    assert "python manage.py demo_boot" in start and "exec gunicorn" in start


def test_the_image_installs_released_packages() -> None:
    pyproject = (PROJECT / "pyproject.toml").read_text()
    assert '"karni>=0.5,<0.6"' in pyproject and '"karni-payments>=0.5,<0.6"' in pyproject
    package = (PROJECT / "frontend" / "package.json").read_text()
    assert '"@karni/ui": "^' in package and "file:" not in package


def test_the_readme_has_the_deploy_button_and_the_live_demo_link() -> None:
    readme = (REPO / "README.md").read_text()
    assert "https://render.com/deploy?repo=https://github.com/cbsshekhawat18-lab/karni" in readme
    assert "https://render.com/images/deploy-to-render-button.svg" in readme
    assert readme.count('<a href="https://karni-shop-demo.onrender.com/">Live demo</a>') == 1
